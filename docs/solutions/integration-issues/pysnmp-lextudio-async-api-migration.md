---
title: "pysnmp-lextudio 6.x 异步 API 迁移问题"
date: 2026-01-05
category: integration-issues
severity: high
components:
  - SNMP Scanner
  - pysnmp-lextudio
  - asyncio
tags:
  - SNMP
  - asyncio
  - API migration
  - pysnmp-lextudio 6.x
  - coroutine
status: solved
---

# SNMP 扫描器异步 API 迁移

## 问题症状

**错误表现**:
1. SNMP 扫描时报错: `'coroutine' object is not iterable`
2. 扫描进度卡在 50%，然后直接跳到 100% 显示失败
3. 无法解析 varBind: `'list' object has no attribute 'getValue'`
4. 数据库约束错误: `NOT NULL constraint failed: ipam_networkdevice.last_scan_error`

**错误日志**:
```python
TypeError: 'coroutine' object is not iterable
AttributeError: 'list' object has no attribute 'getValue'
IntegrityError: NOT NULL constraint failed: ipam_networkdevice.last_scan_error
```

## 根本原因

### pysnmp-lextudio 版本升级破坏性变更

**pysnmp-lextudio 6.x 的重大变更**:
1. **完全异步化**: 从同步 API 改为异步 API
2. **导入路径变更**: 从 `pysnmp.hlapi` 改为 `pysnmp.hlapi.asyncio`
3. **varBind 结构变更**: 返回的数据结构与旧版不同

### 代码问题分析

**原始代码** (同步方式):
```python
# ❌ 错误：使用同步 API
from pysnmp.hlapi import nextCmd

for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(...):
    # nextCmd 在 6.x 中返回 coroutine，不能直接迭代
    pass
```

**问题**:
- `nextCmd()` 在 6.x 中返回 coroutine 对象
- 无法使用 `for` 循环直接迭代
- 需要 `await` 关键字

## 解决方案

### 1. 更新导入语句

```python
# ✅ 正确：使用异步 API
from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    nextCmd,
    isEndOfMib,
    # ... 其他导入
)
```

### 2. 创建异步扫描方法

**文件**: `/opt/ipim/backend/ipam/snmp_scanner.py`

```python
async def _async_scan_arp_table(self) -> List[ArpEntry]:
    """异步扫描设备 ARP 表"""
    entries = []
    auth_data = self._get_auth_data()
    transport = self._get_transport_target()

    try:
        current_oid = ObjectType(ObjectIdentity(ARP_TABLE_OID))
        max_iterations = 10000
        iteration = 0

        while iteration < max_iterations:
            iteration += 1

            # ✅ 使用 await 调用异步函数
            errorIndication, errorStatus, errorIndex, varBinds = await nextCmd(
                self.engine,
                auth_data,
                transport,
                ContextData(),
                current_oid,
            )

            if errorIndication or errorStatus:
                break

            if not varBinds:
                break

            for varBind in varBinds:
                # ✅ 安全获取 OID 和值
                try:
                    if isinstance(varBind, (list, tuple)) and len(varBind) >= 2:
                        oid_obj = varBind[0]
                        value_obj = varBind[1]
                    else:
                        oid_obj = varBind.getName() if hasattr(varBind, 'getName') else varBind[0]
                        value_obj = varBind.getValue() if hasattr(varBind, 'getValue') else varBind[1]

                    oid_str = str(oid_obj)

                    # 检查是否超出 ARP 表范围
                    if not oid_str.startswith(ARP_TABLE_OID):
                        return entries

                    # 解析 MAC 地址
                    if hasattr(value_obj, 'prettyPrint'):
                        raw_value = value_obj.prettyPrint()
                        if raw_value.startswith('0x'):
                            hex_str = raw_value[2:]
                            mac_addr = ":".join(hex_str[i:i+2].upper() for i in range(0, len(hex_str), 2))
                        else:
                            mac_addr = self._format_mac_address(bytes(value_obj))
                    else:
                        mac_addr = self._format_mac_address(bytes(value_obj))

                    # 解析 IP 地址（从 OID 中提取）
                    oid_parts = oid_str.split(".")
                    if len(oid_parts) >= 15:
                        if_index = int(oid_parts[10])
                        ip_addr = ".".join(oid_parts[11:15])

                        entries.append(ArpEntry(
                            ip_address=ip_addr,
                            mac_address=mac_addr,
                            interface_index=if_index,
                            entry_type=3,  # dynamic
                        ))

                    # 更新下一个 OID
                    current_oid = ObjectType(oid_obj)

                except (ValueError, IndexError, TypeError, AttributeError) as e:
                    logger.warning(f"解析 ARP 条目失败: {oid_str} - {e}")
                    continue

    except Exception as e:
        logger.exception(f"SNMP 扫描异常 [{self.device.name}]: {e}")
        raise

    return entries
```

### 3. 创建同步包装器

```python
def scan_arp_table(self) -> List[ArpEntry]:
    """扫描设备 ARP 表（同步包装器）"""
    # ✅ 使用 asyncio.run() 包装异步函数
    return asyncio.run(self._async_scan_arp_table())
```

### 4. 修复数据库约束问题

**文件**: `/opt/ipim/backend/ipam/snmp_scanner.py:285`

```python
# ❌ 错误：设置为 None
self.device.last_scan_error = None

# ✅ 正确：设置为空字符串
self.device.last_scan_error = ""
```

**原因**: `last_scan_error` 字段定义为 `TextField(blank=True)`，允许空字符串但不允许 NULL

## 代码变更

### 受影响文件

1. **`/opt/ipim/backend/ipam/snmp_scanner.py`**:
   - 第 19-33 行: 导入语句更新
   - 第 135-234 行: 新增异步扫描方法
   - 第 236-244 行: 同步包装器
   - 第 285 行: 修复 NULL 约束

2. **`/opt/ipim/requirements.txt`**:
   ```txt
   pysnmp-lextudio==6.2.6
   pyasn1==0.6.0  # 重要：0.6.1 有兼容性问题
   ```

## 测试验证

### 1. 基本功能测试

```bash
# 运行测试脚本
python3 /opt/ipim/test_snmp_scan.py
```

**预期输出**:
```
✓ 创建测试设备: 测试设备 (127.0.0.1)
✓ SNMP 扫描器实例创建成功
  - SNMP 版本: v2c
```

### 2. 真实设备测试

```bash
# 测试锐捷无线控制器
python3 /opt/ipim/test_snmp_scan.py --device-ip 10.75.255.118 --community zhld2018
```

**成功案例**:
```
✓ 系统描述: Ruijie 10G Wireless Switch(WS6512)
✓ 系统名称: R01-MES-WLC
✓ 扫描完成! 耗时: 34.58 秒
```

### 3. Web 界面测试

1. 添加网络设备（设备管理页面）
2. 点击"立即扫描"按钮
3. 观察扫描进度：10% → 30% → 80% → 100%
4. 查看扫描日志和结果

## 预防策略

### 1. 依赖版本锁定

**`requirements.txt`** 中明确版本:
```txt
pysnmp-lextudio==6.2.6  # 不使用 >= 或 ~=
pyasn1==0.6.0           # 锁定在兼容版本
```

### 2. API 版本检测

```python
import pysnmp

# 检查 pysnmp 版本
if not hasattr(pysnmp, '__version__'):
    raise ImportError("无法确定 pysnmp 版本")

version = tuple(map(int, pysnmp.__version__.split('.')[:2]))
if version[0] >= 6:
    # 使用异步 API
    from pysnmp.hlapi.asyncio import nextCmd
else:
    # 使用旧版同步 API
    from pysnmp.hlapi import nextCmd
```

### 3. 添加单元测试

**`/opt/ipim/backend/ipam/tests.py`**:
```python
class SNMPScannerTest(TestCase):
    def test_async_scan_compatibility(self):
        """测试异步扫描 API 兼容性"""
        device = NetworkDevice.objects.create(
            name="测试设备",
            ip_address="127.0.0.1",
            snmp_version="v2c",
            snmp_community="public",
        )

        scanner = SNMPScanner(device)

        # 应该能创建实例而不抛出异常
        self.assertIsNotNone(scanner)

        # 异步方法应该存在
        self.assertTrue(hasattr(scanner, '_async_scan_arp_table'))
```

### 4. 优雅降级

如果 SNMP 扫描失败，不影响其他功能：
```python
try:
    scanner = SNMPScanner(device)
    scanned, updated, conflicts = scanner.scan_and_update()
except Exception as e:
    logger.error(f"SNMP 扫描失败: {e}")
    # 更新设备状态但不中断流程
    device.last_scan_status = "error"
    device.last_scan_error = str(e)[:500]
    device.save()
```

## 常见陷阱

### 1. ❌ 直接迭代 nextCmd

```python
# 错误：6.x 中不能这样做
for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(...):
    pass
```

### 2. ❌ 混用同步和异步 API

```python
# 错误：导入混乱
from pysnmp.hlapi import nextCmd  # 旧版
from pysnmp.hlapi.asyncio import getCmd  # 新版
```

### 3. ❌ 忘记 await

```python
# 错误：忘记 await
varBinds = nextCmd(...)  # 返回 coroutine 对象
```

### 4. ❌ 使用 None 而不是空字符串

```python
# 错误：违反 NOT NULL 约束
device.last_scan_error = None

# 正确
device.last_scan_error = ""
```

## 锐捷设备特殊问题

### 问题：ARP 表为空

测试锐捷 WS6512 无线控制器时，虽然 SNMP 连接成功，但 ARP 表返回 0 条记录。

**可能原因**:
1. 锐捷设备使用私有 OID（不是标准的 `1.3.6.1.2.1.4.22.1.2`）
2. 当前没有无线客户端连接
3. 需要更高级别的 Community 权限

**诊断方法**:
```bash
# 使用 snmpwalk 验证
snmpwalk -v2c -c zhld2018 10.75.255.118 .1.3.6.1.2.1.4
```

**解决建议**:
- 联系锐捷技术支持获取正确的 OID
- 检查是否有活跃的无线客户端
- 尝试不同的 Community 字符串

## 相关资源

### 文档
- [pysnmp-lextudio GitHub](https://github.com/lextudio/pysnmp)
- [pysnmp-lextudio 文档](https://pysnmp.readthedocs.io/)
- [Python asyncio 官方文档](https://docs.python.org/3/library/asyncio.html)

### 测试脚本
- `/opt/ipim/test_snmp_scan.py` - 通用 SNMP 测试
- `/opt/ipim/test_ruijie_snmp.py` - 锐捷设备诊断
- `/opt/ipim/SNMP_TEST_GUIDE.md` - 测试指南

### 相关问题
- pyasn1 0.6.1 兼容性问题
- Docker 容器内 SNMP 网络连通性
- 不同厂商设备的 SNMP OID 差异

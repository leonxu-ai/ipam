# SNMP 扫描测试指南

## 问题修复总结

### 1. IP 释放功能 404 错误
**问题**: 点击释放按钮后显示 HTTP 404 错误

**原因**: API URL 不正确，使用了 `/api/ip-addresses/{id}/release/` 而不是 `/api/ip-addresses/release/`

**修复**: 修改了 `ip_list.html` 中的释放函数，使用正确的 URL 并在请求体中传递 `ip_id`

### 2. 扫描设备进度显示优化
**问题**: 扫描时一直卡在 50%，缺少详细的进度信息

**修复**:
- 添加了详细的扫描阶段提示（连接设备 → 获取 ARP 表 → 更新数据库）
- 增加了实时日志功能，显示扫描的每个步骤
- 改进了进度条，从 10% → 30% → 80% → 100%
- 使用不同颜色标识日志级别（成功/错误/信息/警告）

## 使用测试脚本

我编写了一个独立的测试脚本 `/opt/ipim/test_snmp_scan.py`，可以用来测试 SNMP 扫描功能。

### 基本测试（不需要真实设备）

```bash
python3 /opt/ipim/test_snmp_scan.py
```

这会测试：
- SNMP 扫描器实例创建
- 基本功能是否正常

### 完整测试（需要真实设备）

如果你有支持 SNMP 的网络设备（交换机、路由器等），可以这样测试：

```bash
python3 /opt/ipim/test_snmp_scan.py --device-ip 192.168.1.1 --community public
```

参数说明：
- `--device-ip`: 设备的 IP 地址
- `--community`: SNMP Community 字符串（默认: public）

### 测试包含的内容

1. **基本功能测试**: 验证扫描器能否正常创建
2. **SNMP 连接测试**: 尝试连接真实设备并获取 ARP 表
3. **完整扫描流程测试**: 模拟真实扫描并更新数据库
4. **扫描管理器测试**: 测试批量扫描功能

### 常见问题排查

#### 扫描失败的可能原因：

1. **设备 IP 不可达**
   - 使用 `ping` 命令验证设备是否在线
   ```bash
   ping 192.168.1.1
   ```

2. **SNMP Community 字符串错误**
   - 检查设备的 SNMP 配置
   - 常见的 Community: `public`, `private`

3. **设备未启用 SNMP**
   - 登录设备管理界面
   - 启用 SNMP 服务

4. **防火墙阻止**
   - SNMP 使用 UDP 161 端口
   - 检查防火墙规则：
   ```bash
   # 检查端口是否开放
   ss -ulnp | grep 161
   # 或
   netstat -ulnp | grep 161
   ```

5. **SNMP 版本不匹配**
   - 确认设备支持 SNMPv2c 或 SNMPv3
   - 在 Web 界面添加设备时选择正确的版本

## 在 Web 界面测试

### 1. 添加测试设备

访问 http://localhost:8000/devices/，点击"添加设备"：

- **设备名称**: 测试交换机
- **IP 地址**: 你的设备 IP
- **SNMP 版本**: v2c
- **Community**: public（或你设备的实际值）

### 2. 立即扫描

点击设备列表中的"扫描"按钮，会弹出扫描进度窗口，显示：
- 实时进度条
- 详细日志输出
- 扫描结果统计

### 3. 查看扫描结果

扫描完成后：
- 查看"上次扫描"时间更新
- 检查设备状态（成功/失败）
- 如果失败，查看错误信息

## Docker 环境测试

如果你在 Docker 容器内测试，需要确保容器能访问网络设备：

```bash
# 进入容器
docker exec -it ipam-web bash

# 测试网络连通性
ping 192.168.1.1

# 测试 SNMP
apt-get update && apt-get install -y snmp
snmpwalk -v2c -c public 192.168.1.1 system

# 运行测试脚本
cd /opt/ipim
python3 test_snmp_scan.py --device-ip 192.168.1.1
```

## 日志查看

查看详细的扫描日志：

```bash
# Web 服务日志
docker logs ipam-web -f

# Worker 日志（如果使用批量扫描）
docker logs ipam-worker -f
```

## 推荐的测试步骤

1. **先运行基本测试**
   ```bash
   python3 test_snmp_scan.py
   ```

2. **准备一个测试设备**
   - 找一台支持 SNMP 的交换机或路由器
   - 确认 IP 地址和 Community 字符串
   - 确保网络可达

3. **运行完整测试**
   ```bash
   python3 test_snmp_scan.py --device-ip <设备IP> --community <Community>
   ```

4. **在 Web 界面测试**
   - 添加设备
   - 点击扫描
   - 观察进度和日志

5. **检查结果**
   - IP 管理页面应该显示从 ARP 表获取的 IP-MAC 映射
   - 审计日志应该记录扫描操作

## 技术支持

如果扫描仍然失败：

1. 检查 `/opt/ipim/backend/ipam/snmp_scanner.py:166-231` 的错误日志
2. 确认 pysnmp-lextudio 版本正确（6.x）
3. 验证设备 SNMP 配置是否正确
4. 测试使用命令行工具 `snmpwalk` 是否能连接设备

祝测试顺利！

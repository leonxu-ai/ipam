# 修复审计日志显示、弹窗替换和 SNMP 过滤

## 概述

本计划解决 IPAM 系统的四个关键问题：
1. 审计日志显示代码而非中文描述，子网列显示为 "-"
2. 审计日志详情 API 返回 500 内部服务错误
3. 系统使用原生浏览器弹窗（alert/confirm），需替换为自定义模态框
4. SNMP 扫描结果需过滤，只保留系统中已创建网段的 IP 地址

## 问题分析

### 1. 审计日志显示问题

**根本原因**：
- `AuditLog` 模型有 `subnet` (ForeignKey) 和 `subnet_network` (CharField) 字段
- 但 `services.py` 创建审计日志时**未设置这两个字段**
- 子网信息仅存储在 `details` JSON 中，前端模板无法正确显示

**代码位置**：
- `/opt/ipim/backend/ipam/services.py:89-101` - allocate 记录
- `/opt/ipim/backend/ipam/services.py:219-231` - release 记录
- `/opt/ipim/backend/ipam/services.py:332-344` - conflict 记录

### 2. 审计日志详情 500 错误

**可能原因**：
- 序列化器缺少 `subnet` 和 `subnet_network` 字段
- 当 `subnet=None` 时，尝试访问关联字段会报错

**代码位置**：
- `/opt/ipim/backend/ipam/serializers.py:150-163`

### 3. 浏览器弹窗使用情况

**统计**：
- 19 处使用 `alert()`
- 9 处使用 `confirm()`
- 分布在 8 个模板文件中

### 4. SNMP 扫描过滤

**当前逻辑**：
- 扫描 ARP 表获取所有 IP-MAC 映射
- 仅更新数据库中已存在的 IP
- 未过滤非系统子网的 IP（虽然不会入库，但会计入扫描数量）

**代码位置**：
- `/opt/ipim/backend/ipam/snmp_scanner.py:246-303`

---

## 实现计划

### Phase 1: 修复审计日志子网字段 (30分钟)

#### 1.1 修改 services.py 中的审计日志创建

**文件**: `/opt/ipim/backend/ipam/services.py`

```python
# services.py:89-101 - allocate_ip 方法
AuditLog.objects.create(
    user=user,
    action="allocate",
    subnet=ip.subnet,                    # ✅ 添加外键
    subnet_network=ip.subnet.network,    # ✅ 添加快照
    ip_address=ip.address,
    hostname=hostname,
    mac_address=mac_address,
    details={
        "device_type": device_type,
        "department": department,
        "responsible_person": responsible_person,
    }
)
```

```python
# services.py:219-231 - release_ip 方法
AuditLog.objects.create(
    user=user,
    action="release",
    subnet=ip.subnet,                    # ✅ 添加外键
    subnet_network=ip.subnet.network,    # ✅ 添加快照
    ip_address=ip.address,
    hostname=old_hostname,
    mac_address=old_mac,
    details={
        "device_type": old_device_type,
        "keep_info": keep_info,
    }
)
```

```python
# services.py:332-344 - conflict 检测
AuditLog.objects.create(
    user=None,
    action="conflict_detected",
    subnet=ip.subnet,                    # ✅ 添加外键
    subnet_network=ip.subnet.network,    # ✅ 添加快照
    ip_address=ip.address,
    hostname=ip.hostname,
    mac_address=scanned_mac,
    details={
        "old_mac": ip.mac_address,
        "new_mac": scanned_mac,
        "scan_source": scan_source,
    }
)
```

#### 1.2 添加用户友好的操作描述

**文件**: `/opt/ipim/backend/ipam/models.py`

在 `AuditLog` 模型中添加 `get_display_message()` 方法：

```python
class AuditLog(models.Model):
    # ... 现有字段 ...

    def get_display_message(self) -> str:
        """生成用户友好的操作描述"""
        messages = {
            'allocate': f"分配 IP 地址 {self.ip_address}",
            'release': f"释放 IP 地址 {self.ip_address}",
            'update': f"更新 IP 地址 {self.ip_address} 信息",
            'conflict_detected': f"检测到 IP 地址 {self.ip_address} 的 MAC 冲突",
            'create_subnet': f"创建子网 {self.subnet_network or ''}",
            'update_subnet': f"更新子网 {self.subnet_network or ''} 信息",
            'delete_subnet': f"删除子网 {self.subnet_network or ''}",
            'snmp_scan': f"SNMP 扫描完成",
        }

        base_msg = messages.get(self.action, f"执行操作: {self.get_action_display()}")

        # 添加详细信息
        if self.hostname:
            base_msg += f" (主机名: {self.hostname})"

        return base_msg
```

---

### Phase 2: 修复审计日志详情 API (20分钟)

#### 2.1 更新序列化器

**文件**: `/opt/ipim/backend/ipam/serializers.py`

```python
class AuditLogSerializer(serializers.ModelSerializer):
    """审计日志序列化器"""

    user_username = serializers.CharField(
        source='user.username',
        read_only=True,
        default=''  # ✅ 添加默认值防止 None 报错
    )
    action_display = serializers.CharField(source='get_action_display', read_only=True)
    display_message = serializers.CharField(source='get_display_message', read_only=True)  # ✅ 新增
    subnet_display = serializers.SerializerMethodField()  # ✅ 新增

    class Meta:
        model = AuditLog
        fields = [
            'id', 'timestamp', 'user', 'user_username',
            'action', 'action_display', 'display_message',  # ✅ 添加 display_message
            'ip_address', 'hostname', 'mac_address',
            'subnet', 'subnet_network', 'subnet_display',   # ✅ 添加子网字段
            'details'
        ]
        read_only_fields = '__all__'

    def get_subnet_display(self, obj):
        """安全获取子网显示信息"""
        if obj.subnet:
            return obj.subnet.network
        elif obj.subnet_network:
            return f"{obj.subnet_network} (已删除)"
        elif obj.details and 'subnet' in obj.details:
            return obj.details['subnet']  # 兼容旧数据
        return None
```

#### 2.2 更新前端模板显示

**文件**: `/opt/ipim/backend/templates/ipam/audit_log_list.html`

更新表格行显示逻辑：

```html
<!-- 操作描述列 -->
<td class="px-6 py-4">
    <span class="text-slate-900 dark:text-white">
        {{ log.get_display_message }}
    </span>
</td>

<!-- 子网列 -->
<td class="px-6 py-4">
    {% if log.subnet %}
        <a href="{% url 'ipam:subnet_detail' log.subnet.id %}"
           class="text-blue-600 hover:text-blue-500 dark:text-blue-400">
            {{ log.subnet.network }}
        </a>
    {% elif log.subnet_network %}
        <span class="text-slate-400" title="子网已删除">
            {{ log.subnet_network }}
        </span>
    {% elif log.details.subnet %}
        <span class="text-slate-500">
            {{ log.details.subnet }}
        </span>
    {% else %}
        <span class="text-slate-400">-</span>
    {% endif %}
</td>
```

---

### Phase 3: 创建统一模态框组件 (60分钟)

#### 3.1 创建全局模态框管理器

**文件**: `/opt/ipim/backend/templates/base.html`

在 `<body>` 结束前添加模态框容器和 JavaScript：

```html
<!-- 全局模态框容器 -->
<div id="modal-container"></div>

<script>
// 全局模态框管理器
window.modal = {
    container: null,

    init() {
        this.container = document.getElementById('modal-container');
    },

    /**
     * 显示确认对话框
     * @param {Object} options - 配置选项
     * @param {string} options.title - 标题
     * @param {string} options.message - 消息内容
     * @param {string} options.type - 类型: info/warning/error/success
     * @param {string} options.confirmText - 确认按钮文字
     * @param {string} options.cancelText - 取消按钮文字
     * @returns {Promise<boolean>} - 用户选择结果
     */
    confirm(options) {
        return new Promise((resolve) => {
            const {
                title = '确认操作',
                message,
                type = 'warning',
                confirmText = '确定',
                cancelText = '取消'
            } = typeof options === 'string' ? { message: options } : options;

            const typeStyles = {
                info: { icon: 'info', color: 'blue' },
                warning: { icon: 'warning', color: 'amber' },
                error: { icon: 'error', color: 'red' },
                success: { icon: 'check_circle', color: 'green' }
            };

            const style = typeStyles[type] || typeStyles.warning;

            const html = `
                <div class="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4"
                     id="modal-overlay">
                    <div class="bg-white dark:bg-slate-800 rounded-xl shadow-2xl max-w-md w-full
                                border border-slate-200 dark:border-slate-700
                                transform transition-all duration-200 scale-100"
                         id="modal-content">
                        <!-- 头部 -->
                        <div class="p-6 pb-4 flex items-start gap-4">
                            <div class="flex-shrink-0 w-12 h-12 rounded-full
                                        bg-${style.color}-100 dark:bg-${style.color}-900/30
                                        flex items-center justify-center">
                                <span class="material-symbols-outlined text-${style.color}-600 dark:text-${style.color}-400 text-2xl">
                                    ${style.icon}
                                </span>
                            </div>
                            <div class="flex-1 pt-1">
                                <h3 class="text-lg font-semibold text-slate-900 dark:text-white">
                                    ${title}
                                </h3>
                                <p class="mt-2 text-slate-600 dark:text-slate-400">
                                    ${message}
                                </p>
                            </div>
                        </div>

                        <!-- 底部按钮 -->
                        <div class="px-6 py-4 bg-slate-50 dark:bg-slate-900/50
                                    border-t border-slate-200 dark:border-slate-700
                                    flex justify-end gap-3 rounded-b-xl">
                            <button type="button" id="modal-cancel"
                                    class="px-4 py-2 rounded-lg text-sm font-medium
                                           bg-white dark:bg-slate-700
                                           text-slate-700 dark:text-slate-300
                                           border border-slate-300 dark:border-slate-600
                                           hover:bg-slate-50 dark:hover:bg-slate-600
                                           transition-colors">
                                ${cancelText}
                            </button>
                            <button type="button" id="modal-confirm"
                                    class="px-4 py-2 rounded-lg text-sm font-medium text-white
                                           bg-${style.color}-600 hover:bg-${style.color}-500
                                           transition-colors">
                                ${confirmText}
                            </button>
                        </div>
                    </div>
                </div>
            `;

            this.container.innerHTML = html;

            // 绑定事件
            const overlay = document.getElementById('modal-overlay');
            const confirmBtn = document.getElementById('modal-confirm');
            const cancelBtn = document.getElementById('modal-cancel');

            const close = (result) => {
                this.container.innerHTML = '';
                resolve(result);
            };

            confirmBtn.onclick = () => close(true);
            cancelBtn.onclick = () => close(false);
            overlay.onclick = (e) => {
                if (e.target === overlay) close(false);
            };

            // ESC 键关闭
            const escHandler = (e) => {
                if (e.key === 'Escape') {
                    document.removeEventListener('keydown', escHandler);
                    close(false);
                }
            };
            document.addEventListener('keydown', escHandler);

            // 自动聚焦确认按钮
            confirmBtn.focus();
        });
    },

    /**
     * 显示提示消息
     * @param {Object} options - 配置选项
     * @returns {Promise<void>}
     */
    alert(options) {
        const opts = typeof options === 'string' ? { message: options } : options;
        return this.confirm({
            ...opts,
            cancelText: null  // 不显示取消按钮
        }).then(() => {});
    },

    /**
     * 显示 Toast 消息（3秒自动消失）
     * @param {string} message - 消息内容
     * @param {string} type - 类型: success/error/info/warning
     */
    toast(message, type = 'info') {
        const typeStyles = {
            success: { icon: 'check_circle', bg: 'bg-green-600' },
            error: { icon: 'error', bg: 'bg-red-600' },
            info: { icon: 'info', bg: 'bg-blue-600' },
            warning: { icon: 'warning', bg: 'bg-amber-600' }
        };

        const style = typeStyles[type] || typeStyles.info;

        const toast = document.createElement('div');
        toast.className = `fixed top-4 right-4 z-50 flex items-center gap-3 px-4 py-3 rounded-lg shadow-lg
                          ${style.bg} text-white transform transition-all duration-300
                          translate-x-full opacity-0`;
        toast.innerHTML = `
            <span class="material-symbols-outlined">${style.icon}</span>
            <span>${message}</span>
        `;

        document.body.appendChild(toast);

        // 动画进入
        requestAnimationFrame(() => {
            toast.classList.remove('translate-x-full', 'opacity-0');
        });

        // 3秒后消失
        setTimeout(() => {
            toast.classList.add('translate-x-full', 'opacity-0');
            setTimeout(() => toast.remove(), 300);
        }, 3000);
    }
};

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => window.modal.init());
</script>
```

#### 3.2 替换模板中的弹窗调用

**示例替换** - `/opt/ipim/backend/templates/ipam/ip_list.html`:

```javascript
// 之前
async function releaseIP(ipId) {
    if (confirm('确定要释放这个 IP 地址吗？')) {
        // ...
        alert('释放成功！');
    }
}

// 之后
async function releaseIP(ipId) {
    const confirmed = await window.modal.confirm({
        title: '释放 IP 地址',
        message: '确定要释放这个 IP 地址吗？释放后设备信息将被清除。',
        type: 'warning',
        confirmText: '释放',
        cancelText: '取消'
    });

    if (confirmed) {
        try {
            await window.apiFetch('/api/ip-addresses/release/', {
                method: 'POST',
                body: JSON.stringify({ ip_id: ipId })
            });
            window.modal.toast('IP 地址已释放', 'success');
            location.reload();
        } catch (error) {
            window.modal.toast('释放失败: ' + error.message, 'error');
        }
    }
}
```

**需要替换的文件列表**：

| 文件 | alert() | confirm() | 优先级 |
|------|---------|-----------|--------|
| `ip_list.html` | 3 | 2 | 高 |
| `ip_detail.html` | 4 | 2 | 高 |
| `subnet_detail.html` | 2 | 2 | 高 |
| `device_list.html` | 4 | 2 | 高 |
| `audit_log_list.html` | 1 | 0 | 中 |
| `ip_allocate.html` | 3 | 0 | 中 |
| `user_list.html` | 0 | 1 | 低 |
| `base.html` | 1 | 0 | 低 |

---

### Phase 4: SNMP 扫描子网过滤 (40分钟)

#### 4.1 添加子网过滤逻辑

**文件**: `/opt/ipim/backend/ipam/snmp_scanner.py`

```python
import ipaddress
from ipam.models import Subnet

class SNMPScanner:
    # ... 现有代码 ...

    def _get_system_subnets(self) -> list:
        """获取系统中所有已创建的子网"""
        subnets = []
        for subnet in Subnet.objects.all():
            try:
                network = ipaddress.ip_network(subnet.network)
                subnets.append(network)
            except ValueError:
                logger.warning(f"无效的子网格式: {subnet.network}")
        return subnets

    def _is_ip_in_system_subnets(self, ip_str: str, subnets: list) -> bool:
        """检查 IP 是否在系统子网内"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in subnet for subnet in subnets)
        except ValueError:
            return False

    def scan_and_update(self) -> Tuple[int, int, int]:
        """
        扫描并更新数据库

        Returns:
            (扫描数量, 更新数量, 冲突数量)
        """
        scanned = 0
        updated = 0
        conflicts = 0
        filtered = 0  # 新增：被过滤的数量

        try:
            entries = self.scan_arp_table()
            total_entries = len(entries)

            # 获取系统子网列表用于过滤
            system_subnets = self._get_system_subnets()
            logger.info(f"系统子网数量: {len(system_subnets)}")

            for entry in entries:
                # ✅ 新增：检查 IP 是否在系统子网内
                if not self._is_ip_in_system_subnets(entry.ip_address, system_subnets):
                    filtered += 1
                    logger.debug(f"过滤非系统子网 IP: {entry.ip_address}")
                    continue

                scanned += 1  # 只计入系统内的 IP

                # 检测冲突
                conflict_ip = ConflictDetectionService.detect_mac_conflict(
                    ip_address=entry.ip_address,
                    scanned_mac=entry.mac_address,
                    scan_source="SNMP",
                )

                if conflict_ip:
                    conflicts += 1
                else:
                    try:
                        ip = IpAddress.objects.get(address=entry.ip_address)
                        if ip.status == "available" and ip.mac_address != entry.mac_address:
                            ip.mac_address = entry.mac_address
                            ip.save()
                            updated += 1
                    except IpAddress.DoesNotExist:
                        pass

            # 更新设备扫描状态
            self.device.last_scan_at = timezone.now()
            self.device.last_scan_status = "success"
            self.device.last_scan_error = ""
            self.device.save()

            logger.info(
                f"SNMP扫描完成 [{self.device.name}]: "
                f"总数{total_entries}, 有效{scanned}, 过滤{filtered}, "
                f"更新{updated}, 冲突{conflicts}"
            )

        except Exception as e:
            self.device.last_scan_at = timezone.now()
            self.device.last_scan_status = "error"
            self.device.last_scan_error = str(e)[:500]
            self.device.save()
            logger.error(f"SNMP扫描失败 [{self.device.name}]: {e}")
            raise

        return scanned, updated, conflicts
```

#### 4.2 更新 API 返回值

**文件**: `/opt/ipim/backend/ipam/views.py`

更新 `NetworkDeviceViewSet.scan` 方法，返回过滤统计：

```python
@action(detail=True, methods=['post'])
def scan(self, request, pk=None):
    device = self.get_object()

    try:
        scanner = SNMPScanner(device)
        start_time = time.time()
        scanned, updated, conflicts = scanner.scan_and_update()
        elapsed = time.time() - start_time

        return Response({
            'status': 'success',
            'scanned': scanned,      # 系统内 IP 数量
            'updated': updated,
            'conflicts': conflicts,
            'elapsed': f'{elapsed:.2f}'
        })
    except Exception as e:
        return Response({
            'status': 'error',
            'message': str(e)
        }, status=500)
```

---

## 验收标准

### Phase 1: 审计日志子网字段
- [ ] 新创建的审计日志正确设置 `subnet` 和 `subnet_network` 字段
- [ ] 审计日志列表显示正确的子网信息，不再显示 "-"
- [ ] 兼容旧数据：能从 `details` JSON 中读取子网信息

### Phase 2: 审计日志详情 API
- [ ] 点击详情按钮正常显示日志详细信息
- [ ] API 返回包含 `display_message` 字段的中文操作描述
- [ ] 无 500 错误

### Phase 3: 模态框组件
- [ ] 创建全局 `window.modal` 对象
- [ ] 替换所有 `alert()` 调用为 `window.modal.toast()` 或 `window.modal.alert()`
- [ ] 替换所有 `confirm()` 调用为 `window.modal.confirm()`
- [ ] 模态框支持键盘操作（ESC 关闭、Enter 确认）
- [ ] 模态框适配暗色主题

### Phase 4: SNMP 扫描过滤
- [ ] 扫描结果只包含系统中已创建子网内的 IP 地址
- [ ] 非系统子网的 IP 被过滤，不计入扫描数量
- [ ] 日志记录过滤详情
- [ ] 测试锐捷 AC 设备（10.75.255.118）扫描正常

---

## 测试计划

### 1. 审计日志测试

```bash
# 1. 分配一个 IP 地址
# 2. 释放该 IP 地址
# 3. 检查审计日志列表：
#    - 子网列是否显示正确的子网
#    - 操作描述是否为中文
# 4. 点击详情按钮，确认无 500 错误
```

### 2. 模态框测试

```bash
# 1. 访问 IP 列表页面
# 2. 点击"释放"按钮，确认弹出自定义模态框
# 3. 测试 ESC 键关闭
# 4. 测试点击遮罩层关闭
# 5. 测试确认/取消按钮功能
# 6. 切换暗色主题，确认样式正确
```

### 3. SNMP 扫描测试

```bash
# 运行测试脚本
python3 /opt/ipim/test_snmp_scan.py --device-ip 10.75.255.118 --community zhld2018

# 检查结果：
# - 扫描数量应只包含系统内子网的 IP
# - 日志显示过滤了多少非系统 IP
```

---

## 风险与注意事项

1. **历史数据兼容**：旧审计日志的 `subnet` 字段为 `None`，前端需同时处理两种情况
2. **模态框样式**：需确保 Tailwind CSS 包含动态类名（可能需要 safelist）
3. **SNMP 性能**：子网过滤使用 Python 内存操作，大量子网时可能有性能影响
4. **并发安全**：审计日志创建在事务内，无需额外处理

---

## 时间估算

| 阶段 | 任务 | 预估时间 |
|------|------|----------|
| Phase 1 | 修复审计日志子网字段 | 30 分钟 |
| Phase 2 | 修复审计日志详情 API | 20 分钟 |
| Phase 3 | 创建模态框组件 | 30 分钟 |
| Phase 3 | 替换所有弹窗调用 | 30 分钟 |
| Phase 4 | SNMP 扫描子网过滤 | 40 分钟 |
| 测试 | 功能验证 | 30 分钟 |
| **总计** | | **约 3 小时** |

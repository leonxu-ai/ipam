# fix: IPAM 界面优化与功能修复

## Overview

修复 IPAM 系统中多个 UI/UX 问题和数据显示问题，包括子网详情页 IP 方块分组显示、IP 列表分页、设备类型中文显示、审计日志子网显示、以及用户角色互斥性。

## Problem Statement / Motivation

当前系统存在以下问题影响用户体验和数据准确性：

1. **子网详情页 IP 方块显示混乱**：对于 /22 等跨多个 C 类段的子网，所有 IP 方块混在一起，用户难以快速定位
2. **IP 列表只显示 200 条**：硬编码限制导致无法查看全部 IP，缺少分页功能
3. **设备类型显示英文代码**：分配 IP 后，设备类型列显示 `clean_instrument` 而非中文"洁净仪"
4. **审计日志子网显示为"-"**：模板引用了不存在的 `log.subnet` 字段
5. **用户角色不互斥**：允许同时勾选"管理员"和"超级管理员"，逻辑混乱

## Proposed Solution

### 1. 子网详情页 IP 方块分组

按 C 类地址段分组显示（如 172.20.36.x、37.x、38.x、39.x 各一块），每块显示 256 个方块（0-255），带明确的段标题。

### 2. IP 列表分页功能

移除 `[:200]` 硬编码限制，添加 Django Paginator 分页，支持用户选择每页显示数量（50/100/200/500）。

### 3. 设备类型中文显示

为 `device_type` 字段定义 `choices`，在模板中使用 `get_device_type_display()` 显示中文。

### 4. 审计日志子网显示

在 `AuditLog` 模型中添加 `subnet` 外键和 `subnet_network` 冗余字段，确保历史记录可追溯。

### 5. 用户角色互斥

将 `is_staff` 和 `is_superuser` 两个布尔字段改为单选角色字段，表单层面强制互斥。

## Technical Approach

### Architecture

```
修改文件:
├── models.py          # 添加 choices、外键、验证
├── frontend_views.py  # 修复分页、传递上下文
├── templates/
│   ├── subnet_detail.html  # IP 方块分组布局
│   ├── ip_list.html        # 分页控件
│   ├── audit_log_list.html # 子网字段显示
│   └── user_form.html      # 角色单选按钮
└── migrations/        # 数据库迁移
```

### Implementation Phases

#### Phase 1: 数据模型修复

**1.1 设备类型 choices 定义**

```python
# models.py - IpAddress 类
DEVICE_TYPE_CHOICES = [
    ("server", "服务器"),
    ("workstation", "工作站"),
    ("printer", "打印机"),
    ("network", "网络设备"),
    ("clean_instrument", "洁净仪"),
    ("iot", "物联网设备"),
    ("camera", "监控摄像头"),
    ("access_control", "门禁设备"),
    ("other", "其他"),
]

device_type = models.CharField(
    max_length=100,
    choices=DEVICE_TYPE_CHOICES,
    blank=True,
    verbose_name="设备类型",
)
```

**1.2 审计日志子网字段**

```python
# models.py - AuditLog 类
subnet = models.ForeignKey(
    'Subnet',
    on_delete=models.SET_NULL,
    null=True,
    blank=True,
    related_name='audit_logs',
    verbose_name="关联子网",
)
subnet_network = models.CharField(
    max_length=43,
    blank=True,
    verbose_name="子网地址（快照）",
    help_text="冗余存储，防止子网删除后丢失信息",
)
```

**1.3 用户角色字段**

```python
# 在 user_form.html 表单中实现互斥逻辑
# 使用单选按钮组替代两个复选框
```

#### Phase 2: IP 列表分页

**2.1 视图层修改**

```python
# frontend_views.py - ip_list 函数
from django.core.paginator import Paginator

def ip_list(request):
    # 获取每页数量参数
    page_size = request.GET.get('page_size', '100')
    if page_size not in ['50', '100', '200', '500']:
        page_size = '100'
    page_size = int(page_size)

    # 过滤和排序
    ips = IpAddress.objects.select_related("subnet", "allocated_by").all()
    # ... 过滤逻辑 ...
    ips = ips.order_by("address")

    # 分页
    paginator = Paginator(ips, page_size)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "page_size": page_size,
        "page_size_options": [50, 100, 200, 500],
        # ... 其他上下文 ...
    }
```

**2.2 模板分页控件**

```html
<!-- ip_list.html -->
<!-- 每页数量选择器 -->
<select onchange="changePageSize(this.value)">
    {% for size in page_size_options %}
    <option value="{{ size }}" {% if size == page_size %}selected{% endif %}>
        {{ size }} 条/页
    </option>
    {% endfor %}
</select>

<!-- 分页导航 -->
{% if page_obj.has_other_pages %}
<div class="pagination">
    {% if page_obj.has_previous %}
        <a href="?page=1&page_size={{ page_size }}">首页</a>
        <a href="?page={{ page_obj.previous_page_number }}&page_size={{ page_size }}">上一页</a>
    {% endif %}

    <span>第 {{ page_obj.number }} / {{ page_obj.paginator.num_pages }} 页</span>

    {% if page_obj.has_next %}
        <a href="?page={{ page_obj.next_page_number }}&page_size={{ page_size }}">下一页</a>
        <a href="?page={{ page_obj.paginator.num_pages }}&page_size={{ page_size }}">末页</a>
    {% endif %}
</div>
{% endif %}
```

#### Phase 3: 子网详情页 IP 分组

**3.1 视图层计算分组**

```python
# frontend_views.py - subnet_detail 函数
from ipaddress import ip_network

def subnet_detail(request, pk):
    subnet = get_object_or_404(Subnet, pk=pk)
    network = ip_network(subnet.network, strict=False)

    # 计算 C 类段分组
    c_class_groups = []
    start_ip = int(network.network_address)
    end_ip = int(network.broadcast_address)

    current_c_class = start_ip >> 8  # 取前24位
    group_ips = []

    for ip_int in range(start_ip, end_ip + 1):
        ip_c_class = ip_int >> 8
        if ip_c_class != current_c_class:
            # 新的 C 类段
            c_class_groups.append({
                'prefix': f"{(current_c_class >> 16) & 255}.{(current_c_class >> 8) & 255}.{current_c_class & 255}",
                'ips': group_ips,
            })
            current_c_class = ip_c_class
            group_ips = []

        # 获取 IP 对象
        ip_str = str(ipaddress.ip_address(ip_int))
        ip_obj = subnet.ip_addresses.filter(address=ip_str).first()
        group_ips.append({
            'address': ip_str,
            'last_octet': ip_int & 255,
            'status': ip_obj.status if ip_obj else 'uninitialized',
            'id': ip_obj.id if ip_obj else None,
        })

    # 添加最后一组
    if group_ips:
        c_class_groups.append({
            'prefix': f"{(current_c_class >> 16) & 255}.{(current_c_class >> 8) & 255}.{current_c_class & 255}",
            'ips': group_ips,
        })

    context = {
        'subnet': subnet,
        'c_class_groups': c_class_groups,
    }
```

**3.2 模板分组显示**

```html
<!-- subnet_detail.html -->
{% for group in c_class_groups %}
<div class="c-class-group mb-6">
    <h3 class="text-lg font-semibold mb-2">{{ group.prefix }}.x</h3>
    <div class="grid grid-cols-16 gap-1">
        {% for ip in group.ips %}
        <div class="ip-cell aspect-square flex items-center justify-center text-xs
                    {% if ip.status == 'available' %}bg-emerald-100 dark:bg-emerald-500/20{% endif %}
                    {% if ip.status == 'allocated' %}bg-blue-100 dark:bg-blue-500/20{% endif %}
                    {% if ip.status == 'reserved' %}bg-amber-100 dark:bg-amber-500/20{% endif %}
                    {% if ip.status == 'conflict' %}bg-red-100 dark:bg-red-500/20{% endif %}
                    {% if ip.status == 'uninitialized' %}bg-slate-100 dark:bg-slate-700{% endif %}"
             title="{{ ip.address }}">
            {{ ip.last_octet }}
        </div>
        {% endfor %}
    </div>
</div>
{% endfor %}
```

#### Phase 4: 审计日志子网显示

**4.1 模板修复**

```html
<!-- audit_log_list.html -->
<td>
    {% if log.subnet %}
        <a href="{% url 'ipam:subnet_detail' log.subnet.id %}">
            {{ log.subnet.network }}
        </a>
    {% elif log.subnet_network %}
        <span class="text-slate-400">{{ log.subnet_network }}</span>
    {% else %}
        -
    {% endif %}
</td>
```

**4.2 创建审计日志时填充子网**

```python
# services.py 或 views.py 中创建审计日志时
def create_audit_log(action, ip_address, user, details=None):
    subnet = ip_address.subnet if ip_address else None
    AuditLog.objects.create(
        action=action,
        ip_address=ip_address.address if ip_address else '',
        subnet=subnet,
        subnet_network=subnet.network if subnet else '',
        user=user,
        details=details,
    )
```

#### Phase 5: 用户角色互斥

**5.1 表单模板修改**

```html
<!-- user_form.html -->
<div class="form-group">
    <label class="block text-sm font-medium mb-2">用户角色 *</label>
    <div class="space-y-2">
        <label class="flex items-center gap-2">
            <input type="radio" name="role" value="user"
                   {% if not user.is_staff and not user.is_superuser %}checked{% endif %}>
            <span>普通用户</span>
            <span class="text-xs text-slate-500">- 只能查看和申请 IP</span>
        </label>
        <label class="flex items-center gap-2">
            <input type="radio" name="role" value="admin"
                   {% if user.is_staff and not user.is_superuser %}checked{% endif %}>
            <span>管理员</span>
            <span class="text-xs text-slate-500">- 可以管理 IP 和子网</span>
        </label>
        <label class="flex items-center gap-2">
            <input type="radio" name="role" value="superadmin"
                   {% if user.is_superuser %}checked{% endif %}>
            <span>超级管理员</span>
            <span class="text-xs text-slate-500">- 完全控制权限</span>
        </label>
    </div>
</div>
```

**5.2 视图层处理角色**

```python
# frontend_views.py - user_create/user_edit 函数
def user_create(request):
    if request.method == 'POST':
        role = request.POST.get('role', 'user')

        user = User.objects.create_user(
            username=request.POST.get('username'),
            password=request.POST.get('password'),
        )

        # 根据角色设置权限
        if role == 'superadmin':
            user.is_staff = True
            user.is_superuser = True
        elif role == 'admin':
            user.is_staff = True
            user.is_superuser = False
        else:  # user
            user.is_staff = False
            user.is_superuser = False

        user.save()
```

## Acceptance Criteria

### Functional Requirements

- [ ] 子网详情页按 C 类地址段分组显示 IP 方块
- [ ] 每个分组顶部显示段前缀（如 `172.20.36.x`）
- [ ] 每个方块显示最后一个八位数（1-255）
- [ ] IP 列表页显示完整的分页控件
- [ ] 用户可选择每页显示 50/100/200/500 条
- [ ] 分页时保持筛选条件
- [ ] 设备类型在所有页面显示中文
- [ ] 审计日志正确显示关联子网
- [ ] 用户表单只能选择一个角色

### Non-Functional Requirements

- [ ] IP 列表页加载时间 < 2 秒（1000+ 条记录）
- [ ] 子网详情页支持最大 /22 子网（1024 个 IP）
- [ ] 分页参数通过 URL 传递，支持刷新和书签

### Quality Gates

- [ ] 现有测试用例全部通过
- [ ] 设备类型数据迁移脚本正确执行
- [ ] 审计日志历史数据回填完成

## Dependencies & Prerequisites

- 需要创建数据库迁移文件
- 需要清洗现有设备类型数据
- 需要回填审计日志的子网字段

## Risk Analysis & Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|---------|
| 大子网（/16）渲染性能问题 | 中 | 高 | 限制最大显示为 /22，超过显示警告 |
| 历史审计日志无法关联子网 | 高 | 低 | 使用冗余 subnet_network 字段 |
| 设备类型历史数据不一致 | 高 | 低 | 提供数据清洗迁移脚本 |

## File Changes Summary

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `models.py` | 修改 | 添加 device_type choices, AuditLog.subnet 字段 |
| `frontend_views.py` | 修改 | ip_list 分页, subnet_detail 分组逻辑 |
| `ip_list.html` | 修改 | 添加分页控件, 使用 get_device_type_display |
| `subnet_detail.html` | 修改 | IP 方块分组显示 |
| `audit_log_list.html` | 修改 | 修复子网显示 |
| `user_form.html` | 修改 | 角色单选按钮 |
| `0004_*.py` | 新建 | 数据库迁移文件 |

## References & Research

### Internal References
- `frontend_views.py:167` - IP 列表硬编码 `[:200]` 限制
- `models.py:266-271` - device_type 字段定义
- `models.py:575-659` - AuditLog 模型
- `user_form.html:147-162` - 用户权限复选框

### External References
- Django Paginator 文档: https://docs.djangoproject.com/en/4.2/topics/pagination/
- Django model choices: https://docs.djangoproject.com/en/4.2/ref/models/fields/#choices
- Django get_FOO_display(): https://docs.djangoproject.com/en/4.2/ref/models/instances/#django.db.models.Model.get_FOO_display

---

Generated with [Claude Code](https://claude.com/claude-code)

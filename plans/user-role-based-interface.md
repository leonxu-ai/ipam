# feat: 基于用户角色的界面权限控制

**日期**: 2026-01-05
**类型**: Enhancement
**优先级**: 高

## 问题描述

当前普通用户登录后可以看到与管理员相同的界面（仪表板、子网管理、IP管理、网络设备、审计日志），这些专业内容对普通用户来说过于复杂且不必要。

**用户期望**：
- 普通用户：只能看到 **IP 申请向导**，简洁易用
- 管理员：看到完整管理界面

## 现状分析

### 当前权限结构

| 功能 | 当前权限 | 期望权限 |
|------|---------|---------|
| 仪表板 | 所有用户 | 仅管理员 |
| 子网管理 | 所有用户 | 仅管理员 |
| IP 管理 | 所有用户 | 仅管理员 |
| 网络设备 | 所有用户 | 仅管理员 |
| 审计日志 | 所有用户 | 仅管理员 |
| **IP 申请向导** | 所有用户 | **所有用户** |
| 用户管理 | 仅管理员 | 仅管理员 |
| Django Admin | 仅管理员 | 仅管理员 |

### 关键文件

| 文件 | 说明 |
|------|------|
| `/backend/templates/base.html:119-173` | 侧边栏菜单（需修改） |
| `/backend/ipam/frontend_views.py:25-27` | `is_admin()` 函数 |
| `/backend/ipam/frontend_views.py:184` | IP 申请向导视图 |
| `/backend/templates/ipam/ip_allocate.html` | IP 申请向导模板 |

## 解决方案

### 用户角色定义

```
普通用户 (is_staff=False, is_superuser=False)
  └── 只能访问: IP 申请向导、我的申请记录

管理员 (is_staff=True)
  └── 可以访问: 所有功能

超级管理员 (is_superuser=True)
  └── 可以访问: 所有功能 + Django Admin
```

## 实施计划

### Phase 1: 修改侧边栏菜单

**文件**: `/backend/templates/base.html`

```html
<!-- 导航菜单 -->
<nav class="flex-1 py-4 px-3 space-y-1 overflow-y-auto">
    <!-- IP 申请向导 - 所有用户可见 -->
    <a href="{% url 'ipam:ip_allocate' %}"
       class="flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors
              {% if 'allocate' in request.resolver_match.url_name %}
              bg-blue-600 text-white
              {% else %}
              text-slate-600 hover:bg-slate-100 hover:text-slate-900
              dark:text-slate-400 dark:hover:bg-slate-800 dark:hover:text-white
              {% endif %}">
        <span class="material-symbols-outlined text-xl">add_circle</span>
        IP 申请
    </a>

    <!-- 我的申请记录 - 所有用户可见 -->
    <a href="{% url 'ipam:my_allocations' %}"
       class="flex items-center gap-3 px-4 py-3 rounded-lg text-sm font-medium transition-colors ...">
        <span class="material-symbols-outlined text-xl">list_alt</span>
        我的申请
    </a>

    {% if request.user.is_staff %}
    <!-- 管理功能 - 仅管理员可见 -->
    <div class="mt-4 pt-4 border-t border-slate-200 dark:border-slate-800">
        <p class="px-4 py-2 text-xs font-medium text-slate-400 uppercase tracking-wider">管理功能</p>

        <a href="{% url 'ipam:dashboard' %}">仪表板</a>
        <a href="{% url 'ipam:subnet_list' %}">子网管理</a>
        <a href="{% url 'ipam:ip_list' %}">IP 管理</a>
        <a href="{% url 'ipam:device_list' %}">网络设备</a>
        <a href="{% url 'ipam:audit_log_list' %}">审计日志</a>
        <a href="{% url 'ipam:user_list' %}">用户管理</a>
    </div>
    {% endif %}

    {% if request.user.is_superuser %}
    <div class="mt-4 pt-4 border-t border-slate-200 dark:border-slate-800">
        <a href="{% url 'admin:index' %}">Django Admin</a>
    </div>
    {% endif %}
</nav>
```

### Phase 2: 添加视图权限控制

**文件**: `/backend/ipam/frontend_views.py`

为管理功能添加 `@user_passes_test(is_admin)` 装饰器：

```python
# 仪表板 - 仅管理员
@login_required
@user_passes_test(is_admin)
def dashboard(request):
    ...

# 子网列表 - 仅管理员
@login_required
@user_passes_test(is_admin)
def subnet_list(request):
    ...

# IP 列表 - 仅管理员
@login_required
@user_passes_test(is_admin)
def ip_list(request):
    ...

# 设备列表 - 仅管理员
@login_required
@user_passes_test(is_admin)
def device_list(request):
    ...

# 审计日志 - 仅管理员
@login_required
@user_passes_test(is_admin)
def audit_log_list(request):
    ...

# IP 申请向导 - 所有用户（保持不变）
@login_required
def ip_allocate(request, subnet_pk=None):
    ...
```

### Phase 3: 添加"我的申请"页面

新增普通用户查看自己申请记录的功能。

**文件**: `/backend/ipam/frontend_views.py`

```python
@login_required
def my_allocations(request):
    """我的IP申请记录"""
    # 获取当前用户分配的所有IP
    my_ips = IpAddress.objects.filter(
        allocated_by=request.user
    ).select_related("subnet").order_by("-allocated_at")

    return render(request, "ipam/my_allocations.html", {
        "ips": my_ips,
    })
```

**文件**: `/backend/templates/ipam/my_allocations.html`

显示用户自己申请的 IP 列表，包含：
- IP 地址
- 所属子网
- 主机名
- 申请时间
- 状态

### Phase 4: 修改默认首页

普通用户登录后自动跳转到 IP 申请向导。

**文件**: `/backend/ipam/frontend_views.py`

```python
@login_required
def index(request):
    """首页 - 根据用户角色跳转"""
    if request.user.is_staff:
        return redirect("ipam:dashboard")
    else:
        return redirect("ipam:ip_allocate")
```

**文件**: `/backend/ipam/urls.py`

```python
path("", frontend_views.index, name="index"),
```

## 验收标准

- [ ] 普通用户登录后只看到 "IP 申请" 和 "我的申请" 两个菜单
- [ ] 普通用户无法访问管理功能页面（返回 403 或跳转）
- [ ] 管理员可以看到完整菜单和所有功能
- [ ] "我的申请" 页面正确显示当前用户的申请记录
- [ ] 普通用户登录后默认跳转到 IP 申请向导

## 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `/backend/templates/base.html` | 修改 | 重构侧边栏菜单权限 |
| `/backend/ipam/frontend_views.py` | 修改 | 添加视图权限装饰器 |
| `/backend/ipam/frontend_views.py` | 新增 | `my_allocations()` 视图 |
| `/backend/ipam/frontend_views.py` | 新增 | `index()` 首页路由 |
| `/backend/ipam/urls.py` | 修改 | 添加新路由 |
| `/backend/templates/ipam/my_allocations.html` | 新增 | 我的申请模板 |

## 界面预览

### 普通用户侧边栏
```
┌─────────────────┐
│ 🏭 CALB-IPAM    │
├─────────────────┤
│ ⊕ IP 申请      │  ← 主要功能
│ 📋 我的申请    │  ← 查看记录
├─────────────────┤
│ 👤 用户名       │
│    登出        │
└─────────────────┘
```

### 管理员侧边栏
```
┌─────────────────┐
│ 🏭 CALB-IPAM    │
├─────────────────┤
│ ⊕ IP 申请      │
│ 📋 我的申请    │
├─ 管理功能 ─────┤
│ 📊 仪表板      │
│ 🌐 子网管理    │
│ 🔢 IP 管理     │
│ 📡 网络设备    │
│ 📜 审计日志    │
│ 👥 用户管理    │
├─────────────────┤
│ ⚙️ Django Admin │
└─────────────────┘
```

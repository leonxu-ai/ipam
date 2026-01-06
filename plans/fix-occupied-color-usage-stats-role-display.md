# fix: IP已占用颜色显示、使用统计、用户角色显示修复

## 📋 Overview

修复多个UI显示问题：
1. IP地址分布网格中"已占用"方框颜色显示异常（透明/白色）
2. 子网选择时"已用"显示为0，应显示实际使用数量
3. 用户身份显示硬编码为"网络管理员"，应根据实际角色动态显示

## 🐛 Problem Statement

### 问题1: 已占用颜色显示异常

**现象**: 子网详情页和IP申请页中，"已占用"状态的IP方框显示为透明色或白色，难以辨认

**位置**:
- `/opt/ipim/backend/templates/ipam/subnet_detail.html:191` - 使用 `bg-purple-500/80`
- `/opt/ipim/backend/templates/ipam/ip_allocate.html:265` - 使用 `'bg-purple-500/80'`

**根本原因**: Tailwind CSS 编译时可能未包含 `bg-purple-500/80` 类，或与其他样式冲突。需要确保：
1. Tailwind 配置正确扫描模板文件
2. 使用完整的颜色类而非透明度变体

### 问题2: "已用"统计显示为0

**现象**: 用户申请IP时，子网选择卡片显示"可用: 812, 已用: 0"

**位置**:
- `/opt/ipim/backend/ipam/frontend_views.py:299` - 只传递 `allocated_count`
- `/opt/ipim/backend/templates/ipam/ip_allocate.html:174` - 显示 `subnet.allocated_count`

**根本原因**:
- `allocated_count` 只统计状态为 `allocated` 的IP
- 未包含 `occupied`（扫描发现）和 `reserved`（保留）的IP
- 实际"已用" = allocated + occupied + reserved

### 问题3: 用户角色显示错误

**现象**: 普通用户登录后，左下角显示"网络管理员"

**位置**:
- `/opt/ipim/backend/templates/base.html:318` - 硬编码 `<p class="text-xs text-slate-500">网络管理员</p>`

**根本原因**: 角色文本未根据用户实际权限动态显示

**正确的角色映射**:
- `is_superuser=True` → "超级管理员"
- `is_staff=True, is_superuser=False` → "管理员"
- `is_staff=False, is_superuser=False` → "普通用户"

## ✅ Proposed Solution

### 修复1: 已占用颜色 - 使用不透明颜色

将 `bg-purple-500/80` 改为 `bg-purple-500` 避免透明度问题，或使用更明显的颜色。

### 修复2: 添加 used_count 字段

在 `frontend_views.py` 中计算并传递 `used_count`：
```python
"used_count": stats["allocated_count"] + stats["occupied_count"] + stats["reserved_count"]
```

### 修复3: 动态显示用户角色

使用Django模板条件判断：
```django
{% if request.user.is_superuser %}超级管理员
{% elif request.user.is_staff %}管理员
{% else %}普通用户{% endif %}
```

## 📝 Acceptance Criteria

- [ ] 子网详情页IP网格中"已占用"状态显示紫色方框，清晰可见
- [ ] IP申请页网格中"已占用"状态显示紫色方框，清晰可见
- [ ] 子网选择卡片"已用"显示正确数量（allocated + occupied + reserved）
- [ ] 子网详情页统计考虑将"已分配"和"已占用"合并显示
- [ ] 普通用户登录显示"普通用户"
- [ ] 管理员登录显示"管理员"
- [ ] 超级管理员登录显示"超级管理员"

## 🔧 Implementation Plan

### Phase 1: 修复颜色显示

**文件: `/opt/ipim/backend/templates/ipam/subnet_detail.html`**

```html
<!-- 第191行：将透明度80%改为100% -->
{% elif ip.status == 'occupied' %}bg-purple-500 hover:bg-purple-400 text-white
```

**文件: `/opt/ipim/backend/templates/ipam/ip_allocate.html`**

```html
<!-- 第265行：将透明度80%改为100% -->
'bg-purple-500': ip.status === 'occupied',
```

### Phase 2: 修复使用统计

**文件: `/opt/ipim/backend/ipam/frontend_views.py`**

```python
# 第288-301行：添加 used_count 字段
for subnet in subnets:
    stats = subnet.get_usage_stats()
    subnet_list.append({
        "id": subnet.id,
        "network": subnet.network,
        "description": subnet.description,
        "building": subnet.building or "",
        "floor": subnet.floor or 0,
        "available_count": stats["available_count"],
        "allocated_count": stats["allocated_count"],
        "occupied_count": stats["occupied_count"],  # 新增
        "used_count": stats["allocated_count"] + stats["occupied_count"] + stats["reserved_count"],  # 新增
        "usage_rate": stats["usage_rate"],
    })
```

**文件: `/opt/ipim/backend/templates/ipam/ip_allocate.html`**

```html
<!-- 第173-175行：显示更详细的统计 -->
<span class="text-emerald-600 dark:text-emerald-400">可用: <span x-text="subnet.available_count"></span></span>
<span class="text-purple-600 dark:text-purple-400">已占用: <span x-text="subnet.occupied_count"></span></span>
<span class="text-blue-600 dark:text-blue-400">已分配: <span x-text="subnet.allocated_count"></span></span>
```

### Phase 3: 修复用户角色显示

**文件: `/opt/ipim/backend/templates/base.html`**

```html
<!-- 第318行：替换硬编码文本 -->
<p class="text-xs text-slate-500">
    {% if request.user.is_superuser %}超级管理员
    {% elif request.user.is_staff %}管理员
    {% else %}普通用户{% endif %}
</p>
```

### Phase 4: 可选 - 合并已分配和已占用显示

在子网详情页和子网选择页，考虑将统计简化为：
- **已使用**: allocated + occupied + reserved
- **可用**: available
- **冲突**: conflict

## 📊 Files to Modify

| 文件 | 修改内容 |
|------|----------|
| `templates/ipam/subnet_detail.html` | 修复 occupied 颜色 |
| `templates/ipam/ip_allocate.html` | 修复 occupied 颜色 + 统计显示 |
| `ipam/frontend_views.py` | 添加 used_count, occupied_count 字段 |
| `templates/base.html` | 动态显示用户角色 |

## 🧪 Testing

1. **颜色测试**:
   - 进入子网详情页，确认已占用IP显示紫色
   - 进入IP申请页，确认已占用IP显示紫色
   - 测试暗色模式下颜色是否正常

2. **统计测试**:
   - 选择一个有已占用IP的子网
   - 确认"已占用"数量正确
   - 确认"已分配"数量正确

3. **角色测试**:
   - 以普通用户登录，确认显示"普通用户"
   - 以管理员登录，确认显示"管理员"
   - 以超级管理员登录，确认显示"超级管理员"

## 📚 References

- `/opt/ipim/backend/ipam/models.py:188-221` - get_usage_stats() 方法
- `/opt/ipim/backend/ipam/frontend_views.py:649-661` - 角色映射逻辑
- Tailwind CSS 颜色文档: https://tailwindcss.com/docs/background-color

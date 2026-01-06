# feat: 子网可见范围设置功能

## Overview

为子网管理界面添加可见范围设置功能，允许管理员控制子网在IP分配页面的显示范围。

## 当前状态

| 组件 | 状态 | 说明 |
|------|------|------|
| 数据库字段 | ✅ 已有 | building, floor, is_global 都已定义 |
| 过滤逻辑 | ✅ 已有 | filterSubnets() 已完美实现 |
| 子网编辑视图 | ❌ 缺少 | 需添加字段处理 |
| 子网创建视图 | ❌ 缺少 | 需添加字段处理 |
| 表单UI | ❌ 缺少 | 需添加输入字段 |

## 可见性规则

| 配置 | is_global | building | floor | 效果 |
|------|-----------|----------|-------|------|
| 全局可见 | true | - | - | 所有位置都可见 |
| 仅M1全部楼层 | false | "M1" | null | M1的1-4F都可见 |
| 仅M1-2F | false | "M1" | 2 | 只有M1-2F可见 |
| 不可见 | false | "NONE" | null | 任何位置都不可见 |

## Implementation

### Phase 1: 修改 subnet_form.html

添加三个表单字段：

```html
<!-- 可见范围设置 -->
<div class="space-y-4">
    <h3>可见范围设置</h3>

    <!-- 全局可见开关 -->
    <label>
        <input type="checkbox" name="is_global" {% if subnet.is_global %}checked{% endif %}>
        全局可见（所有位置都能看到此子网）
    </label>

    <!-- 楼栋选择 -->
    <select name="building">
        <option value="">所有楼栋</option>
        <option value="M1">M1 厂房</option>
        <option value="M2">M2 厂房</option>
        <option value="M3">M3 厂房</option>
        <option value="NONE">不可见</option>
    </select>

    <!-- 楼层选择 -->
    <select name="floor">
        <option value="">所有楼层</option>
        <option value="1">1F</option>
        <option value="2">2F</option>
        <option value="3">3F</option>
        <option value="4">4F</option>
    </select>
</div>
```

### Phase 2: 修改 frontend_views.py

**subnet_edit 视图** (第520-543行):
```python
# 添加到POST处理中
building = request.POST.get("building", "").strip()
floor = request.POST.get("floor", "").strip()
is_global = request.POST.get("is_global") == "on"

subnet.building = building
subnet.floor = int(floor) if floor else None
subnet.is_global = is_global
```

**subnet_create 视图** (第470-515行):
同样的处理逻辑

### Phase 3: 传递楼栋配置到模板

```python
buildings = [
    {"code": "M1", "name": "M1 厂房", "floors": [1, 2, 3, 4]},
    {"code": "M2", "name": "M2 厂房", "floors": [1, 2, 3]},
    {"code": "M3", "name": "M3 厂房", "floors": [1, 2, 3]},
]
context["buildings"] = buildings
```

## Files to Modify

1. `/opt/ipim/backend/templates/ipam/subnet_form.html` - 添加表单字段
2. `/opt/ipim/backend/ipam/frontend_views.py` - 修改 subnet_edit 和 subnet_create

## Acceptance Criteria

- [ ] 子网编辑页面显示可见范围设置选项
- [ ] 可以设置全局可见（勾选后所有位置可见）
- [ ] 可以设置仅特定楼栋可见
- [ ] 可以设置仅特定楼栋+楼层可见
- [ ] 可以设置为"NONE"使子网不可见
- [ ] 保存后IP分配页面按新规则过滤

## UI 交互逻辑

```javascript
// 当勾选"全局可见"时，禁用楼栋/楼层选择
if (isGlobal) {
    buildingSelect.disabled = true;
    floorSelect.disabled = true;
}

// 当选择楼栋时，动态更新楼层选项
// M1: 1-4F, M2/M3: 1-3F
```

# fix: 修复用户删除失败及超管账户保护

## 概述

修复用户删除时因 PostgreSQL 触发器阻止审计日志更新而失败的问题，同时实现以下改进：
1. 允许删除用户但保留其审计日志和 IP 分配记录
2. 保护 `admin` 超管账户不被删除（不显示删除按钮）
3. 更新权限说明：超管仅比管理员多 Django Admin 界面访问权限

## 问题分析

### 当前问题

**错误信息**：
```
Audit logs cannot be modified CONTEXT: PL/pgSQL function prevent_audit_log_update() line 3 at RAISE
```

**根本原因**：
- `AuditLog.user` 外键设置为 `on_delete=models.SET_NULL`
- 删除用户时 Django 执行 `UPDATE ipam_auditlog SET user_id = NULL WHERE user_id = ?`
- PostgreSQL 触发器 `prevent_audit_log_update()` 阻止**所有** UPDATE 操作
- 触发器未区分"恶意修改"与"用户删除触发的 SET_NULL"

### 当前触发器代码

```sql
-- /opt/ipim/backend/ipam/migrations/0002_add_audit_log_triggers.py
CREATE OR REPLACE FUNCTION prevent_audit_log_update()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'Audit logs cannot be modified';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
```

## 技术方案

### Phase 1: 修改 PostgreSQL 触发器

修改触发器逻辑，允许仅将 `user_id` 设置为 NULL 的操作：

```sql
CREATE OR REPLACE FUNCTION prevent_audit_log_update()
RETURNS TRIGGER AS $$
BEGIN
    -- 允许的情况：仅将 user_id 从非空设为 NULL（用户删除触发的 SET_NULL）
    IF OLD.user_id IS NOT NULL AND NEW.user_id IS NULL THEN
        -- 检查其他字段是否被修改
        IF OLD.timestamp = NEW.timestamp
           AND OLD.action = NEW.action
           AND OLD.ip_address IS NOT DISTINCT FROM NEW.ip_address
           AND OLD.hostname IS NOT DISTINCT FROM NEW.hostname
           AND OLD.mac_address IS NOT DISTINCT FROM NEW.mac_address
           AND OLD.subnet_id IS NOT DISTINCT FROM NEW.subnet_id
           AND OLD.subnet_network IS NOT DISTINCT FROM NEW.subnet_network
           AND OLD.details IS NOT DISTINCT FROM NEW.details
        THEN
            -- 仅 user_id 被设为 NULL，允许此操作
            RETURN NEW;
        END IF;
    END IF;

    -- 其他任何修改都拒绝
    RAISE EXCEPTION 'Audit logs cannot be modified';
    RETURN NULL;
END;
$$ LANGUAGE plpgsql;
```

**文件**: `/opt/ipim/backend/ipam/migrations/0011_fix_audit_log_trigger.py`

### Phase 2: 保护 admin 账户

在 `user_list.html` 模板中，对 `admin` 用户名的超管账户隐藏删除按钮：

```html
<!-- 条件：不是自己，且不是 username='admin' 的超管账户 -->
{% if user != request.user and not (user.username == 'admin' and user.is_superuser) %}
    <button type="button" onclick="confirmDeleteUser({{ user.id }}, '{{ user.username }}')" ...>
        <span class="material-symbols-outlined">delete</span>
    </button>
{% endif %}
```

**文件**: `/opt/ipim/backend/templates/ipam/user_list.html`

### Phase 3: 后端保护逻辑

在 `user_delete` 视图中添加额外保护：

```python
def user_delete(request, pk):
    user = get_object_or_404(User, pk=pk)

    # 不能删除自己
    if user == request.user:
        messages.error(request, "不能删除自己的账户")
        return redirect("ipam:user_list")

    # 不能删除 admin 超管账户
    if user.username == 'admin' and user.is_superuser:
        messages.error(request, "admin 超管账户无法删除")
        return redirect("ipam:user_list")

    # 不能删除超级管理员（除非自己也是超级管理员）
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, "只有超级管理员可以删除其他超级管理员")
        return redirect("ipam:user_list")

    # ... 执行删除
```

**文件**: `/opt/ipim/backend/ipam/frontend_views.py:851-872`

### Phase 4: 更新权限说明

在用户列表页面更新权限说明文字：

| 角色 | 旧说明 | 新说明 |
|-----|-------|-------|
| 超级管理员 | 拥有系统最高权限 | 管理员权限 + Django Admin 后台访问 |
| 管理员 | 可管理子网、设备、查看审计日志 | 可管理子网、设备、用户、查看审计日志 |
| 普通用户 | 仅可分配和释放IP地址 | 仅可分配和释放IP地址 |

**文件**: `/opt/ipim/backend/templates/ipam/user_list.html`

## 验收标准

### 功能要求

- [ ] 删除普通用户成功，不再出现触发器错误
- [ ] 删除用户后，其审计日志保留（`user_id = NULL`）
- [ ] 删除用户后，其 IP 分配记录保留（`allocated_by = NULL`）
- [ ] `admin` 超管账户的删除按钮不显示
- [ ] 尝试通过 API 删除 `admin` 账户返回错误
- [ ] 权限说明文字已更新

### 边缘情况

- [ ] 不能删除自己
- [ ] 普通管理员不能删除超级管理员
- [ ] 超级管理员可以删除其他非 admin 的超级管理员
- [ ] 删除用户后审计日志正确显示"已删除用户"

## 实施步骤

### Step 1: 创建数据库迁移

```python
# /opt/ipim/backend/ipam/migrations/0011_fix_audit_log_trigger.py

from django.db import migrations

class Migration(migrations.Migration):
    dependencies = [
        ('ipam', '0010_add_network_device_type_description'),
    ]

    operations = [
        migrations.RunSQL(
            sql='''
            CREATE OR REPLACE FUNCTION prevent_audit_log_update()
            RETURNS TRIGGER AS $$
            BEGIN
                -- 允许仅将 user_id 设为 NULL 的操作（用户删除触发）
                IF OLD.user_id IS NOT NULL AND NEW.user_id IS NULL THEN
                    IF OLD.timestamp = NEW.timestamp
                       AND OLD.action = NEW.action
                       AND OLD.ip_address IS NOT DISTINCT FROM NEW.ip_address
                       AND OLD.hostname IS NOT DISTINCT FROM NEW.hostname
                       AND OLD.mac_address IS NOT DISTINCT FROM NEW.mac_address
                       AND OLD.subnet_id IS NOT DISTINCT FROM NEW.subnet_id
                       AND OLD.subnet_network IS NOT DISTINCT FROM NEW.subnet_network
                       AND OLD.details IS NOT DISTINCT FROM NEW.details
                    THEN
                        RETURN NEW;
                    END IF;
                END IF;

                RAISE EXCEPTION 'Audit logs cannot be modified';
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            ''',
            reverse_sql='''
            CREATE OR REPLACE FUNCTION prevent_audit_log_update()
            RETURNS TRIGGER AS $$
            BEGIN
                RAISE EXCEPTION 'Audit logs cannot be modified';
                RETURN NULL;
            END;
            $$ LANGUAGE plpgsql;
            '''
        ),
    ]
```

### Step 2: 修改前端模板

**user_list.html** 删除按钮条件：

```html
<!-- 不显示删除按钮的条件：是自己 OR 是 admin 超管 -->
{% if user != request.user and not (user.username == 'admin' and user.is_superuser) %}
    <form method="post" action="{% url 'ipam:user_delete' user.id %}" ...>
        {% csrf_token %}
        <button type="button" onclick="confirmDeleteUser({{ user.id }}, '{{ user.username }}')" ...>
            <span class="material-symbols-outlined text-lg">delete</span>
        </button>
    </form>
{% endif %}
```

### Step 3: 修改后端视图

**frontend_views.py** `user_delete` 函数：

```python
@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def user_delete(request: HttpRequest, pk: int) -> HttpResponse:
    """删除用户"""
    user = get_object_or_404(User, pk=pk)

    # 不能删除自己
    if user == request.user:
        messages.error(request, "不能删除自己的账户")
        return redirect("ipam:user_list")

    # 不能删除 admin 超管账户
    if user.username == 'admin' and user.is_superuser:
        messages.error(request, "admin 超管账户无法删除，只能禁用")
        return redirect("ipam:user_list")

    # 不能删除超级管理员（除非自己也是超级管理员）
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, "只有超级管理员可以删除其他超级管理员")
        return redirect("ipam:user_list")

    username = user.username
    try:
        user.delete()
        messages.success(request, f"用户 {username} 已删除")
    except Exception as e:
        messages.error(request, f"删除用户失败: {e}")

    return redirect("ipam:user_list")
```

### Step 4: 更新权限说明文字

在 `user_list.html` 的权限说明区域：

```html
<div class="bg-card-dark rounded-lg p-4 border border-border-dark">
    <h3 class="text-lg font-medium text-text-primary mb-3">权限说明</h3>
    <div class="space-y-2 text-sm text-text-secondary">
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs bg-purple-500/20 text-purple-400">超级管理员</span>
            <span>管理员权限 + Django Admin 后台访问</span>
        </div>
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs bg-amber-500/20 text-amber-400">管理员</span>
            <span>可管理子网、设备、用户、查看审计日志</span>
        </div>
        <div class="flex items-center gap-2">
            <span class="px-2 py-0.5 rounded text-xs bg-gray-500/20 text-gray-400">普通用户</span>
            <span>仅可分配和释放IP地址</span>
        </div>
    </div>
</div>
```

## 风险与缓解

| 风险 | 可能性 | 影响 | 缓解措施 |
|-----|-------|-----|---------|
| 触发器修改后仍有问题 | 低 | 高 | 充分测试 SET_NULL 场景 |
| 遗漏其他引用 User 的外键 | 中 | 中 | 审查所有模型 |
| admin 账户被通过 API 删除 | 低 | 高 | 后端添加保护逻辑 |

## 测试用例

### 单元测试

```python
def test_delete_user_preserves_audit_logs(self):
    """删除用户时保留审计日志"""
    user = User.objects.create_user('testuser', 'test@test.com', 'password')
    AuditLog.objects.create(user=user, action='allocate', ip_address='10.0.0.1')

    user.delete()

    log = AuditLog.objects.get(ip_address='10.0.0.1')
    assert log.user is None
    assert log.action == 'allocate'

def test_cannot_delete_admin_superuser(self):
    """不能删除 admin 超管账户"""
    admin = User.objects.get(username='admin')

    response = self.client.post(f'/users/{admin.id}/delete/')

    assert User.objects.filter(username='admin').exists()
    assert 'admin 超管账户无法删除' in str(response.content)
```

## 参考资料

### 内部文件
- `/opt/ipim/backend/ipam/migrations/0002_add_audit_log_triggers.py` - 原触发器定义
- `/opt/ipim/backend/ipam/models.py:780-787` - AuditLog.user 外键定义
- `/opt/ipim/backend/ipam/frontend_views.py:851-872` - user_delete 视图
- `/opt/ipim/backend/templates/ipam/user_list.html:164-172` - 删除按钮 UI

### 外部文档
- [Django ForeignKey on_delete 参数](https://docs.djangoproject.com/en/4.2/ref/models/fields/#django.db.models.ForeignKey.on_delete)
- [PostgreSQL 触发器文档](https://www.postgresql.org/docs/current/plpgsql-trigger.html)

---

*计划创建时间: 2026-01-06*

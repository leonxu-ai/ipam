# Django 数据库迁移最佳实践速查表

## 目录
- [核心原则](#核心原则)
- [添加字段](#添加字段)
- [修改字段](#修改字段)
- [删除字段](#删除字段)
- [数据迁移](#数据迁移)
- [性能优化](#性能优化)
- [回滚策略](#回滚策略)
- [测试检查清单](#测试检查清单)

---

## 核心原则

### 1. 永远不要丢失数据
```python
# ❌ 危险：直接删除字段
class Migration(migrations.Migration):
    operations = [
        migrations.RemoveField('Model', 'important_field'),
    ]

# ✅ 安全：分步删除
# Step 1: 将字段标记为可选，停止写入（代码部署）
# Step 2: 部署代码后，删除字段（迁移部署）
```

### 2. 始终提供安全默认值
```python
# ❌ 错误：无默认值
field = models.IntegerField()  # 现有记录会失败

# ✅ 正确：提供默认值
field = models.IntegerField(default=0)

# ✅ 正确：允许 NULL（如果语义合理）
field = models.DateTimeField(blank=True, null=True)
```

### 3. 双层数据验证
```python
# ✅ 最佳实践：应用层 + 数据库层
class Migration(migrations.Migration):
    operations = [
        # 应用层验证
        migrations.AddField(
            model_name='device',
            name='priority',
            field=models.IntegerField(
                default=5,
                validators=[MinValueValidator(1), MaxValueValidator(10)],
            ),
        ),
        # 数据库层约束
        migrations.AddConstraint(
            model_name='device',
            constraint=models.CheckConstraint(
                check=models.Q(priority__gte=1) & models.Q(priority__lte=10),
                name='device_priority_valid_range',
            ),
        ),
    ]
```

### 4. 索引策略
```python
# ✅ 需要索引的场景
db_index=True  # WHERE 子句中的字段
db_index=True  # ORDER BY 子句中的字段
db_index=True  # JOIN 条件中的字段（外键自动索引）

# ❌ 不需要索引的场景
# - 低基数字段（如布尔字段，只有 True/False）
# - 很少查询的字段
# - 表数据量极小（< 1000 条）
```

---

## 添加字段

### 布尔字段
```python
# ✅ 标准模式
migrations.AddField(
    model_name='subnet',
    name='is_active',
    field=models.BooleanField(
        default=True,
        verbose_name='激活状态',
        db_index=True,  # 如果需要过滤
    ),
)
```

### 整数字段
```python
# ✅ 带验证的整数字段
migrations.AddField(
    model_name='device',
    name='port',
    field=models.IntegerField(
        default=161,
        validators=[
            MinValueValidator(1, message='端口号至少为1'),
            MaxValueValidator(65535, message='端口号最多为65535'),
        ],
        verbose_name='SNMP端口',
        help_text='默认: 161',
    ),
)

# 推荐：添加数据库约束
migrations.AddConstraint(
    model_name='device',
    constraint=models.CheckConstraint(
        check=models.Q(port__gte=1) & models.Q(port__lte=65535),
        name='device_port_valid_range',
    ),
)
```

### 字符字段
```python
# ✅ 带默认值和验证的字符字段
migrations.AddField(
    model_name='user',
    name='role',
    field=models.CharField(
        max_length=20,
        default='viewer',
        choices=[
            ('admin', '管理员'),
            ('editor', '编辑员'),
            ('viewer', '查看员'),
        ],
        verbose_name='角色',
        db_index=True,
    ),
)
```

### 日期时间字段
```python
# ✅ 允许 NULL 的时间戳（表示"未知"）
migrations.AddField(
    model_name='ipaddress',
    name='last_seen_at',
    field=models.DateTimeField(
        blank=True,
        null=True,
        verbose_name='最后发现时间',
        db_index=True,
    ),
)

# ✅ 自动时间戳
migrations.AddField(
    model_name='model',
    name='created_at',
    field=models.DateTimeField(
        auto_now_add=True,
        default=timezone.now,  # 为现有记录提供默认值
        verbose_name='创建时间',
    ),
    preserve_default=False,  # 迁移后移除默认值
)
```

### 外键字段
```python
# ✅ 允许 NULL 的外键
migrations.AddField(
    model_name='ipaddress',
    name='assigned_to',
    field=models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name='assigned_ips',
        verbose_name='分配给',
    ),
)

# ⚠️ 分步添加 NOT NULL 外键
# Step 1: 添加可选外键
migrations.AddField(..., null=True)

# Step 2: 数据迁移（填充值）
def populate_foreign_key(apps, schema_editor):
    Model = apps.get_model('app', 'Model')
    default_user = User.objects.first()
    Model.objects.filter(assigned_to__isnull=True).update(assigned_to=default_user)

migrations.RunPython(populate_foreign_key)

# Step 3: 设置 NOT NULL
migrations.AlterField(..., null=False)
```

---

## 修改字段

### 重命名字段
```python
# ✅ 使用 RenameField（保留数据）
migrations.RenameField(
    model_name='ipaddress',
    old_name='mac',
    new_name='mac_address',
)
```

### 改变字段类型
```python
# ⚠️ 高风险操作！可能丢失数据
# Step 1: 添加新字段
migrations.AddField(
    model_name='model',
    name='age_new',
    field=models.IntegerField(null=True),
)

# Step 2: 数据迁移
def convert_age(apps, schema_editor):
    Model = apps.get_model('app', 'Model')
    for obj in Model.objects.all():
        try:
            obj.age_new = int(obj.age_old)
            obj.save()
        except ValueError:
            obj.age_new = 0  # 默认值
            obj.save()

migrations.RunPython(convert_age)

# Step 3: 删除旧字段
migrations.RemoveField('model', 'age_old')

# Step 4: 重命名新字段
migrations.RenameField('model', 'age_new', 'age')
```

### 添加 NOT NULL 约束
```python
# ✅ 分步添加 NOT NULL
# Step 1: 添加可选字段
migrations.AddField(..., null=True, blank=True)

# Step 2: 填充现有记录
def populate_field(apps, schema_editor):
    Model = apps.get_model('app', 'Model')
    Model.objects.filter(field__isnull=True).update(field='default')

migrations.RunPython(populate_field)

# Step 3: 设置 NOT NULL
migrations.AlterField(
    model_name='model',
    name='field',
    field=models.CharField(max_length=100),  # null=False 是默认值
)
```

---

## 删除字段

### 安全删除流程
```python
# ✅ 三步安全删除
# Step 1: 代码中停止使用该字段（部署代码）
# Step 2: 将字段标记为可选（迁移）
migrations.AlterField(
    model_name='model',
    name='deprecated_field',
    field=models.CharField(max_length=100, blank=True, null=True),
)

# Step 3: 观察一段时间后删除（迁移）
migrations.RemoveField(
    model_name='model',
    name='deprecated_field',
)
```

### 删除带数据的字段
```python
# ⚠️ 归档数据后再删除
# Step 1: 数据归档
def archive_data(apps, schema_editor):
    Model = apps.get_model('app', 'Model')
    ArchivedData = apps.get_model('app', 'ArchivedData')

    for obj in Model.objects.all():
        if obj.deprecated_field:
            ArchivedData.objects.create(
                model_id=obj.id,
                deprecated_value=obj.deprecated_field,
            )

migrations.RunPython(archive_data)

# Step 2: 删除字段
migrations.RemoveField('model', 'deprecated_field')
```

---

## 数据迁移

### 基本数据迁移
```python
def forward_migration(apps, schema_editor):
    """正向迁移"""
    Model = apps.get_model('app', 'Model')
    Model.objects.filter(status='old').update(status='new')

def reverse_migration(apps, schema_editor):
    """反向迁移（回滚）"""
    Model = apps.get_model('app', 'Model')
    Model.objects.filter(status='new').update(status='old')

class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(forward_migration, reverse_migration),
    ]
```

### 批量数据迁移
```python
def batch_update(apps, schema_editor):
    """批量更新避免内存溢出"""
    Model = apps.get_model('app', 'Model')
    batch_size = 1000

    total = Model.objects.count()
    for offset in range(0, total, batch_size):
        batch = Model.objects.all()[offset:offset + batch_size]
        for obj in batch:
            obj.new_field = compute_value(obj)
            obj.save(update_fields=['new_field'])

migrations.RunPython(batch_update)
```

### 条件数据迁移
```python
def conditional_update(apps, schema_editor):
    """条件更新"""
    Model = apps.get_model('app', 'Model')

    # 更新满足条件的记录
    Model.objects.filter(
        created_at__lt=timezone.now() - timedelta(days=30)
    ).update(
        is_archived=True
    )

migrations.RunPython(conditional_update)
```

---

## 性能优化

### 大表迁移
```python
# ❌ 危险：大表上直接添加索引（可能锁表数分钟）
migrations.AddField(
    model_name='ipaddress',  # 假设有 100 万条记录
    name='status',
    field=models.CharField(max_length=20, db_index=True),
)

# ✅ 安全：分步添加索引
# Step 1: 添加字段（不加索引）
migrations.AddField(
    model_name='ipaddress',
    name='status',
    field=models.CharField(max_length=20, db_index=False),
)

# Step 2: 在线添加索引（PostgreSQL）
migrations.RunSQL(
    "CREATE INDEX CONCURRENTLY ipam_ipaddress_status_idx ON ipam_ipaddress (status);",
    reverse_sql="DROP INDEX ipam_ipaddress_status_idx;",
)

# Step 3: 更新模型定义
migrations.AlterField(
    model_name='ipaddress',
    name='status',
    field=models.CharField(max_length=20, db_index=True),
)
```

### 索引优化
```python
# ✅ 复合索引
class Meta:
    indexes = [
        models.Index(fields=['subnet', 'status']),  # 复合索引
        models.Index(fields=['-created_at']),       # 降序索引
        models.Index(fields=['address'], name='custom_idx_name'),
    ]
```

---

## 回滚策略

### 可回滚的迁移
```python
# ✅ 提供反向操作
class Migration(migrations.Migration):
    operations = [
        migrations.AddField(...),  # 自动可回滚
        migrations.RemoveField(...),  # 自动可回滚（数据丢失！）
        migrations.RunPython(forward, reverse),  # 手动提供回滚函数
    ]
```

### 不可回滚的迁移
```python
# ⚠️ 数据删除操作不可完全回滚
class Migration(migrations.Migration):
    operations = [
        migrations.RunPython(delete_old_data, migrations.RunPython.noop),
        # noop 表示回滚时不做任何操作（数据已删除）
    ]
```

### 回滚测试
```bash
# 应用迁移
python manage.py migrate app 0010

# 回滚到上一个版本
python manage.py migrate app 0009

# 验证数据完整性
python manage.py shell
>>> Model.objects.count()  # 应该与迁移前相同
```

---

## 测试检查清单

### 迁移前检查
- [ ] 创建数据库备份
- [ ] 在开发环境测试迁移
- [ ] 在预生产环境用生产数据副本测试
- [ ] 估算迁移时间（特别是大表）
- [ ] 准备回滚计划

### 迁移代码检查
- [ ] 所有新字段都有默认值或允许 NULL
- [ ] 使用了适当的验证器
- [ ] 关键字段添加了数据库索引
- [ ] 考虑了数据库层约束
- [ ] 提供了回滚函数（如果使用 RunPython）
- [ ] 数据迁移使用批处理（大表）

### 迁移后验证
- [ ] 检查记录总数是否一致
- [ ] 验证外键完整性
- [ ] 检查新字段的值分布
- [ ] 运行应用测试套件
- [ ] 监控应用性能
- [ ] 验证回滚功能

### 生产环境部署
- [ ] 选择业务低峰期
- [ ] 通知相关团队
- [ ] 准备好数据库备份
- [ ] 准备好回滚脚本
- [ ] 监控迁移过程
- [ ] 验证业务功能

---

## 常见陷阱

### 1. 忘记提供默认值
```python
# ❌ 错误
field = models.IntegerField()  # 现有记录会失败

# ✅ 正确
field = models.IntegerField(default=0)
```

### 2. 删除字段前未停止使用
```python
# ❌ 错误流程
# 1. 迁移删除字段
# 2. 部署代码（代码还在使用该字段 → 报错！）

# ✅ 正确流程
# 1. 部署代码（停止使用该字段）
# 2. 迁移删除字段
```

### 3. 大表上直接添加索引
```python
# ❌ 危险：可能锁表数分钟
db_index=True  # 在有百万条记录的表上

# ✅ 安全：使用 CONCURRENTLY（PostgreSQL）
migrations.RunSQL(
    "CREATE INDEX CONCURRENTLY ...",
)
```

### 4. 使用 auto_now_add 而不提供默认值
```python
# ❌ 错误：现有记录会失败
created_at = models.DateTimeField(auto_now_add=True)

# ✅ 正确
created_at = models.DateTimeField(
    auto_now_add=True,
    default=timezone.now,
)
# 迁移后可以移除 default
```

### 5. 数据迁移中使用模型方法
```python
# ❌ 危险：模型方法可能在未来版本中改变
def migrate_data(apps, schema_editor):
    from myapp.models import Model  # 使用当前模型
    for obj in Model.objects.all():
        obj.compute_something()  # 方法可能在迁移时不存在

# ✅ 安全：使用历史模型
def migrate_data(apps, schema_editor):
    Model = apps.get_model('app', 'Model')
    for obj in Model.objects.all():
        obj.field = simple_calculation(obj.other_field)
        obj.save()
```

---

## 数据库特定注意事项

### PostgreSQL
```python
# ✅ 在线添加索引
migrations.RunSQL(
    "CREATE INDEX CONCURRENTLY idx_name ON table_name (column);",
    reverse_sql="DROP INDEX idx_name;",
)

# ✅ 在线添加 NOT NULL
# Step 1: 添加 CHECK 约束
migrations.RunSQL(
    "ALTER TABLE table_name ADD CONSTRAINT check_not_null CHECK (column IS NOT NULL) NOT VALID;",
)

# Step 2: 验证约束（不锁表）
migrations.RunSQL(
    "ALTER TABLE table_name VALIDATE CONSTRAINT check_not_null;",
)

# Step 3: 设置 NOT NULL
migrations.RunSQL(
    "ALTER TABLE table_name ALTER COLUMN column SET NOT NULL;",
)
```

### MySQL
```python
# ⚠️ 大表迁移使用 pt-online-schema-change
# 命令行工具，不是 Django 迁移
# pt-online-schema-change --alter "ADD COLUMN status VARCHAR(20)" D=db,t=table

# ✅ Django 迁移中注释说明
class Migration(migrations.Migration):
    """
    大表迁移：请在生产环境使用 pt-online-schema-change

    命令：
    pt-online-schema-change --alter "ADD COLUMN status VARCHAR(20) DEFAULT 'active'" \\
        D=ipam_db,t=ipam_ipaddress --execute
    """
    operations = [
        # 开发环境使用标准迁移
        migrations.AddField(...),
    ]
```

---

## 总结

### 黄金法则
1. **永远不要丢失数据** - 删除前备份
2. **提供安全默认值** - 让现有记录能正常工作
3. **双层验证** - 应用层 + 数据库层
4. **测试回滚** - 确保能安全回退
5. **小步迭代** - 拆分复杂迁移为多个小步骤

### 生产环境部署
- 🕐 选择业务低峰期
- 💾 创建数据库备份
- 🧪 预生产环境验证
- 📊 监控性能指标
- 🔄 准备回滚计划

### 紧急回滚
```bash
# 1. 回滚迁移
python manage.py migrate app 0009

# 2. 如果失败，恢复备份
psql ipam_db < backup.sql

# 3. 重启应用服务
systemctl restart gunicorn
```

---

**记住**：数据完整性 > 性能优化 > 开发便利性

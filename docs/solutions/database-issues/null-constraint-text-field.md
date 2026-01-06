---
title: "Django TextField NOT NULL 约束错误"
date: 2026-01-05
category: database-issues
severity: medium
components:
  - Django ORM
  - PostgreSQL
tags:
  - IntegrityError
  - NOT NULL constraint
  - TextField
  - blank=True
status: solved
---

# Django TextField NOT NULL 约束错误

## 问题症状

**错误信息**:
```
django.db.utils.IntegrityError: NOT NULL constraint failed: ipam_networkdevice.last_scan_error
```

**发生场景**:
- SNMP 扫描成功后保存设备状态
- 代码中设置 `device.last_scan_error = None`
- 数据库拒绝 NULL 值

## 根本原因

### Django 字段定义与 NULL/空字符串

**模型定义** (`/opt/ipim/backend/ipam/models.py:521`):
```python
class NetworkDevice(models.Model):
    last_scan_error = models.TextField(
        blank=True,      # ✅ 表单验证允许空
        verbose_name="最后扫描错误",
    )
```

**关键区别**:
- `blank=True`: 表单验证层面允许空值
- `null=True`: 数据库层面允许 NULL

**当只设置 `blank=True` 时**:
- 表单提交时允许空字符串 `""`
- 但数据库层面 **不允许 NULL**
- 默认值应该是 `""` 而不是 `None`

## 错误代码

**文件**: `/opt/ipim/backend/ipam/snmp_scanner.py:285`

```python
# ❌ 错误：尝试设置 NULL
self.device.last_scan_status = "success"
self.device.last_scan_error = None  # 违反 NOT NULL 约束
self.device.save()
```

## 解决方案

### 修复代码

```python
# ✅ 正确：使用空字符串
self.device.last_scan_status = "success"
self.device.last_scan_error = ""  # 空字符串，不是 NULL
self.device.save()
```

### Django ORM 的 NULL vs 空字符串规则

| 字段类型 | `null=True` | `blank=True` | 清空时应使用 | 说明 |
|---------|-------------|--------------|-------------|------|
| `CharField` | ❌ | ✅ | `""` | Django 约定使用空字符串 |
| `TextField` | ❌ | ✅ | `""` | Django 约定使用空字符串 |
| `IntegerField` | ✅ | ✅ | `None` | 数值类型使用 NULL |
| `DateTimeField` | ✅ | ✅ | `None` | 日期类型使用 NULL |
| `ForeignKey` | ✅ | ✅ | `None` | 关系字段使用 NULL |
| `JSONField` | ✅ | ✅ | `None` 或 `{}` | 可以两者都用 |

### Django 最佳实践

**字符串字段（CharField/TextField）**:
```python
# ✅ 推荐：不使用 null=True
description = models.TextField(blank=True)

# 清空时
obj.description = ""  # 使用空字符串
```

**数值/日期/关系字段**:
```python
# ✅ 推荐：使用 null=True
age = models.IntegerField(blank=True, null=True)
created_at = models.DateTimeField(blank=True, null=True)
parent = models.ForeignKey('self', blank=True, null=True)

# 清空时
obj.age = None
obj.created_at = None
obj.parent = None
```

## 为什么 Django 对字符串字段避免 NULL

### Django 的哲学

引用自 [Django 文档](https://docs.djangoproject.com/en/4.2/ref/models/fields/#null):

> "Avoid using null on string-based fields such as CharField and TextField.
> If a string-based field has null=True, that means it has two possible values
> for 'no data': NULL, and the empty string. In most cases, it's redundant to
> have two possible values for 'no data'."

**翻译**:
避免在基于字符串的字段（如 CharField 和 TextField）上使用 `null=True`。如果字符串字段设置了 `null=True`，意味着"无数据"有两种可能的值：NULL 和空字符串。在大多数情况下，为"无数据"提供两种可能值是多余的。

### 实际问题

```python
# ❌ 使用 null=True 会导致混乱
error = models.TextField(blank=True, null=True)

# 查询时需要同时检查两种情况
devices_with_errors = Device.objects.filter(
    Q(last_scan_error__isnull=False) &
    ~Q(last_scan_error='')
)

# ✅ 只用空字符串更简洁
error = models.TextField(blank=True)

# 查询清晰
devices_with_errors = Device.objects.exclude(last_scan_error='')
```

## 迁移现有数据库

如果已经有 `null=True` 的字段，如何迁移：

### 步骤 1: 更新现有 NULL 值

```python
# 创建数据迁移
python manage.py makemigrations --empty ipam

# 编辑迁移文件
from django.db import migrations

def convert_nulls_to_empty_strings(apps, schema_editor):
    NetworkDevice = apps.get_model('ipam', 'NetworkDevice')
    NetworkDevice.objects.filter(last_scan_error__isnull=True).update(
        last_scan_error=''
    )

class Migration(migrations.Migration):
    dependencies = [
        ('ipam', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(convert_nulls_to_empty_strings),
    ]
```

### 步骤 2: 移除 null=True

```python
# models.py
class NetworkDevice(models.Model):
    last_scan_error = models.TextField(
        blank=True,
        # null=True,  # 移除这一行
    )
```

### 步骤 3: 生成 schema 迁移

```bash
python manage.py makemigrations
python manage.py migrate
```

## 测试验证

### 单元测试

```python
from django.test import TestCase
from ipam.models import NetworkDevice

class NetworkDeviceTest(TestCase):
    def test_empty_last_scan_error(self):
        """测试 last_scan_error 字段可以为空字符串"""
        device = NetworkDevice.objects.create(
            name="测试设备",
            ip_address="192.168.1.1",
            snmp_version="v2c",
            snmp_community="public",
            last_scan_error="",  # 空字符串
        )

        device.refresh_from_db()
        self.assertEqual(device.last_scan_error, "")

    def test_cannot_set_null(self):
        """测试 last_scan_error 不能设置为 NULL"""
        device = NetworkDevice.objects.create(
            name="测试设备",
            ip_address="192.168.1.1",
            snmp_version="v2c",
        )

        with self.assertRaises(IntegrityError):
            device.last_scan_error = None
            device.save()
```

## 预防策略

### 1. Code Review Checklist

审查字段定义时检查：
- [ ] 字符串字段（CharField/TextField）不使用 `null=True`
- [ ] 清空字符串字段时使用 `""`，不使用 `None`
- [ ] 数值/日期/外键字段明确指定 `null=True`

### 2. Linter 规则

使用 `flake8-django` 或 `pylint-django`:
```python
# .pylintrc
[MESSAGES CONTROL]
enable=django-null-on-string-field
```

### 3. 模型生成器模板

创建模型时的默认模板：
```python
# 字符串字段模板
name = models.CharField(max_length=200, blank=True)  # ✅ 不加 null=True

# 可选数值字段模板
count = models.IntegerField(blank=True, null=True)  # ✅ 明确 null=True

# 可选外键模板
parent = models.ForeignKey('self', blank=True, null=True, on_delete=models.SET_NULL)
```

### 4. 自动化测试

在 CI/CD 中添加检查：
```bash
# scripts/check_model_fields.py
import ast
import sys

def check_string_field_null(filename):
    with open(filename) as f:
        tree = ast.parse(f.read())

    errors = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if hasattr(node.func, 'attr'):
                # 检查 CharField/TextField
                if node.func.attr in ['CharField', 'TextField']:
                    for keyword in node.keywords:
                        if keyword.arg == 'null' and keyword.value.value == True:
                            errors.append(f"{filename}: {node.lineno}")

    return errors

if __name__ == '__main__':
    errors = check_string_field_null('ipam/models.py')
    if errors:
        print("❌ 发现字符串字段使用 null=True:")
        for error in errors:
            print(f"  {error}")
        sys.exit(1)
    print("✅ 所有字符串字段符合规范")
```

## 相关问题

- Django ORM 字段选项
- PostgreSQL vs SQLite NULL 处理差异
- 数据库迁移策略

## 参考资料

- [Django Field Options - null](https://docs.djangoproject.com/en/4.2/ref/models/fields/#null)
- [Django Field Options - blank](https://docs.djangoproject.com/en/4.2/ref/models/fields/#blank)
- [Django Best Practices - CharField null](https://docs.djangoproject.com/en/4.2/ref/models/fields/#django.db.models.CharField)
- [Two Scoops of Django - Field Choices](https://www.feldroy.com/books/two-scoops-of-django-3-x)

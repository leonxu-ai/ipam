# 数据库迁移审查总结

**项目**: IPAM 系统
**审查日期**: 2026-01-05
**审查人**: 数据完整性守护者

---

## 执行摘要

已完成对三个数据库迁移的全面审查：

- **迁移 0007**: 添加 `Subnet.is_global` 字段 ✅
- **迁移 0008**: 添加 `NetworkDevice.scan_interval_minutes` 字段 ⚠️
- **迁移 0009**: 添加 `IpAddress.consecutive_missing` 和 `last_seen_at` 字段 ⚠️

### 总体评估
- **风险等级**: 🟢 **低风险** - 所有迁移可安全部署
- **数据丢失风险**: ✅ **无** - 不会造成任何数据丢失
- **回滚安全性**: ✅ **完全可回滚**
- **生产环境就绪**: ✅ **是**（建议添加数据库约束）

---

## 迁移详情

### 迁移 0007: Subnet.is_global

#### 变更内容
```python
migrations.AddField(
    model_name='subnet',
    name='is_global',
    field=models.BooleanField(default=False, db_index=True),
)
```

#### 数据完整性评估
| 检查项 | 状态 | 说明 |
|--------|------|------|
| 安全默认值 | ✅ 通过 | `default=False` |
| NOT NULL 约束 | ✅ 通过 | BooleanField 默认不允许 NULL |
| 数据库索引 | ✅ 通过 | `db_index=True` 用于过滤查询 |
| 现有数据影响 | ✅ 无影响 | 所有现有子网自动设置为 `is_global=False` |
| 回滚安全性 | ✅ 安全 | 删除列不影响其他数据 |

#### 风险评级
🟢 **低风险** - 可直接部署到生产环境

---

### 迁移 0008: NetworkDevice.scan_interval_minutes

#### 变更内容
```python
migrations.AddField(
    model_name='networkdevice',
    name='scan_interval_minutes',
    field=models.IntegerField(
        default=30,
        validators=[MinValueValidator(1), MaxValueValidator(1440)],
    ),
)
```

#### 数据完整性评估
| 检查项 | 状态 | 说明 |
|--------|------|------|
| 安全默认值 | ✅ 通过 | `default=30` (30 分钟) |
| NOT NULL 约束 | ✅ 通过 | IntegerField 默认不允许 NULL |
| 数据验证器 | ✅ 通过 | 应用层验证范围 1-1440 |
| 数据库约束 | ⚠️ 缺失 | 仅有应用层验证，无数据库 CHECK 约束 |
| 现有数据影响 | ✅ 无影响 | 所有现有设备自动设置为 30 分钟 |
| 回滚安全性 | ✅ 安全 | 删除列不影响其他数据 |

#### 风险评级
🟡 **中低风险** - 建议添加数据库 CHECK 约束

#### 发现的问题
**问题**: 缺少数据库层约束

**风险**: 直接 SQL 操作可绕过验证器插入无效值（如 -1 或 99999）

**建议修复**:
```python
migrations.AddConstraint(
    model_name='networkdevice',
    constraint=models.CheckConstraint(
        check=models.Q(scan_interval_minutes__gte=1) &
              models.Q(scan_interval_minutes__lte=1440),
        name='networkdevice_scan_interval_valid_range',
    ),
)
```

---

### 迁移 0009: IpAddress 跟踪字段

#### 变更内容
```python
migrations.AddField(
    model_name='ipaddress',
    name='consecutive_missing',
    field=models.IntegerField(
        default=0,
        validators=[MinValueValidator(0)],
        db_index=True,
    ),
)

migrations.AddField(
    model_name='ipaddress',
    name='last_seen_at',
    field=models.DateTimeField(blank=True, null=True, db_index=True),
)
```

#### 数据完整性评估
| 检查项 | 状态 | 说明 |
|--------|------|------|
| **consecutive_missing** | | |
| 安全默认值 | ✅ 通过 | `default=0` |
| NOT NULL 约束 | ✅ 通过 | IntegerField 默认不允许 NULL |
| 数据验证器 | ✅ 通过 | 应用层验证 >= 0 |
| 数据库约束 | ⚠️ 缺失 | 仅有应用层验证，无数据库 CHECK 约束 |
| 数据库索引 | ✅ 通过 | `db_index=True` 用于查找离线设备 |
| **last_seen_at** | | |
| 允许 NULL | ✅ 正确 | `null=True` - NULL 表示"未扫描" |
| 数据库索引 | ✅ 通过 | `db_index=True` 用于时间范围查询 |
| 现有数据影响 | ✅ 无影响 | `consecutive_missing=0`, `last_seen_at=NULL` |
| 回滚安全性 | ✅ 安全 | 删除列不影响其他数据 |

#### 风险评级
🟡 **中低风险** - 建议添加数据库 CHECK 约束

#### 发现的问题
**问题**: `consecutive_missing` 缺少数据库层约束

**风险**: 直接 SQL 操作可插入负数

**建议修复**:
```python
migrations.AddConstraint(
    model_name='ipaddress',
    constraint=models.CheckConstraint(
        check=models.Q(consecutive_missing__gte=0),
        name='ipaddress_consecutive_missing_non_negative',
    ),
)
```

---

## 性能影响评估

### 表锁定时间估算

| 表 | 预估记录数 | 新增列 | 新增索引 | 预计锁定时间 |
|----|-----------|--------|----------|-------------|
| `ipam_subnet` | < 1000 | 1 | 1 | < 1 秒 |
| `ipam_networkdevice` | < 100 | 1 | 0 | < 0.5 秒 |
| `ipam_ipaddress` | 10,000-100,000 | 2 | 2 | 2-10 秒 |

### 索引性能提升

| 索引字段 | 查询场景 | 预期性能提升 |
|---------|---------|-------------|
| `subnet.is_global` | `filter(is_global=True)` | +50-90% |
| `ipaddress.consecutive_missing` | `filter(consecutive_missing__gte=5)` | +60-95% |
| `ipaddress.last_seen_at` | `filter(last_seen_at__lt=date)` | +60-95% |

### 生产环境建议
- ✅ 在业务低峰期执行迁移
- ✅ 如果 `ipam_ipaddress` 表超过 50 万条记录，考虑使用在线迁移工具
- ✅ PostgreSQL: 使用 `CREATE INDEX CONCURRENTLY`
- ✅ MySQL: 使用 `pt-online-schema-change`

---

## 数据隐私合规

### GDPR/CCPA 影响分析

| 字段 | 包含 PII | 数据类型 | 合规措施 |
|------|----------|----------|----------|
| `is_global` | ❌ 否 | 元数据 | 无需特殊措施 |
| `scan_interval_minutes` | ❌ 否 | 配置数据 | 无需特殊措施 |
| `consecutive_missing` | ❌ 否 | 运营数据 | 无需特殊措施 |
| `last_seen_at` | ⚠️ 间接 | 时间戳 | 建议 90 天数据保留策略 |

**`last_seen_at` 隐私建议**:
- 实施数据保留策略：定期清理 90 天前的历史数据
- 限制访问权限：仅授权管理员可查看
- 审计日志：记录所有访问操作

---

## 回滚测试

### 回滚流程
```bash
# 1. 应用迁移
python manage.py migrate ipam 0009

# 2. 测试功能
# ... 运行测试 ...

# 3. 回滚到 0006
python manage.py migrate ipam 0006

# 4. 验证数据完整性
python manage.py shell
>>> from ipam.models import Subnet, NetworkDevice, IpAddress
>>> Subnet.objects.count()  # 应该与迁移前相同
>>> NetworkDevice.objects.count()  # 应该与迁移前相同
>>> IpAddress.objects.count()  # 应该与迁移前相同
```

### 回滚安全性
| 迁移 | 回滚操作 | 数据丢失 | 业务影响 |
|------|---------|---------|---------|
| 0007 | 删除 `is_global` 列 | ❌ 无 | 功能降级（失去全局子网标记） |
| 0008 | 删除 `scan_interval_minutes` 列 | ❌ 无 | 功能降级（使用默认扫描间隔） |
| 0009 | 删除两个跟踪字段 | ❌ 无 | 功能降级（失去离线设备跟踪） |

---

## 改进建议

### 立即实施（高优先级）

#### 1. 添加数据库约束
在生产环境部署前，建议使用改进版本的迁移文件：

**文件位置**:
- `/opt/ipim/backend/ipam/migrations/0008_add_scan_interval_to_networkdevice_v2.py.example`
- `/opt/ipim/backend/ipam/migrations/0009_add_tracking_fields_to_ipaddress_v2.py.example`

**改进内容**:
```python
# 添加数据库 CHECK 约束
migrations.AddConstraint(
    model_name='networkdevice',
    constraint=models.CheckConstraint(
        check=models.Q(scan_interval_minutes__gte=1) &
              models.Q(scan_interval_minutes__lte=1440),
        name='networkdevice_scan_interval_valid_range',
    ),
)

migrations.AddConstraint(
    model_name='ipaddress',
    constraint=models.CheckConstraint(
        check=models.Q(consecutive_missing__gte=0),
        name='ipaddress_consecutive_missing_non_negative',
    ),
)
```

### 后续优化（中优先级）

#### 2. 监控索引性能
部署后监控新增索引的实际性能影响：
```sql
-- PostgreSQL: 检查索引使用情况
SELECT schemaname, tablename, indexname, idx_scan, idx_tup_read
FROM pg_stat_user_indexes
WHERE tablename IN ('ipam_subnet', 'ipam_ipaddress')
ORDER BY idx_scan DESC;
```

#### 3. 评估复合索引需求
如果经常需要复合查询，考虑添加复合索引：
```python
class IpAddress(models.Model):
    class Meta:
        indexes = [
            # 复合索引：查找特定子网中的离线设备
            models.Index(fields=['subnet', 'consecutive_missing']),
            # 复合索引：按状态和最后发现时间排序
            models.Index(fields=['status', '-last_seen_at']),
        ]
```

### 长期优化（低优先级）

#### 4. 数据保留策略
实施 `last_seen_at` 数据清理任务：
```python
# tasks.py
from celery import shared_task
from datetime import timedelta
from django.utils import timezone

@shared_task
def cleanup_old_tracking_data():
    """清理 90 天前的跟踪数据"""
    threshold = timezone.now() - timedelta(days=90)
    IpAddress.objects.filter(
        last_seen_at__lt=threshold
    ).update(last_seen_at=None, consecutive_missing=0)
```

---

## 测试验证

### 提供的测试工具

#### 1. 单元测试
**文件**: `/opt/ipim/backend/ipam/tests/test_migrations.py`

**运行**:
```bash
python manage.py test ipam.tests.test_migrations
```

**覆盖范围**:
- ✅ 字段默认值测试
- ✅ 验证器测试（最小值、最大值）
- ✅ 索引查询测试
- ✅ 数据完整性测试

#### 2. 迁移验证脚本
**文件**: `/opt/ipim/scripts/verify_migrations.py`

**运行**:
```bash
python manage.py shell < scripts/verify_migrations.py
```

**验证内容**:
- ✅ 字段存在性检查
- ✅ 默认值验证
- ✅ 索引检查
- ✅ 验证器测试
- ✅ 数据完整性检查

---

## 部署检查清单

### 部署前准备
- [ ] 在开发环境测试所有三个迁移
- [ ] 运行完整的测试套件 (`python manage.py test`)
- [ ] 运行迁移验证脚本 (`scripts/verify_migrations.py`)
- [ ] 在预生产环境用生产数据副本测试
- [ ] 创建数据库完整备份
- [ ] 准备回滚脚本

### 迁移执行
- [ ] 选择业务低峰期（如凌晨 2-4 点）
- [ ] 通知相关团队迁移时间窗口
- [ ] 启用维护模式（可选）
- [ ] 执行迁移: `python manage.py migrate ipam 0009`
- [ ] 监控迁移进度和数据库性能
- [ ] 记录迁移耗时

### 迁移后验证
- [ ] 验证记录总数: `python manage.py shell < scripts/verify_migrations.py`
- [ ] 运行应用测试套件
- [ ] 验证核心业务功能
- [ ] 检查应用日志无异常
- [ ] 监控系统性能指标（CPU、内存、数据库连接）
- [ ] 验证索引已创建

### 出现问题时
- [ ] 立即回滚: `python manage.py migrate ipam 0006`
- [ ] 如果回滚失败，恢复数据库备份
- [ ] 分析失败原因
- [ ] 修复问题后重新测试

---

## 文档资源

### 已创建的文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 详细审查报告 | `/opt/ipim/docs/migration-review-report.md` | 完整的数据完整性分析 |
| 最佳实践指南 | `/opt/ipim/docs/migration-best-practices.md` | Django 迁移最佳实践速查表 |
| 迁移验证脚本 | `/opt/ipim/scripts/verify_migrations.py` | 自动化验证工具 |
| 单元测试 | `/opt/ipim/backend/ipam/tests/test_migrations.py` | 完整的迁移测试套件 |
| 改进版迁移（v2） | `/opt/ipim/backend/ipam/migrations/*_v2.py.example` | 包含数据库约束的版本 |

### 迁移文件

| 迁移 | 路径 | 状态 |
|------|------|------|
| 0007 | `backend/ipam/migrations/0007_add_is_global_to_subnet.py` | ✅ 已创建 |
| 0008 | `backend/ipam/migrations/0008_add_scan_interval_to_networkdevice.py` | ✅ 已创建 |
| 0009 | `backend/ipam/migrations/0009_add_tracking_fields_to_ipaddress.py` | ✅ 已创建 |
| 0008 v2 | `backend/ipam/migrations/0008_*_v2.py.example` | 💡 改进版本（包含约束） |
| 0009 v2 | `backend/ipam/migrations/0009_*_v2.py.example` | 💡 改进版本（包含约束） |

---

## 最终建议

### 部署建议
1. ✅ **批准部署**到开发环境和预生产环境
2. ⚠️ **建议使用改进版本**（包含数据库约束）部署到生产环境
3. ✅ 在业务低峰期执行迁移
4. ✅ 准备完整的回滚计划

### 优先级排序
1. **高优先级**: 在开发环境测试迁移
2. **高优先级**: 考虑使用 v2 版本（包含数据库约束）
3. **中优先级**: 在预生产环境验证
4. **中优先级**: 部署到生产环境
5. **低优先级**: 监控索引性能，评估复合索引需求

### 技术债务
- ⚠️ 当前版本缺少数据库层 CHECK 约束（中等风险）
- 💡 可以在后续迁移中添加约束
- 💡 建议在下一个维护窗口实施

---

## 批准

### 数据完整性审查
- **审查人**: 数据完整性守护者
- **日期**: 2026-01-05
- **结论**: ✅ **通过** - 可安全部署

### 风险评估
- **数据丢失风险**: 🟢 **无**
- **性能影响**: 🟢 **低** (< 10 秒锁定时间)
- **回滚风险**: 🟢 **低** (完全可回滚)
- **总体风险**: 🟢 **低风险**

### 推荐操作
✅ **批准部署** - 建议在业务低峰期执行

---

**报告生成时间**: 2026-01-05
**报告版本**: 1.0
**下次审查**: 生产环境部署后

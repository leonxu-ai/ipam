# 迁移快速参考卡片

## 迁移概览

```
迁移 0007: Subnet.is_global           ✅ 安全
迁移 0008: NetworkDevice.scan_interval ⚠️  建议添加约束
迁移 0009: IpAddress 跟踪字段         ⚠️  建议添加约束
```

---

## 一分钟评估

### ✅ 优点
- 所有字段都有安全默认值
- 关键字段已添加索引
- 完全可回滚
- 不会丢失现有数据

### ⚠️ 改进点
- 缺少数据库层 CHECK 约束（中等风险）
- 建议使用改进版本（*_v2.py.example）

### 🎯 推荐
**批准部署** - 建议使用改进版本

---

## 快速部署指南

### 步骤 1: 测试（开发环境）
```bash
# 应用迁移
python manage.py migrate ipam 0009

# 运行测试
python manage.py test ipam.tests.test_migrations

# 验证
python manage.py shell < scripts/verify_migrations.py
```

### 步骤 2: 验证（预生产环境）
```bash
# 克隆生产数据
# 执行迁移
# 验证业务功能
```

### 步骤 3: 部署（生产环境）
```bash
# 1. 备份数据库
pg_dump ipam_db > backup_$(date +%Y%m%d_%H%M%S).sql

# 2. 执行迁移（低峰期）
python manage.py migrate ipam 0009

# 3. 验证
python manage.py shell < scripts/verify_migrations.py
```

### 紧急回滚
```bash
# 回滚迁移
python manage.py migrate ipam 0006

# 如果失败，恢复备份
psql ipam_db < backup_20260105_020000.sql
```

---

## 迁移细节速查

### 迁移 0007
```python
# 新增字段
Subnet.is_global = BooleanField(default=False, db_index=True)

# 默认值：所有现有子网 = False
# 锁定时间：< 1 秒
# 风险等级：🟢 低
```

### 迁移 0008
```python
# 新增字段
NetworkDevice.scan_interval_minutes = IntegerField(
    default=30,
    validators=[MinValueValidator(1), MaxValueValidator(1440)]
)

# 默认值：所有现有设备 = 30
# 锁定时间：< 0.5 秒
# 风险等级：🟡 中低（建议添加 CHECK 约束）
```

### 迁移 0009
```python
# 新增字段 1
IpAddress.consecutive_missing = IntegerField(
    default=0,
    validators=[MinValueValidator(0)],
    db_index=True
)

# 新增字段 2
IpAddress.last_seen_at = DateTimeField(
    blank=True,
    null=True,
    db_index=True
)

# 默认值：consecutive_missing=0, last_seen_at=NULL
# 锁定时间：2-10 秒（取决于 IP 数量）
# 风险等级：🟡 中低（建议添加 CHECK 约束）
```

---

## 性能影响

| 表 | 锁定时间 | 索引数量 | 影响 |
|----|---------|---------|------|
| ipam_subnet | < 1s | +1 | 🟢 低 |
| ipam_networkdevice | < 0.5s | 0 | 🟢 低 |
| ipam_ipaddress | 2-10s | +2 | 🟡 中 |

**建议**: 在业务低峰期（如凌晨 2-4 点）执行

---

## 常见问题

### Q: 现有数据会丢失吗？
**A**: ❌ 不会。所有迁移都有安全默认值，不影响现有数据。

### Q: 能回滚吗？
**A**: ✅ 能。所有迁移都完全可回滚。

### Q: 缺少数据库约束有什么风险？
**A**: ⚠️ 中等风险。直接 SQL 操作可绕过验证器插入无效值。建议使用改进版本（*_v2.py.example）。

### Q: 大表迁移会锁表多久？
**A**: `ipam_ipaddress` 表可能锁定 2-10 秒。如果表超过 50 万条记录，建议使用在线迁移工具。

### Q: 如何使用改进版本？
**A**:
```bash
# 删除原版本
rm backend/ipam/migrations/0008_*.py
rm backend/ipam/migrations/0009_*.py

# 重命名改进版本
mv backend/ipam/migrations/0008_*_v2.py.example backend/ipam/migrations/0008_add_scan_interval_to_networkdevice.py
mv backend/ipam/migrations/0009_*_v2.py.example backend/ipam/migrations/0009_add_tracking_fields_to_ipaddress.py
```

---

## 关键文件位置

```
迁移文件:
  backend/ipam/migrations/0007_add_is_global_to_subnet.py
  backend/ipam/migrations/0008_add_scan_interval_to_networkdevice.py
  backend/ipam/migrations/0009_add_tracking_fields_to_ipaddress.py

改进版本:
  backend/ipam/migrations/0008_*_v2.py.example
  backend/ipam/migrations/0009_*_v2.py.example

测试工具:
  backend/ipam/tests/test_migrations.py
  scripts/verify_migrations.py

文档:
  docs/migration-review-report.md          (详细审查)
  docs/migration-best-practices.md         (最佳实践)
  docs/MIGRATION_REVIEW_SUMMARY.md         (总结报告)
```

---

## 检查清单

### 部署前
- [ ] 开发环境测试
- [ ] 运行单元测试
- [ ] 预生产验证
- [ ] 数据库备份
- [ ] 准备回滚脚本

### 部署中
- [ ] 选择低峰期
- [ ] 执行迁移
- [ ] 监控性能

### 部署后
- [ ] 验证数据完整性
- [ ] 测试核心功能
- [ ] 检查应用日志
- [ ] 监控系统性能

---

**需要帮助？** 查看完整文档：
- 详细审查: `docs/migration-review-report.md`
- 最佳实践: `docs/migration-best-practices.md`
- 总结报告: `docs/MIGRATION_REVIEW_SUMMARY.md`

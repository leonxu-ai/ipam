---
title: "审计日志详情 HTTP 500 错误 - 文件权限问题"
date: 2026-01-05
category: runtime-errors
severity: high
components:
  - Django
  - Docker
  - File Permissions
tags:
  - HTTP 500
  - PermissionError
  - exception_handlers.py
  - audit logs
status: solved
---

# 审计日志详情显示 HTTP 500 错误

## 问题症状

**错误表现**:
- 点击审计日志列表中的"详情"按钮
- 页面显示 "打开日志详情失败 HTTP 500"
- 前端调用 `/api/audit-logs/{id}/` 返回 500 错误

**用户影响**:
- 无法查看审计日志的详细信息
- 影响审计追踪功能

## 错误日志

```
PermissionError: [Errno 13] Permission denied: '/app/ipam_project/exception_handlers.py'
[05/Jan/2026 10:55:17] "GET /api/audit-logs/2/ HTTP/1.1" 500 164321
```

## 根本原因

### 技术分析

1. **文件权限问题**: `/opt/ipim/backend/ipam_project/exception_handlers.py` 的权限设置为 `600` (仅 root 可读写)
   ```bash
   -rw------- 1 root root 3846 Jan  5 02:13 /app/ipam_project/exception_handlers.py
   ```

2. **Django 进程无法读取**: Docker 容器内的 Django 进程以非 root 用户运行，无法读取该文件

3. **导入失败**: 当 API 请求触发异常处理时，Django 无法导入 `exception_handlers.py`，导致二次错误

### 为什么会发生

- 文件是在容器外（宿主机）创建的，默认权限为 600
- Docker 挂载时保留了原始文件权限
- Django 的异常处理机制需要读取该文件

## 解决方案

### 修复步骤

1. **修改文件权限** (在宿主机上):
   ```bash
   chmod 644 /opt/ipim/backend/ipam_project/exception_handlers.py
   ```

2. **重启容器**:
   ```bash
   docker compose restart web
   ```

3. **验证修复**:
   - 访问审计日志列表
   - 点击任意日志的"详情"按钮
   - 应该能正常显示日志详细信息

### 代码位置

**受影响文件**:
- `/opt/ipim/backend/ipam_project/exception_handlers.py` - 自定义异常处理器
- `/opt/ipim/backend/ipam_project/settings.py:146` - 配置异常处理器

**API 端点**:
- `GET /api/audit-logs/{id}/` - 审计日志详情 API

**前端调用**:
- `/opt/ipim/backend/templates/ipam/audit_log_list.html:309` - `showLogDetail()` 函数

## 预防策略

### 1. 在创建新文件时设置正确权限

**在宿主机创建文件时**:
```bash
# 创建文件
touch new_file.py

# 立即设置权限
chmod 644 new_file.py
```

### 2. Dockerfile 中明确设置权限

在 `Dockerfile` 中添加：
```dockerfile
# 确保 Python 文件可读
RUN find /app -name "*.py" -type f -exec chmod 644 {} \;
```

### 3. 使用 docker-compose 健康检查

在 `docker-compose.yml` 中添加：
```yaml
services:
  web:
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/api/audit-logs/"]
      interval: 30s
      timeout: 10s
      retries: 3
```

### 4. 添加文件权限检查脚本

创建 `scripts/check-permissions.sh`:
```bash
#!/bin/bash
# 检查关键 Python 文件权限
find backend -name "*.py" -type f ! -perm -644 -ls
```

## 相关问题

- Docker 文件挂载权限问题
- Django 异常处理器配置
- 容器内进程的用户权限

## 测试验证

### 手动测试
```bash
# 1. 检查文件权限
ls -la /opt/ipim/backend/ipam_project/exception_handlers.py

# 2. 在容器内测试导入
docker exec ipam-web python -c "from ipam_project.exception_handlers import custom_exception_handler"

# 3. 测试 API
curl -X GET http://localhost:8000/api/audit-logs/1/ -H "Authorization: Bearer <token>"
```

### 预期结果
- 文件权限应为 `-rw-r--r--` (644)
- Python 导入成功，无错误
- API 返回 200 状态码和 JSON 数据

## 参考资料

- [Django Exception Handling](https://docs.djangoproject.com/en/4.2/topics/http/views/#customizing-error-views)
- [Docker File Permissions](https://docs.docker.com/storage/bind-mounts/#configure-bind-propagation)
- [Linux File Permissions](https://www.linux.com/training-tutorials/understanding-linux-file-permissions/)

# 中创新航 IPAM 系统

企业级 IP 地址管理系统，用于中创新航工厂的网络 IP 资源管理。

## 系统概览

- **前端**: Django Templates + Tailwind CSS + Alpine.js
- **后端**: Django 4.2 LTS + Django REST Framework
- **数据库**: PostgreSQL 15
- **缓存/队列**: Redis 7 + Django-Q2
- **部署**: Docker Compose
- **特性**: 完全离线部署，无需互联网连接

## 功能特性

### IP 地址管理
- 4 种状态管理：可用、已分配、保留、冲突
- 并发安全分配（数据库行锁 + 重试机制）
- 可视化 256 格 IP 网格选择器
- 3 步骤分配向导

### 子网管理
- CIDR 格式支持
- 自动 IP 池初始化
- 使用率统计和监控

### SNMP 网络扫描
- 自动扫描（每 10 分钟）
- 支持 SNMPv2c / SNMPv3
- ARP 表解析
- MAC 地址冲突检测

### 审计日志
- 完整操作追踪
- 不可修改保护（数据库触发器）
- 按时间/操作类型筛选

### 仪表板
- 实时统计卡片
- IP 状态分布图表
- 高负载子网监控
- 最近操作日志

## 快速开始

### 前置要求

- Docker 20.10+
- Docker Compose 2.0+
- 4GB+ 可用内存

### 一键部署

```bash
# 1. 进入项目目录
cd /opt/ipim

# 2. 运行部署脚本
./scripts/deploy.sh
```

部署脚本将自动:
- 生成安全配置
- 构建 Docker 镜像
- 启动所有服务
- 初始化数据库
- 创建管理员账户

### 访问系统

- **前端界面**: http://10.21.111.129:8000
- **管理后台**: http://10.21.111.129:8000/admin/
- **API 文档**: http://10.21.111.129:8000/api/docs/

## 目录结构

```
/opt/ipim/
├── backend/                 # Django 后端应用
│   ├── ipam_project/       # Django 项目配置
│   ├── ipam/               # IPAM 核心应用
│   ├── templates/          # Django 模板
│   └── static/             # 静态文件
├── frontend/               # 前端构建工具
│   ├── src/               # Tailwind CSS 源文件
│   └── tailwind.config.js # Tailwind 配置
├── nginx/                  # Nginx 配置
├── scripts/                # 部署脚本
│   ├── deploy.sh          # 一键部署
│   ├── backup.sh          # 数据备份
│   └── restore.sh         # 数据恢复
├── secrets/                # 加密密钥（gitignore）
├── docker-compose.yml      # Docker 编排
├── Dockerfile              # 应用镜像
├── requirements.txt        # Python 依赖
└── .env.example           # 环境变量模板
```

## 手动部署

### 1. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，设置安全的密码
```

### 2. 生成加密密钥

```bash
mkdir -p secrets
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > secrets/snmp_encryption.key
chmod 600 secrets/snmp_encryption.key
```

### 3. 构建并启动

```bash
docker compose build
docker compose up -d
```

### 4. 初始化数据库

```bash
docker compose exec web python manage.py migrate
docker compose exec web python manage.py collectstatic --noinput
docker compose exec web python manage.py createsuperuser
```

## 常用命令

```bash
# 查看服务状态
docker compose ps

# 查看日志
docker compose logs -f

# 重启服务
docker compose restart

# 停止服务
docker compose down

# 备份数据
./scripts/backup.sh

# 恢复数据
./scripts/restore.sh /path/to/backup.sql.gz
```

## API 端点

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/subnets/` | GET, POST | 子网管理 |
| `/api/ip-addresses/` | GET, POST | IP 地址管理 |
| `/api/ip-addresses/{id}/allocate/` | POST | 分配 IP |
| `/api/ip-addresses/{id}/release/` | POST | 释放 IP |
| `/api/network-devices/` | GET, POST | 网络设备管理 |
| `/api/audit-logs/` | GET | 审计日志查询 |
| `/api/dashboard/stats/` | GET | 仪表板统计 |
| `/api/agent/system_context/` | GET | Agent 系统上下文 |

详细 API 文档请访问 `/api/docs/`

## 安全说明

- SNMP 凭证使用 Fernet 对称加密存储
- 加密密钥存储在独立文件（不纳入版本控制）
- 审计日志受数据库触发器保护，不可修改或删除
- 生产环境请务必修改默认密码

## 性能优化

- 数据库查询使用 `select_related` 优化
- IP 分配使用 `select_for_update` 行锁
- 静态文件使用 Nginx 缓存
- Tailwind CSS 使用 PurgeCSS 压缩

## 故障排除

### 服务无法启动

```bash
# 检查端口占用
netstat -tlnp | grep -E '8000|5432|6379'

# 检查 Docker 日志
docker compose logs web
```

### 数据库连接失败

```bash
# 检查 PostgreSQL 状态
docker compose exec db pg_isready

# 检查环境变量
docker compose exec web env | grep POSTGRES
```

### 静态文件 404

```bash
# 重新收集静态文件
docker compose exec web python manage.py collectstatic --noinput
```

## 技术支持

- 项目地址: /opt/ipim
- 部署目标: http://10.21.111.129

---

**版本**: 1.0.0
**更新日期**: 2024-01

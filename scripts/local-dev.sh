#!/bin/bash
# ========================================
# IPAM 本地开发环境启动脚本
# 无需 Docker，直接使用本地 Python
# ========================================

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "${GREEN}[INFO]${NC} $1"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }

cd /opt/ipim

# 创建必要目录
mkdir -p secrets logs

# 生成 SNMP 密钥（如果不存在）
if [ ! -f secrets/snmp_encryption.key ]; then
    python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > secrets/snmp_encryption.key
    chmod 600 secrets/snmp_encryption.key
    log_info "SNMP 加密密钥已生成"
fi

# 创建 .env 文件（如果不存在）
if [ ! -f .env ]; then
    cp .env.example .env
    log_info "已创建 .env 配置文件"
fi

# 检查 PostgreSQL
if command -v psql &> /dev/null; then
    log_info "检测到 PostgreSQL..."
else
    log_warn "未检测到 PostgreSQL，将使用 SQLite 数据库"
    # 修改 settings 使用 SQLite
    export DATABASE_URL="sqlite:///db.sqlite3"
fi

# 检查 Redis
if command -v redis-cli &> /dev/null && redis-cli ping &> /dev/null; then
    log_info "Redis 服务正在运行"
else
    log_warn "Redis 未运行，任务队列功能将不可用"
fi

cd backend

log_info "运行数据库迁移..."
python3 manage.py migrate --noinput 2>/dev/null || python3 manage.py migrate

log_info "收集静态文件..."
python3 manage.py collectstatic --noinput 2>/dev/null || true

# 检查是否有超级用户
SUPERUSER_EXISTS=$(python3 manage.py shell -c "from django.contrib.auth import get_user_model; User = get_user_model(); print(User.objects.filter(is_superuser=True).exists())" 2>/dev/null)

if [ "$SUPERUSER_EXISTS" != "True" ]; then
    log_info "创建管理员账户..."
    echo "用户名 (默认 admin):"
    read -r USERNAME
    USERNAME=${USERNAME:-admin}

    echo "密码:"
    read -s PASSWORD
    PASSWORD=${PASSWORD:-admin123}

    python3 manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='${USERNAME}').exists():
    User.objects.create_superuser('${USERNAME}', 'admin@example.com', '${PASSWORD}')
    print('管理员账户创建成功')
EOF
fi

log_info "启动开发服务器..."
log_info "访问地址: http://0.0.0.0:8000"
log_info "按 Ctrl+C 停止服务器"

python3 manage.py runserver 0.0.0.0:8000

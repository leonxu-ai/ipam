#!/bin/bash
# ========================================
# IPAM 系统一键部署脚本
# 适用于离线环境部署
# ========================================

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 检查 Docker 是否安装
check_docker() {
    log_info "检查 Docker 环境..."
    if ! command -v docker &> /dev/null; then
        log_error "Docker 未安装，请先安装 Docker"
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        log_error "Docker Compose 未安装，请先安装 Docker Compose"
        exit 1
    fi

    log_info "Docker 环境检查通过"
}

# 创建必要目录
create_directories() {
    log_info "创建必要目录..."
    mkdir -p secrets
    mkdir -p logs
    chmod 700 secrets
}

# 生成环境配置
setup_environment() {
    log_info "配置环境变量..."

    if [ ! -f .env ]; then
        cp .env.example .env

        # 生成随机 SECRET_KEY
        SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))" 2>/dev/null || openssl rand -base64 50 | tr -d '\n')
        sed -i "s/your-secret-key-here-change-in-production/${SECRET_KEY}/" .env

        # 生成随机数据库密码
        DB_PASSWORD=$(python3 -c "import secrets; print(secrets.token_urlsafe(24))" 2>/dev/null || openssl rand -base64 24 | tr -d '\n')
        sed -i "s/ipam_password_change_me/${DB_PASSWORD}/" .env

        log_info "已生成 .env 配置文件"
    else
        log_warn ".env 文件已存在，跳过生成"
    fi
}

# 生成 SNMP 加密密钥
generate_snmp_key() {
    log_info "生成 SNMP 加密密钥..."

    if [ ! -f secrets/snmp_encryption.key ]; then
        python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > secrets/snmp_encryption.key
        chmod 600 secrets/snmp_encryption.key
        log_info "SNMP 加密密钥已生成"
    else
        log_warn "SNMP 加密密钥已存在，跳过生成"
    fi
}

# 构建并启动服务
start_services() {
    log_info "构建 Docker 镜像..."
    docker compose build --no-cache

    log_info "启动服务..."
    docker compose up -d

    log_info "等待服务启动..."
    sleep 10

    # 检查服务状态
    docker compose ps
}

# 初始化数据库
init_database() {
    log_info "初始化数据库..."

    # 运行迁移
    docker compose exec -T web python manage.py migrate --noinput

    # 收集静态文件
    docker compose exec -T web python manage.py collectstatic --noinput

    log_info "数据库初始化完成"
}

# 创建超级用户
create_superuser() {
    log_info "创建管理员账户..."

    echo "请输入管理员用户名 (默认: admin):"
    read -r ADMIN_USER
    ADMIN_USER=${ADMIN_USER:-admin}

    echo "请输入管理员邮箱 (默认: admin@example.com):"
    read -r ADMIN_EMAIL
    ADMIN_EMAIL=${ADMIN_EMAIL:-admin@example.com}

    echo "请输入管理员密码:"
    read -s ADMIN_PASSWORD

    docker compose exec -T web python manage.py shell << EOF
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='${ADMIN_USER}').exists():
    User.objects.create_superuser('${ADMIN_USER}', '${ADMIN_EMAIL}', '${ADMIN_PASSWORD}')
    print('管理员账户创建成功')
else:
    print('管理员账户已存在')
EOF
}

# 显示部署信息
show_info() {
    echo ""
    echo "=========================================="
    echo -e "${GREEN}IPAM 系统部署完成!${NC}"
    echo "=========================================="
    echo ""
    echo "访问地址: http://10.21.111.129:8000"
    echo "管理后台: http://10.21.111.129:8000/admin/"
    echo "API 文档: http://10.21.111.129:8000/api/docs/"
    echo ""
    echo "常用命令:"
    echo "  docker compose ps          # 查看服务状态"
    echo "  docker compose logs -f     # 查看日志"
    echo "  docker compose restart     # 重启服务"
    echo "  docker compose down        # 停止服务"
    echo ""
}

# 主流程
main() {
    log_info "开始部署 IPAM 系统..."

    cd "$(dirname "$0")/.."

    check_docker
    create_directories
    setup_environment
    generate_snmp_key
    start_services
    init_database

    echo ""
    echo "是否创建管理员账户? (y/n)"
    read -r CREATE_ADMIN
    if [ "$CREATE_ADMIN" = "y" ] || [ "$CREATE_ADMIN" = "Y" ]; then
        create_superuser
    fi

    show_info
}

main "$@"

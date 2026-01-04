#!/bin/bash
# ========================================
# IPAM 系统恢复脚本
# ========================================

set -e

BACKUP_DIR="/opt/ipim/backups"

# 颜色输出
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# 显示可用备份
show_backups() {
    echo "可用的备份文件:"
    ls -lt "${BACKUP_DIR}/"*_db.sql.gz 2>/dev/null | head -10 || echo "未找到备份文件"
}

# 恢复数据库
restore_database() {
    local BACKUP_FILE=$1

    if [ ! -f "$BACKUP_FILE" ]; then
        log_error "备份文件不存在: $BACKUP_FILE"
        exit 1
    fi

    log_warn "警告：这将覆盖现有数据库数据!"
    echo "确认要恢复吗? (输入 'yes' 确认)"
    read -r CONFIRM
    if [ "$CONFIRM" != "yes" ]; then
        log_info "操作已取消"
        exit 0
    fi

    cd /opt/ipim

    log_info "停止 Web 服务..."
    docker compose stop web worker

    log_info "恢复数据库..."
    gunzip -c "$BACKUP_FILE" | docker compose exec -T db psql -U ipam_user -d ipam_db

    log_info "启动 Web 服务..."
    docker compose start web worker

    log_info "数据库恢复完成"
}

# 主流程
main() {
    if [ -z "$1" ]; then
        show_backups
        echo ""
        echo "用法: $0 <备份文件路径>"
        echo "示例: $0 /opt/ipim/backups/ipam_backup_20240104_120000_db.sql.gz"
        exit 1
    fi

    restore_database "$1"
}

main "$@"

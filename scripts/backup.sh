#!/bin/bash
# ========================================
# IPAM 系统备份脚本
# ========================================

set -e

BACKUP_DIR="/opt/ipim/backups"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_NAME="ipam_backup_${TIMESTAMP}"

# 颜色输出
GREEN='\033[0;32m'
NC='\033[0m'

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

# 创建备份目录
mkdir -p "${BACKUP_DIR}"

cd /opt/ipim

log_info "开始备份 IPAM 系统..."

# 备份数据库
log_info "备份 PostgreSQL 数据库..."
docker compose exec -T db pg_dump -U ipam_user ipam_db | gzip > "${BACKUP_DIR}/${BACKUP_NAME}_db.sql.gz"

# 备份配置文件
log_info "备份配置文件..."
tar -czf "${BACKUP_DIR}/${BACKUP_NAME}_config.tar.gz" \
    .env \
    secrets/ \
    nginx/

# 备份静态文件（可选）
# log_info "备份静态文件..."
# docker compose exec -T web tar -czf - /app/staticfiles | gzip > "${BACKUP_DIR}/${BACKUP_NAME}_static.tar.gz"

# 清理旧备份（保留最近7天）
log_info "清理过期备份..."
find "${BACKUP_DIR}" -name "ipam_backup_*" -mtime +7 -delete

log_info "备份完成: ${BACKUP_DIR}/${BACKUP_NAME}_*"

# 显示备份文件
ls -lh "${BACKUP_DIR}/${BACKUP_NAME}"*

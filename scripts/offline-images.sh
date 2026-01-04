#!/bin/bash
# ========================================
# Docker 离线镜像导出/导入脚本
# 用于无网络环境的部署
# ========================================

set -e

IMAGES_DIR="/opt/ipim/docker-images"
IMAGES=(
    "python:3.9-slim"
    "postgres:15-alpine"
    "redis:7-alpine"
    "nginx:alpine"
)

export_images() {
    echo "导出 Docker 镜像..."
    mkdir -p "$IMAGES_DIR"

    for image in "${IMAGES[@]}"; do
        echo "拉取镜像: $image"
        docker pull "$image"

        filename=$(echo "$image" | tr ':/' '_').tar
        echo "导出: $filename"
        docker save "$image" -o "$IMAGES_DIR/$filename"
    done

    echo "所有镜像已导出到: $IMAGES_DIR"
    ls -lh "$IMAGES_DIR"
}

import_images() {
    echo "导入 Docker 镜像..."

    if [ ! -d "$IMAGES_DIR" ]; then
        echo "错误: 找不到镜像目录 $IMAGES_DIR"
        exit 1
    fi

    for tarfile in "$IMAGES_DIR"/*.tar; do
        if [ -f "$tarfile" ]; then
            echo "导入: $tarfile"
            docker load -i "$tarfile"
        fi
    done

    echo "所有镜像已导入"
    docker images
}

case "$1" in
    export)
        export_images
        ;;
    import)
        import_images
        ;;
    *)
        echo "用法: $0 {export|import}"
        echo ""
        echo "  export - 在有网络的机器上导出镜像"
        echo "  import - 在离线机器上导入镜像"
        exit 1
        ;;
esac

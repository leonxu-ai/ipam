#!/bin/bash
# ========================================
# 配置 Docker 使用国内镜像加速
# ========================================

set -e

echo "配置 Docker 镜像加速..."

# 创建或更新 Docker daemon 配置
mkdir -p /etc/docker

cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.mirrors.ustc.edu.cn",
    "https://hub-mirror.c.163.com",
    "https://mirror.baidubce.com"
  ],
  "log-driver": "json-file",
  "log-opts": {
    "max-size": "100m",
    "max-file": "3"
  }
}
EOF

echo "重启 Docker 服务..."
systemctl daemon-reload
systemctl restart docker

echo "验证配置..."
docker info | grep -A5 "Registry Mirrors"

echo "Docker 镜像加速配置完成!"

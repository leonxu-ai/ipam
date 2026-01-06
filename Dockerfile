# Python 3.9 基础镜像（与中创新航生产环境兼容）
FROM python:3.9-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# 设置工作目录
WORKDIR /app

# 使用国内镜像源加速（阿里云）
RUN sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list.d/debian.sources 2>/dev/null || \
    sed -i 's/deb.debian.org/mirrors.aliyun.com/g' /etc/apt/sources.list 2>/dev/null || true

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    iputils-ping \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# 配置 pip 使用国内镜像
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/ && \
    pip config set global.trusted-host mirrors.aliyun.com

# 复制依赖文件（利用 Docker 缓存）
COPY requirements.txt .

# 安装 Python 依赖
RUN pip install -r requirements.txt

# 创建非 root 用户（在复制代码之前创建，利用缓存）
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/staticfiles /app/secrets && \
    chown -R appuser:appuser /app

# 复制应用代码
COPY --chown=appuser:appuser backend/ .

# 切换到非 root 用户
USER appuser

# 收集静态文件（如果需要）
RUN python manage.py collectstatic --noinput 2>/dev/null || true

# 暴露端口
EXPOSE 8000

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health/ || exit 1

# 默认命令
CMD ["gunicorn", "ipam_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4", "--threads", "2", "--timeout", "120"]

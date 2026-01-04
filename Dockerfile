# Python 3.9 基础镜像（与中创新航生产环境兼容）
FROM python:3.9-slim

# 设置环境变量
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .

# 安装 Python 依赖（包含gunicorn生产服务器）
RUN pip install --no-cache-dir -r requirements.txt

# 复制应用代码
COPY backend/ .

# 创建非 root 用户
RUN useradd -m -u 1000 appuser && \
    mkdir -p /app/staticfiles /app/secrets && \
    chown -R appuser:appuser /app

# 切换到非 root 用户
USER appuser

# 收集静态文件
RUN python manage.py collectstatic --noinput --settings=ipam_project.settings 2>/dev/null || true

# 暴露端口
EXPOSE 8000

# 默认命令
CMD ["gunicorn", "ipam_project.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "4"]

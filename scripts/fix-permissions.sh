#!/bin/bash
# 修复项目文件权限的脚本
# 用于解决 Docker 容器中的 Permission denied 错误

set -e

PROJECT_DIR="${1:-/opt/ipim}"

echo "=== 修复 IPAM 项目文件权限 ==="
echo "项目目录: $PROJECT_DIR"
echo ""

# 修复目录权限
echo "1. 修复目录权限为 755..."
find "$PROJECT_DIR/backend" -type d -exec chmod 755 {} \;

# 修复 Python 文件权限
echo "2. 修复 Python 文件权限为 644..."
find "$PROJECT_DIR/backend" -type f -name "*.py" -exec chmod 644 {} \;

# 修复模板文件权限
echo "3. 修复模板文件权限为 644..."
find "$PROJECT_DIR/backend" -type f -name "*.html" -exec chmod 644 {} \;

# 修复静态文件权限
echo "4. 修复静态文件权限为 644..."
find "$PROJECT_DIR/backend" -type f \( -name "*.css" -o -name "*.js" -o -name "*.json" \) -exec chmod 644 {} \;

# 修复配置文件权限
echo "5. 修复配置文件权限为 644..."
find "$PROJECT_DIR" -maxdepth 1 -type f \( -name "*.yml" -o -name "*.yaml" -o -name "*.txt" -o -name "*.md" \) -exec chmod 644 {} \;

# 验证
echo ""
echo "=== 验证结果 ==="
PROBLEM_FILES=$(find "$PROJECT_DIR/backend" -type f \( -name "*.py" -o -name "*.html" \) ! -perm -004 2>/dev/null | wc -l)
if [ "$PROBLEM_FILES" -eq 0 ]; then
    echo "✅ 所有文件权限已修复"
else
    echo "⚠️  仍有 $PROBLEM_FILES 个文件存在权限问题"
    find "$PROJECT_DIR/backend" -type f \( -name "*.py" -o -name "*.html" \) ! -perm -004 2>/dev/null
fi

echo ""
echo "提示: 如果使用 Docker，请重启容器以应用更改:"
echo "  docker restart ipam-web ipam-worker"

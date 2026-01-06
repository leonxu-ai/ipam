# fix: API JSON 解析错误和 SNMP 模块导入失败

## Overview

修复两个相关 bug：
1. **JSON 解析错误**：普通用户（如 xuliang）调用 API 时出现 `SyntaxError: Unexpected token '<', "<!DOCTYPE "... is not valid JSON`
2. **SNMP 扫描失败**：点击扫描按钮报错 `No module named 'pyasn1.compat.octets'`

## Problem Statement / Motivation

### Bug 1: API 返回 HTML 而非 JSON

**根本原因**：
- 当用户会话过期或权限不足时，Django/DRF 返回 HTML 错误页面（登录页或 403 页面）
- 前端 JavaScript `fetch()` 调用直接执行 `response.json()` 而不检查 HTTP 状态码
- 结果：HTML 被当作 JSON 解析，导致 `SyntaxError`

**影响范围**：
- 所有前端 fetch 调用（IP 分配、设备扫描、释放 IP 等）
- 会话超时后的所有 API 请求
- 普通用户尝试访问管理员 API

### Bug 2: pyasn1 模块缺失

**根本原因**：
- `pyasn1` 0.6.1 版本删除了 `pyasn1/compat/octets.py` 文件（破坏性变更）
- `pysnmp-lextudio` 6.0.4 仍依赖 `from pyasn1.compat.octets import octs2ints`
- 导入链：`pysnmp/debug.py` → `pyasn1.compat.octets` → 失败

**影响范围**：
- 所有 SNMP 扫描功能
- 网络设备发现和 MAC 地址更新

## Proposed Solution

### 方案 A: API 错误处理（必须）

1. 创建自定义 DRF 异常处理器，确保所有 API 端点返回 JSON
2. 在前端添加统一的 `apiFetch()` 封装函数
3. 修改所有 fetch 调用使用新的封装函数

### 方案 B: SNMP 依赖修复（必须）

1. 锁定 `pyasn1==0.6.0`（0.6.1 之前的版本）
2. 更新 `requirements.txt`

## Technical Approach

### Phase 1: 后端异常处理器

**1.1 创建自定义异常处理器**

```python
# /opt/ipim/backend/ipam_project/exception_handlers.py

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import PermissionDenied
from django.http import Http404


def custom_api_exception_handler(exc, context):
    """
    自定义 DRF 异常处理器，确保 API 端点始终返回 JSON 响应
    """
    # 调用 DRF 默认异常处理器
    response = exception_handler(exc, context)

    if response is not None:
        # 标准化响应格式
        response.data = {
            'success': False,
            'status_code': response.status_code,
            'message': response.data.get('detail', str(response.data)),
            'errors': response.data if isinstance(response.data, dict) else None,
        }
        return response

    # 处理 Django 原生异常
    if isinstance(exc, Http404):
        return Response(
            {
                'success': False,
                'status_code': 404,
                'message': '资源未找到',
            },
            status=status.HTTP_404_NOT_FOUND
        )

    if isinstance(exc, PermissionDenied):
        return Response(
            {
                'success': False,
                'status_code': 403,
                'message': '无权限访问',
            },
            status=status.HTTP_403_FORBIDDEN
        )

    # 未处理的异常返回 500
    return Response(
        {
            'success': False,
            'status_code': 500,
            'message': '服务器内部错误',
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )
```

**1.2 更新 settings.py**

```python
# /opt/ipim/backend/ipam_project/settings.py

REST_FRAMEWORK = {
    # ... 现有配置 ...
    'EXCEPTION_HANDLER': 'ipam_project.exception_handlers.custom_api_exception_handler',
}
```

### Phase 2: 前端统一错误处理

**2.1 在 base.html 添加全局 API 封装函数**

```javascript
// 添加到 base.html 的 <script> 标签内

window.getCsrfToken = function() {
    return document.querySelector('[name=csrfmiddlewaretoken]')?.value ||
           document.cookie.split('; ')
               .find(row => row.startsWith('csrftoken='))
               ?.split('=')[1] ||
           '';
};

window.apiFetch = async function(url, options = {}) {
    const headers = {
        'Content-Type': 'application/json',
        ...options.headers
    };

    // 对于非安全方法添加 CSRF token
    const unsafeMethods = ['POST', 'PUT', 'PATCH', 'DELETE'];
    const method = (options.method || 'GET').toUpperCase();

    if (unsafeMethods.includes(method)) {
        headers['X-CSRFToken'] = window.getCsrfToken();
    }

    try {
        const response = await fetch(url, {
            ...options,
            headers,
            credentials: 'same-origin'
        });

        // 处理认证错误 - 先检查状态码再解析 JSON
        if (response.status === 401 || response.status === 403) {
            // 尝试解析 JSON 响应
            let errorMsg = '会话已过期或权限不足';
            try {
                const data = await response.json();
                errorMsg = data.message || data.detail || errorMsg;
            } catch (e) {
                // 如果不是 JSON，使用默认消息
            }

            if (response.status === 401) {
                // 会话过期，跳转登录
                alert('会话已过期，请重新登录');
                window.location.href = '/login/?next=' + encodeURIComponent(window.location.pathname);
                throw new Error('Authentication required');
            } else {
                // 权限不足
                throw new Error(errorMsg);
            }
        }

        // 处理其他错误
        if (!response.ok) {
            let errorMsg = '请求失败';
            try {
                const data = await response.json();
                errorMsg = data.message || data.detail || errorMsg;
            } catch (e) {
                errorMsg = `HTTP ${response.status}`;
            }
            throw new Error(errorMsg);
        }

        return await response.json();

    } catch (error) {
        if (error.name === 'TypeError' && error.message.includes('Failed to fetch')) {
            throw new Error('网络连接失败，请检查网络');
        }
        throw error;
    }
};
```

**2.2 更新各模板的 fetch 调用**

需要修改的文件列表：
- `ip_allocate.html` - IP 分配
- `ip_detail.html` - IP 详情页的释放/冲突解决
- `ip_list.html` - IP 列表的释放
- `subnet_detail.html` - 子网详情的 IP 释放
- `device_list.html` - 设备扫描
- `audit_log_list.html` - 审计日志详情

### Phase 3: SNMP 依赖修复

**3.1 更新 requirements.txt**

```diff
# /opt/ipim/requirements.txt

- pysnmp-lextudio==6.0.4
+ pysnmp-lextudio==6.0.4
+ pyasn1==0.6.0  # 锁定版本，0.6.1 删除了 compat.octets 模块
```

**3.2 重新安装依赖**

```bash
pip install 'pyasn1==0.6.0' --force-reinstall
```

## Acceptance Criteria

### Functional Requirements

- [ ] 未登录用户访问 API 返回 JSON 格式的 401 响应
- [ ] 会话过期后 API 请求返回 JSON 格式的 401 响应
- [ ] 权限不足时返回 JSON 格式的 403 响应
- [ ] 前端正确处理 401/403 错误，显示友好提示
- [ ] 401 错误后自动跳转到登录页面
- [ ] SNMP 扫描功能正常工作，无模块导入错误
- [ ] 单设备扫描和批量扫描都能正常执行

### Non-Functional Requirements

- [ ] 错误响应时间 < 100ms
- [ ] 不影响正常 API 响应的性能
- [ ] 日志记录所有认证失败事件

### Quality Gates

- [ ] 所有现有测试通过
- [ ] 手动测试覆盖所有 fetch 调用场景
- [ ] pyasn1 版本锁定不影响其他依赖

## Dependencies & Prerequisites

- Django 4.2.11
- Django REST Framework 3.14.0
- pysnmp-lextudio 6.0.4
- pyasn1 需要降级到 0.6.0

## Risk Analysis & Mitigation

| 风险 | 概率 | 影响 | 缓解措施 |
|------|------|------|----------|
| pyasn1 降级影响其他库 | 低 | 高 | 运行完整测试套件验证 |
| 遗漏部分 fetch 调用 | 中 | 中 | 全局搜索所有 fetch( 调用 |
| 异常处理器遗漏某些错误类型 | 低 | 中 | 添加兜底的 500 处理 |

## File Changes Summary

| 文件 | 变更类型 | 说明 |
|------|---------|------|
| `ipam_project/exception_handlers.py` | 新建 | 自定义 DRF 异常处理器 |
| `ipam_project/settings.py` | 修改 | 添加 EXCEPTION_HANDLER 配置 |
| `templates/base.html` | 修改 | 添加全局 apiFetch 函数 |
| `templates/ipam/ip_allocate.html` | 修改 | 使用 apiFetch |
| `templates/ipam/ip_detail.html` | 修改 | 使用 apiFetch |
| `templates/ipam/ip_list.html` | 修改 | 使用 apiFetch |
| `templates/ipam/subnet_detail.html` | 修改 | 使用 apiFetch |
| `templates/ipam/device_list.html` | 修改 | 使用 apiFetch |
| `templates/ipam/audit_log_list.html` | 修改 | 使用 apiFetch |
| `requirements.txt` | 修改 | 添加 pyasn1==0.6.0 |

## References & Research

### Internal References
- `ipam_project/settings.py:184-190` - 当前 DRF 配置
- `ipam/views.py:46,90,282,388,434,580` - ViewSet 权限声明
- `templates/ipam/device_list.html:666-671` - 现有 getCsrfToken 实现
- `templates/ipam/ip_allocate.html:569-596` - fetch 调用示例

### External References
- [DRF Authentication](https://www.django-rest-framework.org/api-guide/authentication/)
- [DRF Exceptions](https://www.django-rest-framework.org/api-guide/exceptions/)
- [pyasn1 GitHub Issue #76](https://github.com/pyasn1/pyasn1/issues/76)
- [pysnmp Changelog](https://docs.lextudio.com/pysnmp/v7.1/changelog)

---

Generated with [Claude Code](https://claude.com/claude-code)

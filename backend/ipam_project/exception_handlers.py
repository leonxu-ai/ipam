"""
自定义 DRF 异常处理器

确保所有 API 端点始终返回 JSON 响应，即使在认证失败或权限不足的情况下。
解决前端 fetch() 解析 HTML 响应导致的 SyntaxError 问题。
"""

from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from django.core.exceptions import PermissionDenied
from django.http import Http404
import logging

logger = logging.getLogger(__name__)


def custom_api_exception_handler(exc, context):
    """
    自定义 DRF 异常处理器，确保 API 端点始终返回 JSON 响应。

    处理场景：
    1. DRF 标准异常（401, 403, 404, 400 等）
    2. Django 原生异常（Http404, PermissionDenied）
    3. 未捕获的异常（返回 500）
    """
    # 获取请求信息用于日志
    request = context.get('request')
    view = context.get('view')

    # 调用 DRF 默认异常处理器
    response = exception_handler(exc, context)

    if response is not None:
        # DRF 已处理的异常，标准化响应格式
        error_detail = response.data.get('detail') if isinstance(response.data, dict) else None

        if error_detail:
            message = str(error_detail)
        elif isinstance(response.data, dict):
            # 处理字段验证错误
            messages = []
            for field, errors in response.data.items():
                if isinstance(errors, list):
                    messages.extend([f"{field}: {e}" for e in errors])
                else:
                    messages.append(f"{field}: {errors}")
            message = '; '.join(messages) if messages else '请求失败'
        elif isinstance(response.data, list):
            message = '; '.join([str(e) for e in response.data])
        else:
            message = str(response.data)

        response.data = {
            'success': False,
            'status_code': response.status_code,
            'message': message,
            'errors': response.data if isinstance(response.data, dict) and 'detail' not in response.data else None,
        }

        # 记录认证失败日志
        if response.status_code in (401, 403):
            logger.warning(
                f"认证/权限失败: {response.status_code} - {message} - "
                f"Path: {request.path if request else 'unknown'} - "
                f"User: {request.user if request else 'unknown'}"
            )

        return response

    # 处理 Django 原生异常
    if isinstance(exc, Http404):
        logger.info(f"资源未找到: {request.path if request else 'unknown'}")
        return Response(
            {
                'success': False,
                'status_code': 404,
                'message': '资源未找到',
                'errors': None,
            },
            status=status.HTTP_404_NOT_FOUND
        )

    if isinstance(exc, PermissionDenied):
        logger.warning(
            f"权限拒绝: {request.path if request else 'unknown'} - "
            f"User: {request.user if request else 'unknown'}"
        )
        return Response(
            {
                'success': False,
                'status_code': 403,
                'message': '无权限访问',
                'errors': None,
            },
            status=status.HTTP_403_FORBIDDEN
        )

    # 未处理的异常返回 500
    logger.exception(
        f"服务器内部错误: {exc.__class__.__name__}: {exc} - "
        f"Path: {request.path if request else 'unknown'} - "
        f"View: {view.__class__.__name__ if view else 'unknown'}"
    )

    return Response(
        {
            'success': False,
            'status_code': 500,
            'message': '服务器内部错误',
            'errors': None,
        },
        status=status.HTTP_500_INTERNAL_SERVER_ERROR
    )

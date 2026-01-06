"""
IPAM应用URL路由配置
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import (
    SubnetViewSet,
    IpAddressViewSet,
    NetworkDeviceViewSet,
    AuditLogViewSet,
    DashboardViewSet,
    AgentViewSet,
)
from . import frontend_views

# DRF路由器
router = DefaultRouter()
router.register(r"subnets", SubnetViewSet, basename="subnet")
router.register(r"ip-addresses", IpAddressViewSet, basename="ipaddress")
router.register(r"network-devices", NetworkDeviceViewSet, basename="networkdevice")
router.register(r"audit-logs", AuditLogViewSet, basename="auditlog")
router.register(r"dashboard", DashboardViewSet, basename="dashboard")
router.register(r"agent", AgentViewSet, basename="agent")

app_name = "ipam"

urlpatterns = [
    # API路由
    path("api/", include(router.urls)),

    # 前端页面路由
    path("", frontend_views.index, name="index"),
    path("dashboard/", frontend_views.dashboard, name="dashboard"),
    path("my-allocations/", frontend_views.my_allocations, name="my_allocations"),
    path("ping-test/", frontend_views.ping_test, name="ping_test"),

    # 子网管理
    path("subnets/", frontend_views.subnet_list, name="subnet_list"),
    path("subnets/create/", frontend_views.subnet_create, name="subnet_create"),
    path("subnets/<int:pk>/", frontend_views.subnet_detail, name="subnet_detail"),
    path("subnets/<int:pk>/edit/", frontend_views.subnet_edit, name="subnet_edit"),
    path("subnets/<int:pk>/delete/", frontend_views.subnet_delete, name="subnet_delete"),
    path("subnets/<int:pk>/init-pool/", frontend_views.subnet_init_pool, name="subnet_init_pool"),

    # IP管理
    path("ips/", frontend_views.ip_list, name="ip_list"),
    path("ips/<int:pk>/", frontend_views.ip_detail, name="ip_detail"),
    path("ips/allocate/", frontend_views.ip_allocate, name="ip_allocate"),
    path("ips/allocate/<int:subnet_pk>/", frontend_views.ip_allocate, name="ip_allocate_subnet"),

    # 网络设备
    path("devices/", frontend_views.device_list, name="device_list"),

    # 审计日志
    path("audit-logs/", frontend_views.audit_log_list, name="audit_log_list"),

    # 用户管理
    path("users/", frontend_views.user_list, name="user_list"),
    path("users/create/", frontend_views.user_create, name="user_create"),
    path("users/<int:pk>/edit/", frontend_views.user_edit, name="user_edit"),
    path("users/<int:pk>/delete/", frontend_views.user_delete, name="user_delete"),
    path("users/<int:pk>/toggle-active/", frontend_views.user_toggle_active, name="user_toggle_active"),

    # 密码修改（无需登录）
    path("password-change/", frontend_views.password_change, name="password_change"),
]

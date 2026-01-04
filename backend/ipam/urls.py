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
    path("", frontend_views.dashboard, name="dashboard"),
    path("subnets/", frontend_views.subnet_list, name="subnet_list"),
    path("subnets/<int:pk>/", frontend_views.subnet_detail, name="subnet_detail"),
    path("ips/", frontend_views.ip_list, name="ip_list"),
    path("ips/<int:pk>/", frontend_views.ip_detail, name="ip_detail"),
    path("ips/allocate/", frontend_views.ip_allocate, name="ip_allocate"),
    path("ips/allocate/<int:subnet_pk>/", frontend_views.ip_allocate, name="ip_allocate_subnet"),
    path("devices/", frontend_views.device_list, name="device_list"),
    path("audit-logs/", frontend_views.audit_log_list, name="audit_log_list"),
]

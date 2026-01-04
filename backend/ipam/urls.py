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
    path("api/", include(router.urls)),
]

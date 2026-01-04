"""
IPAM API视图层
"""

from __future__ import annotations

from typing import Any
from django.db.models import QuerySet, Count, Q
from django.core.exceptions import ValidationError as DjangoValidationError
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes

from .models import Subnet, IpAddress, NetworkDevice, AuditLog
from .serializers import (
    SubnetSerializer,
    SubnetInitializeSerializer,
    IpAddressSerializer,
    IpAddressListSerializer,
    IpAddressAllocationSerializer,
    IpAddressReleaseSerializer,
    NetworkDeviceSerializer,
    AuditLogSerializer,
)
from .services import IPAllocationService, ConflictDetectionService


@extend_schema_view(
    list=extend_schema(summary="获取子网列表", tags=["Subnet"]),
    retrieve=extend_schema(summary="获取子网详情", tags=["Subnet"]),
    create=extend_schema(summary="创建子网", tags=["Subnet"]),
    update=extend_schema(summary="更新子网", tags=["Subnet"]),
    partial_update=extend_schema(summary="部分更新子网", tags=["Subnet"]),
    destroy=extend_schema(summary="删除子网", tags=["Subnet"]),
)
class SubnetViewSet(viewsets.ModelViewSet):
    """子网管理API"""

    queryset = Subnet.objects.all().order_by("-created_at")
    serializer_class = SubnetSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["vlan_id"]
    search_fields = ["network", "description"]

    @extend_schema(
        summary="初始化子网IP地址池",
        description="为指定子网生成所有IP地址记录",
        request=SubnetInitializeSerializer,
        responses={200: {"type": "object", "properties": {"count": {"type": "integer"}}}},
        tags=["Subnet"],
    )
    @action(detail=True, methods=["post"])
    def initialize_ips(self, request: Request, pk: int = None) -> Response:
        """
        初始化子网IP地址池

        为子网生成所有IP地址记录（状态为available）
        """
        subnet = self.get_object()
        serializer = SubnetInitializeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            count = subnet.initialize_ip_pool(**serializer.validated_data)
            return Response(
                {"message": f"成功初始化{count}个IP地址", "count": count},
                status=status.HTTP_200_OK,
            )
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(summary="获取IP地址列表（轻量级）", tags=["IP Address"]),
    retrieve=extend_schema(summary="获取IP地址详情", tags=["IP Address"]),
    create=extend_schema(summary="创建IP地址记录", tags=["IP Address"]),
    update=extend_schema(summary="更新IP地址信息", tags=["IP Address"]),
    partial_update=extend_schema(summary="部分更新IP地址", tags=["IP Address"]),
    destroy=extend_schema(summary="删除IP地址记录", tags=["IP Address"]),
)
class IpAddressViewSet(viewsets.ModelViewSet):
    """IP地址管理API"""

    queryset = IpAddress.objects.select_related("subnet", "allocated_by").all()
    permission_classes = [IsAuthenticated]
    filterset_fields = ["subnet", "status", "device_type"]
    search_fields = ["address", "hostname", "mac_address", "responsible_person"]

    def get_serializer_class(self):
        """根据action选择序列化器"""
        if self.action == "list":
            return IpAddressListSerializer
        return IpAddressSerializer

    def get_queryset(self) -> QuerySet:
        """优化查询性能"""
        queryset = super().get_queryset()
        if self.action == "list":
            # 列表视图只选择必要字段
            return queryset.only(
                "id",
                "address",
                "status",
                "hostname",
                "mac_address",
                "device_type",
                "allocated_at",
                "subnet__network",
            )
        return queryset

    @extend_schema(
        summary="分配IP地址",
        description="将指定IP地址分配给设备",
        request=IpAddressAllocationSerializer,
        responses={200: IpAddressSerializer},
        tags=["IP Address"],
    )
    @action(detail=False, methods=["post"])
    def allocate(self, request: Request) -> Response:
        """
        分配IP地址

        将指定IP地址分配给设备（并发安全）
        """
        serializer = IpAddressAllocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ip = IPAllocationService.allocate_ip(
                user=request.user, **serializer.validated_data
            )
            return Response(
                IpAddressSerializer(ip).data, status=status.HTTP_200_OK
            )
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="释放IP地址",
        description="释放已分配的IP地址",
        request=IpAddressReleaseSerializer,
        responses={200: IpAddressSerializer},
        tags=["IP Address"],
    )
    @action(detail=False, methods=["post"])
    def release(self, request: Request) -> Response:
        """
        释放IP地址

        将已分配的IP地址释放为可用状态
        """
        serializer = IpAddressReleaseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            ip = IPAllocationService.release_ip(
                user=request.user, **serializer.validated_data
            )
            return Response(
                IpAddressSerializer(ip).data, status=status.HTTP_200_OK
            )
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @extend_schema(
        summary="获取子网可用IP列表",
        description="获取指定子网中所有可用的IP地址",
        parameters=[
            OpenApiParameter(
                name="subnet_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="子网ID",
            )
        ],
        responses={200: IpAddressListSerializer(many=True)},
        tags=["IP Address"],
    )
    @action(detail=False, methods=["get"])
    def available_by_subnet(self, request: Request) -> Response:
        """
        获取子网可用IP列表

        返回指定子网中所有状态为available的IP地址
        """
        subnet_id = request.query_params.get("subnet_id")
        if not subnet_id:
            return Response(
                {"error": "subnet_id参数必填"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            subnet_id_int = int(subnet_id)
            ips = IpAddress.objects.filter(
                subnet_id=subnet_id_int, status="available"
            ).order_by("address")

            serializer = IpAddressListSerializer(ips, many=True)
            return Response(serializer.data, status=status.HTTP_200_OK)
        except ValueError:
            return Response(
                {"error": "subnet_id必须为整数"}, status=status.HTTP_400_BAD_REQUEST
            )

    @extend_schema(
        summary="解决IP冲突",
        description="解决MAC地址冲突的IP",
        request={
            "type": "object",
            "properties": {
                "ip_id": {"type": "integer"},
                "resolution": {
                    "type": "string",
                    "enum": ["keep_current", "update_mac", "release"],
                },
            },
        },
        responses={200: IpAddressSerializer},
        tags=["IP Address"],
    )
    @action(detail=False, methods=["post"])
    def resolve_conflict(self, request: Request) -> Response:
        """
        解决IP冲突

        可选解决方案：keep_current（保留当前）/update_mac（更新MAC）/release（释放）
        """
        ip_id = request.data.get("ip_id")
        resolution = request.data.get("resolution", "keep_current")

        if not ip_id:
            return Response(
                {"error": "ip_id参数必填"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            ip = ConflictDetectionService.resolve_conflict(
                ip_id=ip_id, user=request.user, resolution=resolution
            )
            return Response(
                IpAddressSerializer(ip).data, status=status.HTTP_200_OK
            )
        except DjangoValidationError as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)


@extend_schema_view(
    list=extend_schema(summary="获取网络设备列表", tags=["Network Device"]),
    retrieve=extend_schema(summary="获取网络设备详情", tags=["Network Device"]),
    create=extend_schema(summary="创建网络设备", tags=["Network Device"]),
    update=extend_schema(summary="更新网络设备", tags=["Network Device"]),
    partial_update=extend_schema(summary="部分更新网络设备", tags=["Network Device"]),
    destroy=extend_schema(summary="删除网络设备", tags=["Network Device"]),
)
class NetworkDeviceViewSet(viewsets.ModelViewSet):
    """网络设备管理API（SNMP扫描源）"""

    queryset = NetworkDevice.objects.all().order_by("-created_at")
    serializer_class = NetworkDeviceSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["enabled", "snmp_version", "last_scan_status"]
    search_fields = ["name", "ip_address"]

    @extend_schema(
        summary="启用设备扫描",
        description="启用指定设备的SNMP扫描",
        request=None,
        responses={200: NetworkDeviceSerializer},
        tags=["Network Device"],
    )
    @action(detail=True, methods=["post"])
    def enable(self, request: Request, pk: int = None) -> Response:
        """启用设备扫描"""
        device = self.get_object()
        device.enabled = True
        device.save()
        return Response(
            NetworkDeviceSerializer(device).data, status=status.HTTP_200_OK
        )

    @extend_schema(
        summary="禁用设备扫描",
        description="禁用指定设备的SNMP扫描",
        request=None,
        responses={200: NetworkDeviceSerializer},
        tags=["Network Device"],
    )
    @action(detail=True, methods=["post"])
    def disable(self, request: Request, pk: int = None) -> Response:
        """禁用设备扫描"""
        device = self.get_object()
        device.enabled = False
        device.save()
        return Response(
            NetworkDeviceSerializer(device).data, status=status.HTTP_200_OK
        )


@extend_schema_view(
    list=extend_schema(summary="获取审计日志列表", tags=["Audit Log"]),
    retrieve=extend_schema(summary="获取审计日志详情", tags=["Audit Log"]),
)
class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    """审计日志查询API（只读）"""

    queryset = AuditLog.objects.select_related("user").all().order_by("-timestamp")
    serializer_class = AuditLogSerializer
    permission_classes = [IsAuthenticated]
    filterset_fields = ["action", "user", "ip_address"]
    search_fields = ["ip_address", "hostname", "mac_address"]

    @extend_schema(
        summary="按时间范围查询审计日志",
        description="查询指定时间范围内的审计日志",
        parameters=[
            OpenApiParameter(
                name="start_date",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description="开始时间（ISO 8601格式）",
            ),
            OpenApiParameter(
                name="end_date",
                type=OpenApiTypes.DATETIME,
                location=OpenApiParameter.QUERY,
                required=False,
                description="结束时间（ISO 8601格式）",
            ),
        ],
        responses={200: AuditLogSerializer(many=True)},
        tags=["Audit Log"],
    )
    @action(detail=False, methods=["get"])
    def by_date_range(self, request: Request) -> Response:
        """按时间范围查询"""
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        queryset = self.get_queryset()

        if start_date:
            queryset = queryset.filter(timestamp__gte=start_date)
        if end_date:
            queryset = queryset.filter(timestamp__lte=end_date)

        serializer = self.get_serializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class DashboardViewSet(viewsets.ViewSet):
    """仪表板统计API"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="获取仪表板统计数据",
        description="获取IP使用率、子网统计、设备统计等",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "ip_stats": {
                        "type": "object",
                        "properties": {
                            "total": {"type": "integer"},
                            "available": {"type": "integer"},
                            "allocated": {"type": "integer"},
                            "reserved": {"type": "integer"},
                            "conflict": {"type": "integer"},
                            "usage_rate": {"type": "number"},
                        },
                    },
                    "subnet_stats": {
                        "type": "object",
                        "properties": {"total": {"type": "integer"}},
                    },
                    "device_stats": {
                        "type": "object",
                        "properties": {
                            "total": {"type": "integer"},
                            "enabled": {"type": "integer"},
                        },
                    },
                    "recent_allocations": {"type": "integer"},
                    "conflict_count": {"type": "integer"},
                },
            }
        },
        tags=["Dashboard"],
    )
    @action(detail=False, methods=["get"])
    def stats(self, request: Request) -> Response:
        """
        获取仪表板统计数据

        返回IP使用统计、子网数量、设备数量等
        """
        # IP地址统计
        ip_stats = IpAddress.objects.aggregate(
            total=Count("id"),
            available=Count("id", filter=Q(status="available")),
            allocated=Count("id", filter=Q(status="allocated")),
            reserved=Count("id", filter=Q(status="reserved")),
            conflict=Count("id", filter=Q(status="conflict")),
        )

        # 计算使用率
        if ip_stats["total"] > 0:
            usage_rate = (
                (ip_stats["allocated"] + ip_stats["reserved"])
                / ip_stats["total"]
                * 100
            )
        else:
            usage_rate = 0.0

        ip_stats["usage_rate"] = round(usage_rate, 2)

        # 子网统计
        subnet_stats = {"total": Subnet.objects.count()}

        # 设备统计
        device_stats = {
            "total": NetworkDevice.objects.count(),
            "enabled": NetworkDevice.objects.filter(enabled=True).count(),
        }

        # 最近24小时分配数量
        yesterday = timezone.now() - timezone.timedelta(days=1)
        recent_allocations = IpAddress.objects.filter(
            allocated_at__gte=yesterday
        ).count()

        # 冲突数量
        conflict_count = IpAddress.objects.filter(status="conflict").count()

        return Response(
            {
                "ip_stats": ip_stats,
                "subnet_stats": subnet_stats,
                "device_stats": device_stats,
                "recent_allocations": recent_allocations,
                "conflict_count": conflict_count,
            },
            status=status.HTTP_200_OK,
        )

    @extend_schema(
        summary="获取子网使用率排行",
        description="获取所有子网的IP使用率排行（降序）",
        responses={
            200: {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "subnet_id": {"type": "integer"},
                        "network": {"type": "string"},
                        "total_ips": {"type": "integer"},
                        "allocated_count": {"type": "integer"},
                        "usage_rate": {"type": "number"},
                    },
                },
            }
        },
        tags=["Dashboard"],
    )
    @action(detail=False, methods=["get"])
    def subnet_usage_ranking(self, request: Request) -> Response:
        """
        获取子网使用率排行

        返回所有子网的使用率统计，按使用率降序排列
        """
        subnets = Subnet.objects.all()
        ranking = []

        for subnet in subnets:
            stats = subnet.get_usage_stats()
            ranking.append(
                {
                    "subnet_id": subnet.id,
                    "network": subnet.network,
                    "total_ips": stats["total_ips"],
                    "allocated_count": stats["allocated_count"],
                    "usage_rate": stats["usage_rate"],
                }
            )

        # 按使用率降序排序
        ranking.sort(key=lambda x: x["usage_rate"], reverse=True)

        return Response(ranking, status=status.HTTP_200_OK)


class AgentViewSet(viewsets.ViewSet):
    """Agent系统提示API"""

    permission_classes = [IsAuthenticated]

    @extend_schema(
        summary="获取Agent系统上下文",
        description="获取当前IPAM系统状态的完整上下文，供AI Agent使用",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "context": {"type": "string"},
                },
            }
        },
        tags=["Agent"],
    )
    @action(detail=False, methods=["get"])
    def system_context(self, request: Request) -> Response:
        """获取完整的系统上下文"""
        from .agent_prompts import AgentPromptGenerator

        context = AgentPromptGenerator.generate_system_context()
        return Response({"context": context}, status=status.HTTP_200_OK)

    @extend_schema(
        summary="获取子网分配上下文",
        description="获取针对特定子网的分配上下文",
        parameters=[
            OpenApiParameter(
                name="subnet_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="子网ID",
            )
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "context": {"type": "string"},
                },
            }
        },
        tags=["Agent"],
    )
    @action(detail=False, methods=["get"])
    def allocation_context(self, request: Request) -> Response:
        """获取子网分配上下文"""
        from .agent_prompts import AgentPromptGenerator

        subnet_id = request.query_params.get("subnet_id")
        if not subnet_id:
            return Response(
                {"error": "subnet_id参数必填"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            context = AgentPromptGenerator.generate_allocation_context(int(subnet_id))
            return Response({"context": context}, status=status.HTTP_200_OK)
        except ValueError:
            return Response(
                {"error": "subnet_id必须为整数"}, status=status.HTTP_400_BAD_REQUEST
            )

    @extend_schema(
        summary="获取冲突解决上下文",
        description="获取针对特定冲突IP的解决上下文",
        parameters=[
            OpenApiParameter(
                name="ip_id",
                type=OpenApiTypes.INT,
                location=OpenApiParameter.QUERY,
                required=True,
                description="IP地址记录ID",
            )
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "context": {"type": "string"},
                },
            }
        },
        tags=["Agent"],
    )
    @action(detail=False, methods=["get"])
    def conflict_context(self, request: Request) -> Response:
        """获取冲突解决上下文"""
        from .agent_prompts import AgentPromptGenerator

        ip_id = request.query_params.get("ip_id")
        if not ip_id:
            return Response(
                {"error": "ip_id参数必填"}, status=status.HTTP_400_BAD_REQUEST
            )

        try:
            context = AgentPromptGenerator.generate_conflict_resolution_context(int(ip_id))
            return Response({"context": context}, status=status.HTTP_200_OK)
        except ValueError:
            return Response(
                {"error": "ip_id必须为整数"}, status=status.HTTP_400_BAD_REQUEST
            )

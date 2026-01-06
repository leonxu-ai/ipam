"""
IPAM API视图层
"""

from __future__ import annotations

from typing import Any
import csv
from django.db.models import QuerySet, Count, Q
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import HttpResponse
from django.utils import timezone
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.pagination import PageNumberPagination
from drf_spectacular.utils import extend_schema, extend_schema_view, OpenApiParameter
from drf_spectacular.types import OpenApiTypes


class LargeResultsPagination(PageNumberPagination):
    """允许大数据量的分页器，用于IP地址列表"""
    page_size = 100
    page_size_query_param = 'page_size'
    max_page_size = 2048  # 支持最多2048个结果（足够覆盖大多数子网）

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
    pagination_class = LargeResultsPagination  # 使用允许大数据量的分页器
    filterset_fields = ["subnet", "status", "device_type"]
    search_fields = ["address", "hostname", "mac_address", "responsible_person"]

    def get_serializer_class(self):
        """根据action选择序列化器"""
        if self.action == "list":
            return IpAddressListSerializer
        return IpAddressSerializer

    def get_queryset(self) -> QuerySet:
        """优化查询性能"""
        if self.action == "list":
            # 列表视图使用轻量级查询，不需要 allocated_by
            return IpAddress.objects.select_related("subnet").only(
                "id",
                "address",
                "status",
                "hostname",
                "mac_address",
                "device_type",
                "allocated_at",
                "subnet__network",
            )
        return super().get_queryset()

    @extend_schema(
        summary="分配IP地址",
        description="将指定IP地址分配给设备",
        request=IpAddressAllocationSerializer,
        responses={200: IpAddressSerializer},
        tags=["IP Address"],
    )
    @action(detail=True, methods=["post"])
    def allocate(self, request: Request, pk=None) -> Response:
        """
        分配IP地址

        将指定IP地址分配给设备（并发安全）
        """
        ip_address = self.get_object()

        # 检查 IP 是否可用（available 或 occupied 都可以分配）
        if ip_address.status not in ("available", "occupied"):
            return Response(
                {"error": f"IP地址 {ip_address.address} 状态为 {ip_address.status}，无法分配"},
                status=status.HTTP_400_BAD_REQUEST
            )

        # 更新 IP 地址信息（包括位置信息，跟随设备）
        ip_address.status = request.data.get("status", "allocated")
        ip_address.hostname = request.data.get("hostname", "")
        ip_address.mac_address = request.data.get("mac_address", "")
        ip_address.device_type = request.data.get("device_type", "")
        ip_address.notes = request.data.get("notes", "")
        ip_address.building = request.data.get("building", "")
        ip_address.floor = request.data.get("floor") or None
        ip_address.allocated_by = request.user
        ip_address.allocated_at = timezone.now()
        ip_address.save()

        # 记录审计日志
        AuditLog.objects.create(
            user=request.user,
            action="allocate",
            subnet=ip_address.subnet,
            subnet_network=ip_address.subnet.network if ip_address.subnet else "",
            ip_address=ip_address.address,
            hostname=ip_address.hostname,
            mac_address=ip_address.mac_address,
            details={
                "device_type": ip_address.device_type,
            }
        )

        return Response(IpAddressSerializer(ip_address).data, status=status.HTTP_200_OK)

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
        summary="Ping测试IP地址",
        description="对指定IP地址执行Ping测试，返回可达性和响应时间",
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean", "description": "测试是否成功执行"},
                    "reachable": {"type": "boolean", "description": "IP是否可达"},
                    "response_time_ms": {"type": "number", "description": "平均响应时间(ms)"},
                    "packet_loss": {"type": "number", "description": "丢包率(%)"},
                    "message": {"type": "string", "description": "结果消息"},
                },
            }
        },
        tags=["IP Address"],
    )
    @action(detail=True, methods=["post"])
    def ping_test(self, request: Request, pk=None) -> Response:
        """
        Ping测试IP地址

        通过SSH连接到核心交换机执行Ping测试
        支持 switch_index=-1 测试所有交换机
        """
        from .switch_ping import ping_via_switch, ping_via_all_switches, get_available_switches

        ip_address = self.get_object()
        target_ip = str(ip_address.address)
        switch_index = request.data.get("switch_index", 0)

        try:
            switch_index = int(switch_index)
        except (ValueError, TypeError):
            switch_index = 0

        # switch_index = -1 表示测试所有交换机
        if switch_index == -1:
            all_results = ping_via_all_switches(target_ip, count=4)

            any_reachable = any(r.get("reachable", False) for r in all_results)
            all_success = all(r.get("success", False) for r in all_results)
            switch_names = [r.get("switch_name", "") for r in all_results]

            response_data = {
                "success": all_success,
                "reachable": any_reachable,
                "target_ip": target_ip,
                "switch_name": " + ".join(switch_names),
                "switch_ip": "",
                "packet_sent": sum(r.get("packet_sent", 0) for r in all_results),
                "packet_received": sum(r.get("packet_received", 0) for r in all_results),
                "packet_loss": 0 if any_reachable else 100.0,
                "response_time_ms": None,
                "min_time_ms": None,
                "max_time_ms": None,
                "message": "",
                "raw_output": "",
                "all_results": all_results,
                "available_switches": get_available_switches(),
            }

            valid_times = [r.get("avg_time") for r in all_results if r.get("avg_time")]
            if valid_times:
                response_data["response_time_ms"] = round(sum(valid_times) / len(valid_times), 2)

            reachable_switches = [r.get("switch_name") for r in all_results if r.get("reachable")]
            if any_reachable:
                response_data["message"] = f"可达 (通过: {', '.join(reachable_switches)})"
                if response_data["response_time_ms"]:
                    response_data["message"] += f", 平均延迟: {response_data['response_time_ms']}ms"
            else:
                response_data["message"] = "所有交换机测试均不可达"

            return Response(response_data, status=status.HTTP_200_OK)

        # 单台交换机测试
        result = ping_via_switch(target_ip, switch_index, count=4)

        response_data = {
            "success": result.get("success", False),
            "reachable": result.get("reachable", False),
            "target_ip": target_ip,
            "switch_name": result.get("switch_name", ""),
            "switch_ip": result.get("switch_ip", ""),
            "packet_sent": result.get("packet_sent", 0),
            "packet_received": result.get("packet_received", 0),
            "packet_loss": result.get("packet_loss", 100.0),
            "response_time_ms": result.get("avg_time"),
            "min_time_ms": result.get("min_time"),
            "max_time_ms": result.get("max_time"),
            "message": result.get("message", ""),
            "raw_output": result.get("raw_output", ""),
            "available_switches": get_available_switches(),
        }

        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="快速Ping测试",
        description="通过IP地址字符串执行Ping测试（无需先查找IP记录）",
        request={
            "type": "object",
            "properties": {
                "target_ip": {"type": "string", "description": "要测试的IP地址"},
            },
            "required": ["target_ip"],
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "success": {"type": "boolean"},
                    "reachable": {"type": "boolean"},
                    "response_time_ms": {"type": "number"},
                    "packet_loss": {"type": "number"},
                    "message": {"type": "string"},
                },
            }
        },
        tags=["IP Address"],
    )
    @action(detail=False, methods=["post"])
    def quick_ping(self, request: Request) -> Response:
        """
        快速Ping测试

        通过SSH连接到核心交换机执行Ping测试
        支持选择不同的交换机进行测试
        """
        import ipaddress as ip_lib
        from .switch_ping import ping_via_switch, get_available_switches

        target_ip = request.data.get("target_ip", "").strip()
        switch_index = request.data.get("switch_index", 0)  # 默认使用第一台交换机

        if not target_ip:
            return Response({"error": "请提供target_ip参数"}, status=status.HTTP_400_BAD_REQUEST)

        # 验证IP地址格式
        try:
            ip_lib.ip_address(target_ip)
        except ValueError:
            return Response({"error": "无效的IP地址格式"}, status=status.HTTP_400_BAD_REQUEST)

        # 转换switch_index为整数
        try:
            switch_index = int(switch_index)
        except (ValueError, TypeError):
            switch_index = 0

        # switch_index = -1 表示测试所有交换机
        if switch_index == -1:
            from .switch_ping import ping_via_all_switches
            all_results = ping_via_all_switches(target_ip, count=4)

            # 汇总所有交换机的结果
            any_reachable = any(r.get("reachable", False) for r in all_results)
            all_success = all(r.get("success", False) for r in all_results)
            switch_names = [r.get("switch_name", "") for r in all_results]

            response_data = {
                "success": all_success,
                "reachable": any_reachable,
                "target_ip": target_ip,
                "switch_name": " + ".join(switch_names),
                "switch_ip": "",
                "packet_sent": sum(r.get("packet_sent", 0) for r in all_results),
                "packet_received": sum(r.get("packet_received", 0) for r in all_results),
                "packet_loss": 0 if any_reachable else 100.0,
                "response_time_ms": None,
                "min_time_ms": None,
                "max_time_ms": None,
                "message": "",
                "raw_output": "",
                "all_results": all_results,  # 返回每台交换机的详细结果
                "available_switches": get_available_switches(),
            }

            # 计算平均响应时间
            valid_times = [r.get("avg_time") for r in all_results if r.get("avg_time")]
            if valid_times:
                response_data["response_time_ms"] = round(sum(valid_times) / len(valid_times), 2)

            # 生成汇总消息
            reachable_switches = [r.get("switch_name") for r in all_results if r.get("reachable")]
            unreachable_switches = [r.get("switch_name") for r in all_results if not r.get("reachable") and r.get("success")]

            if any_reachable:
                response_data["message"] = f"可达 (通过: {', '.join(reachable_switches)})"
                if response_data["response_time_ms"]:
                    response_data["message"] += f", 平均延迟: {response_data['response_time_ms']}ms"
            else:
                response_data["message"] = "所有交换机测试均不可达"

            return Response(response_data, status=status.HTTP_200_OK)

        # 单台交换机测试
        result = ping_via_switch(target_ip, switch_index, count=4)

        # 格式化返回结果
        response_data = {
            "success": result.get("success", False),
            "reachable": result.get("reachable", False),
            "target_ip": target_ip,
            "switch_name": result.get("switch_name", ""),
            "switch_ip": result.get("switch_ip", ""),
            "packet_sent": result.get("packet_sent", 0),
            "packet_received": result.get("packet_received", 0),
            "packet_loss": result.get("packet_loss", 100.0),
            "response_time_ms": result.get("avg_time"),
            "min_time_ms": result.get("min_time"),
            "max_time_ms": result.get("max_time"),
            "message": result.get("message", ""),
            "raw_output": result.get("raw_output", ""),
            "available_switches": get_available_switches(),
        }

        return Response(response_data, status=status.HTTP_200_OK)

    @extend_schema(
        summary="获取可用交换机列表",
        description="返回可用于Ping测试的核心交换机列表",
        responses={200: {"type": "array", "items": {"type": "object"}}},
        tags=["IP Address"],
    )
    @action(detail=False, methods=["get"])
    def available_switches(self, request: Request) -> Response:
        """获取可用交换机列表"""
        from .switch_ping import get_available_switches
        return Response(get_available_switches(), status=status.HTTP_200_OK)

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
                "ip_id": {"type": "integer", "description": "IP地址记录ID"},
                "resolution": {
                    "type": "string",
                    "enum": ["keep_current", "update_mac", "release"],
                    "description": "解决方案：keep_current保留当前MAC/update_mac更新为扫描MAC/release释放IP",
                },
                "scanned_mac": {
                    "type": "string",
                    "description": "扫描检测到的MAC地址（update_mac时需要）",
                },
            },
            "required": ["ip_id"],
        },
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "message": {"type": "string"},
                    "data": {"$ref": "#/components/schemas/IpAddress"},
                },
            }
        },
        tags=["IP Address"],
    )
    @action(detail=False, methods=["post"])
    def resolve_conflict(self, request: Request) -> Response:
        """
        解决IP冲突

        可选解决方案：
        - keep_current: 保留当前配置，恢复为已分配状态
        - update_mac: 更新为扫描检测到的MAC地址
        - release: 释放此IP地址
        """
        ip_id = request.data.get("ip_id")
        resolution = request.data.get("resolution", "keep_current")
        scanned_mac = request.data.get("scanned_mac")

        if not ip_id:
            return Response(
                {"status": "error", "message": "ip_id参数必填"},
                status=status.HTTP_400_BAD_REQUEST
            )

        try:
            ip = ConflictDetectionService.resolve_conflict(
                ip_id=ip_id,
                user=request.user,
                resolution=resolution,
                scanned_mac=scanned_mac
            )
            return Response({
                "status": "success",
                "message": f"冲突已解决: {ip.address}",
                "data": IpAddressSerializer(ip).data
            }, status=status.HTTP_200_OK)
        except DjangoValidationError as e:
            return Response(
                {"status": "error", "message": str(e)},
                status=status.HTTP_400_BAD_REQUEST
            )


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

    @extend_schema(
        summary="扫描单个网络设备",
        description="触发 SNMP 扫描并返回扫描结果",
        request=None,
        responses={
            200: {
                "type": "object",
                "properties": {
                    "status": {"type": "string"},
                    "device": {"type": "string"},
                    "scanned": {"type": "integer"},
                    "updated": {"type": "integer"},
                    "conflicts": {"type": "integer"},
                    "elapsed": {"type": "number"},
                },
            }
        },
        tags=["Network Device"],
    )
    @action(detail=True, methods=["post"])
    def scan(self, request: Request, pk: int = None) -> Response:
        """扫描单个设备"""
        import time

        device = self.get_object()

        try:
            from .snmp_scanner import SNMPScanner

            start_time = time.time()
            scanner = SNMPScanner(device)
            scanned, updated, conflicts = scanner.scan_and_update()
            elapsed = time.time() - start_time

            # 更新设备的扫描状态
            device.last_scan_status = "success"
            device.last_scan_error = ""
            device.save()

            return Response({
                "status": "success",
                "device": device.name,
                "scanned": scanned,
                "updated": updated,
                "conflicts": conflicts,
                "elapsed": round(elapsed, 2),
            })
        except Exception as e:
            device.last_scan_status = "error"
            device.last_scan_error = str(e)[:500]
            device.save()

            return Response({
                "status": "error",
                "device": device.name,
                "error": str(e),
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


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

    @extend_schema(
        summary="导出审计日志为CSV",
        description="将审计日志导出为CSV文件，支持筛选条件",
        parameters=[
            OpenApiParameter(
                name="q",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="搜索关键词（IP、用户等）",
            ),
            OpenApiParameter(
                name="action",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=False,
                description="操作类型筛选",
            ),
            OpenApiParameter(
                name="start_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description="开始日期",
            ),
            OpenApiParameter(
                name="end_date",
                type=OpenApiTypes.DATE,
                location=OpenApiParameter.QUERY,
                required=False,
                description="结束日期",
            ),
        ],
        responses={200: {"type": "string", "format": "binary"}},
        tags=["Audit Log"],
    )
    @action(detail=False, methods=["get"])
    def export(self, request: Request) -> HttpResponse:
        """导出审计日志为CSV文件"""
        queryset = self.get_queryset()

        # 应用筛选条件
        search = request.query_params.get("q")
        action_filter = request.query_params.get("action")
        start_date = request.query_params.get("start_date")
        end_date = request.query_params.get("end_date")

        if search:
            queryset = queryset.filter(
                Q(ip_address__icontains=search) |
                Q(hostname__icontains=search) |
                Q(mac_address__icontains=search) |
                Q(user__username__icontains=search)
            )

        if action_filter:
            queryset = queryset.filter(action=action_filter)

        if start_date:
            queryset = queryset.filter(timestamp__date__gte=start_date)

        if end_date:
            queryset = queryset.filter(timestamp__date__lte=end_date)

        # 创建CSV响应
        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="audit_logs_{timezone.now().strftime("%Y%m%d_%H%M%S")}.csv"'

        # 写入UTF-8 BOM以支持Excel正确显示中文
        response.write('\ufeff')

        writer = csv.writer(response)
        # 写入表头
        writer.writerow(["时间", "操作", "操作员", "IP地址", "主机名", "MAC地址", "子网", "详情"])

        # 操作类型映射
        action_names = {
            "allocate": "分配",
            "release": "释放",
            "update": "更新",
            "conflict_detected": "冲突检测",
            "conflict_resolved": "冲突解决",
            "scan": "扫描",
            "device_discovered": "设备发现",
            "device_changed": "设备变更",
        }

        # 写入数据
        for log in queryset[:10000]:  # 限制最多导出10000条
            writer.writerow([
                log.timestamp.strftime("%Y-%m-%d %H:%M:%S") if log.timestamp else "",
                action_names.get(log.action, log.action),
                log.user.username if log.user else "系统",
                log.ip_address or "",
                log.hostname or "",
                log.mac_address or "",
                log.subnet_network or (log.subnet.network if log.subnet else ""),
                str(log.details) if log.details else "",
            ])

        return response


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

    @extend_schema(
        summary="扫描所有网络设备",
        description="启动异步任务扫描所有启用的设备",
        request=None,
        responses={
            202: {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "device_count": {"type": "integer"},
                },
            }
        },
        tags=["Agent"],
    )
    @action(detail=False, methods=["post"])
    def scan_all(self, request: Request) -> Response:
        """扫描所有设备"""
        import uuid

        # 获取启用的设备数量
        device_count = NetworkDevice.objects.filter(enabled=True).count()

        if device_count == 0:
            return Response({
                "status": "error",
                "error": "没有启用的设备可供扫描",
            }, status=status.HTTP_400_BAD_REQUEST)

        # 生成任务 ID
        task_id = str(uuid.uuid4())

        # 尝试使用 Django-Q2 异步任务
        try:
            from django_q.tasks import async_task

            async_task(
                'ipam.tasks.scan_all_with_progress',
                task_id,
                task_name=f'scan_all_{task_id}',
                group='snmp_scan',
            )
        except Exception:
            # 如果 Django-Q 不可用，同步执行
            from django.core.cache import cache
            from .tasks import scan_all_with_progress

            # 在后台线程中执行
            import threading

            def run_scan():
                scan_all_with_progress(task_id)

            thread = threading.Thread(target=run_scan)
            thread.daemon = True
            thread.start()

        return Response({
            "task_id": task_id,
            "status": "queued",
            "device_count": device_count,
        }, status=status.HTTP_202_ACCEPTED)

    @extend_schema(
        summary="查询扫描任务状态",
        description="获取扫描任务的进度和结果",
        parameters=[
            OpenApiParameter(
                name="task_id",
                type=OpenApiTypes.STR,
                location=OpenApiParameter.QUERY,
                required=True,
                description="任务 ID",
            )
        ],
        responses={
            200: {
                "type": "object",
                "properties": {
                    "task_id": {"type": "string"},
                    "status": {"type": "string"},
                    "progress": {"type": "integer"},
                    "message": {"type": "string"},
                },
            }
        },
        tags=["Agent"],
    )
    @action(detail=False, methods=["get"])
    def scan_status(self, request: Request) -> Response:
        """查询扫描状态"""
        task_id = request.query_params.get('task_id')
        if not task_id:
            return Response({"error": "task_id 参数必填"}, status=status.HTTP_400_BAD_REQUEST)

        from django.core.cache import cache

        # 从缓存获取进度
        progress = cache.get(f'scan_progress_{task_id}')

        if progress:
            return Response(progress)

        # 任务可能还未开始
        return Response({
            "task_id": task_id,
            "status": "pending",
            "progress": 0,
            "message": "任务排队中...",
        })

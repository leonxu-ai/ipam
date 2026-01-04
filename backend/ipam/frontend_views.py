"""
IPAM前端视图（Django模板渲染）
"""

from __future__ import annotations

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth import logout
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from datetime import timedelta

from .models import Subnet, IpAddress, NetworkDevice, AuditLog


@login_required
def dashboard(request):
    """仪表板页面"""
    # IP统计
    ip_stats = IpAddress.objects.aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status="available")),
        allocated=Count("id", filter=Q(status="allocated")),
        reserved=Count("id", filter=Q(status="reserved")),
        conflict=Count("id", filter=Q(status="conflict")),
    )

    # 计算使用率
    total = ip_stats["total"] or 0
    if total > 0:
        usage_rate = ((ip_stats["allocated"] + ip_stats["reserved"]) / total) * 100
    else:
        usage_rate = 0.0

    # 子网统计
    subnet_count = Subnet.objects.count()

    # 高负载子网
    subnets = Subnet.objects.all()
    high_usage_subnets = []
    for subnet in subnets:
        stats = subnet.get_usage_stats()
        if stats["total_ips"] > 0:
            high_usage_subnets.append({
                "id": subnet.id,
                "network": subnet.network,
                "description": subnet.description or subnet.network,
                "usage_rate": stats["usage_rate"],
                "available": stats["available_count"],
            })
    # 按使用率排序
    high_usage_subnets.sort(key=lambda x: x["usage_rate"], reverse=True)

    # 最近操作日志
    recent_logs = AuditLog.objects.select_related("user").order_by("-timestamp")[:10]

    # 最近24小时新分配数
    yesterday = timezone.now() - timedelta(days=1)
    recent_allocations = IpAddress.objects.filter(allocated_at__gte=yesterday).count()

    context = {
        "ip_stats": ip_stats,
        "usage_rate": round(usage_rate, 1),
        "subnet_count": subnet_count,
        "high_usage_subnets": high_usage_subnets[:5],
        "recent_logs": recent_logs,
        "recent_allocations": recent_allocations,
    }

    return render(request, "ipam/dashboard.html", context)


@login_required
def subnet_list(request):
    """子网列表页面"""
    subnets = Subnet.objects.all().order_by("-created_at")

    # 添加使用统计
    subnet_data = []
    for subnet in subnets:
        stats = subnet.get_usage_stats()
        subnet_data.append({
            "subnet": subnet,
            "stats": stats,
        })

    context = {
        "subnets": subnet_data,
    }
    return render(request, "ipam/subnet_list.html", context)


@login_required
def subnet_detail(request, pk):
    """子网详情页面"""
    subnet = get_object_or_404(Subnet, pk=pk)
    stats = subnet.get_usage_stats()

    # 获取该子网的所有IP（用于网格显示）
    ips = IpAddress.objects.filter(subnet=subnet).order_by("address")

    # 获取已分配的IP（用于列表显示）
    allocated_ips = IpAddress.objects.filter(
        subnet=subnet,
        status__in=["allocated", "reserved", "conflict"]
    ).select_related("allocated_by").order_by("address")

    context = {
        "subnet": subnet,
        "stats": stats,
        "ips": ips,
        "allocated_ips": allocated_ips,
    }
    return render(request, "ipam/subnet_detail.html", context)


@login_required
def ip_list(request):
    """IP地址列表页面"""
    # 过滤参数
    status_filter = request.GET.get("status", "")
    subnet_filter = request.GET.get("subnet", "")
    search = request.GET.get("q", "")

    ips = IpAddress.objects.select_related("subnet", "allocated_by").all()

    if status_filter:
        ips = ips.filter(status=status_filter)
    if subnet_filter:
        ips = ips.filter(subnet_id=subnet_filter)
    if search:
        ips = ips.filter(
            Q(address__icontains=search) |
            Q(hostname__icontains=search) |
            Q(mac_address__icontains=search) |
            Q(responsible_person__icontains=search)
        )

    ips = ips.order_by("address")[:200]  # 限制数量

    # 获取子网列表供过滤
    subnets = Subnet.objects.all()

    context = {
        "ips": ips,
        "subnets": subnets,
        "status_filter": status_filter,
        "subnet_filter": subnet_filter,
        "search": search,
    }
    return render(request, "ipam/ip_list.html", context)


@login_required
def ip_detail(request, pk):
    """IP详情页面"""
    ip = get_object_or_404(IpAddress.objects.select_related("subnet", "allocated_by"), pk=pk)

    # 获取该IP的审计日志
    audit_logs = AuditLog.objects.filter(ip_address=ip.address).select_related("user").order_by("-timestamp")[:20]

    context = {
        "ip": ip,
        "audit_logs": audit_logs,
    }
    return render(request, "ipam/ip_detail.html", context)


@login_required
def ip_allocate(request, subnet_pk=None):
    """IP分配向导页面"""
    # 获取预设子网
    preset_subnet = None
    preset_ip = None

    if subnet_pk:
        preset_subnet = get_object_or_404(Subnet, pk=subnet_pk)
        # 添加可用IP数量
        preset_subnet.available_count = IpAddress.objects.filter(
            subnet=preset_subnet, status="available"
        ).count()

    # 检查是否有预设IP
    ip_id = request.GET.get("ip")
    if ip_id:
        preset_ip = get_object_or_404(IpAddress.objects.select_related("subnet"), pk=ip_id)
        preset_subnet = preset_ip.subnet
        preset_subnet.available_count = IpAddress.objects.filter(
            subnet=preset_subnet, status="available"
        ).count()

    # 获取所有子网及其统计
    subnets = Subnet.objects.all()
    subnet_list = []
    for subnet in subnets:
        stats = subnet.get_usage_stats()
        subnet_list.append({
            "id": subnet.id,
            "network": subnet.network,
            "description": subnet.description,
            "available_count": stats["available_count"],
            "allocated_count": stats["allocated_count"],
            "usage_rate": stats["usage_rate"],
        })

    context = {
        "preset_subnet": preset_subnet,
        "preset_ip": preset_ip,
        "subnets": subnet_list,
    }
    return render(request, "ipam/ip_allocate.html", context)


@login_required
def device_list(request):
    """网络设备列表页面"""
    devices = NetworkDevice.objects.all().order_by("-created_at")

    # 统计信息
    stats = {
        "total": devices.count(),
        "active": devices.filter(is_active=True).count(),
        "inactive": devices.filter(is_active=False).count(),
    }

    # 最后扫描时间
    last_scan = NetworkDevice.objects.filter(
        last_scan__isnull=False
    ).order_by("-last_scan").values_list("last_scan", flat=True).first()

    context = {
        "devices": devices,
        "stats": stats,
        "last_scan": last_scan,
    }
    return render(request, "ipam/device_list.html", context)


@login_required
def audit_log_list(request):
    """审计日志列表页面"""
    # 过滤参数
    action_filter = request.GET.get("action", "")
    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date", "")
    search = request.GET.get("q", "")

    logs = AuditLog.objects.select_related("user").all()

    if action_filter:
        logs = logs.filter(action=action_filter)
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)
    if search:
        logs = logs.filter(
            Q(ip_address__icontains=search) |
            Q(hostname__icontains=search) |
            Q(mac_address__icontains=search) |
            Q(user__username__icontains=search)
        )

    logs = logs.order_by("-timestamp")

    # 统计信息
    today = timezone.now().date()
    stats = {
        "total": AuditLog.objects.count(),
        "today": AuditLog.objects.filter(timestamp__date=today).count(),
        "allocate": AuditLog.objects.filter(action="allocate").count(),
        "release": AuditLog.objects.filter(action="release").count(),
        "conflict": AuditLog.objects.filter(action="conflict_detected").count(),
        "update": AuditLog.objects.filter(action="update").count(),
    }

    # 分页
    paginator = Paginator(logs, 50)  # 每页50条
    page_number = request.GET.get("page", 1)
    logs = paginator.get_page(page_number)

    context = {
        "logs": logs,
        "stats": stats,
        "action_filter": action_filter,
        "start_date": start_date,
        "end_date": end_date,
        "search": search,
    }
    return render(request, "ipam/audit_log_list.html", context)


def user_logout(request):
    """用户登出"""
    logout(request)
    messages.success(request, "您已成功退出登录")
    return redirect("login")

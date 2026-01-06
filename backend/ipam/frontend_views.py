"""
IPAM前端视图（Django模板渲染）
"""

from __future__ import annotations

import ipaddress
import json
from typing import Any

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import logout
from django.contrib.auth.models import User
from django.contrib import messages
from django.db.models import Count, Q
from django.utils import timezone
from django.core.paginator import Paginator
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from datetime import timedelta

from .models import Subnet, IpAddress, NetworkDevice, AuditLog


def is_admin(user: Any) -> bool:
    """检查用户是否是管理员"""
    return user.is_staff or user.is_superuser


@login_required
def index(request):
    """首页 - 根据用户角色跳转"""
    if request.user.is_staff or request.user.is_superuser:
        return redirect("ipam:dashboard")
    else:
        return redirect("ipam:ip_allocate")


@login_required
@user_passes_test(is_admin)
def dashboard(request):
    """仪表板页面 - 仅管理员可访问"""
    # IP统计
    ip_stats = IpAddress.objects.aggregate(
        total=Count("id"),
        available=Count("id", filter=Q(status="available")),
        occupied=Count("id", filter=Q(status="occupied")),
        allocated=Count("id", filter=Q(status="allocated")),
        reserved=Count("id", filter=Q(status="reserved")),
        conflict=Count("id", filter=Q(status="conflict")),
    )

    # 计算使用率（已分配 + 已占用 + 保留）
    total = ip_stats["total"] or 0
    if total > 0:
        usage_rate = ((ip_stats["allocated"] + ip_stats["occupied"] + ip_stats["reserved"]) / total) * 100
    else:
        usage_rate = 0.0

    # 子网统计
    subnet_count = Subnet.objects.count()

    # 网络设备统计
    device_stats = {
        "total": NetworkDevice.objects.count(),
        "enabled": NetworkDevice.objects.filter(enabled=True).count(),
        "online": NetworkDevice.objects.filter(
            enabled=True,
            last_scan_status="success"
        ).count(),
    }

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
        "device_stats": device_stats,
        "high_usage_subnets": high_usage_subnets[:5],
        "recent_logs": recent_logs,
        "recent_allocations": recent_allocations,
    }

    return render(request, "ipam/dashboard.html", context)


@login_required
@user_passes_test(is_admin)
def subnet_list(request):
    """子网列表页面 - 仅管理员可访问"""
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
@user_passes_test(is_admin)
def subnet_detail(request, pk):
    """子网详情页面 - 仅管理员可访问"""
    subnet = get_object_or_404(Subnet, pk=pk)
    stats = subnet.get_usage_stats()

    # 获取该子网的所有IP
    ips = IpAddress.objects.filter(subnet=subnet).order_by("address")
    # 构建IP查找字典
    ip_dict = {ip.address: ip for ip in ips}

    # 按 C 类地址段分组 IP 方块
    network = ipaddress.ip_network(subnet.network, strict=False)
    c_class_groups = []

    # 计算所有主机地址
    hosts = list(network.hosts())
    if not hosts:
        # /31 或 /32 子网
        hosts = list(network)

    current_c_prefix = None
    group_ips = []

    for host in hosts:
        host_str = str(host)
        # 获取 C 类前缀 (前三个八位)
        octets = host_str.split(".")
        c_prefix = ".".join(octets[:3])
        last_octet = int(octets[3])

        if current_c_prefix is None:
            current_c_prefix = c_prefix
        elif c_prefix != current_c_prefix:
            # 新的 C 类段，保存当前组
            c_class_groups.append({
                "prefix": current_c_prefix,
                "ips": group_ips,
            })
            current_c_prefix = c_prefix
            group_ips = []

        # 获取 IP 对象
        ip_obj = ip_dict.get(host_str)
        group_ips.append({
            "address": host_str,
            "last_octet": last_octet,
            "status": ip_obj.status if ip_obj else "uninitialized",
            "id": ip_obj.id if ip_obj else None,
        })

    # 添加最后一组
    if group_ips:
        c_class_groups.append({
            "prefix": current_c_prefix,
            "ips": group_ips,
        })

    # 获取已分配的IP（用于列表显示）
    allocated_ips = IpAddress.objects.filter(
        subnet=subnet,
        status__in=["allocated", "reserved", "conflict"]
    ).select_related("allocated_by").order_by("address")

    context = {
        "subnet": subnet,
        "stats": stats,
        "c_class_groups": c_class_groups,
        "allocated_ips": allocated_ips,
    }
    return render(request, "ipam/subnet_detail.html", context)


@login_required
@user_passes_test(is_admin)
def ip_list(request):
    """IP地址列表页面 - 仅管理员可访问"""
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
            Q(responsible_person__icontains=search) |
            Q(department__icontains=search) |
            Q(building__icontains=search) |
            Q(notes__icontains=search)
        )

    ips = ips.order_by("address")

    # 获取子网列表供过滤
    subnets = Subnet.objects.all()

    # 分页配置
    page_size_options = [50, 100, 200, 500]
    page_size = request.GET.get("page_size", "100")
    try:
        page_size = int(page_size)
        if page_size not in page_size_options:
            page_size = 100
    except (ValueError, TypeError):
        page_size = 100

    paginator = Paginator(ips, page_size)
    page_number = request.GET.get("page", 1)
    page_obj = paginator.get_page(page_number)

    context = {
        "page_obj": page_obj,
        "subnets": subnets,
        "status_filter": status_filter,
        "subnet_filter": subnet_filter,
        "search": search,
        "page_size": page_size,
        "page_size_options": page_size_options,
    }
    return render(request, "ipam/ip_list.html", context)


@login_required
@user_passes_test(is_admin)
def ip_detail(request, pk):
    """IP详情页面 - 仅管理员可访问"""
    ip = get_object_or_404(IpAddress.objects.select_related("subnet", "allocated_by"), pk=pk)

    # 获取该IP的审计日志
    # 使用 str() 确保格式一致，因为 GenericIPAddressField 可能有格式差异
    ip_addr_str = str(ip.address)
    # 首先尝试精确匹配
    audit_logs = AuditLog.objects.filter(ip_address=ip_addr_str).select_related("user").order_by("-timestamp")[:20]

    # 如果精确匹配没有结果，尝试模糊匹配（处理可能的格式差异）
    if not audit_logs.exists():
        audit_logs = AuditLog.objects.filter(ip_address__icontains=ip_addr_str).select_related("user").order_by("-timestamp")[:20]

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
        # 计算已使用数量 = 已分配 + 已占用 + 保留
        used_count = stats["allocated_count"] + stats["occupied_count"] + stats["reserved_count"]
        subnet_list.append({
            "id": subnet.id,
            "network": subnet.network,
            "description": subnet.description,
            "building": subnet.building or "",
            "floor": subnet.floor or 0,
            "is_global": subnet.is_global,  # 全局子网标志
            "available_count": stats["available_count"],
            "occupied_count": stats["occupied_count"],
            "allocated_count": stats["allocated_count"],
            "reserved_count": stats["reserved_count"],
            "used_count": used_count,
            "usage_rate": stats["usage_rate"],
        })

    # 楼栋配置: M1有4层, M2/M3有3层
    buildings = [
        {"code": "M1", "name": "M1 厂房", "floors": [1, 2, 3, 4]},
        {"code": "M2", "name": "M2 厂房", "floors": [1, 2, 3]},
        {"code": "M3", "name": "M3 厂房", "floors": [1, 2, 3]},
    ]

    context = {
        "preset_subnet": preset_subnet,
        "preset_ip": preset_ip,
        "subnets": json.dumps(subnet_list, ensure_ascii=False),
        "buildings": buildings,
    }
    return render(request, "ipam/ip_allocate.html", context)


@login_required
def my_allocations(request):
    """我的IP申请记录 - 所有用户可访问"""
    # 获取当前用户分配的所有IP
    my_ips = IpAddress.objects.filter(
        allocated_by=request.user
    ).select_related("subnet").order_by("-allocated_at")

    # 分页
    paginator = Paginator(my_ips, 20)
    page = request.GET.get("page", 1)
    ips = paginator.get_page(page)

    # 统计
    stats = {
        "total": my_ips.count(),
        "allocated": my_ips.filter(status="allocated").count(),
        "reserved": my_ips.filter(status="reserved").count(),
    }

    context = {
        "ips": ips,
        "stats": stats,
    }
    return render(request, "ipam/my_allocations.html", context)


@login_required
@user_passes_test(is_admin)
def device_list(request):
    """网络设备列表页面 - 仅管理员可访问"""
    devices = NetworkDevice.objects.all().order_by("-created_at")

    # 统计信息
    stats = {
        "total": devices.count(),
        "active": devices.filter(enabled=True).count(),
        "inactive": devices.filter(enabled=False).count(),
    }

    # 最后扫描时间
    last_scan = NetworkDevice.objects.filter(
        last_scan_at__isnull=False
    ).order_by("-last_scan_at").values_list("last_scan_at", flat=True).first()

    context = {
        "devices": devices,
        "stats": stats,
        "last_scan": last_scan,
    }
    return render(request, "ipam/device_list.html", context)


@login_required
@user_passes_test(is_admin)
def audit_log_list(request):
    """审计日志列表页面 - 仅管理员可访问"""
    # 过滤参数
    action_filter = request.GET.get("action", "")
    start_date = request.GET.get("start_date", "")
    end_date = request.GET.get("end_date", "")
    search = request.GET.get("q", "")
    ip_filter = request.GET.get("ip", "")  # 支持按IP地址精确过滤

    logs = AuditLog.objects.select_related("user", "subnet").all()

    if action_filter:
        logs = logs.filter(action=action_filter)
    if start_date:
        logs = logs.filter(timestamp__date__gte=start_date)
    if end_date:
        logs = logs.filter(timestamp__date__lte=end_date)
    if ip_filter:
        # 按IP地址精确过滤
        logs = logs.filter(ip_address=ip_filter)
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
        "ip_filter": ip_filter,
    }
    return render(request, "ipam/audit_log_list.html", context)


def user_logout(request):
    """用户登出"""
    logout(request)
    messages.success(request, "您已成功退出登录")
    return redirect("login")


# ========== 子网管理视图 ==========

@login_required
@user_passes_test(is_admin)
def subnet_create(request):
    """创建子网页面 - 仅管理员可访问"""
    if request.method == "POST":
        network = request.POST.get("network", "").strip()
        description = request.POST.get("description", "").strip()
        gateway = request.POST.get("gateway", "").strip() or None
        vlan_id = request.POST.get("vlan_id", "").strip()

        # 可见范围设置
        is_global = request.POST.get("is_global") == "on"
        building = request.POST.get("building", "").strip()
        floor = request.POST.get("floor", "").strip()

        # 验证网络地址格式
        try:
            net = ipaddress.ip_network(network, strict=False)
        except ValueError as e:
            messages.error(request, f"无效的网络地址格式: {e}")
            return render(request, "ipam/subnet_form.html", {
                "form_data": request.POST,
                "is_edit": False,
            })

        # 检查子网是否已存在
        if Subnet.objects.filter(network=str(net)).exists():
            messages.error(request, f"子网 {net} 已存在")
            return render(request, "ipam/subnet_form.html", {
                "form_data": request.POST,
                "is_edit": False,
            })

        # 创建子网
        try:
            # 处理可见范围
            subnet_building = ""
            subnet_floor = None
            if not is_global:
                subnet_building = building if building else ""
                subnet_floor = int(floor) if floor else None

            subnet = Subnet.objects.create(
                network=str(net),
                description=description,
                gateway=gateway,
                vlan_id=int(vlan_id) if vlan_id else None,
                is_global=is_global,
                building=subnet_building,
                floor=subnet_floor,
            )
            messages.success(request, f"子网 {subnet.network} 创建成功")

            # 询问是否初始化IP池
            return redirect("ipam:subnet_detail", pk=subnet.id)
        except Exception as e:
            messages.error(request, f"创建子网失败: {e}")
            return render(request, "ipam/subnet_form.html", {
                "form_data": request.POST,
                "is_edit": False,
            })

    return render(request, "ipam/subnet_form.html", {"is_edit": False})


@login_required
@user_passes_test(is_admin)
def subnet_edit(request, pk):
    """编辑子网页面 - 仅管理员可访问"""
    subnet = get_object_or_404(Subnet, pk=pk)

    if request.method == "POST":
        description = request.POST.get("description", "").strip()
        gateway = request.POST.get("gateway", "").strip() or None
        vlan_id = request.POST.get("vlan_id", "").strip()

        # 可见范围设置
        is_global = request.POST.get("is_global") == "on"
        building = request.POST.get("building", "").strip()
        floor = request.POST.get("floor", "").strip()

        try:
            subnet.description = description
            subnet.gateway = gateway
            subnet.vlan_id = int(vlan_id) if vlan_id else None

            # 更新可见范围
            subnet.is_global = is_global
            if is_global:
                # 全局可见时清空楼栋楼层限制
                subnet.building = ""
                subnet.floor = None
            else:
                subnet.building = building if building else ""
                subnet.floor = int(floor) if floor else None

            subnet.save()

            messages.success(request, f"子网 {subnet.network} 更新成功")
            return redirect("ipam:subnet_detail", pk=subnet.id)
        except Exception as e:
            messages.error(request, f"更新子网失败: {e}")

    return render(request, "ipam/subnet_form.html", {
        "subnet": subnet,
        "is_edit": True,
    })


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def subnet_delete(request, pk):
    """删除子网 - 仅管理员可访问"""
    subnet = get_object_or_404(Subnet, pk=pk)
    network = subnet.network

    # 检查子网下是否有已分配的IP
    allocated_count = IpAddress.objects.filter(
        subnet=subnet,
        status__in=["allocated", "reserved"]
    ).count()

    if allocated_count > 0:
        messages.error(request, f"无法删除子网 {network}，还有 {allocated_count} 个IP地址已分配或保留")
        return redirect("ipam:subnet_detail", pk=pk)

    try:
        # 删除所有关联的IP地址
        IpAddress.objects.filter(subnet=subnet).delete()
        subnet.delete()
        messages.success(request, f"子网 {network} 已删除")
    except Exception as e:
        messages.error(request, f"删除子网失败: {e}")
        return redirect("ipam:subnet_detail", pk=pk)

    return redirect("ipam:subnet_list")


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def subnet_init_pool(request, pk):
    """初始化子网IP池 - 仅管理员可访问"""
    subnet = get_object_or_404(Subnet, pk=pk)

    # 检查是否已有IP
    existing_count = IpAddress.objects.filter(subnet=subnet).count()
    if existing_count > 0:
        messages.warning(request, f"子网 {subnet.network} 已有 {existing_count} 个IP地址")
        return redirect("ipam:subnet_detail", pk=pk)

    try:
        net = ipaddress.ip_network(subnet.network, strict=False)
        hosts = list(net.hosts())

        # 安全限制：防止超大子网导致性能问题（支持到 /20 子网）
        MAX_IP_POOL_SIZE = 4096
        total_hosts = net.num_addresses - 2  # 排除网络地址和广播地址
        if len(hosts) > MAX_IP_POOL_SIZE:
            hosts = hosts[:MAX_IP_POOL_SIZE]
            messages.warning(
                request,
                f"子网过大（共 {total_hosts} 个IP），已限制初始化前 {MAX_IP_POOL_SIZE} 个地址"
            )

        # 批量创建IP（网关地址自动标记为保留）
        gateway_ip = subnet.gateway if subnet.gateway else None
        ip_objects = []
        for host in hosts:
            host_str = str(host)
            if gateway_ip and host_str == gateway_ip:
                ip_objects.append(IpAddress(
                    address=host_str,
                    subnet=subnet,
                    status="reserved",
                    notes="网关地址",
                ))
            else:
                ip_objects.append(IpAddress(
                    address=host_str,
                    subnet=subnet,
                    status="available",
                ))
        IpAddress.objects.bulk_create(ip_objects)

        gateway_msg = f"（网关 {gateway_ip} 已标记为保留）" if gateway_ip else ""
        messages.success(request, f"已为子网 {subnet.network} 初始化 {len(ip_objects)} 个IP地址{gateway_msg}")
    except Exception as e:
        messages.error(request, f"初始化IP池失败: {e}")

    return redirect("ipam:subnet_detail", pk=pk)


# ========== 用户管理视图 ==========

@login_required
@user_passes_test(is_admin)
def user_list(request):
    """用户列表页面"""
    users = User.objects.all().order_by("-date_joined")

    # 搜索
    search = request.GET.get("q", "")
    if search:
        users = users.filter(
            Q(username__icontains=search) |
            Q(email__icontains=search) |
            Q(first_name__icontains=search) |
            Q(last_name__icontains=search)
        )

    # 统计（管理员不包含超级管理员）
    stats = {
        "total": User.objects.count(),
        "active": User.objects.filter(is_active=True).count(),
        "staff": User.objects.filter(is_staff=True, is_superuser=False).count(),
        "superuser": User.objects.filter(is_superuser=True).count(),
    }

    # 分页
    paginator = Paginator(users, 20)
    page_number = request.GET.get("page", 1)
    users = paginator.get_page(page_number)

    context = {
        "users": users,
        "stats": stats,
        "search": search,
    }
    return render(request, "ipam/user_list.html", context)


@login_required
@user_passes_test(is_admin)
def user_create(request):
    """创建用户页面"""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        role = request.POST.get("role", "user")
        is_active = request.POST.get("is_active", "on") == "on"

        # 根据角色设置权限
        if role == "superadmin":
            is_staff = True
            is_superuser = True
        elif role == "admin":
            is_staff = True
            is_superuser = False
        else:  # user
            is_staff = False
            is_superuser = False

        # 验证
        errors = []
        if not username:
            errors.append("用户名不能为空")
        elif User.objects.filter(username=username).exists():
            errors.append("用户名已存在")

        if not password:
            errors.append("密码不能为空")
        elif len(password) < 8:
            errors.append("密码长度至少8位")
        elif password != password2:
            errors.append("两次输入的密码不一致")

        if errors:
            for error in errors:
                messages.error(request, error)
            return render(request, "ipam/user_form.html", {
                "form_data": request.POST,
                "is_edit": False,
            })

        try:
            user = User.objects.create_user(
                username=username,
                email=email,
                password=password,
                first_name=first_name,
                last_name=last_name,
            )
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = is_active
            user.save()

            messages.success(request, f"用户 {username} 创建成功")
            return redirect("ipam:user_list")
        except Exception as e:
            messages.error(request, f"创建用户失败: {e}")

    return render(request, "ipam/user_form.html", {"is_edit": False})


@login_required
@user_passes_test(is_admin)
def user_edit(request, pk):
    """编辑用户页面"""
    user = get_object_or_404(User, pk=pk)

    if request.method == "POST":
        email = request.POST.get("email", "").strip()
        password = request.POST.get("password", "")
        password2 = request.POST.get("password2", "")
        first_name = request.POST.get("first_name", "").strip()
        last_name = request.POST.get("last_name", "").strip()
        role = request.POST.get("role", "user")
        is_active = request.POST.get("is_active") == "on"

        # 根据角色设置权限
        if role == "superadmin":
            is_staff = True
            is_superuser = True
        elif role == "admin":
            is_staff = True
            is_superuser = False
        else:  # user
            is_staff = False
            is_superuser = False

        # 验证密码
        if password:
            if len(password) < 8:
                messages.error(request, "密码长度至少8位")
                return render(request, "ipam/user_form.html", {
                    "user": user,
                    "is_edit": True,
                })
            if password != password2:
                messages.error(request, "两次输入的密码不一致")
                return render(request, "ipam/user_form.html", {
                    "user": user,
                    "is_edit": True,
                })

        try:
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_staff = is_staff
            user.is_superuser = is_superuser
            user.is_active = is_active

            if password:
                user.set_password(password)

            user.save()
            messages.success(request, f"用户 {user.username} 更新成功")
            return redirect("ipam:user_list")
        except Exception as e:
            messages.error(request, f"更新用户失败: {e}")

    return render(request, "ipam/user_form.html", {
        "user": user,
        "is_edit": True,
    })


@login_required
def ping_test(request):
    """Ping测试页面"""
    # 获取当前用户的IP地址（已分配和已占用的）
    my_ips = IpAddress.objects.filter(
        Q(allocated_by=request.user) | Q(status='allocated', allocated_by=request.user)
    ).filter(
        status__in=['allocated', 'occupied']
    ).select_related('subnet').order_by('-allocated_at', 'address')

    return render(request, "ipam/ping_test.html", {
        "my_ips": my_ips,
    })


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def user_delete(request, pk):
    """删除用户"""
    user = get_object_or_404(User, pk=pk)

    # 不能删除自己
    if user == request.user:
        messages.error(request, "不能删除自己的账户")
        return redirect("ipam:user_list")

    # 不能删除 admin 超管账户
    if user.username == 'admin' and user.is_superuser:
        messages.error(request, "admin 超管账户无法删除，只能禁用")
        return redirect("ipam:user_list")

    # 不能删除超级管理员（除非自己也是超级管理员）
    if user.is_superuser and not request.user.is_superuser:
        messages.error(request, "只有超级管理员可以删除其他超级管理员")
        return redirect("ipam:user_list")

    username = user.username
    try:
        user.delete()
        messages.success(request, f"用户 {username} 已删除")
    except Exception as e:
        messages.error(request, f"删除用户失败: {e}")

    return redirect("ipam:user_list")


@login_required
@user_passes_test(is_admin)
@require_http_methods(["POST"])
def user_toggle_active(request, pk):
    """切换用户激活状态"""
    user = get_object_or_404(User, pk=pk)

    if user == request.user:
        messages.error(request, "不能禁用自己的账户")
        return redirect("ipam:user_list")

    user.is_active = not user.is_active
    user.save()

    status = "启用" if user.is_active else "禁用"
    messages.success(request, f"用户 {user.username} 已{status}")
    return redirect("ipam:user_list")


# ========== 密码修改视图 ==========

def password_change(request):
    """用户自助修改密码（无需登录）"""
    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        old_password = request.POST.get("old_password", "")
        new_password1 = request.POST.get("new_password1", "")
        new_password2 = request.POST.get("new_password2", "")

        # 验证必填字段
        if not all([username, old_password, new_password1, new_password2]):
            messages.error(request, "请填写所有必填字段")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 验证两次密码一致
        if new_password1 != new_password2:
            messages.error(request, "两次输入的新密码不一致")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 验证新密码长度
        if len(new_password1) < 8:
            messages.error(request, "新密码长度至少8位")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 验证账号和原密码
        try:
            user = User.objects.get(username=username)
            if not user.check_password(old_password):
                messages.error(request, "账号或原密码错误")
                return render(request, "ipam/password_change.html", {
                    "form_data": {"username": username}
                })
        except User.DoesNotExist:
            # 为了安全，不透露账号是否存在
            messages.error(request, "账号或原密码错误")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

        # 修改密码
        try:
            user.set_password(new_password1)
            user.save()

            # 记录审计日志
            AuditLog.objects.create(
                action="password_change",
                ip_address=request.POST.get("ip_address"),
                details=f"用户 {username} 修改了密码",
                changes={"action": "self_password_change", "username": username}
            )

            messages.success(request, "密码修改成功，请使用新密码登录")
            return redirect("login")
        except Exception as e:
            messages.error(request, f"密码修改失败: {e}")
            return render(request, "ipam/password_change.html", {
                "form_data": {"username": username}
            })

    return render(request, "ipam/password_change.html")

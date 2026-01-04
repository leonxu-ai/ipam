"""
Agent系统提示动态生成模块

为AI Agent提供当前IPAM系统状态的上下文信息
"""

from __future__ import annotations

from typing import Dict, List, Any
from django.db.models import Count, Q
from django.utils import timezone
from .models import Subnet, IpAddress, NetworkDevice, AuditLog


class AgentPromptGenerator:
    """Agent系统提示生成器"""

    @classmethod
    def generate_system_context(cls) -> str:
        """
        生成完整的系统上下文提示

        Returns:
            包含系统状态、可用操作和约束的提示字符串
        """
        sections = [
            cls._generate_header(),
            cls._generate_system_overview(),
            cls._generate_subnet_info(),
            cls._generate_ip_statistics(),
            cls._generate_conflict_alerts(),
            cls._generate_available_operations(),
            cls._generate_constraints(),
        ]

        return "\n\n".join(sections)

    @classmethod
    def _generate_header(cls) -> str:
        """生成标题头"""
        return """# IPAM系统Agent上下文

你是中创新航工厂IP地址管理系统(IPAM)的AI助手。以下是当前系统状态的实时信息。"""

    @classmethod
    def _generate_system_overview(cls) -> str:
        """生成系统概览"""
        now = timezone.now()
        return f"""## 系统概览

- 当前时间: {now.strftime('%Y-%m-%d %H:%M:%S')}
- 系统版本: 1.0.0
- 数据库状态: 正常"""

    @classmethod
    def _generate_subnet_info(cls) -> str:
        """生成子网信息"""
        subnets = Subnet.objects.all()

        if not subnets.exists():
            return """## 子网信息

当前系统中没有配置任何子网。"""

        lines = ["## 子网信息", ""]
        lines.append("| 子网 | VLAN | 网关 | 总IP数 | 已分配 | 可用 | 使用率 |")
        lines.append("|------|------|------|--------|--------|------|--------|")

        for subnet in subnets:
            stats = subnet.get_usage_stats()
            lines.append(
                f"| {subnet.network} | {subnet.vlan_id or 'N/A'} | "
                f"{subnet.gateway or 'N/A'} | {stats['total_ips']} | "
                f"{stats['allocated_count']} | {stats['available_count']} | "
                f"{stats['usage_rate']:.1f}% |"
            )

        return "\n".join(lines)

    @classmethod
    def _generate_ip_statistics(cls) -> str:
        """生成IP统计信息"""
        stats = IpAddress.objects.aggregate(
            total=Count("id"),
            available=Count("id", filter=Q(status="available")),
            allocated=Count("id", filter=Q(status="allocated")),
            reserved=Count("id", filter=Q(status="reserved")),
            conflict=Count("id", filter=Q(status="conflict")),
        )

        total = stats["total"] or 0
        if total > 0:
            usage_rate = ((stats["allocated"] + stats["reserved"]) / total) * 100
        else:
            usage_rate = 0.0

        return f"""## IP地址统计

- 总IP数量: {total}
- 可用: {stats['available']} ({stats['available']/total*100:.1f}% if total else 0)
- 已分配: {stats['allocated']}
- 保留: {stats['reserved']}
- 冲突: {stats['conflict']}
- 整体使用率: {usage_rate:.1f}%"""

    @classmethod
    def _generate_conflict_alerts(cls) -> str:
        """生成冲突告警信息"""
        conflicts = IpAddress.objects.filter(status="conflict").select_related("subnet")

        if not conflicts.exists():
            return """## 冲突告警

当前没有IP地址冲突。"""

        lines = ["## 冲突告警", "", "**以下IP地址存在MAC冲突，需要处理：**", ""]

        for ip in conflicts[:10]:  # 最多显示10条
            lines.append(
                f"- **{ip.address}** ({ip.subnet.network}): "
                f"主机名={ip.hostname or 'N/A'}, "
                f"当前MAC={ip.mac_address or 'N/A'}, "
                f"原MAC={ip.previous_mac_address or 'N/A'}"
            )

        if conflicts.count() > 10:
            lines.append(f"\n*还有 {conflicts.count() - 10} 条冲突未显示*")

        return "\n".join(lines)

    @classmethod
    def _generate_available_operations(cls) -> str:
        """生成可用操作说明"""
        return """## 可用操作

### IP地址管理
- `allocate_ip(ip_id, hostname, mac_address, device_type, department, responsible_person)` - 分配指定IP
- `allocate_next_available(subnet_id, ...)` - 自动分配子网中下一个可用IP
- `release_ip(ip_id, keep_info=False)` - 释放IP地址
- `resolve_conflict(ip_id, resolution)` - 解决IP冲突（keep_current/update_mac/release）

### 子网管理
- `list_subnets()` - 列出所有子网
- `get_subnet_usage(subnet_id)` - 获取子网使用统计
- `initialize_ip_pool(subnet_id)` - 初始化子网IP池

### 查询操作
- `search_ip(address/hostname/mac)` - 搜索IP地址
- `get_available_ips(subnet_id)` - 获取可用IP列表
- `get_audit_logs(start_date, end_date)` - 查询审计日志"""

    @classmethod
    def _generate_constraints(cls) -> str:
        """生成约束说明"""
        return """## 系统约束

1. **并发安全**: 所有IP分配操作都使用数据库行锁，确保不会出现重复分配
2. **审计不可变**: 审计日志一旦创建就不能修改或删除
3. **MAC冲突检测**: SNMP扫描会自动检测MAC地址变化并标记冲突
4. **权限要求**: 所有操作都需要用户认证

## 注意事项

- 分配IP时建议填写完整的设备信息（主机名、MAC、部门、责任人）
- 冲突IP需要及时处理，否则可能影响网络正常运行
- 释放IP时默认会清空设备信息，如需保留请设置keep_info=True"""

    @classmethod
    def generate_allocation_context(cls, subnet_id: int) -> str:
        """
        生成针对特定子网的分配上下文

        Args:
            subnet_id: 子网ID

        Returns:
            包含该子网详细信息的提示字符串
        """
        try:
            subnet = Subnet.objects.get(pk=subnet_id)
        except Subnet.DoesNotExist:
            return f"错误: 子网ID {subnet_id} 不存在"

        stats = subnet.get_usage_stats()

        # 获取最近分配的IP
        recent_allocations = (
            IpAddress.objects.filter(subnet=subnet, status="allocated")
            .order_by("-allocated_at")[:5]
        )

        lines = [
            f"# 子网 {subnet.network} 分配上下文",
            "",
            "## 子网信息",
            f"- CIDR: {subnet.network}",
            f"- 网关: {subnet.gateway or '未设置'}",
            f"- 子网掩码: {subnet.netmask or '自动计算'}",
            f"- VLAN ID: {subnet.vlan_id or '未设置'}",
            f"- 描述: {subnet.description or '无'}",
            "",
            "## 使用统计",
            f"- 总IP数: {stats['total_ips']}",
            f"- 可用: {stats['available_count']}",
            f"- 已分配: {stats['allocated_count']}",
            f"- 保留: {stats['reserved_count']}",
            f"- 冲突: {stats['conflict_count']}",
            f"- 使用率: {stats['usage_rate']:.1f}%",
            "",
        ]

        if recent_allocations:
            lines.extend([
                "## 最近分配记录",
                "",
            ])
            for ip in recent_allocations:
                alloc_time = ip.allocated_at.strftime('%m-%d %H:%M') if ip.allocated_at else 'N/A'
                lines.append(
                    f"- {ip.address}: {ip.hostname or 'N/A'} ({ip.device_type or 'N/A'}) - {alloc_time}"
                )

        return "\n".join(lines)

    @classmethod
    def generate_conflict_resolution_context(cls, ip_id: int) -> str:
        """
        生成冲突解决上下文

        Args:
            ip_id: IP地址记录ID

        Returns:
            包含冲突详情和解决建议的提示字符串
        """
        try:
            ip = IpAddress.objects.select_related("subnet", "allocated_by").get(pk=ip_id)
        except IpAddress.DoesNotExist:
            return f"错误: IP记录ID {ip_id} 不存在"

        if ip.status != "conflict":
            return f"IP地址 {ip.address} 当前状态为 {ip.get_status_display()}，不是冲突状态"

        # 查询相关审计日志
        conflict_logs = AuditLog.objects.filter(
            ip_address=ip.address,
            action="conflict_detected"
        ).order_by("-timestamp")[:5]

        lines = [
            f"# IP冲突解决上下文: {ip.address}",
            "",
            "## 当前状态",
            f"- IP地址: {ip.address}",
            f"- 子网: {ip.subnet.network}",
            f"- 主机名: {ip.hostname or '未设置'}",
            f"- 当前记录的MAC: {ip.mac_address or '未记录'}",
            f"- 冲突前的MAC: {ip.previous_mac_address or '未记录'}",
            f"- 设备类型: {ip.device_type or '未设置'}",
            f"- 责任人: {ip.responsible_person or '未设置'}",
            f"- 冲突检测时间: {ip.conflict_detected_at.strftime('%Y-%m-%d %H:%M:%S') if ip.conflict_detected_at else 'N/A'}",
            "",
            "## 解决方案",
            "",
            "1. **keep_current** - 保留当前记录的MAC地址，忽略本次冲突",
            "   - 适用场景: 扫描到的MAC是临时设备或误报",
            "",
            "2. **update_mac** - 更新为新扫描到的MAC地址",
            "   - 适用场景: 设备已更换网卡或迁移到新设备",
            "",
            "3. **release** - 释放此IP地址",
            "   - 适用场景: 原设备已下线，需要重新分配",
            "",
        ]

        if conflict_logs:
            lines.extend([
                "## 冲突历史记录",
                "",
            ])
            for log in conflict_logs:
                details = log.details or {}
                lines.append(
                    f"- {log.timestamp.strftime('%Y-%m-%d %H:%M')}: "
                    f"原MAC={details.get('old_mac', 'N/A')} -> "
                    f"新MAC={details.get('new_mac', 'N/A')} "
                    f"(来源: {details.get('scan_source', 'N/A')})"
                )

        return "\n".join(lines)

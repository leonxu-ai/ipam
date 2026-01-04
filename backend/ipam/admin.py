"""
Django Admin配置
"""

from django.contrib import admin
from django.utils.html import format_html
from .models import Subnet, IpAddress, NetworkDevice, AuditLog


@admin.register(Subnet)
class SubnetAdmin(admin.ModelAdmin):
    """子网管理界面"""

    list_display = ["network", "gateway", "vlan_id", "usage_display", "created_at"]
    list_filter = ["vlan_id", "created_at"]
    search_fields = ["network", "description"]
    readonly_fields = ["created_at", "updated_at"]

    fieldsets = [
        ("网络配置", {
            "fields": ["network", "gateway", "netmask", "vlan_id"]
        }),
        ("描述信息", {
            "fields": ["description"]
        }),
        ("时间戳", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    ]

    def usage_display(self, obj):
        """显示使用率"""
        stats = obj.get_usage_stats()
        allocated = stats.get("allocated", 0)
        total = stats.get("usable", 1)
        percentage = (allocated / total * 100) if total > 0 else 0

        if percentage > 80:
            color = "red"
        elif percentage > 60:
            color = "orange"
        else:
            color = "green"

        return format_html(
            '<span style="color: {};">{}/{} ({:.1f}%)</span>',
            color, allocated, total, percentage
        )
    usage_display.short_description = "使用率"


@admin.register(IpAddress)
class IpAddressAdmin(admin.ModelAdmin):
    """IP地址管理界面"""

    list_display = [
        "address",
        "status_badge",
        "hostname",
        "mac_address",
        "device_type",
        "department",
        "allocated_by",
        "allocated_at"
    ]
    list_filter = ["status", "device_type", "department", "allocated_at", "subnet"]
    search_fields = [
        "address",
        "hostname",
        "mac_address",
        "responsible_person",
        "notes"
    ]
    readonly_fields = [
        "created_at",
        "updated_at",
        "conflict_detected_at"
    ]

    fieldsets = [
        ("基本信息", {
            "fields": ["subnet", "address", "status"]
        }),
        ("设备信息", {
            "fields": [
                "hostname",
                "mac_address",
                "device_type",
                "department",
                "responsible_person"
            ]
        }),
        ("分配信息", {
            "fields": ["allocated_by", "allocated_at", "notes"]
        }),
        ("冲突检测", {
            "fields": [
                "conflict_detected_at",
                "previous_mac_address"
            ],
            "classes": ["collapse"]
        }),
        ("时间戳", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    ]

    def status_badge(self, obj):
        """状态徽章"""
        colors = {
            "available": "green",
            "allocated": "blue",
            "reserved": "orange",
            "conflict": "red",
        }
        color = colors.get(obj.status, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_status_display()
        )
    status_badge.short_description = "状态"

    def get_readonly_fields(self, request, obj=None):
        """根据对象状态动态设置只读字段"""
        readonly = list(self.readonly_fields)
        if obj and obj.status == "allocated":
            readonly.extend(["allocated_by", "allocated_at"])
        return readonly


@admin.register(NetworkDevice)
class NetworkDeviceAdmin(admin.ModelAdmin):
    """网络设备管理界面"""

    list_display = [
        "name",
        "ip_address",
        "snmp_version",
        "enabled",
        "last_scan_status_display",
        "last_scan_at"
    ]
    list_filter = ["enabled", "snmp_version", "last_scan_status"]
    search_fields = ["name", "ip_address"]
    readonly_fields = [
        "last_scan_at",
        "last_scan_status",
        "last_scan_error",
        "created_at",
        "updated_at"
    ]

    fieldsets = [
        ("基本信息", {
            "fields": ["name", "ip_address", "enabled"]
        }),
        ("SNMP配置", {
            "fields": ["snmp_version", "snmp_community"]
        }),
        ("SNMPv3凭证 (加密存储)", {
            "fields": [
                "snmp_username",
                "snmp_auth_password_encrypted",
                "snmp_priv_password_encrypted"
            ],
            "classes": ["collapse"]
        }),
        ("扫描状态", {
            "fields": [
                "last_scan_at",
                "last_scan_status",
                "last_scan_error"
            ]
        }),
        ("时间戳", {
            "fields": ["created_at", "updated_at"],
            "classes": ["collapse"]
        }),
    ]

    def last_scan_status_display(self, obj):
        """最后扫描状态显示"""
        if not obj.last_scan_status:
            return format_html(
                '<span style="color: gray;">未扫描</span>'
            )

        colors = {
            "success": "green",
            "failed": "red",
            "timeout": "orange",
        }
        color = colors.get(obj.last_scan_status, "gray")
        return format_html(
            '<span style="color: {};">{}</span>',
            color, obj.last_scan_status
        )
    last_scan_status_display.short_description = "扫描状态"


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    """审计日志管理界面（只读）"""

    list_display = [
        "timestamp",
        "action_badge",
        "user",
        "ip_address",
        "hostname",
        "mac_address"
    ]
    list_filter = ["action", "timestamp"]
    search_fields = ["ip_address", "hostname", "mac_address", "user__username"]
    readonly_fields = [
        "timestamp",
        "user",
        "action",
        "ip_address",
        "hostname",
        "mac_address",
        "details"
    ]

    # 禁止添加、修改、删除
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def action_badge(self, obj):
        """操作类型徽章"""
        colors = {
            "allocate": "blue",
            "release": "green",
            "update": "orange",
            "delete": "red",
            "create_subnet": "purple",
            "update_subnet": "purple",
            "delete_subnet": "red",
            "snmp_scan": "gray",
            "conflict_detected": "red",
        }
        color = colors.get(obj.action, "gray")
        return format_html(
            '<span style="background-color: {}; color: white; padding: 3px 8px; '
            'border-radius: 3px; font-size: 11px;">{}</span>',
            color, obj.get_action_display()
        )
    action_badge.short_description = "操作"

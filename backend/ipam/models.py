"""
IPAM数据模型

包含子网、IP地址、网络设备和审计日志的数据模型定义
"""

from __future__ import annotations

import ipaddress
from typing import TYPE_CHECKING, Optional
from django.db import models
from django.contrib.auth import get_user_model
from django.core.validators import (
    RegexValidator,
    MinValueValidator,
    MaxValueValidator,
)
from django.core.exceptions import ValidationError
from django.utils import timezone

if TYPE_CHECKING:
    from django.contrib.auth.models import User as UserType
else:
    UserType = get_user_model()

User = get_user_model()


class IPAddressValidator:
    """CIDR格式验证器"""

    def __call__(self, value: str) -> None:
        try:
            ipaddress.ip_network(value, strict=True)
        except ValueError as e:
            raise ValidationError(
                f"无效的CIDR格式: {value}. 错误: {str(e)}"
            ) from e

    def deconstruct(self):
        """Django迁移序列化支持"""
        return (
            'ipam.models.IPAddressValidator',
            [],
            {}
        )


class MACAddressValidator:
    """MAC地址格式验证器"""

    def __call__(self, value: str) -> None:
        if not value:
            return
        # 支持三种常见格式：AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABBCCDDEEFF
        import re
        pattern = r'^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$|^([0-9A-Fa-f]{12})$'
        if not re.match(pattern, value):
            raise ValidationError(
                f"无效的MAC地址格式: {value}. "
                f"支持格式: AA:BB:CC:DD:EE:FF, AA-BB-CC-DD-EE-FF, AABBCCDDEEFF"
            )

    def deconstruct(self):
        """Django迁移序列化支持"""
        return (
            'ipam.models.MACAddressValidator',
            [],
            {}
        )


class Subnet(models.Model):
    """子网模型"""

    network = models.CharField(
        max_length=43,  # IPv6 CIDR最长：ffff:ffff:ffff:ffff:ffff:ffff:ffff:ffff/128
        unique=True,
        validators=[IPAddressValidator()],
        verbose_name="网络地址",
        help_text="CIDR格式，例如: 192.168.10.0/24",
        db_index=True,
    )
    gateway = models.GenericIPAddressField(
        protocol="both",
        verbose_name="网关地址",
        blank=True,
        null=True,
    )
    netmask = models.GenericIPAddressField(
        protocol="both",
        verbose_name="子网掩码",
        blank=True,
        null=True,
    )
    vlan_id = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(4094)],
        verbose_name="VLAN ID",
        db_index=True,
    )
    description = models.TextField(
        blank=True,
        verbose_name="描述",
    )
    # 楼栋和楼层信息
    building = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="楼栋",
        help_text="例如: M1, M2, M3",
        db_index=True,
    )
    floor = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name="楼层",
        db_index=True,
    )
    is_global = models.BooleanField(
        default=False,
        verbose_name="全局子网",
        help_text="标记为全局子网，所有用户可见可用",
        db_index=True,
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间",
    )

    class Meta:
        verbose_name = "子网"
        verbose_name_plural = "子网"
        ordering = ["network"]
        indexes = [
            models.Index(fields=["network"]),
            models.Index(fields=["vlan_id"]),
        ]

    def __str__(self) -> str:
        return f"{self.network}"

    def clean(self) -> None:
        """验证子网配置"""
        super().clean()

        # 验证CIDR格式
        try:
            net = ipaddress.ip_network(self.network, strict=True)
        except ValueError as e:
            raise ValidationError({"network": str(e)}) from e

        # 自动计算netmask（如果未提供）
        if not self.netmask:
            self.netmask = str(net.netmask)

        # 验证gateway是否在子网内
        if self.gateway:
            try:
                gw_addr = ipaddress.ip_address(self.gateway)
                if gw_addr not in net:
                    raise ValidationError({
                        "gateway": f"网关地址 {self.gateway} 不在子网 {self.network} 范围内"
                    })
            except ValueError as e:
                raise ValidationError({"gateway": str(e)}) from e

    def save(self, *args, **kwargs) -> None:
        """保存前验证"""
        self.clean()
        super().save(*args, **kwargs)

    @property
    def total_ips(self) -> int:
        """子网总IP数量"""
        net = ipaddress.ip_network(self.network)
        return net.num_addresses

    @property
    def usable_ips(self) -> int:
        """可用IP数量（排除网络地址和广播地址）"""
        net = ipaddress.ip_network(self.network)
        # /31和/32子网特殊处理
        if net.prefixlen >= 31:
            return net.num_addresses
        return net.num_addresses - 2

    def get_usage_stats(self) -> dict[str, any]:
        """获取使用统计"""
        ips = self.ip_addresses.all()
        total_ips = ips.count()
        available_count = ips.filter(status="available").count()
        occupied_count = ips.filter(status="occupied").count()
        allocated_count = ips.filter(status="allocated").count()
        reserved_count = ips.filter(status="reserved").count()
        conflict_count = ips.filter(status="conflict").count()

        # 计算使用率（已占用、已分配、保留都算使用中）
        if total_ips > 0:
            usage_rate = ((occupied_count + allocated_count + reserved_count) / total_ips) * 100
        else:
            usage_rate = 0.0

        return {
            "total_ips": total_ips,
            "usable_ips": self.usable_ips,
            "available_count": available_count,
            "occupied_count": occupied_count,
            "allocated_count": allocated_count,
            "reserved_count": reserved_count,
            "conflict_count": conflict_count,
            "usage_rate": round(usage_rate, 1),
            # 兼容旧键名
            "total": self.total_ips,
            "usable": self.usable_ips,
            "available": available_count,
            "occupied": occupied_count,
            "allocated": allocated_count,
            "reserved": reserved_count,
            "conflict": conflict_count,
        }


class IpAddress(models.Model):
    """IP地址模型"""

    STATUS_CHOICES = [
        ("available", "可用"),
        ("occupied", "已占用"),  # 扫描发现正在使用，但未在系统中分配
        ("allocated", "已分配"),
        ("reserved", "保留"),
        ("conflict", "冲突"),
    ]

    DEVICE_TYPE_CHOICES = [
        ("server", "服务器"),
        ("workstation", "工作站"),
        ("printer", "打印机"),
        ("network", "网络设备"),
        ("clean_instrument", "洁净仪"),
        ("iot", "物联网设备"),
        ("camera", "监控摄像头"),
        ("access_control", "门禁设备"),
        ("plc", "PLC控制器"),
        ("hmi", "触摸屏/HMI"),
        ("robot", "机器人"),
        ("agv", "AGV小车"),
        ("scanner", "扫码枪"),
        ("sensor", "传感器"),
        ("wireless_controller", "无线控制器"),
        ("other", "其他"),
    ]

    subnet = models.ForeignKey(
        Subnet,
        on_delete=models.CASCADE,
        related_name="ip_addresses",
        verbose_name="所属子网",
        db_index=True,
    )
    address = models.GenericIPAddressField(
        protocol="both",
        unique=True,
        verbose_name="IP地址",
        db_index=True,
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default="available",
        verbose_name="状态",
        db_index=True,
    )

    # 设备信息
    hostname = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="主机名",
        db_index=True,
    )
    mac_address = models.CharField(
        max_length=17,
        blank=True,
        validators=[MACAddressValidator()],
        verbose_name="MAC地址",
        db_index=True,
    )
    device_type = models.CharField(
        max_length=100,
        choices=DEVICE_TYPE_CHOICES,
        blank=True,
        verbose_name="设备类型",
        help_text="例如: 服务器、打印机、工控机",
    )
    department = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="使用部门",
    )
    responsible_person = models.CharField(
        max_length=100,
        blank=True,
        verbose_name="责任人",
    )

    # 位置信息（跟随分配的设备）
    building = models.CharField(
        max_length=10,
        blank=True,
        verbose_name="楼栋",
        help_text="例如: M1, M2, M3",
    )
    floor = models.IntegerField(
        blank=True,
        null=True,
        validators=[MinValueValidator(1), MaxValueValidator(10)],
        verbose_name="楼层",
    )

    # 分配信息
    allocated_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="分配时间",
        db_index=True,
    )
    allocated_by = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="allocated_ips",
        verbose_name="分配人",
    )

    # 冲突检测相关
    conflict_detected_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="冲突检测时间",
    )
    previous_mac_address = models.CharField(
        max_length=17,
        blank=True,
        verbose_name="之前的MAC地址",
        help_text="用于检测MAC地址变化",
    )

    # 扫描跟踪字段
    consecutive_missing = models.IntegerField(
        default=0,
        validators=[MinValueValidator(0, message="连续缺失次数不能为负数")],
        verbose_name="连续缺失次数",
        help_text="SNMP扫描中连续未发现该IP的次数",
        db_index=True,
    )
    last_seen_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="最后发现时间",
        help_text="SNMP扫描最后一次发现该IP在线的时间",
        db_index=True,
    )

    # 备注
    notes = models.TextField(
        blank=True,
        verbose_name="备注",
    )

    # 时间戳
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间",
    )

    class Meta:
        verbose_name = "IP地址"
        verbose_name_plural = "IP地址"
        ordering = ["address"]
        indexes = [
            models.Index(fields=["address"]),
            models.Index(fields=["status"]),
            models.Index(fields=["subnet", "status"]),
            models.Index(fields=["mac_address"]),
            models.Index(fields=["hostname"]),
            models.Index(fields=["allocated_at"]),
        ]

    def __str__(self) -> str:
        return f"{self.address} ({self.get_status_display()})"

    def clean(self) -> None:
        """验证IP地址配置"""
        super().clean()

        # 验证IP地址格式
        try:
            addr = ipaddress.ip_address(self.address)
        except ValueError as e:
            raise ValidationError({"address": str(e)}) from e

        # 验证IP是否在所属子网内
        if self.subnet_id:
            try:
                net = ipaddress.ip_network(self.subnet.network)
                if addr not in net:
                    raise ValidationError({
                        "address": f"IP地址 {self.address} 不在子网 {self.subnet.network} 范围内"
                    })
            except ValueError as e:
                raise ValidationError({"subnet": str(e)}) from e

        # 验证状态转换
        if self.pk:  # 更新现有记录
            old = IpAddress.objects.get(pk=self.pk)
            if old.status == "allocated" and self.status == "available":
                # 释放IP时清空相关字段
                if not self.pk:  # 只在首次保存时自动清空
                    self.hostname = ""
                    self.mac_address = ""
                    self.device_type = ""
                    self.department = ""
                    self.responsible_person = ""
                    self.notes = ""
                    self.allocated_at = None
                    self.allocated_by = None

    def save(self, *args, **kwargs) -> None:
        """保存前验证"""
        self.clean()

        # MAC地址标准化为大写格式
        if self.mac_address:
            self.mac_address = self.mac_address.upper()
        if self.previous_mac_address:
            self.previous_mac_address = self.previous_mac_address.upper()

        # 自动设置分配时间
        if self.status == "allocated" and not self.allocated_at:
            self.allocated_at = timezone.now()

        super().save(*args, **kwargs)

    def allocate(
        self,
        user: UserType,
        hostname: str = "",
        mac_address: str = "",
        device_type: str = "",
        department: str = "",
        responsible_person: str = "",
        notes: str = "",
    ) -> None:
        """分配IP地址"""
        if self.status != "available":
            raise ValidationError(f"IP地址 {self.address} 当前状态为 {self.get_status_display()}，无法分配")

        self.status = "allocated"
        self.hostname = hostname
        self.mac_address = mac_address
        self.device_type = device_type
        self.department = department
        self.responsible_person = responsible_person
        self.notes = notes
        self.allocated_at = timezone.now()
        self.allocated_by = user
        self.save()

    def release(self, keep_info: bool = False) -> None:
        """释放IP地址"""
        self.status = "available"
        self.allocated_at = None
        self.allocated_by = None

        if not keep_info:
            self.hostname = ""
            self.mac_address = ""
            self.device_type = ""
            self.department = ""
            self.responsible_person = ""
            self.notes = ""

        self.save()

    def ping_test(self, timeout: int = 3, count: int = 3) -> dict:
        """
        执行 Ping 测试（Fat Model 方法）

        Args:
            timeout: 超时时间（秒），默认 3 秒
            count: ping 次数，默认 3 次

        Returns:
            {
                "success": bool,
                "reachable": bool,
                "response_time_ms": float | None,
                "packet_loss": float,  # 丢包率 0-100
                "message": str,
            }
        """
        import subprocess
        import platform
        import re

        result = {
            "success": False,
            "reachable": False,
            "response_time_ms": None,
            "packet_loss": 100.0,
            "message": "",
        }

        try:
            # 根据操作系统选择参数
            system = platform.system().lower()
            if system == "windows":
                cmd = ["ping", "-n", str(count), "-w", str(timeout * 1000), self.address]
            else:  # Linux/macOS
                cmd = ["ping", "-c", str(count), "-W", str(timeout), self.address]

            # 执行 ping 命令
            process = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout * count + 5,  # 总超时
            )

            output = process.stdout + process.stderr
            result["success"] = True

            # 解析丢包率
            loss_match = re.search(r"(\d+(?:\.\d+)?)[%％]", output)
            if loss_match:
                result["packet_loss"] = float(loss_match.group(1))

            # 解析响应时间（取平均值）
            # Linux: rtt min/avg/max/mdev = 0.123/0.456/0.789/0.012 ms
            # Windows: 平均 = 123ms
            avg_match = re.search(r"(?:avg|平均)[^=]*=\s*(\d+(?:\.\d+)?)", output, re.IGNORECASE)
            if avg_match:
                result["response_time_ms"] = float(avg_match.group(1))
            else:
                # 尝试匹配 time=xx.x ms 格式
                time_matches = re.findall(r"time[<=]?(\d+(?:\.\d+)?)\s*ms", output, re.IGNORECASE)
                if time_matches:
                    times = [float(t) for t in time_matches]
                    result["response_time_ms"] = round(sum(times) / len(times), 2)

            # 判断是否可达
            result["reachable"] = result["packet_loss"] < 100

            if result["reachable"]:
                if result["response_time_ms"]:
                    result["message"] = f"可达，响应时间 {result['response_time_ms']} ms"
                else:
                    result["message"] = "可达"
            else:
                result["message"] = "不可达"

        except subprocess.TimeoutExpired:
            result["success"] = True
            result["message"] = "请求超时"
        except FileNotFoundError:
            result["message"] = "ping 命令不可用"
        except Exception as e:
            result["message"] = f"执行错误: {str(e)[:100]}"

        return result


class NetworkDevice(models.Model):
    """网络设备模型（SNMP扫描目标）"""

    SNMP_VERSION_CHOICES = [
        ("v2c", "SNMPv2c"),
        ("v3", "SNMPv3"),
    ]

    DEVICE_TYPE_CHOICES = [
        ("switch", "交换机"),
        ("router", "路由器"),
        ("firewall", "防火墙"),
        ("wireless_controller", "无线控制器"),
        ("ap", "无线AP"),
        ("other", "其他"),
    ]

    name = models.CharField(
        max_length=200,
        unique=True,
        verbose_name="设备名称",
        db_index=True,
    )
    ip_address = models.GenericIPAddressField(
        protocol="both",
        unique=True,
        verbose_name="IP地址",
        db_index=True,
    )
    device_type = models.CharField(
        max_length=50,
        choices=DEVICE_TYPE_CHOICES,
        default="switch",
        verbose_name="设备类型",
    )
    description = models.TextField(
        blank=True,
        verbose_name="描述",
    )
    snmp_version = models.CharField(
        max_length=10,
        choices=SNMP_VERSION_CHOICES,
        default="v2c",
        verbose_name="SNMP版本",
    )

    # SNMPv2c 凭证
    snmp_community = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="Community字符串",
        help_text="SNMPv2c使用",
    )

    # SNMPv3 凭证（加密存储）
    snmp_username = models.CharField(
        max_length=200,
        blank=True,
        verbose_name="SNMP用户名",
        help_text="SNMPv3使用",
    )
    snmp_auth_password_encrypted = models.TextField(
        blank=True,
        verbose_name="认证密码（加密）",
        help_text="SNMPv3使用，Fernet加密存储",
    )
    snmp_priv_password_encrypted = models.TextField(
        blank=True,
        verbose_name="隐私密码（加密）",
        help_text="SNMPv3使用，Fernet加密存储",
    )

    # 扫描配置
    enabled = models.BooleanField(
        default=True,
        verbose_name="启用扫描",
        db_index=True,
    )
    scan_interval_minutes = models.IntegerField(
        default=30,
        validators=[
            MinValueValidator(1, message="扫描间隔至少为1分钟"),
            MaxValueValidator(1440, message="扫描间隔最多为1440分钟(24小时)"),
        ],
        verbose_name="扫描间隔(分钟)",
        help_text="自动扫描的时间间隔，范围: 1-1440分钟",
    )
    last_scan_at = models.DateTimeField(
        blank=True,
        null=True,
        verbose_name="最后扫描时间",
    )
    last_scan_status = models.CharField(
        max_length=20,
        blank=True,
        verbose_name="最后扫描状态",
        help_text="success/failed/timeout",
    )
    last_scan_error = models.TextField(
        blank=True,
        verbose_name="最后扫描错误",
    )

    # 时间戳
    created_at = models.DateTimeField(
        auto_now_add=True,
        verbose_name="创建时间",
    )
    updated_at = models.DateTimeField(
        auto_now=True,
        verbose_name="更新时间",
    )

    class Meta:
        verbose_name = "网络设备"
        verbose_name_plural = "网络设备"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["name"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["enabled"]),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.ip_address})"

    def clean(self) -> None:
        """验证设备配置"""
        super().clean()

        # 验证SNMP凭证
        if self.snmp_version == "v2c" and not self.snmp_community:
            raise ValidationError({
                "snmp_community": "SNMPv2c需要配置Community字符串"
            })

        if self.snmp_version == "v3":
            if not self.snmp_username:
                raise ValidationError({
                    "snmp_username": "SNMPv3需要配置用户名"
                })
            if not self.snmp_auth_password_encrypted:
                raise ValidationError({
                    "snmp_auth_password_encrypted": "SNMPv3需要配置认证密码"
                })

    def set_snmp_auth_password(self, plaintext_password: str) -> None:
        """设置SNMPv3认证密码（自动加密）"""
        from .encryption import encrypt_snmp_credential
        self.snmp_auth_password_encrypted = encrypt_snmp_credential(plaintext_password)

    def get_snmp_auth_password(self) -> str:
        """获取SNMPv3认证密码（自动解密）"""
        if not self.snmp_auth_password_encrypted:
            return ""
        from .encryption import decrypt_snmp_credential
        return decrypt_snmp_credential(self.snmp_auth_password_encrypted)

    def set_snmp_priv_password(self, plaintext_password: str) -> None:
        """设置SNMPv3隐私密码（自动加密）"""
        from .encryption import encrypt_snmp_credential
        self.snmp_priv_password_encrypted = encrypt_snmp_credential(plaintext_password)

    def get_snmp_priv_password(self) -> str:
        """获取SNMPv3隐私密码（自动解密）"""
        if not self.snmp_priv_password_encrypted:
            return ""
        from .encryption import decrypt_snmp_credential
        return decrypt_snmp_credential(self.snmp_priv_password_encrypted)


class AuditLog(models.Model):
    """审计日志模型（不可修改）"""

    ACTION_CHOICES = [
        ("allocate", "分配IP"),
        ("release", "释放IP"),
        ("update", "更新IP"),
        ("delete", "删除IP"),
        ("create_subnet", "创建子网"),
        ("update_subnet", "更新子网"),
        ("delete_subnet", "删除子网"),
        ("snmp_scan", "SNMP扫描"),
        ("scan", "网络扫描"),
        ("conflict_detected", "检测到冲突"),
        ("conflict_resolved", "冲突已解决"),
        ("device_discovered", "发现设备"),
        ("device_changed", "设备变更"),
    ]

    timestamp = models.DateTimeField(
        auto_now_add=True,
        verbose_name="时间戳",
        db_index=True,
    )
    user = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        blank=True,
        null=True,
        related_name="audit_logs",
        verbose_name="操作用户",
    )
    action = models.CharField(
        max_length=50,
        choices=ACTION_CHOICES,
        verbose_name="操作类型",
        db_index=True,
    )

    # 子网相关信息
    subnet = models.ForeignKey(
        Subnet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_logs",
        verbose_name="关联子网",
    )
    subnet_network = models.CharField(
        max_length=43,
        blank=True,
        verbose_name="子网地址（快照）",
        help_text="冗余存储，防止子网删除后丢失信息",
    )

    # IP相关信息（冗余存储，即使IP被删除也能查看历史）
    ip_address = models.CharField(
        max_length=45,
        blank=True,
        verbose_name="IP地址",
        db_index=True,
    )
    hostname = models.CharField(
        max_length=255,
        blank=True,
        verbose_name="主机名",
    )
    mac_address = models.CharField(
        max_length=17,
        blank=True,
        verbose_name="MAC地址",
    )

    # 详细信息
    details = models.JSONField(
        blank=True,
        null=True,
        verbose_name="详细信息",
        help_text="额外的操作详情，JSON格式",
    )

    class Meta:
        verbose_name = "审计日志"
        verbose_name_plural = "审计日志"
        ordering = ["-timestamp"]
        indexes = [
            models.Index(fields=["-timestamp"]),
            models.Index(fields=["action"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["user", "-timestamp"]),
        ]
        # Django 2.1+ 默认提供 view_<modelname> 权限，无需自定义

    def __str__(self) -> str:
        return f"{self.timestamp} - {self.get_action_display()} - {self.ip_address}"

    def save(self, force_insert=False, force_update=False, *args, **kwargs) -> None:
        """重写save方法，只允许插入，不允许更新"""
        if self.pk is not None and not force_insert:
            raise ValidationError("审计日志不可修改")
        super().save(force_insert=True, *args, **kwargs)

    def delete(self, *args, **kwargs) -> None:
        """禁止删除审计日志"""
        raise ValidationError("审计日志不可删除")

    def get_display_message(self) -> str:
        """生成用户友好的操作描述"""
        # 获取子网显示文本
        subnet_text = ""
        if self.subnet:
            subnet_text = self.subnet.network
        elif self.subnet_network:
            subnet_text = self.subnet_network
        elif self.details and isinstance(self.details, dict) and "subnet" in self.details:
            subnet_text = self.details["subnet"]

        # 根据操作类型生成描述
        messages = {
            "allocate": f"分配 IP 地址 {self.ip_address}",
            "release": f"释放 IP 地址 {self.ip_address}",
            "update": f"更新 IP 地址 {self.ip_address} 信息",
            "delete": f"删除 IP 地址 {self.ip_address}",
            "create_subnet": f"创建子网 {subnet_text}",
            "update_subnet": f"更新子网 {subnet_text} 信息",
            "delete_subnet": f"删除子网 {subnet_text}",
            "snmp_scan": "SNMP 扫描完成",
            "conflict_detected": f"检测到 IP {self.ip_address} 的 MAC 地址冲突",
        }

        base_msg = messages.get(self.action, f"执行操作: {self.get_action_display()}")

        # 添加主机名信息（如果有）
        if self.hostname and self.action in ("allocate", "release", "update"):
            base_msg += f" (主机名: {self.hostname})"

        return base_msg

    def get_subnet_display(self) -> str:
        """获取子网显示文本"""
        if self.subnet:
            return self.subnet.network
        elif self.subnet_network:
            return f"{self.subnet_network} (已删除)"
        elif self.details and isinstance(self.details, dict) and "subnet" in self.details:
            return self.details["subnet"]
        return ""

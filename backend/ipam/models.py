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

    def get_usage_stats(self) -> dict[str, int]:
        """获取使用统计"""
        ips = self.ip_addresses.all()
        return {
            "total": self.total_ips,
            "usable": self.usable_ips,
            "available": ips.filter(status="available").count(),
            "allocated": ips.filter(status="allocated").count(),
            "reserved": ips.filter(status="reserved").count(),
            "conflict": ips.filter(status="conflict").count(),
        }


class IpAddress(models.Model):
    """IP地址模型"""

    STATUS_CHOICES = [
        ("available", "可用"),
        ("allocated", "已分配"),
        ("reserved", "保留"),
        ("conflict", "冲突"),
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


class NetworkDevice(models.Model):
    """网络设备模型（SNMP扫描目标）"""

    SNMP_VERSION_CHOICES = [
        ("v2c", "SNMPv2c"),
        ("v3", "SNMPv3"),
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
        ("conflict_detected", "检测到冲突"),
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

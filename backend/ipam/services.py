"""
IPAM业务逻辑服务层

包含IP分配、释放、冲突检测等核心业务逻辑
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional
from django.db import transaction
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import IpAddress, Subnet, AuditLog

if TYPE_CHECKING:
    from django.contrib.auth.models import User


class IPAllocationService:
    """IP地址分配服务（并发安全）"""

    MAX_RETRIES = 3
    RETRY_DELAY = 0.1  # 100ms

    @classmethod
    @transaction.atomic
    def allocate_ip(
        cls,
        ip_id: int,
        user: User,
        hostname: str = "",
        mac_address: str = "",
        device_type: str = "",
        department: str = "",
        responsible_person: str = "",
        notes: str = "",
    ) -> IpAddress:
        """
        分配IP地址（带并发控制）

        使用select_for_update()行锁 + 重试机制避免竞态条件

        Args:
            ip_id: IP地址记录ID
            user: 分配用户
            hostname: 主机名
            mac_address: MAC地址
            device_type: 设备类型
            department: 使用部门
            responsible_person: 责任人
            notes: 备注

        Returns:
            已分配的IP地址对象

        Raises:
            ValidationError: IP不可用或参数无效
        """
        for attempt in range(cls.MAX_RETRIES):
            try:
                # 数据库行锁（阻塞模式）
                ip = IpAddress.objects.select_for_update().get(pk=ip_id)

                # CAS验证：检查状态是否仍然可用
                if ip.status != "available":
                    raise ValidationError(
                        f"IP地址 {ip.address} 当前状态为 {ip.get_status_display()}，无法分配"
                    )

                # 执行分配
                ip.status = "allocated"
                ip.hostname = hostname
                ip.mac_address = mac_address
                ip.device_type = device_type
                ip.department = department
                ip.responsible_person = responsible_person
                ip.notes = notes
                ip.allocated_at = timezone.now()
                ip.allocated_by = user

                # 更新previous_mac_address用于冲突检测
                if mac_address and not ip.previous_mac_address:
                    ip.previous_mac_address = mac_address

                ip.save()

                # 记录审计日志
                AuditLog.objects.create(
                    user=user,
                    action="allocate",
                    ip_address=ip.address,
                    hostname=hostname,
                    mac_address=mac_address,
                    details={
                        "device_type": device_type,
                        "department": department,
                        "responsible_person": responsible_person,
                        "subnet": ip.subnet.network,
                    }
                )

                return ip

            except IpAddress.DoesNotExist as e:
                raise ValidationError(f"IP地址记录不存在: ID={ip_id}") from e

            except Exception as e:
                # 其他数据库错误（如死锁），重试
                if attempt < cls.MAX_RETRIES - 1:
                    time.sleep(cls.RETRY_DELAY * (attempt + 1))  # 指数退避
                    continue
                raise

        raise ValidationError("IP分配失败：超过最大重试次数")

    @classmethod
    @transaction.atomic
    def allocate_next_available_ip(
        cls,
        subnet_id: int,
        user: User,
        hostname: str = "",
        mac_address: str = "",
        device_type: str = "",
        department: str = "",
        responsible_person: str = "",
        notes: str = "",
    ) -> IpAddress:
        """
        从子网中分配下一个可用IP

        Args:
            subnet_id: 子网ID
            user: 分配用户
            其他参数同allocate_ip

        Returns:
            已分配的IP地址对象

        Raises:
            ValidationError: 子网不存在或无可用IP
        """
        try:
            subnet = Subnet.objects.get(pk=subnet_id)
        except Subnet.DoesNotExist as e:
            raise ValidationError(f"子网不存在: ID={subnet_id}") from e

        # 查找第一个可用IP（加锁）
        available_ip = (
            IpAddress.objects
            .select_for_update(skip_locked=True)  # 跳过已锁定的行
            .filter(subnet=subnet, status="available")
            .first()
        )

        if not available_ip:
            raise ValidationError(f"子网 {subnet.network} 没有可用IP地址")

        # 使用allocate_ip进行分配
        return cls.allocate_ip(
            ip_id=available_ip.id,
            user=user,
            hostname=hostname,
            mac_address=mac_address,
            device_type=device_type,
            department=department,
            responsible_person=responsible_person,
            notes=notes,
        )

    @classmethod
    @transaction.atomic
    def release_ip(
        cls,
        ip_id: int,
        user: User,
        keep_info: bool = False
    ) -> IpAddress:
        """
        释放IP地址

        Args:
            ip_id: IP地址记录ID
            user: 操作用户
            keep_info: 是否保留设备信息（默认清空）

        Returns:
            已释放的IP地址对象

        Raises:
            ValidationError: IP不存在或状态无效
        """
        try:
            ip = IpAddress.objects.select_for_update().get(pk=ip_id)
        except IpAddress.DoesNotExist as e:
            raise ValidationError(f"IP地址记录不存在: ID={ip_id}") from e

        # 记录释放前的信息
        old_hostname = ip.hostname
        old_mac = ip.mac_address
        old_device_type = ip.device_type

        # 执行释放
        ip.status = "available"
        ip.allocated_at = None
        ip.allocated_by = None

        if not keep_info:
            ip.hostname = ""
            ip.mac_address = ""
            ip.device_type = ""
            ip.department = ""
            ip.responsible_person = ""
            ip.notes = ""

        ip.save()

        # 记录审计日志
        AuditLog.objects.create(
            user=user,
            action="release",
            ip_address=ip.address,
            hostname=old_hostname,
            mac_address=old_mac,
            details={
                "device_type": old_device_type,
                "keep_info": keep_info,
                "subnet": ip.subnet.network,
            }
        )

        return ip

    @classmethod
    @transaction.atomic
    def update_ip_info(
        cls,
        ip_id: int,
        user: User,
        **fields
    ) -> IpAddress:
        """
        更新IP地址信息

        Args:
            ip_id: IP地址记录ID
            user: 操作用户
            **fields: 要更新的字段（hostname, mac_address, device_type等）

        Returns:
            更新后的IP地址对象
        """
        try:
            ip = IpAddress.objects.select_for_update().get(pk=ip_id)
        except IpAddress.DoesNotExist as e:
            raise ValidationError(f"IP地址记录不存在: ID={ip_id}") from e

        # 记录变更前的值
        changes = {}
        for field, value in fields.items():
            if hasattr(ip, field):
                old_value = getattr(ip, field)
                if old_value != value:
                    changes[field] = {"old": old_value, "new": value}
                    setattr(ip, field, value)

        if not changes:
            return ip  # 没有变化，直接返回

        ip.save()

        # 记录审计日志
        AuditLog.objects.create(
            user=user,
            action="update",
            ip_address=ip.address,
            hostname=ip.hostname,
            mac_address=ip.mac_address,
            details={
                "changes": changes,
                "subnet": ip.subnet.network,
            }
        )

        return ip


class ConflictDetectionService:
    """IP冲突检测服务"""

    @classmethod
    @transaction.atomic
    def detect_mac_conflict(
        cls,
        ip_address: str,
        scanned_mac: str,
        scan_source: str = "SNMP"
    ) -> Optional[IpAddress]:
        """
        检测MAC地址冲突

        Args:
            ip_address: IP地址
            scanned_mac: 扫描到的MAC地址
            scan_source: 扫描来源（SNMP/ARP等）

        Returns:
            冲突的IP对象（如果有冲突），否则返回None
        """
        try:
            ip = IpAddress.objects.select_for_update().get(address=ip_address)
        except IpAddress.DoesNotExist:
            return None

        # 如果IP未分配，更新MAC地址
        if ip.status == "available":
            ip.mac_address = scanned_mac
            ip.previous_mac_address = scanned_mac
            ip.save()
            return None

        # 如果已分配，检查MAC是否变化
        if ip.mac_address and ip.mac_address != scanned_mac:
            # 检测到MAC地址变化 - 可能是冲突
            ip.status = "conflict"
            ip.conflict_detected_at = timezone.now()
            ip.previous_mac_address = ip.mac_address  # 保存旧MAC
            ip.save()

            # 记录审计日志
            AuditLog.objects.create(
                user=None,  # 系统自动检测
                action="conflict_detected",
                ip_address=ip.address,
                hostname=ip.hostname,
                mac_address=scanned_mac,
                details={
                    "old_mac": ip.mac_address,
                    "new_mac": scanned_mac,
                    "scan_source": scan_source,
                    "subnet": ip.subnet.network,
                }
            )

            return ip

        return None

    @classmethod
    def resolve_conflict(
        cls,
        ip_id: int,
        user: User,
        resolution: str = "keep_current"
    ) -> IpAddress:
        """
        解决IP冲突

        Args:
            ip_id: IP地址记录ID
            user: 操作用户
            resolution: 解决方案（keep_current保留当前/update_mac更新MAC/release释放）

        Returns:
            解决后的IP对象
        """
        try:
            ip = IpAddress.objects.select_for_update().get(pk=ip_id)
        except IpAddress.DoesNotExist as e:
            raise ValidationError(f"IP地址记录不存在: ID={ip_id}") from e

        if ip.status != "conflict":
            raise ValidationError(f"IP地址 {ip.address} 不处于冲突状态")

        if resolution == "keep_current":
            # 保留当前配置，恢复为已分配状态
            ip.status = "allocated"
            ip.conflict_detected_at = None

        elif resolution == "update_mac":
            # 更新为扫描到的MAC（存储在previous_mac_address）
            ip.status = "allocated"
            # MAC已在检测时更新，这里只需恢复状态
            ip.conflict_detected_at = None

        elif resolution == "release":
            # 释放IP
            return IPAllocationService.release_ip(ip_id, user)

        else:
            raise ValidationError(f"无效的解决方案: {resolution}")

        ip.save()

        # 记录审计日志
        AuditLog.objects.create(
            user=user,
            action="update",
            ip_address=ip.address,
            hostname=ip.hostname,
            mac_address=ip.mac_address,
            details={
                "resolution": resolution,
                "conflict_resolved": True,
            }
        )

        return ip

"""
SNMP扫描模块

使用pysnmp-lextudio进行SNMP扫描
获取网络设备的ARP表信息，用于IP-MAC映射

注意：pysnmp-lextudio 6.x 使用异步API
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from django.db import transaction
from django.utils import timezone

# pysnmp imports (异步版本)
from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    nextCmd,
    isEndOfMib,
    usmHMACMD5AuthProtocol,
    usmHMACSHAAuthProtocol,
    usmDESPrivProtocol,
    usmAesCfb128Protocol,
)

from .models import NetworkDevice, IpAddress, Subnet
from .services import ConflictDetectionService

logger = logging.getLogger(__name__)

# SNMP OIDs
# ipNetToMediaPhysAddress - ARP表的MAC地址
ARP_TABLE_OID = "1.3.6.1.2.1.4.22.1.2"
# ipNetToMediaNetAddress - ARP表的IP地址
ARP_IP_OID = "1.3.6.1.2.1.4.22.1.3"
# ipNetToMediaType - ARP条目类型
ARP_TYPE_OID = "1.3.6.1.2.1.4.22.1.4"


@dataclass
class ArpEntry:
    """ARP表条目"""
    ip_address: str
    mac_address: str
    interface_index: int
    entry_type: int  # 1=other, 2=invalid, 3=dynamic, 4=static


class SNMPScanner:
    """SNMP扫描器（同步版本）"""

    TIMEOUT = 5  # 秒
    RETRIES = 2

    def __init__(self, device: NetworkDevice):
        """
        初始化扫描器

        Args:
            device: 网络设备对象
        """
        self.device = device
        self.engine = SnmpEngine()

    def _get_auth_data(self) -> CommunityData | UsmUserData:
        """
        获取SNMP认证数据

        Returns:
            CommunityData（v2c）或UsmUserData（v3）
        """
        if self.device.snmp_version == "v2c":
            return CommunityData(
                self.device.snmp_community or "public",
                mpModel=1  # SNMPv2c
            )
        elif self.device.snmp_version == "v3":
            # SNMPv3认证
            auth_password = self.device.get_snmp_auth_password()
            priv_password = self.device.get_snmp_priv_password()

            # 认证协议
            auth_protocol = usmHMACSHAAuthProtocol  # 默认SHA

            # 加密协议
            priv_protocol = usmAesCfb128Protocol if priv_password else None

            return UsmUserData(
                userName=self.device.snmp_username or "admin",
                authKey=auth_password or None,
                privKey=priv_password or None,
                authProtocol=auth_protocol if auth_password else None,
                privProtocol=priv_protocol,
            )
        else:
            # 默认使用v2c
            return CommunityData("public", mpModel=1)

    def _get_transport_target(self) -> UdpTransportTarget:
        """获取SNMP传输目标"""
        return UdpTransportTarget(
            (self.device.ip_address, 161),
            timeout=self.TIMEOUT,
            retries=self.RETRIES,
        )

    def _format_mac_address(self, raw_mac: bytes) -> str:
        """
        格式化MAC地址

        Args:
            raw_mac: 原始MAC字节

        Returns:
            格式化的MAC地址字符串（AA:BB:CC:DD:EE:FF）
        """
        if isinstance(raw_mac, bytes) and len(raw_mac) == 6:
            return ":".join(f"{b:02X}" for b in raw_mac)
        elif isinstance(raw_mac, str):
            # 有时候返回的是十六进制字符串
            clean = raw_mac.replace(":", "").replace("-", "").replace(" ", "")
            if len(clean) == 12:
                return ":".join(clean[i:i+2].upper() for i in range(0, 12, 2))
        return str(raw_mac)

    async def _async_scan_arp_table(self) -> List[ArpEntry]:
        """
        异步扫描设备ARP表

        Returns:
            ARP条目列表
        """
        entries = []
        auth_data = self._get_auth_data()
        transport = self._get_transport_target()

        try:
            # 初始 OID
            current_oid = ObjectType(ObjectIdentity(ARP_TABLE_OID))

            # 使用 nextCmd 循环遍历 ARP 表
            max_iterations = 10000  # 防止无限循环
            iteration = 0

            while iteration < max_iterations:
                iteration += 1

                errorIndication, errorStatus, errorIndex, varBinds = await nextCmd(
                    self.engine,
                    auth_data,
                    transport,
                    ContextData(),
                    current_oid,
                )

                if errorIndication:
                    logger.error(f"SNMP错误 [{self.device.name}]: {errorIndication}")
                    break

                if errorStatus:
                    logger.error(
                        f"SNMP状态错误 [{self.device.name}]: "
                        f"{errorStatus.prettyPrint()} at {errorIndex}"
                    )
                    break

                # 检查是否到达 MIB 末尾
                if not varBinds:
                    break

                # pysnmp 6.x 返回嵌套列表: [[ObjectType(...)]]
                # 需要正确处理这个结构
                last_oid_obj = None
                should_continue = True

                for varBindRow in varBinds:
                    if not isinstance(varBindRow, list):
                        varBindRow = [varBindRow]

                    for varBind in varBindRow:
                        try:
                            # ObjectType 支持索引访问 [0]=OID, [1]=Value
                            oid_obj = varBind[0]
                            value_obj = varBind[1]
                            oid = str(oid_obj)
                            last_oid_obj = oid_obj
                        except (IndexError, AttributeError, TypeError) as e:
                            logger.warning(f"无法解析varBind: {type(varBind)} - {e}")
                            continue

                        # 检查是否超出 ARP_TABLE_OID 范围
                        if not oid.startswith(ARP_TABLE_OID):
                            should_continue = False
                            break

                        # 解析OID获取接口索引和IP地址
                        # OID格式: 1.3.6.1.2.1.4.22.1.2.<ifIndex>.<ipAddr>
                        oid_parts = oid.split(".")
                        if len(oid_parts) >= 15:
                            try:
                                if_index = int(oid_parts[10])
                                ip_addr = ".".join(oid_parts[11:15])

                                # 安全获取 MAC 地址
                                if hasattr(value_obj, 'prettyPrint'):
                                    raw_value = value_obj.prettyPrint()
                                    # 处理 0x 开头的十六进制字符串
                                    if raw_value.startswith('0x'):
                                        hex_str = raw_value[2:]
                                        mac_addr = ":".join(
                                            hex_str[i:i+2].upper()
                                            for i in range(0, len(hex_str), 2)
                                        )
                                    else:
                                        mac_addr = self._format_mac_address(bytes(value_obj))
                                else:
                                    mac_addr = self._format_mac_address(bytes(value_obj))

                                entries.append(ArpEntry(
                                    ip_address=ip_addr,
                                    mac_address=mac_addr,
                                    interface_index=if_index,
                                    entry_type=3,  # 默认为dynamic
                                ))
                            except (ValueError, IndexError, TypeError) as e:
                                logger.warning(f"解析ARP条目失败: {oid} - {e}")

                    if not should_continue:
                        break

                if not should_continue:
                    break

                # 更新下一个 OID
                if last_oid_obj is not None:
                    current_oid = ObjectType(last_oid_obj)
                else:
                    break

        except Exception as e:
            logger.exception(f"SNMP扫描异常 [{self.device.name}]: {e}")
            raise

        return entries

    def scan_arp_table(self) -> List[ArpEntry]:
        """
        扫描设备ARP表（同步包装器）

        Returns:
            ARP条目列表
        """
        # 直接使用 asyncio.run()，它会创建新的事件循环
        return asyncio.run(self._async_scan_arp_table())

    def _get_system_subnets(self) -> List[ipaddress.IPv4Network]:
        """获取系统中所有已创建的子网"""
        subnets = []
        for subnet in Subnet.objects.all():
            try:
                network = ipaddress.ip_network(subnet.network, strict=False)
                subnets.append(network)
            except ValueError as e:
                logger.warning(f"无效的子网格式: {subnet.network} - {e}")
        return subnets

    def _is_ip_in_system_subnets(
        self, ip_str: str, subnets: List[ipaddress.IPv4Network]
    ) -> bool:
        """检查 IP 是否在系统子网内"""
        try:
            ip = ipaddress.ip_address(ip_str)
            return any(ip in subnet for subnet in subnets)
        except ValueError:
            return False

    def _is_valid_arp_entry(self, entry: ArpEntry) -> bool:
        """
        验证 ARP 条目是否有效

        过滤条件：
        1. IP 地址必须是有效的 IPv4 地址
        2. MAC 地址必须是有效格式（6字节，非全0/全F）
        3. 排除广播和组播 MAC

        Returns:
            True 如果条目有效
        """
        # 验证 IP 地址
        try:
            ip = ipaddress.ip_address(entry.ip_address)
            # 排除环回、链路本地等特殊地址
            if ip.is_loopback or ip.is_link_local or ip.is_multicast:
                return False
        except ValueError:
            logger.debug(f"无效 IP 地址: {entry.ip_address}")
            return False

        # 验证 MAC 地址格式
        mac = entry.mac_address.upper().replace("-", ":").replace(".", ":")
        parts = mac.split(":")

        # 必须是 6 段
        if len(parts) != 6:
            logger.debug(f"无效 MAC 格式: {entry.mac_address}")
            return False

        try:
            bytes_list = [int(p, 16) for p in parts]
        except ValueError:
            logger.debug(f"MAC 包含非十六进制: {entry.mac_address}")
            return False

        # 排除全 0 MAC (00:00:00:00:00:00)
        if all(b == 0 for b in bytes_list):
            logger.debug(f"过滤全零 MAC: {entry.ip_address}")
            return False

        # 排除全 F MAC (FF:FF:FF:FF:FF:FF) - 广播地址
        if all(b == 255 for b in bytes_list):
            logger.debug(f"过滤广播 MAC: {entry.ip_address}")
            return False

        # 排除组播 MAC（第一字节最低位为1）
        if bytes_list[0] & 0x01:
            logger.debug(f"过滤组播 MAC: {entry.mac_address}")
            return False

        return True

    def scan_and_update(self) -> Tuple[int, int, int]:
        """
        扫描并更新数据库

        只处理系统中已创建子网内的 IP 地址，
        其他网段的 IP 将被过滤掉。

        优化：
        - 使用 bulk_update 批量更新 IP
        - 跟踪 last_seen_at 和 consecutive_missing

        Returns:
            (扫描数量, 更新数量, 冲突数量)
        """
        scanned = 0
        updated = 0
        conflicts = 0
        filtered = 0

        try:
            entries = self.scan_arp_table()
            total_entries = len(entries)

            # 获取系统子网列表用于过滤
            system_subnets = self._get_system_subnets()
            logger.info(f"系统子网数量: {len(system_subnets)}")

            # 收集有效的 ARP 条目
            valid_entries: Dict[str, ArpEntry] = {}

            for entry in entries:
                # 验证 ARP 条目完整性（IP/MAC格式有效性）
                if not self._is_valid_arp_entry(entry):
                    filtered += 1
                    continue

                # 检查 IP 是否在系统子网内
                if not self._is_ip_in_system_subnets(entry.ip_address, system_subnets):
                    filtered += 1
                    logger.debug(f"过滤非系统子网 IP: {entry.ip_address}")
                    continue

                scanned += 1
                valid_entries[entry.ip_address] = entry

            # 使用事务包装数据库操作（select_for_update 需要事务）
            with transaction.atomic():
                # 批量查询现有 IP 记录
                existing_ips = {
                    ip.address: ip
                    for ip in IpAddress.objects.filter(
                        address__in=valid_entries.keys()
                    ).select_for_update(skip_locked=True)
                }

                now = timezone.now()
                ips_to_update: List[IpAddress] = []
                update_fields = ["mac_address", "last_seen_at", "consecutive_missing"]

                for ip_addr, entry in valid_entries.items():
                    # 检测冲突
                    conflict_ip = ConflictDetectionService.detect_mac_conflict(
                        ip_address=entry.ip_address,
                        scanned_mac=entry.mac_address,
                        scan_source="SNMP",
                    )

                    if conflict_ip:
                        conflicts += 1
                        continue

                    # 尝试更新 IP
                    ip = existing_ips.get(ip_addr)
                    if ip:
                        changed = False

                        # 更新 last_seen_at
                        ip.last_seen_at = now
                        ip.consecutive_missing = 0
                        changed = True

                        # 更新 MAC 地址（仅 available 或 occupied 状态）
                        if ip.status in ("available", "occupied"):
                            if ip.mac_address != entry.mac_address:
                                ip.mac_address = entry.mac_address
                                updated += 1

                        if changed:
                            ips_to_update.append(ip)

                # 批量更新
                if ips_to_update:
                    IpAddress.objects.bulk_update(ips_to_update, update_fields, batch_size=100)
                    logger.info(f"批量更新 {len(ips_to_update)} 条 IP 记录")

            # 更新设备扫描状态
            self.device.last_scan_at = now
            self.device.last_scan_status = "success"
            self.device.last_scan_error = ""
            self.device.save()

            logger.info(
                f"SNMP扫描完成 [{self.device.name}]: "
                f"总数{total_entries}, 有效{scanned}, 过滤{filtered}, "
                f"更新{updated}, 冲突{conflicts}"
            )

        except Exception as e:
            # 更新设备错误状态
            self.device.last_scan_at = timezone.now()
            self.device.last_scan_status = "error"
            self.device.last_scan_error = str(e)[:500]
            self.device.save()

            logger.error(f"SNMP扫描失败 [{self.device.name}]: {e}")
            raise

        return scanned, updated, conflicts


class SNMPScanManager:
    """SNMP扫描管理器"""

    @classmethod
    def get_devices_due_for_scan(cls) -> List[NetworkDevice]:
        """
        获取需要扫描的设备列表

        根据每个设备的 scan_interval_minutes 字段，
        只返回已到期需要扫描的设备。

        添加30秒缓冲区：由于调度任务从任务结束时间计算下次运行，
        而设备的 last_scan_at 在扫描完成时才更新，可能导致
        任务运行时设备还差几秒才到期。30秒缓冲区解决这个时间差问题。

        Returns:
            需要扫描的设备列表
        """
        from datetime import timedelta

        now = timezone.now()
        # 30秒缓冲区，解决调度任务与设备扫描时间的微小差异
        buffer = timedelta(seconds=30)
        devices_to_scan = []

        for device in NetworkDevice.objects.filter(enabled=True):
            # 如果从未扫描过，需要扫描
            if device.last_scan_at is None:
                devices_to_scan.append(device)
                continue

            # 计算下次扫描时间
            interval = timedelta(minutes=device.scan_interval_minutes)
            next_scan_time = device.last_scan_at + interval

            # 如果已到期或接近到期（在缓冲区内），需要扫描
            if now >= next_scan_time - buffer:
                devices_to_scan.append(device)

        logger.info(
            f"设备扫描检查: {len(devices_to_scan)} 台需要扫描 "
            f"(总启用设备: {NetworkDevice.objects.filter(enabled=True).count()})"
        )

        return devices_to_scan

    @classmethod
    def scan_all_devices(cls, force: bool = False) -> Dict[str, Any]:
        """
        扫描所有启用的设备

        Args:
            force: 强制扫描所有设备，忽略 scan_interval_minutes

        Returns:
            扫描结果统计
        """
        if force:
            devices = list(NetworkDevice.objects.filter(enabled=True))
        else:
            devices = cls.get_devices_due_for_scan()

        results = {
            "total_devices": len(devices),
            "successful": 0,
            "failed": 0,
            "total_scanned": 0,
            "total_updated": 0,
            "total_conflicts": 0,
            "errors": [],
            "skipped": 0,
        }

        for device in devices:
            try:
                scanner = SNMPScanner(device)
                scanned, updated, conflicts = scanner.scan_and_update()

                results["successful"] += 1
                results["total_scanned"] += scanned
                results["total_updated"] += updated
                results["total_conflicts"] += conflicts

            except Exception as e:
                results["failed"] += 1
                results["errors"].append({
                    "device": device.name,
                    "ip": device.ip_address,
                    "error": str(e),
                })

        return results

    @classmethod
    def scan_device(cls, device_id: int) -> Dict[str, Any]:
        """
        扫描单个设备

        Args:
            device_id: 设备ID

        Returns:
            扫描结果
        """
        try:
            device = NetworkDevice.objects.get(pk=device_id)
        except NetworkDevice.DoesNotExist:
            return {"error": f"设备不存在: ID={device_id}"}

        if not device.enabled:
            return {"error": f"设备未启用: {device.name}"}

        try:
            scanner = SNMPScanner(device)
            scanned, updated, conflicts = scanner.scan_and_update()

            return {
                "success": True,
                "device": device.name,
                "scanned": scanned,
                "updated": updated,
                "conflicts": conflicts,
            }
        except Exception as e:
            return {
                "success": False,
                "device": device.name,
                "error": str(e),
            }

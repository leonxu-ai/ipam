"""
SNMP扫描模块

使用pysnmp-lextudio进行同步SNMP扫描
获取网络设备的ARP表信息，用于IP-MAC映射
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass
from django.utils import timezone

# pysnmp imports
from pysnmp.hlapi import (
    SnmpEngine,
    CommunityData,
    UsmUserData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    nextCmd,
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

    def scan_arp_table(self) -> List[ArpEntry]:
        """
        扫描设备ARP表

        Returns:
            ARP条目列表
        """
        entries = []
        auth_data = self._get_auth_data()
        transport = self._get_transport_target()

        try:
            # 使用SNMP GETNEXT遍历ARP表
            for (errorIndication, errorStatus, errorIndex, varBinds) in nextCmd(
                self.engine,
                auth_data,
                transport,
                ContextData(),
                ObjectType(ObjectIdentity(ARP_TABLE_OID)),
                lexicographicMode=False,
            ):
                if errorIndication:
                    logger.error(f"SNMP错误 [{self.device.name}]: {errorIndication}")
                    break

                if errorStatus:
                    logger.error(
                        f"SNMP状态错误 [{self.device.name}]: "
                        f"{errorStatus.prettyPrint()} at {errorIndex}"
                    )
                    break

                for varBind in varBinds:
                    oid = str(varBind[0])
                    value = varBind[1]

                    # 解析OID获取接口索引和IP地址
                    # OID格式: 1.3.6.1.2.1.4.22.1.2.<ifIndex>.<ipAddr>
                    oid_parts = oid.split(".")
                    if len(oid_parts) >= 15:
                        try:
                            if_index = int(oid_parts[10])
                            ip_addr = ".".join(oid_parts[11:15])
                            mac_addr = self._format_mac_address(bytes(value))

                            entries.append(ArpEntry(
                                ip_address=ip_addr,
                                mac_address=mac_addr,
                                interface_index=if_index,
                                entry_type=3,  # 默认为dynamic
                            ))
                        except (ValueError, IndexError) as e:
                            logger.warning(f"解析ARP条目失败: {oid} - {e}")

        except Exception as e:
            logger.exception(f"SNMP扫描异常 [{self.device.name}]: {e}")
            raise

        return entries

    def scan_and_update(self) -> Tuple[int, int, int]:
        """
        扫描并更新数据库

        Returns:
            (扫描数量, 更新数量, 冲突数量)
        """
        scanned = 0
        updated = 0
        conflicts = 0

        try:
            entries = self.scan_arp_table()
            scanned = len(entries)

            for entry in entries:
                # 检测冲突
                conflict_ip = ConflictDetectionService.detect_mac_conflict(
                    ip_address=entry.ip_address,
                    scanned_mac=entry.mac_address,
                    scan_source="SNMP",
                )

                if conflict_ip:
                    conflicts += 1
                else:
                    # 尝试更新IP的MAC地址（如果存在且未分配）
                    try:
                        ip = IpAddress.objects.get(address=entry.ip_address)
                        if ip.status == "available" and ip.mac_address != entry.mac_address:
                            ip.mac_address = entry.mac_address
                            ip.save()
                            updated += 1
                    except IpAddress.DoesNotExist:
                        pass

            # 更新设备扫描状态
            self.device.last_scan_at = timezone.now()
            self.device.last_scan_status = "success"
            self.device.last_scan_error = None
            self.device.save()

            logger.info(
                f"SNMP扫描完成 [{self.device.name}]: "
                f"扫描{scanned}, 更新{updated}, 冲突{conflicts}"
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
    def scan_all_devices(cls) -> Dict[str, Any]:
        """
        扫描所有启用的设备

        Returns:
            扫描结果统计
        """
        devices = NetworkDevice.objects.filter(enabled=True)
        results = {
            "total_devices": devices.count(),
            "successful": 0,
            "failed": 0,
            "total_scanned": 0,
            "total_updated": 0,
            "total_conflicts": 0,
            "errors": [],
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

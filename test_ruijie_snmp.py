#!/usr/bin/env python3
"""
锐捷无线控制器 SNMP 诊断脚本

用于诊断和测试锐捷设备的 SNMP 配置
"""

import asyncio
from pysnmp.hlapi.asyncio import (
    SnmpEngine,
    CommunityData,
    UdpTransportTarget,
    ContextData,
    ObjectType,
    ObjectIdentity,
    nextCmd,
    getCmd,
)

# 锐捷设备信息
DEVICE_IP = "10.75.255.118"
COMMUNITY = "zhld2018"

# 常用 OID
SYSTEM_OID = "1.3.6.1.2.1.1.1.0"  # sysDescr - 系统描述
UPTIME_OID = "1.3.6.1.2.1.1.3.0"  # sysUpTime - 系统运行时间
CONTACT_OID = "1.3.6.1.2.1.1.4.0"  # sysContact - 系统联系人
NAME_OID = "1.3.6.1.2.1.1.5.0"  # sysName - 系统名称
LOCATION_OID = "1.3.6.1.2.1.1.6.0"  # sysLocation - 系统位置

# ARP 表 OID
ARP_TABLE_OID = "1.3.6.1.2.1.4.22.1.2"  # ipNetToMediaPhysAddress
ARP_IP_OID = "1.3.6.1.2.1.4.22.1.3"  # ipNetToMediaNetAddress

# 备用 ARP 表 OID (新版)
IP_NET_TO_PHYSICAL_PHYS_ADDRESS = "1.3.6.1.2.1.4.35.1.4"  # ipNetToPhysicalPhysAddress


async def test_system_info():
    """测试系统信息"""
    print("=" * 60)
    print("测试 1: 获取锐捷设备系统信息")
    print("=" * 60)

    engine = SnmpEngine()
    auth = CommunityData(COMMUNITY, mpModel=1)
    transport = UdpTransportTarget((DEVICE_IP, 161), timeout=5, retries=2)

    oids = [
        ("系统描述", SYSTEM_OID),
        ("系统名称", NAME_OID),
        ("系统位置", LOCATION_OID),
        ("系统联系人", CONTACT_OID),
        ("系统运行时间", UPTIME_OID),
    ]

    for name, oid in oids:
        try:
            errorIndication, errorStatus, errorIndex, varBinds = await getCmd(
                engine, auth, transport, ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            if errorIndication:
                print(f"✗ {name}: SNMP 错误 - {errorIndication}")
            elif errorStatus:
                print(f"✗ {name}: SNMP 状态错误 - {errorStatus.prettyPrint()}")
            else:
                for varBind in varBinds:
                    value = varBind[1] if isinstance(varBind, (list, tuple)) else varBind.prettyPrint()
                    print(f"✓ {name}: {value}")

        except Exception as e:
            print(f"✗ {name}: 错误 - {e}")


async def test_arp_table_walk(oid_name, oid):
    """遍历 ARP 表"""
    print(f"\n尝试 OID: {oid_name} ({oid})")
    print("-" * 60)

    engine = SnmpEngine()
    auth = CommunityData(COMMUNITY, mpModel=1)
    transport = UdpTransportTarget((DEVICE_IP, 161), timeout=5, retries=2)

    entries = []
    iteration = 0
    max_iterations = 100

    try:
        current_oid = ObjectType(ObjectIdentity(oid))

        while iteration < max_iterations:
            iteration += 1

            errorIndication, errorStatus, errorIndex, varBinds = await nextCmd(
                engine, auth, transport, ContextData(), current_oid
            )

            if errorIndication:
                print(f"  ✗ SNMP 错误: {errorIndication}")
                break

            if errorStatus:
                print(f"  ✗ SNMP 状态错误: {errorStatus.prettyPrint()}")
                break

            if not varBinds:
                break

            for varBind in varBinds:
                try:
                    # 安全获取 OID 和值
                    if isinstance(varBind, (list, tuple)) and len(varBind) >= 2:
                        oid_obj = varBind[0]
                        value_obj = varBind[1]
                    else:
                        oid_obj = varBind.getName() if hasattr(varBind, 'getName') else varBind[0]
                        value_obj = varBind.getValue() if hasattr(varBind, 'getValue') else varBind[1]

                    oid_str = str(oid_obj)

                    # 检查是否超出范围
                    if not oid_str.startswith(oid):
                        print(f"  → 到达 OID 末尾，停止遍历")
                        return entries

                    # 解析值
                    if hasattr(value_obj, 'prettyPrint'):
                        value = value_obj.prettyPrint()
                    else:
                        value = str(value_obj)

                    entries.append({
                        'oid': oid_str,
                        'value': value
                    })

                    # 更新下一个 OID
                    current_oid = ObjectType(oid_obj)

                except Exception as e:
                    print(f"  ⚠ 解析 varBind 失败: {e}")
                    continue

    except Exception as e:
        print(f"  ✗ 遍历失败: {e}")

    return entries


async def test_arp_tables():
    """测试 ARP 表获取"""
    print("\n" + "=" * 60)
    print("测试 2: 尝试获取 ARP 表")
    print("=" * 60)

    # 测试旧版 ARP 表 OID
    entries1 = await test_arp_table_walk("旧版 ARP 表 (ipNetToMediaPhysAddress)", ARP_TABLE_OID)
    if entries1:
        print(f"\n  ✓ 找到 {len(entries1)} 条记录")
        print("  前 5 条:")
        for entry in entries1[:5]:
            print(f"    OID: {entry['oid']}")
            print(f"    值:  {entry['value']}")
    else:
        print(f"  ✗ 未找到记录")

    # 测试新版 ARP 表 OID
    entries2 = await test_arp_table_walk("新版 ARP 表 (ipNetToPhysicalPhysAddress)", IP_NET_TO_PHYSICAL_PHYS_ADDRESS)
    if entries2:
        print(f"\n  ✓ 找到 {len(entries2)} 条记录")
        print("  前 5 条:")
        for entry in entries2[:5]:
            print(f"    OID: {entry['oid']}")
            print(f"    值:  {entry['value']}")
    else:
        print(f"  ✗ 未找到记录")

    # 尝试直接遍历 IP MIB
    print("\n尝试遍历整个 IP MIB (1.3.6.1.2.1.4)")
    print("-" * 60)
    entries3 = await test_arp_table_walk("IP MIB", "1.3.6.1.2.1.4")
    if entries3:
        print(f"  ✓ 找到 {len(entries3)} 条记录")
        print(f"  显示前 20 条:")
        for entry in entries3[:20]:
            print(f"    {entry['oid']}: {entry['value']}")
    else:
        print(f"  ✗ 未找到记录")


async def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("锐捷无线控制器 AC SNMP 诊断")
    print("=" * 60)
    print(f"设备 IP: {DEVICE_IP}")
    print(f"Community: {COMMUNITY}")
    print("=" * 60)

    # 测试系统信息
    await test_system_info()

    # 测试 ARP 表
    await test_arp_tables()

    print("\n" + "=" * 60)
    print("诊断完成")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())

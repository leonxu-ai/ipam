#!/usr/bin/env python3
"""
SNMP 扫描器本地测试脚本

用于测试 SNMP 扫描功能，不需要启动 Django 服务器
可以直接在命令行运行测试

用法:
    python3 test_snmp_scan.py
    python3 test_snmp_scan.py --device-ip 192.168.1.1 --community public
"""

import os
import sys
import django
import argparse
import time
from typing import Dict, Any

# 设置 Django 环境
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ipam_project.settings')
os.environ['USE_SQLITE'] = 'True'  # 使用 SQLite 以便独立测试

# Django 设置路径
sys.path.insert(0, '/opt/ipim/backend')
django.setup()

# 导入 Django 模型和扫描器
from ipam.models import NetworkDevice, IpAddress, Subnet
from ipam.snmp_scanner import SNMPScanner, SNMPScanManager


def test_scanner_basic():
    """测试扫描器基本功能"""
    print("=" * 60)
    print("测试 1: 扫描器基本功能测试")
    print("=" * 60)

    # 测试创建扫描器
    try:
        # 创建测试设备
        device, created = NetworkDevice.objects.get_or_create(
            name="测试设备",
            defaults={
                "ip_address": "127.0.0.1",
                "snmp_version": "v2c",
                "snmp_community": "public",
                "enabled": True,
            }
        )

        if created:
            print(f"✓ 创建测试设备: {device.name} ({device.ip_address})")
        else:
            print(f"✓ 使用已存在设备: {device.name} ({device.ip_address})")

        # 创建扫描器实例
        scanner = SNMPScanner(device)
        print(f"✓ SNMP 扫描器实例创建成功")
        print(f"  - SNMP 版本: {device.snmp_version}")

        return True
    except Exception as e:
        print(f"✗ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_snmp_connection(device_ip: str, community: str = "public"):
    """测试 SNMP 连接"""
    print("\n" + "=" * 60)
    print(f"测试 2: SNMP 连接测试 ({device_ip})")
    print("=" * 60)

    try:
        # 创建或更新测试设备
        device, _ = NetworkDevice.objects.update_or_create(
            ip_address=device_ip,
            defaults={
                "name": f"SNMP测试_{device_ip}",
                "snmp_version": "v2c",
                "snmp_community": community,
                "enabled": True,
            }
        )

        print(f"✓ 设备配置:")
        print(f"  - IP: {device.ip_address}")
        print(f"  - Community: {community}")

        # 创建扫描器并尝试扫描
        scanner = SNMPScanner(device)
        print(f"\n⏳ 开始扫描 ARP 表...")

        start_time = time.time()
        entries = scanner.scan_arp_table()
        elapsed = time.time() - start_time

        print(f"\n✓ 扫描完成! 耗时: {elapsed:.2f} 秒")
        print(f"✓ 发现 {len(entries)} 条 ARP 记录")

        if entries:
            print(f"\n前 5 条 ARP 记录:")
            for i, entry in enumerate(entries[:5], 1):
                print(f"  {i}. IP: {entry.ip_address:15s}  MAC: {entry.mac_address}  接口: {entry.interface_index}")

        return True

    except Exception as e:
        print(f"\n✗ SNMP 连接失败: {e}")
        print(f"\n可能的原因:")
        print(f"  1. 设备 IP 不可达")
        print(f"  2. SNMP Community 字符串错误")
        print(f"  3. 设备未启用 SNMP")
        print(f"  4. 防火墙阻止 UDP 161 端口")

        import traceback
        traceback.print_exc()
        return False


def test_full_scan():
    """测试完整扫描流程"""
    print("\n" + "=" * 60)
    print("测试 3: 完整扫描流程测试")
    print("=" * 60)

    try:
        # 确保有测试子网
        subnet, created = Subnet.objects.get_or_create(
            network="192.168.1.0/24",
            defaults={
                "gateway": "192.168.1.1",
                "vlan_id": 100,
            }
        )

        if created:
            print(f"✓ 创建测试子网: {subnet.network}")
        else:
            print(f"✓ 使用已存在子网: {subnet.network}")

        # 获取所有启用的设备
        devices = NetworkDevice.objects.filter(enabled=True)
        print(f"✓ 找到 {devices.count()} 个启用的设备")

        if devices.count() == 0:
            print(f"⚠ 没有启用的设备，跳过扫描测试")
            return True

        # 扫描第一个设备
        device = devices.first()
        print(f"\n⏳ 扫描设备: {device.name} ({device.ip_address})")

        scanner = SNMPScanner(device)
        start_time = time.time()
        scanned, updated, conflicts = scanner.scan_and_update()
        elapsed = time.time() - start_time

        print(f"\n✓ 扫描完成:")
        print(f"  - 扫描记录: {scanned}")
        print(f"  - 更新 IP: {updated}")
        print(f"  - 冲突数量: {conflicts}")
        print(f"  - 耗时: {elapsed:.2f} 秒")

        # 检查设备状态
        device.refresh_from_db()
        print(f"\n设备扫描状态:")
        print(f"  - 状态: {device.last_scan_status}")
        print(f"  - 最后扫描: {device.last_scan_at}")
        if device.last_scan_error:
            print(f"  - 错误信息: {device.last_scan_error}")

        return True

    except Exception as e:
        print(f"\n✗ 完整扫描测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_scan_manager():
    """测试扫描管理器"""
    print("\n" + "=" * 60)
    print("测试 4: 扫描管理器测试")
    print("=" * 60)

    try:
        print("⏳ 使用 SNMPScanManager 扫描所有设备...")

        start_time = time.time()
        results = SNMPScanManager.scan_all_devices()
        elapsed = time.time() - start_time

        print(f"\n✓ 批量扫描完成! 耗时: {elapsed:.2f} 秒")
        print(f"\n扫描结果:")
        print(f"  - 设备总数: {results['total_devices']}")
        print(f"  - 成功: {results['successful']}")
        print(f"  - 失败: {results['failed']}")
        print(f"  - 扫描记录: {results['total_scanned']}")
        print(f"  - 更新 IP: {results['total_updated']}")
        print(f"  - 冲突: {results['total_conflicts']}")

        if results['errors']:
            print(f"\n错误列表:")
            for error in results['errors']:
                print(f"  - {error['device']} ({error['ip']}): {error['error']}")

        return True

    except Exception as e:
        print(f"\n✗ 扫描管理器测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def run_all_tests(device_ip: str = None, community: str = "public"):
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("SNMP 扫描器测试套件")
    print("=" * 60)
    print(f"Django 版本: {django.VERSION}")
    print(f"Python 版本: {sys.version}")
    print("=" * 60)

    results = []

    # 测试 1: 基本功能
    results.append(("基本功能", test_scanner_basic()))

    # 测试 2: SNMP 连接（如果提供了设备 IP）
    if device_ip:
        results.append(("SNMP 连接", test_snmp_connection(device_ip, community)))
        results.append(("完整扫描", test_full_scan()))
        results.append(("扫描管理器", test_scan_manager()))

    # 打印总结
    print("\n" + "=" * 60)
    print("测试总结")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ 通过" if result else "✗ 失败"
        print(f"{status:8s} - {name}")

    print("=" * 60)
    print(f"总计: {passed}/{total} 测试通过")
    print("=" * 60)

    if device_ip is None:
        print("\n💡 提示: 使用 --device-ip 参数测试真实设备的 SNMP 连接")
        print("   例如: python3 test_snmp_scan.py --device-ip 192.168.1.1 --community public")

    return passed == total


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SNMP 扫描器测试脚本")
    parser.add_argument("--device-ip", help="测试设备的 IP 地址")
    parser.add_argument("--community", default="public", help="SNMP Community 字符串 (默认: public)")

    args = parser.parse_args()

    success = run_all_tests(args.device_ip, args.community)
    sys.exit(0 if success else 1)

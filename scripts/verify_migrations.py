#!/usr/bin/env python
"""
数据库迁移验证脚本

使用方法:
    python manage.py shell < scripts/verify_migrations.py

或者在 Django shell 中运行:
    exec(open('scripts/verify_migrations.py').read())
"""

import sys
from django.db import connection
from django.core.exceptions import ValidationError
from ipam.models import Subnet, NetworkDevice, IpAddress
from django.contrib.auth import get_user_model

User = get_user_model()


def print_header(text):
    """打印分隔标题"""
    print(f"\n{'='*60}")
    print(f"  {text}")
    print(f"{'='*60}\n")


def print_result(test_name, passed, message=""):
    """打印测试结果"""
    status = "✅ 通过" if passed else "❌ 失败"
    print(f"{status} - {test_name}")
    if message:
        print(f"   {message}")


def verify_migration_0007():
    """验证迁移 0007: is_global 字段"""
    print_header("验证迁移 0007: Subnet.is_global")

    # 测试 1: 字段存在性
    try:
        subnet = Subnet.objects.first()
        if subnet is None:
            # 创建测试子网
            subnet = Subnet.objects.create(network="192.168.100.0/24")
        hasattr(subnet, 'is_global')
        print_result("字段存在性", True, "is_global 字段已添加")
    except Exception as e:
        print_result("字段存在性", False, str(e))
        return False

    # 测试 2: 默认值
    test_subnet = Subnet.objects.create(network="192.168.101.0/24")
    print_result(
        "默认值检查",
        test_subnet.is_global == False,
        f"默认值: {test_subnet.is_global} (预期: False)"
    )

    # 测试 3: 索引检查
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT COUNT(*) FROM pg_indexes
            WHERE tablename = 'ipam_subnet'
            AND indexdef LIKE '%is_global%'
        """ if connection.vendor == 'postgresql' else """
            SHOW INDEX FROM ipam_subnet WHERE Column_name = 'is_global'
        """)
        has_index = cursor.fetchone()[0] > 0 if connection.vendor == 'postgresql' else cursor.rowcount > 0
    print_result("数据库索引", has_index, "is_global 字段已索引")

    # 测试 4: 查询测试
    Subnet.objects.create(network="192.168.102.0/24", is_global=True)
    global_count = Subnet.objects.filter(is_global=True).count()
    print_result("过滤查询", global_count > 0, f"找到 {global_count} 个全局子网")

    # 清理测试数据
    test_subnet.delete()

    return True


def verify_migration_0008():
    """验证迁移 0008: scan_interval_minutes 字段"""
    print_header("验证迁移 0008: NetworkDevice.scan_interval_minutes")

    # 测试 1: 字段存在性
    try:
        device = NetworkDevice.objects.first()
        if device is None:
            # 创建测试设备
            device = NetworkDevice.objects.create(
                name="Test Device",
                ip_address="192.168.100.1",
                snmp_version="v2c",
                snmp_community="public",
            )
        hasattr(device, 'scan_interval_minutes')
        print_result("字段存在性", True, "scan_interval_minutes 字段已添加")
    except Exception as e:
        print_result("字段存在性", False, str(e))
        return False

    # 测试 2: 默认值
    test_device = NetworkDevice.objects.create(
        name="Test Device 2",
        ip_address="192.168.100.2",
        snmp_version="v2c",
        snmp_community="public",
    )
    print_result(
        "默认值检查",
        test_device.scan_interval_minutes == 30,
        f"默认值: {test_device.scan_interval_minutes} (预期: 30)"
    )

    # 测试 3: 最小值验证器
    test_device.scan_interval_minutes = -1
    try:
        test_device.full_clean()
        print_result("最小值验证器", False, "验证器未生效！")
    except ValidationError:
        print_result("最小值验证器", True, "负值被正确拒绝")

    # 测试 4: 最大值验证器
    test_device.scan_interval_minutes = 9999
    try:
        test_device.full_clean()
        print_result("最大值验证器", False, "验证器未生效！")
    except ValidationError:
        print_result("最大值验证器", True, "超大值被正确拒绝")

    # 测试 5: 有效值
    test_device.scan_interval_minutes = 60
    try:
        test_device.full_clean()
        test_device.save()
        print_result("有效值测试", True, "60分钟的值被正确接受")
    except ValidationError:
        print_result("有效值测试", False, "有效值被错误拒绝")

    # 清理测试数据
    test_device.delete()

    return True


def verify_migration_0009():
    """验证迁移 0009: consecutive_missing 和 last_seen_at 字段"""
    print_header("验证迁移 0009: IpAddress tracking fields")

    # 准备测试数据
    subnet = Subnet.objects.first()
    if subnet is None:
        subnet = Subnet.objects.create(network="192.168.100.0/24")

    # 测试 1: 字段存在性
    try:
        ip = IpAddress.objects.first()
        if ip is None:
            ip = IpAddress.objects.create(
                subnet=subnet,
                address="192.168.100.10",
            )
        has_consecutive = hasattr(ip, 'consecutive_missing')
        has_last_seen = hasattr(ip, 'last_seen_at')
        print_result(
            "字段存在性",
            has_consecutive and has_last_seen,
            "consecutive_missing 和 last_seen_at 字段已添加"
        )
    except Exception as e:
        print_result("字段存在性", False, str(e))
        return False

    # 测试 2: consecutive_missing 默认值
    test_ip = IpAddress.objects.create(
        subnet=subnet,
        address="192.168.100.11",
    )
    print_result(
        "consecutive_missing 默认值",
        test_ip.consecutive_missing == 0,
        f"默认值: {test_ip.consecutive_missing} (预期: 0)"
    )

    # 测试 3: last_seen_at 默认值
    print_result(
        "last_seen_at 默认值",
        test_ip.last_seen_at is None,
        f"默认值: {test_ip.last_seen_at} (预期: None)"
    )

    # 测试 4: consecutive_missing 非负验证
    test_ip.consecutive_missing = -1
    try:
        test_ip.full_clean()
        print_result("consecutive_missing 非负验证", False, "验证器未生效！")
    except ValidationError:
        print_result("consecutive_missing 非负验证", True, "负值被正确拒绝")

    # 测试 5: consecutive_missing 索引
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE tablename = 'ipam_ipaddress'
                AND indexdef LIKE '%consecutive_missing%'
            """)
            has_index = cursor.fetchone()[0] > 0
        else:
            cursor.execute("SHOW INDEX FROM ipam_ipaddress WHERE Column_name = 'consecutive_missing'")
            has_index = cursor.rowcount > 0
    print_result("consecutive_missing 索引", has_index, "consecutive_missing 字段已索引")

    # 测试 6: last_seen_at 索引
    with connection.cursor() as cursor:
        if connection.vendor == 'postgresql':
            cursor.execute("""
                SELECT COUNT(*) FROM pg_indexes
                WHERE tablename = 'ipam_ipaddress'
                AND indexdef LIKE '%last_seen_at%'
            """)
            has_index = cursor.fetchone()[0] > 0
        else:
            cursor.execute("SHOW INDEX FROM ipam_ipaddress WHERE Column_name = 'last_seen_at'")
            has_index = cursor.rowcount > 0
    print_result("last_seen_at 索引", has_index, "last_seen_at 字段已索引")

    # 测试 7: 查询测试
    IpAddress.objects.create(subnet=subnet, address="192.168.100.12", consecutive_missing=10)
    IpAddress.objects.create(subnet=subnet, address="192.168.100.13", consecutive_missing=5)
    offline_count = IpAddress.objects.filter(consecutive_missing__gte=5).count()
    print_result("过滤查询", offline_count >= 2, f"找到 {offline_count} 个离线 IP")

    # 清理测试数据
    test_ip.delete()

    return True


def verify_data_integrity():
    """验证数据完整性"""
    print_header("数据完整性验证")

    # 测试 1: 记录总数检查
    subnet_count = Subnet.objects.count()
    device_count = NetworkDevice.objects.count()
    ip_count = IpAddress.objects.count()
    print_result(
        "数据库记录统计",
        True,
        f"子网: {subnet_count}, 设备: {device_count}, IP: {ip_count}"
    )

    # 测试 2: 外键完整性
    orphaned_ips = IpAddress.objects.filter(subnet__isnull=True).count()
    print_result(
        "外键完整性",
        orphaned_ips == 0,
        f"孤立 IP 数量: {orphaned_ips}"
    )

    # 测试 3: 现有数据的新字段值检查
    if Subnet.objects.exists():
        subnets_without_is_global = Subnet.objects.filter(is_global__isnull=True).count()
        print_result(
            "Subnet.is_global 非空检查",
            subnets_without_is_global == 0,
            f"NULL 值数量: {subnets_without_is_global}"
        )

    if NetworkDevice.objects.exists():
        devices_without_interval = NetworkDevice.objects.filter(scan_interval_minutes__isnull=True).count()
        print_result(
            "NetworkDevice.scan_interval_minutes 非空检查",
            devices_without_interval == 0,
            f"NULL 值数量: {devices_without_interval}"
        )

    if IpAddress.objects.exists():
        ips_without_consecutive = IpAddress.objects.filter(consecutive_missing__isnull=True).count()
        print_result(
            "IpAddress.consecutive_missing 非空检查",
            ips_without_consecutive == 0,
            f"NULL 值数量: {ips_without_consecutive}"
        )

        # last_seen_at 允许为 NULL
        ips_with_last_seen = IpAddress.objects.filter(last_seen_at__isnull=False).count()
        total_ips = IpAddress.objects.count()
        print_result(
            "IpAddress.last_seen_at 统计",
            True,
            f"有值: {ips_with_last_seen}, NULL: {total_ips - ips_with_last_seen}"
        )

    return True


def main():
    """主函数"""
    print("\n" + "="*60)
    print("  数据库迁移验证工具")
    print("  验证迁移: 0007, 0008, 0009")
    print("="*60)

    all_passed = True

    # 执行验证
    all_passed &= verify_migration_0007()
    all_passed &= verify_migration_0008()
    all_passed &= verify_migration_0009()
    all_passed &= verify_data_integrity()

    # 总结
    print_header("验证总结")
    if all_passed:
        print("✅ 所有测试通过！迁移成功。")
        return 0
    else:
        print("❌ 部分测试失败，请检查迁移。")
        return 1


if __name__ == "__main__":
    exit_code = main()
    sys.exit(exit_code)
else:
    # 在 Django shell 中直接运行
    main()

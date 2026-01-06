"""
数据库迁移测试

测试迁移 0007, 0008, 0009 的数据完整性
"""

from django.test import TestCase
from django.core.exceptions import ValidationError
from django.db import IntegrityError
from django.utils import timezone
from ipam.models import Subnet, NetworkDevice, IpAddress
from django.contrib.auth import get_user_model

User = get_user_model()


class Migration0007TestCase(TestCase):
    """测试迁移 0007: 添加 is_global 到 Subnet"""

    def setUp(self):
        """创建测试数据"""
        self.subnet = Subnet.objects.create(
            network="192.168.1.0/24",
            gateway="192.168.1.1",
        )

    def test_default_is_global_is_false(self):
        """测试默认值为 False"""
        subnet = Subnet.objects.create(network="10.0.0.0/24")
        self.assertFalse(subnet.is_global)

    def test_can_set_is_global_to_true(self):
        """测试可以设置为 True"""
        self.subnet.is_global = True
        self.subnet.save()
        self.subnet.refresh_from_db()
        self.assertTrue(self.subnet.is_global)

    def test_is_global_not_null(self):
        """测试字段不允许 NULL"""
        # Django BooleanField 默认 null=False
        subnet = Subnet.objects.create(network="172.16.0.0/16")
        self.assertIsNotNone(subnet.is_global)

    def test_filter_by_is_global(self):
        """测试按 is_global 过滤"""
        Subnet.objects.create(network="10.1.0.0/24", is_global=True)
        Subnet.objects.create(network="10.2.0.0/24", is_global=False)

        global_subnets = Subnet.objects.filter(is_global=True)
        private_subnets = Subnet.objects.filter(is_global=False)

        self.assertEqual(global_subnets.count(), 1)
        self.assertEqual(private_subnets.count(), 2)  # 包括 setUp 中的 subnet


class Migration0008TestCase(TestCase):
    """测试迁移 0008: 添加 scan_interval_minutes 到 NetworkDevice"""

    def setUp(self):
        """创建测试数据"""
        self.device = NetworkDevice.objects.create(
            name="Core Switch",
            ip_address="192.168.1.254",
            snmp_version="v2c",
            snmp_community="public",
        )

    def test_default_scan_interval_is_30(self):
        """测试默认扫描间隔为 30 分钟"""
        device = NetworkDevice.objects.create(
            name="Test Device",
            ip_address="10.0.0.1",
            snmp_version="v2c",
            snmp_community="public",
        )
        self.assertEqual(device.scan_interval_minutes, 30)

    def test_can_set_valid_scan_interval(self):
        """测试可以设置有效的扫描间隔"""
        valid_intervals = [1, 5, 15, 30, 60, 120, 1440]
        for interval in valid_intervals:
            self.device.scan_interval_minutes = interval
            self.device.full_clean()  # 应该不抛出异常
            self.device.save()

    def test_scan_interval_minimum_validation(self):
        """测试扫描间隔最小值验证（应用层）"""
        self.device.scan_interval_minutes = 0
        with self.assertRaises(ValidationError) as cm:
            self.device.full_clean()
        self.assertIn('scan_interval_minutes', cm.exception.error_dict)

        self.device.scan_interval_minutes = -1
        with self.assertRaises(ValidationError) as cm:
            self.device.full_clean()
        self.assertIn('scan_interval_minutes', cm.exception.error_dict)

    def test_scan_interval_maximum_validation(self):
        """测试扫描间隔最大值验证（应用层）"""
        self.device.scan_interval_minutes = 1441
        with self.assertRaises(ValidationError) as cm:
            self.device.full_clean()
        self.assertIn('scan_interval_minutes', cm.exception.error_dict)

        self.device.scan_interval_minutes = 9999
        with self.assertRaises(ValidationError) as cm:
            self.device.full_clean()
        self.assertIn('scan_interval_minutes', cm.exception.error_dict)

    def test_scan_interval_not_null(self):
        """测试字段不允许 NULL"""
        device = NetworkDevice.objects.create(
            name="Test Device 2",
            ip_address="10.0.0.2",
            snmp_version="v2c",
            snmp_community="public",
        )
        self.assertIsNotNone(device.scan_interval_minutes)


class Migration0009TestCase(TestCase):
    """测试迁移 0009: 添加 consecutive_missing 和 last_seen_at 到 IpAddress"""

    def setUp(self):
        """创建测试数据"""
        self.user = User.objects.create_user(username="testuser", password="testpass")
        self.subnet = Subnet.objects.create(network="192.168.1.0/24")
        self.ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="192.168.1.10",
            status="available",
        )

    def test_default_consecutive_missing_is_zero(self):
        """测试 consecutive_missing 默认值为 0"""
        ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="192.168.1.20",
            status="available",
        )
        self.assertEqual(ip.consecutive_missing, 0)

    def test_default_last_seen_at_is_null(self):
        """测试 last_seen_at 默认值为 NULL"""
        ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="192.168.1.30",
            status="available",
        )
        self.assertIsNone(ip.last_seen_at)

    def test_can_set_consecutive_missing(self):
        """测试可以设置 consecutive_missing"""
        valid_values = [0, 1, 5, 10, 100]
        for value in valid_values:
            self.ip.consecutive_missing = value
            self.ip.full_clean()  # 应该不抛出异常
            self.ip.save()
            self.ip.refresh_from_db()
            self.assertEqual(self.ip.consecutive_missing, value)

    def test_consecutive_missing_cannot_be_negative(self):
        """测试 consecutive_missing 不能为负数（应用层）"""
        self.ip.consecutive_missing = -1
        with self.assertRaises(ValidationError) as cm:
            self.ip.full_clean()
        self.assertIn('consecutive_missing', cm.exception.error_dict)

        self.ip.consecutive_missing = -100
        with self.assertRaises(ValidationError) as cm:
            self.ip.full_clean()
        self.assertIn('consecutive_missing', cm.exception.error_dict)

    def test_can_set_last_seen_at(self):
        """测试可以设置 last_seen_at"""
        now = timezone.now()
        self.ip.last_seen_at = now
        self.ip.save()
        self.ip.refresh_from_db()
        self.assertIsNotNone(self.ip.last_seen_at)
        # 允许微小的时间差异
        time_diff = abs((self.ip.last_seen_at - now).total_seconds())
        self.assertLess(time_diff, 1)

    def test_last_seen_at_can_be_null(self):
        """测试 last_seen_at 可以为 NULL"""
        self.ip.last_seen_at = None
        self.ip.full_clean()  # 应该不抛出异常
        self.ip.save()
        self.ip.refresh_from_db()
        self.assertIsNone(self.ip.last_seen_at)

    def test_consecutive_missing_not_null(self):
        """测试 consecutive_missing 不允许 NULL"""
        ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="192.168.1.40",
            status="available",
        )
        self.assertIsNotNone(ip.consecutive_missing)

    def test_filter_by_consecutive_missing(self):
        """测试按 consecutive_missing 过滤"""
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.50", consecutive_missing=0)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.51", consecutive_missing=5)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.52", consecutive_missing=10)

        offline_ips = IpAddress.objects.filter(consecutive_missing__gte=5)
        self.assertEqual(offline_ips.count(), 2)

        online_ips = IpAddress.objects.filter(consecutive_missing=0)
        self.assertEqual(online_ips.count(), 2)  # 包括 setUp 中的 self.ip

    def test_filter_by_last_seen_at(self):
        """测试按 last_seen_at 过滤"""
        now = timezone.now()
        old_time = now - timezone.timedelta(days=7)

        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.60", last_seen_at=now)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.61", last_seen_at=old_time)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.62", last_seen_at=None)

        recently_seen = IpAddress.objects.filter(
            last_seen_at__gte=now - timezone.timedelta(days=1)
        )
        self.assertEqual(recently_seen.count(), 1)

        never_seen = IpAddress.objects.filter(last_seen_at__isnull=True)
        self.assertEqual(never_seen.count(), 2)  # 包括 setUp 中的 self.ip

    def test_order_by_consecutive_missing(self):
        """测试按 consecutive_missing 排序"""
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.70", consecutive_missing=10)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.71", consecutive_missing=5)
        IpAddress.objects.create(subnet=self.subnet, address="192.168.1.72", consecutive_missing=20)

        ordered_ips = IpAddress.objects.order_by('-consecutive_missing')
        self.assertEqual(ordered_ips[0].consecutive_missing, 20)
        self.assertEqual(ordered_ips[1].consecutive_missing, 10)


class DataIntegrityTestCase(TestCase):
    """综合数据完整性测试"""

    def setUp(self):
        """创建测试数据"""
        self.user = User.objects.create_user(username="admin", password="admin")
        self.subnet = Subnet.objects.create(
            network="10.0.0.0/24",
            is_global=True,
        )
        self.device = NetworkDevice.objects.create(
            name="Router",
            ip_address="10.0.0.1",
            snmp_version="v2c",
            snmp_community="public",
            scan_interval_minutes=60,
        )

    def test_complex_query_with_new_fields(self):
        """测试包含新字段的复杂查询"""
        # 创建多个 IP，模拟真实场景
        for i in range(10):
            IpAddress.objects.create(
                subnet=self.subnet,
                address=f"10.0.0.{i+10}",
                status="available",
                consecutive_missing=i,
                last_seen_at=timezone.now() - timezone.timedelta(days=i) if i > 0 else None,
            )

        # 查询：全局子网中，连续缺失超过5次的IP
        offline_ips = IpAddress.objects.filter(
            subnet__is_global=True,
            consecutive_missing__gte=5,
        )
        self.assertEqual(offline_ips.count(), 5)

        # 查询：7天内未见过的IP
        threshold = timezone.now() - timezone.timedelta(days=7)
        long_missing_ips = IpAddress.objects.filter(
            last_seen_at__lt=threshold,
        )
        self.assertEqual(long_missing_ips.count(), 3)

    def test_migration_backward_compatibility(self):
        """测试迁移前后的数据兼容性"""
        # 模拟迁移前创建的数据（没有新字段值）
        ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="10.0.0.100",
            status="allocated",
            hostname="test-server",
        )

        # 验证新字段有默认值
        self.assertEqual(ip.consecutive_missing, 0)
        self.assertIsNone(ip.last_seen_at)

        # 验证旧字段不受影响
        self.assertEqual(ip.hostname, "test-server")
        self.assertEqual(ip.status, "allocated")

"""
IPAM单元测试
"""

from django.test import TestCase, TransactionTestCase
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from .models import Subnet, IpAddress, NetworkDevice, AuditLog
from .services import IPAllocationService, ConflictDetectionService

User = get_user_model()


class SubnetModelTest(TestCase):
    """子网模型测试"""

    def setUp(self):
        """测试前准备"""
        self.subnet = Subnet.objects.create(
            network="192.168.1.0/24",
            gateway="192.168.1.1",
            vlan_id=100,
            description="测试子网"
        )

    def test_subnet_creation(self):
        """测试子网创建"""
        self.assertEqual(self.subnet.network, "192.168.1.0/24")
        self.assertEqual(self.subnet.gateway, "192.168.1.1")
        self.assertIsNotNone(self.subnet.netmask)

    def test_subnet_total_ips(self):
        """测试IP总数计算"""
        self.assertEqual(self.subnet.total_ips, 256)

    def test_subnet_usable_ips(self):
        """测试可用IP数量"""
        self.assertEqual(self.subnet.usable_ips, 254)  # 排除网络地址和广播地址


class IpAddressModelTest(TestCase):
    """IP地址模型测试"""

    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.subnet = Subnet.objects.create(network="10.0.0.0/24", gateway="10.0.0.1")
        self.ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="10.0.0.10",
            status="available"
        )

    def test_ip_creation(self):
        """测试IP创建"""
        self.assertEqual(self.ip.address, "10.0.0.10")
        self.assertEqual(self.ip.status, "available")

    def test_ip_allocation(self):
        """测试IP分配"""
        self.ip.allocate(
            user=self.user,
            hostname="server01",
            mac_address="AA:BB:CC:DD:EE:FF",
            device_type="服务器"
        )

        self.assertEqual(self.ip.status, "allocated")
        self.assertEqual(self.ip.hostname, "server01")
        self.assertEqual(self.ip.allocated_by, self.user)
        self.assertIsNotNone(self.ip.allocated_at)


class IPAllocationServiceTest(TransactionTestCase):
    """IP分配服务测试"""

    def setUp(self):
        """测试前准备"""
        self.user = User.objects.create_user(username="testuser", password="test123")
        self.subnet = Subnet.objects.create(network="172.16.0.0/24")

        # 创建可用IP
        self.available_ip = IpAddress.objects.create(
            subnet=self.subnet,
            address="172.16.0.10",
            status="available"
        )

    def test_allocate_ip_success(self):
        """测试成功分配IP"""
        result = IPAllocationService.allocate_ip(
            ip_id=self.available_ip.id,
            user=self.user,
            hostname="test-server",
            mac_address="11:22:33:44:55:66"
        )

        self.assertEqual(result.status, "allocated")
        self.assertEqual(result.hostname, "test-server")

        # 验证审计日志
        audit = AuditLog.objects.filter(action="allocate", ip_address="172.16.0.10").first()
        self.assertIsNotNone(audit)
        self.assertEqual(audit.user, self.user)


class NetworkDeviceModelTest(TestCase):
    """网络设备模型测试"""

    def test_device_creation(self):
        """测试设备创建"""
        device = NetworkDevice.objects.create(
            name="Core Switch",
            ip_address="192.168.1.1",
            snmp_version="v2c",
            snmp_community="public"
        )

        self.assertEqual(device.name, "Core Switch")
        self.assertTrue(device.enabled)

    def test_snmp_credential_encryption(self):
        """测试SNMP凭证加密"""
        device = NetworkDevice.objects.create(
            name="Encrypted Device",
            ip_address="10.0.0.2",
            snmp_version="v3",
            snmp_username="admin"
        )

        # 设置加密密码
        device.set_snmp_auth_password("secret123")
        device.save()

        # 验证加密存储
        self.assertNotEqual(device.snmp_auth_password_encrypted, "secret123")
        self.assertTrue(len(device.snmp_auth_password_encrypted) > 20)

        # 验证解密
        decrypted = device.get_snmp_auth_password()
        self.assertEqual(decrypted, "secret123")

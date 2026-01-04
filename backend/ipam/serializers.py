"""
IPAM API序列化器
"""

from rest_framework import serializers
from .models import Subnet, IpAddress, NetworkDevice, AuditLog


class SubnetSerializer(serializers.ModelSerializer):
    """子网序列化器"""

    usage_stats = serializers.SerializerMethodField()

    class Meta:
        model = Subnet
        fields = [
            'id', 'network', 'gateway', 'netmask', 'vlan_id',
            'description', 'created_at', 'updated_at', 'usage_stats'
        ]
        read_only_fields = ['created_at', 'updated_at', 'usage_stats']

    def get_usage_stats(self, obj):
        """获取使用统计"""
        return obj.get_usage_stats()


class IpAddressSerializer(serializers.ModelSerializer):
    """IP地址序列化器"""

    subnet_network = serializers.CharField(source='subnet.network', read_only=True)
    allocated_by_username = serializers.CharField(source='allocated_by.username', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = IpAddress
        fields = [
            'id', 'subnet', 'subnet_network', 'address', 'status', 'status_display',
            'hostname', 'mac_address', 'device_type', 'department', 'responsible_person',
            'allocated_at', 'allocated_by', 'allocated_by_username',
            'conflict_detected_at', 'previous_mac_address', 'notes',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'allocated_at', 'allocated_by',
            'conflict_detected_at', 'previous_mac_address'
        ]


class IpAddressListSerializer(serializers.ModelSerializer):
    """IP地址列表序列化器（轻量级）"""

    subnet_network = serializers.CharField(source='subnet.network', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = IpAddress
        fields = [
            'id', 'address', 'status', 'status_display',
            'hostname', 'mac_address', 'device_type',
            'subnet_network', 'allocated_at'
        ]


class IpAddressAllocationSerializer(serializers.Serializer):
    """IP分配请求序列化器"""

    ip_id = serializers.IntegerField(help_text="IP地址记录ID")
    hostname = serializers.CharField(max_length=255, required=False, allow_blank=True)
    mac_address = serializers.CharField(max_length=17, required=False, allow_blank=True)
    device_type = serializers.CharField(max_length=100, required=False, allow_blank=True)
    department = serializers.CharField(max_length=200, required=False, allow_blank=True)
    responsible_person = serializers.CharField(max_length=100, required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class IpAddressReleaseSerializer(serializers.Serializer):
    """IP释放请求序列化器"""

    ip_id = serializers.IntegerField(help_text="IP地址记录ID")
    keep_info = serializers.BooleanField(default=False, help_text="是否保留设备信息")


class NetworkDeviceSerializer(serializers.ModelSerializer):
    """网络设备序列化器"""

    snmp_version_display = serializers.CharField(source='get_snmp_version_display', read_only=True)

    # 明文密码字段（仅写入）
    snmp_auth_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="SNMPv3认证密码（明文，自动加密存储）"
    )
    snmp_priv_password = serializers.CharField(
        write_only=True,
        required=False,
        allow_blank=True,
        help_text="SNMPv3隐私密码（明文，自动加密存储）"
    )

    class Meta:
        model = NetworkDevice
        fields = [
            'id', 'name', 'ip_address', 'snmp_version', 'snmp_version_display',
            'snmp_community', 'snmp_username',
            'snmp_auth_password', 'snmp_priv_password',  # 写入字段
            'enabled', 'last_scan_at', 'last_scan_status', 'last_scan_error',
            'created_at', 'updated_at'
        ]
        read_only_fields = [
            'last_scan_at', 'last_scan_status', 'last_scan_error',
            'created_at', 'updated_at'
        ]

    def create(self, validated_data):
        """创建网络设备（处理密码加密）"""
        auth_password = validated_data.pop('snmp_auth_password', None)
        priv_password = validated_data.pop('snmp_priv_password', None)

        device = NetworkDevice.objects.create(**validated_data)

        if auth_password:
            device.set_snmp_auth_password(auth_password)
        if priv_password:
            device.set_snmp_priv_password(priv_password)

        if auth_password or priv_password:
            device.save()

        return device

    def update(self, instance, validated_data):
        """更新网络设备（处理密码加密）"""
        auth_password = validated_data.pop('snmp_auth_password', None)
        priv_password = validated_data.pop('snmp_priv_password', None)

        for attr, value in validated_data.items():
            setattr(instance, attr, value)

        if auth_password:
            instance.set_snmp_auth_password(auth_password)
        if priv_password:
            instance.set_snmp_priv_password(priv_password)

        instance.save()
        return instance


class AuditLogSerializer(serializers.ModelSerializer):
    """审计日志序列化器"""

    user_username = serializers.CharField(source='user.username', read_only=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    class Meta:
        model = AuditLog
        fields = [
            'id', 'timestamp', 'user', 'user_username',
            'action', 'action_display',
            'ip_address', 'hostname', 'mac_address', 'details'
        ]
        read_only_fields = '__all__'  # 审计日志完全只读


class SubnetInitializeSerializer(serializers.Serializer):
    """子网IP初始化请求序列化器"""

    exclude_gateway = serializers.BooleanField(
        default=True,
        help_text="是否排除网关地址"
    )
    exclude_broadcast = serializers.BooleanField(
        default=True,
        help_text="是否排除广播地址"
    )
    reserve_first_n = serializers.IntegerField(
        default=0,
        min_value=0,
        help_text="保留前N个IP地址"
    )

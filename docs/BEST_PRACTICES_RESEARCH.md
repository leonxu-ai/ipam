# Django 网络设备管理最佳实践研究报告

> 研究日期: 2026-01-05
> 适用于: Django + Paramiko/Netmiko + Django-Q2 + SNMP 网络设备管理系统

---

## 目录

1. [Django + Paramiko/Netmiko SSH 集成](#1-django--paramikonetmiko-ssh-集成)
2. [Django-Q2 异步任务执行](#2-django-q2-异步任务执行)
3. [实时进度更新方案](#3-实时进度更新方案)
4. [敏感凭证存储](#4-敏感凭证存储)
5. [SNMP ARP表扫描](#5-snmp-arp表扫描)
6. [处理不完整的ARP条目](#6-处理不完整的arp条目)
7. [IP地址模糊搜索](#7-ip地址模糊搜索)

---

## 1. Django + Paramiko/Netmiko SSH 集成

### 核心建议: 使用 Netmiko 而非直接使用 Paramiko

**理由**: Netmiko 是基于 Paramiko 的高级封装,专门为网络设备设计,解决了 Paramiko 在网络设备连接中的诸多问题。

### 1.1 连接参数最佳实践

```python
from netmiko import ConnectHandler
from netmiko.exceptions import (
    NetmikoTimeoutException,
    NetmikoAuthenticationException,
    ConfigInvalidException,
    ReadTimeout
)

# 推荐的连接配置
device_config = {
    'device_type': 'cisco_ios',  # 或其他支持的设备类型
    'host': '192.168.1.1',
    'username': 'admin',
    'password': credentials.password,  # 从加密存储获取

    # 超时配置 (关键!)
    'timeout': 100,              # 命令执行超时 (秒)
    'conn_timeout': 10,          # TCP连接超时 (秒)
    'auth_timeout': 30,          # 认证超时 (秒)
    'banner_timeout': 15,        # SSH banner 超时 (秒)
    'blocking_timeout': 20,      # 阻塞操作超时 (秒)
    'read_timeout_override': None,  # 覆盖默认读取超时

    # SSH 密钥认证 (优先于密码)
    'use_keys': True,
    'key_file': '/path/to/private/key',
    'passphrase': None,

    # 安全配置
    'ssh_strict': False,         # 接受未知主机密钥 (生产环境谨慎使用)
    'system_host_keys': True,    # 加载系统 known_hosts
    'allow_agent': False,        # 禁用 SSH agent

    # 性能优化
    'fast_cli': True,            # 优化性能,减少延迟
    'global_delay_factor': 1.0,  # 全局延迟因子
    'keepalive': 30,             # SSH keepalive 间隔 (秒)

    # 日志和调试
    'session_log': 'session.log',
    'session_log_record_writes': False,
    'verbose': False,
}
```

### 1.2 错误处理模式

```python
def connect_to_device(device_config, max_retries=3):
    """
    连接网络设备的健壮模式

    Args:
        device_config: 设备连接配置字典
        max_retries: 最大重试次数

    Returns:
        connection: Netmiko 连接对象

    Raises:
        自定义异常: 统一处理所有连接错误
    """
    for attempt in range(max_retries):
        try:
            # 使用上下文管理器自动处理连接关闭
            connection = ConnectHandler(**device_config)

            # 验证连接
            connection.find_prompt()

            return connection

        except NetmikoAuthenticationException as e:
            # 认证失败 - 不应重试
            logger.error(f"Authentication failed for {device_config['host']}: {e}")
            raise DeviceAuthenticationError(f"Invalid credentials for {device_config['host']}")

        except NetmikoTimeoutException as e:
            # 连接超时 - 可以重试
            logger.warning(f"Connection timeout (attempt {attempt+1}/{max_retries}): {e}")
            if attempt == max_retries - 1:
                raise DeviceConnectionError(f"Device unreachable: {device_config['host']}")
            time.sleep(2 ** attempt)  # 指数退避

        except ReadTimeout as e:
            # 读取超时 - 命令执行时间过长
            logger.error(f"Command execution timeout: {e}")
            raise CommandExecutionError("Command took too long to execute")

        except ConfigInvalidException as e:
            # 配置错误 - 不应重试
            logger.error(f"Invalid configuration: {e}")
            raise DeviceConfigError(str(e))

        except Exception as e:
            # 其他未知错误
            logger.exception(f"Unexpected error connecting to device: {e}")
            if attempt == max_retries - 1:
                raise DeviceConnectionError(f"Failed to connect: {str(e)}")
            time.sleep(2 ** attempt)

def execute_command_safe(connection, command, read_timeout=60):
    """
    安全执行命令,带超时和错误处理
    """
    try:
        output = connection.send_command(
            command,
            read_timeout=read_timeout,
            expect_string=None,  # 使用默认提示符
            strip_prompt=True,
            strip_command=True,
        )
        return output

    except ReadTimeout:
        logger.error(f"Command '{command}' timed out after {read_timeout}s")
        raise CommandTimeoutError(f"Command timeout: {command}")

    except Exception as e:
        logger.exception(f"Error executing command '{command}': {e}")
        raise CommandExecutionError(str(e))
```

### 1.3 连接池管理 (Django 集成)

**重要**: SSH 连接不应使用传统的数据库连接池模式,而应按需创建和销毁。

```python
# models.py
from django.db import models
from django.core.exceptions import ValidationError

class NetworkDevice(models.Model):
    """网络设备模型"""

    hostname = models.CharField(max_length=255, unique=True)
    ip_address = models.GenericIPAddressField()
    device_type = models.CharField(
        max_length=50,
        choices=[
            ('cisco_ios', 'Cisco IOS'),
            ('cisco_nxos', 'Cisco NX-OS'),
            ('huawei', 'Huawei'),
            ('ruijie_os', 'Ruijie OS'),
            # ... 其他设备类型
        ]
    )

    # 凭证引用 (不直接存储)
    credential = models.ForeignKey(
        'DeviceCredential',
        on_delete=models.PROTECT,
        related_name='devices'
    )

    # 连接配置
    ssh_port = models.PositiveIntegerField(default=22)
    connection_timeout = models.PositiveIntegerField(default=10)
    command_timeout = models.PositiveIntegerField(default=100)

    is_active = models.BooleanField(default=True)
    last_connected = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'network_devices'
        indexes = [
            models.Index(fields=['ip_address']),
            models.Index(fields=['is_active']),
        ]

    def get_connection_params(self):
        """
        获取 Netmiko 连接参数
        """
        return {
            'device_type': self.device_type,
            'host': self.ip_address,
            'username': self.credential.get_username(),
            'password': self.credential.get_password(),  # 解密
            'port': self.ssh_port,
            'timeout': self.command_timeout,
            'conn_timeout': self.connection_timeout,
            'auth_timeout': 30,
            'fast_cli': True,
            'session_log': None,  # 在任务中配置
        }

    def connect(self):
        """
        建立 SSH 连接

        Returns:
            ConnectHandler: Netmiko 连接对象
        """
        from .ssh_manager import SSHConnectionManager

        params = self.get_connection_params()
        connection = SSHConnectionManager.connect(params)

        # 更新最后连接时间
        self.last_connected = timezone.now()
        self.save(update_fields=['last_connected'])

        return connection


# ssh_manager.py
from netmiko import ConnectHandler
from django.core.cache import cache
import logging

logger = logging.getLogger(__name__)

class SSHConnectionManager:
    """
    SSH 连接管理器

    不使用连接池,而是提供统一的连接创建和错误处理
    """

    @staticmethod
    def connect(device_params, max_retries=3):
        """
        创建 SSH 连接

        Args:
            device_params: Netmiko 连接参数
            max_retries: 最大重试次数

        Returns:
            connection: Netmiko 连接对象
        """
        # ... (使用上面的 connect_to_device 实现)
        pass

    @staticmethod
    def execute_with_retry(connection, command, retries=2):
        """
        执行命令,失败时重试
        """
        for attempt in range(retries + 1):
            try:
                return execute_command_safe(connection, command)
            except CommandTimeoutError:
                if attempt == retries:
                    raise
                logger.warning(f"Retrying command (attempt {attempt+2}/{retries+1})")
                time.sleep(1)

    @staticmethod
    def close_connection(connection):
        """
        安全关闭连接
        """
        if connection:
            try:
                connection.disconnect()
            except Exception as e:
                logger.warning(f"Error closing connection: {e}")
```

### 1.4 Django 视图/服务层集成

```python
# services.py
from contextlib import contextmanager
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

@contextmanager
def device_connection(device):
    """
    设备连接上下文管理器

    使用示例:
        with device_connection(device) as conn:
            output = conn.send_command('show version')
    """
    connection = None
    try:
        connection = device.connect()
        yield connection

    except DeviceAuthenticationError as e:
        # 记录认证失败
        DeviceLog.objects.create(
            device=device,
            event_type='auth_failed',
            message=str(e),
            severity='error'
        )
        raise

    except DeviceConnectionError as e:
        # 记录连接失败
        DeviceLog.objects.create(
            device=device,
            event_type='connection_failed',
            message=str(e),
            severity='error'
        )
        raise

    finally:
        # 确保连接被关闭
        if connection:
            SSHConnectionManager.close_connection(connection)


class DeviceManagementService:
    """
    设备管理服务层
    """

    @staticmethod
    def get_device_info(device_id):
        """
        获取设备信息 (同步操作 - 仅用于快速命令)
        """
        device = NetworkDevice.objects.get(id=device_id)

        with device_connection(device) as conn:
            # 执行快速命令
            version = conn.send_command('show version')
            interfaces = conn.send_command('show ip interface brief')

        return {
            'version': version,
            'interfaces': interfaces,
        }

    @staticmethod
    def execute_long_command(device_id, command, timeout=300):
        """
        执行长时间运行的命令 (应在异步任务中调用)

        Args:
            device_id: 设备 ID
            command: 要执行的命令
            timeout: 命令超时时间 (秒)

        Returns:
            dict: 命令执行结果
        """
        device = NetworkDevice.objects.get(id=device_id)

        with device_connection(device) as conn:
            start_time = timezone.now()

            try:
                output = conn.send_command(
                    command,
                    read_timeout=timeout,
                )

                execution_time = (timezone.now() - start_time).total_seconds()

                return {
                    'success': True,
                    'output': output,
                    'execution_time': execution_time,
                }

            except CommandTimeoutError as e:
                return {
                    'success': False,
                    'error': str(e),
                    'execution_time': timeout,
                }
```

### 1.5 生产环境安全考虑

1. **SSH 密钥优先于密码**: 生产环境应使用 SSH 密钥认证
2. **禁用 SSH Agent**: 设置 `allow_agent=False` 避免意外使用本地密钥
3. **严格的主机密钥验证**: 生产环境应设置 `ssh_strict=True` 并维护 known_hosts
4. **超时配置**: 根据网络延迟调整,避免长时间挂起
5. **连接日志**: 记录所有 SSH 连接活动用于审计
6. **最小权限原则**: 设备账号仅授予必要权限

### 相关资源

- [Netmiko GitHub](https://github.com/ktbyers/netmiko) - 多供应商网络设备 SSH 库
- [Netmiko 官方文档](https://github.com/ktbyers/netmiko/tree/develop/docs)
- [Paramiko 官方文档](https://github.com/paramiko/paramiko)

---

## 2. Django-Q2 异步任务执行

### 2.1 为什么选择 Django-Q2

**Django-Q2** 是 Django-Q 的现代化分支,活跃维护,支持最新 Django 版本。

**优势**:
- 简单配置,无需 Redis (可使用 ORM 后端)
- 原生支持定时任务和 cron
- 内置管理界面监控任务
- 支持任务组和链式任务
- 轻量级,适合中小型项目

**适用场景**:
- 小型到中型 Django 项目
- 需要周期性任务的应用
- 不想引入 Redis/RabbitMQ 的项目

### 2.2 推荐配置

```python
# settings.py

# Django-Q2 集群配置
Q_CLUSTER = {
    # 基础配置
    'name': 'IPAMQueue',           # 集群名称
    'workers': 4,                   # 工作进程数 (根据 CPU 核心数调整)
    'recycle': 500,                 # 工作进程处理多少任务后回收
    'timeout': 300,                 # 任务超时时间 (秒) - 重要!
    'retry': 300,                   # 失败任务重试间隔 (秒)
    'queue_limit': 100,             # 队列任务数限制
    'bulk': 10,                     # 批量处理任务数

    # 后端选择
    # 选项 1: ORM 后端 (简单,无需 Redis)
    'orm': 'default',               # 使用 Django ORM 存储任务

    # 选项 2: Redis 后端 (生产环境推荐)
    # 'redis': {
    #     'host': 'localhost',
    #     'port': 6379,
    #     'db': 0,
    #     'password': None,
    #     'socket_timeout': 10,
    #     'charset': 'utf-8',
    # },

    # 结果存储
    'save_limit': 1000,             # 保留结果数量限制
    'cached': False,                # 是否使用缓存存储结果

    # 性能优化
    'compress': True,               # 压缩任务数据
    'cpu_affinity': 1,              # CPU 亲和性

    # 错误处理
    'error_reporter': {
        'function': 'myapp.tasks.error_reporter',
    },

    # 日志
    'log_level': 'INFO',
    'label': 'Django Q2',

    # 定时任务
    'scheduler': True,              # 启用调度器
    'catch_up': True,               # 启动时执行错过的任务

    # 生产环境设置
    'sync': False,                  # 开发环境可设为 True (同步执行)
    'ack_failures': True,           # 确认失败的任务
    'max_attempts': 3,              # 最大重试次数
    'retry_failed': True,           # 重试失败任务
}

# 开发环境同步执行
if DEBUG:
    Q_CLUSTER['sync'] = True  # 任务同步执行,方便调试
```

### 2.3 任务定义最佳实践

```python
# tasks.py
from django_q.tasks import async_task, result, fetch
from django_q.models import Task, Schedule
from django.utils import timezone
import logging

logger = logging.getLogger(__name__)

def scan_device_snmp(device_id, scan_type='arp'):
    """
    SNMP 扫描任务

    这个函数会在后台工作进程中执行
    必须是可序列化的,不能包含复杂对象

    Args:
        device_id: 设备 ID (整数)
        scan_type: 扫描类型

    Returns:
        dict: 扫描结果
    """
    from .models import NetworkDevice, ScanResult
    from .snmp_scanner import SNMPScanner

    try:
        # 获取设备
        device = NetworkDevice.objects.get(id=device_id)

        # 创建扫描记录
        scan_result = ScanResult.objects.create(
            device=device,
            scan_type=scan_type,
            status='running',
            started_at=timezone.now()
        )

        # 执行扫描
        scanner = SNMPScanner(device)

        if scan_type == 'arp':
            data = scanner.get_arp_table()
        elif scan_type == 'interface':
            data = scanner.get_interfaces()
        else:
            raise ValueError(f"Unknown scan type: {scan_type}")

        # 更新扫描结果
        scan_result.status = 'completed'
        scan_result.data = data
        scan_result.completed_at = timezone.now()
        scan_result.save()

        logger.info(f"SNMP scan completed for device {device_id}")

        return {
            'success': True,
            'scan_id': scan_result.id,
            'entries_found': len(data),
        }

    except NetworkDevice.DoesNotExist:
        logger.error(f"Device {device_id} not found")
        return {
            'success': False,
            'error': 'Device not found',
        }

    except Exception as e:
        logger.exception(f"SNMP scan failed for device {device_id}: {e}")

        # 更新扫描记录为失败
        if 'scan_result' in locals():
            scan_result.status = 'failed'
            scan_result.error_message = str(e)
            scan_result.completed_at = timezone.now()
            scan_result.save()

        return {
            'success': False,
            'error': str(e),
        }


def bulk_scan_devices(device_ids, scan_type='arp'):
    """
    批量扫描设备

    为每个设备创建独立的异步任务
    """
    task_ids = []

    for device_id in device_ids:
        task_id = async_task(
            'ipam.tasks.scan_device_snmp',
            device_id,
            scan_type,
            task_name=f'SNMP Scan - Device {device_id}',
            timeout=300,  # 5 分钟超时
            hook='ipam.tasks.scan_completed_hook',  # 完成时的回调
        )
        task_ids.append(task_id)

    return task_ids


def scan_completed_hook(task):
    """
    扫描完成后的钩子函数

    Args:
        task: Task 对象
    """
    from .models import ScanNotification

    if task.success:
        logger.info(f"Task {task.id} completed successfully")
        result = task.result

        # 发送通知或触发其他操作
        if result.get('entries_found', 0) > 0:
            ScanNotification.objects.create(
                task_id=task.id,
                message=f"Found {result['entries_found']} entries",
                level='success'
            )
    else:
        logger.error(f"Task {task.id} failed: {task.result}")

        # 记录失败
        ScanNotification.objects.create(
            task_id=task.id,
            message=f"Scan failed: {task.result}",
            level='error'
        )


def error_reporter(task):
    """
    全局错误报告函数 (在 Q_CLUSTER 配置中引用)
    """
    from .models import TaskError

    TaskError.objects.create(
        task_id=task.id,
        function=task.func,
        error=str(task.result),
        traceback=task.result if hasattr(task.result, '__traceback__') else '',
        created_at=timezone.now()
    )

    logger.error(f"Task error: {task.func} - {task.result}")
```

### 2.4 在视图中使用异步任务

```python
# views.py
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django_q.tasks import async_task, result as task_result
from django_q.models import Task
import json

@require_http_methods(["POST"])
def start_device_scan(request):
    """
    启动设备扫描

    返回任务 ID,前端可用于轮询进度
    """
    try:
        data = json.loads(request.body)
        device_id = data.get('device_id')
        scan_type = data.get('scan_type', 'arp')

        # 创建异步任务
        task_id = async_task(
            'ipam.tasks.scan_device_snmp',
            device_id,
            scan_type,
            task_name=f'SNMP Scan - Device {device_id}',
            timeout=300,
            hook='ipam.tasks.scan_completed_hook',
        )

        return JsonResponse({
            'success': True,
            'task_id': task_id,
            'message': 'Scan started',
        })

    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e),
        }, status=400)


@require_http_methods(["GET"])
def get_task_status(request, task_id):
    """
    获取任务状态

    Args:
        task_id: 任务 ID

    Returns:
        JSON: 任务状态和结果
    """
    try:
        # 获取任务
        task = Task.objects.get(id=task_id)

        # 任务状态
        response = {
            'task_id': task_id,
            'name': task.name,
            'started': task.started.isoformat() if task.started else None,
            'stopped': task.stopped.isoformat() if task.stopped else None,
        }

        # 检查任务是否完成
        if task.stopped:
            if task.success:
                response['status'] = 'completed'
                response['result'] = task.result
            else:
                response['status'] = 'failed'
                response['error'] = str(task.result)
        else:
            response['status'] = 'running'

        return JsonResponse(response)

    except Task.DoesNotExist:
        return JsonResponse({
            'error': 'Task not found',
        }, status=404)
```

### 2.5 定时任务配置

```python
# 在 Django Admin 或代码中创建定时任务
from django_q.models import Schedule

# 每小时扫描所有活跃设备
Schedule.objects.create(
    name='Hourly ARP Scan',
    func='ipam.tasks.bulk_scan_devices',
    args='[1,2,3,4,5]',  # 设备 ID 列表 (JSON 字符串)
    kwargs='{"scan_type": "arp"}',
    schedule_type=Schedule.HOURLY,
    repeats=-1,  # 无限重复
)

# 每天凌晨 2 点执行完整扫描
Schedule.objects.create(
    name='Daily Full Scan',
    func='ipam.tasks.full_network_scan',
    schedule_type=Schedule.DAILY,
    next_run=timezone.now().replace(hour=2, minute=0, second=0),
    repeats=-1,
)

# Cron 表达式 (每 15 分钟)
Schedule.objects.create(
    name='Periodic Interface Check',
    func='ipam.tasks.check_interfaces',
    cron='*/15 * * * *',  # Cron 格式
    repeats=-1,
)
```

### 2.6 监控和管理

```bash
# 启动工作集群
python manage.py qcluster

# 查看任务队列
python manage.py qmonitor

# 清理旧任务
python manage.py qclean
```

### 2.7 生产环境最佳实践

1. **使用 Redis 后端**: ORM 后端适合开发,生产环境推荐 Redis
2. **合理设置 timeout**: 根据任务类型设置,避免僵尸任务
3. **启用压缩**: 减少 Redis/数据库存储空间
4. **限制 save_limit**: 避免结果表无限增长
5. **使用 Supervisor/Systemd**: 管理 qcluster 进程
6. **监控队列长度**: 避免任务积压
7. **错误报告**: 配置 error_reporter 及时发现问题
8. **任务幂等性**: 确保任务可以安全重试

### Django 6.0 新功能提醒

**Django 6.0** 引入了原生的 Tasks 框架,适合开发和测试,但生产环境仍需 Django-Q2 或 Celery。

### 相关资源

- [Django-Q2 GitHub](https://github.com/django-q2/django-q2)
- [Django-Q2 文档](https://django-q2.readthedocs.io/en/master/tasks.html)
- [2025 Django 任务队列对比](https://medium.com/@g.suryawanshi/lightweight-django-task-queues-in-2025-beyond-celery-74a95e0548ec)
- [Django Task Queues 分析](https://www.loopwerk.io/articles/2025/django-task-queues/)

---

## 3. 实时进度更新方案

### 3.1 技术对比

| 技术 | 延迟 | 带宽开销 | 双向通信 | 实现复杂度 | 适用场景 |
|------|------|----------|----------|-----------|----------|
| **Long Polling** | 高 | 最高 (每次完整 HTTP 请求) | 否 | 低 | 旧系统兼容 |
| **Server-Sent Events (SSE)** | 低 | 中 (约 5 bytes/消息) | 否 (单向) | 中 | 进度更新、通知 |
| **WebSocket** | 最低 | 最低 (2 bytes/帧) | 是 | 高 | 聊天、协作工具 |

### 3.2 推荐方案: Server-Sent Events (SSE)

**理由**: 对于单向进度更新,SSE 是最佳选择。

**优势**:
- 自动重连
- 简单的 HTTP 协议
- 浏览器原生支持
- 比 WebSocket 简单
- 低延迟

**Django 实现**:

```python
# views.py
from django.http import StreamingHttpResponse
from django_q.models import Task
import json
import time

def task_progress_stream(request, task_id):
    """
    SSE 端点,流式传输任务进度

    Usage (前端):
        const eventSource = new EventSource(`/api/tasks/${taskId}/progress/`);
        eventSource.onmessage = (event) => {
            const data = JSON.parse(event.data);
            console.log(data);
        };
    """
    def event_stream():
        """
        生成器函数,持续发送任务状态
        """
        while True:
            try:
                task = Task.objects.get(id=task_id)

                # 构建进度数据
                data = {
                    'task_id': task_id,
                    'status': 'running' if not task.stopped else ('completed' if task.success else 'failed'),
                    'started': task.started.isoformat() if task.started else None,
                }

                # 如果任务完成,添加结果
                if task.stopped:
                    if task.success:
                        data['result'] = task.result
                    else:
                        data['error'] = str(task.result)

                    # 发送最终消息并关闭连接
                    yield f"data: {json.dumps(data)}\n\n"
                    break

                # 检查是否有进度更新 (从缓存中读取)
                from django.core.cache import cache
                progress = cache.get(f'task_progress_{task_id}')
                if progress:
                    data['progress'] = progress

                # 发送 SSE 消息
                yield f"data: {json.dumps(data)}\n\n"

                # 等待 1 秒再检查
                time.sleep(1)

            except Task.DoesNotExist:
                error_data = {'error': 'Task not found'}
                yield f"data: {json.dumps(error_data)}\n\n"
                break

            except Exception as e:
                error_data = {'error': str(e)}
                yield f"data: {json.dumps(error_data)}\n\n"
                break

    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'  # 禁用 nginx 缓冲

    return response


# tasks.py - 在任务中更新进度
from django.core.cache import cache

def long_running_scan(device_id):
    """
    长时间运行的扫描任务,带进度更新
    """
    from .models import NetworkDevice
    from django_q.models import current_task

    # 获取当前任务 ID
    task_id = current_task  # Django-Q2 提供的上下文变量

    device = NetworkDevice.objects.get(id=device_id)
    total_steps = 5

    for step in range(1, total_steps + 1):
        # 执行工作
        time.sleep(2)  # 模拟耗时操作

        # 更新进度到缓存
        progress = {
            'current_step': step,
            'total_steps': total_steps,
            'percentage': int((step / total_steps) * 100),
            'message': f'Processing step {step}/{total_steps}',
        }
        cache.set(f'task_progress_{task_id}', progress, timeout=600)

    # 清理进度缓存
    cache.delete(f'task_progress_{task_id}')

    return {'success': True, 'steps_completed': total_steps}
```

### 3.3 前端实现 (JavaScript)

```html
<!-- progress.html -->
<div id="progress-container">
    <div id="progress-bar" style="width: 0%; background: green; height: 30px;"></div>
    <p id="progress-text">Waiting...</p>
</div>

<script>
function watchTaskProgress(taskId) {
    const eventSource = new EventSource(`/api/tasks/${taskId}/progress/`);

    eventSource.onmessage = function(event) {
        const data = JSON.parse(event.data);

        console.log('Progress update:', data);

        // 更新进度条
        if (data.progress) {
            const percentage = data.progress.percentage;
            document.getElementById('progress-bar').style.width = percentage + '%';
            document.getElementById('progress-text').textContent = data.progress.message;
        }

        // 任务完成
        if (data.status === 'completed') {
            console.log('Task completed:', data.result);
            document.getElementById('progress-text').textContent = 'Completed!';
            eventSource.close();
        }

        // 任务失败
        if (data.status === 'failed') {
            console.error('Task failed:', data.error);
            document.getElementById('progress-text').textContent = 'Failed: ' + data.error;
            eventSource.close();
        }
    };

    eventSource.onerror = function(error) {
        console.error('SSE error:', error);
        eventSource.close();
    };

    // 自动清理
    setTimeout(() => {
        eventSource.close();
    }, 600000);  // 10 分钟后自动关闭
}

// 启动任务并监听进度
fetch('/api/devices/scan/', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({device_id: 1, scan_type: 'arp'})
})
.then(response => response.json())
.then(data => {
    if (data.success) {
        watchTaskProgress(data.task_id);
    }
});
</script>
```

### 3.4 替代方案: 轮询 (Polling)

如果无法使用 SSE (例如老旧浏览器),可以使用简单的轮询:

```javascript
function pollTaskStatus(taskId) {
    const pollInterval = setInterval(async () => {
        try {
            const response = await fetch(`/api/tasks/${taskId}/status/`);
            const data = await response.json();

            console.log('Task status:', data);

            // 更新 UI
            updateProgressUI(data);

            // 任务完成,停止轮询
            if (data.status === 'completed' || data.status === 'failed') {
                clearInterval(pollInterval);
                handleTaskComplete(data);
            }

        } catch (error) {
            console.error('Polling error:', error);
            clearInterval(pollInterval);
        }
    }, 2000);  // 每 2 秒轮询一次

    // 最多轮询 10 分钟
    setTimeout(() => clearInterval(pollInterval), 600000);
}
```

### 3.5 WebSocket 方案 (Django Channels)

仅在需要双向通信时使用:

```python
# routing.py (需要安装 channels)
from django.urls import path
from . import consumers

websocket_urlpatterns = [
    path('ws/tasks/<str:task_id>/', consumers.TaskProgressConsumer.as_asgi()),
]

# consumers.py
import json
from channels.generic.websocket import AsyncWebsocketConsumer
from django_q.models import Task
from asgiref.sync import sync_to_async

class TaskProgressConsumer(AsyncWebsocketConsumer):
    async def connect(self):
        self.task_id = self.scope['url_route']['kwargs']['task_id']
        await self.accept()

        # 启动进度监控
        await self.monitor_task()

    async def disconnect(self, close_code):
        pass

    async def monitor_task(self):
        """
        监控任务进度并推送更新
        """
        import asyncio

        while True:
            try:
                # 获取任务状态
                task = await sync_to_async(Task.objects.get)(id=self.task_id)

                # 发送进度
                await self.send(text_data=json.dumps({
                    'task_id': self.task_id,
                    'status': 'running' if not task.stopped else 'completed',
                    'result': task.result if task.stopped else None,
                }))

                # 任务完成,关闭连接
                if task.stopped:
                    await self.close()
                    break

                # 等待 1 秒
                await asyncio.sleep(1)

            except Task.DoesNotExist:
                await self.send(text_data=json.dumps({'error': 'Task not found'}))
                await self.close()
                break
```

### 3.6 生产环境建议

1. **优先使用 SSE**: 对于单向进度更新,SSE 最简单有效
2. **设置超时**: 避免长时间连接占用资源
3. **缓存进度数据**: 使用 Redis 缓存进度,避免频繁数据库查询
4. **限流**: 限制每个用户的 SSE 连接数
5. **Nginx 配置**: 禁用 SSE 端点的缓冲

```nginx
# nginx.conf
location /api/tasks/ {
    proxy_pass http://django;
    proxy_set_header Connection '';
    proxy_http_version 1.1;
    chunked_transfer_encoding off;
    proxy_buffering off;
    proxy_cache off;
}
```

### 相关资源

- [WebSockets vs SSE vs Long Polling](https://blog.openreplay.com/websockets-sse-long-polling/)
- [Django Channels 指南](https://ably.com/topic/what-is-django-channels)
- [Django 实时应用构建](https://medium.com/@yogeshkrishnanseeniraj/building-real-time-django-applications-a-complete-guide-e291748c5334)
- [2025 实时更新技术对比](https://dev.to/haraf/server-sent-events-sse-vs-websockets-vs-long-polling-whats-best-in-2025-5ep8)

---

## 4. 敏感凭证存储

### 4.1 核心原则

1. **永远不要明文存储密码**
2. **使用字段级加密**
3. **环境变量管理加密密钥**
4. **符合合规要求 (GDPR, HIPAA)**

### 4.2 推荐库: django-cryptography

```bash
pip install django-cryptography
```

**优势**:
- 使用 Python cryptography 库 (Fernet 对称加密)
- 简单易用
- 透明加解密

### 4.3 实现示例

```python
# settings.py
from pathlib import Path
from decouple import config  # pip install python-decouple

# 加密密钥 (必须保存在环境变量中)
# 生成方法: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
CRYPTOGRAPHY_KEY = config('CRYPTOGRAPHY_KEY')

# 确保密钥不在代码仓库中
if not CRYPTOGRAPHY_KEY:
    raise ImproperlyConfigured("CRYPTOGRAPHY_KEY environment variable not set")


# models.py
from django.db import models
from django_cryptography.fields import encrypt

class DeviceCredential(models.Model):
    """
    设备凭证模型 - 加密存储
    """

    name = models.CharField(max_length=100, unique=True)
    username = encrypt(models.CharField(max_length=255))  # 加密用户名
    password = encrypt(models.CharField(max_length=255))  # 加密密码

    # 可选: SNMP community string
    snmp_community = encrypt(models.CharField(max_length=255, blank=True, null=True))

    # 可选: SSH 私钥
    ssh_private_key = encrypt(models.TextField(blank=True, null=True))
    ssh_passphrase = encrypt(models.CharField(max_length=255, blank=True, null=True))

    # 元数据
    created_by = models.ForeignKey(
        'auth.User',
        on_delete=models.PROTECT,
        related_name='created_credentials'
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    # 审计日志
    last_used = models.DateTimeField(null=True, blank=True)
    usage_count = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = 'device_credentials'
        ordering = ['name']

    def __str__(self):
        return f"{self.name} ({self.username})"

    def get_username(self):
        """获取解密的用户名"""
        return self.username

    def get_password(self):
        """获取解密的密码"""
        # 记录使用
        self.last_used = timezone.now()
        self.usage_count += 1
        self.save(update_fields=['last_used', 'usage_count'])

        return self.password

    def get_snmp_community(self):
        """获取解密的 SNMP community"""
        return self.snmp_community if self.snmp_community else 'public'


# 审计日志
class CredentialAccessLog(models.Model):
    """
    凭证访问审计日志
    """

    credential = models.ForeignKey(
        DeviceCredential,
        on_delete=models.CASCADE,
        related_name='access_logs'
    )
    accessed_by = models.ForeignKey(
        'auth.User',
        on_delete=models.SET_NULL,
        null=True
    )
    accessed_at = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField()
    purpose = models.CharField(max_length=255)  # 'ssh_connection', 'snmp_scan', etc.
    success = models.BooleanField(default=True)

    class Meta:
        db_table = 'credential_access_logs'
        indexes = [
            models.Index(fields=['credential', '-accessed_at']),
            models.Index(fields=['accessed_by', '-accessed_at']),
        ]
```

### 4.4 环境变量管理

```python
# .env (永远不要提交到 Git!)
SECRET_KEY=your-django-secret-key
CRYPTOGRAPHY_KEY=your-fernet-key-here
DATABASE_URL=postgresql://user:pass@localhost/dbname
DEBUG=False

# .env.example (提交到 Git 作为模板)
SECRET_KEY=change-me
CRYPTOGRAPHY_KEY=change-me
DATABASE_URL=postgresql://user:pass@localhost/dbname
DEBUG=True
```

```python
# settings.py
from decouple import config, Csv
from dj_database_url import parse as db_url

# 安全配置
SECRET_KEY = config('SECRET_KEY')
DEBUG = config('DEBUG', default=False, cast=bool)
ALLOWED_HOSTS = config('ALLOWED_HOSTS', default='localhost,127.0.0.1', cast=Csv())

# 加密密钥
CRYPTOGRAPHY_KEY = config('CRYPTOGRAPHY_KEY')

# 数据库
DATABASES = {
    'default': config('DATABASE_URL', cast=db_url)
}
```

```bash
# requirements.txt
django-cryptography>=1.1
python-decouple>=3.8
dj-database-url>=2.1.0
```

### 4.5 密钥轮换

```python
# management/commands/rotate_encryption_key.py
from django.core.management.base import BaseCommand
from cryptography.fernet import Fernet
from ipam.models import DeviceCredential

class Command(BaseCommand):
    help = 'Rotate encryption key for credentials'

    def add_arguments(self, parser):
        parser.add_argument('new_key', type=str, help='New Fernet key')

    def handle(self, *args, **options):
        """
        密钥轮换过程:
        1. 使用旧密钥解密所有凭证
        2. 使用新密钥重新加密
        3. 更新环境变量
        """
        new_key = options['new_key']
        old_key = settings.CRYPTOGRAPHY_KEY

        old_fernet = Fernet(old_key.encode())
        new_fernet = Fernet(new_key.encode())

        credentials = DeviceCredential.objects.all()

        for cred in credentials:
            # 使用旧密钥解密
            old_password = old_fernet.decrypt(cred.password.encode()).decode()

            # 使用新密钥加密
            new_password = new_fernet.encrypt(old_password.encode()).decode()

            # 更新
            cred.password = new_password
            cred.save()

        self.stdout.write(self.style.SUCCESS(
            f'Successfully rotated keys for {credentials.count()} credentials'
        ))
        self.stdout.write(self.style.WARNING(
            'Remember to update CRYPTOGRAPHY_KEY environment variable!'
        ))
```

### 4.6 替代方案: django-encrypted-model-fields

```python
# models.py
from encrypted_model_fields.fields import EncryptedCharField

class DeviceCredential(models.Model):
    username = EncryptedCharField(max_length=255)
    password = EncryptedCharField(max_length=255)
```

### 4.7 生产环境最佳实践

1. **密钥管理**:
   - 使用 AWS Secrets Manager / Azure Key Vault / GCP Secret Manager
   - 永远不要将密钥提交到代码仓库
   - 定期轮换加密密钥

2. **访问控制**:
   - 记录所有凭证访问
   - 实施基于角色的访问控制 (RBAC)
   - 审计日志保留至少 90 天

3. **传输安全**:
   - 强制使用 HTTPS (`SESSION_COOKIE_SECURE = True`)
   - 启用 HSTS: `SECURE_HSTS_SECONDS = 31536000`
   - 使用 `CSRF_COOKIE_SECURE = True`

4. **合规性**:
   - GDPR: 提供数据导出和删除功能
   - HIPAA: 启用完整审计日志
   - PCI DSS: 定期密钥轮换

5. **数据掩码**:
   - API 响应中隐藏敏感字段
   - 日志中不记录明文密码
   - Admin 界面使用 PasswordInput

```python
# admin.py
from django.contrib import admin
from django import forms

class DeviceCredentialAdminForm(forms.ModelForm):
    class Meta:
        model = DeviceCredential
        fields = '__all__'
        widgets = {
            'password': forms.PasswordInput(render_value=True),
            'snmp_community': forms.PasswordInput(render_value=True),
        }

@admin.register(DeviceCredential)
class DeviceCredentialAdmin(admin.ModelAdmin):
    form = DeviceCredentialAdminForm
    list_display = ['name', 'username', 'created_by', 'created_at', 'last_used']
    readonly_fields = ['created_at', 'updated_at', 'last_used', 'usage_count']
```

### 相关资源

- [django-cryptography GitHub](https://github.com/georgemarshall/django-cryptography)
- [Django 加密实现指南](https://loadforge.com/guides/implementing-data-encryption-and-secure-storage-in-django)
- [Django 安全最佳实践 2025](https://shiladityamajumder.medium.com/how-to-secure-your-django-application-best-practices-for-2025-e9234cf71ab7)
- [字段级加密 Python 实现](https://www.piiano.com/blog/field-level-encryption-in-python-for-django-applications)

---

## 5. SNMP ARP表扫描

### 5.1 核心 OID

```python
# SNMP OID 常量
SNMP_OIDS = {
    # ARP 表相关
    'IP_NET_TO_MEDIA_PHYS_ADDRESS': '1.3.6.1.2.1.4.22.1.2',  # IP-MAC 映射
    'IP_NET_TO_MEDIA_IF_INDEX': '1.3.6.1.2.1.4.22.1.1',     # 接口索引
    'IP_NET_TO_MEDIA_NET_ADDRESS': '1.3.6.1.2.1.4.22.1.3',  # 网络地址
    'IP_NET_TO_MEDIA_TYPE': '1.3.6.1.2.1.4.22.1.4',         # 条目类型

    # 接口信息
    'IF_DESCR': '1.3.6.1.2.1.2.2.1.2',      # 接口描述
    'IF_TYPE': '1.3.6.1.2.1.2.2.1.3',       # 接口类型
    'IF_PHYS_ADDRESS': '1.3.6.1.2.1.2.2.1.6',  # 接口物理地址

    # LLDP (链路层发现协议)
    'LLDP_REMOTE_SYS_NAME': '1.0.8802.1.1.2.1.4.1.1.9',
    'LLDP_REMOTE_PORT_ID': '1.0.8802.1.1.2.1.4.1.1.7',

    # CDP (Cisco Discovery Protocol)
    'CDP_CACHE_ADDRESS': '1.3.6.1.4.1.9.9.23.1.2.1.1.4',
    'CDP_CACHE_DEVICE_ID': '1.3.6.1.4.1.9.9.23.1.2.1.1.6',
}
```

### 5.2 SNMP 扫描器实现

```python
# snmp_scanner.py
from pysnmp.hlapi import (
    getCmd, nextCmd, bulkCmd,
    SnmpEngine, CommunityData, UdpTransportTarget,
    ContextData, ObjectType, ObjectIdentity
)
from pysnmp.proto.rfc1902 import OctetString
import logging
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

class SNMPScanner:
    """
    SNMP 扫描器 - 用于获取网络设备信息
    """

    def __init__(self, device, timeout=5, retries=3):
        """
        初始化 SNMP 扫描器

        Args:
            device: NetworkDevice 实例
            timeout: 超时时间 (秒)
            retries: 重试次数
        """
        self.device = device
        self.host = device.ip_address
        self.community = device.credential.get_snmp_community()
        self.timeout = timeout
        self.retries = retries

    def _format_mac_address(self, mac_bytes):
        """
        格式化 MAC 地址

        Args:
            mac_bytes: MAC 地址字节串

        Returns:
            str: 格式化的 MAC 地址 (AA:BB:CC:DD:EE:FF)
        """
        if not mac_bytes or len(mac_bytes) == 0:
            return None

        try:
            if isinstance(mac_bytes, str):
                mac_bytes = mac_bytes.encode('latin-1')

            # 转换为十六进制
            mac_hex = mac_bytes.hex()

            # 检查是否为全 0
            if mac_hex == '000000000000':
                return None

            # 格式化为 AA:BB:CC:DD:EE:FF
            mac = ':'.join(mac_hex[i:i+2] for i in range(0, 12, 2))
            return mac.upper()

        except Exception as e:
            logger.warning(f"Failed to format MAC address: {e}")
            return None

    def get_arp_table(self) -> List[Dict]:
        """
        获取 ARP 表

        Returns:
            list: ARP 条目列表
            [{
                'ip_address': '192.168.1.100',
                'mac_address': 'AA:BB:CC:DD:EE:FF',
                'interface_index': 1,
                'interface_name': 'GigabitEthernet0/1',
                'type': 'dynamic',
            }, ...]
        """
        arp_entries = []

        try:
            # 使用 bulkCmd 批量获取 ARP 表
            iterator = bulkCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget(
                    (self.host, 161),
                    timeout=self.timeout,
                    retries=self.retries
                ),
                ContextData(),
                0, 25,  # non-repeaters, max-repetitions
                ObjectType(ObjectIdentity(SNMP_OIDS['IP_NET_TO_MEDIA_PHYS_ADDRESS'])),
                ObjectType(ObjectIdentity(SNMP_OIDS['IP_NET_TO_MEDIA_IF_INDEX'])),
                lexicographicMode=False
            )

            for error_indication, error_status, error_index, var_binds in iterator:
                if error_indication:
                    logger.error(f"SNMP error indication: {error_indication}")
                    break

                if error_status:
                    logger.error(f"SNMP error status: {error_status.prettyPrint()}")
                    break

                # 解析 OID 获取 IP 地址
                for var_bind in var_binds:
                    oid_str = var_bind[0].prettyPrint()

                    # 提取 IP 地址 (OID 最后 4 个数字)
                    oid_parts = oid_str.split('.')
                    if len(oid_parts) >= 4:
                        # OID 格式: 1.3.6.1.2.1.4.22.1.2.<ifIndex>.<ip1>.<ip2>.<ip3>.<ip4>
                        ip_address = '.'.join(oid_parts[-4:])

                        # 获取 MAC 地址
                        mac_address = self._format_mac_address(var_bind[1])

                        # 跳过无效的 MAC 地址
                        if not mac_address:
                            continue

                        # 获取接口索引 (从 OID 中提取)
                        if len(oid_parts) >= 5:
                            interface_index = int(oid_parts[-5])
                        else:
                            interface_index = 0

                        arp_entries.append({
                            'ip_address': ip_address,
                            'mac_address': mac_address,
                            'interface_index': interface_index,
                            'interface_name': self._get_interface_name(interface_index),
                            'type': 'dynamic',
                        })

            logger.info(f"Retrieved {len(arp_entries)} ARP entries from {self.host}")

        except Exception as e:
            logger.exception(f"Failed to retrieve ARP table from {self.host}: {e}")
            raise SNMPScanError(f"ARP table retrieval failed: {str(e)}")

        return arp_entries

    def _get_interface_name(self, if_index: int) -> Optional[str]:
        """
        根据接口索引获取接口名称

        Args:
            if_index: 接口索引

        Returns:
            str: 接口名称
        """
        if if_index == 0:
            return None

        try:
            # 查询接口描述
            oid = f"{SNMP_OIDS['IF_DESCR']}.{if_index}"

            iterator = getCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, 161), timeout=self.timeout, retries=1),
                ContextData(),
                ObjectType(ObjectIdentity(oid))
            )

            error_indication, error_status, error_index, var_binds = next(iterator)

            if error_indication or error_status:
                return f"ifIndex{if_index}"

            for var_bind in var_binds:
                return str(var_bind[1])

        except Exception as e:
            logger.debug(f"Failed to get interface name for index {if_index}: {e}")
            return f"ifIndex{if_index}"

    def get_interfaces(self) -> List[Dict]:
        """
        获取设备所有接口信息

        Returns:
            list: 接口列表
        """
        interfaces = []

        try:
            iterator = bulkCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, 161), timeout=self.timeout, retries=self.retries),
                ContextData(),
                0, 25,
                ObjectType(ObjectIdentity(SNMP_OIDS['IF_DESCR'])),
                ObjectType(ObjectIdentity(SNMP_OIDS['IF_TYPE'])),
                lexicographicMode=False
            )

            for error_indication, error_status, error_index, var_binds in iterator:
                if error_indication or error_status:
                    break

                # 提取接口索引
                oid_parts = var_binds[0][0].prettyPrint().split('.')
                if_index = int(oid_parts[-1])

                interfaces.append({
                    'index': if_index,
                    'name': str(var_binds[0][1]),
                    'type': int(var_binds[1][1]),
                })

            logger.info(f"Retrieved {len(interfaces)} interfaces from {self.host}")

        except Exception as e:
            logger.exception(f"Failed to retrieve interfaces from {self.host}: {e}")
            raise SNMPScanError(f"Interface retrieval failed: {str(e)}")

        return interfaces

    def test_connectivity(self) -> bool:
        """
        测试 SNMP 连接

        Returns:
            bool: 连接是否成功
        """
        try:
            # 获取系统描述 (sysDescr)
            iterator = getCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, 161), timeout=self.timeout, retries=self.retries),
                ContextData(),
                ObjectType(ObjectIdentity('SNMPv2-MIB', 'sysDescr', 0))
            )

            error_indication, error_status, error_index, var_binds = next(iterator)

            if error_indication or error_status:
                logger.error(f"SNMP connectivity test failed: {error_indication or error_status}")
                return False

            logger.info(f"SNMP connectivity test successful for {self.host}")
            return True

        except Exception as e:
            logger.error(f"SNMP connectivity test failed for {self.host}: {e}")
            return False


# 自定义异常
class SNMPScanError(Exception):
    """SNMP 扫描错误"""
    pass
```

### 5.3 最佳实践

1. **使用 bulkCmd**: 比 nextCmd 快得多,适合大量数据
2. **超时和重试**: 合理配置避免长时间等待
3. **错误处理**: 优雅处理 SNMP 错误
4. **MAC 地址验证**: 过滤全 0 和无效 MAC
5. **异步执行**: SNMP 扫描应在后台任务中执行

### 5.4 集成到 Django-Q2

```python
# tasks.py
from .snmp_scanner import SNMPScanner, SNMPScanError

def snmp_scan_device(device_id):
    """
    SNMP 扫描设备任务
    """
    try:
        device = NetworkDevice.objects.get(id=device_id)

        # 创建扫描器
        scanner = SNMPScanner(device, timeout=10, retries=3)

        # 测试连接
        if not scanner.test_connectivity():
            raise SNMPScanError("SNMP connectivity test failed")

        # 获取 ARP 表
        arp_entries = scanner.get_arp_table()

        # 保存到数据库
        from .models import ARPEntry

        for entry in arp_entries:
            ARPEntry.objects.update_or_create(
                ip_address=entry['ip_address'],
                defaults={
                    'mac_address': entry['mac_address'],
                    'device': device,
                    'interface_name': entry['interface_name'],
                    'last_seen': timezone.now(),
                }
            )

        logger.info(f"SNMP scan completed: {len(arp_entries)} entries")

        return {
            'success': True,
            'entries': len(arp_entries),
        }

    except Exception as e:
        logger.exception(f"SNMP scan failed: {e}")
        return {
            'success': False,
            'error': str(e),
        }
```

### 相关资源

- [SNMP 网络发现最佳实践](https://www.whatsupgold.com/blog/best-practices-series-network-discovery)
- [Palo Alto SNMP 发现](https://docs.paloaltonetworks.com/content/techdocs/en_US/iot/iot-security-admin/get-started-with-iot-security/firewall-deployment-for-dhcp-visibility/use-snmp-network-discovery-to-learn-about-devices-from-switches)
- [Device42 SNMP 自动发现](https://docs.device42.com/auto-discovery/network-auto-discovery/)

---

## 6. 处理不完整的ARP条目

### 6.1 理解不完整 ARP 条目

**原因**:
1. ARP 请求未收到响应
2. 设备不在线或网络不可达
3. VLAN 配置错误
4. 物理链路故障
5. 重复 IP 地址

### 6.2 检测和过滤策略

```python
# snmp_scanner.py (增强版)

class SNMPScanner:
    """
    增强的 SNMP 扫描器 - 处理不完整条目
    """

    def _is_valid_mac_address(self, mac_address: str) -> bool:
        """
        验证 MAC 地址有效性

        Args:
            mac_address: MAC 地址字符串

        Returns:
            bool: 是否有效
        """
        if not mac_address:
            return False

        # 移除分隔符
        mac_clean = mac_address.replace(':', '').replace('-', '')

        # 检查长度
        if len(mac_clean) != 12:
            return False

        # 检查是否全为 0
        if mac_clean == '000000000000':
            logger.debug(f"Skipping all-zero MAC address: {mac_address}")
            return False

        # 检查是否全为 F (broadcast)
        if mac_clean.upper() == 'FFFFFFFFFFFF':
            logger.debug(f"Skipping broadcast MAC address: {mac_address}")
            return False

        # 检查是否为多播地址 (第一个字节的最低位为 1)
        first_byte = int(mac_clean[0:2], 16)
        if first_byte & 0x01:
            logger.debug(f"Skipping multicast MAC address: {mac_address}")
            return False

        return True

    def _is_valid_ip_address(self, ip_address: str) -> bool:
        """
        验证 IP 地址有效性

        Args:
            ip_address: IP 地址字符串

        Returns:
            bool: 是否有效
        """
        import ipaddress

        try:
            ip = ipaddress.ip_address(ip_address)

            # 排除特殊地址
            if ip.is_loopback:
                logger.debug(f"Skipping loopback address: {ip_address}")
                return False

            if ip.is_multicast:
                logger.debug(f"Skipping multicast address: {ip_address}")
                return False

            if ip.is_reserved:
                logger.debug(f"Skipping reserved address: {ip_address}")
                return False

            if ip.is_unspecified:  # 0.0.0.0
                logger.debug(f"Skipping unspecified address: {ip_address}")
                return False

            return True

        except ValueError:
            logger.warning(f"Invalid IP address format: {ip_address}")
            return False

    def get_arp_table(self, include_incomplete=False) -> List[Dict]:
        """
        获取 ARP 表 (增强版)

        Args:
            include_incomplete: 是否包含不完整条目

        Returns:
            list: 有效的 ARP 条目列表
        """
        arp_entries = []
        incomplete_entries = []

        try:
            iterator = bulkCmd(
                SnmpEngine(),
                CommunityData(self.community),
                UdpTransportTarget((self.host, 161), timeout=self.timeout, retries=self.retries),
                ContextData(),
                0, 25,
                ObjectType(ObjectIdentity(SNMP_OIDS['IP_NET_TO_MEDIA_PHYS_ADDRESS'])),
                ObjectType(ObjectIdentity(SNMP_OIDS['IP_NET_TO_MEDIA_IF_INDEX'])),
                lexicographicMode=False
            )

            for error_indication, error_status, error_index, var_binds in iterator:
                if error_indication or error_status:
                    break

                for var_bind in var_binds:
                    oid_str = var_bind[0].prettyPrint()
                    oid_parts = oid_str.split('.')

                    if len(oid_parts) < 4:
                        continue

                    # 提取 IP 地址
                    ip_address = '.'.join(oid_parts[-4:])

                    # 验证 IP 地址
                    if not self._is_valid_ip_address(ip_address):
                        continue

                    # 获取 MAC 地址
                    mac_address = self._format_mac_address(var_bind[1])

                    # 验证 MAC 地址
                    if not mac_address or not self._is_valid_mac_address(mac_address):
                        # 记录不完整条目
                        incomplete_entries.append({
                            'ip_address': ip_address,
                            'mac_address': mac_address or '00:00:00:00:00:00',
                            'reason': 'invalid_mac',
                        })
                        continue

                    # 获取接口索引
                    interface_index = int(oid_parts[-5]) if len(oid_parts) >= 5 else 0

                    # 添加有效条目
                    arp_entries.append({
                        'ip_address': ip_address,
                        'mac_address': mac_address,
                        'interface_index': interface_index,
                        'interface_name': self._get_interface_name(interface_index),
                        'type': 'dynamic',
                        'is_complete': True,
                    })

            # 日志统计
            logger.info(
                f"ARP scan results for {self.host}: "
                f"{len(arp_entries)} valid, {len(incomplete_entries)} incomplete"
            )

            # 根据参数决定是否返回不完整条目
            if include_incomplete:
                for entry in incomplete_entries:
                    entry['is_complete'] = False
                    arp_entries.append(entry)

        except Exception as e:
            logger.exception(f"Failed to retrieve ARP table from {self.host}: {e}")
            raise SNMPScanError(f"ARP table retrieval failed: {str(e)}")

        return arp_entries

    def diagnose_incomplete_entries(self) -> Dict:
        """
        诊断不完整 ARP 条目

        Returns:
            dict: 诊断结果
        """
        diagnostics = {
            'total_entries': 0,
            'valid_entries': 0,
            'incomplete_entries': 0,
            'issues': [],
        }

        try:
            # 获取所有条目 (包括不完整的)
            all_entries = self.get_arp_table(include_incomplete=True)

            diagnostics['total_entries'] = len(all_entries)

            for entry in all_entries:
                if entry.get('is_complete'):
                    diagnostics['valid_entries'] += 1
                else:
                    diagnostics['incomplete_entries'] += 1
                    diagnostics['issues'].append({
                        'ip_address': entry['ip_address'],
                        'mac_address': entry.get('mac_address'),
                        'reason': entry.get('reason', 'unknown'),
                    })

            # 建议
            if diagnostics['incomplete_entries'] > 0:
                diagnostics['recommendations'] = [
                    "Check network connectivity to devices with incomplete ARP",
                    "Verify VLAN configuration",
                    "Look for duplicate IP addresses",
                    "Check for physical layer issues",
                ]

        except Exception as e:
            logger.exception(f"ARP diagnostics failed: {e}")
            diagnostics['error'] = str(e)

        return diagnostics
```

### 6.3 数据库模型

```python
# models.py
class ARPEntry(models.Model):
    """
    ARP 条目模型
    """

    ip_address = models.GenericIPAddressField(db_index=True)
    mac_address = models.CharField(max_length=17, db_index=True)  # AA:BB:CC:DD:EE:FF

    device = models.ForeignKey(
        'NetworkDevice',
        on_delete=models.CASCADE,
        related_name='arp_entries'
    )

    interface_name = models.CharField(max_length=100, blank=True, null=True)
    interface_index = models.PositiveIntegerField(default=0)

    # 状态标记
    is_complete = models.BooleanField(default=True)
    is_static = models.BooleanField(default=False)

    # 时间戳
    first_seen = models.DateTimeField(auto_now_add=True)
    last_seen = models.DateTimeField(auto_now=True)

    # 诊断信息
    incomplete_reason = models.CharField(max_length=255, blank=True, null=True)

    class Meta:
        db_table = 'arp_entries'
        unique_together = ['device', 'ip_address']
        indexes = [
            models.Index(fields=['ip_address', 'mac_address']),
            models.Index(fields=['device', 'is_complete']),
            models.Index(fields=['-last_seen']),
        ]

    def __str__(self):
        return f"{self.ip_address} -> {self.mac_address}"

    @property
    def age(self):
        """条目年龄 (秒)"""
        return (timezone.now() - self.last_seen).total_seconds()

    def is_stale(self, max_age=3600):
        """
        检查条目是否过期

        Args:
            max_age: 最大年龄 (秒), 默认 1 小时

        Returns:
            bool: 是否过期
        """
        return self.age > max_age
```

### 6.4 清理策略

```python
# tasks.py
def cleanup_stale_arp_entries(max_age_hours=24):
    """
    清理过期的 ARP 条目

    Args:
        max_age_hours: 最大保留时间 (小时)
    """
    from datetime import timedelta
    from .models import ARPEntry

    threshold = timezone.now() - timedelta(hours=max_age_hours)

    # 删除过期条目
    deleted_count, _ = ARPEntry.objects.filter(
        last_seen__lt=threshold
    ).delete()

    logger.info(f"Cleaned up {deleted_count} stale ARP entries")

    return {
        'success': True,
        'deleted_count': deleted_count,
    }


def refresh_arp_entries(device_id):
    """
    刷新设备的 ARP 条目

    先清除旧条目,再重新扫描
    """
    from .models import NetworkDevice, ARPEntry

    device = NetworkDevice.objects.get(id=device_id)

    # 删除旧条目
    ARPEntry.objects.filter(device=device).delete()

    # 重新扫描
    scanner = SNMPScanner(device)
    entries = scanner.get_arp_table(include_incomplete=False)

    # 批量创建
    arp_objects = [
        ARPEntry(
            device=device,
            ip_address=entry['ip_address'],
            mac_address=entry['mac_address'],
            interface_name=entry.get('interface_name'),
            interface_index=entry.get('interface_index', 0),
            is_complete=entry.get('is_complete', True),
        )
        for entry in entries
    ]

    ARPEntry.objects.bulk_create(arp_objects, batch_size=500)

    logger.info(f"Refreshed {len(arp_objects)} ARP entries for device {device_id}")

    return {
        'success': True,
        'entries': len(arp_objects),
    }
```

### 6.5 最佳实践

1. **过滤无效条目**: 在保存前验证 IP 和 MAC
2. **记录不完整原因**: 便于诊断
3. **定期清理**: 删除过期条目
4. **监控比率**: 如果不完整条目过多,需要调查
5. **重试机制**: 对不完整条目定期重试

### 相关资源

- [Cisco ARP Incomplete 问题](https://community.cisco.com/t5/switching/incomplete-arp/td-p/826782)
- [ARP 故障排查](https://access.redhat.com/solutions/2453931)
- [Palo Alto ARP 问题](https://knowledgebase.paloaltonetworks.com/kCSArticleDetail?id=kA10g000000Cla2)

---

## 7. IP地址模糊搜索

### 7.1 推荐库: django-postgresql-netfields

```bash
pip install django-postgresql-netfields
```

**优势**:
- 原生支持 PostgreSQL INET/CIDR 类型
- 高效的 IP 地址查询
- 支持子网匹配
- 提供自定义管理器

### 7.2 模型定义

```python
# models.py
from netfields import InetAddressField, CidrAddressField, MACAddressField
from netfields.managers import NetManager

class IPAddress(models.Model):
    """
    IP 地址模型 (使用 netfields)
    """

    # 使用 InetAddressField 替代 GenericIPAddressField
    ip_address = InetAddressField(
        unique=True,
        store_prefix_length=True,  # 存储前缀长度
        db_index=True
    )

    # MAC 地址
    mac_address = MACAddressField(null=True, blank=True)

    # 所属子网
    subnet = models.ForeignKey(
        'Subnet',
        on_delete=models.SET_NULL,
        null=True,
        related_name='ip_addresses'
    )

    # 其他字段...
    hostname = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=20, default='available')

    # 使用 NetManager (提供高级 IP 查询)
    objects = NetManager()

    class Meta:
        db_table = 'ip_addresses'
        indexes = [
            models.Index(fields=['ip_address']),
        ]

    def __str__(self):
        return str(self.ip_address)


class Subnet(models.Model):
    """
    子网模型
    """

    # 使用 CidrAddressField
    network = CidrAddressField(unique=True, db_index=True)

    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)

    # VLAN 信息
    vlan_id = models.PositiveIntegerField(null=True, blank=True)

    objects = NetManager()

    class Meta:
        db_table = 'subnets'

    def __str__(self):
        return f"{self.name} ({self.network})"

    @property
    def total_ips(self):
        """子网中的 IP 总数"""
        import ipaddress
        network = ipaddress.ip_network(str(self.network))
        return network.num_addresses

    @property
    def usable_ips(self):
        """可用 IP 数量 (排除网络地址和广播地址)"""
        return max(0, self.total_ips - 2)
```

### 7.3 高级 IP 查询

```python
# 查询示例

# 1. 精确匹配
ip = IPAddress.objects.get(ip_address='192.168.1.100')

# 2. 子网包含查询
ips_in_subnet = IPAddress.objects.filter(
    ip_address__net_contained='192.168.1.0/24'
)

# 3. 子网包含或等于
ips = IPAddress.objects.filter(
    ip_address__net_contained_or_equal='192.168.1.0/24'
)

# 4. IP 地址包含子网
subnets = Subnet.objects.filter(
    network__net_contains='192.168.1.100'
)

# 5. IP 范围查询
from ipaddress import ip_address

start_ip = ip_address('192.168.1.10')
end_ip = ip_address('192.168.1.50')

ips_in_range = IPAddress.objects.filter(
    ip_address__gte=str(start_ip),
    ip_address__lte=str(end_ip)
)

# 6. 查找子网中的所有 IP
subnet = Subnet.objects.get(network='192.168.1.0/24')
ips = IPAddress.objects.filter(
    ip_address__net_contained=subnet.network
)

# 7. 查找 IP 所属的子网
ip = '192.168.1.100'
subnet = Subnet.objects.filter(
    network__net_contains=ip
).first()
```

### 7.4 模糊搜索实现

```python
# views.py
from django.db.models import Q
from rest_framework.decorators import api_view
from rest_framework.response import Response

@api_view(['GET'])
def search_ip_addresses(request):
    """
    IP 地址模糊搜索 API

    支持:
    - 完整 IP: 192.168.1.100
    - 部分 IP: 192.168.1
    - CIDR: 192.168.1.0/24
    - 主机名: web-server
    - MAC 地址: AA:BB:CC

    参数:
        q: 搜索关键词
        limit: 结果数量限制 (默认 50)
    """
    query = request.GET.get('q', '').strip()
    limit = int(request.GET.get('limit', 50))

    if not query:
        return Response({
            'results': [],
            'count': 0,
        })

    # 构建查询
    filters = Q()

    # 1. 尝试精确 IP 匹配
    try:
        import ipaddress
        ip = ipaddress.ip_address(query)
        filters |= Q(ip_address=str(ip))
    except ValueError:
        pass

    # 2. 尝试 CIDR 匹配
    try:
        import ipaddress
        network = ipaddress.ip_network(query, strict=False)
        filters |= Q(ip_address__net_contained=str(network))
    except ValueError:
        pass

    # 3. 部分 IP 匹配 (使用 LIKE)
    if query.replace('.', '').isdigit():
        # 仅数字和点,可能是部分 IP
        filters |= Q(ip_address__startswith=query)

    # 4. 主机名模糊匹配
    if query.replace('-', '').replace('_', '').isalnum():
        filters |= Q(hostname__icontains=query)

    # 5. MAC 地址模糊匹配
    if ':' in query or '-' in query:
        mac_clean = query.replace(':', '').replace('-', '').upper()
        filters |= Q(mac_address__icontains=mac_clean)

    # 执行查询
    results = IPAddress.objects.filter(filters).distinct()[:limit]

    # 序列化结果
    data = [
        {
            'ip_address': str(ip.ip_address),
            'mac_address': str(ip.mac_address) if ip.mac_address else None,
            'hostname': ip.hostname,
            'status': ip.status,
            'subnet': str(ip.subnet.network) if ip.subnet else None,
        }
        for ip in results
    ]

    return Response({
        'results': data,
        'count': len(data),
        'query': query,
    })
```

### 7.5 PostgreSQL 三元组模糊搜索

对于更高级的模糊搜索 (例如拼写错误容错):

```python
# 1. 启用 pg_trgm 扩展
# 在 PostgreSQL 中执行: CREATE EXTENSION IF NOT EXISTS pg_trgm;

# 2. 创建 GIN 索引
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import TrigramSimilarity

class IPAddress(models.Model):
    # ... 字段定义 ...

    class Meta:
        indexes = [
            GinIndex(fields=['hostname'], name='hostname_trgm_idx', opclasses=['gin_trgm_ops']),
        ]

# 3. 使用三元组相似度搜索
from django.contrib.postgres.search import TrigramSimilarity

def fuzzy_search_hostname(query):
    """
    基于三元组相似度的主机名模糊搜索
    """
    results = IPAddress.objects.annotate(
        similarity=TrigramSimilarity('hostname', query)
    ).filter(
        similarity__gt=0.3  # 相似度阈值
    ).order_by('-similarity')

    return results
```

### 7.6 性能优化

```python
# 1. 添加数据库索引
class IPAddress(models.Model):
    # ...

    class Meta:
        indexes = [
            models.Index(fields=['ip_address']),
            models.Index(fields=['mac_address']),
            models.Index(fields=['hostname']),
            models.Index(fields=['status']),
        ]

# 2. 使用 select_related 和 prefetch_related
results = IPAddress.objects.filter(
    ip_address__net_contained='192.168.1.0/24'
).select_related('subnet').prefetch_related('arp_entries')

# 3. 批量查询
from django.db.models import Count

subnets_with_counts = Subnet.objects.annotate(
    ip_count=Count('ip_addresses'),
    available_count=Count('ip_addresses', filter=Q(ip_addresses__status='available'))
)
```

### 7.7 REST API 示例

```python
# serializers.py
from rest_framework import serializers
from netfields.rest_framework import InetAddressField, MACAddressField

class IPAddressSerializer(serializers.ModelSerializer):
    ip_address = InetAddressField()
    mac_address = MACAddressField(allow_null=True)

    class Meta:
        model = IPAddress
        fields = ['id', 'ip_address', 'mac_address', 'hostname', 'status', 'subnet']

# views.py
from rest_framework import viewsets, filters
from django_filters.rest_framework import DjangoFilterBackend

class IPAddressViewSet(viewsets.ModelViewSet):
    queryset = IPAddress.objects.all()
    serializer_class = IPAddressSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]

    # 精确过滤
    filterset_fields = ['status', 'subnet']

    # 模糊搜索
    search_fields = ['hostname', 'ip_address', 'mac_address']

    # 排序
    ordering_fields = ['ip_address', 'hostname', 'status']
    ordering = ['ip_address']

    def get_queryset(self):
        queryset = super().get_queryset()

        # 子网过滤
        subnet = self.request.query_params.get('subnet', None)
        if subnet:
            queryset = queryset.filter(ip_address__net_contained=subnet)

        # IP 范围过滤
        start_ip = self.request.query_params.get('start_ip', None)
        end_ip = self.request.query_params.get('end_ip', None)
        if start_ip and end_ip:
            queryset = queryset.filter(
                ip_address__gte=start_ip,
                ip_address__lte=end_ip
            )

        return queryset
```

### 7.8 前端集成示例

```javascript
// IP 地址搜索 (带防抖)
let searchTimeout;

function searchIPAddress(query) {
    clearTimeout(searchTimeout);

    searchTimeout = setTimeout(() => {
        fetch(`/api/ip-search/?q=${encodeURIComponent(query)}&limit=20`)
            .then(response => response.json())
            .then(data => {
                displayResults(data.results);
            });
    }, 300);  // 300ms 防抖
}

// HTML
<input type="text" id="ip-search" placeholder="搜索 IP, 主机名或 MAC...">
<div id="search-results"></div>

<script>
document.getElementById('ip-search').addEventListener('input', (e) => {
    searchIPAddress(e.target.value);
});
</script>
```

### 相关资源

- [django-postgresql-netfields GitHub](https://github.com/jimfunk/django-postgresql-netfields)
- [PostgreSQL INET 类型文档](https://www.postgresql.org/docs/current/datatype-net-types.html)
- [PostgreSQL 三元组模糊搜索](https://dzone.com/articles/postgres-fuzzy-search-using)
- [Django REST 模糊搜索](https://github.com/vsemionov/django-rest-fuzzysearch)

---

## 总结和推荐架构

### 技术栈推荐

```
后端框架: Django 5.x / 6.x
SSH 库: Netmiko (基于 Paramiko)
SNMP 库: pysnmp
任务队列: Django-Q2 (中小型) 或 Celery (大型)
实时更新: Server-Sent Events (SSE)
数据库: PostgreSQL (必须)
IP 字段: django-postgresql-netfields
加密: django-cryptography
环境变量: python-decouple
```

### 生产环境清单

- [ ] 使用 Redis 作为 Django-Q2 后端
- [ ] 启用 HTTPS 和所有安全 Cookie 设置
- [ ] 加密密钥存储在环境变量中
- [ ] 配置数据库连接池 (PgBouncer 或原生)
- [ ] 设置 Nginx 禁用 SSE 端点缓冲
- [ ] 实施审计日志 (凭证访问、设备连接)
- [ ] 配置 Supervisor/Systemd 管理 qcluster
- [ ] 设置定时任务清理过期数据
- [ ] 启用 PostgreSQL pg_trgm 扩展
- [ ] 创建必要的数据库索引
- [ ] 配置错误监控 (Sentry)
- [ ] 实施限流和 CSRF 保护

### 代码组织建议

```
backend/
├── ipam/
│   ├── models.py              # 数据模型
│   ├── serializers.py         # DRF 序列化器
│   ├── views.py               # API 视图
│   ├── tasks.py               # Django-Q2 任务
│   ├── ssh_manager.py         # SSH 连接管理
│   ├── snmp_scanner.py        # SNMP 扫描器
│   ├── services.py            # 业务逻辑层
│   ├── exceptions.py          # 自定义异常
│   └── management/
│       └── commands/
│           ├── rotate_keys.py
│           └── cleanup_arp.py
├── ipam_project/
│   ├── settings.py            # Django 设置
│   ├── urls.py
│   └── exception_handlers.py
└── requirements.txt
```

---

**研究完成时间**: 2026-01-05
**最后更新**: 2026-01-05

本研究报告基于 2025-2026 年的最新最佳实践和官方文档。

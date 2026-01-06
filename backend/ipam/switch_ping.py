"""
交换机SSH Ping服务

通过SSH连接到核心交换机执行Ping测试，支持多厂商设备
"""

import re
import logging
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from netmiko import ConnectHandler
from netmiko.exceptions import NetmikoTimeoutException, NetmikoAuthenticationException

logger = logging.getLogger(__name__)


@dataclass
class SwitchConfig:
    """交换机配置"""
    name: str
    host: str
    username: str
    password: str
    enable_password: Optional[str] = None
    device_type: str = "huawei"  # 默认华为设备
    timeout: int = 30


# 核心交换机配置 (Cisco Catalyst 9500)
CORE_SWITCHES: List[SwitchConfig] = [
    SwitchConfig(
        name="J14-MES-CORE",
        host="10.69.253.1",
        username="admin",
        password="zhldserver@2018",
        enable_password="zhldserver@2018",
        device_type="cisco_ios",  # Cisco Catalyst C9407R (VSS)
    ),
    SwitchConfig(
        name="R1-MES-CORE",
        host="10.75.255.230",
        username="admin",
        password="Zhldserver@2022",
        enable_password="Zhldserver@2022",
        device_type="cisco_ios",  # Cisco Catalyst 9500
    ),
]


class SwitchPingService:
    """交换机Ping服务"""

    def __init__(self, switch_config: SwitchConfig):
        self.config = switch_config
        self.connection = None

    def connect(self) -> bool:
        """建立SSH连接"""
        try:
            device = {
                "device_type": self.config.device_type,
                "host": self.config.host,
                "username": self.config.username,
                "password": self.config.password,
                "timeout": self.config.timeout,
                "session_timeout": 60,
            }
            if self.config.enable_password:
                device["secret"] = self.config.enable_password

            self.connection = ConnectHandler(**device)
            logger.info(f"成功连接到交换机 {self.config.name} ({self.config.host})")
            return True
        except NetmikoAuthenticationException as e:
            logger.error(f"交换机认证失败 {self.config.name}: {e}")
            raise ConnectionError(f"交换机认证失败: {self.config.name}")
        except NetmikoTimeoutException as e:
            logger.error(f"交换机连接超时 {self.config.name}: {e}")
            raise ConnectionError(f"交换机连接超时: {self.config.name}")
        except Exception as e:
            logger.error(f"交换机连接失败 {self.config.name}: {e}")
            raise ConnectionError(f"交换机连接失败: {str(e)}")

    def disconnect(self):
        """断开SSH连接"""
        if self.connection:
            try:
                self.connection.disconnect()
            except Exception:
                pass
            self.connection = None

    def ping(self, target_ip: str, count: int = 2) -> Dict[str, Any]:
        """
        执行Ping测试

        Args:
            target_ip: 目标IP地址
            count: Ping次数

        Returns:
            包含Ping结果的字典
        """
        result = {
            "success": False,
            "reachable": False,
            "switch_name": self.config.name,
            "switch_ip": self.config.host,
            "target_ip": target_ip,
            "packet_sent": count,
            "packet_received": 0,
            "packet_loss": 100.0,
            "min_time": None,
            "avg_time": None,
            "max_time": None,
            "raw_output": "",
            "message": "",
        }

        if not self.connection:
            result["message"] = "未连接到交换机"
            return result

        try:
            # Cisco IOS ping命令格式 (timeout 1秒加快响应)
            cmd = f"ping {target_ip} repeat {count} timeout 1"
            logger.info(f"在交换机 {self.config.name} 执行: {cmd}")

            output = self.connection.send_command(
                cmd,
                read_timeout=15,
            )
            result["raw_output"] = output
            result["success"] = True

            # 解析Cisco IOS Ping输出
            # 示例输出:
            # Type escape sequence to abort.
            # Sending 5, 100-byte ICMP Echos to 172.20.36.1, timeout is 2 seconds:
            # !!!!!
            # Success rate is 100 percent (5/5), round-trip min/avg/max = 1/1/2 ms
            #
            # 或失败时:
            # Type escape sequence to abort.
            # Sending 5, 100-byte ICMP Echos to 172.20.36.1, timeout is 2 seconds:
            # .....
            # Success rate is 0 percent (0/5)

            # 解析成功率和收发包数 (5/5)
            success_match = re.search(
                r"Success rate is (\d+) percent \((\d+)/(\d+)\)", output
            )
            if success_match:
                success_rate = int(success_match.group(1))
                result["packet_received"] = int(success_match.group(2))
                result["packet_sent"] = int(success_match.group(3))
                result["packet_loss"] = 100 - success_rate
            else:
                # 备用解析
                sent_match = re.search(r"Sending\s+(\d+)", output)
                if sent_match:
                    result["packet_sent"] = int(sent_match.group(1))

            # 解析响应时间 (min/avg/max = 1/1/2 ms)
            time_match = re.search(
                r"round-trip\s+min/avg/max\s*=\s*([\d.]+)/([\d.]+)/([\d.]+)", output
            )
            if time_match:
                result["min_time"] = float(time_match.group(1))
                result["avg_time"] = float(time_match.group(2))
                result["max_time"] = float(time_match.group(3))

            # 判断是否可达
            result["reachable"] = result["packet_received"] > 0

            if result["reachable"]:
                result["message"] = f"可达 (丢包率: {result['packet_loss']:.1f}%)"
                if result["avg_time"]:
                    result["message"] += f", 平均延迟: {result['avg_time']:.1f}ms"
            else:
                # 检查是否有特定错误消息
                if "Request timed out" in output or "timeout" in output.lower():
                    result["message"] = "请求超时，目标不可达"
                elif "Destination host unreachable" in output or "unreachable" in output.lower():
                    result["message"] = "目标主机不可达"
                elif "Unknown host" in output or "Unrecognized host" in output:
                    result["message"] = "未知主机"
                else:
                    result["message"] = "不可达 (100% 丢包)"

            logger.info(
                f"Ping结果: {target_ip} -> {result['message']} "
                f"(通过 {self.config.name})"
            )

        except Exception as e:
            logger.error(f"Ping执行失败: {e}")
            result["message"] = f"执行失败: {str(e)[:100]}"

        return result


def ping_via_switch(
    target_ip: str,
    switch_index: int = 0,
    count: int = 2,
) -> Dict[str, Any]:
    """
    通过交换机执行Ping测试

    Args:
        target_ip: 目标IP地址
        switch_index: 交换机索引 (0=J14-MES-CORE, 1=R1-MES-CORE)
        count: Ping次数

    Returns:
        Ping结果字典
    """
    if switch_index < 0 or switch_index >= len(CORE_SWITCHES):
        return {
            "success": False,
            "reachable": False,
            "message": f"无效的交换机索引: {switch_index}",
        }

    switch_config = CORE_SWITCHES[switch_index]
    service = SwitchPingService(switch_config)

    try:
        service.connect()
        result = service.ping(target_ip, count)
        return result
    except ConnectionError as e:
        return {
            "success": False,
            "reachable": False,
            "switch_name": switch_config.name,
            "switch_ip": switch_config.host,
            "target_ip": target_ip,
            "message": str(e),
        }
    finally:
        service.disconnect()


def ping_via_all_switches(target_ip: str, count: int = 2) -> List[Dict[str, Any]]:
    """
    通过所有交换机执行Ping测试

    Args:
        target_ip: 目标IP地址
        count: Ping次数

    Returns:
        所有交换机的Ping结果列表
    """
    results = []
    for i, _ in enumerate(CORE_SWITCHES):
        result = ping_via_switch(target_ip, i, count)
        results.append(result)
    return results


def get_available_switches() -> List[Dict[str, str]]:
    """获取可用交换机列表（包含全部交换机选项）"""
    switches = [
        {"index": -1, "name": "全部交换机", "ip": "同时测试"}
    ]
    switches.extend([
        {"index": i, "name": s.name, "ip": s.host}
        for i, s in enumerate(CORE_SWITCHES)
    ])
    return switches

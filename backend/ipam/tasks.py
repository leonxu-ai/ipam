"""
Django-Q2异步任务模块

定义定时任务和异步任务
"""

from __future__ import annotations

import logging
from typing import Dict, Any
from django.utils import timezone

logger = logging.getLogger(__name__)


def scan_all_network_devices() -> Dict[str, Any]:
    """
    扫描所有网络设备的定时任务

    由django-q2调度执行，每10分钟运行一次

    Returns:
        扫描结果统计
    """
    from .snmp_scanner import SNMPScanManager

    logger.info("开始执行定时SNMP扫描任务")
    start_time = timezone.now()

    try:
        results = SNMPScanManager.scan_all_devices()

        elapsed = (timezone.now() - start_time).total_seconds()
        results["elapsed_seconds"] = round(elapsed, 2)

        logger.info(
            f"定时SNMP扫描完成: "
            f"成功{results['successful']}/{results['total_devices']}台, "
            f"扫描{results['total_scanned']}条, "
            f"冲突{results['total_conflicts']}个, "
            f"耗时{elapsed:.2f}秒"
        )

        return results

    except Exception as e:
        logger.exception(f"定时SNMP扫描任务失败: {e}")
        return {"error": str(e)}


def scan_single_device(device_id: int) -> Dict[str, Any]:
    """
    扫描单个网络设备的异步任务

    Args:
        device_id: 设备ID

    Returns:
        扫描结果
    """
    from .snmp_scanner import SNMPScanManager

    logger.info(f"开始扫描设备: ID={device_id}")

    try:
        result = SNMPScanManager.scan_device(device_id)
        logger.info(f"设备扫描完成: {result}")
        return result
    except Exception as e:
        logger.exception(f"设备扫描失败: ID={device_id}, {e}")
        return {"error": str(e), "device_id": device_id}


def cleanup_old_audit_logs(days: int = 365) -> Dict[str, Any]:
    """
    清理旧审计日志的定时任务

    注意：由于审计日志有数据库触发器保护，这个任务需要绕过Django ORM

    Args:
        days: 保留天数，默认365天

    Returns:
        清理结果
    """
    from django.db import connection
    from django.utils import timezone
    from datetime import timedelta

    cutoff_date = timezone.now() - timedelta(days=days)

    logger.info(f"开始清理{days}天前的审计日志")

    try:
        # 注意：正常情况下审计日志不应该被删除
        # 这里只是记录日志数量，不实际删除
        from .models import AuditLog

        old_count = AuditLog.objects.filter(timestamp__lt=cutoff_date).count()

        logger.info(
            f"发现{old_count}条超过{days}天的审计日志 "
            f"(截止日期: {cutoff_date.strftime('%Y-%m-%d')})"
        )

        # 如果确实需要删除，需要先禁用触发器
        # 这里不实际执行删除，只返回统计信息
        return {
            "old_log_count": old_count,
            "cutoff_date": cutoff_date.isoformat(),
            "action": "none",  # 不执行删除
            "message": "审计日志受保护，不执行删除",
        }

    except Exception as e:
        logger.exception(f"审计日志清理任务失败: {e}")
        return {"error": str(e)}


def generate_daily_report() -> Dict[str, Any]:
    """
    生成每日IP使用报告

    Returns:
        报告数据
    """
    from django.db.models import Count, Q
    from .models import Subnet, IpAddress, AuditLog
    from datetime import timedelta

    logger.info("开始生成每日IP使用报告")

    try:
        now = timezone.now()
        yesterday = now - timedelta(days=1)

        # IP统计
        ip_stats = IpAddress.objects.aggregate(
            total=Count("id"),
            available=Count("id", filter=Q(status="available")),
            allocated=Count("id", filter=Q(status="allocated")),
            reserved=Count("id", filter=Q(status="reserved")),
            conflict=Count("id", filter=Q(status="conflict")),
        )

        # 昨日活动
        yesterday_allocations = AuditLog.objects.filter(
            action="allocate",
            timestamp__gte=yesterday,
            timestamp__lt=now,
        ).count()

        yesterday_releases = AuditLog.objects.filter(
            action="release",
            timestamp__gte=yesterday,
            timestamp__lt=now,
        ).count()

        yesterday_conflicts = AuditLog.objects.filter(
            action="conflict_detected",
            timestamp__gte=yesterday,
            timestamp__lt=now,
        ).count()

        # 子网使用率排行
        subnets = Subnet.objects.all()
        subnet_usage = []
        for subnet in subnets:
            stats = subnet.get_usage_stats()
            subnet_usage.append({
                "network": subnet.network,
                "usage_rate": stats["usage_rate"],
                "available": stats["available_count"],
            })

        # 按使用率排序
        subnet_usage.sort(key=lambda x: x["usage_rate"], reverse=True)

        report = {
            "report_date": now.strftime("%Y-%m-%d"),
            "ip_statistics": ip_stats,
            "yesterday_activity": {
                "allocations": yesterday_allocations,
                "releases": yesterday_releases,
                "conflicts": yesterday_conflicts,
            },
            "subnet_usage_top5": subnet_usage[:5],
            "alerts": [],
        }

        # 生成告警
        if ip_stats["conflict"] > 0:
            report["alerts"].append(f"当前有{ip_stats['conflict']}个IP地址冲突需要处理")

        for subnet in subnet_usage[:3]:
            if subnet["usage_rate"] > 90:
                report["alerts"].append(
                    f"子网 {subnet['network']} 使用率已达 {subnet['usage_rate']:.1f}%"
                )

        logger.info(f"每日报告生成完成: {report}")
        return report

    except Exception as e:
        logger.exception(f"每日报告生成失败: {e}")
        return {"error": str(e)}


# Django-Q2调度配置
# 需要在settings.py中配置Q_CLUSTER
# 或者通过Django Admin的Schedule模型添加

SCHEDULE_CONFIG = {
    "snmp_scan": {
        "func": "ipam.tasks.scan_all_network_devices",
        "schedule_type": "I",  # Interval
        "minutes": 10,
        "name": "SNMP网络扫描 (每10分钟)",
    },
    "daily_report": {
        "func": "ipam.tasks.generate_daily_report",
        "schedule_type": "D",  # Daily
        "next_run": "08:00",
        "name": "每日IP使用报告",
    },
}

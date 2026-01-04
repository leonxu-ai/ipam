"""
SNMP凭证加密工具

使用Fernet对称加密保护SNMP密码
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured


class EncryptionManager:
    """加密管理器"""

    _instance: Optional[EncryptionManager] = None
    _fernet: Optional[Fernet] = None

    def __new__(cls) -> EncryptionManager:
        """单例模式"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        """初始化加密管理器"""
        if self._fernet is None:
            self._load_key()

    def _load_key(self) -> None:
        """从环境变量或文件加载加密密钥"""
        # 优先从环境变量读取
        key_str = os.getenv('SNMP_ENCRYPTION_KEY')

        if key_str:
            try:
                self._fernet = Fernet(key_str.encode())
                return
            except Exception as e:
                raise ImproperlyConfigured(
                    f"无效的SNMP_ENCRYPTION_KEY环境变量: {e}"
                ) from e

        # 从文件读取（生产环境推荐方式）
        key_file = self._get_key_file_path()

        if key_file.exists():
            try:
                with open(key_file, 'rb') as f:
                    key_bytes = f.read().strip()
                    self._fernet = Fernet(key_bytes)
                return
            except Exception as e:
                raise ImproperlyConfigured(
                    f"无法从 {key_file} 读取加密密钥: {e}"
                ) from e

        # 如果密钥不存在且在开发环境，自动生成
        if settings.DEBUG:
            self._generate_key_file(key_file)
            with open(key_file, 'rb') as f:
                key_bytes = f.read().strip()
                self._fernet = Fernet(key_bytes)
        else:
            raise ImproperlyConfigured(
                f"未找到加密密钥。请设置SNMP_ENCRYPTION_KEY环境变量或创建 {key_file} 文件。\n"
                f"生成密钥命令：python -c \"from cryptography.fernet import Fernet; "
                f"print(Fernet.generate_key().decode())\" > {key_file}"
            )

    def _get_key_file_path(self) -> Path:
        """获取密钥文件路径"""
        # 优先使用配置的路径
        if hasattr(settings, 'SNMP_KEY_FILE'):
            return Path(settings.SNMP_KEY_FILE)

        # 默认路径：/opt/ipim/secrets/snmp_encryption.key
        base_dir = Path(settings.BASE_DIR).parent
        secrets_dir = base_dir / 'secrets'
        secrets_dir.mkdir(exist_ok=True, mode=0o700)
        return secrets_dir / 'snmp_encryption.key'

    def _generate_key_file(self, key_file: Path) -> None:
        """生成新的加密密钥文件（仅开发环境）"""
        key = Fernet.generate_key()

        # 确保secrets目录存在且权限正确
        key_file.parent.mkdir(exist_ok=True, mode=0o700)

        # 写入密钥文件，设置严格权限
        with open(key_file, 'wb') as f:
            f.write(key)

        # 设置文件权限为600（仅所有者可读写）
        os.chmod(key_file, 0o600)

        print(f"✅ 已生成加密密钥文件: {key_file}")
        print(f"⚠️  请妥善保管此文件！密钥丢失将导致已加密数据无法解密。")

    def encrypt(self, plaintext: str) -> str:
        """加密明文字符串"""
        if not plaintext:
            return ""

        if self._fernet is None:
            raise ImproperlyConfigured("加密管理器未正确初始化")

        encrypted_bytes = self._fernet.encrypt(plaintext.encode('utf-8'))
        return encrypted_bytes.decode('utf-8')

    def decrypt(self, ciphertext: str) -> str:
        """解密密文字符串"""
        if not ciphertext:
            return ""

        if self._fernet is None:
            raise ImproperlyConfigured("加密管理器未正确初始化")

        try:
            decrypted_bytes = self._fernet.decrypt(ciphertext.encode('utf-8'))
            return decrypted_bytes.decode('utf-8')
        except Exception as e:
            raise ValueError(f"解密失败: {e}") from e


# 全局单例实例
_encryption_manager: Optional[EncryptionManager] = None


def get_encryption_manager() -> EncryptionManager:
    """获取加密管理器单例"""
    global _encryption_manager
    if _encryption_manager is None:
        _encryption_manager = EncryptionManager()
    return _encryption_manager


def encrypt_snmp_credential(plaintext: str) -> str:
    """加密SNMP凭证（便捷函数）"""
    return get_encryption_manager().encrypt(plaintext)


def decrypt_snmp_credential(ciphertext: str) -> str:
    """解密SNMP凭证（便捷函数）"""
    return get_encryption_manager().decrypt(ciphertext)

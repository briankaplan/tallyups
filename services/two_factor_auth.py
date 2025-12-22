"""
Two-Factor Authentication Service for Tallyups
Implements TOTP (Time-based One-Time Password) compatible with:
- Google Authenticator
- Authy
- 1Password
- Microsoft Authenticator
"""

import os
import base64
import secrets
import logging
from typing import Optional, Tuple, Dict, Any
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# Try to import pyotp
try:
    import pyotp
    PYOTP_AVAILABLE = True
except ImportError:
    PYOTP_AVAILABLE = False
    logger.warning("pyotp not installed - 2FA will be unavailable")

# Try to import qrcode for QR generation
try:
    import qrcode
    from io import BytesIO
    QRCODE_AVAILABLE = True
except ImportError:
    QRCODE_AVAILABLE = False
    logger.info("qrcode not installed - QR codes will use external service")


class TwoFactorAuth:
    """
    Two-Factor Authentication using TOTP.

    Usage:
        tfa = TwoFactorAuth()

        # Setup 2FA for user
        secret, qr_uri = tfa.generate_secret("user@example.com")

        # Verify code during login
        is_valid = tfa.verify_code(secret, "123456")
    """

    def __init__(self, issuer: str = "Tallyups"):
        self.issuer = issuer
        self._db = None

    def _get_db(self):
        """Get database connection lazily."""
        if self._db is None:
            try:
                from db_mysql import MySQLDatabase
                self._db = MySQLDatabase()
            except Exception as e:
                logger.error(f"Failed to connect to database: {e}")
        return self._db

    def is_available(self) -> bool:
        """Check if 2FA is available (pyotp installed)."""
        return PYOTP_AVAILABLE

    def generate_secret(self, user_email: str = "user") -> Tuple[str, str]:
        """
        Generate a new TOTP secret for a user.

        Args:
            user_email: User identifier for the authenticator app

        Returns:
            Tuple of (secret, provisioning_uri)
            - secret: Base32 encoded secret to store
            - provisioning_uri: URI for QR code (otpauth://...)
        """
        if not PYOTP_AVAILABLE:
            raise RuntimeError("pyotp not installed - cannot generate 2FA secret")

        # Generate a random secret
        secret = pyotp.random_base32()

        # Create TOTP instance
        totp = pyotp.TOTP(secret)

        # Generate provisioning URI for QR code
        uri = totp.provisioning_uri(
            name=user_email,
            issuer_name=self.issuer
        )

        logger.info(f"Generated 2FA secret for user")
        return secret, uri

    def verify_code(self, secret: str, code: str, valid_window: int = 1) -> bool:
        """
        Verify a TOTP code.

        Args:
            secret: The user's stored TOTP secret
            code: The 6-digit code from their authenticator app
            valid_window: Number of time steps to check before/after current
                         (1 = check current, previous, and next code)

        Returns:
            True if code is valid, False otherwise
        """
        if not PYOTP_AVAILABLE:
            logger.error("pyotp not installed - cannot verify 2FA code")
            return False

        if not secret or not code:
            return False

        # Clean up code (remove spaces)
        code = code.replace(" ", "").replace("-", "")

        # Verify it's 6 digits
        if not code.isdigit() or len(code) != 6:
            return False

        try:
            totp = pyotp.TOTP(secret)
            return totp.verify(code, valid_window=valid_window)
        except Exception as e:
            logger.error(f"2FA verification error: {e}")
            return False

    def get_current_code(self, secret: str) -> str:
        """
        Get the current TOTP code (for testing/debugging).

        Args:
            secret: The TOTP secret

        Returns:
            Current 6-digit code
        """
        if not PYOTP_AVAILABLE:
            return ""

        totp = pyotp.TOTP(secret)
        return totp.now()

    def generate_qr_code(self, provisioning_uri: str) -> Optional[bytes]:
        """
        Generate a QR code image for the provisioning URI.

        Args:
            provisioning_uri: The otpauth:// URI

        Returns:
            PNG image bytes, or None if qrcode not available
        """
        if not QRCODE_AVAILABLE:
            return None

        try:
            qr = qrcode.QRCode(
                version=1,
                error_correction=qrcode.constants.ERROR_CORRECT_L,
                box_size=10,
                border=4,
            )
            qr.add_data(provisioning_uri)
            qr.make(fit=True)

            img = qr.make_image(fill_color="black", back_color="white")

            buffer = BytesIO()
            img.save(buffer, format="PNG")
            return buffer.getvalue()
        except Exception as e:
            logger.error(f"QR code generation error: {e}")
            return None

    def generate_backup_codes(self, count: int = 10) -> list:
        """
        Generate backup codes for account recovery.

        Args:
            count: Number of backup codes to generate

        Returns:
            List of 8-character backup codes
        """
        codes = []
        for _ in range(count):
            # Generate 8-character alphanumeric code
            code = secrets.token_hex(4).upper()
            codes.append(code)
        return codes

    # Database operations for 2FA settings

    def enable_2fa(self, user_id: str, secret: str, backup_codes: list) -> bool:
        """
        Enable 2FA for a user and store their secret.

        Args:
            user_id: User identifier
            secret: TOTP secret
            backup_codes: List of backup codes

        Returns:
            True if successful
        """
        db = self._get_db()
        if not db:
            return False

        try:
            # Store 2FA settings
            # Hash backup codes before storing
            import hashlib
            hashed_codes = [hashlib.sha256(c.encode()).hexdigest() for c in backup_codes]

            db.execute("""
                INSERT INTO user_2fa (user_id, totp_secret, backup_codes, enabled_at, is_enabled)
                VALUES (%s, %s, %s, NOW(), TRUE)
                ON DUPLICATE KEY UPDATE
                    totp_secret = VALUES(totp_secret),
                    backup_codes = VALUES(backup_codes),
                    enabled_at = NOW(),
                    is_enabled = TRUE
            """, (user_id, secret, ','.join(hashed_codes)))

            logger.info(f"2FA enabled for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to enable 2FA: {e}")
            return False

    def disable_2fa(self, user_id: str) -> bool:
        """Disable 2FA for a user."""
        db = self._get_db()
        if not db:
            return False

        try:
            db.execute("""
                UPDATE user_2fa SET is_enabled = FALSE, disabled_at = NOW()
                WHERE user_id = %s
            """, (user_id,))

            logger.info(f"2FA disabled for user {user_id}")
            return True
        except Exception as e:
            logger.error(f"Failed to disable 2FA: {e}")
            return False

    def get_2fa_status(self, user_id: str) -> Dict[str, Any]:
        """
        Get 2FA status for a user.

        Returns:
            Dict with:
                - enabled: bool
                - enabled_at: datetime or None
                - has_backup_codes: bool
        """
        db = self._get_db()
        if not db:
            return {'enabled': False, 'enabled_at': None, 'has_backup_codes': False}

        try:
            result = db.query_one("""
                SELECT is_enabled, enabled_at, backup_codes
                FROM user_2fa
                WHERE user_id = %s AND is_enabled = TRUE
            """, (user_id,))

            if result:
                return {
                    'enabled': True,
                    'enabled_at': result['enabled_at'],
                    'has_backup_codes': bool(result.get('backup_codes'))
                }
        except Exception as e:
            logger.error(f"Failed to get 2FA status: {e}")

        return {'enabled': False, 'enabled_at': None, 'has_backup_codes': False}

    def get_secret(self, user_id: str) -> Optional[str]:
        """Get the TOTP secret for a user."""
        db = self._get_db()
        if not db:
            return None

        try:
            result = db.query_one("""
                SELECT totp_secret FROM user_2fa
                WHERE user_id = %s AND is_enabled = TRUE
            """, (user_id,))

            return result['totp_secret'] if result else None
        except Exception as e:
            logger.error(f"Failed to get 2FA secret: {e}")
            return None

    def verify_backup_code(self, user_id: str, code: str) -> bool:
        """
        Verify and consume a backup code.

        Args:
            user_id: User identifier
            code: Backup code to verify

        Returns:
            True if code is valid (and marks it as used)
        """
        db = self._get_db()
        if not db:
            return False

        try:
            import hashlib
            code_hash = hashlib.sha256(code.upper().encode()).hexdigest()

            result = db.query_one("""
                SELECT backup_codes FROM user_2fa
                WHERE user_id = %s AND is_enabled = TRUE
            """, (user_id,))

            if not result or not result.get('backup_codes'):
                return False

            codes = result['backup_codes'].split(',')

            if code_hash in codes:
                # Remove the used code
                codes.remove(code_hash)
                db.execute("""
                    UPDATE user_2fa SET backup_codes = %s
                    WHERE user_id = %s
                """, (','.join(codes), user_id))

                logger.info(f"Backup code used for user {user_id}")
                return True

            return False
        except Exception as e:
            logger.error(f"Failed to verify backup code: {e}")
            return False


# Singleton instance
_tfa_instance = None

def get_2fa_service() -> TwoFactorAuth:
    """Get the singleton TwoFactorAuth instance."""
    global _tfa_instance
    if _tfa_instance is None:
        _tfa_instance = TwoFactorAuth()
    return _tfa_instance


# Database schema for 2FA
SCHEMA_2FA = """
CREATE TABLE IF NOT EXISTS user_2fa (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(255) NOT NULL UNIQUE,
    totp_secret VARCHAR(64),
    backup_codes TEXT,
    is_enabled BOOLEAN DEFAULT FALSE,
    enabled_at DATETIME,
    disabled_at DATETIME,
    last_used_at DATETIME,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_user_id (user_id),
    INDEX idx_enabled (is_enabled)
);
"""

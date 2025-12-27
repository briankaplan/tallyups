"""
User Credentials Service for TallyUps
Manages encrypted storage of third-party service credentials per user
"""

import os
import json
import base64
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from db_mysql import get_db_connection

# Configure logging
logger = logging.getLogger(__name__)

# Encryption Configuration
CREDENTIALS_ENCRYPTION_KEY = os.environ.get('CREDENTIALS_ENCRYPTION_KEY', '')
CREDENTIALS_SALT = os.environ.get('CREDENTIALS_SALT', 'tallyups-credentials-salt')

# Service Types
SERVICE_GMAIL = 'gmail'
SERVICE_GOOGLE_CALENDAR = 'google_calendar'
SERVICE_TASKADE = 'taskade'
SERVICE_OPENAI = 'openai'
SERVICE_GEMINI = 'gemini'
SERVICE_ANTHROPIC = 'anthropic'
SERVICE_PLAID = 'plaid'

VALID_SERVICE_TYPES = {
    SERVICE_GMAIL,
    SERVICE_GOOGLE_CALENDAR,
    SERVICE_TASKADE,
    SERVICE_OPENAI,
    SERVICE_GEMINI,
    SERVICE_ANTHROPIC,
    SERVICE_PLAID
}


class CredentialsError(Exception):
    """Base exception for credentials errors"""
    pass


class CredentialNotFoundError(CredentialsError):
    """Credential not found"""
    pass


class UserCredentialsService:
    """
    User Credentials Service

    Handles:
    - Encrypted storage of OAuth tokens and API keys
    - Per-user, per-service credential management
    - Token refresh and expiration tracking
    """

    def __init__(self):
        self.cipher = self._init_cipher()

    def _init_cipher(self) -> Optional[Fernet]:
        """Initialize encryption cipher."""
        if not CREDENTIALS_ENCRYPTION_KEY:
            logger.warning("CREDENTIALS_ENCRYPTION_KEY not set - credentials will not be encrypted!")
            return None

        try:
            # Derive key from password using PBKDF2
            kdf = PBKDF2HMAC(
                algorithm=hashes.SHA256(),
                length=32,
                salt=CREDENTIALS_SALT.encode(),
                iterations=480000,
            )
            key = base64.urlsafe_b64encode(kdf.derive(CREDENTIALS_ENCRYPTION_KEY.encode()))
            return Fernet(key)
        except Exception as e:
            logger.error(f"Failed to initialize encryption: {e}")
            return None

    def _encrypt(self, value: str) -> str:
        """Encrypt a value."""
        if not self.cipher or not value:
            return value
        try:
            return self.cipher.encrypt(value.encode()).decode()
        except Exception as e:
            logger.error(f"Encryption failed: {e}")
            return value

    def _decrypt(self, value: str) -> str:
        """Decrypt a value."""
        if not self.cipher or not value:
            return value
        try:
            return self.cipher.decrypt(value.encode()).decode()
        except Exception as e:
            logger.error(f"Decryption failed: {e}")
            return value

    def store_credential(
        self,
        user_id: str,
        service_type: str,
        access_token: str = None,
        refresh_token: str = None,
        api_key: str = None,
        account_email: str = None,
        account_name: str = None,
        workspace_id: str = None,
        project_id: str = None,
        folder_id: str = None,
        token_expires_at: datetime = None,
        scopes: List[str] = None,
        metadata: Dict[str, Any] = None
    ) -> int:
        """
        Store or update a credential for a user.

        Args:
            user_id: User's UUID
            service_type: Type of service (gmail, openai, etc.)
            access_token: OAuth access token
            refresh_token: OAuth refresh token
            api_key: API key (for services like OpenAI)
            account_email: Email for the account (for multi-account services)
            account_name: Display name for the account
            workspace_id: Taskade workspace ID
            project_id: Taskade project ID
            folder_id: Taskade folder ID
            token_expires_at: When the access token expires
            scopes: OAuth scopes granted
            metadata: Additional service-specific data

        Returns:
            Credential ID
        """
        if service_type not in VALID_SERVICE_TYPES:
            raise CredentialsError(f"Invalid service type: {service_type}")

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Encrypt sensitive data
            encrypted_access_token = self._encrypt(access_token) if access_token else None
            encrypted_refresh_token = self._encrypt(refresh_token) if refresh_token else None
            encrypted_api_key = self._encrypt(api_key) if api_key else None

            # Check if credential already exists
            cursor.execute("""
                SELECT id FROM user_credentials
                WHERE user_id = %s AND service_type = %s AND (account_email = %s OR (account_email IS NULL AND %s IS NULL))
            """, (user_id, service_type, account_email, account_email))

            existing = cursor.fetchone()

            if existing:
                # Update existing credential
                cursor.execute("""
                    UPDATE user_credentials
                    SET access_token = %s,
                        refresh_token = %s,
                        api_key = %s,
                        account_name = %s,
                        workspace_id = %s,
                        project_id = %s,
                        folder_id = %s,
                        token_expires_at = %s,
                        scopes = %s,
                        metadata = %s,
                        is_active = TRUE,
                        last_error = NULL,
                        error_count = 0,
                        updated_at = NOW()
                    WHERE id = %s
                """, (
                    encrypted_access_token,
                    encrypted_refresh_token,
                    encrypted_api_key,
                    account_name,
                    workspace_id,
                    project_id,
                    folder_id,
                    token_expires_at,
                    json.dumps(scopes) if scopes else None,
                    json.dumps(metadata) if metadata else None,
                    existing[0]
                ))
                credential_id = existing[0]
            else:
                # Insert new credential
                cursor.execute("""
                    INSERT INTO user_credentials (
                        user_id, service_type, account_email, account_name,
                        access_token, refresh_token, api_key,
                        workspace_id, project_id, folder_id,
                        token_expires_at, scopes, metadata,
                        is_active, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, TRUE, NOW(), NOW())
                """, (
                    user_id, service_type, account_email, account_name,
                    encrypted_access_token, encrypted_refresh_token, encrypted_api_key,
                    workspace_id, project_id, folder_id,
                    token_expires_at,
                    json.dumps(scopes) if scopes else None,
                    json.dumps(metadata) if metadata else None
                ))
                credential_id = cursor.lastrowid

            conn.commit()
            logger.info(f"Stored credential for user {user_id}, service {service_type}")
            return credential_id

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to store credential: {e}")
            raise CredentialsError(f"Failed to store credential: {e}")
        finally:
            cursor.close()
            conn.close()

    def get_credential(
        self,
        user_id: str,
        service_type: str,
        account_email: str = None
    ) -> Optional[Dict[str, Any]]:
        """
        Get a credential for a user.

        Args:
            user_id: User's UUID
            service_type: Type of service
            account_email: Optional email for multi-account services

        Returns:
            Dict with credential data or None
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            if account_email:
                cursor.execute("""
                    SELECT * FROM user_credentials
                    WHERE user_id = %s AND service_type = %s AND account_email = %s AND is_active = TRUE
                """, (user_id, service_type, account_email))
            else:
                cursor.execute("""
                    SELECT * FROM user_credentials
                    WHERE user_id = %s AND service_type = %s AND is_active = TRUE
                    ORDER BY updated_at DESC
                    LIMIT 1
                """, (user_id, service_type))

            row = cursor.fetchone()

            if not row:
                return None

            # Decrypt sensitive fields
            if row.get('access_token'):
                row['access_token'] = self._decrypt(row['access_token'])
            if row.get('refresh_token'):
                row['refresh_token'] = self._decrypt(row['refresh_token'])
            if row.get('api_key'):
                row['api_key'] = self._decrypt(row['api_key'])

            # Parse JSON fields
            if row.get('scopes'):
                row['scopes'] = json.loads(row['scopes']) if isinstance(row['scopes'], str) else row['scopes']
            if row.get('metadata'):
                row['metadata'] = json.loads(row['metadata']) if isinstance(row['metadata'], str) else row['metadata']

            return row

        except Exception as e:
            logger.error(f"Failed to get credential: {e}")
            return None
        finally:
            cursor.close()
            conn.close()

    def list_credentials(
        self,
        user_id: str,
        service_type: str = None
    ) -> List[Dict[str, Any]]:
        """
        List all credentials for a user.

        Args:
            user_id: User's UUID
            service_type: Optional filter by service type

        Returns:
            List of credential records (without sensitive data)
        """
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        try:
            if service_type:
                cursor.execute("""
                    SELECT id, user_id, service_type, account_email, account_name,
                           workspace_id, project_id, folder_id,
                           token_expires_at, scopes, is_active, last_used_at,
                           created_at, updated_at
                    FROM user_credentials
                    WHERE user_id = %s AND service_type = %s AND is_active = TRUE
                    ORDER BY updated_at DESC
                """, (user_id, service_type))
            else:
                cursor.execute("""
                    SELECT id, user_id, service_type, account_email, account_name,
                           workspace_id, project_id, folder_id,
                           token_expires_at, scopes, is_active, last_used_at,
                           created_at, updated_at
                    FROM user_credentials
                    WHERE user_id = %s AND is_active = TRUE
                    ORDER BY service_type, updated_at DESC
                """, (user_id,))

            rows = cursor.fetchall()

            for row in rows:
                if row.get('scopes'):
                    row['scopes'] = json.loads(row['scopes']) if isinstance(row['scopes'], str) else row['scopes']

            return rows

        except Exception as e:
            logger.error(f"Failed to list credentials: {e}")
            return []
        finally:
            cursor.close()
            conn.close()

    def delete_credential(
        self,
        user_id: str,
        service_type: str,
        account_email: str = None
    ) -> bool:
        """
        Delete a credential (soft delete by setting is_active = FALSE).

        Args:
            user_id: User's UUID
            service_type: Type of service
            account_email: Optional email for multi-account services

        Returns:
            True if credential was deleted
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if account_email:
                cursor.execute("""
                    UPDATE user_credentials
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE user_id = %s AND service_type = %s AND account_email = %s
                """, (user_id, service_type, account_email))
            else:
                cursor.execute("""
                    UPDATE user_credentials
                    SET is_active = FALSE, updated_at = NOW()
                    WHERE user_id = %s AND service_type = %s
                """, (user_id, service_type))

            conn.commit()
            deleted = cursor.rowcount > 0

            if deleted:
                logger.info(f"Deleted credential for user {user_id}, service {service_type}")

            return deleted

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete credential: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

    def update_tokens(
        self,
        user_id: str,
        service_type: str,
        access_token: str,
        refresh_token: str = None,
        token_expires_at: datetime = None,
        account_email: str = None
    ) -> bool:
        """
        Update OAuth tokens for a credential.

        Args:
            user_id: User's UUID
            service_type: Type of service
            access_token: New access token
            refresh_token: Optional new refresh token
            token_expires_at: When the new access token expires
            account_email: Optional email for multi-account services

        Returns:
            True if tokens were updated
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            encrypted_access = self._encrypt(access_token)
            encrypted_refresh = self._encrypt(refresh_token) if refresh_token else None

            if account_email:
                if refresh_token:
                    cursor.execute("""
                        UPDATE user_credentials
                        SET access_token = %s, refresh_token = %s, token_expires_at = %s,
                            last_used_at = NOW(), updated_at = NOW(),
                            last_error = NULL, error_count = 0
                        WHERE user_id = %s AND service_type = %s AND account_email = %s AND is_active = TRUE
                    """, (encrypted_access, encrypted_refresh, token_expires_at, user_id, service_type, account_email))
                else:
                    cursor.execute("""
                        UPDATE user_credentials
                        SET access_token = %s, token_expires_at = %s,
                            last_used_at = NOW(), updated_at = NOW(),
                            last_error = NULL, error_count = 0
                        WHERE user_id = %s AND service_type = %s AND account_email = %s AND is_active = TRUE
                    """, (encrypted_access, token_expires_at, user_id, service_type, account_email))
            else:
                if refresh_token:
                    cursor.execute("""
                        UPDATE user_credentials
                        SET access_token = %s, refresh_token = %s, token_expires_at = %s,
                            last_used_at = NOW(), updated_at = NOW(),
                            last_error = NULL, error_count = 0
                        WHERE user_id = %s AND service_type = %s AND is_active = TRUE
                    """, (encrypted_access, encrypted_refresh, token_expires_at, user_id, service_type))
                else:
                    cursor.execute("""
                        UPDATE user_credentials
                        SET access_token = %s, token_expires_at = %s,
                            last_used_at = NOW(), updated_at = NOW(),
                            last_error = NULL, error_count = 0
                        WHERE user_id = %s AND service_type = %s AND is_active = TRUE
                    """, (encrypted_access, token_expires_at, user_id, service_type))

            conn.commit()
            return cursor.rowcount > 0

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to update tokens: {e}")
            return False
        finally:
            cursor.close()
            conn.close()

    def record_error(
        self,
        user_id: str,
        service_type: str,
        error_message: str,
        account_email: str = None
    ) -> None:
        """
        Record an error for a credential.

        Args:
            user_id: User's UUID
            service_type: Type of service
            error_message: Error message
            account_email: Optional email for multi-account services
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            if account_email:
                cursor.execute("""
                    UPDATE user_credentials
                    SET last_error = %s, error_count = error_count + 1, updated_at = NOW()
                    WHERE user_id = %s AND service_type = %s AND account_email = %s
                """, (error_message, user_id, service_type, account_email))
            else:
                cursor.execute("""
                    UPDATE user_credentials
                    SET last_error = %s, error_count = error_count + 1, updated_at = NOW()
                    WHERE user_id = %s AND service_type = %s
                """, (error_message, user_id, service_type))

            conn.commit()

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to record error: {e}")
        finally:
            cursor.close()
            conn.close()

    def delete_all_user_credentials(self, user_id: str) -> int:
        """
        Delete all credentials for a user (for account deletion).

        Args:
            user_id: User's UUID

        Returns:
            Number of credentials deleted
        """
        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                DELETE FROM user_credentials WHERE user_id = %s
            """, (user_id,))

            conn.commit()
            count = cursor.rowcount

            logger.info(f"Deleted {count} credentials for user {user_id}")
            return count

        except Exception as e:
            conn.rollback()
            logger.error(f"Failed to delete user credentials: {e}")
            return 0
        finally:
            cursor.close()
            conn.close()


# Global service instance
user_credentials_service = UserCredentialsService()


# Convenience functions
def get_gmail_credentials(user_id: str, account_email: str = None) -> Optional[Dict[str, Any]]:
    """Get Gmail OAuth credentials for a user."""
    return user_credentials_service.get_credential(user_id, SERVICE_GMAIL, account_email)


def get_calendar_credentials(user_id: str, account_email: str = None) -> Optional[Dict[str, Any]]:
    """Get Google Calendar OAuth credentials for a user."""
    return user_credentials_service.get_credential(user_id, SERVICE_GOOGLE_CALENDAR, account_email)


def get_taskade_credentials(user_id: str) -> Optional[Dict[str, Any]]:
    """Get Taskade API credentials for a user."""
    return user_credentials_service.get_credential(user_id, SERVICE_TASKADE)


def get_openai_api_key(user_id: str) -> Optional[str]:
    """Get OpenAI API key for a user."""
    creds = user_credentials_service.get_credential(user_id, SERVICE_OPENAI)
    return creds.get('api_key') if creds else None


def get_gemini_api_key(user_id: str) -> Optional[str]:
    """Get Gemini API key for a user."""
    creds = user_credentials_service.get_credential(user_id, SERVICE_GEMINI)
    return creds.get('api_key') if creds else None


def get_anthropic_api_key(user_id: str) -> Optional[str]:
    """Get Anthropic API key for a user."""
    creds = user_credentials_service.get_credential(user_id, SERVICE_ANTHROPIC)
    return creds.get('api_key') if creds else None

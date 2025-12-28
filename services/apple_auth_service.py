"""
Apple Sign In Authentication Service for TallyUps
Handles Apple identity token verification and user authentication
"""

import os
import jwt
import json
import time
import hashlib
import logging
import requests
from typing import Optional, Dict, Any, Tuple
from datetime import datetime, timezone
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend

# Configure logging
logger = logging.getLogger(__name__)

# Apple Auth Configuration
APPLE_ISSUER = 'https://appleid.apple.com'
APPLE_KEYS_URL = 'https://appleid.apple.com/auth/keys'
APPLE_TOKEN_URL = 'https://appleid.apple.com/auth/token'

# Environment variables
APPLE_TEAM_ID = os.environ.get('APPLE_TEAM_ID', '')
APPLE_KEY_ID = os.environ.get('APPLE_KEY_ID', '')
APPLE_PRIVATE_KEY = os.environ.get('APPLE_PRIVATE_KEY', '')
APPLE_BUNDLE_ID = os.environ.get('APPLE_BUNDLE_ID', 'com.tallyups.scanner')
APPLE_SERVICE_ID = os.environ.get('APPLE_SERVICE_ID', 'com.tallyups.web')  # For web sign-in

# Cache for Apple's public keys
_apple_keys_cache = {
    'keys': None,
    'expires': 0
}
KEYS_CACHE_DURATION = 3600  # 1 hour


class AppleAuthError(Exception):
    """Base exception for Apple auth errors"""
    pass


class InvalidIdentityTokenError(AppleAuthError):
    """Identity token is invalid"""
    pass


class AppleAuthService:
    """
    Apple Sign In Authentication Service

    Handles:
    - Identity token verification
    - Authorization code exchange (web flow)
    - User info extraction
    """

    def __init__(self):
        self.team_id = APPLE_TEAM_ID
        self.key_id = APPLE_KEY_ID
        self.private_key = self._parse_private_key(APPLE_PRIVATE_KEY)
        self.bundle_id = APPLE_BUNDLE_ID
        self.service_id = APPLE_SERVICE_ID

    def _parse_private_key(self, key_str: str) -> Optional[str]:
        """Parse private key from environment variable."""
        if not key_str:
            return None
        # Handle escaped newlines
        return key_str.replace('\\n', '\n')

    async def get_apple_public_keys(self) -> Dict[str, Any]:
        """
        Fetch Apple's public keys for token verification.
        Uses caching to avoid repeated requests.

        Returns:
            Dict of public keys by key ID
        """
        global _apple_keys_cache

        now = time.time()

        # Return cached keys if still valid
        if _apple_keys_cache['keys'] and _apple_keys_cache['expires'] > now:
            return _apple_keys_cache['keys']

        try:
            response = requests.get(APPLE_KEYS_URL, timeout=10)
            response.raise_for_status()

            keys_data = response.json()
            keys = {key['kid']: key for key in keys_data['keys']}

            # Update cache
            _apple_keys_cache['keys'] = keys
            _apple_keys_cache['expires'] = now + KEYS_CACHE_DURATION

            return keys

        except Exception as e:
            logger.error(f"Failed to fetch Apple public keys: {e}")
            # Return cached keys if available, even if expired
            if _apple_keys_cache['keys']:
                return _apple_keys_cache['keys']
            raise AppleAuthError("Failed to fetch Apple public keys")

    def get_apple_public_keys_sync(self) -> Dict[str, Any]:
        """Synchronous version of get_apple_public_keys."""
        global _apple_keys_cache

        now = time.time()

        if _apple_keys_cache['keys'] and _apple_keys_cache['expires'] > now:
            return _apple_keys_cache['keys']

        try:
            response = requests.get(APPLE_KEYS_URL, timeout=10)
            response.raise_for_status()

            keys_data = response.json()
            keys = {key['kid']: key for key in keys_data['keys']}

            _apple_keys_cache['keys'] = keys
            _apple_keys_cache['expires'] = now + KEYS_CACHE_DURATION

            return keys

        except Exception as e:
            logger.error(f"Failed to fetch Apple public keys: {e}")
            if _apple_keys_cache['keys']:
                return _apple_keys_cache['keys']
            raise AppleAuthError("Failed to fetch Apple public keys")

    def verify_identity_token(
        self,
        identity_token: str,
        nonce: str = None
    ) -> Dict[str, Any]:
        """
        Verify an Apple identity token (JWT).

        Args:
            identity_token: The identity token from Apple Sign In
            nonce: Optional nonce for additional verification

        Returns:
            Dict containing:
            - apple_user_id: Apple's unique user identifier
            - email: User's email (may be private relay)
            - email_verified: Whether email is verified
            - is_private_email: Whether using private relay
            - name: User's name (first sign-in only)

        Raises:
            InvalidIdentityTokenError: If token verification fails
        """
        try:
            # Decode header to get key ID
            header = jwt.get_unverified_header(identity_token)
            kid = header.get('kid')

            if not kid:
                raise InvalidIdentityTokenError("Token missing key ID")

            # Get Apple's public keys
            keys = self.get_apple_public_keys_sync()

            if kid not in keys:
                # Refresh keys and try again
                _apple_keys_cache['expires'] = 0
                keys = self.get_apple_public_keys_sync()

                if kid not in keys:
                    raise InvalidIdentityTokenError(f"Unknown key ID: {kid}")

            # Get the public key
            key_data = keys[kid]
            public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(key_data))

            # Accept multiple audiences - bundle ID for iOS and service ID for web
            # This handles both iOS app and web sign-in flows
            valid_audiences = [self.bundle_id]
            if self.service_id and self.service_id != self.bundle_id:
                valid_audiences.append(self.service_id)

            logger.debug(f"Verifying token with audiences: {valid_audiences}")

            # Verify and decode the token
            payload = jwt.decode(
                identity_token,
                public_key,
                algorithms=['RS256'],
                audience=valid_audiences,
                issuer=APPLE_ISSUER
            )

            # Verify nonce if provided
            if nonce:
                token_nonce = payload.get('nonce')
                nonce_hash = hashlib.sha256(nonce.encode()).hexdigest()

                if token_nonce != nonce_hash:
                    raise InvalidIdentityTokenError("Nonce mismatch")

            # Extract user info
            return {
                'apple_user_id': payload['sub'],
                'email': payload.get('email'),
                'email_verified': payload.get('email_verified', False),
                'is_private_email': payload.get('is_private_email', False),
                'auth_time': datetime.fromtimestamp(payload.get('auth_time', 0), tz=timezone.utc)
            }

        except jwt.ExpiredSignatureError:
            raise InvalidIdentityTokenError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise InvalidIdentityTokenError(f"Invalid token: {str(e)}")
        except Exception as e:
            logger.error(f"Apple token verification error: {e}")
            raise InvalidIdentityTokenError(f"Token verification failed: {str(e)}")

    def generate_client_secret(self) -> str:
        """
        Generate a client secret for Apple auth.
        Required for authorization code exchange (web flow).

        Returns:
            Client secret JWT
        """
        if not self.private_key or not self.team_id or not self.key_id:
            raise AppleAuthError("Apple auth not configured (missing team_id, key_id, or private_key)")

        now = int(time.time())
        expires = now + (86400 * 180)  # 6 months max

        headers = {
            'kid': self.key_id,
            'alg': 'ES256'
        }

        payload = {
            'iss': self.team_id,
            'iat': now,
            'exp': expires,
            'aud': APPLE_ISSUER,
            'sub': self.service_id  # Use service ID for web
        }

        return jwt.encode(
            payload,
            self.private_key,
            algorithm='ES256',
            headers=headers
        )

    def exchange_authorization_code(
        self,
        code: str,
        redirect_uri: str = None
    ) -> Dict[str, Any]:
        """
        Exchange authorization code for tokens (web flow).

        Args:
            code: Authorization code from Apple
            redirect_uri: Redirect URI used in auth request

        Returns:
            Dict containing:
            - access_token: Apple access token
            - id_token: Identity token
            - refresh_token: Refresh token
            - user_info: Verified user info from id_token
        """
        client_secret = self.generate_client_secret()

        data = {
            'client_id': self.service_id,
            'client_secret': client_secret,
            'code': code,
            'grant_type': 'authorization_code'
        }

        if redirect_uri:
            data['redirect_uri'] = redirect_uri

        try:
            response = requests.post(
                APPLE_TOKEN_URL,
                data=data,
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )

            if response.status_code != 200:
                error = response.json().get('error', 'unknown_error')
                raise AppleAuthError(f"Token exchange failed: {error}")

            token_data = response.json()

            # Verify the identity token
            user_info = self.verify_identity_token(token_data['id_token'])

            return {
                'access_token': token_data.get('access_token'),
                'id_token': token_data['id_token'],
                'refresh_token': token_data.get('refresh_token'),
                'expires_in': token_data.get('expires_in'),
                'user_info': user_info
            }

        except requests.RequestException as e:
            logger.error(f"Apple token exchange request failed: {e}")
            raise AppleAuthError(f"Token exchange request failed: {str(e)}")

    def validate_authorization_code(
        self,
        code: str,
        redirect_uri: str = None
    ) -> Dict[str, Any]:
        """Alias for exchange_authorization_code for API consistency."""
        return self.exchange_authorization_code(code, redirect_uri)

    def revoke_tokens(self, token: str, token_type: str = 'access_token') -> bool:
        """
        Revoke Apple tokens (for account deletion).

        Args:
            token: The token to revoke
            token_type: 'access_token' or 'refresh_token'

        Returns:
            True if successful
        """
        try:
            client_secret = self.generate_client_secret()

            response = requests.post(
                'https://appleid.apple.com/auth/revoke',
                data={
                    'client_id': self.service_id,
                    'client_secret': client_secret,
                    'token': token,
                    'token_type_hint': token_type
                },
                headers={'Content-Type': 'application/x-www-form-urlencoded'},
                timeout=30
            )

            return response.status_code == 200

        except Exception as e:
            logger.error(f"Failed to revoke Apple token: {e}")
            return False


# Global service instance
apple_auth_service = AppleAuthService()


def generate_nonce() -> str:
    """Generate a random nonce for Apple Sign In."""
    import secrets
    return secrets.token_hex(32)


def hash_nonce(nonce: str) -> str:
    """Hash a nonce for use in Apple Sign In request."""
    return hashlib.sha256(nonce.encode()).hexdigest()

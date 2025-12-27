"""
Tallyups Authentication Module
Multi-user JWT authentication with Sign in with Apple support
Backward compatible with password/PIN auth for admin users
"""

import os
import hashlib
import secrets
import logging
import uuid
from functools import wraps
from flask import session, redirect, url_for, request, jsonify, g

# Try to import bcrypt for secure password hashing
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logging.warning("bcrypt not available - using SHA256 fallback (less secure)")

# Try to import JWT service
try:
    from services.jwt_auth_service import (
        jwt_service, JWTError, TokenExpiredError, InvalidTokenError,
        extract_bearer_token, get_current_user_from_request,
        user_required as jwt_user_required,
        admin_required as jwt_admin_required,
        optional_auth as jwt_optional_auth
    )
    JWT_AVAILABLE = True
except ImportError:
    JWT_AVAILABLE = False
    logging.warning("JWT service not available - using legacy auth only")

# Admin user ID constant
ADMIN_USER_ID = '00000000-0000-0000-0000-000000000001'

# Get password from environment variable (hashed)
# Set this in Railway: AUTH_PASSWORD_HASH=<your_bcrypt_hash>
# Or for simple setup: AUTH_PASSWORD=your_password
AUTH_PASSWORD = os.environ.get('AUTH_PASSWORD', '')
AUTH_PASSWORD_HASH = os.environ.get('AUTH_PASSWORD_HASH', '')
AUTH_PIN = os.environ.get('AUTH_PIN', '')  # 4-6 digit PIN for quick mobile unlock

# Session secret key
SECRET_KEY = os.environ.get('SECRET_KEY', secrets.token_hex(32))

# Session timeout (seconds) - default 7 days
SESSION_TIMEOUT = int(os.environ.get('SESSION_TIMEOUT', 60 * 60 * 24 * 7))

# Check if running in production (Railway sets this)
IS_PRODUCTION = bool(os.environ.get('RAILWAY_ENVIRONMENT'))


def hash_password(password: str) -> str:
    """
    Hash password using bcrypt (preferred) or SHA256 fallback.
    For new hashes, use bcrypt. SHA256 is only for legacy compatibility.
    """
    if BCRYPT_AVAILABLE:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    else:
        # Fallback to SHA256 (less secure but works without bcrypt)
        return hashlib.sha256(password.encode()).hexdigest()


def _verify_hash(password: str, stored_hash: str) -> bool:
    """Verify password against stored hash (bcrypt or SHA256)."""
    if not stored_hash:
        return False

    # Try bcrypt first (hashes start with $2b$ or $2a$)
    if BCRYPT_AVAILABLE and stored_hash.startswith('$2'):
        try:
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
        except (ValueError, TypeError):
            return False

    # Fallback to SHA256 comparison (timing-safe)
    password_hash = hashlib.sha256(password.encode()).hexdigest()
    return secrets.compare_digest(password_hash, stored_hash)


def verify_password(password: str) -> bool:
    """
    Verify password against stored hash or plaintext.
    Uses timing-safe comparison to prevent timing attacks.
    """
    if AUTH_PASSWORD_HASH:
        return _verify_hash(password, AUTH_PASSWORD_HASH)
    elif AUTH_PASSWORD:
        # Plaintext comparison - use timing-safe compare
        return secrets.compare_digest(password, AUTH_PASSWORD)
    else:
        # No password set - BLOCK in production, allow in development
        if IS_PRODUCTION:
            logging.error("SECURITY: No AUTH_PASSWORD configured in production!")
            return False
        logging.warning("No password configured - allowing access (development mode only)")
        return True


def verify_pin(pin: str) -> bool:
    """
    Verify PIN for quick mobile unlock.
    Uses timing-safe comparison to prevent timing attacks.
    """
    if AUTH_PIN:
        # Use constant-time comparison to prevent timing attacks
        return secrets.compare_digest(pin, AUTH_PIN)
    return False


def is_authenticated() -> bool:
    """Check if current session is authenticated"""
    # No password configured
    if not AUTH_PASSWORD and not AUTH_PASSWORD_HASH:
        # BLOCK in production, allow in development
        if IS_PRODUCTION:
            logging.error("SECURITY: No AUTH_PASSWORD configured in production!")
            return False
        return True

    # Check Flask session first (handles browser and properly formatted cookies)
    if session.get('authenticated', False):
        return True

    # Check for admin API key (for iOS app and API clients)
    admin_key = request.headers.get('X-Admin-Key') or request.args.get('admin_key')
    expected_key = os.environ.get('ADMIN_API_KEY')
    if expected_key and admin_key == expected_key:
        return True

    return False


def login_required(f):
    """Decorator to require authentication for routes (backward compatible)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Try JWT auth first if available
        if JWT_AVAILABLE:
            user = get_current_user_from_request()
            if user:
                g.user_id = user['user_id']
                g.user_role = user['role']
                g.auth_method = user['auth_method']
                return f(*args, **kwargs)

        # Fall back to legacy auth
        if not is_authenticated():
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            return redirect(url_for('login', next=request.url))

        # Set user context for legacy auth (admin user)
        g.user_id = ADMIN_USER_ID
        g.user_role = 'admin'
        g.auth_method = 'legacy'

        return f(*args, **kwargs)
    return decorated_function


def user_required(f):
    """
    Decorator to require authenticated user (JWT-aware).
    Sets g.user_id, g.user_role for the request.
    """
    if JWT_AVAILABLE:
        return jwt_user_required(f)

    # Fallback to login_required for legacy mode
    return login_required(f)


def admin_required(f):
    """
    Decorator to require admin role.
    """
    if JWT_AVAILABLE:
        return jwt_admin_required(f)

    # Fallback for legacy mode - same as login_required (all legacy users are admin)
    return login_required(f)


def optional_auth(f):
    """
    Decorator that allows optional authentication.
    Sets g.user_id if authenticated, None otherwise.
    """
    if JWT_AVAILABLE:
        return jwt_optional_auth(f)

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if is_authenticated():
            g.user_id = ADMIN_USER_ID
            g.user_role = 'admin'
            g.auth_method = 'legacy'
        else:
            g.user_id = None
            g.user_role = None
            g.auth_method = None
        return f(*args, **kwargs)
    return decorated_function


def api_key_required(f):
    """Decorator for API key authentication (for external integrations)"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key') or request.args.get('api_key')
        expected_key = os.environ.get('API_KEY', '')

        if expected_key and api_key != expected_key:
            return jsonify({'error': 'Invalid API key'}), 401

        # Set admin context for API key auth
        g.user_id = ADMIN_USER_ID
        g.user_role = 'admin'
        g.auth_method = 'api_key'

        return f(*args, **kwargs)
    return decorated_function


def get_current_user_id() -> str:
    """Get the current user's ID from the request context."""
    return getattr(g, 'user_id', ADMIN_USER_ID)


def get_current_user_role() -> str:
    """Get the current user's role from the request context."""
    return getattr(g, 'user_role', 'admin')


def is_admin() -> bool:
    """Check if the current user is an admin."""
    return get_current_user_role() == 'admin'


# Login page HTML - Production Ready with Apple Sign In
LOGIN_PAGE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>Sign In - Tallyups</title>
    <meta name="description" content="Sign in to Tallyups - Smart receipt management for your business">
    <meta name="theme-color" content="#0A0A0A">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <link rel="icon" type="image/png" href="/receipt-icon-192.png">
    <link rel="apple-touch-icon" href="/receipt-icon-192.png">
    <style>
        :root {
            --brand-primary: #00FFA3;
            --brand-primary-hover: #00CC82;
            --brand-primary-glow: rgba(0, 255, 163, 0.3);
            --gray-50: #FAFAFA;
            --gray-100: #F5F5F5;
            --gray-400: #A3A3A3;
            --gray-500: #737373;
            --gray-600: #525252;
            --gray-700: #404040;
            --gray-800: #262626;
            --gray-900: #171717;
            --gray-950: #0A0A0A;
            --error: #EF4444;
            --radius-md: 12px;
            --radius-lg: 16px;
            --radius-xl: 20px;
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
            background: linear-gradient(180deg, var(--gray-950) 0%, #0D1117 100%);
            color: var(--gray-50);
            min-height: 100vh;
            min-height: 100dvh;
            display: flex;
            flex-direction: column;
            align-items: center;
            justify-content: center;
            padding: 20px;
            -webkit-font-smoothing: antialiased;
        }
        .login-container {
            width: 100%;
            max-width: 400px;
            animation: fadeIn 0.5s ease-out;
        }
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        .logo {
            text-align: center;
            margin-bottom: 48px;
        }
        .logo-icon {
            width: 88px;
            height: 88px;
            background: linear-gradient(135deg, var(--brand-primary) 0%, #00CC82 100%);
            border-radius: var(--radius-xl);
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 20px;
            box-shadow: 0 0 40px var(--brand-primary-glow);
        }
        .logo-icon svg {
            width: 44px;
            height: 44px;
            color: var(--gray-950);
        }
        .logo h1 {
            font-size: 32px;
            font-weight: 700;
            letter-spacing: -0.5px;
            margin-bottom: 8px;
        }
        .logo p {
            color: var(--gray-500);
            font-size: 15px;
        }
        .auth-methods {
            display: flex;
            flex-direction: column;
            gap: 12px;
            margin-bottom: 24px;
        }
        .btn {
            width: 100%;
            padding: 16px 24px;
            border: none;
            border-radius: var(--radius-md);
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 12px;
        }
        .btn-apple {
            background: var(--gray-50);
            color: var(--gray-950);
        }
        .btn-apple:hover {
            background: var(--gray-100);
            transform: translateY(-1px);
        }
        .btn-apple svg {
            width: 20px;
            height: 20px;
        }
        .divider {
            display: flex;
            align-items: center;
            gap: 16px;
            margin: 24px 0;
            color: var(--gray-600);
            font-size: 13px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }
        .divider::before, .divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: var(--gray-800);
        }
        .form-group {
            margin-bottom: 16px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: var(--gray-400);
            font-size: 14px;
            font-weight: 500;
        }
        input {
            width: 100%;
            padding: 16px;
            background: var(--gray-900);
            border: 1px solid var(--gray-800);
            border-radius: var(--radius-md);
            color: var(--gray-50);
            font-size: 16px;
            transition: all 0.2s ease;
        }
        input:focus {
            outline: none;
            border-color: var(--brand-primary);
            box-shadow: 0 0 0 3px var(--brand-primary-glow);
        }
        input::placeholder {
            color: var(--gray-600);
        }
        .btn-primary {
            background: linear-gradient(135deg, var(--brand-primary) 0%, var(--brand-primary-hover) 100%);
            color: var(--gray-950);
            margin-top: 8px;
        }
        .btn-primary:hover {
            transform: translateY(-1px);
            box-shadow: 0 4px 20px var(--brand-primary-glow);
        }
        .btn-primary:active {
            transform: translateY(0);
        }
        .error {
            background: rgba(239, 68, 68, 0.1);
            border: 1px solid rgba(239, 68, 68, 0.3);
            color: var(--error);
            padding: 14px 16px;
            border-radius: var(--radius-md);
            margin-bottom: 20px;
            font-size: 14px;
            display: flex;
            align-items: center;
            gap: 10px;
        }
        .error svg {
            width: 18px;
            height: 18px;
            flex-shrink: 0;
        }
        .alt-actions {
            text-align: center;
            margin-top: 24px;
        }
        .alt-actions a {
            color: var(--brand-primary);
            text-decoration: none;
            font-size: 14px;
            font-weight: 500;
            transition: opacity 0.2s;
        }
        .alt-actions a:hover {
            opacity: 0.8;
        }
        .footer {
            margin-top: 48px;
            text-align: center;
            padding-top: 24px;
            border-top: 1px solid var(--gray-800);
        }
        .footer-links {
            display: flex;
            justify-content: center;
            gap: 24px;
            margin-bottom: 16px;
        }
        .footer-links a {
            color: var(--gray-500);
            text-decoration: none;
            font-size: 13px;
            transition: color 0.2s;
        }
        .footer-links a:hover {
            color: var(--gray-400);
        }
        .footer p {
            color: var(--gray-600);
            font-size: 12px;
        }
        @media (max-width: 480px) {
            .logo-icon {
                width: 72px;
                height: 72px;
            }
            .logo-icon svg {
                width: 36px;
                height: 36px;
            }
            .logo h1 {
                font-size: 28px;
            }
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <div class="logo-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <rect x="3" y="4" width="18" height="16" rx="2"/>
                    <line x1="7" y1="9" x2="17" y2="9"/>
                    <line x1="7" y1="13" x2="13" y2="13"/>
                    <line x1="7" y1="17" x2="10" y2="17"/>
                </svg>
            </div>
            <h1>Tallyups</h1>
            <p>Smart receipt management</p>
        </div>

        {% if error %}
        <div class="error">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="8" x2="12" y2="12"/>
                <line x1="12" y1="16" x2="12.01" y2="16"/>
            </svg>
            {{ error }}
        </div>
        {% endif %}

        <div class="auth-methods">
            <button type="button" class="btn btn-apple" onclick="signInWithApple()">
                <svg viewBox="0 0 24 24" fill="currentColor">
                    <path d="M17.05 20.28c-.98.95-2.05.8-3.08.35-1.09-.46-2.09-.48-3.24 0-1.44.62-2.2.44-3.06-.35C2.79 15.25 3.51 7.59 9.05 7.31c1.35.07 2.29.74 3.08.8 1.18-.24 2.31-.93 3.57-.84 1.51.12 2.65.72 3.4 1.8-3.12 1.87-2.38 5.98.48 7.13-.57 1.5-1.31 2.99-2.54 4.09l.01-.01zM12.03 7.25c-.15-2.23 1.66-4.07 3.74-4.25.29 2.58-2.34 4.5-3.74 4.25z"/>
                </svg>
                Continue with Apple
            </button>
        </div>

        <div class="divider">or sign in with password</div>

        <form method="POST" id="login-form">
            <div class="form-group">
                <label for="password">Password</label>
                <input type="password" id="password" name="password" placeholder="Enter your password" autofocus required autocomplete="current-password">
            </div>
            <button type="submit" class="btn btn-primary">Sign In</button>
        </form>

        {% if has_pin %}
        <div class="alt-actions">
            <a href="/login/pin">Use PIN instead</a>
        </div>
        {% endif %}

        <div class="footer">
            <div class="footer-links">
                <a href="/terms">Terms of Service</a>
                <a href="/privacy">Privacy Policy</a>
            </div>
            <p>&copy; 2025 Tallyups. All rights reserved.</p>
        </div>
    </div>

    <script>
        function signInWithApple() {
            // Apple Sign In will be handled via the native flow or web redirect
            window.location.href = '/auth/apple';
        }
    </script>
</body>
</html>
'''

PIN_PAGE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tallyups - PIN</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, system-ui, sans-serif;
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .container {
            text-align: center;
            padding: 20px;
        }
        h1 { font-size: 24px; margin-bottom: 8px; }
        p { color: #666; margin-bottom: 24px; }

        /* Face ID Button */
        .faceid-btn {
            width: 100%;
            max-width: 280px;
            padding: 16px 24px;
            background: linear-gradient(135deg, #00ff88, #00cc6a);
            border: none;
            border-radius: 16px;
            color: #000;
            font-size: 17px;
            font-weight: 600;
            cursor: pointer;
            display: none;
            align-items: center;
            justify-content: center;
            gap: 12px;
            margin: 0 auto 24px;
            transition: all 0.2s;
        }
        .faceid-btn:hover { transform: scale(1.02); }
        .faceid-btn:active { transform: scale(0.98); }
        .faceid-btn.visible { display: flex; }
        .faceid-icon {
            width: 28px;
            height: 28px;
        }

        .divider {
            display: none;
            align-items: center;
            gap: 16px;
            margin: 24px 0;
            color: #444;
            font-size: 13px;
        }
        .divider.visible { display: flex; }
        .divider::before,
        .divider::after {
            content: '';
            flex: 1;
            height: 1px;
            background: #333;
        }

        .pin-display {
            display: flex;
            gap: 12px;
            justify-content: center;
            margin-bottom: 40px;
        }
        .pin-dot {
            width: 16px;
            height: 16px;
            border: 2px solid #333;
            border-radius: 50%;
            transition: all 0.2s;
        }
        .pin-dot.filled {
            background: #00ff88;
            border-color: #00ff88;
        }
        .keypad {
            display: grid;
            grid-template-columns: repeat(3, 80px);
            gap: 16px;
            justify-content: center;
        }
        .key {
            width: 80px;
            height: 80px;
            background: #111;
            border: 1px solid #333;
            border-radius: 50%;
            color: #fff;
            font-size: 28px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.1s;
        }
        .key:active {
            background: #00ff88;
            color: #000;
            transform: scale(0.95);
        }
        .key.delete {
            font-size: 20px;
        }
        .error {
            color: #ff4444;
            margin-top: 20px;
        }
        .back-link {
            margin-top: 30px;
        }
        .back-link a {
            color: #666;
            text-decoration: none;
        }

        /* Touch ID success animation */
        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.1); }
            100% { transform: scale(1); }
        }
        .faceid-success {
            animation: pulse 0.3s ease;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Unlock Tallyups</h1>
        <p id="subtitle">Use Face ID or enter PIN</p>

        <!-- Face ID Button -->
        <button class="faceid-btn" id="faceid-btn" onclick="tryFaceID()">
            <svg class="faceid-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                <rect x="3" y="3" width="18" height="18" rx="3"/>
                <circle cx="9" cy="10" r="1" fill="currentColor"/>
                <circle cx="15" cy="10" r="1" fill="currentColor"/>
                <path d="M9 15c.5 1.5 2 2 3 2s2.5-.5 3-2" stroke-linecap="round"/>
            </svg>
            <span id="faceid-text">Use Face ID</span>
        </button>

        <div class="divider" id="divider">or enter PIN</div>

        <div class="pin-display">
            <div class="pin-dot" id="dot-0"></div>
            <div class="pin-dot" id="dot-1"></div>
            <div class="pin-dot" id="dot-2"></div>
            <div class="pin-dot" id="dot-3"></div>
        </div>

        <div class="keypad">
            <button class="key" onclick="addDigit('1')">1</button>
            <button class="key" onclick="addDigit('2')">2</button>
            <button class="key" onclick="addDigit('3')">3</button>
            <button class="key" onclick="addDigit('4')">4</button>
            <button class="key" onclick="addDigit('5')">5</button>
            <button class="key" onclick="addDigit('6')">6</button>
            <button class="key" onclick="addDigit('7')">7</button>
            <button class="key" onclick="addDigit('8')">8</button>
            <button class="key" onclick="addDigit('9')">9</button>
            <button class="key" onclick=""></button>
            <button class="key" onclick="addDigit('0')">0</button>
            <button class="key delete" onclick="deleteDigit()">⌫</button>
        </div>

        <div class="error" id="error" style="display:none">Incorrect PIN</div>

        <div class="back-link">
            <a href="/login">Use password instead</a>
        </div>
    </div>

    <script>
        let pin = '';
        const maxLength = 4;
        const BIOMETRIC_KEY = 'tallyups_biometric_enabled';
        const BIOMETRIC_CRED = 'tallyups_biometric_cred';

        // Check if WebAuthn is available and biometrics enrolled
        async function checkBiometricSupport() {
            // Check for WebAuthn support
            if (!window.PublicKeyCredential) {
                console.log('WebAuthn not supported');
                return false;
            }

            // Check if platform authenticator (Face ID/Touch ID) is available
            try {
                const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
                if (!available) {
                    console.log('Platform authenticator not available');
                    return false;
                }
            } catch (e) {
                console.log('Platform auth check failed:', e);
                return false;
            }

            // Check if user has enabled biometrics
            const biometricEnabled = localStorage.getItem(BIOMETRIC_KEY);
            return biometricEnabled === 'true';
        }

        // Initialize - check for biometric support
        async function init() {
            const canUseBiometric = await checkBiometricSupport();

            if (canUseBiometric) {
                document.getElementById('faceid-btn').classList.add('visible');
                document.getElementById('divider').classList.add('visible');

                // Auto-trigger Face ID on load
                setTimeout(() => tryFaceID(), 500);
            } else {
                document.getElementById('subtitle').textContent = 'Enter your PIN';
            }
        }

        // Try Face ID authentication
        async function tryFaceID() {
            const btn = document.getElementById('faceid-btn');
            const text = document.getElementById('faceid-text');

            try {
                text.textContent = 'Authenticating...';
                btn.disabled = true;

                // Get stored credential ID
                const storedCred = localStorage.getItem(BIOMETRIC_CRED);

                if (!storedCred) {
                    // No credential stored - need to enroll first (done after PIN/password login)
                    text.textContent = 'Use Face ID';
                    btn.disabled = false;
                    return;
                }

                // Request authentication
                const challenge = new Uint8Array(32);
                crypto.getRandomValues(challenge);

                const credential = await navigator.credentials.get({
                    publicKey: {
                        challenge: challenge,
                        rpId: window.location.hostname,
                        allowCredentials: [{
                            id: Uint8Array.from(atob(storedCred), c => c.charCodeAt(0)),
                            type: 'public-key',
                            transports: ['internal']
                        }],
                        userVerification: 'required',
                        timeout: 60000
                    }
                });

                if (credential) {
                    // Success! Verify with server
                    btn.classList.add('faceid-success');
                    text.textContent = 'Verified!';

                    // Extract authenticator data from the response
                    const authData = credential.response.authenticatorData;
                    const authDataB64 = btoa(String.fromCharCode(...new Uint8Array(authData)));

                    const response = await fetch('/login/biometric', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({
                            credential_id: btoa(String.fromCharCode(...new Uint8Array(credential.rawId))),
                            authenticator_data: authDataB64
                        })
                    });

                    if (response.ok) {
                        window.location.href = '{{ next_url }}';
                    } else {
                        text.textContent = 'Verification failed';
                        btn.disabled = false;
                    }
                }
            } catch (e) {
                console.log('Face ID error:', e);
                text.textContent = 'Use Face ID';
                btn.disabled = false;

                // User cancelled or error - show PIN instead
                if (e.name === 'NotAllowedError') {
                    // User denied - that's fine, use PIN
                }
            }
        }

        function updateDots() {
            for (let i = 0; i < maxLength; i++) {
                document.getElementById('dot-' + i).classList.toggle('filled', i < pin.length);
            }
        }

        function addDigit(d) {
            if (pin.length < maxLength) {
                pin += d;
                updateDots();
                if (pin.length === maxLength) {
                    submitPin();
                }
            }
        }

        function deleteDigit() {
            pin = pin.slice(0, -1);
            updateDots();
            document.getElementById('error').style.display = 'none';
        }

        async function submitPin() {
            const response = await fetch('/login/pin', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({pin: pin})
            });

            if (response.ok) {
                // After successful PIN login, prompt to enable Face ID
                promptEnableBiometric();
            } else {
                document.getElementById('error').style.display = 'block';
                pin = '';
                updateDots();
            }
        }

        // Prompt user to enable biometrics after successful login
        async function promptEnableBiometric() {
            // Check if platform authenticator is available and not already enrolled
            if (!window.PublicKeyCredential) {
                window.location.href = '{{ next_url }}';
                return;
            }

            const available = await PublicKeyCredential.isUserVerifyingPlatformAuthenticatorAvailable();
            const alreadyEnabled = localStorage.getItem(BIOMETRIC_KEY) === 'true';

            if (!available || alreadyEnabled) {
                window.location.href = '{{ next_url }}';
                return;
            }

            // Ask user if they want to enable Face ID
            if (confirm('Enable Face ID for faster login?')) {
                try {
                    await enrollBiometric();
                } catch (e) {
                    console.log('Biometric enrollment failed:', e);
                }
            }

            window.location.href = '{{ next_url }}';
        }

        // Enroll biometric credential
        async function enrollBiometric() {
            const challenge = new Uint8Array(32);
            crypto.getRandomValues(challenge);

            const userId = new Uint8Array(16);
            crypto.getRandomValues(userId);

            const credential = await navigator.credentials.create({
                publicKey: {
                    challenge: challenge,
                    rp: {
                        name: 'Tallyups',
                        id: window.location.hostname
                    },
                    user: {
                        id: userId,
                        name: 'user@tallyups',
                        displayName: 'Tallyups User'
                    },
                    pubKeyCredParams: [
                        { type: 'public-key', alg: -7 },  // ES256
                        { type: 'public-key', alg: -257 } // RS256
                    ],
                    authenticatorSelection: {
                        authenticatorAttachment: 'platform',
                        userVerification: 'required',
                        residentKey: 'discouraged'
                    },
                    timeout: 60000,
                    attestation: 'none'
                }
            });

            if (credential) {
                // Store the credential ID locally
                const credId = btoa(String.fromCharCode(...new Uint8Array(credential.rawId)));
                localStorage.setItem(BIOMETRIC_CRED, credId);
                localStorage.setItem(BIOMETRIC_KEY, 'true');

                // Register with server
                await fetch('/api/biometric/register', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        credential_id: credId
                    })
                });
            }
        }

        // Initialize on load
        init();
    </script>
</body>
</html>
'''

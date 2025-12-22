"""
Tallyups Authentication Module
Secure password-based auth with bcrypt hashing and timing-safe comparisons
"""

import os
import hashlib
import secrets
import logging
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

# Try to import bcrypt for secure password hashing
try:
    import bcrypt
    BCRYPT_AVAILABLE = True
except ImportError:
    BCRYPT_AVAILABLE = False
    logging.warning("bcrypt not available - using SHA256 fallback (less secure)")

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
    """Decorator to require authentication for routes"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not is_authenticated():
            # Check if it's an API request
            if request.is_json or request.path.startswith('/api/'):
                return jsonify({'error': 'Authentication required'}), 401
            # Redirect to login for browser requests
            return redirect(url_for('login', next=request.url))
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

        return f(*args, **kwargs)
    return decorated_function


# Login page HTML
LOGIN_PAGE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Tallyups - Login</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
            background: #000;
            color: #fff;
            min-height: 100vh;
            display: flex;
            align-items: center;
            justify-content: center;
        }
        .login-container {
            width: 100%;
            max-width: 400px;
            padding: 40px 20px;
        }
        .logo {
            text-align: center;
            margin-bottom: 40px;
        }
        .logo-icon {
            width: 80px;
            height: 80px;
            background: #00ff88;
            border-radius: 20px;
            display: inline-flex;
            align-items: center;
            justify-content: center;
            margin-bottom: 16px;
        }
        .logo-icon svg {
            width: 40px;
            height: 40px;
            color: #000;
        }
        .logo h1 {
            font-size: 28px;
            font-weight: 600;
            letter-spacing: -0.5px;
        }
        .logo p {
            color: #666;
            margin-top: 8px;
        }
        .form-group {
            margin-bottom: 20px;
        }
        label {
            display: block;
            margin-bottom: 8px;
            color: #999;
            font-size: 14px;
        }
        input {
            width: 100%;
            padding: 16px;
            background: #111;
            border: 1px solid #333;
            border-radius: 12px;
            color: #fff;
            font-size: 16px;
            transition: border-color 0.2s;
        }
        input:focus {
            outline: none;
            border-color: #00ff88;
        }
        input::placeholder {
            color: #444;
        }
        button {
            width: 100%;
            padding: 16px;
            background: #00ff88;
            border: none;
            border-radius: 12px;
            color: #000;
            font-size: 16px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }
        button:hover {
            background: #00cc6a;
            transform: translateY(-1px);
        }
        button:active {
            transform: translateY(0);
        }
        .error {
            background: rgba(255, 68, 68, 0.1);
            border: 1px solid #ff4444;
            color: #ff4444;
            padding: 12px 16px;
            border-radius: 8px;
            margin-bottom: 20px;
            font-size: 14px;
        }
        .pin-toggle {
            text-align: center;
            margin-top: 20px;
        }
        .pin-toggle a {
            color: #00ff88;
            text-decoration: none;
            font-size: 14px;
        }
        .pin-input {
            display: flex;
            gap: 12px;
            justify-content: center;
        }
        .pin-input input {
            width: 50px;
            height: 60px;
            text-align: center;
            font-size: 24px;
            font-weight: 600;
        }
    </style>
</head>
<body>
    <div class="login-container">
        <div class="logo">
            <div class="logo-icon">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <rect x="3" y="4" width="18" height="16" rx="2"/>
                    <line x1="7" y1="9" x2="17" y2="9"/>
                    <line x1="7" y1="13" x2="13" y2="13"/>
                    <line x1="7" y1="17" x2="10" y2="17"/>
                </svg>
            </div>
            <h1>Tallyups</h1>
            <p>Enter your password to continue</p>
        </div>

        {% if error %}
        <div class="error">{{ error }}</div>
        {% endif %}

        <form method="POST" id="login-form">
            <div class="form-group">
                <label>Password</label>
                <input type="password" name="password" placeholder="Enter password" autofocus required>
            </div>
            <button type="submit">Unlock</button>
        </form>

        {% if has_pin %}
        <div class="pin-toggle">
            <a href="/login/pin">Use PIN instead</a>
        </div>
        {% endif %}
    </div>
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

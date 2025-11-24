"""
Tallyups Authentication Module
Simple password-based auth for personal use
"""

import os
import hashlib
import secrets
from functools import wraps
from flask import session, redirect, url_for, request, jsonify

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


def hash_password(password: str) -> str:
    """Simple SHA256 hash for password comparison"""
    return hashlib.sha256(password.encode()).hexdigest()


def verify_password(password: str) -> bool:
    """Verify password against stored hash or plaintext"""
    if AUTH_PASSWORD_HASH:
        return hash_password(password) == AUTH_PASSWORD_HASH
    elif AUTH_PASSWORD:
        return password == AUTH_PASSWORD
    else:
        # No password set - allow access (for local development)
        return True


def verify_pin(pin: str) -> bool:
    """Verify PIN for quick mobile unlock"""
    if AUTH_PIN:
        return pin == AUTH_PIN
    return False


def is_authenticated() -> bool:
    """Check if current session is authenticated"""
    # No password configured = no auth required (local dev)
    if not AUTH_PASSWORD and not AUTH_PASSWORD_HASH:
        return True
    return session.get('authenticated', False)


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
        p { color: #666; margin-bottom: 40px; }
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
    </style>
</head>
<body>
    <div class="container">
        <h1>Enter PIN</h1>
        <p>Quick unlock</p>

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
                window.location.href = '{{ next_url }}';
            } else {
                document.getElementById('error').style.display = 'block';
                pin = '';
                updateDots();
            }
        }
    </script>
</body>
</html>
'''

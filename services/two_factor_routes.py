"""
Two-Factor Authentication API Routes for Tallyups
"""

import logging
from flask import Blueprint, request, jsonify, session, send_file
from io import BytesIO

from auth import login_required
from services.two_factor_auth import get_2fa_service

logger = logging.getLogger(__name__)

tfa_bp = Blueprint('tfa', __name__, url_prefix='/api/2fa')


def get_user_id():
    """Get current user ID from session."""
    return session.get('user_id', 'default')


@tfa_bp.route('/status', methods=['GET'])
@login_required
def get_status():
    """Get 2FA status for current user."""
    tfa = get_2fa_service()

    if not tfa.is_available():
        return jsonify({
            'available': False,
            'enabled': False,
            'message': 'Two-factor authentication is not configured on the server'
        })

    status = tfa.get_2fa_status(get_user_id())

    return jsonify({
        'available': True,
        'enabled': status['enabled'],
        'enabled_at': status['enabled_at'].isoformat() if status['enabled_at'] else None,
        'has_backup_codes': status['has_backup_codes']
    })


@tfa_bp.route('/setup', methods=['POST'])
@login_required
def setup_2fa():
    """
    Start 2FA setup - generate secret and QR code.

    Response:
        {
            "success": true,
            "secret": "BASE32SECRET",
            "qr_uri": "otpauth://totp/...",
            "qr_image_url": "/api/2fa/qr?uri=..."
        }
    """
    tfa = get_2fa_service()

    if not tfa.is_available():
        return jsonify({
            'success': False,
            'error': 'Two-factor authentication is not available'
        }), 503

    user_email = request.json.get('email', 'user@tallyups.com') if request.json else 'user@tallyups.com'

    try:
        secret, provisioning_uri = tfa.generate_secret(user_email)

        # Store secret in session temporarily until verified
        session['pending_2fa_secret'] = secret

        return jsonify({
            'success': True,
            'secret': secret,
            'qr_uri': provisioning_uri,
            'qr_image_url': f'/api/2fa/qr?uri={provisioning_uri}'
        })
    except Exception as e:
        logger.error(f"2FA setup error: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@tfa_bp.route('/qr', methods=['GET'])
@login_required
def get_qr_code():
    """Generate QR code image for provisioning URI."""
    tfa = get_2fa_service()

    uri = request.args.get('uri', '')
    if not uri:
        return jsonify({'error': 'Missing URI parameter'}), 400

    qr_bytes = tfa.generate_qr_code(uri)

    if qr_bytes:
        return send_file(
            BytesIO(qr_bytes),
            mimetype='image/png',
            as_attachment=False
        )
    else:
        # Return a redirect to external QR service
        import urllib.parse
        encoded_uri = urllib.parse.quote(uri)
        return jsonify({
            'qr_url': f'https://api.qrserver.com/v1/create-qr-code/?size=200x200&data={encoded_uri}'
        })


@tfa_bp.route('/verify', methods=['POST'])
@login_required
def verify_and_enable():
    """
    Verify TOTP code and enable 2FA.

    Request:
        { "code": "123456" }

    Response:
        {
            "success": true,
            "backup_codes": ["ABC12345", "DEF67890", ...]
        }
    """
    tfa = get_2fa_service()

    data = request.get_json()
    if not data or not data.get('code'):
        return jsonify({
            'success': False,
            'error': 'Verification code is required'
        }), 400

    code = data['code']
    secret = session.get('pending_2fa_secret')

    if not secret:
        return jsonify({
            'success': False,
            'error': 'No pending 2FA setup. Please start setup again.'
        }), 400

    # Verify the code
    if not tfa.verify_code(secret, code):
        return jsonify({
            'success': False,
            'error': 'Invalid verification code. Please try again.'
        }), 400

    # Generate backup codes
    backup_codes = tfa.generate_backup_codes(10)

    # Enable 2FA
    user_id = get_user_id()
    if tfa.enable_2fa(user_id, secret, backup_codes):
        # Clear pending secret
        session.pop('pending_2fa_secret', None)

        # Mark session as 2FA verified
        session['2fa_verified'] = True

        return jsonify({
            'success': True,
            'backup_codes': backup_codes,
            'message': 'Two-factor authentication enabled successfully'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to enable 2FA. Please try again.'
        }), 500


@tfa_bp.route('/disable', methods=['POST'])
@login_required
def disable_2fa():
    """
    Disable 2FA.

    Request:
        { "code": "123456" }  # Current 2FA code required to disable
    """
    tfa = get_2fa_service()

    data = request.get_json()
    if not data or not data.get('code'):
        return jsonify({
            'success': False,
            'error': 'Current 2FA code is required to disable'
        }), 400

    user_id = get_user_id()
    secret = tfa.get_secret(user_id)

    if not secret:
        return jsonify({
            'success': False,
            'error': '2FA is not enabled'
        }), 400

    # Verify code before disabling
    if not tfa.verify_code(secret, data['code']):
        return jsonify({
            'success': False,
            'error': 'Invalid verification code'
        }), 400

    if tfa.disable_2fa(user_id):
        session.pop('2fa_verified', None)
        return jsonify({
            'success': True,
            'message': 'Two-factor authentication disabled'
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to disable 2FA'
        }), 500


@tfa_bp.route('/validate', methods=['POST'])
def validate_2fa():
    """
    Validate 2FA code during login.
    Called after password verification.

    Request:
        { "code": "123456" }
        or
        { "backup_code": "ABC12345" }
    """
    tfa = get_2fa_service()

    # Check if 2FA is pending
    if not session.get('2fa_pending'):
        return jsonify({
            'success': False,
            'error': 'No pending 2FA verification'
        }), 400

    data = request.get_json()
    if not data:
        return jsonify({
            'success': False,
            'error': 'Code is required'
        }), 400

    user_id = session.get('pending_user_id', 'default')
    secret = tfa.get_secret(user_id)

    if not secret:
        # 2FA not enabled, shouldn't happen
        session['authenticated'] = True
        session.pop('2fa_pending', None)
        return jsonify({'success': True})

    # Try TOTP code first
    code = data.get('code')
    if code and tfa.verify_code(secret, code):
        session['authenticated'] = True
        session['2fa_verified'] = True
        session.pop('2fa_pending', None)
        session.pop('pending_user_id', None)
        return jsonify({'success': True})

    # Try backup code
    backup_code = data.get('backup_code')
    if backup_code and tfa.verify_backup_code(user_id, backup_code):
        session['authenticated'] = True
        session['2fa_verified'] = True
        session.pop('2fa_pending', None)
        session.pop('pending_user_id', None)
        return jsonify({
            'success': True,
            'message': 'Logged in with backup code. Consider generating new backup codes.'
        })

    return jsonify({
        'success': False,
        'error': 'Invalid code'
    }), 400


@tfa_bp.route('/backup-codes', methods=['POST'])
@login_required
def regenerate_backup_codes():
    """
    Generate new backup codes (invalidates old ones).

    Request:
        { "code": "123456" }  # Current 2FA code required
    """
    tfa = get_2fa_service()

    data = request.get_json()
    if not data or not data.get('code'):
        return jsonify({
            'success': False,
            'error': 'Current 2FA code is required'
        }), 400

    user_id = get_user_id()
    secret = tfa.get_secret(user_id)

    if not secret:
        return jsonify({
            'success': False,
            'error': '2FA is not enabled'
        }), 400

    # Verify code
    if not tfa.verify_code(secret, data['code']):
        return jsonify({
            'success': False,
            'error': 'Invalid verification code'
        }), 400

    # Generate new backup codes
    backup_codes = tfa.generate_backup_codes(10)

    if tfa.enable_2fa(user_id, secret, backup_codes):
        return jsonify({
            'success': True,
            'backup_codes': backup_codes
        })
    else:
        return jsonify({
            'success': False,
            'error': 'Failed to regenerate backup codes'
        }), 500

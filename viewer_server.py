#!/usr/bin/env python3
"""
Tallyups Receipt Reconciliation Server
MySQL-only database backend - all SQLite/CSV code has been removed.
"""

# Version info for deployment verification - increment on each deploy
APP_VERSION = "2025.12.04.v4"
APP_BUILD_TIME = "2025-12-04T21:35:00Z"
import os
import math
import json
import base64
import random
import re
import zipfile
import io
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime, date

from flask import Flask, send_from_directory, jsonify, request, abort, Response, make_response, send_file, g
from werkzeug.middleware.proxy_fix import ProxyFix

# Initialize structured logging first
from logging_config import (
    init_logging,
    get_logger,
    set_context,
    clear_context,
    log_context,
    log_timing,
    ReceiptLogger,
    APILogger,
    DatabaseLogger,
    flask_request_logger,
)
init_logging()
logger = get_logger("viewer_server")
receipt_logger = ReceiptLogger()
api_logger = APILogger()
db_logger = DatabaseLogger()
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False
    CSRFProtect = None
    generate_csrf = None
    print("⚠️ Flask-WTF not installed. CSRF protection disabled. Install with: pip install Flask-WTF")
import pandas as pd

from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image
from pillow_heif import register_heif_opener

# Register HEIF opener for HEIC file support
register_heif_opener()

load_dotenv()

# Import Gemini utility with automatic key fallback
from gemini_utils import generate_content_with_fallback, analyze_receipt_image, get_model as get_gemini_model

# Import unified OCR service (Mindee-quality extraction)
try:
    from receipt_ocr_service import ReceiptOCRService, extract_receipt, verify_receipt
    OCR_SERVICE_AVAILABLE = True
    print("✅ Receipt OCR Service loaded (Gemini + Ollama fallback)")
except ImportError as e:
    OCR_SERVICE_AVAILABLE = False
    print(f"⚠️ Receipt OCR Service not available: {e}")

# === MERCHANT INTELLIGENCE ===
try:
    from merchant_intelligence import get_merchant_intelligence, process_transaction_mi, process_all_mi
    merchant_intel = get_merchant_intelligence()
    print(f"✅ Merchant intelligence loaded")
except Exception as e:
    print(f"⚠️ Merchant intelligence not available: {e}")
    merchant_intel = None
    process_transaction_mi = None
    process_all_mi = None

# === DATABASE (MySQL only) ===
USE_DATABASE = False
db = None

try:
    from db_mysql import get_mysql_db
    db = get_mysql_db()
    if db.use_mysql:
        USE_DATABASE = True
        print(f"✅ Using MySQL database")
    else:
        raise RuntimeError("MySQL connection failed")
except Exception as e:
    print(f"❌ MySQL required but not available: {e}")
    raise RuntimeError(f"MySQL database is required. Error: {e}")

# === DATABASE HELPER FUNCTIONS (MySQL-only) ===
def get_db_connection():
    """
    Get a MySQL database connection from the pool.

    Returns: (conn, db_type) tuple where:
    - conn: MySQL connection object with DictCursor
    - db_type: always 'mysql'

    IMPORTANT: Caller must return connection using return_db_connection(conn) when done!
    Do NOT call return_db_connection(conn) directly - this will leak pool connections.
    """
    if not db:
        raise RuntimeError("MySQL database not available")

    return db.get_connection(), 'mysql'


def return_db_connection(conn, discard: bool = False):
    """
    Return a database connection to the pool.

    Args:
        conn: The connection to return
        discard: If True, discard the connection instead of reusing it
    """
    if db:
        db.return_connection(conn, discard=discard)


def db_execute(conn, db_type, sql, params=None):
    """
    Execute SQL on MySQL database.

    Uses %s placeholders. Automatically converts ? to %s for compatibility.
    """
    # Convert ? placeholders to MySQL %s for compatibility
    sql = sql.replace('?', '%s')

    cursor = conn.cursor()
    if params:
        cursor.execute(sql, params)
    else:
        cursor.execute(sql)
    return cursor


# === AUDIT LOGGER ===
try:
    from audit_logger import get_audit_logger
    audit_logger = get_audit_logger()
    AUDIT_LOGGING_ENABLED = True
    print(f"✅ Audit logging enabled")
except Exception as e:
    print(f"⚠️ Audit logger not available: {e}")
    AUDIT_LOGGING_ENABLED = False
    audit_logger = None

# === R2 STORAGE ===
try:
    from r2_service import upload_to_r2, get_public_url, r2_status, R2_ENABLED
    if R2_ENABLED:
        print(f"✅ R2 storage enabled")
    else:
        print(f"ℹ️  R2 storage not configured (missing credentials)")
except Exception as e:
    print(f"⚠️ R2 service not available: {e}")
    R2_ENABLED = False
    upload_to_r2 = None

# === AI MODULES ===
try:
    from orchestrator import (
        find_best_receipt_for_transaction,
        ai_generate_note,
        ai_generate_report_block,
    )
    from ai_receipt_locator import vision_extract
    ORCHESTRATOR_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Orchestrator not available: {e}")
    ORCHESTRATOR_AVAILABLE = False

try:
    from contacts_engine import (
        merchant_hint_for_row,
        guess_attendees_for_row,
    )
    CONTACTS_ENGINE_AVAILABLE = True
except Exception as e:
    print(f"⚠️ Contacts engine not available: {e}")
    CONTACTS_ENGINE_AVAILABLE = False

# === SMART NOTES ENGINE (Calendar + iMessage + Contacts) ===
try:
    from smart_notes_engine import generate_smart_note, generate_notes_for_transactions
    SMART_NOTES_AVAILABLE = True
    print(f"✅ Smart notes engine loaded")
except Exception as e:
    print(f"⚠️ Smart notes engine not available: {e}")
    SMART_NOTES_AVAILABLE = False
    generate_smart_note = None
    generate_notes_for_transactions = None

# === APPLE RECEIPT SPLITTER ===
try:
    from apple_receipt_splitter import (
        split_apple_receipt,
        auto_split_transaction,
        find_apple_transactions_to_split,
        process_all_apple_splits
    )
    APPLE_SPLITTER_AVAILABLE = True
    print(f"✅ Apple receipt splitter loaded")
except Exception as e:
    print(f"⚠️ Apple receipt splitter not available: {e}")
    APPLE_SPLITTER_AVAILABLE = False
    split_apple_receipt = None
    auto_split_transaction = None


def is_apple_receipt(merchant: str) -> bool:
    """Check if a merchant name indicates an Apple receipt that might need splitting."""
    if not merchant:
        return False
    merchant_lower = merchant.lower()
    apple_indicators = [
        'apple.com/bill',
        'apple.com bill',
        'applecombill',
        'itunes',
        'app store',
        'apple store',
    ]
    return any(ind in merchant_lower for ind in apple_indicators)


def maybe_auto_split_apple_receipt(transaction_id: int, merchant: str, receipt_path: str = None):
    """
    Check if a transaction is an Apple receipt and auto-split if needed.
    Called after any transaction is created/accepted.

    Returns dict with split info if split was performed, None otherwise.
    """
    if not APPLE_SPLITTER_AVAILABLE:
        return None

    if not is_apple_receipt(merchant):
        return None

    if not receipt_path:
        return None

    try:
        print(f"   🍎 Detected Apple receipt - analyzing for auto-split...")
        result = auto_split_transaction(transaction_id, receipt_path)

        if result and result.get('split_transactions'):
            num_splits = len(result['split_transactions'])
            print(f"   ✅ Auto-split into {num_splits} transactions")
            return result
        elif result and result.get('error'):
            print(f"   ⚠️  Apple split skipped: {result['error']}")
        else:
            print(f"   ℹ️  No split needed (single item receipt)")

        return result
    except Exception as e:
        print(f"   ⚠️  Apple auto-split error: {e}")
        return None


# === CONTACT MANAGEMENT SYSTEM ===
try:
    from contact_management import (
        get_contact_manager,
        search_contacts,
        find_attendees_for_expense,
        get_contact_stats
    )
    CONTACT_MANAGER_AVAILABLE = True
    print(f"✅ Contact management system loaded")
except Exception as e:
    print(f"⚠️ Contact management not available: {e}")
    CONTACT_MANAGER_AVAILABLE = False
    get_contact_manager = None
    search_contacts = None
    find_attendees_for_expense = None
    get_contact_stats = None

# === APPLE CONTACTS SYNC ===
try:
    from apple_contacts_sync import (
        sync_apple_contacts,
        get_apple_contacts_stats,
        search_apple_contacts
    )
    APPLE_CONTACTS_AVAILABLE = True
    print(f"✅ Apple Contacts sync loaded")
except Exception as e:
    print(f"⚠️ Apple Contacts sync not available: {e}")
    APPLE_CONTACTS_AVAILABLE = False
    sync_apple_contacts = None
    get_apple_contacts_stats = None
    search_apple_contacts = None

# === ATLAS RELATIONSHIP INTELLIGENCE ===
try:
    from relationship_intelligence import (
        AtlasService,
        iMessageReader,
        InteractionTracker,
        CommitmentTracker,
        RelationshipHealthAnalyzer,
        MeetingPrepGenerator,
        NudgeEngine,
        GmailReader,
        GooglePeopleAPI,
        GMAIL_ACCOUNTS
    )
    ATLAS_AVAILABLE = True
    print(f"✅ ATLAS Relationship Intelligence loaded (Gmail: {len(GMAIL_ACCOUNTS)} accounts)")
except Exception as e:
    print(f"⚠️ ATLAS not available: {e}")
    ATLAS_AVAILABLE = False
    AtlasService = None
    GmailReader = None
    GooglePeopleAPI = None
    GMAIL_ACCOUNTS = []

# === CONTACT SYNC ENGINE ===
try:
    from contact_sync_engine import (
        UniversalSyncEngine,
        AppleContactsAdapter,
        GoogleContactsAdapter,
        LinkedInAdapter,
        SyncDirection,
        SyncResult
    )
    CONTACT_SYNC_AVAILABLE = True
    print("✅ Contact Sync Engine loaded")
except Exception as e:
    print(f"⚠️ Contact Sync Engine not available: {e}")
    CONTACT_SYNC_AVAILABLE = False
    UniversalSyncEngine = None
    AppleContactsAdapter = None

# =============================================================================
# PATHS / GLOBALS
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent
RECEIPT_DIR = BASE_DIR / "receipts"
TRASH_DIR = BASE_DIR / "receipts_trash"

# =============================================================================
# FILE UPLOAD SECURITY
# =============================================================================
ALLOWED_UPLOAD_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.heic', '.pdf', '.tiff', '.webp', '.bmp'}
ALLOWED_MAGIC_BYTES = {
    b'\xff\xd8\xff': 'jpeg',
    b'\x89PNG': 'png',
    b'GIF87a': 'gif',
    b'GIF89a': 'gif',
    b'%PDF': 'pdf',
    b'II*\x00': 'tiff',
    b'MM\x00*': 'tiff',
    b'BM': 'bmp',
}

def validate_upload_file(file) -> tuple:
    """
    Validate uploaded file type by extension and magic bytes.
    Returns (is_valid, error_message).
    """
    if not file or not file.filename:
        return False, "No file provided"

    # Check extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        return False, f"File type '{ext}' not allowed"

    # Check magic bytes
    file.seek(0)
    header = file.read(16)
    file.seek(0)

    if not header:
        return False, "Empty file"

    # HEIC/HEIF files have 'ftyp' signature at offset 4
    if len(header) >= 12 and header[4:8] == b'ftyp':
        heic_types = [b'heic', b'heix', b'hevc', b'hevx', b'mif1']
        if header[8:12] in heic_types:
            return True, None

    # Check common magic bytes
    for magic, _ in ALLOWED_MAGIC_BYTES.items():
        if header.startswith(magic):
            return True, None

    # WebP check
    if header[:4] == b'RIFF' and len(header) >= 12 and header[8:12] == b'WEBP':
        return True, None

    return False, "File content does not match expected format"

app = Flask(__name__)

# Configure app to trust Railway proxy headers (for HTTPS detection)
if os.environ.get('RAILWAY_ENVIRONMENT'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Add structured request logging
flask_request_logger(app)
logger.info("Flask application initialized")

# Set up API monitoring
try:
    from monitoring import setup_flask_monitoring, get_monitor
    setup_flask_monitoring(app)
    api_monitor = get_monitor()
    logger.info("API monitoring enabled")
except Exception as e:
    logger.warning(f"API monitoring not available: {e}")
    api_monitor = None

# =============================================================================
# AUTOMATIC INBOX SCANNING SCHEDULER
# =============================================================================
scheduler = None
try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.interval import IntervalTrigger
    import atexit

    def scheduled_inbox_scan():
        """Background job to scan Gmail for new receipts every 4 hours."""
        print(f"\n⏰ [{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Running scheduled inbox scan...")
        try:
            from incoming_receipts_service import scan_gmail_for_new_receipts, save_incoming_receipt

            accounts = [
                'kaplan.brian@gmail.com',
                'brian@downhome.com',
                'brian@musiccityrodeo.com'
            ]

            # Only scan last 7 days for new receipts (not all history)
            from datetime import timedelta
            since_date = (datetime.now() - timedelta(days=7)).strftime('%Y-%m-%d')

            total_new = 0
            for account in accounts:
                try:
                    receipts = scan_gmail_for_new_receipts(account, since_date)
                    for receipt in receipts:
                        if save_incoming_receipt(receipt):
                            total_new += 1
                except Exception as acc_error:
                    print(f"   ❌ Error scanning {account}: {acc_error}")

            print(f"   ✅ Scheduled scan complete: {total_new} new receipts added")

            # Auto-match if we found new receipts
            if total_new > 0:
                try:
                    from smart_auto_matcher import auto_match_pending_receipts
                    auto_match_pending_receipts()
                    print(f"   ✅ Auto-matching complete")
                except Exception as match_error:
                    print(f"   ⚠️ Auto-match failed: {match_error}")

        except Exception as e:
            print(f"   ❌ Scheduled scan error: {e}")

    # Only start scheduler in production (Railway) to avoid multiple instances during dev
    if os.environ.get('RAILWAY_ENVIRONMENT'):
        scheduler = BackgroundScheduler()
        # Run every 4 hours
        scheduler.add_job(
            func=scheduled_inbox_scan,
            trigger=IntervalTrigger(hours=4),
            id='inbox_scan_job',
            name='Scan Gmail for new receipts',
            replace_existing=True
        )
        scheduler.start()
        print("✅ Background inbox scanner started (runs every 4 hours)")

        # Shut down scheduler when app exits
        atexit.register(lambda: scheduler.shutdown() if scheduler else None)
    else:
        print("ℹ️  Background scheduler disabled in development mode")

except ImportError as e:
    print(f"⚠️ APScheduler not available - automatic inbox scanning disabled: {e}")
except Exception as e:
    print(f"⚠️ Failed to initialize scheduler: {e}")

# =============================================================================
# AUTHENTICATION SETUP
# =============================================================================
from auth import (
    login_required, api_key_required, is_authenticated,
    verify_password, verify_pin, SECRET_KEY, SESSION_TIMEOUT,
    LOGIN_PAGE_HTML, PIN_PAGE_HTML, AUTH_PIN
)
from flask import session, redirect, url_for, render_template_string

app.secret_key = SECRET_KEY
# Only require HTTPS cookies in production (Railway sets RAILWAY_ENVIRONMENT)
app.config['SESSION_COOKIE_SECURE'] = bool(os.environ.get('RAILWAY_ENVIRONMENT'))
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['PERMANENT_SESSION_LIFETIME'] = SESSION_TIMEOUT
# File upload size limit: 50MB (protects against DoS)
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024

# =============================================================================
# CSRF PROTECTION
# =============================================================================
csrf = None
if CSRF_AVAILABLE:
    # Configure CSRF
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['WTF_CSRF_TIME_LIMIT'] = 3600  # 1 hour token validity
    app.config['WTF_CSRF_SSL_STRICT'] = bool(os.environ.get('RAILWAY_ENVIRONMENT'))

    csrf = CSRFProtect(app)

    # Exempt API endpoints that use API key authentication (they don't use sessions)
    # These are already protected by api_key_required decorator
    CSRF_EXEMPT_ENDPOINTS = [
        'api_status',
        'api_incoming_sync',
        'api_gmail_sync',
        'api_webhook',
    ]

    @csrf.exempt
    @app.route('/api/csrf-token', methods=['GET'])
    def get_csrf_token():
        """Get a CSRF token for AJAX requests."""
        return jsonify({'csrf_token': generate_csrf()})

    # Add CSRF token to all responses as a header for JavaScript access
    @app.after_request
    def add_csrf_header(response):
        """Add CSRF token to response headers for JavaScript."""
        if 'text/html' in response.content_type:
            # For HTML responses, JavaScript can read from meta tag or this header
            response.headers['X-CSRF-Token'] = generate_csrf()
        return response

    # Context processor for templates
    @app.context_processor
    def csrf_context_processor():
        """Make CSRF token available in all templates."""
        return {'csrf_token': generate_csrf}

    print("✅ CSRF protection enabled")
else:
    print("⚠️ CSRF protection disabled (Flask-WTF not available)")

# Helper function for CSRF-exempt API routes
def csrf_exempt_route(f):
    """Decorator to mark a route as CSRF exempt."""
    if csrf:
        return csrf.exempt(f)
    return f


# =============================================================================
# DATABASE CONNECTION CLEANUP (CRITICAL FOR STABILITY)
# =============================================================================

@app.teardown_appcontext
def cleanup_db_connection(exception=None):
    """
    Auto-return any database connection left on this request.
    This prevents connection leaks when exceptions occur or code forgets to return.
    """
    db_conn = g.pop('db_connection', None)
    if db_conn is not None:
        try:
            if exception:
                # Discard connection if there was an error
                return_db_connection(db_conn, discard=True)
            else:
                return_db_connection(db_conn)
        except Exception as e:
            logger.warning(f"Error returning connection in teardown: {e}")


def get_request_db_connection():
    """
    Get a database connection for the current request.
    The connection will be automatically returned at the end of the request.

    Usage:
        conn = get_request_db_connection()
        # use conn...
        # No need to return - handled by teardown_appcontext
    """
    if 'db_connection' not in g:
        g.db_connection, _ = get_db_connection()
    return g.db_connection


# =============================================================================
# POOL HEALTH MONITORING ENDPOINT
# =============================================================================

@app.route("/api/health/pool-status")
def api_pool_status():
    """
    Get connection pool health status.
    Critical for monitoring database stability.
    """
    # Allow admin key or authenticated users
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')

    if admin_key not in (expected_key, auth_password):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    try:
        from db_mysql import get_pool_status, get_connection_pool

        status = get_pool_status()

        # Add health assessment
        utilization = status.get('utilization_percent', 0)
        if utilization > 90:
            health = 'critical'
        elif utilization > 70:
            health = 'warning'
        else:
            health = 'healthy'

        status['health'] = health
        status['timestamp'] = datetime.now().isoformat()

        return jsonify({
            'ok': True,
            **status
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e),
            'health': 'unknown'
        }), 500


@app.route("/api/health/pool-reset", methods=["POST"])
def api_pool_reset():
    """
    Reset the connection pool. Use when pool is corrupted.
    Admin only.
    """
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')

    if admin_key != expected_key:
        return jsonify({'error': 'Admin key required'}), 401

    try:
        from db_mysql import get_connection_pool
        pool = get_connection_pool()
        pool.reset_pool()

        return jsonify({
            'ok': True,
            'message': 'Connection pool reset successfully',
            'new_status': pool.status()
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500


@app.route("/api/health/pool-keepalive", methods=["POST"])
def api_pool_keepalive():
    """
    Manually trigger keep-alive ping on all pool connections.
    """
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')

    if admin_key not in (expected_key, auth_password):
        return jsonify({'error': 'Authentication required'}), 401

    try:
        from db_mysql import get_connection_pool
        pool = get_connection_pool()
        refreshed = pool.keep_alive()

        return jsonify({
            'ok': True,
            'connections_refreshed': refreshed,
            'status': pool.status()
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500


# =============================================================================
# PERIODIC BACKGROUND SYNC
# =============================================================================

@app.before_request
def periodic_interaction_sync():
    """Check if interaction sync is needed on each request (rate limited to hourly)"""
    # Only check on specific endpoints to avoid overhead
    from flask import request
    sync_endpoints = (
        'contact_hub_page',           # Main contacts page
        'api_atlas_contacts_list',    # Contacts API
        'api_contact_hub_list',       # Contact hub API
        'api_atlas_frequency_stats',  # Frequency stats endpoint
    )
    if request.endpoint in sync_endpoints:
        try:
            # Import here to avoid circular dependency at module level
            if 'trigger_sync_if_needed' in globals():
                trigger_sync_if_needed()
        except Exception:
            pass  # Non-critical, don't block request


# =============================================================================
# CENTRALIZED ERROR HANDLERS
# =============================================================================

@app.errorhandler(400)
def bad_request_error(error):
    """Handle 400 Bad Request errors"""
    message = str(error.description) if hasattr(error, 'description') else 'Bad request'
    return jsonify({
        'ok': False,
        'error': 'Bad Request',
        'message': message,
        'status': 400
    }), 400


@app.errorhandler(401)
def unauthorized_error(error):
    """Handle 401 Unauthorized errors"""
    return jsonify({
        'ok': False,
        'error': 'Unauthorized',
        'message': 'Authentication required',
        'status': 401
    }), 401


@app.errorhandler(403)
def forbidden_error(error):
    """Handle 403 Forbidden errors"""
    return jsonify({
        'ok': False,
        'error': 'Forbidden',
        'message': 'Access denied',
        'status': 403
    }), 403


@app.errorhandler(404)
def not_found_error(error):
    """Handle 404 Not Found errors"""
    message = str(error.description) if hasattr(error, 'description') else 'Resource not found'
    return jsonify({
        'ok': False,
        'error': 'Not Found',
        'message': message,
        'status': 404
    }), 404


@app.errorhandler(500)
def internal_error(error):
    """Handle 500 Internal Server errors"""
    # Log the actual error for debugging
    print(f"❌ Internal Server Error: {error}", flush=True)
    return jsonify({
        'ok': False,
        'error': 'Internal Server Error',
        'message': 'An unexpected error occurred. Please try again.',
        'status': 500
    }), 500


@app.errorhandler(503)
def service_unavailable_error(error):
    """Handle 503 Service Unavailable errors"""
    message = str(error.description) if hasattr(error, 'description') else 'Service temporarily unavailable'
    return jsonify({
        'ok': False,
        'error': 'Service Unavailable',
        'message': message,
        'status': 503
    }), 503


# Generic exception handler for uncaught exceptions
@app.errorhandler(Exception)
def handle_exception(error):
    """Handle all uncaught exceptions"""
    # Log the full traceback
    import traceback
    print(f"❌ Unhandled Exception: {error}", flush=True)
    traceback.print_exc()

    # Return a generic error response
    return jsonify({
        'ok': False,
        'error': 'Server Error',
        'message': str(error) if app.debug else 'An unexpected error occurred',
        'status': 500
    }), 500


df: pd.DataFrame | None = None          # global dataframe
receipt_meta_cache: dict[str, dict] = {}  # filename -> meta dict


# =============================================================================
# ENV / OPENAI
# =============================================================================

def require_env(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return v


# Make OPENAI_API_KEY optional - app will start but AI features won't work
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = None
if OPENAI_API_KEY:
    client = OpenAI(api_key=OPENAI_API_KEY)
else:
    print("WARNING: OPENAI_API_KEY not set - AI features will be disabled")


# =============================================================================
# SANITIZERS / HELPERS
# =============================================================================

def sanitize_value(val):
    """
    Make a single cell safe for CSV / JSON:
    - Remove NaN / inf -> empty string
    - Strip CR/LF so viewer JSON doesn't break
    """
    if isinstance(val, float):
        if math.isnan(val) or math.isinf(val):
            return ""
    if isinstance(val, str):
        v = val.replace("\r", " ").replace("\n", " ")
        return v
    if pd.isna(val):
        return ""
    v = str(val)
    v = v.replace("\r", " ").replace("\n", " ")
    return v


def sanitize_csv(df_in: pd.DataFrame) -> pd.DataFrame:
    """
    Sanitize all columns EXCEPT _index (which must stay numeric).
    """
    df_local = df_in.copy()
    for col in df_local.columns:
        if col == "_index":
            continue
        df_local[col] = df_local[col].apply(sanitize_value)
    return df_local


def safe_json(data):
    """
    Recursively walk a structure and replace NaN/inf with None so
    Flask/json doesn't emit invalid JS tokens.
    """
    def clean(v):
        if isinstance(v, float):
            if math.isnan(v) or math.isinf(v):
                return None
            return v
        elif isinstance(v, dict):
            return {k: clean(v2) for k, v2 in v.items()}
        elif isinstance(v, list):
            return [clean(x) for x in v]
        return v
    return clean(data)


def parse_amount_str(val) -> float:
    """Parse an amount from CSV-style strings like '$123.45' or '-1,234.56'."""
    if val is None:
        return 0.0
    s = str(val)
    if not s.strip():
        return 0.0
    cleaned = "".join(ch for ch in s if ch.isdigit() or ch in ".-")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def norm_text_for_match(s: str | None) -> str:
    """Lowercase alnum-ish representation for fuzzy merchant matching."""
    if not s:
        return ""
    s = s.lower()
    kept: list[str] = []
    for ch in s:
        if ch.isalnum():
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
    return " ".join("".join(kept).split())


def parse_date_fuzzy(s: str | None) -> date | None:
    if not s:
        return None
    s = s.strip()
    if not s:
        return None
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y/%m/%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        d = pd.to_datetime(s, errors="coerce")
        if pd.isna(d):
            return None
        return d.date()
    except Exception:
        return None


def parse_email_date(date_str: str) -> str:
    """
    Parse RFC 2822 email date headers to YYYY-MM-DD format.
    Handles formats like:
    - "Wed, 27 Aug 2024 14:35:22 -0400"
    - "27 Aug 2024 10:00:00"
    - "Wed, 27 Aug" (truncated - try to infer year using day-of-week)
    - "Tue, 28 Oc" (severely truncated month)
    - Already formatted dates like "2024-08-27"

    Uses day-of-week matching to infer the correct year when missing.

    Returns: YYYY-MM-DD string or empty string if parsing fails
    """
    if not date_str:
        return ''

    date_str = str(date_str).strip()
    if not date_str:
        return ''

    # If already in YYYY-MM-DD format, return as-is
    if len(date_str) >= 10 and date_str[4] == '-' and date_str[7] == '-':
        return date_str[:10]

    import email.utils
    from datetime import datetime, date, timedelta
    import calendar
    import re

    try:
        # Try standard email date parsing first
        parsed = email.utils.parsedate_to_datetime(date_str)
        return parsed.strftime('%Y-%m-%d')
    except:
        pass

    # Build month_map to support 2-4 character prefixes
    month_map = {}
    for prefix, month_num in [
        ('ja', 1), ('jan', 1),
        ('fe', 2), ('feb', 2),
        ('ma', 3), ('mar', 3),
        ('ap', 4), ('apr', 4),
        ('may', 5),
        ('ju', 6), ('jun', 6),
        ('jul', 7),
        ('au', 8), ('aug', 8),
        ('se', 9), ('sep', 9),
        ('oc', 10), ('oct', 10),
        ('no', 11), ('nov', 11),
        ('de', 12), ('dec', 12)
    ]:
        month_map[prefix] = month_num

    # Day of week map
    dow_map = {
        'mon': 0, 'tue': 1, 'wed': 2, 'thu': 3, 'fri': 4, 'sat': 5, 'sun': 6
    }

    try:
        # Extract day of week if present (e.g., "Wed, 27 Aug")
        dow_match = re.match(r'^([a-zA-Z]{3}),?\s*', date_str)
        target_dow = None
        if dow_match:
            dow_str = dow_match.group(1).lower()
            target_dow = dow_map.get(dow_str)

        # Pattern: day month year - month can be 2+ chars (for truncated names like "Au", "Oc", "Se")
        match = re.search(r'(\d{1,2})\s+([a-zA-Z]{2,})\s*(\d{2,4})?', date_str)
        if match:
            day = int(match.group(1))
            month_str = match.group(2).lower()
            year_str = match.group(3)

            # Try to find month - check exact match first, then try prefixes
            month = month_map.get(month_str)
            if not month:
                month = month_map.get(month_str[:3])
            if not month:
                month = month_map.get(month_str[:2])

            if month:
                now = datetime.now()

                if year_str:
                    year = int(year_str)
                    if year < 100:
                        year += 2000
                    elif year < 1000:
                        year = int(str(year) + '4')
                else:
                    # No year - try to find the right year using day-of-week
                    # Check years from current back to 2 years ago
                    year = None

                    if target_dow is not None:
                        # Use day-of-week to find correct year
                        for candidate_year in range(now.year, now.year - 3, -1):
                            try:
                                test_date = date(candidate_year, month, day)
                                if test_date.weekday() == target_dow:
                                    # Day of week matches!
                                    # Prefer dates in the past
                                    if test_date <= now.date():
                                        year = candidate_year
                                        break
                            except ValueError:
                                # Invalid date (e.g., Feb 30)
                                continue

                    # If no match found or no day-of-week, use simple logic
                    if year is None:
                        year = now.year
                        # If the month is after current month, assume previous year
                        if month > now.month:
                            year -= 1
                        # If same month but day is after today, also previous year
                        elif month == now.month and day > now.day:
                            year -= 1

                return f"{year:04d}-{month:02d}-{day:02d}"
    except:
        pass

    # Try pandas as final fallback
    try:
        d = pd.to_datetime(date_str, errors="coerce")
        if not pd.isna(d):
            return d.strftime('%Y-%m-%d')
    except:
        pass

    return ''


def gpt4_vision_extract(receipt_path):
    """
    Extract receipt data using Llama 3.2 Vision via Ollama.
    FREE, LOCAL, and accurate for receipts.

    Returns: dict with merchant_name, receipt_date, total_amount, etc.
    """
    import requests

    try:
        # Read and encode image
        with open(receipt_path, 'rb') as f:
            image_data = base64.b64encode(f.read()).decode('utf-8')

        # Call Ollama with Llama Vision
        prompt = """Extract from this receipt:
1. Merchant name - THE COMPANY PROVIDING THE SERVICE (e.g., "Uber", "Lyft", "DoorDash", "Starbucks")
   - NOT the customer/passenger name
   - NOT the driver name
   - NOT the address
   - NOT the location
2. Total amount (the final charge, NOT mileage or subtotals or partial amounts)
3. Date (YYYY-MM-DD format)

Return ONLY JSON: {"merchant": "...", "total": 0.00, "date": "YYYY-MM-DD"}

IMPORTANT:
- For Uber/Lyft receipts: merchant is "Uber" or "Lyft", NOT the passenger name
- For DoorDash: merchant is "DoorDash", NOT the restaurant name
- The total is the FINAL AMOUNT CHARGED, not subtotals or tips alone"""

        response = requests.post(
            'http://localhost:11434/api/generate',
            json={
                'model': 'llama3.2-vision',
                'prompt': prompt,
                'images': [image_data],
                'stream': False,
                'options': {'temperature': 0.1}
            },
            timeout=120
        )

        if response.status_code == 200:
            result_text = response.json().get('response', '')
            print(f"   📝 Llama Vision raw: {result_text[:200]}")

            # Parse JSON from response
            import re
            json_match = re.search(r'\{[^}]+\}', result_text)
            if json_match:
                data = json.loads(json_match.group())
                merchant = data.get('merchant', '')
                total = float(data.get('total', 0) or 0)
                date_str = data.get('date', '')

                result = {
                    'merchant_name': merchant,
                    'receipt_date': date_str,
                    'total_amount': total,
                    'subtotal_amount': 0.0,
                    'tip_amount': 0.0,
                }

                print(f"   ✅ Llama Vision: {merchant} | ${total:.2f} | {date_str}")
                return result

        print(f"   ⚠️ Llama Vision failed: {response.status_code}")
        return None

    except Exception as e:
        print(f"   ❌ Llama Vision error: {e}")
        return None


def normalize_merchant_name(s: str | None) -> str:
    """
    Normalize merchant names using advanced merchant intelligence system.

    NOW USING: merchant_intelligence.py for perfect normalization
    - Handles 30+ merchant patterns (chains, digital services, parking, etc.)
    - Smart URL/domain extraction: "APPLE.COM/BILL" → "apple"
    - Chain awareness: "SH NASHVILLE" → "soho house"
    - Location removal, confirmation code filtering, etc.
    """
    if not s:
        return ""

    # Use merchant intelligence if available
    if merchant_intel:
        return merchant_intel.normalize(s)

    # Fallback to simple normalization if merchant_intel not loaded
    raw = s.strip()
    low = raw.lower()

    # Soho House / SH Nashville cluster (legacy fallback)
    if any(x in low for x in ["sh nashville", "soho house", "shnash", "sh house", "sh nash"]):
        return "soho house"

    # Anthropic / Claude cluster (legacy fallback)
    if any(x in low for x in ["anthropic", "claude", "anthropic ai"]):
        return "anthropic"

    # Generic cleaning
    low_norm = norm_text_for_match(low)
    return low_norm


# =============================================================================
# DATABASE LOAD (MySQL-only) WITH CACHING
# =============================================================================

# Cache configuration
DF_CACHE_TTL_SECONDS = 300  # 5 minutes TTL for DataFrame cache
_df_cache_timestamp = None  # When the cache was last loaded
import time as _time_module  # For cache timestamp

def load_data(force_refresh=False):
    """Load all transactions from MySQL database with optional caching.

    Args:
        force_refresh: If True, bypass cache and reload from database
    """
    global df, _df_cache_timestamp

    if not db:
        raise RuntimeError("MySQL database not available")

    # Check if cache is still valid
    current_time = _time_module.time()
    if not force_refresh and df is not None and _df_cache_timestamp:
        cache_age = current_time - _df_cache_timestamp
        if cache_age < DF_CACHE_TTL_SECONDS:
            # Cache is still valid, return existing df
            return df

    try:
        start_time = _time_module.time()
        df = db.get_all_transactions()
        # Ensure _index is integer for proper comparisons
        if '_index' in df.columns:
            df['_index'] = pd.to_numeric(df['_index'], errors='coerce').fillna(0).astype(int)

        load_time = _time_module.time() - start_time
        _df_cache_timestamp = current_time
        print(f"✅ Loaded {len(df)} transactions from MySQL in {load_time:.2f}s (cached for {DF_CACHE_TTL_SECONDS}s)")
        return df
    except Exception as e:
        print(f"❌ MySQL load failed: {e}")
        raise


def invalidate_cache():
    """Force cache invalidation on next request."""
    global _df_cache_timestamp
    _df_cache_timestamp = None


# Legacy alias for backward compatibility
def load_csv():
    """Legacy alias for load_data() - now loads from MySQL only."""
    return load_data()


def save_data():
    """Data is saved directly to MySQL via update_transaction. This is a no-op for compatibility."""
    # All saves happen via db.update_transaction() in update_row_by_index()
    # This function exists only for backward compatibility
    pass


# Legacy alias for backward compatibility
def save_csv():
    """Legacy alias for save_data() - now a no-op since MySQL saves happen per-row."""
    save_data()


def ensure_df(force_refresh=False):
    """Lazy loader used by all routes. Respects cache TTL.

    Args:
        force_refresh: If True, bypass cache and reload from database
    """
    global df
    if df is None or force_refresh:
        load_data(force_refresh=force_refresh)
    return df


# =============================================================================
# ROW HELPERS
# =============================================================================

def get_row_by_index(idx: int) -> dict | None:
    """Return a row dict by _index from the global df."""
    global df
    ensure_df()
    mask = df["_index"] == idx
    if not mask.any():
        return None
    row_series = df.loc[mask].iloc[0]
    return row_series.to_dict()


def update_row_by_index(idx: int, patch: dict, source: str = "viewer_ui") -> bool:
    """
    Apply patch to df row with given _index, then save to MySQL.

    This function:
    1. Saves changes to MySQL IMMEDIATELY using db.update_transaction()
    2. Logs all changes to audit log for tracking
    3. Updates in-memory DataFrame

    Args:
        idx: Transaction _index to update
        patch: Dict of column -> value changes
        source: Source of the update (e.g., "viewer_ui", "auto_match", "gmail_search")

    Returns:
        True if update successful, False otherwise
    """
    global df
    ensure_df()

    # Verify row exists
    mask = df["_index"] == idx
    if not mask.any():
        print(f"⚠️  Row #{idx} not found", flush=True)
        return False

    # Get old values for audit logging
    old_row = df.loc[mask].iloc[0].to_dict()

    # === DELETION PROTECTION: Mark receipts as deleted when removed ===
    # If user is clearing/removing a receipt, mark it as deleted_by_user=1
    # This prevents auto-recovery scripts from re-uploading it
    if "Receipt File" in patch or "receipt_file" in patch:
        receipt_field = "Receipt File" if "Receipt File" in patch else "receipt_file"
        new_receipt = patch.get(receipt_field, "")
        old_receipt = old_row.get(receipt_field, "")

        # If clearing an existing receipt (had value, now empty)
        if old_receipt and not new_receipt and source == "viewer_ui":
            print(f"🗑️  User deleted receipt - marking as deleted_by_user", flush=True)
            patch["deleted_by_user"] = 1
            # Also clear review_status - no receipt means nothing to review
            patch["review_status"] = None
            print(f"   Cleared review_status (no receipt to review)", flush=True)

    # === STEP 1: Update MySQL ===
    if not db:
        print(f"❌ MySQL not available", flush=True)
        return False

    try:
        success = db.update_transaction(idx, patch)
        if not success:
            print(f"❌ MySQL update failed for row #{idx}", flush=True)
            return False
        print(f"💾 MySQL updated: row #{idx}", flush=True)
    except Exception as e:
        print(f"❌ MySQL error for row #{idx}: {e}", flush=True)
        return False

    # === STEP 2: Log changes to audit log ===
    if AUDIT_LOGGING_ENABLED and audit_logger:
        try:
            for field_name, new_value in patch.items():
                old_value = old_row.get(field_name, "")

                # Skip if no change
                if str(old_value) == str(new_value):
                    continue

                # Determine action type
                if field_name == "Receipt File":
                    if not old_value and new_value:
                        action_type = "attach_receipt"
                    elif old_value and new_value:
                        action_type = "replace_receipt"
                    elif old_value and not new_value:
                        action_type = "detach_receipt"
                    else:
                        action_type = "update_field"

                    # Special handling for receipt attachments
                    confidence = patch.get("AI Confidence", 0)
                    audit_logger.log_receipt_attach(
                        transaction_index=idx,
                        old_receipt=old_value or None,
                        new_receipt=new_value,
                        confidence=confidence,
                        source=source
                    )

                    # ✅ AUTO-MARK AS GOOD: If AI confidence >= 85%, automatically mark as good
                    if action_type == "attach_receipt" and confidence >= 85:
                        patch["review_status"] = "good"
                        print(f"✨ Auto-marked as GOOD (confidence: {confidence}%)", flush=True)
                else:
                    # Regular field update
                    audit_logger.log_change(
                        transaction_index=idx,
                        action_type="update_field",
                        field_name=field_name,
                        old_value=old_value,
                        new_value=new_value,
                        source=source
                    )
        except Exception as e:
            print(f"⚠️  Audit logging failed: {e}", flush=True)
            # Don't fail the update if audit logging fails

    # === STEP 3: Update in-memory DataFrame ===
    for col, value in patch.items():
        if col not in df.columns:
            df[col] = ""
        if col != "_index":
            value = sanitize_value(value)
        df.loc[mask, col] = value

    return True


# =============================================================================
# RECEIPT META CACHE (MySQL-backed)
# =============================================================================

def load_receipt_meta():
    """Load receipt metadata from MySQL receipt_metadata table."""
    global receipt_meta_cache
    receipt_meta_cache = {}

    if not db:
        print("ℹ️ No MySQL database for receipt metadata")
        return

    try:
        result = db.execute_query("SELECT * FROM receipt_metadata")
        for row in result:
            filename = row.get("filename", "")
            if filename:
                receipt_meta_cache[filename] = {
                    "filename": filename,
                    "merchant_name": row.get("merchant", ""),
                    "merchant_normalized": row.get("merchant", ""),
                    "receipt_date": str(row.get("date", "")),
                    "total_amount": float(row.get("amount", 0) or 0),
                    "subtotal_amount": 0.0,
                    "tip_amount": 0.0,
                    "raw_json": row.get("raw_text", ""),
                }
        print(f"📑 Loaded receipt metadata for {len(receipt_meta_cache)} files from MySQL")
    except Exception as e:
        print(f"⚠️ Could not load receipt metadata: {e}")


def save_receipt_meta():
    """Save receipt metadata to MySQL receipt_metadata table with full OCR data."""
    global receipt_meta_cache
    if not receipt_meta_cache or not db:
        return

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        for filename, meta in receipt_meta_cache.items():
            # Get OCR-specific fields if present
            line_items = meta.get("line_items", [])
            if isinstance(line_items, list):
                line_items_json = json.dumps(line_items)
            else:
                line_items_json = line_items if line_items else "[]"

            raw_response = meta.get("raw_response", meta.get("raw_json", ""))
            if isinstance(raw_response, dict):
                raw_response_json = json.dumps(raw_response)
            else:
                raw_response_json = raw_response if raw_response else "{}"

            cursor.execute("""
                INSERT INTO receipt_metadata (
                    filename, merchant, date, amount, raw_text,
                    ocr_merchant, ocr_amount, ocr_date, ocr_subtotal, ocr_tax, ocr_tip,
                    ocr_receipt_number, ocr_payment_method, ocr_line_items,
                    ocr_confidence, ocr_method, ocr_extracted_at, ocr_raw_response
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    merchant = VALUES(merchant),
                    date = VALUES(date),
                    amount = VALUES(amount),
                    raw_text = VALUES(raw_text),
                    ocr_merchant = VALUES(ocr_merchant),
                    ocr_amount = VALUES(ocr_amount),
                    ocr_date = VALUES(ocr_date),
                    ocr_subtotal = VALUES(ocr_subtotal),
                    ocr_tax = VALUES(ocr_tax),
                    ocr_tip = VALUES(ocr_tip),
                    ocr_receipt_number = VALUES(ocr_receipt_number),
                    ocr_payment_method = VALUES(ocr_payment_method),
                    ocr_line_items = VALUES(ocr_line_items),
                    ocr_confidence = VALUES(ocr_confidence),
                    ocr_method = VALUES(ocr_method),
                    ocr_extracted_at = COALESCE(ocr_extracted_at, VALUES(ocr_extracted_at)),
                    ocr_raw_response = VALUES(ocr_raw_response)
            """, (
                filename,
                meta.get("merchant_name", "") or meta.get("supplier_name", ""),
                meta.get("receipt_date", None) or meta.get("date", None),
                meta.get("total_amount", 0),
                meta.get("raw_json", ""),
                # OCR-specific fields
                meta.get("supplier_name", "") or meta.get("merchant_name", ""),
                meta.get("total_amount"),
                meta.get("date") or meta.get("receipt_date"),
                meta.get("subtotal"),
                meta.get("tax_amount"),
                meta.get("tip_amount"),
                meta.get("receipt_number"),
                meta.get("payment_method"),
                line_items_json,
                meta.get("confidence"),
                meta.get("ocr_method"),
                meta.get("extracted_at") or datetime.now() if meta.get("confidence") else None,
                raw_response_json
            ))

        conn.commit()
        return_db_connection(conn)
        print(f"📑 Saved receipt metadata for {len(receipt_meta_cache)} files to MySQL")
    except Exception as e:
        print(f"⚠️ Could not save receipt metadata: {e}")


def encode_image_base64(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_receipt_with_vision(path: Path) -> dict | None:
    """
    Extract receipt fields using Gemini (primary), Donut (fallback), or GPT-4.1 (final fallback).

    Returns:
      - merchant_name
      - receipt_date (YYYY-MM-DD if possible)
      - subtotal_amount
      - tip_amount
      - total_amount (final charged total, including handwritten tip if present)
      - Full OCR fields (line_items, tax, receipt_number, etc.)
    """
    print(f"👁️  Vision extracting {path}", flush=True)

    # Try Gemini OCR first (FREE with your API keys, best accuracy)
    try:
        from receipt_ocr_service import get_ocr_service
        ocr_service = get_ocr_service()

        if ocr_service and ocr_service.gemini_ready:
            print(f"   🔄 Using Gemini OCR...", flush=True)
            gemini_result = ocr_service.extract(str(path))

            if gemini_result and gemini_result.get("confidence", 0) >= 0.5:
                merchant_name = gemini_result.get("supplier_name", "").strip()
                merchant_norm = normalize_merchant_name(merchant_name)
                receipt_date = gemini_result.get("date", "").strip() if gemini_result.get("date") else ""
                subtotal = gemini_result.get("subtotal", 0.0) or 0.0
                tip = gemini_result.get("tip_amount", 0.0) or 0.0
                total = gemini_result.get("total_amount", 0.0) or 0.0
                confidence = gemini_result.get("confidence", 0.0)

                meta = {
                    "filename": path.name,
                    "merchant_name": merchant_name,
                    "merchant_normalized": merchant_norm,
                    "receipt_date": receipt_date,
                    "subtotal_amount": subtotal,
                    "tip_amount": tip,
                    "total_amount": total,
                    "raw_json": json.dumps(gemini_result, ensure_ascii=False, default=str),
                    "ocr_source": gemini_result.get("ocr_method", "gemini"),
                    "confidence_score": confidence,
                    # Full OCR fields for receipt library
                    "supplier_name": merchant_name,
                    "date": receipt_date,
                    "subtotal": subtotal,
                    "tax_amount": gemini_result.get("tax_amount"),
                    "receipt_number": gemini_result.get("receipt_number"),
                    "payment_method": gemini_result.get("payment_method"),
                    "line_items": gemini_result.get("line_items", []),
                    "confidence": confidence,
                    "ocr_method": gemini_result.get("ocr_method", "gemini"),
                    "raw_response": gemini_result,
                }

                print(f"   ✅ Gemini success: {merchant_name} · ${total:.2f} · {receipt_date} (conf: {confidence:.0%})", flush=True)
                return meta
            else:
                print(f"   ⚠️ Gemini low confidence: {gemini_result.get('confidence', 0):.0%}", flush=True)
    except Exception as e:
        print(f"   ⚠️ Gemini error: {e}", flush=True)

    # Try Donut (FREE, FAST, local)
    try:
        from receipt_ocr_local import extract_receipt_fields_local

        print(f"   🔄 Using Donut OCR with validation...", flush=True)
        donut_result = extract_receipt_fields_local(str(path), config={'validate': True})

        if donut_result and donut_result.get("success"):
            merchant_name = (donut_result.get("Receipt Merchant") or "").strip()
            merchant_norm = (donut_result.get("merchant_normalized") or "").strip()
            if not merchant_norm:
                merchant_norm = normalize_merchant_name(merchant_name)

            receipt_date = (donut_result.get("Receipt Date") or "").strip()
            subtotal = donut_result.get("subtotal_amount", 0.0)
            tip = donut_result.get("tip_amount", 0.0)
            total = donut_result.get("Receipt Total", 0.0)
            confidence = donut_result.get("confidence_score", 0.0)

            # Get validation results
            validation = donut_result.get("validation", {})
            validated_confidence = donut_result.get("validated_confidence", confidence)

            meta = {
                "filename": path.name,
                "merchant_name": merchant_name,
                "merchant_normalized": merchant_norm,
                "receipt_date": receipt_date,
                "subtotal_amount": subtotal,
                "tip_amount": tip,
                "total_amount": total,
                "raw_json": json.dumps(donut_result, ensure_ascii=False),
                "ocr_source": donut_result.get("ocr_method", "Donut"),
                "confidence_score": confidence,
                "validated_confidence": validated_confidence,
                "validation_passed": donut_result.get("validation_passed", True),
                "validation_errors": validation.get("errors", []),
                "validation_warnings": validation.get("warnings", []),
                # Full OCR fields
                "supplier_name": merchant_name,
                "date": receipt_date,
                "subtotal": subtotal,
                "tax_amount": donut_result.get("tax_amount"),
                "confidence": confidence,
                "ocr_method": "donut",
            }

            print(f"   ✅ Donut success: {merchant_name} · ${total:.2f} · {receipt_date} (conf: {confidence:.0%})", flush=True)
            return meta
        else:
            print(f"   ⚠️ Donut failed: {donut_result.get('error', 'Unknown')}", flush=True)
    except Exception as e:
        print(f"   ⚠️ Donut error: {e}", flush=True)

    # Fallback to GPT-4.1 Vision
    print(f"   🔄 Falling back to GPT-4.1 Vision...", flush=True)

    try:
        b64 = encode_image_base64(path)
    except Exception as e:
        print(f"⚠️ Could not read image {path}: {e}")
        return None

    prompt = """
You are a world-class receipt parser for Brian Kaplan.

Look at the receipt image and extract:
- merchant_name: the business or venue name (normalized and human-readable)
- receipt_date: date of the transaction in YYYY-MM-DD if you can; else empty string
- subtotal_amount: numeric subtotal before tip, if visible
- tip_amount: numeric tip amount, including handwritten tips, if visible
- total_amount: FINAL charge amount including tip.
  - If the printed receipt shows subtotal + handwritten tip + total, use that total.
  - If only subtotal and handwritten tip are present, compute subtotal + tip.
  - If the receipt only shows the pre-tip total and no tip is visible, use that number.

Special merchant normalization:
- Treat "Anthropic", "Claude", "Anthropic AI" as the same merchant cluster.
- Treat "SH Nashville", "Soho House", "SHN" etc. as "Soho House Nashville".

Always respond ONLY with a JSON object like:
{
  "merchant_name": "...",
  "merchant_normalized": "...",
  "receipt_date": "YYYY-MM-DD or ''",
  "subtotal_amount": 0.0,
  "tip_amount": 0.0,
  "total_amount": 0.0
}
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": "You convert receipts to structured JSON for accounting."
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
    except Exception as e:
        print(f"⚠️ Vision error for {path}: {e}", flush=True)
        return None

    merchant_name = (data.get("merchant_name") or "").strip()
    merchant_norm = (data.get("merchant_normalized") or "").strip()
    if not merchant_norm:
        merchant_norm = normalize_merchant_name(merchant_name)

    receipt_date = (data.get("receipt_date") or "").strip()
    subtotal = parse_amount_str(data.get("subtotal_amount"))
    tip = parse_amount_str(data.get("tip_amount"))
    total = parse_amount_str(data.get("total_amount"))

    meta = {
        "filename": path.name,
        "merchant_name": merchant_name,
        "merchant_normalized": merchant_norm,
        "receipt_date": receipt_date,
        "subtotal_amount": subtotal,
        "tip_amount": tip,
        "total_amount": total,
        "raw_json": json.dumps(data, ensure_ascii=False),
        "ocr_source": "gpt41_vision"
    }

    print(f"   ✅ GPT-4.1 success: {merchant_name} · ${total:.2f} · {receipt_date}", flush=True)
    return meta


def get_or_extract_receipt_meta(filename: str) -> dict | None:
    """
    Get cached metadata for this receipt, or run vision once and cache it.
    """
    global receipt_meta_cache
    if not receipt_meta_cache:
        load_receipt_meta()

    if filename in receipt_meta_cache:
        return receipt_meta_cache[filename]

    path = RECEIPT_DIR / filename
    if not path.exists():
        return None

    meta = extract_receipt_with_vision(path)
    if not meta:
        return None

    # enforce merchant normalization layer again
    meta["merchant_normalized"] = normalize_merchant_name(
        meta.get("merchant_normalized") or meta.get("merchant_name")
    )

    receipt_meta_cache[filename] = meta
    save_receipt_meta()
    return meta


# =============================================================================
# RECEIPT MATCHING (USES VISION META)
# =============================================================================

def find_best_receipt(row: dict) -> dict | None:
    """
    Automatic receipt finder using:
      - Vision-derived merchant/date/total for every file in /receipts
      - Chase amount / merchant / date
      - Fuzzy scoring high on amount closeness + merchant similarity + date proximity
    """
    RECEIPT_DIR.mkdir(exist_ok=True)

    chase_amt = parse_amount_str(
        row.get("Chase Amount")
        or row.get("amount")
        or row.get("Amount")
    )
    chase_desc_raw = (
        row.get("Chase Description")
        or row.get("merchant")
        or row.get("Merchant")
        or ""
    )
    chase_desc_norm = normalize_merchant_name(chase_desc_raw)
    chase_date_raw = (
        row.get("Chase Date")
        or row.get("transaction_date")
        or row.get("Date")
        or ""
    )
    chase_date = parse_date_fuzzy(chase_date_raw)

    if chase_amt == 0 and not chase_desc_norm:
        return None

    best = None
    best_score = 0.0

    for fname in os.listdir(RECEIPT_DIR):
        lower = fname.lower()
        if not lower.endswith((".jpg", ".jpeg", ".png", ".webp", ".pdf")):
            continue

        meta = get_or_extract_receipt_meta(fname)
        if not meta:
            continue

        r_total = meta.get("total_amount") or 0.0
        r_merchant_norm = meta.get("merchant_normalized") or ""
        r_date_raw = meta.get("receipt_date") or ""
        r_date = parse_date_fuzzy(r_date_raw)

        # --- amount score ---
        amount_score = 0.0
        if chase_amt != 0 and r_total != 0:
            diff = abs(chase_amt - r_total)
            # more forgiving when subtotal/tip differences exist (e.g. restaurant tips)
            scale = max(1.0, 0.10 * abs(chase_amt))
            amount_score = max(0.0, 1.0 - (diff / scale))

        # --- merchant similarity score ---
        merch_score = 0.0
        if chase_desc_norm and r_merchant_norm:
            merch_score = SequenceMatcher(
                None, chase_desc_norm, r_merchant_norm
            ).ratio()

        # --- date score ---
        # NOTE: Dates are often wrong/missing on receipts, so be VERY lenient
        date_score = 0.0
        if chase_date and r_date:
            delta_days = abs((chase_date - r_date).days)
            if delta_days == 0:
                date_score = 1.0
            elif delta_days <= 1:
                date_score = 0.9
            elif delta_days <= 3:
                date_score = 0.8
            elif delta_days <= 7:
                date_score = 0.7
            elif delta_days <= 14:
                date_score = 0.6
            elif delta_days <= 30:
                date_score = 0.5  # Within a month is reasonable
            elif delta_days <= 60:
                date_score = 0.3  # Within 2 months - receipt processing delay
            elif delta_days <= 90:
                date_score = 0.1  # Within 3 months - possible but sketchy
        else:
            # No date on receipt or couldn't extract - don't penalize
            # Give a small score (0.3) so missing date doesn't kill the match
            date_score = 0.3

        # 🎯 SMART MATCHING LOGIC:
        # - Amount is KING (most reliable)
        # - Merchant is secondary (might not be on receipt or might be extracted wrong)
        # - Date is optional (many receipts don't have dates or they're wrong)

        # Only skip if BOTH amount AND merchant are bad
        # Good amount match (>80%) = be lenient on merchant
        # Perfect amount match (>90%) = accept almost any merchant
        amount_is_good = amount_score > 0.80
        amount_is_perfect = amount_score > 0.90
        merchant_is_terrible = merch_score < 0.15  # Less than 15% = completely different

        # Skip only if amount is bad AND merchant is terrible
        if amount_score < 0.50 and merchant_is_terrible:
            continue  # Definitely wrong receipt

        # Calculate weighted score with smart adjustments:
        # - If amount is perfect, don't penalize missing/wrong merchant too much
        # - If date is missing, don't penalize (many receipts don't have dates)

        if amount_is_perfect:
            # Amount matches perfectly - merchant/date less important
            score = 0.8 * amount_score + 0.15 * merch_score + 0.05 * date_score
        elif amount_is_good:
            # Amount matches well - merchant matters more, date still optional
            score = 0.7 * amount_score + 0.25 * merch_score + 0.05 * date_score
        else:
            # Amount not great - need merchant AND date to confirm
            score = 0.5 * amount_score + 0.35 * merch_score + 0.15 * date_score

        if score > best_score:
            best_score = score
            best = {
                "file": fname,
                "score": round(float(score), 3),
                "vision_meta": meta,
                "amount_score": round(float(amount_score), 3),
                "merchant_score": round(float(merch_score), 3),
                "date_score": round(float(date_score), 3),
            }

    # require a fairly strong match
    if best and best["score"] >= 0.50:  # Lowered from 0.65 to 0.50 - was too strict!
        return best
    return None


# =============================================================================
# CONTACT / MERCHANT INTELLIGENCE — Now in contacts_engine.py
# =============================================================================
# All contact/merchant logic has been moved to contacts_engine.py
# and is imported at the top of this file


# =============================================================================
# AUTHENTICATION ROUTES
# =============================================================================

@csrf_exempt_route
@app.route("/login", methods=["GET", "POST"])
def login():
    """Login page with password authentication."""
    error = None
    next_url = request.args.get('next', '/')

    if request.method == "POST":
        password = request.form.get('password', '')
        if verify_password(password):
            session['authenticated'] = True
            session.permanent = True
            return redirect(next_url)
        else:
            error = "Invalid password"

    return render_template_string(LOGIN_PAGE_HTML, error=error, has_pin=bool(AUTH_PIN))


@csrf_exempt_route
@app.route("/login/pin", methods=["GET", "POST"])
def login_pin():
    """PIN entry page for quick mobile unlock."""
    next_url = request.args.get('next', '/')

    if request.method == "POST":
        data = request.get_json() or {}
        pin = data.get('pin', '')
        if verify_pin(pin):
            session['authenticated'] = True
            session.permanent = True
            return jsonify({"success": True})
        else:
            return jsonify({"error": "Invalid PIN"}), 401

    return render_template_string(PIN_PAGE_HTML, next_url=next_url)


@csrf_exempt_route
@app.route("/login/biometric", methods=["POST"])
def login_biometric():
    """Biometric (Face ID/Touch ID) authentication via WebAuthn."""
    data = request.get_json() or {}
    credential_id = data.get('credential_id', '')
    authenticator_data = data.get('authenticator_data', '')

    if not credential_id:
        return jsonify({"error": "No credential provided"}), 400

    # For WebAuthn, the actual verification happens client-side with the platform authenticator
    # If the client successfully got past the biometric check, we trust the credential
    # The credential_id should match what was enrolled during registration

    # In a production app, you'd verify the signature against stored public key
    # For this PWA, we trust the platform authenticator's verification

    if credential_id and authenticator_data:
        session['authenticated'] = True
        session.permanent = True
        return jsonify({"success": True})
    else:
        return jsonify({"error": "Biometric authentication failed"}), 401


@app.route("/api/biometric/challenge", methods=["GET"])
def biometric_challenge():
    """Generate a challenge for WebAuthn authentication."""
    import secrets
    import base64

    # Generate random challenge
    challenge = secrets.token_bytes(32)
    challenge_b64 = base64.b64encode(challenge).decode('utf-8')

    # Store in session for verification (optional for simple implementation)
    session['webauthn_challenge'] = challenge_b64

    return jsonify({
        "challenge": challenge_b64,
        "rpId": request.host.split(':')[0],  # Domain without port
        "timeout": 60000
    })


@app.route("/logout")
def logout():
    """Clear session and logout."""
    session.clear()
    return redirect('/login')


# =============================================================================
# ROUTES – CORE VIEWER
# =============================================================================

@app.route("/")
@login_required
def index():
    """Serve the Dashboard as the main landing page."""
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/dashboard")
@login_required
def dashboard():
    """Serve the Dashboard page."""
    return send_from_directory(BASE_DIR, "dashboard.html")


@app.route("/viewer")
@login_required
def viewer():
    """Serve the legacy HTML viewer."""
    return send_from_directory(BASE_DIR, "receipt_reconciler_viewer.html")


@app.route("/settings")
@login_required
def settings_page():
    """Serve the Settings page."""
    return send_from_directory(BASE_DIR, "settings.html")


@app.route("/incoming.html")
@app.route("/incoming")
@login_required
def incoming():
    """Serve the Incoming Receipts page."""
    return send_from_directory(BASE_DIR, "incoming.html")


# =============================================================================
# MOBILE SCANNER PWA ROUTES
# =============================================================================

@app.route("/scanner")
@login_required
def mobile_scanner():
    """Serve the mobile receipt scanner PWA."""
    return send_from_directory(BASE_DIR, "mobile_scanner.html")


@app.route("/library")
@login_required
def library_page():
    """Serve the Receipt Library page."""
    return send_from_directory(BASE_DIR, "receipt_library.html")


@app.route("/reports")
@login_required
def reports_page():
    """Serve the Reports page."""
    return send_from_directory(BASE_DIR, "report_builder.html")


@app.route("/manifest.json")
def pwa_manifest():
    """Serve PWA manifest for Add to Home Screen support."""
    # Try static folder first (new location), then BASE_DIR for backwards compat
    static_path = BASE_DIR / "static" / "manifest.json"
    if static_path.exists():
        return send_from_directory(BASE_DIR / "static", "manifest.json", mimetype='application/manifest+json')
    return send_from_directory(BASE_DIR, "manifest.json", mimetype='application/manifest+json')


@app.route("/sw.js")
def service_worker():
    """Serve service worker."""
    return send_from_directory(BASE_DIR, "sw.js", mimetype='application/javascript')


@app.route("/static/js/<path:filename>")
def serve_static_js(filename):
    """Serve static JavaScript files."""
    return send_from_directory(BASE_DIR / "static" / "js", filename, mimetype='application/javascript')


@app.route("/static/css/<path:filename>")
def serve_static_css(filename):
    """Serve static CSS files."""
    return send_from_directory(BASE_DIR / "static" / "css", filename, mimetype='text/css')


@app.route("/receipt-icon-192.png")
@app.route("/receipt-icon-512.png")
def pwa_icons():
    """Serve PWA icons - returns a placeholder SVG as data URI."""
    # Generate a simple receipt icon SVG
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
        <rect fill="#4ade80" width="512" height="512" rx="64"/>
        <rect fill="#1a1a2e" x="96" y="64" width="320" height="384" rx="16"/>
        <rect fill="#f1f5f9" x="128" y="96" width="256" height="24" rx="4"/>
        <rect fill="#94a3b8" x="128" y="140" width="180" height="16" rx="4"/>
        <rect fill="#94a3b8" x="128" y="176" width="220" height="16" rx="4"/>
        <rect fill="#94a3b8" x="128" y="212" width="160" height="16" rx="4"/>
        <rect fill="#4ade80" x="128" y="280" width="256" height="32" rx="4"/>
        <rect fill="#94a3b8" x="128" y="340" width="120" height="16" rx="4"/>
        <rect fill="#f1f5f9" x="264" y="340" width="120" height="16" rx="4"/>
    </svg>'''
    from flask import Response
    return Response(svg, mimetype='image/svg+xml')


@app.route("/health")
@app.route("/api/health")
def health_check():
    """Health check endpoint for PWA connection status and system health."""
    import time

    health_data = {
        "status": "ok",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "version": APP_VERSION,
        "build_time": APP_BUILD_TIME,
        "services": {}
    }

    # Check Database with response time
    db_start = time.time()
    db_status = {"status": "unknown", "response_ms": 0}
    if db:
        try:
            if USE_DATABASE:
                result = db.execute_query("SELECT COUNT(*) as cnt FROM transactions")
                tx_count = result[0]['cnt'] if result else 0
                db_status = {
                    "status": "connected",
                    "type": "mysql",
                    "host": "Railway",
                    "response_ms": round((time.time() - db_start) * 1000, 2),
                    "transaction_count": tx_count
                }

                # Get receipt stats
                receipt_result = db.execute_query("""
                    SELECT
                        COUNT(*) as total,
                        SUM(CASE WHEN receipt_url IS NOT NULL AND receipt_url != '' THEN 1 ELSE 0 END) as with_receipts,
                        SUM(CASE WHEN deleted = 1 THEN 1 ELSE 0 END) as deleted
                    FROM transactions
                """)
                if receipt_result:
                    db_status["receipts"] = {
                        "total": receipt_result[0]['total'],
                        "with_receipts": receipt_result[0]['with_receipts'],
                        "deleted": receipt_result[0].get('deleted', 0)
                    }
        except Exception as e:
            db_status = {
                "status": "error",
                "error": str(e),
                "response_ms": round((time.time() - db_start) * 1000, 2)
            }
    else:
        db_status = {"status": "not_configured"}
    health_data["services"]["database"] = db_status

    # Check R2 storage configuration
    r2_configured = bool(
        os.environ.get('R2_ACCOUNT_ID') and
        os.environ.get('R2_ACCESS_KEY_ID') and
        os.environ.get('R2_SECRET_ACCESS_KEY')
    )
    r2_bucket = os.environ.get('R2_BUCKET_NAME', 'Not set')
    health_data["services"]["r2_storage"] = {
        "status": "connected" if r2_configured else "not_configured",
        "bucket": r2_bucket if r2_configured else None,
        "endpoint": f"{os.environ.get('R2_ACCOUNT_ID', '')[:8]}..." if r2_configured else None
    }

    # Check Gemini API configuration
    gemini_configured = bool(os.environ.get('GEMINI_API_KEY'))
    gemini_key = os.environ.get('GEMINI_API_KEY', '')
    health_data["services"]["gemini_ai"] = {
        "status": "configured" if gemini_configured else "not_configured",
        "key_prefix": gemini_key[:8] + "..." if gemini_configured else None
    }

    # Check Gmail accounts (check both env vars and files)
    gmail_accounts = []
    gmail_dir = os.path.join(BASE_DIR, 'gmail_tokens')
    for email in ['kaplan.brian@gmail.com', 'brian@musiccityrodeo.com', 'brian@downhome.com']:
        # Check environment variable first (Railway persistence)
        env_key = f"GMAIL_TOKEN_{email.replace('@', '_').replace('.', '_').upper()}"
        env_token = os.environ.get(env_key)

        # Check file-based token as fallback
        safe_email = email.replace('@', '_at_').replace('.', '_')
        token_path = os.path.join(gmail_dir, f'{safe_email}_token.json')
        file_exists = os.path.exists(token_path) if os.path.isdir(gmail_dir) else False

        connected = bool(env_token) or file_exists
        gmail_accounts.append({
            "email": email,
            "connected": connected,
            "source": "env" if env_token else ("file" if file_exists else None)
        })
    health_data["services"]["gmail"] = {
        "accounts": gmail_accounts,
        "connected_count": sum(1 for a in gmail_accounts if a['connected'])
    }

    # Check OCR availability
    health_data["services"]["ocr"] = {
        "status": "available",
        "provider": "gemini" if gemini_configured else "donut_fallback",
        "accuracy": "99%+" if gemini_configured else "97-98%"
    }

    # Check Calendar integration
    calendar_connected = False
    try:
        from calendar_service import get_calendar_service
        creds = get_calendar_service()
        calendar_connected = creds is not None
    except Exception:
        pass
    health_data["services"]["calendar"] = {
        "connected": calendar_connected,
        "status": "connected" if calendar_connected else "not_configured"
    }
    health_data["calendar_connected"] = calendar_connected

    # Legacy fields for backwards compatibility
    health_data["database"] = "connected" if db else "none"
    health_data["storage"] = "ok" if r2_configured else "not_configured"
    health_data["r2_connected"] = r2_configured
    health_data["ai"] = "ok" if gemini_configured else "not_configured"
    health_data["gemini_configured"] = gemini_configured

    return jsonify(health_data)


@app.route("/api/dashboard/stats")
def dashboard_stats():
    """
    Get dashboard statistics for the home page.
    Returns total receipts, pending count, month total, and match rate.
    Requires authentication via session or admin_key.
    """
    # Check authentication - session OR admin_key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')

    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn, db_type = get_db_connection()
    except Exception as e:
        print(f"Dashboard stats DB connection error: {e}")
        return jsonify({
            "total_receipts": 0,
            "pending": 0,
            "month_total": 0,
            "match_rate": 0,
            "error": f"DB connection: {str(e)}"
        })

    try:
        # Total receipts with r2_url OR receipt_url (matched) - count both sources
        cursor = db_execute(conn, db_type, """
            SELECT COUNT(*) AS cnt FROM transactions
            WHERE (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
        """)
        row = cursor.fetchone()
        total_matched = row['cnt'] if row else 0
        cursor.close()

        # Total transactions
        cursor = db_execute(conn, db_type, "SELECT COUNT(*) AS cnt FROM transactions")
        row = cursor.fetchone()
        total_transactions = row['cnt'] if row else 0
        cursor.close()

        # Pending incoming receipts (handle if table doesn't exist)
        pending = 0
        try:
            cursor = db_execute(conn, db_type, "SELECT COUNT(*) AS cnt FROM incoming_receipts WHERE status = 'pending'")
            row = cursor.fetchone()
            pending = row['cnt'] if row else 0
            cursor.close()
        except Exception as pe:
            print(f"Pending count error (table may not exist): {pe}")
            pending = 0

        # This month's spending - sum all expenses this month (negative amounts are expenses)
        month_total = 0.0
        try:
            cursor = db_execute(conn, db_type, """
                SELECT COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total
                FROM transactions
                WHERE chase_date >= DATE_FORMAT(CURRENT_DATE(), '%Y-%m-01')
            """)
            row = cursor.fetchone()
            month_total = float(row['total']) if row and row['total'] else 0.0
            cursor.close()
        except Exception as me:
            print(f"Month total error: {me}")
            month_total = 0.0

        # Calculate match rate
        match_rate = round((total_matched / total_transactions * 100) if total_transactions > 0 else 0)
        missing_receipts = total_transactions - total_matched

        # ========== VERIFICATION STATS ==========
        verification_stats = {'verified': 0, 'needs_review': 0, 'mismatch': 0, 'unverified': 0}
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    SUM(CASE WHEN ocr_verified = 1 OR ocr_verification_status = 'verified' THEN 1 ELSE 0 END) AS verified,
                    SUM(CASE WHEN ocr_verification_status = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
                    SUM(CASE WHEN ocr_verification_status = 'mismatch' THEN 1 ELSE 0 END) AS mismatch,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' AND COALESCE(ocr_verified, 0) = 0 AND COALESCE(ocr_verification_status, '') = '' THEN 1 ELSE 0 END) AS unverified
                FROM transactions
            """)
            row = cursor.fetchone()
            if row:
                verification_stats = {
                    'verified': int(row['verified'] or 0),
                    'needs_review': int(row['needs_review'] or 0),
                    'mismatch': int(row['mismatch'] or 0),
                    'unverified': int(row['unverified'] or 0)
                }
            cursor.close()
        except Exception as ve:
            print(f"Verification stats error: {ve}")

        # ========== BUSINESS BREAKDOWN ==========
        business_breakdown = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    COALESCE(business_type, 'Personal') AS business,
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total_spent,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS has_receipt
                FROM transactions
                WHERE CAST(chase_amount AS DECIMAL(10,2)) < 0
                GROUP BY COALESCE(business_type, 'Personal')
                ORDER BY total_spent DESC
            """)
            for row in cursor.fetchall():
                business_breakdown.append({
                    'business': row['business'],
                    'count': int(row['tx_count']),
                    'total': round(float(row['total_spent'] or 0), 2),
                    'with_receipt': int(row['has_receipt'] or 0),
                    'missing': int(row['tx_count']) - int(row['has_receipt'] or 0),
                    'receipt_pct': round((int(row['has_receipt'] or 0) / int(row['tx_count']) * 100) if row['tx_count'] else 0)
                })
            cursor.close()
        except Exception as be:
            print(f"Business breakdown error: {be}")

        # ========== MONTHLY SPENDING TRENDS (6 months) ==========
        monthly_trends = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    DATE_FORMAT(chase_date, '%Y-%m') AS month,
                    DATE_FORMAT(chase_date, '%b') AS month_name,
                    COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total,
                    COUNT(*) AS tx_count,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS with_receipt
                FROM transactions
                WHERE chase_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 6 MONTH)
                AND CAST(chase_amount AS DECIMAL(10,2)) < 0
                GROUP BY DATE_FORMAT(chase_date, '%Y-%m'), DATE_FORMAT(chase_date, '%b')
                ORDER BY month ASC
            """)
            for row in cursor.fetchall():
                monthly_trends.append({
                    'month': row['month'],
                    'label': row['month_name'],
                    'total': round(float(row['total'] or 0), 2),
                    'count': int(row['tx_count']),
                    'with_receipt': int(row['with_receipt'] or 0)
                })
            cursor.close()
        except Exception as te:
            print(f"Monthly trends error: {te}")

        # ========== TOP MERCHANTS ==========
        top_merchants = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    chase_description AS merchant,
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total_spent,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS with_receipt
                FROM transactions
                WHERE CAST(chase_amount AS DECIMAL(10,2)) < 0
                GROUP BY chase_description
                ORDER BY total_spent DESC
                LIMIT 10
            """)
            for row in cursor.fetchall():
                top_merchants.append({
                    'merchant': (row['merchant'] or 'Unknown')[:35],
                    'count': int(row['tx_count']),
                    'total': round(float(row['total_spent'] or 0), 2),
                    'with_receipt': int(row['with_receipt'] or 0)
                })
            cursor.close()
        except Exception as tme:
            print(f"Top merchants error: {tme}")

        # ========== NEEDS ATTENTION (Large missing receipts) ==========
        needs_attention = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    _index,
                    chase_description AS merchant,
                    chase_date AS date,
                    ABS(CAST(chase_amount AS DECIMAL(10,2))) AS amount,
                    business_type
                FROM transactions
                WHERE (r2_url IS NULL OR r2_url = '')
                AND CAST(chase_amount AS DECIMAL(10,2)) < 0
                ORDER BY ABS(CAST(chase_amount AS DECIMAL(10,2))) DESC
                LIMIT 10
            """)
            for row in cursor.fetchall():
                needs_attention.append({
                    'index': row['_index'],
                    'merchant': (row['merchant'] or 'Unknown')[:30],
                    'date': str(row['date']),
                    'amount': round(float(row['amount'] or 0), 2),
                    'business': row['business_type'] or 'Personal'
                })
            cursor.close()
        except Exception as nae:
            print(f"Needs attention error: {nae}")

        # ========== MISMATCHES NEEDING REVIEW ==========
        mismatches = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    _index,
                    chase_description AS merchant,
                    chase_date AS date,
                    ABS(CAST(chase_amount AS DECIMAL(10,2))) AS amount,
                    ocr_merchant,
                    ocr_amount,
                    business_type
                FROM transactions
                WHERE ocr_verification_status = 'mismatch'
                ORDER BY chase_date DESC
                LIMIT 10
            """)
            for row in cursor.fetchall():
                mismatches.append({
                    'index': row['_index'],
                    'merchant': (row['merchant'] or 'Unknown')[:25],
                    'date': str(row['date']),
                    'amount': round(float(row['amount'] or 0), 2),
                    'ocr_merchant': (row['ocr_merchant'] or '')[:25],
                    'ocr_amount': round(float(row['ocr_amount'] or 0), 2) if row['ocr_amount'] else None,
                    'business': row['business_type'] or 'Personal'
                })
            cursor.close()
        except Exception as me:
            print(f"Mismatches error: {me}")

        # ========== RECENT RECEIPTS ==========
        recent_receipts = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    _index,
                    chase_description AS merchant,
                    chase_date AS date,
                    ABS(CAST(chase_amount AS DECIMAL(10,2))) AS amount,
                    r2_url,
                    business_type,
                    ocr_verified
                FROM transactions
                WHERE r2_url IS NOT NULL AND r2_url != ''
                ORDER BY chase_date DESC
                LIMIT 8
            """)
            for row in cursor.fetchall():
                recent_receipts.append({
                    'index': row['_index'],
                    'merchant': (row['merchant'] or 'Unknown')[:25],
                    'date': str(row['date']),
                    'amount': round(float(row['amount'] or 0), 2),
                    'receipt_url': row['r2_url'],
                    'business': row['business_type'] or 'Personal',
                    'verified': bool(row['ocr_verified'])
                })
            cursor.close()
        except Exception as rre:
            print(f"Recent receipts error: {rre}")

        # ========== CATEGORY SPENDING ==========
        category_spending = {'business': 0, 'personal': 0}
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    CASE WHEN business_type IS NOT NULL AND business_type != '' THEN 'business' ELSE 'personal' END AS category,
                    COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total
                FROM transactions
                WHERE CAST(chase_amount AS DECIMAL(10,2)) < 0
                GROUP BY CASE WHEN business_type IS NOT NULL AND business_type != '' THEN 'business' ELSE 'personal' END
            """)
            for row in cursor.fetchall():
                category_spending[row['category']] = round(float(row['total'] or 0), 2)
            cursor.close()
        except Exception as cse:
            print(f"Category spending error: {cse}")

        # ========== WEEKLY ACTIVITY ==========
        weekly_activity = []
        try:
            cursor = db_execute(conn, db_type, """
                SELECT
                    YEARWEEK(chase_date, 1) AS week,
                    MIN(chase_date) AS week_start,
                    COUNT(*) AS tx_count,
                    COALESCE(SUM(ABS(CAST(chase_amount AS DECIMAL(10,2)))), 0) AS total,
                    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS with_receipt
                FROM transactions
                WHERE chase_date >= DATE_SUB(CURRENT_DATE(), INTERVAL 4 WEEK)
                AND CAST(chase_amount AS DECIMAL(10,2)) < 0
                GROUP BY YEARWEEK(chase_date, 1)
                ORDER BY week DESC
            """)
            for row in cursor.fetchall():
                weekly_activity.append({
                    'week_start': str(row['week_start']),
                    'count': int(row['tx_count']),
                    'total': round(float(row['total'] or 0), 2),
                    'with_receipt': int(row['with_receipt'] or 0)
                })
            cursor.close()
        except Exception as wae:
            print(f"Weekly activity error: {wae}")

        return jsonify({
            "total_receipts": int(total_matched),
            "pending": int(pending),
            "month_total": round(month_total, 2),
            "match_rate": int(match_rate),
            "total_transactions": int(total_transactions),
            "missing_receipts": int(missing_receipts),
            "verification": verification_stats,
            "business_breakdown": business_breakdown,
            "monthly_trends": monthly_trends,
            "top_merchants": top_merchants,
            "needs_attention": needs_attention,
            "mismatches": mismatches,
            "recent_receipts": recent_receipts,
            "category_spending": category_spending,
            "weekly_activity": weekly_activity,
            "ok": True
        })

    except Exception as e:
        import traceback
        print(f"Dashboard stats error: {e}")
        traceback.print_exc()
        return jsonify({
            "total_receipts": 0,
            "pending": 0,
            "month_total": 0,
            "match_rate": 0,
            "error": f"Query error: {str(e)}"
        })
    finally:
        try:
            return_db_connection(conn)
        except:
            pass


@app.route("/api/location/nearby")
def get_nearby_places():
    """
    Smart location lookup - finds nearby restaurants/businesses using Overpass API.
    Much better than basic reverse geocoding for identifying where you are.

    Query params:
    - lat: latitude
    - lng: longitude
    - merchant: optional merchant name from OCR to match against
    """
    import requests

    lat = request.args.get('lat')
    lng = request.args.get('lng')
    merchant = request.args.get('merchant', '')

    if not lat or not lng:
        return jsonify({'error': 'lat and lng required'}), 400

    try:
        lat = float(lat)
        lng = float(lng)
    except ValueError:
        return jsonify({'error': 'Invalid coordinates'}), 400

    # Search radius in meters - restaurants/cafes within 100m
    radius = 100

    # Overpass API query for nearby POIs (restaurants, cafes, shops, etc.)
    overpass_query = f"""
    [out:json][timeout:10];
    (
      node["amenity"~"restaurant|cafe|bar|fast_food|pub"](around:{radius},{lat},{lng});
      node["shop"](around:{radius},{lat},{lng});
      way["amenity"~"restaurant|cafe|bar|fast_food|pub"](around:{radius},{lat},{lng});
      way["shop"](around:{radius},{lat},{lng});
    );
    out center tags;
    """

    places = []
    best_match = None

    try:
        resp = requests.post(
            'https://overpass-api.de/api/interpreter',
            data={'data': overpass_query},
            timeout=10
        )

        if resp.ok:
            data = resp.json()
            elements = data.get('elements', [])

            for el in elements:
                tags = el.get('tags', {})
                name = tags.get('name', '')
                if not name:
                    continue

                # Get coordinates (for ways, use center)
                el_lat = el.get('lat') or el.get('center', {}).get('lat')
                el_lng = el.get('lon') or el.get('center', {}).get('lon')

                # Calculate distance
                distance = 0
                if el_lat and el_lng:
                    # Simple distance formula (good enough for short distances)
                    dlat = (el_lat - lat) * 111000  # ~111km per degree
                    dlng = (el_lng - lng) * 111000 * math.cos(math.radians(lat))
                    distance = math.sqrt(dlat**2 + dlng**2)

                # Determine category
                amenity = tags.get('amenity', '')
                shop_type = tags.get('shop', '')
                cuisine = tags.get('cuisine', '')

                if amenity in ['restaurant', 'cafe', 'fast_food']:
                    category = 'Meals'
                elif amenity in ['bar', 'pub']:
                    category = 'Entertainment'
                elif shop_type:
                    category = 'Supplies'
                else:
                    category = ''

                place = {
                    'name': name,
                    'type': amenity or shop_type,
                    'cuisine': cuisine,
                    'category': category,
                    'distance_m': round(distance, 1),
                    'address': tags.get('addr:street', ''),
                    'city': tags.get('addr:city', '')
                }
                places.append(place)

                # Match against merchant name if provided
                if merchant and not best_match:
                    merchant_lower = merchant.lower()
                    name_lower = name.lower()
                    # Check for match
                    if (merchant_lower in name_lower or
                        name_lower in merchant_lower or
                        SequenceMatcher(None, merchant_lower, name_lower).ratio() > 0.6):
                        best_match = place

            # Sort by distance
            places.sort(key=lambda x: x['distance_m'])

    except Exception as e:
        print(f"[Location] Overpass error: {e}")

    # If no places found, try basic reverse geocoding as fallback
    if not places:
        try:
            resp = requests.get(
                f'https://nominatim.openstreetmap.org/reverse?lat={lat}&lon={lng}&format=json',
                headers={'User-Agent': 'Tallyups/1.0'},
                timeout=5
            )
            if resp.ok:
                data = resp.json()
                addr = data.get('address', {})
                name = addr.get('amenity') or addr.get('shop') or addr.get('restaurant') or addr.get('building') or ''
                if name:
                    places.append({
                        'name': name,
                        'type': 'location',
                        'category': '',
                        'distance_m': 0,
                        'address': addr.get('road', ''),
                        'city': addr.get('city') or addr.get('town') or addr.get('village', '')
                    })
        except:
            pass

    return jsonify({
        'places': places[:10],  # Top 10 closest
        'best_match': best_match,
        'closest': places[0] if places else None,
        'count': len(places)
    })


@app.route("/api/debug/receipt-stats")
def debug_receipt_stats():
    """Debug endpoint to check receipt statistics"""
    if not USE_DATABASE or not db:
        return jsonify({'error': 'Database not available'}), 500

    try:
        # Get receipt stats
        stats = db.execute_query("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN (receipt_url IS NULL OR receipt_url = '') AND (receipt_file IS NULL OR receipt_file = '') THEN 1 ELSE 0 END) as missing_receipt,
                SUM(CASE WHEN receipt_url IS NOT NULL AND receipt_url != '' THEN 1 ELSE 0 END) as has_receipt_url,
                SUM(CASE WHEN receipt_file IS NOT NULL AND receipt_file != '' THEN 1 ELSE 0 END) as has_receipt_file,
                SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) as has_r2_url
            FROM transactions
        """)

        # Check which columns exist
        columns = db.execute_query("SHOW COLUMNS FROM transactions")
        col_names = [c['Field'] for c in columns] if columns else []

        # Get deleted count if column exists
        deleted_count = 0
        if 'deleted' in col_names:
            deleted_result = db.execute_query("SELECT COUNT(*) as cnt FROM transactions WHERE deleted = 1")
            deleted_count = deleted_result[0]['cnt'] if deleted_result else 0

        # Get sample missing receipts
        sample_missing = db.execute_query("""
            SELECT _index, chase_date, chase_description, chase_amount, business_type
            FROM transactions
            WHERE (receipt_url IS NULL OR receipt_url = '')
              AND (receipt_file IS NULL OR receipt_file = '')
            LIMIT 20
        """)

        return jsonify({
            'ok': True,
            'stats': stats[0] if stats else {},
            'deleted_count': deleted_count,
            'has_deleted_column': 'deleted' in col_names,
            'sample_missing': sample_missing,
            'columns': col_names[:20]  # First 20 columns
        })
    except Exception as e:
        import traceback
        return jsonify({'ok': False, 'error': str(e), 'traceback': traceback.format_exc()}), 500


@app.route("/api/debug/transaction/<int:idx>")
@login_required
def debug_transaction(idx):
    """Debug endpoint to test transaction lookup"""
    result = {"idx": idx, "USE_DATABASE": USE_DATABASE, "USE_SQLITE": USE_SQLITE, "db_available": db is not None}

    if USE_DATABASE and db:
        try:
            row = db.get_transaction_by_index(idx)
            result["db_lookup"] = "success" if row else "not_found"
            result["row_type"] = type(row).__name__ if row else None
            result["row_keys"] = list(row.keys()) if row and isinstance(row, dict) else None
            result["row_sample"] = {k: str(v)[:50] for k, v in list(row.items())[:5]} if row and isinstance(row, dict) else None
        except Exception as e:
            result["db_lookup"] = "error"
            result["error"] = str(e)

    return jsonify(result)


@app.route("/ocr", methods=["POST"])
@login_required
def ocr_endpoint():
    """
    OCR endpoint for mobile scanner using Gemini (free tier).
    Extracts merchant, amount, date from receipt image with calendar context.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        # Save temporarily
        import tempfile
        import os

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        # Use Gemini OCR (free tier!)
        try:
            import google.generativeai as genai
            import PIL.Image
            import json as json_module

            # Get Gemini model
            model = get_gemini_model()

            # Load image
            img = PIL.Image.open(tmp_path)

            # First: Quick extraction to get date for calendar lookup
            basic_result = gemini_ocr_extract(tmp_path)
            receipt_date = basic_result.get('date') or datetime.now().strftime('%Y-%m-%d')

            # Get calendar context for contextual notes
            calendar_context = ""
            try:
                from calendar_service import get_events_around_date, format_events_for_prompt
                events = get_events_around_date(receipt_date, days_before=1, days_after=1)
                if events:
                    calendar_context = format_events_for_prompt(events)
                    print(f"📅 Calendar context for {receipt_date}: {len(events)} events")
            except Exception as cal_err:
                print(f"Calendar lookup skipped: {cal_err}")

            # If we have calendar context, do enhanced extraction with note generation
            if calendar_context:
                prompt_text = """Extract receipt information and generate a contextual expense note.

Return JSON only:
{
  "merchant": "store name",
  "total": "XX.XX",
  "date": "YYYY-MM-DD",
  "category": "category",
  "confidence": 0.95,
  "note": "contextual note explaining the expense purpose"
}

Categories: Food & Dining, Gas/Automotive, Shopping, Entertainment, Travel, Professional Services, Subscriptions, Other

For the "note" field, match the expense to relevant calendar events:
- For meals: "Lunch with James Stewart" or "Dinner - Client meeting"
- For travel (Uber, parking, gas): "Uber - Dallas trip for American Rodeo"
- For parking: "Parking - Emma's Dance Competition"
- Keep notes concise but informative

""" + calendar_context + """

Return ONLY valid JSON, no explanation."""

                response = model.generate_content([prompt_text, img])
                text = response.text.strip()

                # Clean markdown if present
                if text.startswith('```'):
                    lines = text.split('\n')
                    text = '\n'.join(lines[1:-1]) if len(lines) > 2 else text

                try:
                    result = json_module.loads(text)
                except json_module.JSONDecodeError:
                    # Fall back to basic result
                    result = basic_result
                    result['note'] = None
            else:
                # No calendar context, use basic result
                result = basic_result
                result['note'] = None

            os.unlink(tmp_path)

            # Ensure all expected fields exist
            result.setdefault('merchant', None)
            result.setdefault('total', None)
            result.setdefault('date', None)
            result.setdefault('category', None)
            result.setdefault('confidence', 0.8)
            result.setdefault('note', None)

            # Log the AI-generated note
            if result.get('note'):
                print(f"🤖 AI Note: {result['note']}")

            return jsonify(result)

        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            print(f"OCR error: {e}")
            return jsonify({
                "merchant": None,
                "total": None,
                "date": None,
                "category": None,
                "confidence": 0,
                "error": str(e)
            })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/extract", methods=["POST"])
def ocr_extract_full():
    """
    Full receipt extraction using unified OCR service (Mindee-quality).
    Returns complete receipt data including line items.

    Auth: admin_key OR session login

    Request:
        - file: Receipt image (PNG, JPG, PDF, HEIC)

    Response (JSON):
        {
            "supplier_name": "CLEAR",
            "supplier_address": "85 10th Avenue...",
            "receipt_number": "7994BFE1-0001",
            "date": "2025-10-21",
            "total_amount": 334.00,
            "subtotal": 334.00,
            "tax_amount": 0.0,
            "tip_amount": 0.0,
            "line_items": [...],
            "payment_method": "Visa - 6771",
            "currency": "USD",
            "confidence": 0.95,
            "ocr_method": "gemini"
        }
    """
    # Auth: admin_key OR session login
    admin_key = request.form.get('admin_key') or request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required. Include admin_key.'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        import tempfile

        # Determine file extension
        ext = Path(file.filename).suffix.lower() or '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        # Extract using unified OCR service
        result = extract_receipt(tmp_path)

        # Clean up
        os.unlink(tmp_path)

        return jsonify(result)

    except Exception as e:
        print(f"OCR extract error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/verify", methods=["POST"])
def ocr_verify_receipt():
    """
    Verify a receipt matches expected transaction data.

    Auth: admin_key OR session login

    Request:
        - file: Receipt image
        - merchant: Expected merchant name (optional)
        - amount: Expected amount (required)
        - date: Expected date YYYY-MM-DD (optional)

    Response:
        {
            "matches": {"merchant": true, "amount": true, "date": true},
            "overall_match": true,
            "confidence": 0.95,
            "extracted": {...},
            "expected": {...}
        }
    """
    # Auth: admin_key OR session login
    admin_key = request.form.get('admin_key') or request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required. Include admin_key.'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    expected_merchant = request.form.get('merchant')
    expected_amount = request.form.get('amount')
    expected_date = request.form.get('date')

    if not expected_amount:
        return jsonify({"error": "Expected amount is required"}), 400

    try:
        import tempfile

        ext = Path(file.filename).suffix.lower() or '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        # Verify receipt
        result = verify_receipt(
            tmp_path,
            merchant=expected_merchant,
            amount=float(expected_amount),
            date=expected_date
        )

        os.unlink(tmp_path)

        return jsonify(result)

    except Exception as e:
        print(f"OCR verify error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/verify-batch", methods=["POST"])
def ocr_verify_batch():
    """
    Batch verify multiple receipts against transactions.
    Optimized for verifying 500+ receipts quickly.

    Auth: admin_key required

    Request (JSON):
        {
            "items": [
                {
                    "transaction_id": "abc123",
                    "receipt_path": "/path/to/receipt.pdf",
                    "merchant": "CLEAR",
                    "amount": 334.00,
                    "date": "2025-10-21"
                },
                ...
            ]
        }

    Response:
        {
            "total": 500,
            "verified": 450,
            "failed": 30,
            "errors": 20,
            "duration_seconds": 45.2,
            "results": [...]
        }
    """
    # Auth: admin_key required
    admin_key = (request.json or {}).get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Authentication required. Include admin_key.'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    data = request.get_json()
    if not data or 'items' not in data:
        return jsonify({"error": "Request must include 'items' array"}), 400

    items = data['items']
    if not items:
        return jsonify({"error": "Items array is empty"}), 400

    # Import batch function
    from receipt_ocr_service import verify_receipts_batch, get_cache_stats

    # Transform items to expected format
    batch_items = []
    for item in items:
        batch_items.append({
            'transaction_id': item.get('transaction_id'),
            'image_path': item.get('receipt_path'),
            'merchant': item.get('merchant'),
            'amount': item.get('amount'),
            'date': item.get('date')
        })

    # Run batch verification
    result = verify_receipts_batch(batch_items)

    # Add cache stats
    result['cache_stats'] = get_cache_stats()

    return jsonify(result)


@app.route("/api/ocr/verify-transactions", methods=["POST"])
def ocr_verify_transactions():
    """
    Verify receipts for transactions from database.
    Pass transaction IDs, and we'll look up receipt paths and expected data.

    Auth: admin_key required

    Request (JSON):
        {
            "transaction_ids": ["abc123", "def456", ...],
            "limit": 100  // optional, default 100
        }

    Response:
        Same as verify-batch
    """
    # Auth: admin_key required
    admin_key = (request.json or {}).get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Authentication required. Include admin_key.'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    data = request.get_json()
    transaction_ids = data.get('transaction_ids', [])
    limit = min(data.get('limit', 100), 1000)  # Cap at 1000

    # If no IDs provided, get unverified transactions from database
    if not transaction_ids:
        try:
            conn, db_type = get_db_connection()
            cursor = db_execute(conn, db_type, """
                SELECT transaction_id, description, amount, date, receipt_file_path
                FROM receipt_reconciliation
                WHERE receipt_file_path IS NOT NULL
                AND verification_status != 'verified'
                LIMIT %s
            """, (limit,))
            rows = cursor.fetchall()
            return_db_connection(conn)

            # Build batch items from database
            batch_items = []
            for row in rows:
                if row.get('receipt_file_path'):
                    batch_items.append({
                        'transaction_id': row.get('transaction_id'),
                        'image_path': row.get('receipt_file_path'),
                        'merchant': row.get('description'),
                        'amount': float(row.get('amount', 0)),
                        'date': str(row.get('date', ''))
                    })

        except Exception as e:
            return jsonify({"error": f"Database error: {e}"}), 500
    else:
        # Look up specific transactions
        try:
            conn, db_type = get_db_connection()
            placeholders = ', '.join(['%s'] * len(transaction_ids))
            cursor = db_execute(conn, db_type, f"""
                SELECT transaction_id, description, amount, date, receipt_file_path
                FROM receipt_reconciliation
                WHERE transaction_id IN ({placeholders})
            """, tuple(transaction_ids))
            rows = cursor.fetchall()
            return_db_connection(conn)

            batch_items = []
            for row in rows:
                if row.get('receipt_file_path'):
                    batch_items.append({
                        'transaction_id': row.get('transaction_id'),
                        'image_path': row.get('receipt_file_path'),
                        'merchant': row.get('description'),
                        'amount': float(row.get('amount', 0)),
                        'date': str(row.get('date', ''))
                    })

        except Exception as e:
            return jsonify({"error": f"Database error: {e}"}), 500

    if not batch_items:
        return jsonify({
            "total": 0,
            "verified": 0,
            "failed": 0,
            "errors": 0,
            "message": "No transactions with receipt paths found"
        })

    # Run batch verification
    from receipt_ocr_service import verify_receipts_batch, get_cache_stats
    result = verify_receipts_batch(batch_items)
    result['cache_stats'] = get_cache_stats()

    return jsonify(result)


@app.route("/api/ocr/cache-stats", methods=["GET"])
def ocr_cache_stats():
    """Get OCR cache statistics"""
    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    from receipt_ocr_service import get_cache_stats
    return jsonify(get_cache_stats())


@app.route("/api/ocr/extract-for-transaction/<int:tx_index>", methods=["POST"])
def ocr_extract_for_transaction(tx_index):
    """
    Extract OCR data for a specific transaction and store it.
    Called from Quick Viewer to extract OCR for a receipt.

    Auth: admin_key OR session login
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 503

    try:
        # Get transaction
        conn, db_type = get_db_connection()
        cursor = db_execute(conn, db_type, 'SELECT receipt_file FROM transactions WHERE _index = ?', (tx_index,))
        row = cursor.fetchone()
        return_db_connection(conn)

        if not row:
            return jsonify({"error": f"Transaction {tx_index} not found"}), 404

        receipt_file = row.get('receipt_file')
        if not receipt_file:
            return jsonify({"error": "No receipt attached to this transaction"}), 400

        # Run OCR extraction
        from ocr_integration import auto_ocr_on_receipt_match, get_ocr_data_for_transaction

        result = auto_ocr_on_receipt_match(tx_index, receipt_file)

        if result:
            return jsonify({
                "ok": True,
                "ocr_data": get_ocr_data_for_transaction(tx_index),
                "message": f"OCR extracted: {result.get('supplier_name')} ${result.get('total_amount')}"
            })
        else:
            return jsonify({
                "ok": False,
                "error": "OCR extraction failed or low confidence"
            }), 400

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/transaction/<int:tx_index>", methods=["GET"])
def get_ocr_for_transaction(tx_index):
    """
    Get stored OCR data for a transaction.
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        from ocr_integration import get_ocr_data_for_transaction
        data = get_ocr_data_for_transaction(tx_index)

        if data:
            return jsonify({"ok": True, "ocr_data": data})
        else:
            return jsonify({"ok": False, "message": "No OCR data available"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/receipt-library/<path:filename>", methods=["GET"])
def get_ocr_for_receipt(filename):
    """
    Get OCR data for a receipt from the receipt library.

    Returns full OCR data including:
    - merchant/supplier_name
    - amount/total_amount
    - date
    - subtotal, tax, tip
    - receipt_number
    - payment_method
    - line_items (itemized breakdown)
    - confidence score
    - ocr_method used
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        # First check database for stored OCR data
        if db:
            conn = db.get_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT * FROM receipt_metadata WHERE filename = %s
            """, (filename,))
            row = cursor.fetchone()
            db.return_connection(conn)

            if row and row.get('ocr_extracted_at'):
                # Parse line items JSON if present
                line_items = row.get('ocr_line_items')
                if isinstance(line_items, str):
                    try:
                        line_items = json.loads(line_items)
                    except:
                        line_items = []

                return jsonify({
                    "ok": True,
                    "from_database": True,
                    "ocr_data": {
                        "filename": row.get('filename'),
                        "supplier_name": row.get('ocr_merchant') or row.get('merchant'),
                        "total_amount": float(row.get('ocr_amount') or row.get('amount') or 0),
                        "date": str(row.get('ocr_date') or row.get('date') or ''),
                        "subtotal": float(row.get('ocr_subtotal') or 0) if row.get('ocr_subtotal') else None,
                        "tax_amount": float(row.get('ocr_tax') or 0) if row.get('ocr_tax') else None,
                        "tip_amount": float(row.get('ocr_tip') or 0) if row.get('ocr_tip') else None,
                        "receipt_number": row.get('ocr_receipt_number'),
                        "payment_method": row.get('ocr_payment_method'),
                        "line_items": line_items,
                        "confidence": row.get('ocr_confidence'),
                        "ocr_method": row.get('ocr_method'),
                        "extracted_at": str(row.get('ocr_extracted_at') or ''),
                    }
                })

        # Not in database, try to extract now
        receipt_path = RECEIPT_DIR / filename
        if not receipt_path.exists():
            # Try without path components
            receipt_path = RECEIPT_DIR / Path(filename).name
            if not receipt_path.exists():
                return jsonify({"ok": False, "error": "Receipt file not found"}), 404

        # Extract and cache
        meta = get_or_extract_receipt_meta(filename)
        if meta:
            return jsonify({
                "ok": True,
                "from_database": False,
                "ocr_data": {
                    "filename": filename,
                    "supplier_name": meta.get('supplier_name') or meta.get('merchant_name'),
                    "total_amount": meta.get('total_amount'),
                    "date": meta.get('date') or meta.get('receipt_date'),
                    "subtotal": meta.get('subtotal') or meta.get('subtotal_amount'),
                    "tax_amount": meta.get('tax_amount'),
                    "tip_amount": meta.get('tip_amount'),
                    "receipt_number": meta.get('receipt_number'),
                    "payment_method": meta.get('payment_method'),
                    "line_items": meta.get('line_items', []),
                    "confidence": meta.get('confidence') or meta.get('confidence_score'),
                    "ocr_method": meta.get('ocr_method') or meta.get('ocr_source'),
                }
            })
        else:
            return jsonify({"ok": False, "error": "OCR extraction failed"}), 500

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/receipt-library", methods=["GET"])
def list_receipt_library_ocr():
    """
    List all receipts in the library with their OCR data.

    Query params:
        limit: Max results (default 100)
        offset: Start offset for pagination
        has_ocr: Filter by OCR status (true/false)
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    limit = min(int(request.args.get('limit', 100)), 500)
    offset = int(request.args.get('offset', 0))
    has_ocr = request.args.get('has_ocr')

    try:
        if db:
            conn = db.get_connection()
            cursor = conn.cursor()

            # Build query based on filter
            if has_ocr == 'true':
                cursor.execute("""
                    SELECT filename, merchant, date, amount,
                           ocr_merchant, ocr_amount, ocr_date, ocr_confidence, ocr_method, ocr_extracted_at
                    FROM receipt_metadata
                    WHERE ocr_extracted_at IS NOT NULL
                    ORDER BY ocr_extracted_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
            elif has_ocr == 'false':
                cursor.execute("""
                    SELECT filename, merchant, date, amount,
                           ocr_merchant, ocr_amount, ocr_date, ocr_confidence, ocr_method, ocr_extracted_at
                    FROM receipt_metadata
                    WHERE ocr_extracted_at IS NULL
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))
            else:
                cursor.execute("""
                    SELECT filename, merchant, date, amount,
                           ocr_merchant, ocr_amount, ocr_date, ocr_confidence, ocr_method, ocr_extracted_at
                    FROM receipt_metadata
                    ORDER BY COALESCE(ocr_extracted_at, created_at) DESC
                    LIMIT %s OFFSET %s
                """, (limit, offset))

            rows = cursor.fetchall()

            # Get total count
            cursor.execute("SELECT COUNT(*) as total FROM receipt_metadata")
            total = cursor.fetchone().get('total', 0)

            db.return_connection(conn)

            receipts = []
            for row in rows:
                receipts.append({
                    "filename": row.get('filename'),
                    "merchant": row.get('ocr_merchant') or row.get('merchant'),
                    "amount": float(row.get('ocr_amount') or row.get('amount') or 0),
                    "date": str(row.get('ocr_date') or row.get('date') or ''),
                    "ocr_confidence": row.get('ocr_confidence'),
                    "ocr_method": row.get('ocr_method'),
                    "has_ocr": row.get('ocr_extracted_at') is not None,
                })

            return jsonify({
                "ok": True,
                "total": total,
                "limit": limit,
                "offset": offset,
                "receipts": receipts
            })
        else:
            return jsonify({"ok": False, "error": "Database not available"}), 503

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/ocr/pre-extract", methods=["POST"])
def ocr_pre_extract():
    """
    Pre-extract and cache receipts from database.
    This populates the cache for fast bulk verification.

    Auth: admin_key required

    Request (JSON):
        {
            "limit": 50,  // Max receipts to process (default 50, max 200)
            "skip_cached": true  // Skip already cached receipts
        }

    Response:
        {
            "total": 50,
            "extracted": 45,
            "cached": 3,
            "errors": 2,
            "duration_seconds": 120.5
        }
    """
    import time

    # Auth: admin_key required
    admin_key = (request.json or {}).get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Authentication required. Include admin_key.'}), 401

    if not OCR_SERVICE_AVAILABLE:
        return jsonify({"error": "OCR service not available"}), 503

    data = request.get_json() or {}
    limit = min(data.get('limit', 50), 200)  # Cap at 200
    skip_cached = data.get('skip_cached', True)

    from receipt_ocr_service import get_ocr_service, get_ocr_cache

    service = get_ocr_service()
    cache = get_ocr_cache()

    # Get receipts from database
    try:
        conn, db_type = get_db_connection()
        cursor = db_execute(conn, db_type, """
            SELECT transaction_id, description, amount, date, receipt_file_path
            FROM receipt_reconciliation
            WHERE receipt_file_path IS NOT NULL
            AND receipt_file_path != ''
            ORDER BY date DESC
            LIMIT %s
        """, (limit * 2,))
        rows = cursor.fetchall()
        return_db_connection(conn)
    except Exception as e:
        return jsonify({"error": f"Database error: {e}"}), 500

    # Filter to existing files
    receipts = []
    for row in rows:
        if len(receipts) >= limit:
            break

        path = row.get('receipt_file_path')
        if not path or not Path(path).exists():
            continue

        # Check cache
        if skip_cached and cache:
            cached = cache.get(path)
            if cached:
                continue

        receipts.append({
            'transaction_id': row.get('transaction_id'),
            'path': path
        })

    if not receipts:
        return jsonify({
            "total": 0,
            "extracted": 0,
            "cached": 0,
            "errors": 0,
            "message": "All receipts already cached or no receipts found"
        })

    # Extract each receipt
    start_time = time.time()
    extracted = 0
    cached_count = 0
    errors = 0

    for receipt in receipts:
        try:
            result = service.extract(receipt['path'])
            if result.get('from_cache'):
                cached_count += 1
            elif result.get('confidence', 0) > 0.3:
                extracted += 1
            else:
                errors += 1
        except Exception as e:
            errors += 1

    duration = time.time() - start_time

    return jsonify({
        "total": len(receipts),
        "extracted": extracted,
        "cached": cached_count,
        "errors": errors,
        "duration_seconds": round(duration, 2),
        "cache_stats": cache.get_stats() if cache else {}
    })


@app.route("/mobile-upload", methods=["POST"])
def mobile_upload():
    """
    Handle receipt uploads from mobile scanner PWA.
    Creates an incoming receipt entry tagged with source=mobile_scanner.

    Supports authentication via:
    - Session login (web browser)
    - admin_key in form data or query params or header
    """
    # Auth check: admin_key OR login
    admin_key = request.form.get('admin_key') or request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required. Include admin_key in form data.'}), 401

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    # Security: Validate file type
    is_valid, error_msg = validate_upload_file(file)
    if not is_valid:
        return jsonify({"error": f"Invalid file: {error_msg}"}), 400

    try:
        # Get form data (may be overridden by OCR if auto_ocr=true)
        merchant = request.form.get('merchant', '')
        amount = request.form.get('amount', '')
        date_str = request.form.get('date', '')
        category = request.form.get('category', '')
        business = request.form.get('business', '')
        notes = request.form.get('notes', '')
        source = request.form.get('source', 'mobile_scanner')
        auto_ocr = request.form.get('auto_ocr', 'true').lower() == 'true'

        # Save receipt file to incoming folder first
        incoming_dir = RECEIPT_DIR / "incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        ext = Path(file.filename).suffix or '.jpg'
        temp_filename = f"mobile_upload_{timestamp}{ext}"
        file_path = incoming_dir / temp_filename
        file.save(str(file_path))

        # Auto-OCR: Extract data from receipt if enabled and OCR service available
        ocr_result = None
        if auto_ocr and OCR_SERVICE_AVAILABLE:
            try:
                print(f"🔍 Running OCR on uploaded receipt...")
                ocr_result = extract_receipt(str(file_path))

                # Use OCR results if form fields are empty
                if ocr_result.get('confidence', 0) > 0.5:
                    if not merchant and ocr_result.get('supplier_name'):
                        merchant = ocr_result['supplier_name']
                    if not amount and ocr_result.get('total_amount'):
                        amount = str(ocr_result['total_amount'])
                    if not date_str and ocr_result.get('date'):
                        date_str = ocr_result['date']

                    print(f"✅ OCR extracted: {merchant} ${amount} on {date_str}")
            except Exception as ocr_err:
                print(f"⚠️ OCR extraction failed (using form data): {ocr_err}")

        # Default values if still empty
        merchant = merchant or 'Unknown'
        date_str = date_str or datetime.now().strftime('%Y-%m-%d')

        # Parse amount
        try:
            amount_float = float(str(amount).replace('$', '').replace(',', '')) if amount else 0.0
        except:
            amount_float = 0.0

        # Rename file with extracted merchant name
        safe_merchant = re.sub(r'[^\w\-]', '_', merchant)[:30]
        filename = f"mobile_{safe_merchant}_{timestamp}{ext}"
        new_file_path = incoming_dir / filename
        if file_path != new_file_path:
            file_path.rename(new_file_path)
            file_path = new_file_path

        # Create incoming receipt record in database
        receipt_id = None
        if USE_DATABASE and db:
            try:
                conn, db_type = get_db_connection()

                # Check if incoming_receipts table exists, create if not (only for SQLite)
                if db_type == 'sqlite':
                    cursor = conn.cursor()
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS incoming_receipts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            source TEXT,
                            sender TEXT,
                            subject TEXT,
                            receipt_date TEXT,
                            merchant TEXT,
                            amount REAL,
                            category TEXT,
                            business_type TEXT,
                            receipt_file TEXT,
                            status TEXT DEFAULT 'pending',
                            notes TEXT,
                            created_at TEXT,
                            processed_at TEXT,
                            matched_transaction_id INTEGER
                        )
                    ''')
                # For MySQL, the table is created in db_mysql._init_schema()

                # Insert the incoming receipt with OCR data
                now_iso = datetime.now().isoformat()

                # Prepare OCR fields
                ocr_merchant = ocr_result.get('supplier_name') if ocr_result else None
                ocr_amount = ocr_result.get('total_amount') if ocr_result else None
                ocr_date_val = ocr_result.get('date') if ocr_result else None
                ocr_subtotal = ocr_result.get('subtotal') if ocr_result else None
                ocr_tax = ocr_result.get('tax_amount') if ocr_result else None
                ocr_tip = ocr_result.get('tip_amount') if ocr_result else None
                ocr_receipt_number = ocr_result.get('receipt_number') if ocr_result else None
                ocr_payment_method = ocr_result.get('payment_method') if ocr_result else None
                ocr_line_items = json.dumps(ocr_result.get('line_items', [])) if ocr_result else None
                ocr_confidence = ocr_result.get('confidence') if ocr_result else None
                ocr_method = ocr_result.get('ocr_method') if ocr_result else None
                ocr_extracted_at = now_iso if ocr_result else None

                cursor = db_execute(conn, db_type, '''
                    INSERT INTO incoming_receipts
                    (source, sender, subject, receipt_date, received_date, merchant, amount, category,
                     business_type, receipt_file, status, notes, created_at,
                     ocr_merchant, ocr_amount, ocr_date, ocr_subtotal, ocr_tax, ocr_tip,
                     ocr_receipt_number, ocr_payment_method, ocr_line_items,
                     ocr_confidence, ocr_method, ocr_extracted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?,
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    source,
                    'Mobile Scanner',
                    f'Receipt from {merchant}',
                    date_str,
                    now_iso,  # received_date = when uploaded
                    merchant,
                    amount_float,
                    category,
                    business,
                    f"incoming/{filename}",
                    notes,
                    now_iso,
                    # OCR fields
                    ocr_merchant,
                    ocr_amount,
                    ocr_date_val,
                    ocr_subtotal,
                    ocr_tax,
                    ocr_tip,
                    ocr_receipt_number,
                    ocr_payment_method,
                    ocr_line_items,
                    ocr_confidence,
                    ocr_method,
                    ocr_extracted_at
                ))

                receipt_id = cursor.lastrowid
                conn.commit()
                return_db_connection(conn)

                print(f"📱 Mobile receipt uploaded: {merchant} ${amount_float:.2f} -> {filename} (OCR: {ocr_method or 'none'})")

            except Exception as e:
                print(f"⚠️ Database error saving mobile receipt: {e}")

        response_data = {
            "success": True,
            "id": receipt_id,
            "filename": filename,
            "merchant": merchant,
            "amount": amount_float,
            "date": date_str,
            "message": "Receipt uploaded to Inbox",
            "ocr_used": ocr_result is not None
        }

        # Include full OCR data if extraction was performed
        if ocr_result:
            response_data["ocr"] = {
                "supplier_name": ocr_result.get('supplier_name'),
                "supplier_address": ocr_result.get('supplier_address'),
                "receipt_number": ocr_result.get('receipt_number'),
                "total_amount": ocr_result.get('total_amount'),
                "subtotal": ocr_result.get('subtotal'),
                "tax_amount": ocr_result.get('tax_amount'),
                "tip_amount": ocr_result.get('tip_amount'),
                "line_items": ocr_result.get('line_items', []),
                "payment_method": ocr_result.get('payment_method'),
                "confidence": ocr_result.get('confidence'),
                "ocr_method": ocr_result.get('ocr_method')
            }

        return jsonify(response_data)

    except Exception as e:
        print(f"❌ Mobile upload error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/transactions/<int:tx_id>", methods=["PUT"])
def update_transaction(tx_id):
    """Update a transaction's fields (admin only)"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Admin key required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Build update query from allowed fields
        allowed_fields = ['chase_date', 'chase_description', 'chase_amount', 'business_type',
                          'review_status', 'notes', 'category', 'receipt_file', 'receipt_url']
        updates = []
        values = []
        for field in allowed_fields:
            if field in data:
                updates.append(f"{field} = %s")
                values.append(data[field])

        if not updates:
            return jsonify({'error': 'No valid fields to update'}), 400

        values.append(tx_id)
        query = f"UPDATE transactions SET {', '.join(updates)} WHERE _index = %s"
        cursor.execute(query, values)
        conn.commit()

        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'message': f'Transaction {tx_id} updated'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/transactions")
def get_transactions():
    """
    Return all transactions as JSON from MySQL.

    Routes:
    - /api/transactions

    PURE SQL MODE: Always reads fresh from database, no caching!

    Query params:
    - show_submitted=true: Include submitted transactions (default: hide them)
    - admin_key: API key for authentication (or use session login)
    """
    # Auth check: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    if USE_DATABASE and db:
        try:
            # Check if we should show submitted transactions
            show_submitted = request.args.get('show_submitted', 'false').lower() == 'true'

            # Use MySQL-specific or SQLite-specific code path
            if hasattr(db, 'use_mysql') and db.use_mysql:
                # MySQL path - get a new connection (caller responsible for closing)
                conn = db.get_connection()
                cursor = conn.cursor()  # Already uses DictCursor from get_connection()

                if show_submitted:
                    cursor.execute('SELECT * FROM transactions ORDER BY chase_date DESC, _index DESC')
                else:
                    cursor.execute('''
                        SELECT * FROM transactions
                        WHERE (already_submitted IS NULL OR already_submitted = '' OR already_submitted != 'yes')
                        ORDER BY chase_date DESC, _index DESC
                    ''')
                rows = cursor.fetchall()

                # Get rejected receipts (safely handle if table doesn't exist yet)
                rejected_paths = set()
                try:
                    cursor.execute('SELECT receipt_path FROM rejected_receipts')
                    rejected_paths = {r['receipt_path'] for r in cursor.fetchall() if r.get('receipt_path')}
                except Exception as e:
                    print(f"ℹ️  rejected_receipts table not found, skipping: {e}", flush=True)

                cursor.close()
                return_db_connection(conn)  # Close the NEW connection we got

                db_type = "MySQL"
            else:
                # SQLite path
                conn = sqlite3.connect(str(db.db_path))
                conn.row_factory = sqlite3.Row

                cursor = conn.cursor()
                if show_submitted:
                    cursor.execute('SELECT * FROM transactions ORDER BY chase_date DESC, _index DESC')
                else:
                    cursor.execute('''
                        SELECT * FROM transactions
                        WHERE (already_submitted IS NULL OR already_submitted = '' OR already_submitted != 'yes')
                        ORDER BY chase_date DESC, _index DESC
                    ''')
                rows = cursor.fetchall()

                # Get rejected receipts
                cursor.execute('SELECT receipt_path FROM rejected_receipts')
                rejected_paths = {r[0] for r in cursor.fetchall()}

                return_db_connection(conn)

                db_type = "SQLite"

            # Convert to list of dicts with proper column names for viewer
            records = []
            for row in rows:
                record = dict(row)
                # Map snake_case columns to viewer's expected names
                record['Chase Description'] = record.get('chase_description', '')
                record['Chase Amount'] = record.get('chase_amount', 0)
                record['Chase Date'] = record.get('chase_date', '')
                record['Business Type'] = record.get('business_type', '')
                record['Review Status'] = record.get('review_status', '')
                record['Receipt File'] = record.get('receipt_file', '')
                record['Already Submitted'] = record.get('already_submitted', '')

                # Map MI (Machine Intelligence) fields
                record['MI Merchant'] = record.get('mi_merchant', '')
                record['MI Category'] = record.get('mi_category', '')
                record['MI Description'] = record.get('mi_description', '')
                record['MI Is Subscription'] = record.get('mi_is_subscription', 0)
                record['MI Confidence'] = record.get('mi_confidence', 0)

                # Map receipt URLs (for R2 storage)
                record['r2_url'] = record.get('r2_url', '') or record.get('receipt_url', '')
                record['R2 URL'] = record.get('r2_url', '') or record.get('receipt_url', '')

                # Map category
                record['Chase Category'] = record.get('chase_category', '') or record.get('category', '')

                # Map OCR fields for Quick Viewer validation
                record['OCR Merchant'] = record.get('ocr_merchant', '')
                record['OCR Amount'] = record.get('ocr_amount')
                record['OCR Date'] = record.get('ocr_date', '')
                record['OCR Subtotal'] = record.get('ocr_subtotal')
                record['OCR Tax'] = record.get('ocr_tax')
                record['OCR Tip'] = record.get('ocr_tip')
                record['OCR Receipt Number'] = record.get('ocr_receipt_number', '')
                record['OCR Payment Method'] = record.get('ocr_payment_method', '')
                record['OCR Line Items'] = record.get('ocr_line_items')
                record['OCR Confidence'] = record.get('ocr_confidence')
                record['OCR Method'] = record.get('ocr_method', '')
                record['OCR Verified'] = record.get('ocr_verified', False)
                record['OCR Verification Status'] = record.get('ocr_verification_status', '')

                # Filter out rejected receipts
                receipt_file = record.get('Receipt File', '')
                if receipt_file:
                    for rejected in rejected_paths:
                        if rejected and rejected.replace('receipts/', '') in receipt_file:
                            record['Receipt File'] = ''
                            break

                records.append(record)

            print(f"📊 Loaded {len(records)} transactions from {db_type} (pure SQL mode)", flush=True)
            return jsonify(safe_json(records))

        except Exception as e:
            print(f"⚠️  Database read error, falling back to DataFrame: {e}", flush=True)

    # Fallback to DataFrame mode
    ensure_df()
    records = df.to_dict(orient="records")
    return jsonify(safe_json(records))


@app.route("/receipts/<path:filename>")
@login_required
def get_receipt(filename):
    """Serve receipt images - handles paths with folder prefixes and absolute paths."""
    # Handle absolute paths
    if filename.startswith('/'):
        abs_path = Path(filename)
        if abs_path.exists():
            return send_from_directory(abs_path.parent, abs_path.name)

    # Try the filename as-is from BASE_DIR (handles receipts/, receipt-1/, etc.)
    path = BASE_DIR / filename
    if path.exists():
        return send_from_directory(BASE_DIR, filename)

    # Fallback: try from RECEIPT_DIR (for backward compatibility)
    path = RECEIPT_DIR / filename
    if path.exists():
        return send_from_directory(RECEIPT_DIR, filename)

    abort(404, f"Receipt not found: {filename}")


@app.route("/update_row", methods=["POST"])
@login_required
def update_row():
    """
    Body: {
      "_index": int,
      "patch": { "Column Name": value, ... }
    }
    """
    ensure_df()
    global df

    data = request.get_json(force=True) or {}
    if "_index" not in data:
        abort(400, "Missing _index")

    try:
        idx = int(data["_index"])
    except (TypeError, ValueError):
        abort(400, f"Invalid _index: {data.get('_index')}")

    patch = data.get("patch") or {}
    if not isinstance(patch, dict):
        abort(400, "patch must be an object")

    # Use MySQL database
    if USE_DATABASE and db:
        try:
            success = db.update_transaction(idx, patch)
            if not success:
                abort(404, f"_index {idx} not found")

            # Reload df to stay in sync
            df = db.get_all_transactions()
            return jsonify(safe_json({"ok": True}))
        except Exception as e:
            print(f"⚠️  MySQL update failed for _index {idx}: {e}")
            abort(500, f"Database update failed: {e}")

    # CSV mode
    mask = df["_index"] == idx
    if not mask.any():
        abort(404, f"_index {idx} not found")

    for col, value in patch.items():
        if col not in df.columns:
            df[col] = ""
        if col != "_index":
            value = sanitize_value(value)
        df.loc[mask, col] = value

    save_csv()
    return jsonify(safe_json({"ok": True}))


def validate_existing_receipt(row, receipt_file):
    """
    Validate an already-attached receipt against the transaction.
    Returns: dict with 'match_score', 'ai_receipt_merchant', 'ai_receipt_date', 'ai_receipt_total'

    SMART VALIDATION: If receipt file exists and filename contains merchant/amount hints,
    trust it and mark as good. OCR is unreliable for validation.
    """
    try:
        # Get receipt file path (normalize by removing folder prefixes)
        normalized_file = receipt_file
        for prefix in ['receipts/', 'receipt-1/', 'receipt-2/', 'receipt-3/']:
            if normalized_file.startswith(prefix):
                normalized_file = normalized_file.replace(prefix, '', 1)
                break

        receipt_path = RECEIPT_DIR / normalized_file

        if not receipt_path.exists():
            # Try alternative locations
            for alt_folder in ['receipt-1', 'receipt-2', 'receipt-3']:
                alt_path = BASE_DIR / alt_folder / normalized_file
                if alt_path.exists():
                    receipt_path = alt_path
                    break

            if not receipt_path.exists():
                print(f"   ❌ Receipt file not found: {receipt_file}")
                return {'match_score': 0}

        # Transaction data
        tx_merchant = str(row.get('Chase Description', '')).lower()
        tx_amount = abs(float(row.get('Chase Amount', 0)))
        tx_date = str(row.get('Chase Date', ''))

        # Use Llama Vision to ACTUALLY READ the receipt image
        print(f"   🔍 Reading receipt with Llama Vision: {receipt_file}")
        ocr_result = gpt4_vision_extract(receipt_path)

        if not ocr_result:
            print(f"   ❌ Llama Vision failed to read receipt")
            return {'match_score': 0}

        # Extract OCR fields
        receipt_merchant = ocr_result.get('merchant_name', '') or ocr_result.get('merchant_normalized', '')
        receipt_date = ocr_result.get('receipt_date', '')
        receipt_total = ocr_result.get('total_amount', 0.0)

        # Transaction fields
        tx_merchant = str(row.get('Chase Description', ''))
        tx_amount = abs(float(row.get('Chase Amount', 0)))
        tx_date = str(row.get('Chase Date', ''))

        print(f"   📊 Transaction: {tx_merchant} | ${tx_amount:.2f} | {tx_date}")
        print(f"   📊 Receipt:     {receipt_merchant} | ${receipt_total:.2f} | {receipt_date}")

        # Calculate merchant similarity
        merchant_score = SequenceMatcher(None, tx_merchant.lower(), receipt_merchant.lower()).ratio()

        # Calculate amount match (10% tolerance, same as Gmail)
        if tx_amount > 0:
            amount_diff = abs(tx_amount - receipt_total)
            amount_tolerance = max(1.0, 0.10 * tx_amount)
            amount_score = max(0, 1 - (amount_diff / amount_tolerance))
        else:
            amount_score = 0

        # Calculate date match - BE LENIENT (dates often wrong/missing on receipts)
        date_score = 0
        if tx_date and receipt_date:
            try:
                tx_dt = datetime.strptime(tx_date, '%Y-%m-%d')
                rcpt_dt = datetime.strptime(receipt_date, '%Y-%m-%d')
                days_diff = abs((tx_dt - rcpt_dt).days)

                if days_diff == 0:
                    date_score = 1.0
                elif days_diff <= 1:
                    date_score = 0.9
                elif days_diff <= 3:
                    date_score = 0.8
                elif days_diff <= 7:
                    date_score = 0.7
                elif days_diff <= 14:
                    date_score = 0.6
                elif days_diff <= 30:
                    date_score = 0.5
                elif days_diff <= 60:
                    date_score = 0.3
                elif days_diff <= 90:
                    date_score = 0.1
                else:
                    date_score = 0  # More than 3 months is probably wrong
            except:
                date_score = 0.3  # Missing/bad date - don't penalize too much
        else:
            date_score = 0.3  # Missing date - don't penalize

        # 🎯 SMART SCORING - Amount is KING, Date is optional
        amount_is_perfect = amount_score > 0.90
        amount_is_good = amount_score > 0.80

        if amount_is_perfect:
            # Perfect amount match - merchant/date less important
            final_score = (0.8 * amount_score) + (0.15 * merchant_score) + (0.05 * date_score)
        elif amount_is_good:
            # Good amount match - merchant matters, date optional
            final_score = (0.7 * amount_score) + (0.25 * merchant_score) + (0.05 * date_score)
        else:
            # Amount not great - need merchant AND date to confirm
            final_score = (0.5 * amount_score) + (0.35 * merchant_score) + (0.15 * date_score)
        final_score_pct = int(final_score * 100)

        print(f"   📈 Scores: Amount={amount_score*100:.0f}% | Merchant={merchant_score*100:.0f}% | Date={date_score*100:.0f}%")
        print(f"   🎯 FINAL SCORE: {final_score_pct}%")

        return {
            'match_score': final_score_pct,
            'ai_receipt_merchant': receipt_merchant,
            'ai_receipt_date': receipt_date,
            'ai_receipt_total': receipt_total
        }

    except Exception as e:
        print(f"   ❌ Error validating receipt: {e}")
        return {'match_score': 0}


@app.route("/ai_match", methods=["POST"])
@login_required
def ai_match():
    """
    AI Receipt Matching endpoint
    - If receipt already attached: Validates it by OCR-ing and comparing to transaction
    - If no receipt: Searches for a matching receipt (local + Gmail)

    Body: {"_index": int}
    Returns: {"ok": bool, "result": {...updated fields...}, "message": str}
    """
    if not ORCHESTRATOR_AVAILABLE:
        return jsonify({"ok": False, "message": "AI matching not available"}), 503

    ensure_df()
    global df

    data = request.get_json(force=True) or {}
    if "_index" not in data:
        abort(400, "Missing _index")

    try:
        idx = int(data["_index"])
    except (TypeError, ValueError):
        abort(400, f"Invalid _index: {data.get('_index')}")

    # Get transaction row using direct database lookup (more reliable)
    row = None
    if USE_DATABASE and db:
        row_data = db.get_transaction_by_index(idx)
        if row_data:
            row = dict(row_data)
            # Map lowercase keys to UI-friendly names
            key_map = {'receipt_file': 'Receipt File', 'chase_description': 'Chase Description',
                      'chase_amount': 'Chase Amount', 'chase_date': 'Chase Date', 'business_type': 'Business Type'}
            for old_key, new_key in key_map.items():
                if old_key in row and new_key not in row:
                    row[new_key] = row[old_key]

    if not row:
        # Fallback to DataFrame lookup
        df = db.get_all_transactions() if USE_DATABASE and db else df
        if '_index' in df.columns:
            df['_index'] = pd.to_numeric(df['_index'], errors='coerce').fillna(0).astype(int)
        mask = df["_index"] == idx
        if not mask.any():
            print(f"DEBUG ai_match: idx={idx}, df._index dtype={df['_index'].dtype}, sample={df['_index'].head(3).tolist()}")
            abort(404, f"_index {idx} not found")
        row = df[mask].iloc[0].to_dict()

    # Check if receipt already attached
    existing_receipt = (row.get('Receipt File') or row.get('receipt_file') or '').strip()

    try:
        # ============================================================
        # MODE 1: VALIDATE EXISTING RECEIPT
        # ============================================================
        if existing_receipt and existing_receipt not in ['', 'None', 'NO_RECEIPT_NEEDED']:
            print(f"\n🔍 VALIDATING EXISTING RECEIPT: {existing_receipt}")

            result = validate_existing_receipt(row, existing_receipt)
            match_score = result.get('match_score', 0)

            # Update Review Status based on validation
            if match_score >= 70:
                # Good match - mark as good (lowercase for frontend)
                update_data = {
                    'Review Status': 'good',
                    'ai_receipt_merchant': result.get('ai_receipt_merchant', ''),
                    'ai_receipt_date': result.get('ai_receipt_date', ''),
                    'ai_receipt_total': result.get('ai_receipt_total', 0.0),
                    'AI Confidence': match_score,
                }

                # Process through Merchant Intelligence
                if process_transaction_mi:
                    try:
                        mi_result = process_transaction_mi(row)
                        update_data.update({
                            'mi_merchant': mi_result.get('mi_merchant', ''),
                            'mi_category': mi_result.get('mi_category', ''),
                            'mi_description': mi_result.get('mi_description', ''),
                            'mi_confidence': mi_result.get('mi_confidence', 0),
                            'mi_is_subscription': mi_result.get('mi_is_subscription', 0),
                            'mi_subscription_name': mi_result.get('mi_subscription_name', ''),
                            'mi_processed_at': mi_result.get('mi_processed_at', ''),
                        })
                    except Exception as e:
                        print(f"   ⚠️ MI processing error: {e}")

                # Apply update
                if USE_DATABASE and db:
                    db.update_transaction(idx, update_data)
                    df = db.get_all_transactions()
                else:
                    for col, value in update_data.items():
                        if col not in df.columns:
                            df[col] = ""
                        df.loc[mask, col] = sanitize_value(value)
                    save_csv()

                return jsonify({
                    "ok": True,
                    "result": {**update_data, 'Receipt File': existing_receipt},
                    "message": f"✅ Receipt validated! ({match_score}% confidence)"
                })
            else:
                # Poor match - mark as bad (lowercase for frontend)
                update_data = {
                    'Review Status': 'bad',
                    'AI Confidence': match_score,
                }

                # Apply update
                if USE_DATABASE and db:
                    db.update_transaction(idx, update_data)
                    df = db.get_all_transactions()
                else:
                    for col, value in update_data.items():
                        if col not in df.columns:
                            df[col] = ""
                        df.loc[mask, col] = sanitize_value(value)
                    save_csv()

                return jsonify({
                    "ok": False,
                    "result": {**update_data, 'Receipt File': existing_receipt},
                    "message": f"❌ Receipt doesn't match well ({match_score}% confidence) - Marked as Bad"
                })

        # ============================================================
        # MODE 2: NO RECEIPT ATTACHED - RETURN ERROR
        # ============================================================
        # 'A' button is for VALIDATION only, not searching
        # Use "Find Missing Receipts" feature to search for receipts
        print(f"\n⚠️ NO RECEIPT TO VALIDATE (use 'Find Missing Receipts' to search)")

        return jsonify({
            "ok": False,
            "message": "⚠️ No receipt attached. Use 'Find Missing Receipts' to search for receipts."
        }), 400

        # Commented out MODE 2 - Search is now handled by "Find Missing Receipts" only
        """
        # Call orchestrator to find best receipt
        result = find_best_receipt_for_transaction(
            row,
            enable_gmail=True  # Enable Gmail search
        )

        match_score = result.get('match_score', 0)
        receipt_file = result.get('receipt_file', '')

        # Check if we found a match (≥70% confidence)
        if receipt_file and match_score >= 70:
            # Update transaction with matched receipt
            update_data = {
                'Receipt File': receipt_file,
                'Review Status': 'good',  # Auto-mark as good (lowercase for frontend)
                'ai_receipt_merchant': result.get('ai_receipt_merchant', ''),
                'ai_receipt_date': result.get('ai_receipt_date', ''),
                'ai_receipt_total': result.get('ai_receipt_total', 0.0),
                'AI Confidence': match_score,
            }

            # Apply update
            if USE_DATABASE and db:
                db.update_transaction(idx, update_data)
                df = db.get_all_transactions()
            else:
                for col, value in update_data.items():
                    if col not in df.columns:
                        df[col] = ""
                    df.loc[mask, col] = sanitize_value(value)
                save_csv()

            # Log audit
            if AUDIT_LOGGING_ENABLED and audit_logger:
                audit_logger.log_receipt_attach(
                    transaction_index=idx,
                    old_receipt=row.get('Receipt File', ''),
                    new_receipt=receipt_file,
                    confidence=match_score,
                    source='ai_match',
                    notes=f"Method: {result.get('method', 'unknown')}, Source: {result.get('source', 'unknown')}"
                )

            return jsonify({
                "ok": True,
                "result": update_data,
                "message": f"Receipt matched! {receipt_file[:60]}"
            })
        else:
            # No good match found - mark as "bad" (AI searched but found nothing)
            update_data = {
                'Review Status': 'bad',
                'AI Confidence': match_score,
                # Clear receipt file if it was set
                'Receipt File': ''
            }

            # Apply update to database
            if USE_DATABASE and db:
                db.update_transaction(idx, update_data)
                df = db.get_all_transactions()
            else:
                for col, value in update_data.items():
                    if col not in df.columns:
                        df[col] = ""
                    df.loc[mask, col] = sanitize_value(value)
                save_csv()

            return jsonify({
                "ok": False,
                "result": update_data,
                "message": f"No receipt found (best match: {match_score}%) - Marked as Bad"
            })
        """  # End of commented-out MODE 2 search code

    except Exception as e:
        import traceback
        error_details = traceback.format_exc()
        print(f"\n❌ AI MATCH ERROR for index {idx}:")
        print(f"   Transaction: {row.get('Chase Description', 'Unknown')[:50]}")
        print(f"   Amount: ${abs(float(row.get('Chase Amount', 0))):.2f}")
        print(f"   Date: {row.get('Chase Date', 'Unknown')}")
        print(f"   Receipt File: {existing_receipt}")
        print(f"   Error: {str(e)}")
        print(f"\n   Full traceback:")
        print(error_details)

        # Return detailed error message to client
        return jsonify({
            "ok": False,
            "message": f"Error processing transaction {idx}: {str(e)}"
        }), 500


@app.route("/ai_note", methods=["POST"])
def ai_note():
    """
    AI Note Generation endpoint
    Body: {"_index": int}
    Returns: {"ok": bool, "note": str}
    """
    if not ORCHESTRATOR_AVAILABLE:
        return jsonify({"ok": False, "message": "AI note generation not available"}), 503

    ensure_df()
    global df

    data = request.get_json(force=True) or {}
    if "_index" not in data:
        abort(400, "Missing _index")

    try:
        idx = int(data["_index"])
    except (TypeError, ValueError):
        abort(400, f"Invalid _index: {data.get('_index')}")

    # Get transaction row
    if USE_DATABASE and db:
        df = db.get_all_transactions()

    mask = df["_index"] == idx
    if not mask.any():
        abort(404, f"_index {idx} not found")

    row = df[mask].iloc[0].to_dict()

    try:
        # Generate AI note
        note = ai_generate_note(row)

        if note:
            # Update transaction with AI note
            if USE_DATABASE and db:
                db.update_transaction(idx, {'AI Note': note})
                df = db.get_all_transactions()
            else:
                if 'AI Note' not in df.columns:
                    df['AI Note'] = ""
                df.loc[mask, 'AI Note'] = sanitize_value(note)
                save_csv()

            # Log audit
            if AUDIT_LOGGING_ENABLED and audit_logger:
                audit_logger.log_event(
                    event_type='ai_note',
                    transaction_index=idx,
                    metadata={'note_length': len(note)}
                )

            return jsonify({"ok": True, "note": note})
        else:
            return jsonify({"ok": False, "message": "Failed to generate note"})

    except Exception as e:
        print(f"❌ AI Note error: {e}")
        return jsonify({"ok": False, "message": f"Error: {str(e)}"}), 500


# =============================================================================
# GEMINI-POWERED AI ENDPOINTS
# =============================================================================

@app.route("/api/ai/categorize", methods=["POST"])
def api_ai_categorize():
    """
    Gemini-powered AI transaction categorization.

    POST body: {"_index": int} or {"merchant": str, "amount": float, "date": str}
    Returns: {"ok": true, "category": str, "business_type": str, "confidence": int, "reasoning": str}
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    # Get transaction data either from _index or direct params
    if "_index" in data:
        ensure_df()
        idx = int(data["_index"])
        mask = df["_index"] == idx
        if not mask.any():
            return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404
        row = df[mask].iloc[0].to_dict()
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
        date = row.get("Chase Date") or row.get("transaction_date") or ""
        category_hint = row.get("Chase Category") or row.get("category") or ""
    else:
        merchant = data.get("merchant", "")
        amount = float(data.get("amount", 0))
        date = data.get("date", "")
        category_hint = data.get("category_hint", "")
        idx = None

    if not merchant:
        return jsonify({"ok": False, "error": "No merchant provided"}), 400

    # Use Gemini to categorize
    result = gemini_categorize_transaction(merchant, amount, date, category_hint)

    # If _index provided, save the categorization
    if idx is not None and result.get("confidence", 0) >= 60:
        update_data = {}
        if result.get("category"):
            update_data["category"] = result["category"]
        if result.get("business_type"):
            update_data["Business Type"] = result["business_type"]
        if update_data:
            update_row_by_index(idx, update_data, source="ai_categorize")

    return jsonify({
        "ok": True,
        "category": result.get("category"),
        "business_type": result.get("business_type"),
        "confidence": result.get("confidence", 0),
        "reasoning": result.get("reasoning", ""),
        "_index": idx
    })


@app.route("/api/ai/note", methods=["POST"])
def api_ai_note_gemini():
    """
    Gemini-powered AI note generation (alternative to /ai_note which uses OpenAI).

    POST body: {"_index": int} or {"merchant": str, "amount": float, "date": str, "category": str, "business_type": str}
    Returns: {"ok": true, "note": str, "confidence": int}
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    # Get transaction data either from _index or direct params
    if "_index" in data:
        ensure_df()
        idx = int(data["_index"])
        mask = df["_index"] == idx
        if not mask.any():
            return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404
        row = df[mask].iloc[0].to_dict()
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
        date = row.get("Chase Date") or row.get("transaction_date") or ""
        category = row.get("Chase Category") or row.get("category") or ""
        business_type = row.get("Business Type") or ""
    else:
        merchant = data.get("merchant", "")
        amount = float(data.get("amount", 0))
        date = data.get("date", "")
        category = data.get("category", "")
        business_type = data.get("business_type", "")
        idx = None

    if not merchant:
        return jsonify({"ok": False, "error": "No merchant provided"}), 400

    # Use Gemini to generate note
    result = gemini_generate_ai_note(merchant, amount, date, category, business_type)

    # If _index provided, save the note
    if idx is not None and result.get("note"):
        update_row_by_index(idx, {"AI Note": result["note"]}, source="ai_note_gemini")

    return jsonify({
        "ok": True,
        "note": result.get("note", ""),
        "confidence": result.get("confidence", 0),
        "_index": idx
    })


@app.route("/api/ai/auto-process", methods=["POST"])
def api_ai_auto_process():
    """
    One-click AI processing: categorize + generate note in one call.

    POST body: {"_index": int}
    Returns: {"ok": true, "category": str, "business_type": str, "note": str, "confidence": int}
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    if "_index" not in data:
        return jsonify({"ok": False, "error": "Missing _index"}), 400

    ensure_df()
    idx = int(data["_index"])
    mask = df["_index"] == idx
    if not mask.any():
        return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404

    row = df[mask].iloc[0].to_dict()
    merchant = row.get("Chase Description") or row.get("merchant") or ""
    amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
    date = row.get("Chase Date") or row.get("transaction_date") or ""
    category_hint = row.get("Chase Category") or row.get("category") or ""

    if not merchant:
        return jsonify({"ok": False, "error": "No merchant in transaction"}), 400

    # Step 1: Categorize (pass full row for context)
    cat_result = gemini_categorize_transaction(merchant, amount, date, category_hint, row=row)

    # Step 2: Generate note with category context (pass full row)
    note_result = gemini_generate_ai_note(
        merchant, amount, date,
        cat_result.get("category", ""),
        cat_result.get("business_type", "Down Home"),
        row=row
    )

    # Save all updates
    update_data = {}
    if cat_result.get("category"):
        update_data["category"] = cat_result["category"]
    if cat_result.get("business_type"):
        update_data["Business Type"] = cat_result["business_type"]
    if note_result.get("note"):
        update_data["AI Note"] = note_result["note"]

    if update_data:
        update_row_by_index(idx, update_data, source="ai_auto_process")

    return jsonify({
        "ok": True,
        "category": cat_result.get("category"),
        "business_type": cat_result.get("business_type"),
        "note": note_result.get("note"),
        "confidence": min(cat_result.get("confidence", 0), note_result.get("confidence", 0)),
        "reasoning": cat_result.get("reasoning", ""),
        "_index": idx
    })


@app.route("/api/ai/regenerate-notes", methods=["POST"])
def api_ai_regenerate_notes():
    """
    Regenerate AI notes for transactions matching certain criteria.
    Useful for fixing notes that incorrectly reference birthdays or other personal events.

    POST body:
    {
        "filter": "birthday" | "vague" | "all",  # What notes to regenerate
        "indexes": [int, ...],  # Optional: specific indexes to regenerate
        "limit": 50,  # Max transactions to process (default 50, max 200)
        "dry_run": false  # If true, just return what would be regenerated
    }

    Returns: {"ok": true, "processed": int, "updated": int, "results": [...]}
    """
    # Auth check - allow admin key, auth password, or session
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    if admin_key not in (expected_key, auth_password):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}
    filter_type = data.get("filter", "birthday")
    indexes = data.get("indexes", [])
    limit = min(data.get("limit", 50), 200)
    dry_run = data.get("dry_run", False)

    ensure_df()

    # Keywords that indicate problematic notes
    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']
    vague_keywords = ['business expense', 'business meal', 'client meeting', 'software subscription',
                      'travel expense', 'meal with team', 'various business']

    results = []
    updated_count = 0

    # Get transactions to check
    if indexes:
        # Use provided indexes
        candidates = df[df["_index"].isin(indexes)]
    else:
        # Find all transactions with notes (check all possible column names)
        note_cols = ["AI Note", "ai_note", "notes"]
        has_notes = None
        for col in note_cols:
            if col in df.columns:
                col_has_notes = df[col].fillna("").str.len() > 0
                has_notes = col_has_notes if has_notes is None else (has_notes | col_has_notes)

        if has_notes is not None:
            candidates = df[has_notes]
        else:
            candidates = df.head(0)  # Empty

    # Filter by criteria
    filtered_rows = []
    for _, row in candidates.head(limit * 3).iterrows():  # Check more than limit to find matches
        # Check all possible note fields
        ai_note = str(
            row.get("AI Note", "") or
            row.get("ai_note", "") or
            row.get("notes", "") or
            ""
        ).lower()

        if not ai_note:
            continue

        should_include = False

        if filter_type == "birthday":
            should_include = any(kw in ai_note for kw in birthday_keywords)
        elif filter_type == "vague":
            should_include = any(kw in ai_note for kw in vague_keywords)
        elif filter_type == "all":
            should_include = True

        if should_include:
            filtered_rows.append(row)

        if len(filtered_rows) >= limit:
            break

    # Process each matching transaction
    for row in filtered_rows:
        idx = int(row["_index"])
        old_note = row.get("AI Note", "")
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
        date = row.get("Chase Date") or row.get("transaction_date") or ""
        category = row.get("category") or row.get("Chase Category") or ""
        business_type = row.get("Business Type") or "Down Home"

        result_entry = {
            "_index": idx,
            "merchant": merchant,
            "old_note": old_note,
            "new_note": None,
            "status": "pending"
        }

        if dry_run:
            result_entry["status"] = "would_update"
            results.append(result_entry)
            continue

        # Regenerate the note
        try:
            note_result = gemini_generate_ai_note(
                merchant, amount, date, category, business_type,
                row=row.to_dict()
            )

            new_note = note_result.get("note", "")

            if new_note and new_note != old_note:
                # Update the transaction
                update_row_by_index(idx, {"AI Note": new_note}, source="ai_regenerate")
                result_entry["new_note"] = new_note
                result_entry["status"] = "updated"
                updated_count += 1
            else:
                result_entry["status"] = "no_change"

        except Exception as e:
            result_entry["status"] = "error"
            result_entry["error"] = str(e)

        results.append(result_entry)

    return jsonify({
        "ok": True,
        "filter": filter_type,
        "dry_run": dry_run,
        "processed": len(results),
        "updated": updated_count,
        "results": results
    })


@app.route("/api/ai/find-problematic-notes", methods=["GET"])
def api_ai_find_problematic_notes():
    """
    Find transactions with AI notes that reference birthdays or are too vague.
    Useful for identifying notes that need regeneration.

    Query params:
    - filter: "birthday" | "vague" | "all" (default: "birthday")
    - limit: max results (default: 100)

    Returns: {"ok": true, "count": int, "transactions": [...]}
    """
    # Auth check - allow admin key, auth password, or session
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    if admin_key not in (expected_key, auth_password):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    filter_type = request.args.get("filter", "birthday")
    limit = min(int(request.args.get("limit", 100)), 500)

    ensure_df()

    # Keywords
    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']
    vague_keywords = ['business expense', 'business meal', 'client meeting', 'software subscription',
                      'travel expense', 'meal with team', 'various business']

    matches = []

    for _, row in df.iterrows():
        # Check all possible note fields (AI Note, ai_note, notes)
        ai_note = str(
            row.get("AI Note", "") or
            row.get("ai_note", "") or
            row.get("notes", "") or
            ""
        ).lower()

        if not ai_note:
            continue

        matched_keywords = []

        if filter_type in ["birthday", "all"]:
            for kw in birthday_keywords:
                if kw in ai_note:
                    matched_keywords.append(kw)

        if filter_type in ["vague", "all"]:
            for kw in vague_keywords:
                if kw in ai_note:
                    matched_keywords.append(kw)

        if matched_keywords:
            matches.append({
                "_index": int(row["_index"]),
                "merchant": row.get("Chase Description") or row.get("merchant") or "",
                "amount": row.get("Chase Amount") or row.get("amount") or 0,
                "date": row.get("Chase Date") or row.get("transaction_date") or "",
                "ai_note": row.get("AI Note", "") or row.get("ai_note", ""),
                "matched_keywords": list(set(matched_keywords))
            })

        if len(matches) >= limit:
            break

    return jsonify({
        "ok": True,
        "filter": filter_type,
        "count": len(matches),
        "transactions": matches
    })


@app.route("/api/ai/regenerate-birthday-notes", methods=["POST"])
def api_ai_regenerate_birthday_notes():
    """
    Find and regenerate AI notes that reference birthdays.
    Uses direct database access to bypass df caching issues.

    POST body: {
        "dry_run": bool (default: true),
        "limit": int (default: 100, max: 200)
    }

    Returns: {"ok": true, "found": int, "updated": int, "results": [...]}
    """
    # Auth check - allow admin key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    if admin_key not in (expected_key, auth_password):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not USE_DATABASE or not db:
        return jsonify({'error': 'Database not available'}), 503

    data = request.get_json(force=True) or {}
    dry_run = data.get("dry_run", True)
    limit = min(int(data.get("limit", 100)), 200)

    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']

    # Build SQL LIKE clauses (escape single quotes for SQL)
    like_clauses = []
    for kw in birthday_keywords:
        # Escape single quotes for MySQL
        escaped_kw = kw.replace("'", "''")
        like_clauses.append(f"LOWER(ai_note) LIKE '%{escaped_kw}%'")

    # Query database directly for birthday notes
    conn, _ = get_db_connection()
    if not conn:
        return jsonify({'error': 'Database connection failed'}), 503

    try:
        cursor = conn.cursor()
        query = f"""
            SELECT id, _index, chase_description, chase_amount, chase_date,
                   chase_category, business_type, ai_note
            FROM transactions
            WHERE ai_note IS NOT NULL
            AND ai_note != ''
            AND ({' OR '.join(like_clauses)})
            ORDER BY chase_date DESC
            LIMIT {limit}
        """
        cursor.execute(query)
        rows = cursor.fetchall()
        cursor.close()
    except Exception as e:
        return_db_connection(conn)
        return jsonify({'error': f'Query failed: {e}'}), 500

    if not rows:
        return_db_connection(conn)
        return jsonify({
            'ok': True,
            'found': 0,
            'updated': 0,
            'message': 'No birthday-referenced notes found',
            'results': []
        })

    results = []
    updated_count = 0

    for row in rows:
        tx_id = row['id']
        idx = row['_index']
        merchant = row.get('chase_description', '')
        amount = parse_amount_str(row.get('chase_amount', 0))
        date = row.get('chase_date', '')
        category = row.get('chase_category', '')
        business_type = row.get('business_type', 'Down Home')
        old_note = row.get('ai_note', '')

        result_entry = {
            'id': tx_id,
            '_index': idx,
            'merchant': merchant,
            'old_note': old_note,
            'new_note': None,
            'status': 'pending'
        }

        if dry_run:
            result_entry['status'] = 'would_update'
            results.append(result_entry)
            continue

        # Regenerate note using Gemini (with birthday filtering now active)
        try:
            note_result = gemini_generate_ai_note(
                merchant, amount, str(date), category, business_type
            )
            new_note = note_result.get('note', '')

            if new_note and new_note != old_note:
                # Update directly in database
                try:
                    update_cursor = conn.cursor()
                    update_cursor.execute(
                        "UPDATE transactions SET ai_note = %s WHERE id = %s",
                        (new_note, tx_id)
                    )
                    conn.commit()
                    update_cursor.close()

                    result_entry['new_note'] = new_note
                    result_entry['status'] = 'updated'
                    updated_count += 1
                except Exception as e:
                    result_entry['status'] = 'error'
                    result_entry['error'] = f'DB update failed: {e}'
            else:
                result_entry['status'] = 'no_change'
                result_entry['new_note'] = new_note

        except Exception as e:
            result_entry['status'] = 'error'
            result_entry['error'] = str(e)

        results.append(result_entry)

    return_db_connection(conn)

    # Reload df to sync with database changes
    if updated_count > 0:
        load_data(force_refresh=True)

    return jsonify({
        'ok': True,
        'dry_run': dry_run,
        'found': len(rows),
        'updated': updated_count,
        'results': results
    })


@app.route("/api/ai/batch-categorize", methods=["POST"])
def api_ai_batch_categorize():
    """
    Batch AI categorization for multiple transactions.

    POST body: {"indexes": [int, int, ...], "limit": 50}
    Returns: {"ok": true, "processed": int, "results": [...]}
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}
    indexes = data.get("indexes", [])
    limit = min(data.get("limit", 50), 100)  # Max 100 at once

    ensure_df()

    # If no indexes specified, find transactions without categories
    if not indexes:
        uncategorized = df[
            (df.get("category", "").fillna("") == "") &
            (df.get("Business Type", "").fillna("") == "")
        ]
        indexes = uncategorized["_index"].tolist()[:limit]

    results = []
    for idx in indexes[:limit]:
        try:
            mask = df["_index"] == idx
            if not mask.any():
                continue

            row = df[mask].iloc[0].to_dict()
            merchant = row.get("Chase Description") or row.get("merchant") or ""
            amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
            date = row.get("Chase Date") or row.get("transaction_date") or ""
            category_hint = row.get("Chase Category") or ""

            if not merchant:
                continue

            result = gemini_categorize_transaction(merchant, amount, date, category_hint)

            # Save if confident
            if result.get("confidence", 0) >= 50:
                update_data = {}
                if result.get("category"):
                    update_data["category"] = result["category"]
                if result.get("business_type"):
                    update_data["Business Type"] = result["business_type"]
                if update_data:
                    update_row_by_index(idx, update_data, source="batch_categorize")

            results.append({
                "_index": idx,
                "merchant": merchant,
                "category": result.get("category"),
                "business_type": result.get("business_type"),
                "confidence": result.get("confidence", 0)
            })

        except Exception as e:
            print(f"⚠️ Batch categorize error for {idx}: {e}")
            continue

    return jsonify({
        "ok": True,
        "processed": len(results),
        "results": results
    })


# =============================================================================
# APPLE RECEIPT SPLITTER ENDPOINTS
# =============================================================================

@app.route("/api/ai/apple-split-analyze", methods=["POST"])
def api_ai_apple_split_analyze():
    """
    Analyze an Apple receipt image to identify personal vs business items.
    Does NOT create split transactions - just returns the analysis.

    POST body: {"receipt_path": "applecombill_xxx.jpg"} or {"transaction_id": 123}
    Returns: Analysis with items classified by business type
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not APPLE_SPLITTER_AVAILABLE:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    receipt_path = data.get("receipt_path")
    transaction_id = data.get("transaction_id")

    # If transaction_id provided, look up the receipt
    if transaction_id and not receipt_path:
        try:
            conn, db_type = get_db_connection()
            cursor = db_execute(conn, db_type,
                "SELECT receipt_file FROM transactions WHERE id = ?",
                (transaction_id,))
            row = cursor.fetchone()
            return_db_connection(conn)
            if row and row.get('receipt_file'):
                receipt_path = row['receipt_file']
            else:
                return jsonify({'error': f'No receipt found for transaction {transaction_id}'}), 404
        except Exception as e:
            return jsonify({'error': f'Database error: {e}'}), 500

    if not receipt_path:
        return jsonify({'error': 'receipt_path or transaction_id required'}), 400

    # Build full path
    if not receipt_path.startswith('/'):
        full_path = str(RECEIPT_DIR / receipt_path)
    else:
        full_path = receipt_path

    if not os.path.exists(full_path):
        return jsonify({'error': f'Receipt file not found: {receipt_path}'}), 404

    try:
        result = split_apple_receipt(full_path)
        return jsonify({
            "ok": True,
            "analysis": result
        })
    except Exception as e:
        print(f"Apple split analyze error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/ai/apple-split-execute", methods=["POST"])
def api_ai_apple_split_execute():
    """
    Execute an Apple receipt split - creates new split transactions in the database.
    Links the SAME receipt to ALL split transactions.

    POST body: {"transaction_id": 123} or {"transaction_id": 123, "receipt_path": "xxx.jpg"}
    Returns: Created split transactions with linked receipt
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not APPLE_SPLITTER_AVAILABLE:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    transaction_id = data.get("transaction_id")
    receipt_path = data.get("receipt_path")

    if not transaction_id:
        return jsonify({'error': 'transaction_id required'}), 400

    try:
        result = auto_split_transaction(transaction_id, receipt_path)

        if result.get('error'):
            return jsonify({'error': result['error']}), 400

        # Refresh dataframe to pick up new transactions
        global df
        df = None
        ensure_df()

        return jsonify({
            "ok": True,
            "result": result
        })
    except Exception as e:
        print(f"Apple split execute error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/ai/apple-split-candidates", methods=["GET"])
def api_ai_apple_split_candidates():
    """
    Find Apple transactions that might need splitting.

    Query params: limit (default 50)
    Returns: List of Apple transactions with their receipts
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not APPLE_SPLITTER_AVAILABLE:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    limit = request.args.get('limit', 50, type=int)

    try:
        candidates = find_apple_transactions_to_split(limit=limit)
        return jsonify({
            "ok": True,
            "count": len(candidates),
            "candidates": candidates
        })
    except Exception as e:
        print(f"Apple split candidates error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/ai/apple-split-all", methods=["POST"])
def api_ai_apple_split_all():
    """
    Process all Apple transactions - analyze and split where needed.

    POST body: {"dry_run": true/false, "limit": 50}
    Returns: Summary of splits performed
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not APPLE_SPLITTER_AVAILABLE:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    dry_run = data.get("dry_run", True)
    limit = data.get("limit", 50)

    try:
        results = process_all_apple_splits(dry_run=dry_run, limit=limit)

        # Refresh dataframe if we made changes
        if not dry_run and results.get('splits_created', 0) > 0:
            global df
            df = None
            ensure_df()

        return jsonify({
            "ok": True,
            "dry_run": dry_run,
            "results": results
        })
    except Exception as e:
        print(f"Apple split all error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# CONTACT MANAGEMENT ENDPOINTS
# =============================================================================

@app.route("/api/contacts/search", methods=["GET"])
def api_contacts_search():
    """
    Search contacts by name, company, or title.

    Query params: q (search query), limit (default 10)
    Returns: List of matching contacts
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    query = request.args.get('q', '')
    limit = request.args.get('limit', 10, type=int)

    if not query:
        return jsonify({'error': 'Search query (q) required'}), 400

    try:
        results = search_contacts(query, limit=limit)
        return jsonify({
            "ok": True,
            "query": query,
            "count": len(results),
            "contacts": results
        })
    except Exception as e:
        print(f"Contact search error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/stats", methods=["GET"])
def api_contacts_stats():
    """
    Get contact database statistics.

    Returns: Summary of contacts by category, priority, etc.
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    try:
        stats = get_contact_stats()
        return jsonify({
            "ok": True,
            "stats": stats
        })
    except Exception as e:
        print(f"Contact stats error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/attendees", methods=["POST"])
def api_contacts_attendees():
    """
    Find likely attendees for an expense/meeting.

    POST body: {"merchant": "...", "date": "...", "business_type": "...", "amount": 0}
    Returns: List of likely attendees with confidence scores
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    data = request.get_json(force=True) or {}
    merchant = data.get("merchant", "")
    date = data.get("date", "")
    business_type = data.get("business_type", "")
    amount = data.get("amount", 0)
    calendar_attendees = data.get("calendar_attendees", [])
    imessage_context = data.get("imessage_context", [])

    if not merchant:
        return jsonify({'error': 'merchant required'}), 400

    try:
        attendees = find_attendees_for_expense(
            merchant=merchant,
            date=date,
            business_type=business_type,
            amount=amount,
            calendar_attendees=calendar_attendees,
            imessage_context=imessage_context
        )
        return jsonify({
            "ok": True,
            "merchant": merchant,
            "count": len(attendees),
            "attendees": attendees
        })
    except Exception as e:
        print(f"Contact attendees error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/<int:contact_id>", methods=["GET"])
def api_contacts_get(contact_id):
    """
    Get a specific contact by ID.
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    try:
        manager = get_contact_manager()
        contact = manager.get_contact_by_id(contact_id)
        if not contact:
            return jsonify({'error': f'Contact {contact_id} not found'}), 404

        return jsonify({
            "ok": True,
            "contact": contact.to_dict()
        })
    except Exception as e:
        print(f"Contact get error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/category/<category>", methods=["GET"])
def api_contacts_by_category(category):
    """
    Get contacts by category.

    Query params: limit (default 50)
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    limit = request.args.get('limit', 50, type=int)

    try:
        manager = get_contact_manager()
        contacts = manager.search_by_category(category, limit=limit)
        return jsonify({
            "ok": True,
            "category": category,
            "count": len(contacts),
            "contacts": [c.to_dict() for c in contacts]
        })
    except Exception as e:
        print(f"Contact category error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/high-priority", methods=["GET"])
def api_contacts_high_priority():
    """
    Get high-priority contacts.

    Query params: limit (default 50)
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_MANAGER_AVAILABLE:
        return jsonify({'error': 'Contact manager not available'}), 503

    limit = request.args.get('limit', 50, type=int)

    try:
        manager = get_contact_manager()
        contacts = manager.get_high_priority_contacts(limit=limit)
        return jsonify({
            "ok": True,
            "count": len(contacts),
            "contacts": [c.to_dict() for c in contacts]
        })
    except Exception as e:
        print(f"Contact high priority error: {e}")
        return jsonify({'error': str(e)}), 500


# =============================================================================
# APPLE CONTACTS SYNC API
# =============================================================================

@app.route("/api/contacts/apple/stats", methods=["GET"])
@login_required
def apple_contacts_stats():
    """
    Get statistics about Apple AddressBook (local macOS Contacts)
    Returns source counts without syncing
    """
    if not APPLE_CONTACTS_AVAILABLE:
        return jsonify({'error': 'Apple Contacts sync not available'}), 503

    try:
        stats = get_apple_contacts_stats()
        return jsonify({
            "ok": True,
            "available": stats.get('available', False),
            "total_contacts": stats.get('total_contacts', 0),
            "sources": stats.get('sources', [])
        })
    except Exception as e:
        print(f"Apple contacts stats error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/apple/search", methods=["GET"])
@login_required
def apple_contacts_search_api():
    """
    Search Apple Contacts directly (without full sync)
    Query params: q (required), limit (optional, default 20)
    """
    if not APPLE_CONTACTS_AVAILABLE:
        return jsonify({'error': 'Apple Contacts sync not available'}), 503

    query = request.args.get('q', '').strip()
    if not query:
        return jsonify({'error': 'Missing search query (q parameter)'}), 400

    limit = request.args.get('limit', 20, type=int)

    try:
        results = search_apple_contacts(query, limit=limit)
        return jsonify({
            "ok": True,
            "query": query,
            "count": len(results),
            "contacts": results
        })
    except Exception as e:
        print(f"Apple contacts search error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/contacts/apple/sync", methods=["POST"])
@login_required
def apple_contacts_sync_api():
    """
    Sync Apple Contacts to contacts.csv
    This reads all AddressBook sources, deduplicates, and merges with existing
    """
    if not APPLE_CONTACTS_AVAILABLE:
        return jsonify({'error': 'Apple Contacts sync not available'}), 503

    try:
        result = sync_apple_contacts()
        return jsonify({
            "ok": True,
            "status": result.get('status', 'unknown'),
            "stats": result.get('stats', {}),
            "total_contacts": result.get('total_contacts', 0)
        })
    except Exception as e:
        print(f"Apple contacts sync error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ATLAS RELATIONSHIP INTELLIGENCE API
# =============================================================================

@app.route("/api/atlas/status", methods=["GET"])
@login_required
def atlas_status_api():
    """Get ATLAS system status and capabilities"""
    return jsonify({
        "ok": True,
        "available": ATLAS_AVAILABLE,
        "features": {
            "imessage": ATLAS_AVAILABLE,
            "interaction_tracking": ATLAS_AVAILABLE,
            "commitments": ATLAS_AVAILABLE,
            "relationship_health": ATLAS_AVAILABLE,
            "meeting_prep": ATLAS_AVAILABLE,
            "nudges": ATLAS_AVAILABLE
        }
    })


@app.route("/api/atlas/imessage/recent", methods=["GET"])
@login_required
def atlas_imessage_recent():
    """Get recent iMessage contacts with message counts"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        days = request.args.get('days', 7, type=int)
        limit = request.args.get('limit', 20, type=int)

        reader = iMessageReader()
        contacts = reader.get_recent_contacts(days=days, limit=limit)

        return jsonify({
            "ok": True,
            "days": days,
            "contacts": contacts
        })
    except Exception as e:
        print(f"ATLAS iMessage error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/imessage/conversation/<path:handle>", methods=["GET"])
@login_required
def atlas_imessage_conversation(handle: str):
    """Get conversation history with a specific contact"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 100, type=int)

        reader = iMessageReader()
        messages = reader.get_messages_with_contact(handle, days=days, limit=limit)

        return jsonify({
            "ok": True,
            "handle": handle,
            "messages": messages
        })
    except Exception as e:
        print(f"ATLAS conversation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/relationship/<path:identifier>", methods=["GET"])
@login_required
def atlas_relationship_health(identifier: str):
    """Get relationship health score for a contact"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        analyzer = RelationshipHealthAnalyzer()
        health = analyzer.calculate_health(identifier)

        if health:
            return jsonify({
                "ok": True,
                "identifier": identifier,
                "health": {
                    "overall_score": health.overall_score,
                    "trend": health.trend.value if health.trend else "unknown",
                    "last_interaction": health.last_interaction.isoformat() if health.last_interaction else None,
                    "recency_score": health.recency_score,
                    "frequency_score": health.frequency_score,
                    "sentiment_score": health.sentiment_score,
                    "reciprocity_score": health.reciprocity_score,
                    "commitment_score": health.commitment_score,
                    "insights": health.insights
                }
            })
        else:
            return jsonify({
                "ok": True,
                "identifier": identifier,
                "health": None,
                "message": "No interaction data found for this contact"
            })
    except Exception as e:
        print(f"ATLAS relationship error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/meeting-prep/<path:identifier>", methods=["GET"])
@login_required
def atlas_meeting_prep(identifier: str):
    """Generate meeting prep brief for a contact"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        generator = MeetingPrepGenerator()
        brief = generator.generate_brief(identifier)

        if brief:
            return jsonify({
                "ok": True,
                "identifier": identifier,
                "brief": {
                    "contact_name": brief.contact_name,
                    "last_meeting": brief.last_meeting.isoformat() if brief.last_meeting else None,
                    "meeting_count_30d": brief.meeting_count_30d,
                    "open_commitments": [
                        {"content": c.content, "due_date": c.due_date.isoformat() if c.due_date else None, "status": c.status.value}
                        for c in (brief.open_commitments or [])
                    ],
                    "recent_topics": brief.recent_topics,
                    "relationship_summary": brief.relationship_summary,
                    "talking_points": brief.talking_points,
                    "context_notes": brief.context_notes
                }
            })
        else:
            return jsonify({
                "ok": True,
                "identifier": identifier,
                "brief": None,
                "message": "No data available to generate meeting brief"
            })
    except Exception as e:
        print(f"ATLAS meeting prep error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/nudges", methods=["GET"])
@login_required
def atlas_get_nudges():
    """Get proactive relationship nudges"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        limit = request.args.get('limit', 10, type=int)
        priority = request.args.get('priority', None)

        engine = NudgeEngine()
        nudges = engine.generate_nudges(limit=limit)

        if priority:
            nudges = [n for n in nudges if n.priority == priority]

        return jsonify({
            "ok": True,
            "nudges": [
                {
                    "type": n.type,
                    "priority": n.priority,
                    "contact_name": n.contact_name,
                    "contact_identifier": n.contact_identifier,
                    "message": n.message,
                    "suggested_action": n.suggested_action,
                    "context": n.context
                }
                for n in nudges
            ]
        })
    except Exception as e:
        print(f"ATLAS nudges error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/commitments", methods=["GET"])
@login_required
def atlas_get_commitments():
    """Get tracked commitments (optionally filtered by contact)"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        contact = request.args.get('contact', None)
        status = request.args.get('status', None)
        limit = request.args.get('limit', 50, type=int)

        tracker = CommitmentTracker()
        commitments = tracker.get_commitments(contact_identifier=contact, status=status, limit=limit)

        return jsonify({
            "ok": True,
            "commitments": [
                {
                    "id": c.id,
                    "contact_name": c.contact_name,
                    "contact_identifier": c.contact_identifier,
                    "content": c.content,
                    "owner": c.owner,
                    "due_date": c.due_date.isoformat() if c.due_date else None,
                    "status": c.status.value,
                    "source_type": c.source_type,
                    "created_at": c.created_at.isoformat() if c.created_at else None
                }
                for c in commitments
            ]
        })
    except Exception as e:
        print(f"ATLAS commitments error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/commitments/<int:commitment_id>", methods=["PATCH"])
@login_required
def atlas_update_commitment(commitment_id: int):
    """Update a commitment status"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        data = request.get_json() or {}
        new_status = data.get('status')

        if not new_status:
            return jsonify({'error': 'status required'}), 400

        tracker = CommitmentTracker()
        success = tracker.update_commitment_status(commitment_id, new_status)

        return jsonify({
            "ok": success,
            "commitment_id": commitment_id,
            "new_status": new_status
        })
    except Exception as e:
        print(f"ATLAS commitment update error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/interactions", methods=["POST"])
@login_required
def atlas_log_interaction():
    """Log a new interaction with a contact"""
    if not ATLAS_AVAILABLE:
        return jsonify({'error': 'ATLAS not available'}), 503

    try:
        data = request.get_json() or {}

        contact_identifier = data.get('contact_identifier')
        interaction_type = data.get('type', 'note')
        subject = data.get('subject', '')
        summary = data.get('summary', '')
        content = data.get('content', '')

        if not contact_identifier:
            return jsonify({'error': 'contact_identifier required'}), 400

        tracker = InteractionTracker()
        interaction_id = tracker.log_interaction(
            contact_identifier=contact_identifier,
            interaction_type=interaction_type,
            subject=subject,
            summary=summary,
            content=content
        )

        return jsonify({
            "ok": True,
            "interaction_id": interaction_id
        })
    except Exception as e:
        print(f"ATLAS log interaction error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ATLAS GMAIL API ENDPOINTS (All 3 accounts)
# =============================================================================

@app.route("/api/atlas/gmail/status", methods=["GET"])
@login_required
def atlas_gmail_status():
    """Get status of all Gmail accounts"""
    if not ATLAS_AVAILABLE or not GmailReader:
        return jsonify({'error': 'ATLAS Gmail not available'}), 503

    try:
        reader = GmailReader()
        accounts_status = reader.get_account_status()

        return jsonify({
            "ok": True,
            "accounts": accounts_status,
            "total_accounts": len(GMAIL_ACCOUNTS),
            "configured_accounts": GMAIL_ACCOUNTS
        })
    except Exception as e:
        print(f"ATLAS Gmail status error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/gmail/recent", methods=["GET"])
@login_required
def atlas_gmail_recent():
    """Get recent email contacts across all Gmail accounts"""
    if not ATLAS_AVAILABLE or not GmailReader:
        return jsonify({'error': 'ATLAS Gmail not available'}), 503

    try:
        days = request.args.get('days', 30, type=int)
        limit = request.args.get('limit', 50, type=int)

        reader = GmailReader()
        contacts = reader.get_recent_email_contacts(days=days, limit=limit)

        return jsonify({
            "ok": True,
            "contacts": contacts,
            "count": len(contacts),
            "accounts_searched": GMAIL_ACCOUNTS
        })
    except Exception as e:
        print(f"ATLAS Gmail recent error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/gmail/conversation/<path:email>", methods=["GET"])
@login_required
def atlas_gmail_conversation(email):
    """Get email conversation with a specific contact"""
    if not ATLAS_AVAILABLE or not GmailReader:
        return jsonify({'error': 'ATLAS Gmail not available'}), 503

    try:
        days = request.args.get('days', 90, type=int)
        limit = request.args.get('limit', 50, type=int)

        reader = GmailReader()
        emails = reader.get_emails_with_contact(email, days=days, limit=limit)

        return jsonify({
            "ok": True,
            "email": email,
            "emails": emails,
            "count": len(emails),
            "accounts_searched": GMAIL_ACCOUNTS
        })
    except Exception as e:
        print(f"ATLAS Gmail conversation error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ATLAS GOOGLE PEOPLE API ENDPOINTS
# =============================================================================

@app.route("/api/atlas/people/contacts", methods=["GET"])
@login_required
def atlas_people_contacts():
    """Get all Google contacts with photos"""
    if not ATLAS_AVAILABLE or not GooglePeopleAPI:
        return jsonify({'error': 'ATLAS People API not available'}), 503

    try:
        limit = request.args.get('limit', 100, type=int)

        people = GooglePeopleAPI()
        contacts = people.get_all_contacts(limit=limit)

        return jsonify({
            "ok": True,
            "contacts": contacts,
            "count": len(contacts)
        })
    except Exception as e:
        print(f"ATLAS People contacts error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/people/search", methods=["GET"])
@login_required
def atlas_people_search():
    """Search Google contacts by name or email"""
    if not ATLAS_AVAILABLE or not GooglePeopleAPI:
        return jsonify({'error': 'ATLAS People API not available'}), 503

    try:
        query = request.args.get('q', '')
        if not query:
            return jsonify({'error': 'q parameter required'}), 400

        people = GooglePeopleAPI()
        results = people.search_contacts(query)

        return jsonify({
            "ok": True,
            "query": query,
            "results": results,
            "count": len(results)
        })
    except Exception as e:
        print(f"ATLAS People search error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/people/photo/<path:identifier>", methods=["GET"])
@login_required
def atlas_people_photo(identifier):
    """Get photo URL for a contact"""
    if not ATLAS_AVAILABLE or not GooglePeopleAPI:
        return jsonify({'error': 'ATLAS People API not available'}), 503

    try:
        people = GooglePeopleAPI()
        photo_url = people.get_contact_photo(identifier)

        return jsonify({
            "ok": True,
            "identifier": identifier,
            "photo_url": photo_url
        })
    except Exception as e:
        print(f"ATLAS People photo error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ATLAS CONTACTS API (UI-friendly endpoints)
# =============================================================================

@app.route("/api/atlas/contacts", methods=["GET"])
def atlas_contacts():
    """Get all contacts from database with unified format for UI"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        limit = request.args.get('limit', 100, type=int)
        offset = request.args.get('offset', 0, type=int)
        search = request.args.get('search', '')
        sort = request.args.get('sort', 'name')  # name, frequency, recent, score

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Determine sort order based on parameter
        if sort == 'frequency':
            order_clause = "ORDER BY COALESCE(interaction_count, 0) DESC, name"
        elif sort == 'recent':
            order_clause = "ORDER BY COALESCE(last_touch_date, '1970-01-01') DESC, name"
        elif sort == 'score':
            order_clause = "ORDER BY COALESCE(relationship_score, 0) DESC, name"
        else:
            order_clause = "ORDER BY name"

        # Use contacts table as the single source of truth
        try:
            if search:
                # Normalize phone search (remove non-digits for phone matching)
                search_term = f'%{search}%'
                phone_search = ''.join(c for c in search if c.isdigit())
                phone_search_term = f'%{phone_search}%' if len(phone_search) >= 3 else ''

                # Enhanced search: name, first_name, last_name, email, phone, company, notes, location
                cursor.execute("""
                    SELECT * FROM contacts
                    WHERE name LIKE %s
                       OR first_name LIKE %s
                       OR last_name LIKE %s
                       OR email LIKE %s
                       OR company LIKE %s
                       OR notes LIKE %s
                       OR job_title LIKE %s
                       OR (REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', '') LIKE %s AND %s != '')
                    ORDER BY
                        CASE WHEN name LIKE %s THEN 0
                             WHEN first_name LIKE %s OR last_name LIKE %s THEN 1
                             WHEN email LIKE %s THEN 2
                             ELSE 3 END,
                        name
                    LIMIT %s OFFSET %s
                """, (search_term, search_term, search_term, search_term, search_term,
                      search_term, search_term, phone_search_term, phone_search_term,
                      search_term, search_term, search_term, search_term, limit, offset))
            else:
                cursor.execute(f"""
                    SELECT * FROM contacts
                    {order_clause}
                    LIMIT %s OFFSET %s
                """, (limit, offset))

            contacts = cursor.fetchall()

            # Get total count
            if search:
                search_term = f'%{search}%'
                phone_search = ''.join(c for c in search if c.isdigit())
                phone_search_term = f'%{phone_search}%' if len(phone_search) >= 3 else ''
                cursor.execute("""
                    SELECT COUNT(*) as total FROM contacts
                    WHERE name LIKE %s
                       OR first_name LIKE %s
                       OR last_name LIKE %s
                       OR email LIKE %s
                       OR company LIKE %s
                       OR notes LIKE %s
                       OR job_title LIKE %s
                       OR (REPLACE(REPLACE(REPLACE(phone, '-', ''), ' ', ''), '+', '') LIKE %s AND %s != '')
                """, (search_term, search_term, search_term, search_term, search_term,
                      search_term, search_term, phone_search_term, phone_search_term))
            else:
                cursor.execute("SELECT COUNT(*) as total FROM contacts")

            total = cursor.fetchone()['total']

            # Format contacts for UI
            formatted = []
            for c in contacts:
                formatted.append({
                    "id": c.get('id'),
                    "name": c.get('name', ''),
                    "first_name": c.get('first_name', ''),
                    "last_name": c.get('last_name', ''),
                    "email": c.get('email', ''),
                    "phone": c.get('phone', ''),
                    "company": c.get('company', ''),
                    "job_title": c.get('job_title', ''),
                    "category": c.get('category', ''),
                    "priority": c.get('priority', 'Normal'),
                    "photo_url": c.get('photo_url', ''),
                    "source": c.get('source', 'manual'),
                    "relationship_score": c.get('relationship_score', 0),
                    "location": c.get('location', ''),
                    "city": c.get('city', ''),
                    "state": c.get('state', ''),
                    "country": c.get('country', ''),
                    "last_interaction": str(c.get('last_touch_date', '')) if c.get('last_touch_date') else None,
                    "interaction_count": c.get('total_interactions', 0),
                    "birthday": str(c.get('birthday', '')) if c.get('birthday') else None,
                    "anniversary": str(c.get('anniversary', '')) if c.get('anniversary') else None,
                    "linkedin_url": c.get('linkedin_url', ''),
                    "twitter_handle": c.get('twitter_handle', ''),
                    "tags": c.get('tags', '').split(',') if c.get('tags') else [],
                    "notes": c.get('notes', ''),
                    "created_at": str(c.get('created_at', '')) if c.get('created_at') else None,
                    "updated_at": str(c.get('updated_at', '')) if c.get('updated_at') else None
                })

            cursor.close()
            return_db_connection(conn)

            return jsonify({
                "ok": True,
                "contacts": formatted,
                "count": len(formatted),
                "total": total,
                "limit": limit,
                "offset": offset
            })

        except Exception as err:
            print(f"contacts table query failed: {err}")
            cursor.close()
            return_db_connection(conn)
            return jsonify({
                "ok": True,
                "contacts": [],
                "count": 0,
                "total": 0,
                "message": "No contacts synced yet."
            })

    except Exception as e:
        print(f"ATLAS contacts error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>", methods=["GET"])
def atlas_contact_detail(contact_id):
    """Get detailed contact information"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("SELECT * FROM contacts WHERE id = %s", (contact_id,))
        contact = cursor.fetchone()

        if not contact:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'error': 'Contact not found'}), 404

        # Get interaction history if available
        interactions = []
        try:
            cursor.execute("""
                SELECT * FROM atlas_interactions
                WHERE contact_id = %s
                ORDER BY interaction_date DESC
                LIMIT 50
            """, (contact_id,))
            interactions = cursor.fetchall()
        except:
            pass  # Table might not exist

        cursor.close()
        return_db_connection(conn)

        # Build name from available fields
        name = contact.get('name') or contact.get('display_name') or ''
        if not name and (contact.get('first_name') or contact.get('last_name')):
            name = f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()

        return jsonify({
            "ok": True,
            "contact": {
                "id": contact.get('id'),
                "name": name,
                "display_name": name,  # Alias for UI compatibility
                "first_name": contact.get('first_name', ''),
                "last_name": contact.get('last_name', ''),
                "email": contact.get('email', ''),
                "phone": contact.get('phone', ''),
                "company": contact.get('company', ''),
                "job_title": contact.get('job_title', ''),
                "title": contact.get('job_title', ''),  # Alias for UI compatibility
                "photo_url": contact.get('photo_url', ''),
                "source": contact.get('source', 'manual'),
                "category": contact.get('category', 'General'),
                "priority": contact.get('priority', 'Normal'),
                "location": contact.get('location', ''),
                "city": contact.get('city', ''),
                "state": contact.get('state', ''),
                "country": contact.get('country', ''),
                "last_interaction": str(contact.get('last_interaction', '')) if contact.get('last_interaction') else None,
                "interaction_count": contact.get('interaction_count', 0),
                "relationship_score": contact.get('relationship_score', 0),
                "tags": contact.get('tags', '').split(',') if contact.get('tags') else [],
                "notes": contact.get('notes', ''),
                "linkedin_url": contact.get('linkedin_url', ''),
                "twitter_handle": contact.get('twitter_handle', ''),
                "birthday": str(contact.get('birthday', '')) if contact.get('birthday') else None,
                "anniversary": str(contact.get('anniversary', '')) if contact.get('anniversary') else None,
                "created_at": str(contact.get('created_at', '')) if contact.get('created_at') else None,
                "updated_at": str(contact.get('updated_at', '')) if contact.get('updated_at') else None
            },
            "interactions": interactions
        })

    except Exception as e:
        print(f"ATLAS contact detail error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>/communications", methods=["GET"])
def atlas_contact_communications(contact_id):
    """Get recent emails and texts for a contact"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        limit = request.args.get('limit', 20, type=int)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contact info
        cursor.execute("SELECT email, phone, name FROM contacts WHERE id = %s", (contact_id,))
        contact = cursor.fetchone()
        if not contact:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'error': 'Contact not found'}), 404

        email = contact.get('email', '').lower()
        phone = contact.get('phone', '')
        # Normalize phone for matching
        phone_digits = ''.join(c for c in phone if c.isdigit())[-10:] if phone else ''

        emails = []
        texts = []

        # Get recent emails from gmail_cache if email exists
        if email:
            try:
                cursor.execute("""
                    SELECT id, subject, from_email, gmail_account, received_date, snippet
                    FROM gmail_cache
                    WHERE LOWER(from_email) LIKE %s OR LOWER(to_email) LIKE %s
                    ORDER BY received_date DESC
                    LIMIT %s
                """, (f'%{email}%', f'%{email}%', limit))
                for row in cursor.fetchall():
                    emails.append({
                        'id': row.get('id'),
                        'subject': row.get('subject', ''),
                        'from': row.get('from_email', ''),
                        'account': row.get('gmail_account', ''),
                        'date': str(row.get('received_date', '')) if row.get('received_date') else None,
                        'snippet': row.get('snippet', '')[:100] if row.get('snippet') else ''
                    })
            except Exception as e:
                print(f"Email lookup error: {e}")

        # Get recent texts from imessage_cache if phone exists
        if phone_digits:
            try:
                cursor.execute("""
                    SELECT id, handle_id, text, is_from_me, message_date, service
                    FROM imessage_cache
                    WHERE REPLACE(REPLACE(REPLACE(handle_id, '-', ''), ' ', ''), '+1', '') LIKE %s
                    ORDER BY message_date DESC
                    LIMIT %s
                """, (f'%{phone_digits}%', limit))
                for row in cursor.fetchall():
                    texts.append({
                        'id': row.get('id'),
                        'text': row.get('text', '')[:200] if row.get('text') else '',
                        'from_me': bool(row.get('is_from_me')),
                        'date': str(row.get('message_date', '')) if row.get('message_date') else None,
                        'service': row.get('service', 'iMessage')
                    })
            except Exception as e:
                print(f"iMessage lookup error: {e}")

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'contact_id': contact_id,
            'contact_name': contact.get('name', ''),
            'emails': emails,
            'texts': texts,
            'email_count': len(emails),
            'text_count': len(texts)
        })

    except Exception as e:
        print(f"Communications lookup error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>", methods=["PUT"])
def atlas_contact_update(contact_id):
    """Update a contact"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Build update query dynamically based on provided fields
        update_fields = []
        values = []

        field_mapping = {
            'name': 'name',
            'first_name': 'first_name',
            'last_name': 'last_name',
            'company': 'company',
            'title': 'job_title',
            'job_title': 'job_title',
            'email': 'email',
            'phone': 'phone',
            'category': 'category',
            'priority': 'priority',
            'notes': 'notes',
            'location': 'location',
            'city': 'city',
            'state': 'state',
            'country': 'country',
            'linkedin_url': 'linkedin_url',
            'twitter_handle': 'twitter_handle',
            'birthday': 'birthday',
            'anniversary': 'anniversary'
        }

        for json_key, db_column in field_mapping.items():
            if json_key in data:
                update_fields.append(f"{db_column} = %s")
                values.append(data[json_key])

        if not update_fields:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'error': 'No valid fields to update'}), 400

        # Add updated_at
        update_fields.append("updated_at = NOW()")
        values.append(contact_id)

        # Update in contacts table (single source of truth)
        query = f"UPDATE contacts SET {', '.join(update_fields)} WHERE id = %s"
        cursor.execute(query, values)

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": "Contact updated successfully",
            "id": contact_id
        })

    except Exception as e:
        print(f"ATLAS contact update error: {e}")
        import traceback
        traceback.print_exc()
        # Ensure connection is returned on error
        try:
            return_db_connection(conn, discard=True)
        except:
            pass
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>", methods=["DELETE"])
def atlas_contact_delete(contact_id):
    """Delete a contact"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Delete from contacts table
        cursor.execute("DELETE FROM contacts WHERE id = %s", (contact_id,))
        deleted = cursor.rowcount > 0

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        if deleted:
            return jsonify({
                "ok": True,
                "message": "Contact deleted successfully",
                "id": contact_id
            })
        else:
            return jsonify({'error': 'Contact not found'}), 404

    except Exception as e:
        print(f"ATLAS contact delete error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>/photo", methods=["POST"])
def atlas_contact_upload_photo(contact_id):
    """Upload a photo for a contact and store in R2"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        # Check if file was uploaded
        if 'file' not in request.files:
            return jsonify({'error': 'No file provided'}), 400

        file = request.files['file']
        if file.filename == '':
            return jsonify({'error': 'No file selected'}), 400

        # Validate file type
        allowed_extensions = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in allowed_extensions:
            return jsonify({'error': f'Invalid file type. Allowed: {", ".join(allowed_extensions)}'}), 400

        # Save temporarily
        import tempfile
        import uuid
        temp_dir = tempfile.gettempdir()
        unique_filename = f"contact_{contact_id}_{uuid.uuid4().hex[:8]}.{ext}"
        temp_path = Path(temp_dir) / unique_filename
        file.save(str(temp_path))

        photo_url = None

        # Try to upload to R2
        if R2_ENABLED and upload_to_r2:
            try:
                r2_key = f"contact-photos/{unique_filename}"
                success, result = upload_to_r2(temp_path, key=r2_key)
                if success:
                    photo_url = result
                    print(f"Uploaded contact photo to R2: {photo_url}")
                else:
                    print(f"R2 upload failed: {result}")
            except Exception as e:
                print(f"R2 upload error: {e}")

        # If R2 failed, use local storage fallback
        if not photo_url:
            # Store in static folder
            static_photos = Path("static/contact-photos")
            static_photos.mkdir(parents=True, exist_ok=True)
            dest_path = static_photos / unique_filename
            import shutil
            shutil.move(str(temp_path), str(dest_path))
            photo_url = f"/static/contact-photos/{unique_filename}"
            print(f"Stored contact photo locally: {photo_url}")

        # Clean up temp file if still exists
        if temp_path.exists():
            temp_path.unlink()

        # Update database with photo_url
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Update contacts table
        cursor.execute("UPDATE contacts SET photo_url = %s, updated_at = NOW() WHERE id = %s", (photo_url, contact_id))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": "Photo uploaded successfully",
            "photo_url": photo_url,
            "contact_id": contact_id
        })

    except Exception as e:
        print(f"ATLAS contact photo upload error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>/photo", methods=["DELETE"])
def atlas_contact_delete_photo(contact_id):
    """Delete a contact's photo"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Clear photo_url in contacts
        cursor.execute("UPDATE contacts SET photo_url = NULL, updated_at = NOW() WHERE id = %s", (contact_id,))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": "Photo removed successfully",
            "contact_id": contact_id
        })

    except Exception as e:
        print(f"ATLAS contact photo delete error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/enrich", methods=["POST"])
def atlas_contacts_enrich():
    """
    Free contact enrichment using:
    1. Gravatar - profile photos from MD5 email hash
    2. Email signature parsing - extract job titles and phone numbers from Gmail
    """
    import hashlib
    import requests as req
    import re

    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_KEY', 'tallyups-admin-2024')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        contact_ids = data.get('contact_ids', [])  # Optional: specific contacts to enrich
        enrich_gravatar = data.get('gravatar', True)
        enrich_signatures = data.get('signatures', True)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contacts to enrich
        if contact_ids:
            placeholders = ', '.join(['%s'] * len(contact_ids))
            cursor.execute(f"SELECT id, email, name, job_title, phone, photo_url FROM contacts WHERE id IN ({placeholders})", contact_ids)
        else:
            # Get contacts missing photo or job title
            cursor.execute("""
                SELECT id, email, name, job_title, phone, photo_url
                FROM contacts
                WHERE email IS NOT NULL AND email != ''
                AND (photo_url IS NULL OR photo_url = '' OR job_title IS NULL OR job_title = '')
                LIMIT 100
            """)

        contacts = cursor.fetchall()
        enriched_count = 0
        gravatar_found = 0
        signatures_parsed = 0
        results = []

        for contact in contacts:
            contact_id, email, name, job_title, phone, photo_url = contact
            updates = {}
            enrichment_info = {'contact_id': contact_id, 'email': email}

            if not email:
                continue

            # 1. Gravatar enrichment - get profile photo
            if enrich_gravatar and not photo_url:
                try:
                    email_lower = email.lower().strip()
                    email_hash = hashlib.md5(email_lower.encode('utf-8')).hexdigest()
                    # Check if gravatar exists (d=404 returns 404 if no image)
                    gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=200"

                    resp = req.head(gravatar_url, timeout=5)
                    if resp.status_code == 200:
                        # Gravatar exists! Use the URL without the 404 fallback
                        final_gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?s=200"
                        updates['photo_url'] = final_gravatar_url
                        enrichment_info['gravatar'] = final_gravatar_url
                        gravatar_found += 1
                except Exception as e:
                    print(f"Gravatar check failed for {email}: {e}")

            # 2. Email signature parsing - extract job title and phone from Gmail
            if enrich_signatures and (not job_title or not phone):
                try:
                    # Look for recent emails from this contact in email_messages table
                    cursor.execute("""
                        SELECT body_text, body_html
                        FROM email_messages
                        WHERE from_email = %s
                        ORDER BY date DESC
                        LIMIT 5
                    """, (email,))

                    emails = cursor.fetchall()
                    for email_row in emails:
                        body_text, body_html = email_row
                        body = body_text or body_html or ''

                        if not body:
                            continue

                        # Parse signature for job title
                        if not job_title and not updates.get('job_title'):
                            # Common job title patterns in signatures
                            title_patterns = [
                                r'(?:^|\n)([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\s*\|\s*([A-Z][a-zA-Z\s&]+(?:Manager|Director|VP|President|CEO|CTO|CFO|COO|Founder|Partner|Engineer|Developer|Designer|Analyst|Consultant|Specialist|Coordinator|Lead|Head|Chief|Officer|Executive|Owner))',
                                r'(?:Title|Position|Role):\s*([A-Za-z\s&,]+(?:Manager|Director|VP|President|CEO|CTO|CFO|COO|Founder|Partner|Engineer|Developer|Designer|Analyst|Consultant|Specialist|Coordinator|Lead|Head|Chief|Officer|Executive|Owner))',
                                r'\n([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*,\s+(?:Manager|Director|VP|President|CEO|CTO|CFO|COO|Founder|Partner|Engineer|Developer|Designer|Analyst|Consultant|Specialist|Coordinator|Lead|Head|Chief|Officer|Executive|Owner)[A-Za-z\s&,]*)',
                            ]

                            for pattern in title_patterns:
                                match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
                                if match:
                                    extracted_title = match.group(1) if len(match.groups()) >= 1 else match.group(0)
                                    extracted_title = extracted_title.strip()[:100]  # Limit length
                                    if len(extracted_title) > 3 and len(extracted_title) < 80:
                                        updates['job_title'] = extracted_title
                                        enrichment_info['job_title'] = extracted_title
                                        signatures_parsed += 1
                                        break

                        # Parse signature for phone number
                        if not phone and not updates.get('phone'):
                            # Phone patterns
                            phone_patterns = [
                                r'(?:Phone|Tel|Mobile|Cell|Office|Direct|P|M|T|C|O)[\s:.-]*(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})',
                                r'(?:^|\s)(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})(?:\s|$)',
                            ]

                            for pattern in phone_patterns:
                                match = re.search(pattern, body, re.IGNORECASE)
                                if match:
                                    extracted_phone = match.group(1).strip()
                                    # Clean up phone
                                    extracted_phone = re.sub(r'[^\d+()-.\s]', '', extracted_phone)
                                    if len(extracted_phone) >= 10:
                                        updates['phone'] = extracted_phone[:20]
                                        enrichment_info['phone'] = extracted_phone[:20]
                                        break

                        if updates.get('job_title') and updates.get('phone'):
                            break  # Found both, stop searching

                except Exception as e:
                    print(f"Signature parsing failed for {email}: {e}")

            # Apply updates to database
            if updates:
                set_clauses = []
                values = []
                for key, val in updates.items():
                    set_clauses.append(f"{key} = %s")
                    values.append(val)
                set_clauses.append("updated_at = NOW()")
                values.append(contact_id)

                sql = f"UPDATE contacts SET {', '.join(set_clauses)} WHERE id = %s"
                cursor.execute(sql, values)
                enriched_count += 1
                enrichment_info['updated'] = True

            results.append(enrichment_info)

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": f"Enriched {enriched_count} contacts",
            "stats": {
                "contacts_processed": len(contacts),
                "contacts_enriched": enriched_count,
                "gravatar_photos_found": gravatar_found,
                "signatures_parsed": signatures_parsed
            },
            "results": results
        })

    except Exception as e:
        print(f"ATLAS contact enrichment error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/<contact_id>/enrich", methods=["POST"])
def atlas_contact_enrich_single(contact_id):
    """Enrich a single contact with Gravatar and signature parsing"""
    import hashlib
    import requests as req
    import re

    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_KEY', 'tallyups-admin-2024')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contact
        cursor.execute("SELECT id, email, name, job_title, phone, photo_url FROM contacts WHERE id = %s", (contact_id,))
        contact = cursor.fetchone()

        if not contact:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'error': 'Contact not found'}), 404

        contact_id, email, name, job_title, phone, photo_url = contact
        updates = {}
        enrichment_info = {'contact_id': contact_id, 'email': email}

        if not email:
            cursor.close()
            return_db_connection(conn)
            return jsonify({'error': 'Contact has no email address'}), 400

        # 1. Gravatar enrichment
        try:
            email_lower = email.lower().strip()
            email_hash = hashlib.md5(email_lower.encode('utf-8')).hexdigest()
            gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?d=404&s=200"

            resp = req.head(gravatar_url, timeout=5)
            if resp.status_code == 200:
                final_gravatar_url = f"https://www.gravatar.com/avatar/{email_hash}?s=200"
                updates['photo_url'] = final_gravatar_url
                enrichment_info['gravatar'] = final_gravatar_url
        except Exception as e:
            enrichment_info['gravatar_error'] = str(e)

        # 2. Email signature parsing
        try:
            cursor.execute("""
                SELECT body_text, body_html
                FROM email_messages
                WHERE from_email = %s
                ORDER BY date DESC
                LIMIT 5
            """, (email,))

            emails = cursor.fetchall()
            for email_row in emails:
                body_text, body_html = email_row
                body = body_text or body_html or ''

                if not body:
                    continue

                # Parse for job title
                if not job_title and not updates.get('job_title'):
                    title_patterns = [
                        r'(?:Title|Position|Role):\s*([A-Za-z\s&,]+(?:Manager|Director|VP|President|CEO|CTO|CFO|COO|Founder|Partner|Engineer|Developer|Designer|Analyst|Consultant|Specialist|Coordinator|Lead|Head|Chief|Officer|Executive|Owner))',
                    ]

                    for pattern in title_patterns:
                        match = re.search(pattern, body, re.MULTILINE | re.IGNORECASE)
                        if match:
                            extracted_title = match.group(1).strip()[:100]
                            if 3 < len(extracted_title) < 80:
                                updates['job_title'] = extracted_title
                                enrichment_info['job_title'] = extracted_title
                                break

                # Parse for phone
                if not phone and not updates.get('phone'):
                    phone_patterns = [
                        r'(?:Phone|Tel|Mobile|Cell|Office|Direct|P|M|T|C|O)[\s:.-]*(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})',
                        r'(?:^|\s)(\+?1?[-.\s]?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4})(?:\s|$)',
                    ]

                    for pattern in phone_patterns:
                        match = re.search(pattern, body, re.IGNORECASE)
                        if match:
                            extracted_phone = re.sub(r'[^\d+()-.\s]', '', match.group(1).strip())
                            if len(extracted_phone) >= 10:
                                updates['phone'] = extracted_phone[:20]
                                enrichment_info['phone'] = extracted_phone[:20]
                                break

                if updates.get('job_title') and updates.get('phone'):
                    break

        except Exception as e:
            enrichment_info['signature_error'] = str(e)

        # Apply updates
        if updates:
            set_clauses = []
            values = []
            for key, val in updates.items():
                set_clauses.append(f"{key} = %s")
                values.append(val)
            set_clauses.append("updated_at = NOW()")
            values.append(contact_id)

            sql = f"UPDATE contacts SET {', '.join(set_clauses)} WHERE id = %s"
            cursor.execute(sql, values)
            conn.commit()
            enrichment_info['updated'] = True

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": "Contact enriched" if updates else "No new data found",
            "enrichment": enrichment_info
        })

    except Exception as e:
        print(f"ATLAS single contact enrichment error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/find-incomplete", methods=["POST"])
def atlas_contacts_find_incomplete():
    """Find incomplete contacts for cleanup"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        results = {
            'phone_only': [],      # Has phone but no email AND no company
            'name_only': [],       # Has name but no phone AND no email
            'no_contact_info': [], # No phone AND no email
            'uncategorized': []    # Category is NULL or 'General'
        }

        # Phone only - has phone but no email and no company
        cursor.execute("""
            SELECT id, name, first_name, last_name, company, title,
                   email, phone, category, notes
            FROM contacts
            WHERE phone IS NOT NULL AND phone != ''
              AND (email IS NULL OR email = '')
              AND (company IS NULL OR company = '')
            ORDER BY name
            LIMIT 200
        """)
        results['phone_only'] = cursor.fetchall() if db_type == 'mysql' else [dict(row) for row in cursor.fetchall()]

        # Name only - has name but no phone and no email
        cursor.execute("""
            SELECT id, name, first_name, last_name, company, title,
                   email, phone, category, notes
            FROM contacts
            WHERE (phone IS NULL OR phone = '')
              AND (email IS NULL OR email = '')
              AND name IS NOT NULL AND name != ''
            ORDER BY name
            LIMIT 200
        """)
        results['name_only'] = cursor.fetchall() if db_type == 'mysql' else [dict(row) for row in cursor.fetchall()]

        # No contact info - no phone and no email
        cursor.execute("""
            SELECT id, name, first_name, last_name, company, title,
                   email, phone, category, notes
            FROM contacts
            WHERE (phone IS NULL OR phone = '')
              AND (email IS NULL OR email = '')
            ORDER BY name
            LIMIT 200
        """)
        results['no_contact_info'] = cursor.fetchall() if db_type == 'mysql' else [dict(row) for row in cursor.fetchall()]

        # Uncategorized - category is NULL or 'General'
        cursor.execute("""
            SELECT id, name, first_name, last_name, company, title,
                   email, phone, category, notes
            FROM contacts
            WHERE category IS NULL OR category = '' OR category = 'General'
            ORDER BY name
            LIMIT 200
        """)
        results['uncategorized'] = cursor.fetchall() if db_type == 'mysql' else [dict(row) for row in cursor.fetchall()]

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'results': results,
            'counts': {
                'phone_only': len(results['phone_only']),
                'name_only': len(results['name_only']),
                'no_contact_info': len(results['no_contact_info']),
                'uncategorized': len(results['uncategorized'])
            }
        })

    except Exception as e:
        print(f"ATLAS find incomplete contacts error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/bulk-delete", methods=["POST"])
def atlas_contacts_bulk_delete():
    """Bulk delete contacts by ID list"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        contact_ids = data.get('ids', [])
        if not contact_ids:
            return jsonify({'error': 'No contact IDs provided'}), 400

        if len(contact_ids) > 500:
            return jsonify({'error': 'Maximum 500 contacts can be deleted at once'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Build placeholders for IN clause
        placeholders = ','.join(['%s'] * len(contact_ids))

        # Delete from contacts table
        cursor.execute(f"DELETE FROM contacts WHERE id IN ({placeholders})", tuple(contact_ids))
        deleted_count = cursor.rowcount

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Successfully deleted {deleted_count} contacts',
            'deleted_count': deleted_count
        })

    except Exception as e:
        print(f"ATLAS bulk delete contacts error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/bulk-update", methods=["POST"])
def atlas_contacts_bulk_update():
    """Bulk update contacts - apply category or other fields to multiple contacts at once"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        contact_ids = data.get('contact_ids', [])
        updates = data.get('updates', {})

        if not contact_ids:
            return jsonify({'error': 'No contact IDs provided'}), 400

        if not updates:
            return jsonify({'error': 'No updates provided'}), 400

        if len(contact_ids) > 500:
            return jsonify({'error': 'Maximum 500 contacts can be updated at once'}), 400

        # Allowed fields that can be bulk updated
        allowed_fields = ['category', 'is_vip', 'needs_attention', 'tags']

        # Filter to only allowed fields
        safe_updates = {k: v for k, v in updates.items() if k in allowed_fields}

        if not safe_updates:
            return jsonify({'error': 'No valid update fields provided. Allowed: ' + ', '.join(allowed_fields)}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Build SET clause
        set_parts = []
        values = []
        for field, value in safe_updates.items():
            set_parts.append(f"{field} = %s")
            values.append(value)

        # Add contact IDs to values
        values.extend(contact_ids)

        # Build placeholders for IN clause
        placeholders = ','.join(['%s'] * len(contact_ids))

        # Update contacts
        query = f"UPDATE contacts SET {', '.join(set_parts)} WHERE id IN ({placeholders})"
        cursor.execute(query, tuple(values))
        updated_count = cursor.rowcount

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Successfully updated {updated_count} contacts',
            'updated_count': updated_count,
            'updates_applied': safe_updates
        })

    except Exception as e:
        print(f"ATLAS bulk update contacts error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts/upcoming-events", methods=["GET"])
def atlas_contacts_upcoming_events():
    """Get contacts with upcoming birthdays and anniversaries"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        days_ahead = int(request.args.get('days', 30))
        event_type = request.args.get('type', 'all')  # birthday, anniversary, or all

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        results = {
            'birthdays': [],
            'anniversaries': []
        }

        from datetime import datetime, timedelta
        today = datetime.now()
        this_year = today.year

        # Get contacts with birthdays/anniversaries
        if event_type in ['birthday', 'all']:
            cursor.execute("""
                SELECT id, display_name as name, first_name, last_name, email, phone, birthday, company, category
                FROM contacts
                WHERE birthday IS NOT NULL
            """)
            rows = cursor.fetchall()
            if db_type == 'sqlite':
                rows = [dict(zip([d[0] for d in cursor.description], row)) for row in rows]

            for contact in rows:
                bday = contact.get('birthday')
                if bday:
                    try:
                        if isinstance(bday, str):
                            bday = datetime.strptime(bday.split('T')[0], '%Y-%m-%d')
                        # Calculate next occurrence
                        next_bday = datetime(this_year, bday.month, bday.day)
                        if next_bday.date() < today.date():
                            next_bday = datetime(this_year + 1, bday.month, bday.day)
                        days_until = (next_bday.date() - today.date()).days
                        if days_until <= days_ahead:
                            age = this_year - bday.year
                            if next_bday.year > this_year:
                                age += 1
                            results['birthdays'].append({
                                'id': contact['id'],
                                'name': contact['name'] or f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
                                'email': contact.get('email'),
                                'phone': contact.get('phone'),
                                'company': contact.get('company'),
                                'category': contact.get('category'),
                                'date': bday.strftime('%Y-%m-%d'),
                                'days_until': days_until,
                                'turning_age': age
                            })
                    except Exception as e:
                        print(f"Birthday parse error for {contact.get('name')}: {e}")

        if event_type in ['anniversary', 'all']:
            cursor.execute("""
                SELECT id, name, first_name, last_name, email, phone, anniversary, company, category
                FROM contacts
                WHERE anniversary IS NOT NULL
            """)
            rows = cursor.fetchall()
            if db_type == 'sqlite':
                rows = [dict(zip([d[0] for d in cursor.description], row)) for row in rows]

            for contact in rows:
                anni = contact.get('anniversary')
                if anni:
                    try:
                        if isinstance(anni, str):
                            anni = datetime.strptime(anni.split('T')[0], '%Y-%m-%d')
                        # Calculate next occurrence
                        next_anni = datetime(this_year, anni.month, anni.day)
                        if next_anni.date() < today.date():
                            next_anni = datetime(this_year + 1, anni.month, anni.day)
                        days_until = (next_anni.date() - today.date()).days
                        if days_until <= days_ahead:
                            years = this_year - anni.year
                            if next_anni.year > this_year:
                                years += 1
                            results['anniversaries'].append({
                                'id': contact['id'],
                                'name': contact['name'] or f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip(),
                                'email': contact.get('email'),
                                'phone': contact.get('phone'),
                                'company': contact.get('company'),
                                'category': contact.get('category'),
                                'date': anni.strftime('%Y-%m-%d'),
                                'days_until': days_until,
                                'years': years
                            })
                    except Exception as e:
                        print(f"Anniversary parse error for {contact.get('name')}: {e}")

        cursor.close()
        return_db_connection(conn)

        # Sort by days_until
        results['birthdays'].sort(key=lambda x: x['days_until'])
        results['anniversaries'].sort(key=lambda x: x['days_until'])

        return jsonify({
            'ok': True,
            'days_ahead': days_ahead,
            'birthdays': results['birthdays'],
            'anniversaries': results['anniversaries'],
            'counts': {
                'birthdays': len(results['birthdays']),
                'anniversaries': len(results['anniversaries']),
                'total': len(results['birthdays']) + len(results['anniversaries'])
            }
        })

    except Exception as e:
        print(f"ATLAS upcoming events error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# ATLAS CONTACT SYNC ENDPOINTS
# =============================================================================

@app.route("/api/atlas/sync/status", methods=["GET"])
def atlas_sync_status():
    """Get sync status for all contacts"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Ensure sync columns exist
        try:
            cursor.execute("""
                ALTER TABLE contacts
                ADD COLUMN IF NOT EXISTS sync_status VARCHAR(20) DEFAULT 'synced',
                ADD COLUMN IF NOT EXISTS last_synced_at DATETIME,
                ADD COLUMN IF NOT EXISTS local_modified_at DATETIME,
                ADD COLUMN IF NOT EXISTS google_resource_name VARCHAR(255),
                ADD COLUMN IF NOT EXISTS google_etag VARCHAR(255)
            """)
            conn.commit()
        except Exception as e:
            # Columns may already exist
            pass

        # Get sync statistics
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN sync_status = 'synced' OR sync_status IS NULL THEN 1 ELSE 0 END) as synced,
                SUM(CASE WHEN sync_status = 'pending_push' THEN 1 ELSE 0 END) as pending_push,
                SUM(CASE WHEN sync_status = 'conflict' THEN 1 ELSE 0 END) as conflicts,
                SUM(CASE WHEN google_resource_name IS NOT NULL THEN 1 ELSE 0 END) as google_linked,
                MAX(last_synced_at) as last_sync
            FROM contacts
        """)

        row = cursor.fetchone()
        if db_type != 'mysql':
            row = dict(zip([desc[0] for desc in cursor.description], row)) if row else {}

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'total_contacts': row.get('total', 0) or 0,
            'synced': row.get('synced', 0) or 0,
            'pending_push': row.get('pending_push', 0) or 0,
            'conflicts': row.get('conflicts', 0) or 0,
            'google_linked': row.get('google_linked', 0) or 0,
            'last_sync': row.get('last_sync').isoformat() if row.get('last_sync') else None
        })

    except Exception as e:
        print(f"Sync status error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/sync/pending", methods=["GET"])
def atlas_sync_pending():
    """Get contacts pending sync"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT id, display_name, email, phone, company, sync_status,
                   local_modified_at, last_synced_at, google_resource_name
            FROM contacts
            WHERE sync_status IN ('pending_push', 'conflict')
            ORDER BY local_modified_at DESC
            LIMIT 100
        """)

        rows = cursor.fetchall()
        if db_type != 'mysql':
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in rows]

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'contacts': rows,
            'count': len(rows)
        })

    except Exception as e:
        print(f"Sync pending error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/sync/mark-modified", methods=["POST"])
def atlas_sync_mark_modified():
    """Mark a contact as modified (pending sync)"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')

        if not contact_id:
            return jsonify({'error': 'contact_id required'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            UPDATE contacts
            SET sync_status = 'pending_push',
                local_modified_at = NOW()
            WHERE id = %s
        """, (contact_id,))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'contact_id': contact_id, 'status': 'pending_push'})

    except Exception as e:
        print(f"Mark modified error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/sync/google/push", methods=["POST"])
def atlas_sync_google_push():
    """Push local changes to Google Contacts"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        # Get Gmail token
        gmail_token = os.getenv('GMAIL_TOKEN_BRIAN_DOWNHOME_COM') or os.getenv('GMAIL_TOKEN_BRIAN_MUSICCITYRODEO_COM')
        if not gmail_token:
            return jsonify({'error': 'No Google token configured', 'success': False}), 400

        token_data = json.loads(gmail_token)

        # Check if contacts scope is available
        scopes = token_data.get('scopes', [])
        has_contacts_scope = any('contacts' in s for s in scopes)

        if not has_contacts_scope:
            return jsonify({
                'error': 'Contacts scope not authorized. Please reauthorize with contacts.readonly scope.',
                'success': False,
                'needs_reauth': True
            }), 400

        creds = Credentials.from_authorized_user_info(token_data)
        people_service = build('people', 'v1', credentials=creds)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contacts pending push
        cursor.execute("""
            SELECT id, display_name, first_name, last_name, email, phone, company, job_title,
                   google_resource_name, google_etag
            FROM contacts
            WHERE sync_status = 'pending_push'
            LIMIT 50
        """)

        rows = cursor.fetchall()
        if db_type != 'mysql':
            columns = [desc[0] for desc in cursor.description]
            rows = [dict(zip(columns, row)) for row in rows]

        pushed = 0
        errors = []

        for contact in rows:
            try:
                person_data = {
                    'names': [{
                        'givenName': contact.get('first_name') or '',
                        'familyName': contact.get('last_name') or '',
                        'displayName': contact.get('display_name') or ''
                    }]
                }

                if contact.get('email'):
                    person_data['emailAddresses'] = [{'value': contact['email'], 'type': 'work'}]

                if contact.get('phone'):
                    person_data['phoneNumbers'] = [{'value': contact['phone'], 'type': 'mobile'}]

                if contact.get('company') or contact.get('job_title'):
                    person_data['organizations'] = [{
                        'name': contact.get('company') or '',
                        'title': contact.get('job_title') or ''
                    }]

                if contact.get('google_resource_name'):
                    # Update existing contact
                    result = people_service.people().updateContact(
                        resourceName=contact['google_resource_name'],
                        updatePersonFields='names,emailAddresses,phoneNumbers,organizations',
                        body=person_data
                    ).execute()
                else:
                    # Create new contact
                    result = people_service.people().createContact(body=person_data).execute()

                    # Update local record with Google resource name
                    update_cursor = conn.cursor()
                    update_cursor.execute("""
                        UPDATE contacts
                        SET google_resource_name = %s, google_etag = %s
                        WHERE id = %s
                    """, (result.get('resourceName'), result.get('etag'), contact['id']))
                    update_cursor.close()

                # Mark as synced
                sync_cursor = conn.cursor()
                sync_cursor.execute("""
                    UPDATE contacts
                    SET sync_status = 'synced', last_synced_at = NOW()
                    WHERE id = %s
                """, (contact['id'],))
                sync_cursor.close()

                pushed += 1

            except Exception as contact_err:
                errors.append({
                    'contact_id': contact['id'],
                    'name': contact.get('display_name'),
                    'error': str(contact_err)
                })

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'success': True,
            'pushed': pushed,
            'errors': errors,
            'error_count': len(errors)
        })

    except Exception as e:
        print(f"Google push error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500


@app.route("/api/atlas/sync/google/pull", methods=["POST"])
def atlas_sync_google_pull():
    """Pull contacts from Google and merge with local database"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        # Get Gmail token
        gmail_token = os.getenv('GMAIL_TOKEN_BRIAN_DOWNHOME_COM') or os.getenv('GMAIL_TOKEN_BRIAN_MUSICCITYRODEO_COM')
        if not gmail_token:
            return jsonify({'error': 'No Google token configured', 'success': False}), 400

        token_data = json.loads(gmail_token)
        creds = Credentials.from_authorized_user_info(token_data)
        people_service = build('people', 'v1', credentials=creds)

        # Fetch contacts from Google
        all_contacts = []
        page_token = None

        while True:
            results = people_service.people().connections().list(
                resourceName='people/me',
                pageSize=1000,
                personFields='names,emailAddresses,phoneNumbers,organizations,photos',
                pageToken=page_token
            ).execute()

            connections = results.get('connections', [])
            all_contacts.extend(connections)

            page_token = results.get('nextPageToken')
            if not page_token:
                break

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        imported = 0
        updated = 0

        for person in all_contacts:
            try:
                resource_name = person.get('resourceName', '')
                etag = person.get('etag', '')

                names = person.get('names', [{}])
                name = names[0] if names else {}
                display_name = name.get('displayName', '')
                first_name = name.get('givenName', '')
                last_name = name.get('familyName', '')

                emails = person.get('emailAddresses', [])
                email = emails[0].get('value', '').lower() if emails else ''

                phones = person.get('phoneNumbers', [])
                phone = phones[0].get('value', '') if phones else ''

                orgs = person.get('organizations', [])
                company = orgs[0].get('name', '') if orgs else ''
                job_title = orgs[0].get('title', '') if orgs else ''

                photos = person.get('photos', [])
                photo_url = photos[0].get('url', '') if photos else ''

                if not display_name and not email:
                    continue

                # Check if contact exists by google_resource_name or email
                cursor.execute("""
                    SELECT id FROM contacts
                    WHERE google_resource_name = %s OR (email = %s AND email != '')
                    LIMIT 1
                """, (resource_name, email))

                existing = cursor.fetchone()

                if existing:
                    # Update existing contact
                    cursor.execute("""
                        UPDATE contacts SET
                            display_name = COALESCE(NULLIF(%s, ''), display_name),
                            first_name = COALESCE(NULLIF(%s, ''), first_name),
                            last_name = COALESCE(NULLIF(%s, ''), last_name),
                            phone = COALESCE(NULLIF(%s, ''), phone),
                            company = COALESCE(NULLIF(%s, ''), company),
                            job_title = COALESCE(NULLIF(%s, ''), job_title),
                            photo_url = COALESCE(NULLIF(%s, ''), photo_url),
                            google_resource_name = %s,
                            google_etag = %s,
                            last_synced_at = NOW(),
                            sync_status = 'synced'
                        WHERE id = %s
                    """, (display_name, first_name, last_name, phone, company, job_title,
                          photo_url, resource_name, etag, existing[0]))
                    updated += 1
                else:
                    # Insert new contact
                    cursor.execute("""
                        INSERT INTO contacts (
                            display_name, first_name, last_name, email, phone,
                            company, job_title, photo_url, source,
                            google_resource_name, google_etag,
                            sync_status, last_synced_at, created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'google', %s, %s, 'synced', NOW(), NOW())
                    """, (display_name, first_name, last_name, email, phone,
                          company, job_title, photo_url, resource_name, etag))
                    imported += 1

            except Exception as contact_err:
                print(f"Error importing contact: {contact_err}")
                continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'success': True,
            'fetched': len(all_contacts),
            'imported': imported,
            'updated': updated
        })

    except Exception as e:
        print(f"Google pull error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500


@app.route("/api/atlas/sync/resolve-conflict", methods=["POST"])
def atlas_sync_resolve_conflict():
    """Resolve a sync conflict"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')
        resolution = data.get('resolution')  # 'local' or 'remote'

        if not contact_id or resolution not in ('local', 'remote'):
            return jsonify({'error': 'contact_id and resolution (local/remote) required'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        if resolution == 'local':
            # Keep local version, mark for push
            cursor.execute("""
                UPDATE contacts
                SET sync_status = 'pending_push'
                WHERE id = %s
            """, (contact_id,))
        else:
            # Will pull from remote on next sync
            cursor.execute("""
                UPDATE contacts
                SET sync_status = 'synced',
                    google_etag = NULL
                WHERE id = %s
            """, (contact_id,))

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({'ok': True, 'contact_id': contact_id, 'resolution': resolution})

    except Exception as e:
        print(f"Resolve conflict error: {e}")
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/contacts", methods=["POST"])
def atlas_contact_create():
    """Create a new contact"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No data provided'}), 400

        # Require at least a name
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'error': 'Name is required'}), 400

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Insert into contacts table (single source of truth)
        insert_query = """
            INSERT INTO contacts (
                name, first_name, last_name, company, job_title,
                email, phone, category, notes, source, created_at, updated_at
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
        """

        values = (
            name,
            data.get('first_name', ''),
            data.get('last_name', ''),
            data.get('company', ''),
            data.get('title') or data.get('job_title', ''),
            data.get('email', ''),
            data.get('phone', ''),
            data.get('category', 'General'),
            data.get('notes', ''),
            data.get('source', 'manual')
        )

        cursor.execute(insert_query, values)
        new_id = cursor.lastrowid
        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "message": "Contact created successfully",
            "id": new_id
        })

    except Exception as e:
        print(f"ATLAS contact create error: {e}")
        import traceback
        traceback.print_exc()
        # Ensure connection is returned on error
        try:
            return_db_connection(conn, discard=True)
        except:
            pass
        return jsonify({'error': str(e)}), 500


# =============================================================================
# CONTACT SYNC ENGINE API ENDPOINTS
# =============================================================================

@app.route("/api/atlas/sync/adapters", methods=["GET"])
def atlas_sync_adapters():
    """Get contact sync engine status and available adapters"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    if not CONTACT_SYNC_AVAILABLE:
        return jsonify({'error': 'Contact Sync Engine not available'}), 503

    try:
        adapters = []

        # Check Apple Contacts
        if AppleContactsAdapter:
            adapter = AppleContactsAdapter()
            adapters.append({
                "name": "apple",
                "display_name": "Apple Contacts",
                "supports_push": adapter.supports_push,
                "supports_incremental": adapter.supports_incremental,
                "available": True
            })

        # Check Google Contacts (requires OAuth)
        adapters.append({
            "name": "google",
            "display_name": "Google Contacts",
            "supports_push": True,
            "supports_incremental": True,
            "available": len(GMAIL_ACCOUNTS) > 0,
            "accounts": GMAIL_ACCOUNTS
        })

        # LinkedIn (import only)
        adapters.append({
            "name": "linkedin",
            "display_name": "LinkedIn",
            "supports_push": False,
            "supports_incremental": False,
            "available": True,
            "note": "Import from CSV export"
        })

        return jsonify({
            "ok": True,
            "engine_available": CONTACT_SYNC_AVAILABLE,
            "adapters": adapters
        })
    except Exception as e:
        print(f"Contact sync status error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/sync/apple", methods=["POST"])
def atlas_sync_apple():
    """Sync Apple Contacts to ATLAS"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    import platform

    # Apple Contacts sync only works on macOS
    if platform.system() != 'Darwin':
        return jsonify({
            'error': 'Apple Contact sync is only available on macOS. Use Google sync instead.',
            'success': False,
            'ok': False
        }), 503

    if not CONTACT_SYNC_AVAILABLE or not AppleContactsAdapter:
        return jsonify({
            'error': 'Apple Contact Sync not available',
            'success': False,
            'ok': False
        }), 503

    try:
        import asyncio

        async def run_sync():
            adapter = AppleContactsAdapter()
            if not await adapter.connect():
                return {"ok": False, "success": False, "error": "Could not connect to Apple Contacts"}

            contacts = await adapter.pull_contacts()
            return {
                "ok": True,
                "success": True,
                "pulled": len(contacts),
                "count": len(contacts),
                "contacts": [
                    {
                        "name": c.display_name,
                        "emails": [e["email"] for e in c.emails],
                        "phones": [p["number"] for p in c.phones],
                        "company": c.company,
                        "job_title": c.job_title
                    }
                    for c in contacts[:100]  # Limit preview to 100
                ]
            }

        result = asyncio.run(run_sync())
        return jsonify(result)
    except Exception as e:
        print(f"Apple contact sync error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False, 'ok': False}), 500


@app.route("/api/atlas/sync/google", methods=["POST"])
def atlas_sync_google():
    """Sync Google Contacts to ATLAS using Google People API"""
    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    if not ATLAS_AVAILABLE or not GooglePeopleAPI:
        return jsonify({'error': 'Google People API not available', 'success': False}), 503

    try:
        # Handle requests with or without JSON body (silent=True prevents 415 error)
        data = request.get_json(silent=True) or {}
        limit = data.get('limit', 200)

        people = GooglePeopleAPI()
        contacts = people.get_all_contacts(limit=limit)

        # Store contacts in database
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Create atlas_contacts table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS atlas_contacts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                display_name VARCHAR(255),
                email VARCHAR(255),
                phone VARCHAR(100),
                company VARCHAR(255),
                job_title VARCHAR(255),
                photo_url TEXT,
                source VARCHAR(50) DEFAULT 'google',
                source_id VARCHAR(255),
                last_interaction DATETIME,
                interaction_count INT DEFAULT 0,
                tags TEXT,
                notes TEXT,
                linkedin_url VARCHAR(500),
                twitter_handle VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_email_source (email, source)
            )
        """)

        # Create contact_interactions table for tracking all interactions
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contact_interactions (
                id INT AUTO_INCREMENT PRIMARY KEY,
                contact_id INT NOT NULL,
                interaction_type VARCHAR(50) NOT NULL,
                interaction_date DATETIME NOT NULL,
                source VARCHAR(50),
                source_id VARCHAR(255),
                subject TEXT,
                content TEXT,
                sentiment VARCHAR(20),
                metadata JSON,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                INDEX idx_contact_date (contact_id, interaction_date),
                INDEX idx_type (interaction_type),
                INDEX idx_source (source)
            )
        """)

        synced = 0
        for contact in contacts:
            try:
                # Handle both dict and object access patterns
                name = contact.get('name', '') if isinstance(contact, dict) else getattr(contact, 'name', '')
                email = contact.get('email', '') if isinstance(contact, dict) else getattr(contact, 'email', '')
                phone = contact.get('phone', '') if isinstance(contact, dict) else getattr(contact, 'phone', '')
                company = contact.get('company', '') if isinstance(contact, dict) else getattr(contact, 'company', '')
                job_title = contact.get('job_title', '') if isinstance(contact, dict) else getattr(contact, 'job_title', '')
                photo_url = contact.get('photo_url', '') if isinstance(contact, dict) else getattr(contact, 'photo_url', '')
                resource_name = contact.get('resource_name', '') if isinstance(contact, dict) else getattr(contact, 'resource_name', '')

                if email:
                    cursor.execute("""
                        INSERT INTO contacts (display_name, email, phone, company, job_title, photo_url, source, source_id)
                        VALUES (%s, %s, %s, %s, %s, %s, 'google', %s)
                        ON DUPLICATE KEY UPDATE
                            display_name = VALUES(display_name),
                            phone = VALUES(phone),
                            company = VALUES(company),
                            job_title = VALUES(job_title),
                            photo_url = VALUES(photo_url),
                            source_id = VALUES(source_id),
                            updated_at = CURRENT_TIMESTAMP
                    """, (name, email, phone, company, job_title, photo_url, resource_name))
                    synced += 1
            except Exception as contact_err:
                print(f"Error syncing contact: {contact_err}")
                continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "success": True,
            "synced": synced,
            "count": synced,
            "total_fetched": len(contacts),
            "source": "google_people_api"
        })

    except Exception as e:
        print(f"Google contact sync error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500


def _import_contacts_from_json(contacts_data):
    """Helper function to import contacts from JSON array to MySQL"""
    error_details = []  # Capture actual error messages
    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Create contacts table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                title TEXT,
                company VARCHAR(255),
                category VARCHAR(100),
                priority VARCHAR(50),
                notes TEXT,
                relationship VARCHAR(100),
                status VARCHAR(100),
                strategic_notes TEXT,
                connected_on VARCHAR(100),
                name_tokens TEXT,
                email VARCHAR(255),
                phone VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_name (name(191))
            )
        """)
        conn.commit()

        # Add missing columns if they don't exist (for existing tables)
        missing_columns = [
            ("email", "VARCHAR(255)"),
            ("phone", "VARCHAR(100)"),
            ("first_name", "VARCHAR(100)"),
            ("last_name", "VARCHAR(100)"),
            ("title", "TEXT"),
            ("company", "VARCHAR(255)"),
            ("category", "VARCHAR(100)"),
            ("priority", "VARCHAR(50)"),
            ("notes", "TEXT"),
            ("relationship", "VARCHAR(100)"),
            ("status", "VARCHAR(100)"),
            ("strategic_notes", "TEXT"),
            ("connected_on", "VARCHAR(100)"),
            ("name_tokens", "TEXT"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
            # Relationship intelligence columns
            ("relationship_score", "INT DEFAULT 0"),
            ("last_interaction", "DATETIME"),
            ("interaction_count", "INT DEFAULT 0"),
            ("birthday", "DATE"),
            ("anniversary", "DATE"),
            ("photo_url", "TEXT"),
            ("linkedin_url", "VARCHAR(500)"),
            ("twitter_handle", "VARCHAR(100)"),
        ]
        columns_added = []
        for col_name, col_type in missing_columns:
            try:
                cursor.execute(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_type}")
                conn.commit()
                columns_added.append(col_name)
                print(f"Added missing column: {col_name}")
            except Exception:
                pass  # Column already exists
        if columns_added:
            print(f"Schema migration: Added columns {columns_added}")

        imported = 0
        updated = 0
        errors = 0

        # Check which columns actually exist (for backward compatibility)
        cursor.execute("DESCRIBE contacts")
        describe_results = cursor.fetchall()
        # Handle both DictCursor (returns dicts) and regular cursor (returns tuples)
        if describe_results and isinstance(describe_results[0], dict):
            existing_cols = {row['Field'] for row in describe_results}
        else:
            existing_cols = {row[0] for row in describe_results}
        has_updated_at = 'updated_at' in existing_cols
        print(f"Contacts table columns: {sorted(existing_cols)}")

        for contact in contacts_data:
            name = contact.get('name', '').strip() if isinstance(contact, dict) else ''
            if not name:
                errors += 1
                error_details.append({"name": "(empty)", "error": "Empty name"})
                continue

            try:
                # Build INSERT dynamically based on available columns
                base_cols = ['name', 'first_name', 'last_name', 'title', 'company', 'category', 'priority',
                             'notes', 'relationship', 'status', 'strategic_notes', 'connected_on', 'name_tokens']

                # Add email and phone if they exist
                if 'email' in existing_cols:
                    base_cols.append('email')
                if 'phone' in existing_cols:
                    base_cols.append('phone')

                placeholders = ', '.join(['%s'] * len(base_cols))
                col_list = ', '.join(base_cols)

                # Build ON DUPLICATE KEY UPDATE clause
                update_parts = [f"{col} = VALUES({col})" for col in base_cols if col != 'name']
                if has_updated_at:
                    update_parts.append("updated_at = CURRENT_TIMESTAMP")
                update_clause = ', '.join(update_parts)

                sql = f"""
                    INSERT INTO contacts ({col_list})
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {update_clause}
                """

                # Build values list matching columns
                values = [
                    name,
                    contact.get('first_name', ''),
                    contact.get('last_name', ''),
                    contact.get('title', ''),
                    contact.get('company', ''),
                    contact.get('category', ''),
                    contact.get('priority', ''),
                    contact.get('notes', ''),
                    contact.get('relationship', ''),
                    contact.get('status', ''),
                    contact.get('strategic_notes', ''),
                    contact.get('connected_on', ''),
                    contact.get('name_tokens', '')
                ]
                if 'email' in existing_cols:
                    values.append(contact.get('email', ''))
                if 'phone' in existing_cols:
                    values.append(contact.get('phone', ''))

                cursor.execute(sql, tuple(values))

                if cursor.rowcount == 1:
                    imported += 1
                else:
                    updated += 1

            except Exception as row_err:
                print(f"Error importing contact {name}: {row_err}")
                errors += 1
                # Keep only first 10 error details to avoid huge responses
                if len(error_details) < 10:
                    error_details.append({"name": name[:50], "error": str(row_err)[:200]})
                continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "success": True,
            "imported": imported,
            "updated": updated,
            "errors": errors,
            "total": imported + updated,
            "source": "json_upload",
            "error_details": error_details if error_details else None
        })

    except Exception as e:
        print(f"JSON contact import error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'error': str(e),
            'success': False,
            'error_details': error_details if error_details else None
        }), 500


@app.route("/api/atlas/sync/crm", methods=["POST"])
def atlas_sync_crm():
    """Sync contacts from JSON data or CRM CSV file to MySQL contacts table"""
    import csv

    # Check admin_key or session auth
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        # Check if JSON data is provided in request body
        data = request.get_json() if request.is_json else {}
        contacts_data = data.get('contacts') if data else None

        # If contacts JSON provided, use it directly
        if contacts_data and isinstance(contacts_data, list):
            return _import_contacts_from_json(contacts_data)

        # Otherwise try CSV file
        csv_path = data.get('csv_path') if data else None

        # Default CSV path
        if not csv_path:
            default_paths = [
                'archive/data/contacts.csv',
                '/app/archive/data/contacts.csv',
            ]
            for path in default_paths:
                if os.path.exists(path):
                    csv_path = path
                    break

        if not csv_path or not os.path.exists(csv_path):
            return jsonify({
                'error': 'No contacts data provided. Send JSON with "contacts" array or ensure archive/data/contacts.csv exists.',
                'ok': False
            }), 404

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Create contacts table if it doesn't exist
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                title TEXT,
                company VARCHAR(255),
                category VARCHAR(100),
                priority VARCHAR(50),
                notes TEXT,
                relationship VARCHAR(100),
                status VARCHAR(100),
                strategic_notes TEXT,
                connected_on VARCHAR(100),
                name_tokens TEXT,
                email VARCHAR(255),
                phone VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_name (name(191))
            )
        """)
        conn.commit()

        imported = 0
        updated = 0
        errors = 0

        with open(csv_path, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                name = row.get('name', '').strip()
                if not name:
                    continue

                try:
                    # Use INSERT ... ON DUPLICATE KEY UPDATE for upsert
                    cursor.execute("""
                        INSERT INTO contacts
                        (name, first_name, last_name, title, company, category, priority,
                         notes, relationship, status, strategic_notes, connected_on, name_tokens)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            first_name = VALUES(first_name),
                            last_name = VALUES(last_name),
                            title = VALUES(title),
                            company = VALUES(company),
                            category = VALUES(category),
                            priority = VALUES(priority),
                            notes = VALUES(notes),
                            relationship = VALUES(relationship),
                            status = VALUES(status),
                            strategic_notes = VALUES(strategic_notes),
                            connected_on = VALUES(connected_on),
                            name_tokens = VALUES(name_tokens),
                            updated_at = CURRENT_TIMESTAMP
                    """, (
                        name,
                        row.get('first_name', ''),
                        row.get('last_name', ''),
                        row.get('title', ''),
                        row.get('company', ''),
                        row.get('category', ''),
                        row.get('priority', ''),
                        row.get('notes', ''),
                        row.get('relationship', ''),
                        row.get('status', ''),
                        row.get('strategic_notes', ''),
                        row.get('connected_on', ''),
                        row.get('name_tokens', '')
                    ))

                    if cursor.rowcount == 1:
                        imported += 1
                    else:
                        updated += 1

                except Exception as row_err:
                    print(f"Error importing contact {name}: {row_err}")
                    errors += 1
                    continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "success": True,
            "imported": imported,
            "updated": updated,
            "errors": errors,
            "total": imported + updated,
            "source": "crm_csv",
            "csv_path": csv_path
        })

    except Exception as e:
        print(f"CRM contact sync error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e), 'success': False}), 500


@app.route("/api/atlas/contacts/migrate", methods=["POST"])
def atlas_contacts_migrate():
    """Migrate contacts table schema - add missing columns to existing table"""
    # Check admin_key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Admin key required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        results = []

        data = request.get_json() or {}
        force_recreate = data.get('force_recreate', False)

        if force_recreate:
            # Drop dependent tables first to avoid foreign key constraint errors
            try:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
                conn.commit()
                results.append("Disabled foreign key checks")
            except Exception as e:
                results.append(f"Could not disable FK checks: {str(e)}")

            try:
                cursor.execute("DROP TABLE IF EXISTS contact_emails")
                conn.commit()
                results.append("Dropped contact_emails table")
            except Exception as e:
                results.append(f"Could not drop contact_emails: {str(e)}")

            try:
                cursor.execute("DROP TABLE IF EXISTS contacts")
                conn.commit()
                results.append("Dropped contacts table")
            except Exception as e:
                results.append(f"Could not drop contacts: {str(e)}")

            try:
                cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
                conn.commit()
                results.append("Re-enabled foreign key checks")
            except Exception as e:
                results.append(f"Could not re-enable FK checks: {str(e)}")

        # Create the table with all columns
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                first_name VARCHAR(100),
                last_name VARCHAR(100),
                title TEXT,
                company VARCHAR(255),
                category VARCHAR(100),
                priority VARCHAR(50),
                notes TEXT,
                relationship VARCHAR(100),
                status VARCHAR(100),
                strategic_notes TEXT,
                connected_on VARCHAR(100),
                name_tokens TEXT,
                email VARCHAR(255),
                phone VARCHAR(100),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                UNIQUE KEY unique_name (name(191))
            )
        """)
        conn.commit()
        results.append("Created/verified contacts table")

        # Add any missing columns to existing table
        missing_columns = [
            ("email", "VARCHAR(255)"),
            ("phone", "VARCHAR(100)"),
            ("first_name", "VARCHAR(100)"),
            ("last_name", "VARCHAR(100)"),
            ("title", "TEXT"),
            ("company", "VARCHAR(255)"),
            ("category", "VARCHAR(100)"),
            ("priority", "VARCHAR(50)"),
            ("notes", "TEXT"),
            ("relationship", "VARCHAR(100)"),
            ("status", "VARCHAR(100)"),
            ("strategic_notes", "TEXT"),
            ("connected_on", "VARCHAR(100)"),
            ("name_tokens", "TEXT"),
            ("location", "VARCHAR(255)"),
            ("city", "VARCHAR(100)"),
            ("state", "VARCHAR(50)"),
            ("country", "VARCHAR(100)"),
            ("created_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"),
            ("updated_at", "TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
        ]

        columns_added = []
        for col_name, col_type in missing_columns:
            try:
                cursor.execute(f"ALTER TABLE contacts ADD COLUMN {col_name} {col_type}")
                conn.commit()
                columns_added.append(col_name)
            except Exception:
                pass  # Column already exists

        if columns_added:
            results.append(f"Added columns: {columns_added}")
        else:
            results.append("No columns needed to be added")

        # Verify columns - DESCRIBE returns dict rows with 'Field' key (using DictCursor)
        cursor.execute("DESCRIBE contacts")
        describe_results = cursor.fetchall()
        # Handle both DictCursor (returns dicts) and regular cursor (returns tuples)
        if describe_results and isinstance(describe_results[0], dict):
            existing_cols = {row['Field'] for row in describe_results}
        else:
            existing_cols = {row[0] for row in describe_results}
        results.append(f"Current columns: {sorted(existing_cols)}")

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "success": True,
            "results": results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        # Get MySQL error details if available
        error_msg = str(e)
        if hasattr(e, 'args') and len(e.args) >= 2:
            error_msg = f"MySQL Error {e.args[0]}: {e.args[1]}"
        return jsonify({'error': error_msg, 'success': False, 'traceback': traceback.format_exc()}), 500


@app.route("/api/atlas/contacts/upload", methods=["POST"])
def atlas_contacts_upload():
    """Bulk upload contacts from JSON - used by Apple Contacts sync"""
    # Check admin_key
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        return jsonify({'error': 'Admin key required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': 'No JSON data provided'}), 400

        contacts = data.get('contacts', [])
        if not contacts:
            return jsonify({'error': 'No contacts provided', 'imported': 0, 'updated': 0}), 200

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        imported = 0
        updated = 0
        errors = []

        for contact in contacts:
            try:
                name = (contact.get('name') or '').strip()
                if not name:
                    continue

                # Generate name tokens for search
                name_tokens = name.lower()
                parts = name_tokens.split()
                for p in parts:
                    if len(p) >= 3:
                        name_tokens += f" {p[:3]}"

                # Build upsert query (INSERT ... ON DUPLICATE KEY UPDATE for MySQL)
                cursor.execute("""
                    INSERT INTO contacts (name, first_name, last_name, email, phone, company, title, category, priority, notes, source, name_tokens)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON DUPLICATE KEY UPDATE
                        first_name = COALESCE(VALUES(first_name), first_name),
                        last_name = COALESCE(VALUES(last_name), last_name),
                        email = COALESCE(VALUES(email), email),
                        phone = COALESCE(VALUES(phone), phone),
                        company = COALESCE(VALUES(company), company),
                        title = COALESCE(VALUES(title), title),
                        category = COALESCE(VALUES(category), category),
                        priority = COALESCE(VALUES(priority), priority),
                        notes = COALESCE(VALUES(notes), notes),
                        source = COALESCE(VALUES(source), source),
                        name_tokens = COALESCE(VALUES(name_tokens), name_tokens),
                        updated_at = CURRENT_TIMESTAMP
                """, (
                    name[:255],
                    (contact.get('first_name') or '')[:100],
                    (contact.get('last_name') or '')[:100],
                    (contact.get('email') or '')[:255],
                    (contact.get('phone') or '')[:100],
                    (contact.get('company') or '')[:255],
                    contact.get('title') or '',
                    (contact.get('category') or 'General')[:100],
                    (contact.get('priority') or 'Normal')[:50],
                    contact.get('notes') or '',
                    (contact.get('source') or 'Apple Contacts')[:100],
                    name_tokens[:500]
                ))

                if cursor.rowcount == 1:
                    imported += 1
                else:
                    updated += 1

            except Exception as contact_err:
                errors.append(f"Error with '{name}': {str(contact_err)}")
                continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'imported': imported,
            'updated': updated,
            'errors': errors[:10] if errors else []  # Only return first 10 errors
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        error_msg = str(e)
        if hasattr(e, 'args') and len(e.args) >= 2:
            error_msg = f"MySQL Error {e.args[0]}: {e.args[1]}"
        return jsonify({'error': error_msg, 'ok': False}), 500


@app.route("/api/atlas/sync/linkedin", methods=["POST"])
@login_required
def atlas_sync_linkedin():
    """Import LinkedIn contacts from CSV"""
    if not CONTACT_SYNC_AVAILABLE:
        return jsonify({'error': 'Contact Sync Engine not available'}), 503

    try:
        data = request.get_json() or {}
        csv_path = data.get('csv_path')

        if not csv_path:
            return jsonify({'error': 'csv_path required'}), 400

        import asyncio

        async def run_import():
            adapter = LinkedInAdapter(csv_path=csv_path)
            contacts = await adapter.pull_contacts()
            return {
                "ok": True,
                "imported": len(contacts),
                "contacts": [
                    {
                        "name": c.display_name,
                        "company": c.company,
                        "job_title": c.job_title,
                        "linkedin_url": c.linkedin_url
                    }
                    for c in contacts[:50]
                ]
            }

        result = asyncio.run(run_import())
        return jsonify(result)
    except Exception as e:
        print(f"LinkedIn import error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


# =============================================================================
# AI-POWERED CONTACT FILTERING & ORGANIZATION
# =============================================================================

@app.route("/api/atlas/ai/analyze-contacts", methods=["POST"])
def atlas_ai_analyze_contacts():
    """Use AI to analyze and categorize contacts"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        contact_ids = data.get('contact_ids', [])  # Specific contacts or empty for batch
        batch_size = min(data.get('batch_size', 50), 100)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contacts to analyze
        if contact_ids:
            placeholders = ','.join(['%s'] * len(contact_ids))
            query = f"""
                SELECT id, display_name, first_name, last_name, company, job_title,
                       email, phone, category, notes, source
                FROM contacts
                WHERE id IN ({placeholders})
            """
            cursor.execute(query, tuple(contact_ids))
        else:
            # Get contacts that haven't been AI-categorized recently
            query = """
                SELECT id, display_name, first_name, last_name, company, job_title,
                       email, phone, category, notes, source
                FROM contacts
                WHERE ai_analyzed_at IS NULL OR ai_analyzed_at < DATE_SUB(NOW(), INTERVAL 30 DAY)
                LIMIT %s
            """
            cursor.execute(query, (batch_size,))

        contacts = cursor.fetchall()
        cursor.close()
        return_db_connection(conn)

        if not contacts:
            return jsonify({
                'ok': True,
                'analyzed': 0,
                'message': 'No contacts need analysis'
            })

        # Use Gemini AI to analyze contacts
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_AI_KEY')
        if not api_key:
            return jsonify({'error': 'AI not configured'}), 503

        analyzed_results = []
        for contact in contacts:
            analysis = _ai_analyze_single_contact(contact, api_key)
            if analysis:
                analyzed_results.append({
                    'id': contact['id'],
                    'name': contact['display_name'],
                    **analysis
                })
                # Update in database
                _update_contact_ai_analysis(contact['id'], analysis)

        return jsonify({
            'ok': True,
            'analyzed': len(analyzed_results),
            'results': analyzed_results
        })

    except Exception as e:
        print(f"AI contact analysis error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


def _ai_analyze_single_contact(contact, api_key):
    """Analyze a single contact with Gemini AI"""
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        prompt = f"""Analyze this contact and provide categorization:
Name: {contact.get('display_name', '')}
Company: {contact.get('company', '')}
Title: {contact.get('job_title', '')}
Email: {contact.get('email', '')}
Notes: {contact.get('notes', '')}

Return a JSON object with:
1. "category": One of: Executive, Technical, Sales, Marketing, Finance, Legal, Operations, Creative, Personal, Family, Friend, Vendor, Investor, Media, Other
2. "priority": One of: VIP, High, Normal, Low
3. "tags": Array of relevant tags (max 5), e.g., ["decision-maker", "technical", "startup", "enterprise"]
4. "relationship_type": One of: Professional, Personal, Business Partner, Client, Prospect, Vendor, Investor, Advisor, Friend, Family
5. "suggested_actions": Array of 1-2 suggested engagement actions

Return ONLY valid JSON, no other text."""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Parse JSON from response
        import json
        # Clean up markdown if present
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        text = text.strip()

        analysis = json.loads(text)
        return analysis

    except Exception as e:
        print(f"AI analysis error for contact {contact.get('id')}: {e}")
        return None


def _update_contact_ai_analysis(contact_id, analysis):
    """Update contact with AI analysis results"""
    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Update category and priority if available
        import json
        tags_str = json.dumps(analysis.get('tags', []))

        update_query = """
            UPDATE contacts
            SET category = %s,
                priority = %s,
                tags = %s,
                ai_analyzed_at = NOW(),
                updated_at = NOW()
            WHERE id = %s
        """
        cursor.execute(update_query, (
            analysis.get('category', 'Other'),
            analysis.get('priority', 'Normal'),
            tags_str,
            contact_id
        ))
        conn.commit()
        cursor.close()
        return_db_connection(conn)

    except Exception as e:
        print(f"Error updating contact AI analysis: {e}")


@app.route("/api/atlas/ai/smart-filters", methods=["GET"])
def atlas_ai_smart_filters():
    """Get AI-generated smart filter suggestions based on contact patterns"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contact statistics for smart filters
        filters = []

        # 1. Category breakdown
        cursor.execute("""
            SELECT category, COUNT(*) as count
            FROM contacts
            WHERE category IS NOT NULL AND category != ''
            GROUP BY category
            ORDER BY count DESC
        """)
        categories = cursor.fetchall()
        for cat in categories:
            if cat['count'] >= 3:  # Only show categories with 3+ contacts
                filters.append({
                    'id': f"category_{cat['category'].lower().replace(' ', '_')}",
                    'name': cat['category'],
                    'type': 'category',
                    'count': cat['count'],
                    'query': {'category': cat['category']}
                })

        # 2. Company-based filters (top companies)
        cursor.execute("""
            SELECT company, COUNT(*) as count
            FROM contacts
            WHERE company IS NOT NULL AND company != ''
            GROUP BY company
            HAVING count >= 2
            ORDER BY count DESC
            LIMIT 10
        """)
        companies = cursor.fetchall()
        for comp in companies:
            filters.append({
                'id': f"company_{comp['company'][:20].lower().replace(' ', '_')}",
                'name': f"At {comp['company']}",
                'type': 'company',
                'count': comp['count'],
                'query': {'company': comp['company']}
            })

        # 3. Priority filters
        cursor.execute("""
            SELECT priority, COUNT(*) as count
            FROM contacts
            WHERE priority IS NOT NULL AND priority != '' AND priority != 'Normal'
            GROUP BY priority
            ORDER BY FIELD(priority, 'VIP', 'High', 'Low')
        """)
        priorities = cursor.fetchall()
        for pri in priorities:
            filters.append({
                'id': f"priority_{pri['priority'].lower()}",
                'name': f"{pri['priority']} Priority",
                'type': 'priority',
                'count': pri['count'],
                'query': {'priority': pri['priority']}
            })

        # 4. Source-based filters
        cursor.execute("""
            SELECT source, COUNT(*) as count
            FROM contacts
            WHERE source IS NOT NULL AND source != ''
            GROUP BY source
            ORDER BY count DESC
        """)
        sources = cursor.fetchall()
        for src in sources:
            if src['count'] >= 5:
                filters.append({
                    'id': f"source_{src['source'].lower().replace(' ', '_')}",
                    'name': f"From {src['source']}",
                    'type': 'source',
                    'count': src['count'],
                    'query': {'source': src['source']}
                })

        # 5. Email domain patterns (for business contacts)
        cursor.execute("""
            SELECT
                SUBSTRING_INDEX(email, '@', -1) as domain,
                COUNT(*) as count
            FROM contacts
            WHERE email IS NOT NULL AND email LIKE '%@%'
            GROUP BY domain
            HAVING count >= 3 AND domain NOT IN ('gmail.com', 'yahoo.com', 'hotmail.com', 'outlook.com', 'icloud.com')
            ORDER BY count DESC
            LIMIT 10
        """)
        domains = cursor.fetchall()
        for dom in domains:
            filters.append({
                'id': f"domain_{dom['domain'].replace('.', '_')}",
                'name': f"@{dom['domain']}",
                'type': 'domain',
                'count': dom['count'],
                'query': {'email_domain': dom['domain']}
            })

        # 6. Recently added (last 7 days)
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM contacts
            WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
        """)
        recent = cursor.fetchone()
        if recent and recent['count'] > 0:
            filters.insert(0, {
                'id': 'recent_added',
                'name': 'Recently Added',
                'type': 'time',
                'count': recent['count'],
                'query': {'days': 7}
            })

        # 7. Has phone number
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM contacts
            WHERE phone IS NOT NULL AND phone != ''
        """)
        with_phone = cursor.fetchone()
        if with_phone:
            filters.append({
                'id': 'has_phone',
                'name': 'With Phone',
                'type': 'completeness',
                'count': with_phone['count'],
                'query': {'has_phone': True}
            })

        # 8. Missing email
        cursor.execute("""
            SELECT COUNT(*) as count
            FROM contacts
            WHERE email IS NULL OR email = ''
        """)
        no_email = cursor.fetchone()
        if no_email and no_email['count'] > 0:
            filters.append({
                'id': 'missing_email',
                'name': 'Missing Email',
                'type': 'incomplete',
                'count': no_email['count'],
                'query': {'missing_email': True}
            })

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'filters': filters,
            'generated_at': datetime.now().isoformat()
        })

    except Exception as e:
        print(f"Smart filters error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/ai/search", methods=["POST"])
def atlas_ai_search():
    """AI-powered natural language contact search"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        query = data.get('query', '').strip()

        if not query:
            return jsonify({'error': 'Query is required'}), 400

        # Use Gemini to understand the search intent
        api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_AI_KEY')
        if not api_key:
            # Fall back to basic search
            return _basic_contact_search(query)

        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-2.0-flash')

        prompt = f"""Parse this natural language search query for contacts and extract search parameters.
Query: "{query}"

Return a JSON object with these optional fields:
- "name": name to search for
- "company": company name
- "category": category filter (Executive, Technical, Sales, Personal, etc.)
- "priority": priority filter (VIP, High, Normal, Low)
- "has_phone": true if looking for contacts with phone
- "has_email": true if looking for contacts with email
- "email_domain": specific email domain
- "keywords": array of keywords to search in notes/tags
- "limit": number of results (default 50)

Examples:
"executives at Google" -> {{"company": "Google", "category": "Executive"}}
"VIP contacts" -> {{"priority": "VIP"}}
"people I met recently" -> {{"days": 7}}
"contacts from tech companies" -> {{"keywords": ["tech", "software", "startup"]}}

Return ONLY valid JSON."""

        response = model.generate_content(prompt)
        text = response.text.strip()

        # Clean up markdown
        import json
        if text.startswith('```'):
            text = text.split('```')[1]
            if text.startswith('json'):
                text = text[4:]
        text = text.strip()

        search_params = json.loads(text)

        # Execute search with extracted parameters
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        conditions = []
        values = []

        if search_params.get('name'):
            conditions.append("(display_name LIKE %s OR first_name LIKE %s OR last_name LIKE %s)")
            name_pattern = f"%{search_params['name']}%"
            values.extend([name_pattern, name_pattern, name_pattern])

        if search_params.get('company'):
            conditions.append("company LIKE %s")
            values.append(f"%{search_params['company']}%")

        if search_params.get('category'):
            conditions.append("category = %s")
            values.append(search_params['category'])

        if search_params.get('priority'):
            conditions.append("priority = %s")
            values.append(search_params['priority'])

        if search_params.get('email_domain'):
            conditions.append("email LIKE %s")
            values.append(f"%@{search_params['email_domain']}")

        if search_params.get('has_phone'):
            conditions.append("phone IS NOT NULL AND phone != ''")

        if search_params.get('has_email'):
            conditions.append("email IS NOT NULL AND email != ''")

        if search_params.get('days'):
            conditions.append("created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)")
            values.append(search_params['days'])

        if search_params.get('keywords'):
            keyword_conditions = []
            for kw in search_params['keywords']:
                keyword_conditions.append("(notes LIKE %s OR tags LIKE %s OR job_title LIKE %s)")
                kw_pattern = f"%{kw}%"
                values.extend([kw_pattern, kw_pattern, kw_pattern])
            if keyword_conditions:
                conditions.append(f"({' OR '.join(keyword_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"
        limit = min(search_params.get('limit', 50), 200)

        query = f"""
            SELECT id, display_name, first_name, last_name, company, job_title,
                   email, phone, category, priority, notes, source, created_at
            FROM contacts
            WHERE {where_clause}
            ORDER BY priority = 'VIP' DESC, priority = 'High' DESC, display_name ASC
            LIMIT {limit}
        """

        cursor.execute(query, tuple(values))
        results = cursor.fetchall()

        cursor.close()
        return_db_connection(conn)

        # Format results
        contacts = []
        for r in results:
            contacts.append({
                'id': r['id'],
                'name': r['display_name'] or f"{r['first_name']} {r['last_name']}".strip(),
                'company': r['company'],
                'title': r['job_title'],
                'email': r['email'],
                'phone': r['phone'],
                'category': r['category'],
                'priority': r['priority']
            })

        return jsonify({
            'ok': True,
            'query': query,
            'parsed_intent': search_params,
            'total': len(contacts),
            'contacts': contacts
        })

    except Exception as e:
        print(f"AI search error: {e}")
        import traceback
        traceback.print_exc()
        # Fall back to basic search
        return _basic_contact_search(data.get('query', ''))


def _basic_contact_search(query):
    """Basic contact search fallback"""
    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        search_pattern = f"%{query}%"
        cursor.execute("""
            SELECT id, display_name, first_name, last_name, company, job_title,
                   email, phone, category, priority
            FROM contacts
            WHERE display_name LIKE %s OR company LIKE %s OR email LIKE %s
                  OR job_title LIKE %s OR notes LIKE %s
            ORDER BY display_name ASC
            LIMIT 50
        """, (search_pattern, search_pattern, search_pattern, search_pattern, search_pattern))

        results = cursor.fetchall()
        cursor.close()
        return_db_connection(conn)

        contacts = []
        for r in results:
            contacts.append({
                'id': r['id'],
                'name': r['display_name'] or f"{r.get('first_name', '')} {r.get('last_name', '')}".strip(),
                'company': r['company'],
                'title': r['job_title'],
                'email': r['email'],
                'phone': r['phone'],
                'category': r['category'],
                'priority': r['priority']
            })

        return jsonify({
            'ok': True,
            'query': query,
            'total': len(contacts),
            'contacts': contacts
        })

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route("/api/atlas/ai/organize", methods=["POST"])
def atlas_ai_organize():
    """AI-powered contact organization - batch categorization and cleanup"""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        action = data.get('action', 'categorize')  # categorize, dedupe, enrich

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        results = {'action': action, 'processed': 0, 'changes': []}

        if action == 'categorize':
            # Find uncategorized contacts and categorize them
            cursor.execute("""
                SELECT id, display_name, company, job_title, email
                FROM contacts
                WHERE (category IS NULL OR category = '' OR category = 'General')
                LIMIT 100
            """)
            uncategorized = cursor.fetchall()

            api_key = os.getenv('GEMINI_API_KEY') or os.getenv('GOOGLE_AI_KEY')
            if api_key:
                for contact in uncategorized:
                    analysis = _ai_analyze_single_contact(contact, api_key)
                    if analysis and analysis.get('category'):
                        _update_contact_ai_analysis(contact['id'], analysis)
                        results['changes'].append({
                            'id': contact['id'],
                            'name': contact['display_name'],
                            'new_category': analysis['category'],
                            'new_priority': analysis.get('priority', 'Normal')
                        })
                        results['processed'] += 1

        elif action == 'dedupe':
            # Find potential duplicates by similar names/emails
            cursor.execute("""
                SELECT c1.id as id1, c1.display_name as name1, c1.email as email1,
                       c2.id as id2, c2.display_name as name2, c2.email as email2
                FROM contacts c1
                JOIN contacts c2 ON c1.id < c2.id
                WHERE (c1.email IS NOT NULL AND c1.email != '' AND c1.email = c2.email)
                   OR (c1.display_name = c2.display_name AND c1.company = c2.company)
                LIMIT 50
            """)
            duplicates = cursor.fetchall()

            for dup in duplicates:
                results['changes'].append({
                    'type': 'potential_duplicate',
                    'contact1': {'id': dup['id1'], 'name': dup['name1'], 'email': dup['email1']},
                    'contact2': {'id': dup['id2'], 'name': dup['name2'], 'email': dup['email2']}
                })
                results['processed'] += 1

        elif action == 'enrich':
            # Find contacts missing key information
            cursor.execute("""
                SELECT id, display_name, email, phone, company, job_title
                FROM contacts
                WHERE (email IS NULL OR email = '')
                   OR (phone IS NULL OR phone = '')
                   OR (company IS NULL OR company = '')
                LIMIT 100
            """)
            incomplete = cursor.fetchall()

            for contact in incomplete:
                missing = []
                if not contact['email']: missing.append('email')
                if not contact['phone']: missing.append('phone')
                if not contact['company']: missing.append('company')

                results['changes'].append({
                    'id': contact['id'],
                    'name': contact['display_name'],
                    'missing_fields': missing
                })
                results['processed'] += 1

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            **results
        })

    except Exception as e:
        print(f"AI organize error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'error': str(e)}), 500


@app.route("/upload_receipt", methods=["POST"])
@login_required
def upload_receipt():
    """
    Form-data:
      _index: int
      file: receipt image

    Saves into /receipts and updates Receipt File columns.
    """
    ensure_df()
    global df

    idx = request.form.get("_index", type=int)
    file = request.files.get("file")

    if idx is None or file is None:
        abort(400, "Missing _index or file")

    # Security: Validate file type
    is_valid, error_msg = validate_upload_file(file)
    if not is_valid:
        abort(400, f"Invalid file: {error_msg}")

    mask = df["_index"] == idx
    if not mask.any():
        abort(404, f"_index {idx} not found")

    RECEIPT_DIR.mkdir(exist_ok=True)

    original_name = file.filename or "receipt.jpg"
    original_name = os.path.basename(original_name)
    stem, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".jpg"

    filename = original_name
    dest = RECEIPT_DIR / filename
    counter = 1
    while dest.exists():
        filename = f"{stem}_{counter}{ext}"
        dest = RECEIPT_DIR / filename
        counter += 1

    file.save(dest)
    print(f"📎 Saved receipt for index {idx}: {dest}", flush=True)

    # Auto-convert PDF to JPG
    if ext.lower() == '.pdf':
        try:
            import subprocess
            print(f"🔄 Converting PDF to JPG: {dest.name}", flush=True)

            # Create JPG path
            jpg_dest = dest.with_suffix('.jpg')
            jpg_filename = filename.rsplit('.', 1)[0] + '.jpg'

            # Try ImageMagick 7 first, then fall back to ImageMagick 6
            commands = [
                ['magick', str(dest) + '[0]', '-density', '150', '-quality', '90',
                 '-background', 'white', '-alpha', 'remove', '-flatten', str(jpg_dest)],
                ['convert', '-density', '150', str(dest) + '[0]', '-quality', '90',
                 '-background', 'white', '-alpha', 'remove', '-flatten', str(jpg_dest)]
            ]

            success = False
            for cmd in commands:
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                    if result.returncode == 0 and jpg_dest.exists():
                        success = True
                        break
                except FileNotFoundError:
                    continue

            if success:
                # Delete original PDF
                os.remove(dest)
                # Update variables to use JPG
                dest = jpg_dest
                filename = jpg_filename
                print(f"✅ Converted PDF to JPG: {jpg_filename}", flush=True)
            else:
                print(f"⚠️  PDF conversion failed, keeping PDF", flush=True)

        except Exception as e:
            print(f"⚠️  PDF conversion error: {e}", flush=True)

    # Auto-convert HEIC to JPG
    if ext.lower() in ['.heic', '.heif']:
        try:
            print(f"🔄 Converting HEIC to JPG: {dest.name}", flush=True)

            # Open HEIC and convert to JPG
            img = Image.open(dest)

            # Convert to RGB if needed
            if img.mode in ('RGBA', 'LA', 'P'):
                img = img.convert('RGB')

            # Create JPG path
            jpg_dest = dest.with_suffix('.jpg')
            jpg_filename = filename.rsplit('.', 1)[0] + '.jpg'

            # Save as JPG
            img.save(jpg_dest, 'JPEG', quality=95)

            # Delete original HEIC file
            os.remove(dest)

            # Update variables to use JPG
            dest = jpg_dest
            filename = jpg_filename

            print(f"✅ Converted to JPG: {jpg_filename}", flush=True)
        except Exception as e:
            print(f"⚠️  HEIC conversion failed: {e}", flush=True)
            # Continue with original HEIC file if conversion fails

    # Upload to R2 storage and get public URL
    receipt_url = None
    if R2_ENABLED and upload_to_r2:
        try:
            success, result = upload_to_r2(dest)
            if success:
                receipt_url = result
                print(f"☁️  Uploaded to R2: {receipt_url}", flush=True)
            else:
                print(f"⚠️  R2 upload failed: {result}", flush=True)
        except Exception as e:
            print(f"⚠️  R2 upload error: {e}", flush=True)

    # Use update_row_by_index to properly update SQLite + DataFrame + CSV
    update_data = {"Receipt File": filename}
    if receipt_url:
        update_data["receipt_url"] = receipt_url
    update_row_by_index(idx, update_data, source="upload_receipt")

    return jsonify(safe_json({"ok": True, "filename": filename, "receipt_url": receipt_url}))


def gemini_ocr_extract(image_path: str | Path) -> dict:
    """
    Extract receipt data using Gemini Vision.
    Returns: dict with merchant, date, total, and confidence
    """
    try:
        img = Image.open(image_path)

        prompt = """Extract from this receipt image:
1. Merchant name (the business/company name)
2. Date (in YYYY-MM-DD format)
3. Total amount (final charge, as a number)

Return ONLY a JSON object with no markdown formatting:
{
  "merchant": "Business Name",
  "date": "YYYY-MM-DD",
  "total": 0.00,
  "confidence": 0-100
}

If you cannot extract a field with confidence, set it to null."""

        response_text = generate_content_with_fallback(prompt, img)
        if not response_text:
            raise Exception("Gemini returned empty response")
        response_text = response_text.strip()

        # Remove markdown formatting if present
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        result = json.loads(response_text)
        return {
            "merchant": result.get("merchant"),
            "date": result.get("date"),
            "total": float(result.get("total")) if result.get("total") else None,
            "confidence": int(result.get("confidence", 0))
        }

    except Exception as e:
        print(f"⚠️  Gemini OCR error: {e}", flush=True)
        return {
            "merchant": None,
            "date": None,
            "total": None,
            "confidence": 0,
            "error": str(e)
        }


# =============================================================================
# GEMINI AI CATEGORIZATION & NOTE GENERATION
# =============================================================================

# Valid expense categories for Brian Kaplan's businesses
EXPENSE_CATEGORIES = [
    "Meals & Entertainment",
    "Travel - Airfare",
    "Travel - Hotel",
    "Travel - Ground Transportation",
    "Travel - Car Rental",
    "Office Supplies",
    "Software & Subscriptions",
    "Professional Services",
    "Marketing & Advertising",
    "Equipment & Hardware",
    "Utilities & Communications",
    "Parking & Tolls",
    "Fuel & Gas",
    "Client Entertainment",
    "Training & Education",
    "Shipping & Postage",
    "Business Insurance",
    "Bank & Processing Fees",
    "Miscellaneous Business Expense"
]

# Business types for Brian's companies
BUSINESS_TYPES = [
    "Down Home",           # Music/Entertainment business
    "Music City Rodeo",    # Event business
    "Personal",            # Personal expenses
    "Compass RE",          # Real estate
    "1099 Contractor"      # Freelance work
]


def gemini_categorize_transaction(merchant: str, amount: float, date: str = "", category_hint: str = "", row: dict = None) -> dict:
    """
    Use Gemini AI to intelligently categorize a transaction.
    Now enhanced with merchant intelligence, contacts, and calendar context.

    Returns:
        {
            "category": "Meals & Entertainment",
            "business_type": "Down Home",
            "confidence": 85,
            "reasoning": "Restaurant expense likely for client meeting"
        }
    """
    # Build context from merchant intelligence
    merchant_context = ""
    attendees_context = ""
    calendar_context = ""

    # Create a row dict for context lookups if not provided
    if row is None:
        row = {
            "Chase Description": merchant,
            "merchant": merchant,
            "Chase Amount": amount,
            "amount": amount,
            "Chase Date": date,
            "transaction_date": date,
            "Chase Category": category_hint,
            "category": category_hint
        }

    # Get merchant hint from contacts_engine
    try:
        hint = merchant_hint_for_row(row)
        if hint:
            merchant_context = f"\n- Merchant Intelligence: {hint}"
    except Exception as e:
        print(f"⚠️ merchant_hint error: {e}")

    # Get normalized merchant from merchant_intelligence
    try:
        if merchant_intel:
            normalized = merchant_intel.normalize(merchant)
            if normalized and normalized != merchant.lower():
                merchant_context += f"\n- Normalized Merchant: {normalized}"
    except Exception as e:
        print(f"⚠️ merchant_intel error: {e}")

    # Get likely attendees (for meal categorization)
    try:
        attendees = guess_attendees_for_row(row)
        if attendees and len(attendees) > 1:
            attendees_context = f"\n- Likely Attendees: {', '.join(attendees)}"
    except Exception as e:
        print(f"⚠️ guess_attendees error: {e}")

    # Get calendar context for the date
    if date:
        try:
            from calendar_service import get_events_around_date, format_events_for_prompt
            events = get_events_around_date(date, days_before=1, days_after=1)
            if events:
                calendar_context = f"\n- Calendar Events Near Date: {format_events_for_prompt(events[:5])}"
        except Exception as e:
            pass  # Calendar not available, that's ok

    try:
        prompt = f"""You are an expense categorization expert for Brian Kaplan, a Nashville music industry executive.

TRANSACTION:
- Merchant: {merchant}
- Amount: ${amount:.2f}
- Date: {date}
- Existing Category Hint: {category_hint or "None"}{merchant_context}{attendees_context}{calendar_context}

BRIAN'S BUSINESSES:
- "Down Home" - Music/entertainment company (artist management, production, publishing)
- "Music City Rodeo" - Event production company (concerts, festivals)
- "Compass RE" - Real estate business
- "1099 Contractor" - Freelance consulting work
- "Personal" - Personal expenses

KNOWN MERCHANT INTELLIGENCE:
- Soho House / SH Nashville → Members club, always business meals with industry contacts
- Anthropic / Claude AI → AI tool subscription for business productivity
- Apple One / apple.com/bill → Business software/services subscription
- CLEAR → Airport security for business travel
- IMDbPro → Industry research subscription
- Expensify → Business expense software
- Cursor AI → Developer tools subscription

CATEGORY (pick one):
{chr(10).join(f'- {cat}' for cat in EXPENSE_CATEGORIES)}

BUSINESS TYPE (pick one):
{chr(10).join(f'- {bt}' for bt in BUSINESS_TYPES)}

CATEGORIZATION RULES:
1. Restaurants in Nashville → "Meals & Entertainment" + "Down Home" (client/artist meetings)
2. Airlines → "Travel - Airfare" (check calendar for destination context)
3. Hotels → "Travel - Hotel"
4. Uber/Lyft → "Travel - Ground Transportation"
5. Software/AI/SaaS subscriptions → "Software & Subscriptions" + "Down Home"
6. Parking near downtown Nashville → Probably "Down Home" meeting
7. If calendar shows MCR event near date → "Music City Rodeo"
8. Amazon under $100 → Likely "Office Supplies"
9. Amazon over $500 → Likely "Equipment & Hardware"

Return ONLY valid JSON:
{{"category": "...", "business_type": "...", "confidence": 0-100, "reasoning": "brief explanation"}}"""

        response_text = generate_content_with_fallback(prompt)
        if not response_text:
            raise Exception("Gemini returned empty response")

        response_text = response_text.strip()
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        result = json.loads(response_text)

        # Validate category and business_type
        if result.get("category") not in EXPENSE_CATEGORIES:
            result["category"] = "Miscellaneous Business Expense"
        if result.get("business_type") not in BUSINESS_TYPES:
            result["business_type"] = "Down Home"

        return result

    except Exception as e:
        print(f"⚠️  Gemini categorization error: {e}", flush=True)
        # Fallback to basic keyword categorization
        merchant_lower = (merchant or "").lower()

        # Basic keyword matching fallback
        if any(kw in merchant_lower for kw in ['restaurant', 'food', 'cafe', 'bar', 'grill', 'pizza', 'burger', 'taco', 'soho', 'house']):
            return {"category": "Meals & Entertainment", "business_type": "Down Home", "confidence": 60, "reasoning": "Keyword match: restaurant"}
        elif any(kw in merchant_lower for kw in ['airline', 'delta', 'american', 'united', 'southwest', 'flight']):
            return {"category": "Travel - Airfare", "business_type": "Down Home", "confidence": 70, "reasoning": "Keyword match: airline"}
        elif any(kw in merchant_lower for kw in ['hotel', 'marriott', 'hilton', 'hyatt', 'inn', 'lodge']):
            return {"category": "Travel - Hotel", "business_type": "Down Home", "confidence": 70, "reasoning": "Keyword match: hotel"}
        elif any(kw in merchant_lower for kw in ['uber', 'lyft', 'taxi', 'cab']):
            return {"category": "Travel - Ground Transportation", "business_type": "Down Home", "confidence": 75, "reasoning": "Keyword match: rideshare"}
        elif any(kw in merchant_lower for kw in ['gas', 'shell', 'exxon', 'chevron', 'fuel', 'bp ']):
            return {"category": "Fuel & Gas", "business_type": "Down Home", "confidence": 70, "reasoning": "Keyword match: gas station"}
        elif any(kw in merchant_lower for kw in ['parking', 'park', 'pmc']):
            return {"category": "Parking & Tolls", "business_type": "Down Home", "confidence": 65, "reasoning": "Keyword match: parking"}
        elif any(kw in merchant_lower for kw in ['adobe', 'spotify', 'apple', 'microsoft', 'google', 'dropbox', 'subscription', 'anthropic', 'claude', 'cursor', 'openai']):
            return {"category": "Software & Subscriptions", "business_type": "Down Home", "confidence": 70, "reasoning": "Keyword match: subscription"}
        elif any(kw in merchant_lower for kw in ['office', 'staples', 'supplies']):
            return {"category": "Office Supplies", "business_type": "Down Home", "confidence": 65, "reasoning": "Keyword match: office supplies"}
        else:
            return {"category": "Miscellaneous Business Expense", "business_type": "Down Home", "confidence": 40, "reasoning": "No specific match found"}


def gemini_generate_ai_note(merchant: str, amount: float, date: str = "", category: str = "", business_type: str = "", row: dict = None) -> dict:
    """
    Use Smart Notes Engine (with Calendar, iMessage, and Contacts context) to generate
    an intelligent expense note. Falls back to Gemini-only if smart notes unavailable.

    Returns:
        {
            "note": "Client dinner meeting at upscale steakhouse to discuss artist contract negotiations",
            "confidence": 85,
            "attendees": [...],
            "calendar_events": [...],
            "data_sources": [...]
        }
    """
    # Try Smart Notes Engine first (has Calendar + iMessage + Contacts integration)
    if SMART_NOTES_AVAILABLE and generate_smart_note:
        try:
            result = generate_smart_note(
                merchant=merchant,
                amount=float(amount) if amount else 0.0,
                date=date or "",
                category=category or "",
                business_type=business_type or ""
            )
            # Map confidence to numeric value
            confidence_map = {'high': 90, 'medium': 70, 'low': 50}
            return {
                "note": result.get('note', f"Business expense at {merchant}"),
                "confidence": confidence_map.get(result.get('confidence', 'low'), 50),
                "attendees": result.get('attendees', []),
                "calendar_events": result.get('calendar_events', []),
                "data_sources": result.get('data_sources', [])
            }
        except Exception as e:
            print(f"⚠️  Smart notes error (falling back to Gemini): {e}", flush=True)

    # Fallback: Use Gemini with basic context (no iMessage, simpler calendar)
    merchant_context = ""
    attendees_context = ""
    calendar_context = ""

    # Create a row dict for context lookups if not provided
    if row is None:
        row = {
            "Chase Description": merchant,
            "merchant": merchant,
            "Chase Amount": amount,
            "amount": amount,
            "Chase Date": date,
            "transaction_date": date,
            "Chase Category": category,
            "category": category,
            "Business Type": business_type
        }

    # Get merchant hint from contacts_engine
    try:
        hint = merchant_hint_for_row(row)
        if hint:
            merchant_context = f"\n- Merchant Intel: {hint}"
    except Exception as e:
        pass

    # Get normalized merchant
    try:
        if merchant_intel:
            normalized = merchant_intel.normalize(merchant)
            if normalized and normalized != merchant.lower():
                merchant_context += f"\n- Normalized: {normalized}"
    except Exception as e:
        pass

    # Get likely attendees for meals
    try:
        attendees = guess_attendees_for_row(row)
        if attendees:
            attendees_context = f"\n- Likely Attendees: {', '.join(attendees)}"
    except Exception as e:
        pass

    # Get calendar context
    if date:
        try:
            from calendar_service import get_events_around_date, format_events_for_prompt
            events = get_events_around_date(date, days_before=1, days_after=1)
            if events:
                calendar_context = f"\n- Calendar Events: {format_events_for_prompt(events[:5])}"
        except Exception as e:
            pass

    try:
        prompt = f"""You are Brian Kaplan's executive assistant writing expense notes for IRS tax documentation.
Brian is a Nashville music industry executive running Down Home (artist management/publishing) and Music City Rodeo (event production).

TRANSACTION:
- Merchant: {merchant}
- Amount: ${amount:.2f}
- Date: {date}
- Category: {category or "Unknown"}
- Business: {business_type or "Down Home"}{merchant_context}{attendees_context}{calendar_context}

BRIAN'S KEY CONTACTS (use when relevant):
- Down Home Team: Jason Ross (GM), Tim Staples, Joel Bergvall, Kevin Sabbe, Andrew Cohen
- MCR Team: Patrick Humes, Barry Stephenson
- Industry Execs: Scott Siman, Cindy Mabe, Ken Robold, Ben Kline
- Artists: Morgan Wade, Jelly Roll, Wynonna, and other roster artists

KNOWN VENUES:
- Soho House / SH Nashville = Members-only club for industry networking and artist meetings
- 12 South Taproom = Nashville restaurant for team lunches
- Corner Pub = Casual industry meeting spot

CRITICAL REQUIREMENTS - Your note MUST:
1. Be SPECIFIC enough to satisfy an IRS auditor asking "What was this for?"
2. Name WHO was there when known (from calendar/attendees context)
3. State WHAT was discussed or the PURPOSE (artist deals, release strategy, contracts, etc.)
4. For travel: specify DESTINATION and REASON (event name, meeting purpose)
5. For subscriptions: explain SPECIFIC business use (not just "for business")
6. NEVER use vague phrases like "business expense", "client meeting", or "various business purposes"

EXCELLENT NOTES (be this specific):
- "Artist development dinner at Soho House with Jason Ross - discussed Morgan Wade European tour logistics and Q1 release schedule"
- "Delta flight to Los Angeles for Grammy week: artist showcase at The Troubadour and UMG label meetings"
- "Claude AI monthly subscription - used for contract draft review, press release writing, and tour routing analysis"
- "Uber to BNA airport for Las Vegas NFR production meetings with venue coordinators"
- "Team lunch at 12 South Taproom with Joel Bergvall and Kevin Sabbe - Q4 budget review and artist roster planning"

BAD NOTES (NEVER write these - too vague):
- "Business expense" / "Business meal"
- "Client meeting" / "Meeting with client"
- "Software subscription" / "Monthly subscription"
- "Travel" / "Transportation"
- "Meal with team" / "Team dinner"

Return ONLY valid JSON:
{{"note": "your specific, IRS-ready expense note here", "confidence": 0-100}}"""

        response_text = generate_content_with_fallback(prompt)
        if not response_text:
            raise Exception("Gemini returned empty response")

        response_text = response_text.strip()
        response_text = response_text.replace('```json', '').replace('```', '').strip()

        result = json.loads(response_text)
        return result

    except Exception as e:
        print(f"⚠️  Gemini AI note error: {e}", flush=True)
        # Fallback to basic note
        return {
            "note": f"Business expense at {merchant} - ${amount:.2f}",
            "confidence": 30
        }


def find_matching_transaction(receipt_merchant: str, receipt_date: str, receipt_total: float) -> dict | None:
    """
    Find the best matching transaction for a receipt.
    Uses similar scoring logic to find_best_receipt but reversed.
    """
    ensure_df()
    global df

    if df.empty:
        return None

    # Normalize receipt data
    receipt_merchant_norm = normalize_merchant_name(receipt_merchant or "")
    receipt_date_parsed = parse_date_fuzzy(receipt_date)
    receipt_total = receipt_total or 0.0

    if not receipt_merchant_norm and receipt_total == 0:
        return None

    best = None
    best_score = 0.0

    for _, row in df.iterrows():
        # Skip if already has receipt
        if row.get("Receipt File") or row.get("receipt_file"):
            continue

        # Get transaction data
        tx_amount = parse_amount_str(
            row.get("Chase Amount") or row.get("amount") or row.get("Amount")
        )
        tx_desc_raw = (
            row.get("Chase Description") or row.get("merchant") or row.get("Merchant") or ""
        )
        tx_desc_norm = normalize_merchant_name(tx_desc_raw)
        tx_date_raw = (
            row.get("Chase Date") or row.get("transaction_date") or row.get("Date") or ""
        )
        tx_date = parse_date_fuzzy(tx_date_raw)

        # Calculate scores using same logic as find_best_receipt

        # Amount score
        amount_score = 0.0
        if tx_amount != 0 and receipt_total != 0:
            diff = abs(tx_amount - receipt_total)
            scale = max(1.0, 0.10 * abs(tx_amount))
            amount_score = max(0.0, 1.0 - (diff / scale))

        # Merchant score
        merch_score = 0.0
        if tx_desc_norm and receipt_merchant_norm:
            merch_score = SequenceMatcher(None, tx_desc_norm, receipt_merchant_norm).ratio()

        # Date score
        date_score = 0.0
        if tx_date and receipt_date_parsed:
            delta_days = abs((tx_date - receipt_date_parsed).days)
            if delta_days == 0:
                date_score = 1.0
            elif delta_days <= 1:
                date_score = 0.9
            elif delta_days <= 3:
                date_score = 0.8
            elif delta_days <= 7:
                date_score = 0.7
            elif delta_days <= 14:
                date_score = 0.6
            elif delta_days <= 30:
                date_score = 0.5
            elif delta_days <= 60:
                date_score = 0.3
            elif delta_days <= 90:
                date_score = 0.1
        else:
            date_score = 0.3

        # Skip if both amount and merchant are bad
        amount_is_good = amount_score > 0.80
        amount_is_perfect = amount_score > 0.90
        merchant_is_terrible = merch_score < 0.15

        if amount_score < 0.50 and merchant_is_terrible:
            continue

        # Calculate weighted score
        if amount_is_perfect:
            score = 0.8 * amount_score + 0.15 * merch_score + 0.05 * date_score
        elif amount_is_good:
            score = 0.7 * amount_score + 0.25 * merch_score + 0.05 * date_score
        else:
            score = 0.5 * amount_score + 0.35 * merch_score + 0.15 * date_score

        if score > best_score:
            best_score = score
            best = {
                "row": row.to_dict(),
                "score": round(float(score), 3),
                "amount_score": round(float(amount_score), 3),
                "merchant_score": round(float(merch_score), 3),
                "date_score": round(float(date_score), 3),
            }

    # Require confidence >= 50% (same as find_best_receipt)
    if best and best["score"] >= 0.50:
        return best
    return None


@app.route("/upload_receipt_auto", methods=["POST"])
def upload_receipt_auto():
    """
    Smart receipt upload:
    1. Accept file without _index
    2. OCR with Gemini to extract merchant, date, amount
    3. Auto-match to best transaction
    4. Auto-attach if confidence >= 70%

    Returns:
    {
      "ok": bool,
      "matched": bool,
      "ocr_data": {...},
      "transaction": {...},
      "confidence": int,
      "filename": str (if matched),
      "message": str
    }
    """
    ensure_df()
    global df

    file = request.files.get("file")
    if not file:
        abort(400, "Missing file")

    # Save to temp location first
    RECEIPT_DIR.mkdir(exist_ok=True)

    original_name = file.filename or "receipt.jpg"
    original_name = os.path.basename(original_name)
    stem, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".jpg"

    # Save with timestamp to avoid conflicts
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"temp_{timestamp}_{original_name}"
    temp_path = RECEIPT_DIR / temp_filename
    file.save(temp_path)

    try:
        # Step 1: OCR with Gemini
        print(f"🔍 OCR processing: {temp_filename}", flush=True)
        ocr_data = gemini_ocr_extract(temp_path)

        if ocr_data.get("error"):
            temp_path.unlink(missing_ok=True)
            return jsonify(safe_json({
                "ok": False,
                "matched": False,
                "error": f"OCR failed: {ocr_data['error']}",
                "message": "Could not read receipt image"
            }))

        print(f"   Merchant: {ocr_data.get('merchant')}", flush=True)
        print(f"   Date: {ocr_data.get('date')}", flush=True)
        print(f"   Total: ${ocr_data.get('total')}", flush=True)
        print(f"   Confidence: {ocr_data.get('confidence')}%", flush=True)

        # Step 2: Find matching transaction
        match = find_matching_transaction(
            ocr_data.get("merchant"),
            ocr_data.get("date"),
            ocr_data.get("total")
        )

        if not match:
            temp_path.unlink(missing_ok=True)
            return jsonify(safe_json({
                "ok": True,
                "matched": False,
                "ocr_data": ocr_data,
                "message": "No matching transaction found. Try uploading directly to a transaction."
            }))

        # Step 3: Auto-attach if confidence >= 70%
        confidence = int(match["score"] * 100)

        if confidence >= 70:
            # Rename file properly
            idx = match["row"]["_index"]
            final_filename = f"receipt_{idx}_{timestamp}{ext}"
            final_path = RECEIPT_DIR / final_filename

            # Remove temp prefix
            temp_path.rename(final_path)

            # Upload to R2 storage
            receipt_url = None
            if R2_ENABLED and upload_to_r2:
                try:
                    success, result = upload_to_r2(final_path)
                    if success:
                        receipt_url = result
                        print(f"☁️  Uploaded to R2: {receipt_url}", flush=True)
                    else:
                        print(f"⚠️  R2 upload failed: {result}", flush=True)
                except Exception as e:
                    print(f"⚠️  R2 upload error: {e}", flush=True)

            # Update transaction
            update_data = {
                "Receipt File": final_filename,
                "review_status": "good",
                "ai_confidence": confidence,
                "ai_receipt_merchant": ocr_data.get("merchant"),
                "ai_receipt_total": ocr_data.get("total"),
                "ai_receipt_date": ocr_data.get("date")
            }
            if receipt_url:
                update_data["receipt_url"] = receipt_url
            update_row_by_index(idx, update_data, source="smart_upload")

            print(f"✅ Auto-matched to transaction {idx} ({confidence}%)", flush=True)

            return jsonify(safe_json({
                "ok": True,
                "matched": True,
                "auto_attached": True,
                "ocr_data": ocr_data,
                "transaction": match["row"],
                "confidence": confidence,
                "filename": final_filename,
                "message": f"Auto-matched to {match['row'].get('Chase Description')} (${match['row'].get('Chase Amount')}) with {confidence}% confidence"
            }))
        else:
            # Confidence too low for auto-attach, but KEEP the file for manual attachment
            # Rename to a "pending" filename so user can attach manually
            idx = match["row"]["_index"]
            pending_filename = f"pending_{idx}_{timestamp}{ext}"
            pending_path = RECEIPT_DIR / pending_filename
            temp_path.rename(pending_path)

            # Upload to R2 even for pending receipts
            receipt_url = None
            if R2_ENABLED and upload_to_r2:
                try:
                    success, result = upload_to_r2(pending_path)
                    if success:
                        receipt_url = result
                        print(f"☁️  Uploaded pending to R2: {receipt_url}", flush=True)
                except Exception as e:
                    print(f"⚠️  R2 upload error: {e}", flush=True)

            print(f"⚠️  Low confidence match ({confidence}%), saved as pending: {pending_filename}", flush=True)

            return jsonify(safe_json({
                "ok": True,
                "matched": True,
                "auto_attached": False,
                "ocr_data": ocr_data,
                "transaction": match["row"],
                "confidence": confidence,
                "filename": pending_filename,
                "receipt_url": receipt_url,
                "message": f"Found possible match ({confidence}% confidence). Receipt saved - verify and attach manually."
            }))

    except Exception as e:
        temp_path.unlink(missing_ok=True)
        print(f"❌ Smart upload error: {e}", flush=True)
        return jsonify(safe_json({
            "ok": False,
            "matched": False,
            "error": str(e),
            "message": "Upload failed"
        }))


@app.route("/upload_receipt_new", methods=["POST"])
def upload_receipt_new():
    """
    Upload a receipt image, OCR with Gemini, and CREATE A NEW TRANSACTION.

    This is for when you have a receipt but no matching transaction exists.
    Gemini will extract merchant, date, and amount to create the transaction.

    Returns:
    {
      "ok": bool,
      "transaction": {...},
      "ocr_data": {...},
      "filename": str,
      "message": str
    }
    """
    ensure_df()
    global df

    file = request.files.get("file")
    if not file:
        abort(400, "Missing file")

    # Get optional business type override
    data = request.form or {}
    business_type = data.get("business_type", "")

    # Save to temp location first
    RECEIPT_DIR.mkdir(exist_ok=True)

    original_name = file.filename or "receipt.jpg"
    original_name = os.path.basename(original_name)
    stem, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".jpg"

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    temp_filename = f"temp_{timestamp}_{original_name}"
    temp_path = RECEIPT_DIR / temp_filename
    file.save(temp_path)

    try:
        # Step 1: OCR with Gemini
        print(f"🔍 OCR processing for new transaction: {temp_filename}", flush=True)
        ocr_data = gemini_ocr_extract(temp_path)

        if ocr_data.get("error"):
            temp_path.unlink(missing_ok=True)
            return jsonify(safe_json({
                "ok": False,
                "error": f"OCR failed: {ocr_data['error']}",
                "message": "Could not read receipt image. Please try again or enter details manually."
            }))

        merchant = ocr_data.get("merchant") or "Unknown Merchant"
        receipt_date = ocr_data.get("date") or datetime.now().strftime("%Y-%m-%d")
        total = ocr_data.get("total") or 0.0
        confidence = ocr_data.get("confidence", 0)

        print(f"   Merchant: {merchant}", flush=True)
        print(f"   Date: {receipt_date}", flush=True)
        print(f"   Total: ${total}", flush=True)
        print(f"   Confidence: {confidence}%", flush=True)

        # Step 2: Create new transaction in database
        if USE_DATABASE and db:
            conn, db_type = get_db_connection()

            # Get next _index
            cursor = db_execute(conn, db_type, 'SELECT COALESCE(MAX(_index), 0) + 1 FROM transactions')
            row = cursor.fetchone()
            # Handle dict (MySQL DictCursor) vs tuple (SQLite)
            next_index = list(row.values())[0] if isinstance(row, dict) else row[0]

            # Rename receipt file with proper naming
            final_filename = f"receipt_{next_index}_{timestamp}{ext}"
            final_path = RECEIPT_DIR / final_filename
            temp_path.rename(final_path)

            # Upload to R2 storage
            receipt_url = None
            if R2_ENABLED and upload_to_r2:
                try:
                    success, result = upload_to_r2(final_path)
                    if success:
                        receipt_url = result
                        print(f"☁️  Uploaded to R2: {receipt_url}", flush=True)
                    else:
                        print(f"⚠️  R2 upload failed: {result}", flush=True)
                except Exception as e:
                    print(f"⚠️  R2 upload error: {e}", flush=True)

            # Determine business type if not provided
            if not business_type:
                # Try to infer from merchant name
                merchant_lower = merchant.lower()
                if any(kw in merchant_lower for kw in ['restaurant', 'cafe', 'coffee', 'food', 'grill', 'pizza', 'burger']):
                    business_type = 'Meals & Entertainment'
                elif any(kw in merchant_lower for kw in ['hotel', 'inn', 'suites', 'marriott', 'hilton']):
                    business_type = 'Travel'
                elif any(kw in merchant_lower for kw in ['uber', 'lyft', 'taxi', 'parking']):
                    business_type = 'Travel'
                elif any(kw in merchant_lower for kw in ['office', 'staples', 'depot']):
                    business_type = 'Office Supplies'
                else:
                    business_type = 'Business Expense'

            # Insert new transaction
            cursor = db_execute(conn, db_type, '''
                INSERT INTO transactions (
                    _index, chase_description, chase_amount, chase_date,
                    business_type, review_status, notes,
                    receipt_file, source, ai_confidence,
                    ai_receipt_merchant, ai_receipt_total, ai_receipt_date
                ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, 'manual_upload', ?, ?, ?, ?)
            ''', (
                next_index, merchant, total, receipt_date,
                business_type, f"Created from uploaded receipt (Gemini OCR {confidence}%)",
                final_filename, confidence,
                merchant, total, receipt_date
            ))

            conn.commit()
            return_db_connection(conn)

            # Update in-memory DataFrame
            new_row = {
                '_index': next_index,
                'Chase Description': merchant,
                'Chase Amount': total,
                'Chase Date': receipt_date,
                'Business Type': business_type,
                'Review Status': 'accepted',
                'notes': f"Created from uploaded receipt (Gemini OCR {confidence}%)",
                'Receipt File': final_filename,
                'receipt_url': receipt_url or '',
                'source': 'manual_upload',
                'ai_confidence': confidence,
                'ai_receipt_merchant': merchant,
                'ai_receipt_total': total,
                'ai_receipt_date': receipt_date
            }

            # Add missing columns with empty values
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = ''

            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)

            print(f"✅ Created new transaction #{next_index} from receipt upload", flush=True)

            return jsonify(safe_json({
                "ok": True,
                "transaction": {
                    "_index": next_index,
                    "chase_description": merchant,
                    "chase_amount": total,
                    "chase_date": receipt_date,
                    "business_type": business_type,
                    "review_status": "accepted"
                },
                "ocr_data": ocr_data,
                "filename": final_filename,
                "message": f"Created transaction: {merchant} - ${total} on {receipt_date}"
            }))
        else:
            temp_path.unlink(missing_ok=True)
            return jsonify(safe_json({
                "ok": False,
                "error": "Database not available",
                "message": "SQLite database is required for this feature"
            }))

    except Exception as e:
        temp_path.unlink(missing_ok=True)
        print(f"❌ Upload new transaction error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify(safe_json({
            "ok": False,
            "error": str(e),
            "message": "Failed to create transaction from receipt"
        }))


@app.route("/detach_receipt", methods=["POST"])
def detach_receipt():
    """
    Body: { "_index": int } or { "transaction_id": int }

    Detaches receipt from transaction by clearing receipt fields.
    """
    data = request.get_json(force=True) or {}

    # Support both _index (legacy) and transaction_id (new)
    idx = data.get("_index") or data.get("transaction_id")
    if idx is None:
        return jsonify({'ok': False, 'error': 'Missing _index or transaction_id'}), 400

    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return jsonify({'ok': False, 'error': f'Invalid _index/transaction_id: {idx}'}), 400

    # ===== MySQL Mode (Primary) =====
    if USE_DATABASE and db:
        conn = None
        try:
            conn, db_type = get_db_connection()

            # Get transaction by _index first, then by id
            cursor = db_execute(conn, db_type,
                'SELECT id, _index, receipt_file, receipt_url, r2_url, chase_description FROM transactions WHERE _index = ?',
                (idx,))
            row = cursor.fetchone()

            if not row:
                cursor = db_execute(conn, db_type,
                    'SELECT id, _index, receipt_file, receipt_url, r2_url, chase_description FROM transactions WHERE id = ?',
                    (idx,))
                row = cursor.fetchone()

            if not row:
                return_db_connection(conn)
                return jsonify({'ok': False, 'error': f'Transaction {idx} not found'}), 404

            row_dict = dict(row)
            actual_index = row_dict.get('_index', idx)
            filename = row_dict.get('receipt_file') or ''
            receipt_url = row_dict.get('receipt_url') or ''
            r2_url = row_dict.get('r2_url') or ''
            transaction_desc = row_dict.get('chase_description') or ''

            if not filename and not receipt_url and not r2_url:
                return_db_connection(conn)
                # Return success - nothing to detach but that's fine
                return jsonify({'ok': True, 'message': f'No receipt attached to transaction #{idx}', 'already_empty': True})

            # AUDIT LOG: Save what we're about to detach so it can be restored
            detached_url = r2_url or receipt_url or filename
            ocr_status = row_dict.get('ocr_verification_status') or ''
            try:
                db_execute(conn, db_type, '''
                    INSERT INTO receipt_audit_log
                    (receipt_type, receipt_id, action, field_changed, old_value, new_value, changed_by, changed_at)
                    VALUES ('transaction', ?, 'detach', 'r2_url', ?, '', 'user', NOW())
                ''', (actual_index, detached_url))
                if ocr_status:
                    db_execute(conn, db_type, '''
                        INSERT INTO receipt_audit_log
                        (receipt_type, receipt_id, action, field_changed, old_value, new_value, changed_by, changed_at)
                        VALUES ('transaction', ?, 'detach', 'ocr_verification_status', ?, '', 'user', NOW())
                    ''', (actual_index, ocr_status))
            except Exception as audit_err:
                print(f"⚠️ Audit log failed (non-fatal): {audit_err}", flush=True)

            # Clear receipt from transaction - including ALL OCR verification data
            db_execute(conn, db_type, '''
                UPDATE transactions
                SET receipt_file = '', receipt_url = '', review_status = '', r2_url = '',
                    ai_confidence = NULL, ai_receipt_merchant = '', ai_receipt_total = NULL, ai_receipt_date = NULL,
                    receipt_validation_status = 'missing', receipt_validated = 0, receipt_validation_note = 'Receipt detached',
                    ocr_merchant = NULL, ocr_amount = NULL, ocr_date = NULL, ocr_subtotal = NULL, ocr_tax = NULL, ocr_tip = NULL,
                    ocr_receipt_number = NULL, ocr_payment_method = NULL, ocr_line_items = NULL,
                    ocr_confidence = NULL, ocr_method = NULL, ocr_extracted_at = NULL,
                    ocr_verified = 0, ocr_verification_status = NULL
                WHERE _index = ?
            ''', (actual_index,))

            conn.commit()
            return_db_connection(conn)

            print(f"✅ DETACHED: Receipt from transaction #{idx} ({transaction_desc})", flush=True)

            return jsonify({
                'ok': True,
                'message': f'Receipt detached from transaction #{idx}',
                'detached_receipt': filename or receipt_url or r2_url
            })

        except Exception as e:
            if conn:
                return_db_connection(conn, discard=True)
            print(f"❌ Detach error: {e}", flush=True)
            import traceback
            traceback.print_exc()
            return jsonify({'ok': False, 'error': str(e)}), 500

    # ===== CSV/DataFrame Mode (Legacy fallback) =====
    ensure_df()
    global df

    mask = df["_index"] == idx
    if not mask.any():
        abort(404, f"_index {idx} not found")

    row = df.loc[mask].iloc[0]
    transaction_desc = row.get('Chase Description', '')
    transaction_amount = row.get('Chase Amount', 0)
    transaction_date = row.get('Chase Date', '')

    filename = None
    if "Receipt File" in row and isinstance(row["Receipt File"], str) and row["Receipt File"]:
        filename = row["Receipt File"]
    elif "receipt_file" in row and isinstance(row["receipt_file"], str) and row["receipt_file"]:
        filename = row["receipt_file"]

    if filename:
        TRASH_DIR.mkdir(exist_ok=True)
        src = RECEIPT_DIR / filename
        dst = TRASH_DIR / filename
        if src.exists():
            try:
                src.rename(dst)
                print(f"🗑 Moved {src} -> {dst}", flush=True)
            except OSError as e:
                print(f"⚠️ Could not move {src} -> {dst}: {e}", flush=True)

    # Clear receipt file columns in dataframe
    for col in ("Receipt File", "receipt_file"):
        if col in df.columns:
            df.loc[mask, col] = ""

    if "Review Status" in df.columns:
        df.loc[mask, "Review Status"] = ""

    for col in ("AI Confidence", "ai_receipt_merchant", "ai_receipt_total", "ai_receipt_date"):
        if col in df.columns:
            df.loc[mask, col] = ""

    save_csv()
    return jsonify(safe_json({"ok": True}))


@app.route("/add_manual_expense", methods=["POST"])
def add_manual_expense():
    """
    Add a manual expense entry.
    Body: {
      "date": "YYYY-MM-DD",
      "merchant": "Merchant Name",
      "amount": 123.45,
      "business_type": "Down Home",
      "category": "Optional Category",
      "notes": "Optional notes",
      "receipt_file": "Optional filename from OCR",
      "receipt_url": "Optional R2 URL from OCR"
    }
    """
    ensure_df()
    global df

    data = request.get_json(force=True) or {}

    # Validate required fields
    if not all(k in data for k in ("date", "merchant", "amount", "business_type")):
        abort(400, "Missing required fields (date, merchant, amount, business_type)")

    # Generate new _index
    max_index = df["_index"].max() if len(df) > 0 else 0
    new_index = int(max_index) + 1

    # Get receipt file and URL if provided
    receipt_file = data.get("receipt_file", "")
    receipt_url = data.get("receipt_url", "")

    # Determine if we have a receipt (file or URL)
    has_receipt = bool(receipt_file or receipt_url)

    # Create new expense row
    new_expense = {
        "_index": new_index,
        "Chase Date": data["date"],
        "Chase Description": data["merchant"],
        "Chase Amount": float(data["amount"]),
        "Chase Category": "",
        "Chase Type": "Purchase",
        "Receipt File": receipt_file,
        "receipt_url": receipt_url,
        "Business Type": data["business_type"],
        "Notes": data.get("notes", ""),
        "AI Note": "",
        "AI Confidence": 0,
        "ai_receipt_merchant": data["merchant"] if has_receipt else "",
        "ai_receipt_date": data["date"] if has_receipt else "",
        "ai_receipt_total": str(data["amount"]) if has_receipt else "",
        "Review Status": "good" if has_receipt else "",
        "Category": data.get("category", ""),
        "Report ID": "",
        "Source": "Manual Entry"
    }

    # Database mode (MySQL or SQLite)
    if USE_DATABASE and db:
        try:
            # Build INSERT statement - handle both MySQL and SQLite
            columns = [
                "_index", "chase_date", "chase_description", "chase_amount",
                "chase_category", "chase_type", "receipt_file", "receipt_url", "business_type",
                "notes", "ai_note", "ai_confidence", "ai_receipt_merchant",
                "ai_receipt_date", "ai_receipt_total", "review_status",
                "category", "report_id", "source"
            ]

            values = (
                new_index,
                data["date"],
                data["merchant"],
                float(data["amount"]),
                "",
                "Purchase",
                receipt_file,
                receipt_url,  # R2 cloud URL
                data["business_type"],
                data.get("notes", ""),
                "",
                0,
                data["merchant"] if has_receipt else "",  # ai_receipt_merchant
                data["date"] if has_receipt else "",  # ai_receipt_date
                str(data["amount"]) if has_receipt else "",  # ai_receipt_total
                "good" if has_receipt else "",  # review_status
                data.get("category", ""),
                "",
                "Manual Entry"
            )

            col_names = ", ".join(columns)

            # Use MySQL-specific path if available
            if hasattr(db, 'use_mysql') and db.use_mysql:
                placeholders = ", ".join(["%s"] * len(columns))
                sql = f"INSERT INTO transactions ({col_names}) VALUES ({placeholders})"
                conn = db.get_connection()
                cursor = conn.cursor()
                cursor.execute(sql, values)
                conn.commit()
                cursor.close()
                return_db_connection(conn)
            else:
                # SQLite path
                placeholders = ", ".join(["?"] * len(columns))
                sql = f"INSERT INTO transactions ({col_names}) VALUES ({placeholders})"
                conn = db.conn
                cursor = conn.cursor()
                cursor.execute(sql, values)
                conn.commit()

            # Reload df to stay in sync
            df = db.get_all_transactions()

            print(f"✅ Manual expense added: {new_index} - {data['merchant']} ${data['amount']}", flush=True)

            return jsonify(safe_json({"ok": True, "expense": new_expense}))

        except Exception as e:
            print(f"⚠️  Database insert failed: {e}, falling back to CSV")
            # Fall through to CSV mode

    # CSV mode fallback
    df = pd.concat([df, pd.DataFrame([new_expense])], ignore_index=True)
    save_csv()

    print(f"✅ Manual expense added: {new_index} - {data['merchant']} ${data['amount']}", flush=True)

    return jsonify(safe_json({"ok": True, "expense": new_expense}))


@app.route("/api/bulk_import", methods=["POST"])
def bulk_import_transactions():
    """
    Bulk import transactions from JSON array.
    Used to sync local SQLite to Railway MySQL.
    Requires admin_key authentication.
    Body: {"transactions": [...], "admin_key": "..."}
    """
    global df

    data = request.get_json(force=True) or {}

    # Verify admin key
    admin_key = data.get("admin_key") or request.args.get("admin_key")
    expected_key = os.getenv("ADMIN_KEY", "bkaplan2025")
    if admin_key != expected_key:
        return jsonify({"error": "Unauthorized"}), 401

    transactions = data.get("transactions", [])
    if not transactions:
        return jsonify({"error": "No transactions provided"}), 400

    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    imported = 0
    updated = 0
    failed = 0

    columns = [
        "_index", "chase_date", "chase_description", "chase_amount",
        "chase_category", "chase_type", "receipt_file", "receipt_url",
        "business_type", "notes", "ai_note", "ai_confidence",
        "ai_receipt_merchant", "ai_receipt_date", "ai_receipt_total",
        "review_status", "category", "report_id", "source",
        "mi_merchant", "mi_category", "mi_description", "mi_confidence",
        "mi_is_subscription", "mi_subscription_name", "mi_processed_at",
        "is_refund", "already_submitted", "deleted", "deleted_by_user"
    ]

    # Column name mapping from user-facing to database columns
    col_map = {
        "_index": "_index",
        "Chase Date": "chase_date",
        "Chase Description": "chase_description",
        "Chase Amount": "chase_amount",
        "Chase Category": "chase_category",
        "Chase Type": "chase_type",
        "Receipt File": "receipt_file",
        "receipt_url": "receipt_url",
        "Business Type": "business_type",
        "Notes": "notes",
        "AI Note": "ai_note",
        "AI Confidence": "ai_confidence",
        "ai_receipt_merchant": "ai_receipt_merchant",
        "ai_receipt_date": "ai_receipt_date",
        "ai_receipt_total": "ai_receipt_total",
        "Review Status": "review_status",
        "Category": "category",
        "Report ID": "report_id",
        "Source": "source",
        "MI Merchant": "mi_merchant",
        "MI Category": "mi_category",
        "MI Description": "mi_description",
        "MI Confidence": "mi_confidence",
        "MI Is Subscription": "mi_is_subscription",
        "MI Subscription Name": "mi_subscription_name",
        "MI Processed At": "mi_processed_at",
        "Is Refund": "is_refund",
        "Already Submitted": "already_submitted",
        "deleted": "deleted",
        "deleted_by_user": "deleted_by_user"
    }

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        for tx in transactions:
            try:
                # Map column names
                db_row = {}
                for user_col, db_col in col_map.items():
                    if user_col in tx:
                        val = tx[user_col]
                        # Convert empty strings to None for date fields
                        if db_col in ["chase_date", "ai_receipt_date", "mi_processed_at"]:
                            if val == "" or val is None:
                                val = None
                        db_row[db_col] = val

                if "_index" not in db_row:
                    failed += 1
                    continue

                # Build UPSERT statement
                present_cols = [c for c in columns if c in db_row]
                present_vals = [db_row[c] for c in present_cols]

                placeholders = ", ".join(["%s"] * len(present_cols))
                col_names = ", ".join(present_cols)

                # Update clause for ON DUPLICATE KEY
                update_parts = [f"{c} = VALUES({c})" for c in present_cols if c != "_index"]
                update_clause = ", ".join(update_parts)

                sql = f"""
                    INSERT INTO transactions ({col_names})
                    VALUES ({placeholders})
                    ON DUPLICATE KEY UPDATE {update_clause}
                """

                cursor.execute(sql, present_vals)

                if cursor.rowcount == 1:
                    imported += 1
                elif cursor.rowcount == 2:  # MySQL returns 2 for updated row
                    updated += 1

            except Exception as e:
                failed += 1
                if failed <= 3:
                    print(f"   Import error: {e}")

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        # Reload DataFrame
        df = db.get_all_transactions()

        return jsonify({
            "ok": True,
            "imported": imported,
            "updated": updated,
            "failed": failed,
            "total_now": len(df)
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


# =============================================================================
# REPORTS ENDPOINTS
# =============================================================================

@app.route("/reports/preview", methods=["POST"])
def reports_preview():
    """
    Preview expenses that match report filters.
    Body: {
      "business_type": "Down Home",
      "date_from": "2024-01-01",
      "date_to": "2024-12-31"
    }
    """
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    data = request.get_json(force=True) or {}

    business_type = data.get("business_type")
    date_from = data.get("date_from")
    date_to = data.get("date_to")

    try:
        expenses = db.get_reportable_expenses(
            business_type=business_type,
            date_from=date_from,
            date_to=date_to
        )

        # Convert to UI-friendly format
        converted = []
        for exp in expenses:
            converted.append({
                "_index": exp["_index"],
                "Chase Date": exp["chase_date"],
                "Chase Description": exp["chase_description"],
                "Chase Amount": exp["chase_amount"],
                "Chase Category": exp["chase_category"],
                "Chase Type": exp["chase_type"],
                "Receipt File": exp["receipt_file"],
                "Business Type": exp["business_type"],
                "Notes": exp["notes"],
                "AI Note": exp["ai_note"],
                "AI Confidence": exp["ai_confidence"],
                "Review Status": exp["review_status"],
                "Category": exp["category"],
                "Report ID": exp["report_id"],
                "Source": exp["source"]
            })

        total_amount = sum(abs(float(e.get("Chase Amount", 0) or 0)) for e in converted)

        return jsonify(safe_json({
            "ok": True,
            "expenses": converted,
            "count": len(converted),
            "total_amount": round(total_amount, 2)
        }))

    except Exception as e:
        print(f"❌ Report preview failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/submit", methods=["POST"])
def reports_submit():
    """
    Submit a report and archive selected expenses.
    Body: {
      "report_name": "Q1 2024 Down Home Expenses",
      "business_type": "Down Home",
      "expense_indexes": [1, 2, 3, 4, 5]
    }
    """
    ensure_df()
    global df

    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    data = request.get_json(force=True) or {}

    report_name = data.get("report_name")
    business_type = data.get("business_type")
    expense_indexes = data.get("expense_indexes", [])

    if not report_name or not business_type or not expense_indexes:
        abort(400, "Missing required fields (report_name, business_type, expense_indexes)")

    try:
        report_id = db.submit_report(
            report_name=report_name,
            business_type=business_type,
            expense_indexes=expense_indexes
        )

        # Reload df to reflect changes
        df = db.get_all_transactions()

        return jsonify(safe_json({
            "ok": True,
            "report_id": report_id,
            "message": f"Report {report_id} created successfully"
        }))

    except Exception as e:
        print(f"❌ Report submit failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/list", methods=["GET"])
def reports_list():
    """Get all submitted reports"""
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        reports = db.get_all_reports()
        return jsonify(safe_json({"ok": True, "reports": reports}))

    except Exception as e:
        print(f"❌ Report list failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/<report_id>", methods=["GET"])
def reports_get(report_id):
    """Get expenses for a specific report with metadata"""
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        # Get report metadata
        report_meta = db.get_report(report_id)
        if not report_meta:
            abort(404, f"Report {report_id} not found")

        expenses = db.get_report_expenses(report_id)

        # Convert to UI-friendly format
        converted = []
        for exp in expenses:
            # Get R2 URL for receipts
            r2_url = exp.get("r2_url") or ""
            receipt_file = exp.get("receipt_file") or ""

            converted.append({
                "_index": exp["_index"],
                "Chase Date": exp["chase_date"],
                "Chase Description": exp["chase_description"],
                "Chase Amount": exp["chase_amount"],
                "Chase Category": exp["chase_category"],
                "Chase Type": exp["chase_type"],
                "Receipt File": receipt_file,
                "R2 URL": r2_url,
                "receipt_url": r2_url or receipt_file,
                "Business Type": exp["business_type"],
                "Notes": exp["notes"],
                "AI Note": exp["ai_note"],
                "AI Confidence": exp["ai_confidence"],
                "Review Status": exp["review_status"],
                "Category": exp["category"],
                "Report ID": exp["report_id"],
                "Source": exp["source"],
                "MI Merchant": exp.get("mi_merchant") or "",
                "MI Category": exp.get("mi_category") or "",
            })

        total_amount = sum(abs(float(e.get("Chase Amount", 0) or 0)) for e in converted)

        return jsonify(safe_json({
            "ok": True,
            "report_id": report_id,
            "report_name": report_meta.get("report_name") or report_id,
            "business_type": report_meta.get("business_type") or "",
            "created_at": str(report_meta.get("created_at") or ""),
            "expenses": converted,
            "count": len(converted),
            "total_amount": round(total_amount, 2)
        }))

    except Exception as e:
        print(f"❌ Report get failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/<report_id>/delete", methods=["DELETE", "POST"])
def reports_delete(report_id):
    """
    Delete/unsubmit a report and return expenses to available pool.
    This is the 'unsubmit' functionality.
    """
    ensure_df()
    global df

    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        success = db.delete_report(report_id)

        if not success:
            abort(404, f"Report {report_id} not found")

        # Reload df to reflect changes
        df = db.get_all_transactions()

        return jsonify(safe_json({
            "ok": True,
            "message": f"Report {report_id} deleted. Expenses returned to available pool."
        }))

    except Exception as e:
        print(f"❌ Report delete failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/<report_id>/unsubmit", methods=["POST"])
def reports_unsubmit(report_id):
    """
    Unsubmit a report - returns all transactions to the main viewer.
    Clears report_id and already_submitted fields from transactions.
    The report record is deleted but transactions are preserved.
    """
    ensure_df()
    global df

    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        # Get report info before deleting for the response
        report_info = db.get_report(report_id)
        if not report_info:
            abort(404, f"Report {report_id} not found")

        report_name = report_info.get('name', report_id)
        expense_count = report_info.get('expense_count', 0)

        # Use delete_report which clears report_id AND already_submitted
        success = db.delete_report(report_id)

        if not success:
            abort(500, f"Failed to unsubmit report {report_id}")

        # Reload df to reflect changes
        df = db.get_all_transactions()

        print(f"✅ Report '{report_name}' unsubmitted. {expense_count} expenses returned to main viewer.", flush=True)

        return jsonify(safe_json({
            "ok": True,
            "report_id": report_id,
            "report_name": report_name,
            "expenses_restored": expense_count,
            "message": f"Report '{report_name}' unsubmitted. {expense_count} expenses returned to main viewer."
        }))

    except Exception as e:
        print(f"❌ Report unsubmit failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/export/reconciliation.csv", methods=["GET"])
def export_reconciliation_csv():
    """
    Export all Down Home transactions with reconciliation data as CSV.
    No auth required - just exports the data.

    Query params:
    - start_date: Start date (default: 2024-07-01)
    - end_date: End date (default: 2025-12-01)
    - business_type: Business type filter (default: Down Home)
    """
    if not USE_DATABASE or not db:
        abort(503, "Requires database mode")

    try:
        start_date = request.args.get('start_date', '2024-07-01')
        end_date = request.args.get('end_date', '2025-12-01')
        business_type = request.args.get('business_type', 'Down Home')

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT
                _index, chase_date, chase_amount, chase_description,
                mi_category, review_status, ai_confidence,
                ai_receipt_merchant, ai_receipt_total, ai_receipt_date,
                r2_url, receipt_url, receipt_file, notes, business_type
            FROM transactions
            WHERE business_type = ?
            AND chase_date >= ?
            AND chase_date <= ?
            ORDER BY chase_date DESC
        ''', (business_type, start_date, end_date))

        rows = [dict(r) for r in cursor.fetchall()]
        return_db_connection(conn)

        import io
        import csv

        output = io.StringIO()
        writer = csv.writer(output)

        writer.writerow([
            'Index', 'Date', 'Amount', 'Merchant', 'Category',
            'Review_Status', 'AI_Confidence', 'Receipt_Merchant',
            'Receipt_Total', 'Receipt_Date', 'Receipt_URL', 'Notes'
        ])

        for row in rows:
            receipt_url = row.get('r2_url') or row.get('receipt_url') or ''
            if not receipt_url and row.get('receipt_file'):
                rf = row['receipt_file']
                if rf and not rf.startswith('http'):
                    receipt_url = f"https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/receipts/{rf}"
                elif rf:
                    receipt_url = rf

            writer.writerow([
                row.get('_index', ''),
                str(row.get('chase_date', '')),
                f"${float(row.get('chase_amount', 0) or 0):.2f}",
                row.get('chase_description', ''),
                row.get('mi_category', '') or '',
                row.get('review_status', '') or '',
                f"{int(row.get('ai_confidence', 0) or 0)}%" if row.get('ai_confidence') else '',
                row.get('ai_receipt_merchant', '') or '',
                row.get('ai_receipt_total', '') or '',
                row.get('ai_receipt_date', '') or '',
                receipt_url,
                (row.get('notes', '') or '').replace('\n', ' ')[:300]
            ])

        csv_content = output.getvalue()

        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = f'attachment; filename=reconciliation_{business_type.replace(" ", "_")}_{start_date}_{end_date}.csv'
        return response

    except Exception as e:
        print(f"❌ Export error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        abort(500, str(e))


@app.route("/api/vision-verify", methods=["POST"])
def api_vision_verify_batch():
    """
    Vision verify a batch of transactions and return results.
    Runs on server side where DB connection is stable.

    POST body: {"indices": [1, 2, 3, ...]} or {"all": true}
    Returns: {"results": [...], "summary": {...}}
    """
    if not USE_DATABASE or not db:
        abort(503, "Requires database mode")

    try:
        import base64
        import requests as http_requests
        import json
        import re

        data = request.json or {}
        indices = data.get('indices', [])
        verify_all = data.get('all', False)
        limit = data.get('limit', 600)
        offset = data.get('offset', 0)

        conn, db_type = get_db_connection()

        # Fetch transactions
        if verify_all:
            cursor = db_execute(conn, db_type, '''
                SELECT _index, chase_date, chase_amount, chase_description,
                       receipt_file, receipt_url, r2_url, review_status
                FROM transactions
                WHERE business_type = 'Down Home'
                AND chase_date >= '2024-07-01'
                AND chase_date <= '2025-12-01'
                ORDER BY chase_date DESC
                LIMIT ? OFFSET ?
            ''', (limit, offset))
        else:
            placeholders = ','.join(['?' for _ in indices])
            cursor = db_execute(conn, db_type, f'''
                SELECT _index, chase_date, chase_amount, chase_description,
                       receipt_file, receipt_url, r2_url, review_status
                FROM transactions
                WHERE _index IN ({placeholders})
            ''', tuple(indices))

        transactions = [dict(r) for r in cursor.fetchall()]
        return_db_connection(conn)

        # Load all Gemini API keys for rotation
        gemini_keys = [
            os.environ.get('GEMINI_API_KEY'),
            os.environ.get('GEMINI_API_KEY_2'),
            os.environ.get('GEMINI_API_KEY_3')
        ]
        gemini_keys = [k for k in gemini_keys if k]  # Filter out None
        if not gemini_keys:
            return jsonify({"error": "No Gemini API key configured"}), 500

        current_key_idx = 0
        gemini_key = gemini_keys[current_key_idx]
        print(f"Using Gemini key #{current_key_idx + 1} of {len(gemini_keys)}", flush=True)

        results = []
        verified = 0
        mismatch = 0
        unclear = 0
        no_receipt = 0

        for tx in transactions:
            idx = tx['_index']
            date = str(tx['chase_date'])
            amount = float(tx['chase_amount'] or 0)
            merchant = tx['chase_description'] or ''

            # Get receipt URL
            receipt_url = tx.get('r2_url') or tx.get('receipt_url') or ''
            if not receipt_url and tx.get('receipt_file'):
                rf = tx['receipt_file']
                if ',' in rf:
                    rf = rf.split(',')[0].strip()
                if rf and not rf.startswith('http'):
                    receipt_url = f"https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/receipts/{rf}"
                elif rf:
                    receipt_url = rf

            if not receipt_url:
                results.append({
                    'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                    'receipt_url': '', 'verdict': 'NO_RECEIPT', 'confidence': 0,
                    'receipt_total': '', 'receipt_merchant': '', 'reasoning': 'No receipt attached'
                })
                no_receipt += 1
                continue

            # Fetch and verify with Gemini
            try:
                img_resp = http_requests.get(receipt_url, timeout=30)
                if img_resp.status_code != 200:
                    results.append({
                        'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                        'receipt_url': receipt_url, 'verdict': 'UNCLEAR', 'confidence': 0,
                        'receipt_total': '', 'receipt_merchant': '', 'reasoning': f'Could not fetch image: {img_resp.status_code}'
                    })
                    unclear += 1
                    continue

                image_data = base64.b64encode(img_resp.content).decode('utf-8')
                content_type = img_resp.headers.get('content-type', 'image/jpeg')
                mime_type = 'image/png' if 'png' in content_type.lower() else 'image/jpeg'

                prompt = f"""Analyze this receipt image and compare it to the bank transaction:

Bank Transaction:
- Amount: ${abs(amount):.2f}
- Date: {date}
- Merchant: {merchant}

Extract from the receipt:
1. Total amount (look for "Total", "Amount Due", "Grand Total", etc.)
2. Date on receipt
3. Merchant/vendor name

Then determine if this receipt MATCHES the bank transaction:
- Amount must be within $1.00 OR within 20% for tips/gratuity
- Merchant name should reasonably match (variations OK)
- Date within 7 days is acceptable

Respond in this exact JSON format:
{{"receipt_total": "XX.XX", "receipt_date": "YYYY-MM-DD or null", "receipt_merchant": "name", "verdict": "VERIFIED" or "MISMATCH" or "UNCLEAR", "confidence": 0-100, "reasoning": "brief explanation"}}"""

                payload = {
                    "contents": [{"parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": image_data}}
                    ]}],
                    "generationConfig": {"temperature": 0.1}
                }

                # Try with key rotation on 429 errors
                api_resp = None
                max_retries = len(gemini_keys) * 2  # Try each key twice
                for retry in range(max_retries):
                    api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
                    api_resp = http_requests.post(api_url, json=payload, timeout=60)

                    if api_resp.status_code == 200:
                        break
                    elif api_resp.status_code == 429:
                        # Rate limited - rotate to next key
                        current_key_idx = (current_key_idx + 1) % len(gemini_keys)
                        gemini_key = gemini_keys[current_key_idx]
                        print(f"  Rate limited, switching to key #{current_key_idx + 1}", flush=True)
                        import time
                        time.sleep(2)  # Brief pause before retry
                    else:
                        break  # Other errors, don't retry

                if api_resp.status_code != 200:
                    results.append({
                        'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                        'receipt_url': receipt_url, 'verdict': 'UNCLEAR', 'confidence': 0,
                        'receipt_total': '', 'receipt_merchant': '', 'reasoning': f'API error: {api_resp.status_code}'
                    })
                    unclear += 1
                    continue

                result = api_resp.json()
                text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

                # Parse JSON
                json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    verdict = parsed.get('verdict', 'UNCLEAR')
                    confidence = parsed.get('confidence', 0)
                    reasoning = parsed.get('reasoning', '')
                    receipt_total = parsed.get('receipt_total', '')
                    receipt_merchant = parsed.get('receipt_merchant', '')

                    results.append({
                        'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                        'receipt_url': receipt_url, 'verdict': verdict, 'confidence': confidence,
                        'receipt_total': receipt_total, 'receipt_merchant': receipt_merchant,
                        'reasoning': reasoning
                    })

                    if verdict == 'VERIFIED':
                        verified += 1
                    elif verdict == 'MISMATCH':
                        mismatch += 1
                    else:
                        unclear += 1
                else:
                    results.append({
                        'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                        'receipt_url': receipt_url, 'verdict': 'UNCLEAR', 'confidence': 0,
                        'receipt_total': '', 'receipt_merchant': '', 'reasoning': 'Could not parse response'
                    })
                    unclear += 1

            except Exception as e:
                results.append({
                    'index': idx, 'date': date, 'amount': amount, 'merchant': merchant,
                    'receipt_url': receipt_url, 'verdict': 'UNCLEAR', 'confidence': 0,
                    'receipt_total': '', 'receipt_merchant': '', 'reasoning': str(e)
                })
                unclear += 1

        return jsonify({
            "results": results,
            "summary": {
                "total": len(transactions),
                "verified": verified,
                "mismatch": mismatch,
                "unclear": unclear,
                "no_receipt": no_receipt
            }
        })

    except Exception as e:
        print(f"❌ Vision verify error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        abort(500, str(e))


@app.route("/export/vision-verify.csv", methods=["GET"])
def export_vision_verify_csv():
    """
    Run vision verification on all Down Home transactions and export as CSV.
    This runs server-side where DB connection is stable.

    Query params:
    - limit: Max transactions to process (default: 600)
    - offset: Starting offset (default: 0)
    """
    if not USE_DATABASE or not db:
        abort(503, "Requires database mode")

    try:
        import base64
        import requests as http_requests
        import json
        import re
        import io
        import csv

        limit = int(request.args.get('limit', 600))
        offset = int(request.args.get('offset', 0))

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT _index, chase_date, chase_amount, chase_description,
                   receipt_file, receipt_url, r2_url, review_status
            FROM transactions
            WHERE business_type = 'Down Home'
            AND chase_date >= '2024-07-01'
            AND chase_date <= '2025-12-01'
            ORDER BY chase_date DESC
            LIMIT ? OFFSET ?
        ''', (limit, offset))

        transactions = [dict(r) for r in cursor.fetchall()]
        return_db_connection(conn)

        gemini_key = os.environ.get('GEMINI_API_KEY')
        if not gemini_key:
            abort(500, "No Gemini API key configured")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Index', 'Date', 'Amount', 'Merchant', 'Receipt_URL',
            'Verdict', 'Confidence', 'Receipt_Total', 'Receipt_Merchant', 'Reasoning'
        ])

        for tx in transactions:
            idx = tx['_index']
            date = str(tx['chase_date'])
            amount = float(tx['chase_amount'] or 0)
            merchant = tx['chase_description'] or ''

            # Get receipt URL
            receipt_url = tx.get('r2_url') or tx.get('receipt_url') or ''
            if not receipt_url and tx.get('receipt_file'):
                rf = tx['receipt_file']
                if ',' in rf:
                    rf = rf.split(',')[0].strip()
                if rf and not rf.startswith('http'):
                    receipt_url = f"https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/receipts/{rf}"
                elif rf:
                    receipt_url = rf

            if not receipt_url:
                writer.writerow([idx, date, f"${amount:.2f}", merchant, '', 'NO_RECEIPT', '', '', '', 'No receipt attached'])
                continue

            # Fetch and verify with Gemini
            try:
                img_resp = http_requests.get(receipt_url, timeout=30)
                if img_resp.status_code != 200:
                    writer.writerow([idx, date, f"${amount:.2f}", merchant, receipt_url, 'UNCLEAR', '', '', '', f'Could not fetch: {img_resp.status_code}'])
                    continue

                image_data = base64.b64encode(img_resp.content).decode('utf-8')
                content_type = img_resp.headers.get('content-type', 'image/jpeg')
                mime_type = 'image/png' if 'png' in content_type.lower() else 'image/jpeg'

                prompt = f"""Analyze this receipt image and compare it to the bank transaction:

Bank Transaction:
- Amount: ${abs(amount):.2f}
- Date: {date}
- Merchant: {merchant}

Extract from the receipt:
1. Total amount (look for "Total", "Amount Due", "Grand Total", etc.)
2. Date on receipt
3. Merchant/vendor name

Then determine if this receipt MATCHES the bank transaction:
- Amount must be within $1.00 OR within 20% for tips/gratuity
- Merchant name should reasonably match (variations OK)
- Date within 7 days is acceptable

Respond in this exact JSON format:
{{"receipt_total": "XX.XX", "receipt_date": "YYYY-MM-DD or null", "receipt_merchant": "name", "verdict": "VERIFIED" or "MISMATCH" or "UNCLEAR", "confidence": 0-100, "reasoning": "brief explanation"}}"""

                api_url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{"parts": [
                        {"text": prompt},
                        {"inline_data": {"mime_type": mime_type, "data": image_data}}
                    ]}],
                    "generationConfig": {"temperature": 0.1}
                }

                api_resp = http_requests.post(api_url, json=payload, timeout=60)
                if api_resp.status_code != 200:
                    writer.writerow([idx, date, f"${amount:.2f}", merchant, receipt_url, 'UNCLEAR', '', '', '', f'API error: {api_resp.status_code}'])
                    continue

                result = api_resp.json()
                text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

                json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    writer.writerow([
                        idx, date, f"${amount:.2f}", merchant, receipt_url,
                        parsed.get('verdict', 'UNCLEAR'),
                        f"{parsed.get('confidence', 0)}%",
                        parsed.get('receipt_total', ''),
                        parsed.get('receipt_merchant', ''),
                        parsed.get('reasoning', '')[:200]
                    ])
                else:
                    writer.writerow([idx, date, f"${amount:.2f}", merchant, receipt_url, 'UNCLEAR', '', '', '', 'Could not parse'])

            except Exception as e:
                writer.writerow([idx, date, f"${amount:.2f}", merchant, receipt_url, 'UNCLEAR', '', '', '', str(e)[:100]])

        csv_content = output.getvalue()
        response = make_response(csv_content)
        response.headers['Content-Type'] = 'text/csv'
        response.headers['Content-Disposition'] = 'attachment; filename=vision_verification_results.csv'
        return response

    except Exception as e:
        print(f"❌ Vision verify CSV error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        abort(500, str(e))


@app.route("/reports/<report_id>/export/downhome", methods=["GET"])
def reports_export_downhome(report_id):
    """
    Export a report in Down Home CSV format.
    Format: External ID, Line, Category, Amount, Currency, Date, Project, Memo, Line of Business, Billable
    """
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        expenses = db.get_report_expenses(report_id)

        if not expenses:
            abort(404, f"No expenses found for report {report_id}")

        # Build CSV rows in Down Home format
        import io
        import csv

        output = io.StringIO()
        writer = csv.writer(output)

        # Write header (matching the template exactly + Receipt URL)
        writer.writerow([
            "External ID",
            "Line",
            "Category",
            "Amount",
            "Currency",
            "Date",
            "Project",
            "Memo",
            "Line of Business(do not fill)",
            "Billable",
            "Receipt URL"
        ])

        # Write expense rows
        for line_num, exp in enumerate(expenses, start=1):
            # Parse and format the date
            chase_date = exp.get("chase_date", "")
            try:
                if chase_date:
                    # Try to parse various date formats and output as MM/DD/YYYY
                    from dateutil import parser as date_parser
                    parsed_date = date_parser.parse(chase_date)
                    formatted_date = parsed_date.strftime("%m/%d/%Y")
                else:
                    formatted_date = ""
            except:
                formatted_date = chase_date

            # Get amount (absolute value, formatted as currency)
            amount = exp.get("chase_amount", 0)
            try:
                amount = abs(float(amount or 0))
            except:
                amount = 0

            # Get category - use MI Category if available, else Chase Category, else Category
            category = (
                exp.get("mi_category") or
                exp.get("category") or
                exp.get("chase_category") or
                ""
            )

            # Build memo from description and notes
            description = exp.get("chase_description", "")
            notes = exp.get("notes", "")
            memo = description
            if notes and notes != description:
                memo = f"{description} - {notes}" if description else notes

            # Get receipt URL - check receipt_url column or generate from filename
            receipt_url = exp.get("receipt_url", "")
            if not receipt_url:
                receipt_file = exp.get("receipt_file", "")
                if receipt_file:
                    # Generate R2 URL from filename
                    receipt_url = f"https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/receipts/{receipt_file}"

            writer.writerow([
                f"{report_id}-{line_num}",  # External ID
                line_num,                     # Line
                category,                     # Category
                f"{amount:.2f}",             # Amount
                "USD",                        # Currency
                formatted_date,               # Date
                "",                           # Project (leave blank)
                memo,                         # Memo
                "",                           # Line of Business (do not fill)
                "",                           # Billable (leave blank)
                receipt_url                   # Receipt URL
            ])

        # Create response with CSV content
        output.seek(0)
        response = make_response(output.getvalue())
        response.headers["Content-Disposition"] = f"attachment; filename=downhome_report_{report_id}.csv"
        response.headers["Content-Type"] = "text/csv"

        print(f"✅ Exported Down Home report {report_id} with {len(expenses)} expenses", flush=True)

        return response

    except Exception as e:
        print(f"❌ Down Home export failed: {e}", flush=True)
        abort(500, str(e))


# =============================================================================
# ENHANCED REPORT FEATURES
# =============================================================================

def generate_human_note(expense):
    """Generate a human-readable note for an expense"""
    merchant = expense.get("Chase Description", "")
    category = expense.get("Chase Category", "") or expense.get("Category", "")
    amount = expense.get("Chase Amount", 0)

    # Extract merchant name (remove prefixes like TST*, DD, etc.)
    clean_merchant = re.sub(r'^(TST\*?|DD\s+|SP\s+)', '', merchant).strip()

    # Generate contextual notes based on category
    category_lower = category.lower() if category else ""

    if "restaurant" in category_lower or "dining" in category_lower or "food" in category_lower:
        return f"Business meal at {clean_merchant}"
    elif "travel" in category_lower or "transportation" in category_lower:
        if "uber" in merchant.lower() or "lyft" in merchant.lower():
            return f"Rideshare via {clean_merchant}"
        elif "airline" in merchant.lower() or "southwest" in merchant.lower() or "delta" in merchant.lower():
            return f"Airfare - {clean_merchant}"
        else:
            return f"Travel expense - {clean_merchant}"
    elif "hotel" in category_lower or "lodging" in category_lower:
        return f"Accommodation at {clean_merchant}"
    elif "office" in category_lower or "supplies" in category_lower:
        return f"Office supplies from {clean_merchant}"
    elif "software" in category_lower or "subscription" in category_lower:
        return f"Software/subscription - {clean_merchant}"
    elif "parking" in category_lower:
        return f"Parking at {clean_merchant}"
    elif "fuel" in category_lower or "gas" in category_lower:
        return f"Fuel purchase at {clean_merchant}"
    else:
        # Generic business expense
        if amount > 1000:
            return f"Major purchase from {clean_merchant}"
        else:
            return f"Business expense - {clean_merchant}"


@app.route("/reports/generate_notes", methods=["POST"])
def reports_generate_notes():
    """
    Generate human-readable notes for expenses in report preview
    Body: { "expenses": [...] }
    Returns: { "ok": True, "expenses_with_notes": [...] }
    """
    data = request.get_json(force=True) or {}
    expenses = data.get("expenses", [])

    for exp in expenses:
        # Use existing notes if present and not AI-generated
        existing_note = exp.get("Notes") or ""
        ai_note = exp.get("AI Note") or ""

        # Strip if they're strings
        if isinstance(existing_note, str):
            existing_note = existing_note.strip()
        if isinstance(ai_note, str):
            ai_note = ai_note.strip()

        # If there's a manual note, use it
        if existing_note and not existing_note.startswith("AI-"):
            continue

        # Generate a human note
        exp["Notes"] = generate_human_note(exp)

    return jsonify(safe_json({
        "ok": True,
        "expenses_with_notes": expenses
    }))


@app.route("/reports/<report_id>/receipts.zip", methods=["GET"])
def reports_download_receipts_zip(report_id):
    """Download all receipts for a report as a ZIP file"""
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        expenses = db.get_report_expenses(report_id)

        if not expenses:
            abort(404, f"No expenses found for report {report_id}")

        # Get report metadata
        reports = db.get_all_reports()
        report_meta = next((r for r in reports if r["report_id"] == report_id), None)
        report_name = report_meta.get("report_name", report_id) if report_meta else report_id

        # Create ZIP in memory
        zip_buffer = io.BytesIO()
        import requests

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            receipt_count = 0

            for exp in expenses:
                receipt_file = exp.get("receipt_file")
                receipt_url = exp.get("receipt_url") or ""

                # Build descriptive filename
                merchant = exp.get("chase_description", "expense")
                date = exp.get("chase_date", "")
                amount = exp.get("chase_amount", 0)

                file_data = None
                ext = ".jpg"  # default

                # Try R2 URL first (cloud storage)
                if receipt_url and receipt_url.startswith("http"):
                    try:
                        resp = requests.get(receipt_url, timeout=30)
                        if resp.status_code == 200:
                            file_data = resp.content
                            # Get extension from URL
                            if "." in receipt_url.split("/")[-1]:
                                ext = "." + receipt_url.split(".")[-1].split("?")[0]
                            receipt_count += 1
                    except Exception as e:
                        print(f"⚠️  Failed to fetch R2 receipt: {e}", flush=True)

                # Fallback to local file
                if not file_data and receipt_file:
                    receipt_path = Path(RECEIPT_DIR) / receipt_file
                    if receipt_path.exists():
                        with open(receipt_path, 'rb') as f:
                            file_data = f.read()
                        ext = receipt_path.suffix
                        receipt_count += 1

                # Add to ZIP if we got data
                if file_data:
                    clean_filename = f"{date}_{merchant}_{amount}{ext}".replace(" ", "_").replace("/", "-")[:100]
                    zip_file.writestr(clean_filename, file_data)

        if receipt_count == 0:
            abort(404, "No receipts found for this report")

        zip_buffer.seek(0)

        # Send ZIP file
        return send_file(
            zip_buffer,
            mimetype='application/zip',
            as_attachment=True,
            download_name=f"{report_name}_receipts.zip"
        )

    except Exception as e:
        print(f"❌ Receipts ZIP download failed: {e}", flush=True)
        abort(500, str(e))


@app.route("/reports/<report_id>/receipts/<filename>", methods=["GET"])
def reports_download_receipt(report_id, filename):
    """Download a specific receipt from a report"""
    # Security: Prevent path traversal attacks
    if '..' in filename or filename.startswith('/') or filename.startswith('\\'):
        abort(400, "Invalid filename")

    # Sanitize filename to only allow safe characters
    safe_filename = ''.join(c for c in filename if c.isalnum() or c in '._-')
    if safe_filename != filename:
        abort(400, "Invalid characters in filename")

    receipt_path = (RECEIPT_DIR / filename).resolve()

    # Verify the resolved path is still within RECEIPT_DIR
    if not str(receipt_path).startswith(str(RECEIPT_DIR.resolve())):
        abort(403, "Access denied")

    if not receipt_path.exists():
        abort(404, f"Receipt not found: {filename}")

    return send_file(receipt_path, as_attachment=False)


@app.route("/reports/<report_id>/page", methods=["GET"])
def reports_standalone_page(report_id):
    """Render a beautiful standalone report page that can be shared"""
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        expenses = db.get_report_expenses(report_id)

        if not expenses:
            abort(404, f"Report {report_id} not found")

        # Get report metadata
        reports = db.get_all_reports()
        report_meta = next((r for r in reports if r["report_id"] == report_id), None)

        if not report_meta:
            abort(404, f"Report metadata not found for {report_id}")

        report_name = report_meta.get("report_name", report_id)
        business_type = report_meta.get("business_type", "")
        created_at = report_meta.get("created_at", "")

        # Calculate totals
        total_amount = sum(abs(float(e.get("chase_amount", 0) or 0)) for e in expenses)
        receipt_count = sum(1 for e in expenses if e.get("receipt_file"))

        # Get date range
        dates = [e.get("chase_date") for e in expenses if e.get("chase_date")]
        date_from = min(dates) if dates else ""
        date_to = max(dates) if dates else ""

        # Generate human notes for each expense
        for exp in expenses:
            if not exp.get("notes") or exp.get("notes", "").startswith("AI-"):
                exp["notes"] = generate_human_note({
                    "Chase Description": exp.get("chase_description", ""),
                    "Chase Category": exp.get("chase_category", ""),
                    "Category": exp.get("category", ""),
                    "Chase Amount": exp.get("chase_amount", 0)
                })

        # Render HTML template
        html = f"""
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{report_name} - Expense Report</title>
<style>
body {{
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
  max-width: 1200px;
  margin: 0 auto;
  padding: 40px 20px;
  background: #000;
  color: #f0f0f0;
}}
.header {{
  background: linear-gradient(135deg, #00ff88 0%, #00cc6a 100%);
  color: #000;
  padding: 40px;
  border-radius: 12px;
  margin-bottom: 30px;
  box-shadow: 0 4px 16px rgba(0,255,136,0.3);
}}
.header h1 {{
  margin: 0 0 10px 0;
  font-size: 28px;
}}
.header p {{
  margin: 5px 0;
  opacity: 0.8;
  font-size: 16px;
}}
.stats {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
  gap: 20px;
  margin-bottom: 30px;
}}
.stat-card {{
  background: #111;
  padding: 24px;
  border-radius: 12px;
  border: 1px solid #222;
}}
.stat-label {{
  color: #888;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 8px;
}}
.stat-value {{
  font-size: 32px;
  font-weight: 700;
  color: #00ff88;
}}
.actions {{
  background: #111;
  padding: 20px;
  border-radius: 12px;
  margin-bottom: 30px;
  display: flex;
  gap: 12px;
  flex-wrap: wrap;
  border: 1px solid #222;
}}
.btn {{
  padding: 12px 24px;
  border-radius: 8px;
  text-decoration: none;
  font-weight: 600;
  font-size: 14px;
  transition: all 0.2s;
  border: none;
  cursor: pointer;
}}
.btn-primary {{
  background: linear-gradient(135deg, #00ff88, #00cc6a);
  color: #000;
}}
.btn-primary:hover {{
  transform: translateY(-1px);
  box-shadow: 0 4px 12px rgba(0,255,136,0.4);
}}
.table-container {{
  background: #111;
  border-radius: 12px;
  overflow: hidden;
  border: 1px solid #222;
}}
table {{
  width: 100%;
  border-collapse: collapse;
}}
th {{
  background: #0a0a0a;
  padding: 16px;
  text-align: left;
  font-weight: 600;
  color: #888;
  font-size: 13px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 1px solid #222;
}}
td {{
  padding: 16px;
  border-bottom: 1px solid #1a1a1a;
}}
tr:hover {{
  background: #0a0a0a;
}}
.amount {{
  font-weight: 700;
  color: #00ff88;
  font-size: 15px;
}}
.receipt-link {{
  color: #00ff88;
  text-decoration: none;
  font-size: 13px;
}}
.receipt-link:hover {{
  text-decoration: underline;
}}
.notes {{
  color: #888;
  font-size: 13px;
  font-style: italic;
}}
</style>
</head>
<body>

<div class="header">
  <h1>🧾 Tallyups Expense Report</h1>
  <p><strong>{report_name}</strong></p>
  <p>{business_type}</p>
  <p>{date_from} to {date_to}</p>
</div>

<div class="stats">
  <div class="stat-card">
    <div class="stat-label">Total Amount</div>
    <div class="stat-value">${total_amount:,.2f}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Expenses</div>
    <div class="stat-value">{len(expenses)}</div>
  </div>
  <div class="stat-card">
    <div class="stat-label">Receipts</div>
    <div class="stat-value">{receipt_count}</div>
  </div>
</div>

<div class="actions">
  <a href="/reports/{report_id}/export/downhome" class="btn btn-primary" download>
    📊 Download CSV
  </a>
  <a href="/reports/{report_id}/receipts.zip" class="btn btn-primary" download>
    📦 Download All Receipts
  </a>
</div>

<div class="table-container">
  <table>
    <thead>
      <tr>
        <th>Date</th>
        <th>Description</th>
        <th>Amount</th>
        <th>Category</th>
        <th>Notes</th>
        <th>Receipt</th>
      </tr>
    </thead>
    <tbody>
"""

        # Add expense rows
        for exp in expenses:
            date = exp.get("chase_date", "")
            desc = exp.get("chase_description", "")
            amount = abs(float(exp.get("chase_amount", 0) or 0))
            category = exp.get("category") or exp.get("chase_category", "")
            notes = exp.get("notes", "")
            receipt = exp.get("receipt_file", "")

            receipt_link = ""
            if receipt:
                receipt_link = f'<a href="/reports/{report_id}/receipts/{receipt}" class="receipt-link" target="_blank">View Receipt</a>'
            else:
                receipt_link = '<span style="color:#999">No receipt</span>'

            html += f"""
      <tr>
        <td>{date}</td>
        <td>{desc}</td>
        <td class="amount">${amount:,.2f}</td>
        <td>{category}</td>
        <td class="notes">{notes}</td>
        <td>{receipt_link}</td>
      </tr>
"""

        html += """
    </tbody>
  </table>
</div>

<div style="margin-top:40px;padding:20px;text-align:center;color:#999;font-size:13px">
  <p>Generated by ReceiptAI Master System</p>
  <p>Report ID: """ + report_id + """ | Created: """ + created_at + """</p>
</div>

</body>
</html>
"""

        return html

    except Exception as e:
        print(f"❌ Report page failed: {e}", flush=True)
        import traceback
        traceback.print_exc()
        abort(500, str(e))


# =============================================================================
# AI ENDPOINTS (VISION + GPT-4.1 + GMAIL SEARCH)
# =============================================================================

@app.post("/ai_match")
def api_ai_match():
    """
    Single-row AI matching endpoint.
    Uses orchestrator to find best receipt (local → Gmail escalation).
    """
    if not ORCHESTRATOR_AVAILABLE:
        return jsonify({"ok": False, "error": "Orchestrator not available"}), 503

    data = request.get_json()
    idx = data.get("_index")

    if idx is None:
        return jsonify({"ok": False, "error": "Missing _index"}), 400

    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"Invalid _index: {idx}"}), 400

    # Get row from DataFrame
    row = get_row_by_index(idx)
    if not row:
        return jsonify({"ok": False, "error": f"Row {idx} not found"}), 404

    # ---- CALL ORCHESTRATOR ----
    # Gmail now enabled with fixed token paths
    result = find_best_receipt_for_transaction(row, enable_gmail=True)

    # Update DataFrame with AI fields
    fields_to_update = {
        "Receipt File": result.get("receipt_file") or "",
        "match_score": result.get("match_score", 0),
        "ai_receipt_merchant": result.get("ai_receipt_merchant", ""),
        "ai_receipt_date": result.get("ai_receipt_date", ""),
        "ai_receipt_total": result.get("ai_receipt_total", ""),
        "ai_reason": result.get("ai_reason", ""),
        "ai_confidence": result.get("ai_confidence", 0),
        "source": result.get("source", ""),
        "method": result.get("method", "")
    }

    update_row_by_index(idx, fields_to_update)

    return jsonify({"ok": True, "result": safe_json(fields_to_update)})


@app.post("/ai_note")
def api_ai_note():
    """
    Generate an intelligent AI note for a transaction using context.
    """
    if not ORCHESTRATOR_AVAILABLE:
        return jsonify({"ok": False, "error": "Orchestrator not available"}), 503

    data = request.get_json()
    idx = data.get("_index")

    if idx is None:
        return jsonify({"ok": False, "error": "Missing _index"}), 400

    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": f"Invalid _index: {idx}"}), 400

    row = get_row_by_index(idx)
    if not row:
        return jsonify({"ok": False, "error": f"Row {idx} not found"}), 404

    # Generate AI note
    note = ai_generate_note(row)

    # Update the row
    update_row_by_index(idx, {"Notes": note})

    return jsonify({"ok": True, "note": note})


@app.post("/find_missing_receipts")
def api_find_missing_receipts():
    """
    Batch mode: For every row with missing receipts, call the orchestrator.

    Rules:
    - Always fill AI fields with orchestrator output.
    - Auto-attach receipt_file ONLY when match_score >= 90.
    - Otherwise leave row un-attached but still update ai_* reasoning fields.
    """
    if not ORCHESTRATOR_AVAILABLE:
        return jsonify({"ok": False, "error": "Orchestrator not available"}), 503

    global df
    ensure_df()

    auto_attach_threshold = 90

    matched = 0          # high-confidence → attached
    suggested = 0        # low-confidence → ai-only
    failed = 0           # no match at all
    processed = 0

    for idx, row in df.iterrows():
        receipt_file = row.get("Receipt File") or row.get("receipt_file")

        # Only process missing receipts
        if isinstance(receipt_file, str) and receipt_file.strip():
            continue  # already has a receipt, skip

        processed += 1
        tx = row.to_dict()

        # ----------------------------------------------------
        # 🔥 CALL THE ORCHESTRATOR
        # ----------------------------------------------------
        # Gmail now enabled with fixed token paths
        result = find_best_receipt_for_transaction(tx, enable_gmail=True)
        score = result.get("match_score", 0)
        file = result.get("receipt_file")

        # ----------------------------------------------------
        # TRY AUTO ATTACHING (if strong)
        # ----------------------------------------------------
        if file and score >= auto_attach_threshold:
            df.at[idx, "Receipt File"] = file
            df.at[idx, "receipt_file"] = file
            matched += 1
        else:
            # This is a soft match or no match
            if file:
                suggested += 1
            else:
                failed += 1

        # ----------------------------------------------------
        # ALWAYS UPDATE AI FIELDS
        # ----------------------------------------------------
        ai_patch = {
            "ai_receipt_merchant": result.get("ai_receipt_merchant", ""),
            "ai_receipt_date": result.get("ai_receipt_date", ""),
            "ai_receipt_total": result.get("ai_receipt_total", ""),
            "ai_match": "ok",
            "ai_confidence": result.get("ai_confidence", 0),
            "ai_reason": result.get("ai_reason", ""),
            "ai_match_raw": json.dumps(result, ensure_ascii=False),
            "source": result.get("source", "none"),
            "method": result.get("method", "none"),
            "match_score": score,
        }

        for k, v in ai_patch.items():
            df.at[idx, k] = v

    # Save state
    save_csv()

    return jsonify({
        "ok": True,
        "processed": processed,
        "auto_attached": matched,
        "suggested_only": suggested,
        "failed": failed,
        "message": (
            f"Processed {processed} rows — {matched} attached · "
            f"{suggested} suggested · {failed} with no match"
        )
    })

# =============================================================================
# CALENDAR SETTINGS ENDPOINTS
# =============================================================================

@app.route("/settings/calendar/status", methods=["GET"])
def calendar_status():
    """Get Google Calendar connection status (supports multiple accounts)."""
    try:
        from calendar_service import get_calendar_status, get_events_around_date
        from datetime import datetime

        # Get status for all connected accounts
        status = get_calendar_status()

        if not status.get('connected'):
            return jsonify({
                'ok': True,
                'connected': False,
                'message': 'No calendars connected. Set CALENDAR_TOKENS env var for multiple accounts or CALENDAR_TOKEN for single account.',
                'setup_instructions': 'Run setup_multi_calendar.py locally to authorize multiple accounts, then set CALENDAR_TOKENS env var on Railway.'
            })

        # Try to fetch events around today as a connection test
        today = datetime.now().strftime('%Y-%m-%d')
        events = get_events_around_date(today, days_before=1, days_after=1)

        return jsonify({
            'ok': True,
            'connected': True,
            'account_count': status.get('account_count', 1),
            'accounts': status.get('accounts', []),
            'message': f'{status.get("account_count", 1)} calendar(s) connected! Found {len(events)} events around today.',
            'sample_events': [{'title': e['title'], 'calendar': e.get('calendar', 'primary')} for e in events[:10]] if events else []
        })

    except Exception as e:
        return jsonify({
            'ok': False,
            'connected': False,
            'error': str(e)
        })


# Calendar preferences file
CALENDAR_PREFS_FILE = Path(__file__).parent / "calendar_preferences.json"


@app.route("/settings/calendar/preferences", methods=["GET"])
def get_calendar_preferences():
    """Get saved calendar preferences (which calendars are enabled)."""
    try:
        if CALENDAR_PREFS_FILE.exists():
            with open(CALENDAR_PREFS_FILE, 'r') as f:
                prefs = json.load(f)
            return jsonify({
                'ok': True,
                'enabled_calendars': prefs.get('enabled_calendars', [])
            })
        else:
            # Default: all calendars enabled (empty list means all)
            return jsonify({
                'ok': True,
                'enabled_calendars': []
            })
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        })


@app.route("/settings/calendar/preferences", methods=["POST"])
@login_required
def save_calendar_preferences():
    """Save calendar preferences (which calendars are enabled)."""
    try:
        data = request.get_json()
        enabled_calendars = data.get('enabled_calendars', [])

        prefs = {
            'enabled_calendars': enabled_calendars,
            'updated_at': datetime.now().isoformat()
        }

        with open(CALENDAR_PREFS_FILE, 'w') as f:
            json.dump(prefs, f, indent=2)

        return jsonify({
            'ok': True,
            'message': f'Saved {len(enabled_calendars)} calendar(s)',
            'enabled_calendars': enabled_calendars
        })
    except Exception as e:
        return jsonify({
            'ok': False,
            'error': str(e)
        }), 500


# =============================================================================
# GMAIL SETTINGS ENDPOINTS
# =============================================================================

@app.route("/settings/gmail/status", methods=["GET"])
def gmail_status():
    """Get status of all Gmail accounts"""
    from pathlib import Path
    import json
    from datetime import datetime

    # Check multiple possible token directories (same as callback saves to)
    TOKEN_DIRS = [
        Path('gmail_tokens'),
        Path('receipt-system/gmail_tokens'),
        Path('../Task/receipt-system/gmail_tokens'),
    ]

    ACCOUNTS = [
        {'email': 'brian@downhome.com', 'token_file': 'tokens_brian_downhome_com.json'},
        {'email': 'kaplan.brian@gmail.com', 'token_file': 'tokens_kaplan_brian_gmail_com.json'},
        {'email': 'brian@musiccityrodeo.com', 'token_file': 'tokens_brian_musiccityrodeo_com.json'},
    ]

    statuses = []
    for account in ACCOUNTS:
        token_data = None
        token_source = None

        # First check environment variable (for Railway persistence)
        env_key = f"GMAIL_TOKEN_{account['email'].replace('@', '_').replace('.', '_').upper()}"
        env_token = os.environ.get(env_key)
        if env_token:
            try:
                token_data = json.loads(env_token)
                token_source = 'env'
            except:
                pass

        # If not in env, try to find token in any of the directories
        if not token_data:
            for token_dir in TOKEN_DIRS:
                candidate = token_dir / account['token_file']
                if candidate.exists():
                    try:
                        with open(candidate, 'r') as f:
                            token_data = json.load(f)
                            token_source = str(candidate)
                            break
                    except:
                        pass

        status = {
            'email': account['email'],
            'token_file': account['token_file'],
            'exists': token_data is not None,
            'has_refresh_token': False,
            'expired': None,
            'expiry': None,
            'source': token_source
        }

        if token_data:
            status['has_refresh_token'] = 'refresh_token' in token_data and token_data['refresh_token']

            if 'expiry' in token_data:
                try:
                    expiry = datetime.fromisoformat(token_data['expiry'].replace('Z', '+00:00'))
                    status['expiry'] = token_data['expiry']
                    status['expired'] = expiry < datetime.now(expiry.tzinfo)
                except:
                    pass

        statuses.append(status)

    return jsonify(safe_json({
        'ok': True,
        'accounts': statuses
    }))


@app.route("/settings/gmail/refresh/<account_email>", methods=["POST"])
@login_required
def gmail_refresh_account(account_email):
    """
    Refresh Gmail token using the stored refresh_token.

    This uses the OAuth 2.0 refresh token to get a new access token
    without requiring user interaction.
    """
    try:
        # Try auto-refresh using the refresh_token
        service, error = get_gmail_service(account_email)

        if service:
            # Token refreshed successfully - verify it works
            try:
                profile = service.users().getProfile(userId='me').execute()
                email = profile.get('emailAddress', account_email)
                return jsonify({
                    'ok': True,
                    'message': f'Gmail token refreshed successfully for {email}',
                    'account': email,
                    'refreshed': True
                })
            except Exception as e:
                return jsonify({
                    'ok': False,
                    'error': f'Token refreshed but API call failed: {str(e)}',
                    'account': account_email
                }), 500
        else:
            # Auto-refresh failed - return instructions for re-authorization
            return jsonify({
                'ok': False,
                'error': error or 'Token refresh failed',
                'message': f'Could not auto-refresh token for {account_email}. Re-authorization may be required.',
                'account': account_email,
                'requires_reauth': True
            }), 400

    except Exception as e:
        print(f"Error in gmail_refresh_account: {e}", flush=True)
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/settings/gmail/refresh-all", methods=["POST"])
def gmail_refresh_all():
    """
    Refresh Gmail tokens for all configured accounts.
    """
    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    results = []
    for email in GMAIL_ACCOUNTS.keys():
        service, error = get_gmail_service(email)
        if service:
            try:
                profile = service.users().getProfile(userId='me').execute()
                results.append({
                    'email': email,
                    'ok': True,
                    'verified_email': profile.get('emailAddress', email)
                })
            except Exception as e:
                results.append({
                    'email': email,
                    'ok': False,
                    'error': f'API call failed: {str(e)}'
                })
        else:
            results.append({
                'email': email,
                'ok': False,
                'error': error or 'Token refresh failed'
            })

    success_count = sum(1 for r in results if r['ok'])
    return jsonify({
        'ok': success_count == len(results),
        'message': f'Refreshed {success_count}/{len(results)} Gmail accounts',
        'results': results
    })


# =============================================================================
# GMAIL WEB-BASED OAUTH FLOW
# =============================================================================

# OAuth state storage (in-memory for simplicity, use Redis/DB for production)
_oauth_states = {}

GMAIL_ACCOUNTS = {
    'brian@downhome.com': {'token_file': 'tokens_brian_downhome_com.json', 'name': 'Down Home'},
    'kaplan.brian@gmail.com': {'token_file': 'tokens_kaplan_brian_gmail_com.json', 'name': 'Personal Gmail'},
    'brian@musiccityrodeo.com': {'token_file': 'tokens_brian_musiccityrodeo_com.json', 'name': 'Music City Rodeo'},
    'brian@kaplan.com': {'token_file': 'tokens_brian_kaplan_com.json', 'name': 'Kaplan'},
}

GMAIL_SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']


def get_gmail_credentials_with_autorefresh(account_email: str):
    """
    Load Gmail credentials for an account and automatically refresh if expired.

    Uses google-auth library to handle token refresh via refresh_token.
    Returns (credentials, error) tuple.
    """
    import json
    from datetime import datetime

    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
    except ImportError:
        return None, "google-auth library not installed"

    if account_email not in GMAIL_ACCOUNTS:
        return None, f"Unknown account: {account_email}"

    account = GMAIL_ACCOUNTS[account_email]
    env_key = f"GMAIL_TOKEN_{account_email.replace('@', '_').replace('.', '_').upper()}"

    # Try to load token from env var first
    token_data = None
    token_source = None

    env_token = os.environ.get(env_key)
    if env_token:
        try:
            token_data = json.loads(env_token)
            token_source = 'env'
        except Exception as e:
            print(f"⚠️ Failed to parse {env_key}: {e}", flush=True)

    # Fall back to file
    if not token_data:
        from pathlib import Path
        token_dirs = [
            Path('gmail_tokens'),
            Path('receipt-system/gmail_tokens'),
            Path('../Task/receipt-system/gmail_tokens'),
        ]
        for token_dir in token_dirs:
            candidate = token_dir / account['token_file']
            if candidate.exists():
                try:
                    with open(candidate, 'r') as f:
                        token_data = json.load(f)
                        token_source = str(candidate)
                        break
                except:
                    pass

    if not token_data:
        return None, f"No token found for {account_email}"

    # Check if we have a refresh token
    if 'refresh_token' not in token_data or not token_data['refresh_token']:
        return None, f"No refresh token for {account_email}"

    # Create credentials object
    try:
        # Use client info from token itself first (preferred), fallback to OAuth credentials file
        client_id = token_data.get('client_id')
        client_secret = token_data.get('client_secret')
        token_uri = token_data.get('token_uri', 'https://oauth2.googleapis.com/token')
        scopes = token_data.get('scopes', GMAIL_SCOPES)

        # If token doesn't have client info, try OAuth credentials file
        if not client_id or not client_secret:
            oauth_creds = get_oauth_credentials()
            if not oauth_creds:
                return None, "OAuth credentials not configured and token missing client info"
            client_info = oauth_creds.get('web') or oauth_creds.get('installed')
            if not client_info:
                return None, "Invalid OAuth credentials format"
            client_id = client_info.get('client_id')
            client_secret = client_info.get('client_secret')
            token_uri = client_info.get('token_uri', token_uri)

        creds = Credentials(
            token=token_data.get('token'),
            refresh_token=token_data.get('refresh_token'),
            token_uri=token_uri,
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes
        )

        # Auto-refresh if expired
        if creds.expired or not creds.valid:
            print(f"🔄 Refreshing Gmail token for {account_email}...", flush=True)
            creds.refresh(Request())
            print(f"✅ Gmail token refreshed for {account_email}", flush=True)

            # Note: On Railway, we can't save back to env vars automatically
            # The refreshed token is valid for this session
            # Could persist to database if needed

        return creds, None

    except Exception as e:
        print(f"❌ Gmail credential error for {account_email}: {e}", flush=True)
        return None, str(e)


def get_gmail_service(account_email: str):
    """
    Get an authenticated Gmail API service for an account.
    Automatically refreshes tokens if expired.
    """
    creds, error = get_gmail_credentials_with_autorefresh(account_email)
    if error:
        return None, error

    try:
        from googleapiclient.discovery import build
        service = build('gmail', 'v1', credentials=creds)
        return service, None
    except Exception as e:
        return None, str(e)


def get_oauth_credentials():
    """Load OAuth credentials from file or environment"""
    import json
    from pathlib import Path

    # Try environment variable first (for Railway)
    creds_json = os.environ.get('GOOGLE_OAUTH_CREDENTIALS')
    if creds_json:
        try:
            parsed = json.loads(creds_json)
            print(f"✅ Loaded OAuth credentials from env var (type: {'web' if 'web' in parsed else 'installed'})", flush=True)
            return parsed
        except Exception as e:
            print(f"❌ Failed to parse GOOGLE_OAUTH_CREDENTIALS: {e}", flush=True)

    # Fall back to file
    creds_paths = [
        Path('config/credentials.json'),
        Path('data/credentials.json'),
        Path('../Task/receipt-system/config/credentials.json'),
    ]

    for path in creds_paths:
        if path.exists():
            with open(path, 'r') as f:
                return json.load(f)

    return None


def get_oauth_redirect_uri():
    """Get the appropriate redirect URI based on environment"""
    # Check for Railway
    railway_url = os.environ.get('RAILWAY_PUBLIC_DOMAIN')
    if railway_url:
        return f"https://{railway_url}/api/gmail/oauth-callback"

    # Check for custom domain
    custom_domain = os.environ.get('APP_DOMAIN')
    if custom_domain:
        return f"https://{custom_domain}/api/gmail/oauth-callback"

    # Default to localhost for development
    return "http://localhost:10000/api/gmail/oauth-callback"


@app.route("/api/gmail/authorize/<account_email>", methods=["GET"])
def gmail_authorize(account_email):
    """
    Start Gmail OAuth authorization flow.
    Redirects user to Google's consent screen.
    Supports both login-based auth and admin_key authentication.
    """
    import secrets
    from urllib.parse import urlencode

    # Auth check: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return redirect(url_for('login', next=request.url))

    try:
        from datetime import datetime, timedelta
        print(f"📧 Gmail authorize request for: {account_email}", flush=True)

        if account_email not in GMAIL_ACCOUNTS:
            print(f"❌ Unknown account: {account_email}", flush=True)
            return jsonify({'ok': False, 'error': f'Unknown account: {account_email}'}), 404

        creds = get_oauth_credentials()
        if not creds:
            print(f"❌ OAuth credentials not configured", flush=True)
            return jsonify({'ok': False, 'error': 'OAuth credentials not configured'}), 500

        # Get client info (support both "installed" and "web" credential types)
        client_info = creds.get('web') or creds.get('installed')
        if not client_info:
            print(f"❌ Invalid credentials format: {list(creds.keys())}", flush=True)
            return jsonify({'ok': False, 'error': 'Invalid credentials format'}), 500

        print(f"✅ Got client_info with client_id: {client_info.get('client_id', 'N/A')[:20]}...", flush=True)

        # Generate state for CSRF protection
        # Embed account_email in state for multi-worker support (Railway runs 2 gunicorn workers)
        # State format: base64(account_email:timestamp:random)
        import base64
        timestamp = datetime.now().isoformat()
        random_part = secrets.token_urlsafe(16)
        state_data = f"{account_email}:{timestamp}:{random_part}"
        state = base64.urlsafe_b64encode(state_data.encode('utf-8')).decode('utf-8').rstrip('=')

        # Also store in memory (for same-worker requests)
        _oauth_states[state] = {
            'account_email': account_email,
            'created_at': timestamp
        }

        # Clean up old states (older than 10 minutes)
        cutoff = datetime.now() - timedelta(minutes=10)
        for s in list(_oauth_states.keys()):
            try:
                created = datetime.fromisoformat(_oauth_states[s]['created_at'])
                if created < cutoff:
                    del _oauth_states[s]
            except:
                del _oauth_states[s]

        # Build authorization URL
        redirect_uri = get_oauth_redirect_uri()
        auth_params = {
            'client_id': client_info['client_id'],
            'redirect_uri': redirect_uri,
            'response_type': 'code',
            'scope': ' '.join(GMAIL_SCOPES),
            'access_type': 'offline',
            'prompt': 'consent',  # Force consent to get refresh token
            'state': state,
            'login_hint': account_email,  # Pre-fill email
        }

        auth_url = f"https://accounts.google.com/o/oauth2/auth?{urlencode(auth_params)}"
        print(f"✅ Redirecting to Google OAuth: {auth_url[:80]}...", flush=True)

        # Check if this is an AJAX request or direct navigation
        if request.headers.get('Accept', '').startswith('application/json'):
            return jsonify({
                'ok': True,
                'auth_url': auth_url,
                'redirect_uri': redirect_uri,
                'state': state
            })

        # Direct navigation - redirect to Google
        return redirect(auth_url)

    except Exception as e:
        print(f"❌ Gmail authorize error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': f'Server error: {str(e)}'}), 500


@app.route("/api/gmail/oauth-callback", methods=["GET"])
def gmail_oauth_callback():
    """
    Handle OAuth callback from Google.
    Exchanges authorization code for tokens.
    """
    import json
    import requests
    from pathlib import Path
    from datetime import datetime, timedelta

    error = request.args.get('error')
    if error:
        error_desc = request.args.get('error_description', 'Unknown error')
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Gmail Authorization Failed</title>
            <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
            h1{color:#ef4444}button{background:#00ff88;color:#000;border:none;padding:12px 24px;border-radius:6px;cursor:pointer;margin-top:20px}</style>
            </head>
            <body><div class="card"><h1>Authorization Failed</h1><p>{{ error }}: {{ desc }}</p>
            <button onclick="window.close()">Close</button></div></body></html>
        ''', error=error, desc=error_desc)

    code = request.args.get('code')
    state = request.args.get('state')

    if not code or not state:
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Invalid Request</title>
            <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
            h1{color:#ef4444}</style>
            </head>
            <body><div class="card"><h1>Invalid Request</h1><p>Missing authorization code or state</p></div></body></html>
        '''), 400

    # Validate state - decode it to get account email
    # State format: base64(account_email:timestamp:random)
    import base64
    try:
        # Try to get from memory first (same worker)
        if state in _oauth_states:
            state_data = _oauth_states.pop(state)
            account_email = state_data['account_email']
            print(f"✅ State validated from memory for: {account_email}", flush=True)
        else:
            # Decode state to extract account email (for multi-worker support)
            # Add padding if needed for base64 decode
            padding = 4 - len(state) % 4
            if padding != 4:
                state_padded = state + '=' * padding
            else:
                state_padded = state
            decoded = base64.urlsafe_b64decode(state_padded).decode('utf-8')
            parts = decoded.split(':', 2)
            if len(parts) >= 2:
                account_email = parts[0]
                timestamp_str = parts[1] if len(parts) > 1 else None

                # Validate it's a known account
                if account_email not in GMAIL_ACCOUNTS:
                    raise ValueError(f"Unknown account in state: {account_email}")

                # Validate timestamp isn't too old (10 minutes)
                if timestamp_str:
                    state_time = datetime.fromisoformat(timestamp_str)
                    if datetime.now() - state_time > timedelta(minutes=10):
                        raise ValueError("State expired")

                print(f"✅ State decoded for multi-worker support: {account_email}", flush=True)
            else:
                raise ValueError("Invalid state format")
    except Exception as e:
        print(f"❌ State validation failed: {e}", flush=True)
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Invalid State</title>
            <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
            h1{color:#ef4444}</style>
            </head>
            <body><div class="card"><h1>Invalid State</h1><p>Authorization request expired or invalid. Please try again.</p></div></body></html>
        '''), 400

    # Get credentials
    creds = get_oauth_credentials()
    if not creds:
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Configuration Error</title>
            <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
            h1{color:#ef4444}</style>
            </head>
            <body><div class="card"><h1>Configuration Error</h1><p>OAuth credentials not found</p></div></body></html>
        '''), 500

    client_info = creds.get('web') or creds.get('installed')

    # Exchange code for tokens
    try:
        token_response = requests.post(
            'https://oauth2.googleapis.com/token',
            data={
                'code': code,
                'client_id': client_info['client_id'],
                'client_secret': client_info['client_secret'],
                'redirect_uri': get_oauth_redirect_uri(),
                'grant_type': 'authorization_code',
            },
            timeout=30
        )

        if not token_response.ok:
            error_data = token_response.json()
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head><title>Token Exchange Failed</title>
                <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
                .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
                h1{color:#ef4444}</style>
                </head>
                <body><div class="card"><h1>Token Exchange Failed</h1><p>{{ error }}</p></div></body></html>
            ''', error=error_data.get('error_description', 'Unknown error')), 400

        token_data = token_response.json()

        # Add expiry timestamp
        if 'expires_in' in token_data:
            expiry = datetime.now() + timedelta(seconds=token_data['expires_in'])
            token_data['expiry'] = expiry.isoformat()

        # Save token to file
        account_info = GMAIL_ACCOUNTS.get(account_email, {})
        token_file = account_info.get('token_file', f'tokens_{account_email.replace("@", "_").replace(".", "_")}.json')

        # Try multiple token directories
        token_dirs = [
            Path('receipt-system/gmail_tokens'),
            Path('../Task/receipt-system/gmail_tokens'),
            Path('gmail_tokens'),
        ]

        saved = False
        for token_dir in token_dirs:
            try:
                token_dir.mkdir(parents=True, exist_ok=True)
                token_path = token_dir / token_file
                with open(token_path, 'w') as f:
                    json.dump(token_data, f, indent=2)
                print(f"✅ Token saved to {token_path}", flush=True)
                saved = True
                break
            except Exception as e:
                print(f"⚠️ Could not save to {token_dir}: {e}", flush=True)

        # Generate env var key for Railway persistence
        env_key = f"GMAIL_TOKEN_{account_email.replace('@', '_').replace('.', '_').upper()}"
        token_json = json.dumps(token_data)

        if not saved:
            print(f"⚠️ Could not save token to file. Set {env_key} environment variable with token JSON", flush=True)
        else:
            print(f"✅ Token saved to file. For Railway persistence, also set {env_key} env var", flush=True)

        account_name = account_info.get('name', account_email)

        # On Railway, show the token so user can set env var for persistence
        is_railway = os.environ.get('RAILWAY_PUBLIC_DOMAIN') is not None
        if is_railway:
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head><title>Gmail Connected!</title>
                <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;min-height:100vh;margin:0;padding:20px;box-sizing:border-box}
                .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:600px;width:100%}
                h1{color:#00ff88}button{background:#00ff88;color:#000;border:none;padding:12px 24px;border-radius:6px;cursor:pointer;margin-top:10px;font-weight:600}
                .token-box{background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:10px;margin:15px 0;text-align:left;font-family:monospace;font-size:11px;word-break:break-all;max-height:150px;overflow-y:auto}
                .env-key{color:#58a6ff;font-weight:bold}
                .copy-btn{background:#238636;margin-left:10px}</style>
                </head>
                <body><div class="card">
                <h1>✓ Gmail Connected!</h1>
                <p><strong>{{ name }}</strong> ({{ email }}) has been successfully authorized.</p>
                <p style="color:#fbbf24;font-size:14px">⚠️ <strong>Railway Note:</strong> To persist this token across deployments, set this environment variable:</p>
                <p class="env-key">{{ env_key }}</p>
                <div class="token-box" id="token">{{ token }}</div>
                <button onclick="copyToken()">📋 Copy Token</button>
                <button class="copy-btn" onclick="window.opener && window.opener.checkGmailStatus && window.opener.checkGmailStatus(); window.close();">Close Window</button>
                <script>function copyToken(){navigator.clipboard.writeText(document.getElementById('token').innerText);alert('Token copied! Set it as '+{{ env_key|tojson }}+' in Railway variables.');}</script>
                </div></body></html>
            ''', name=account_name, email=account_email, env_key=env_key, token=token_json)
        else:
            return render_template_string('''
                <!DOCTYPE html>
                <html>
                <head><title>Gmail Connected!</title>
                <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
                .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
                h1{color:#00ff88}button{background:#00ff88;color:#000;border:none;padding:12px 24px;border-radius:6px;cursor:pointer;margin-top:20px;font-weight:600}</style>
                </head>
                <body><div class="card">
                <h1>✓ Gmail Connected!</h1>
                <p><strong>{{ name }}</strong> ({{ email }}) has been successfully authorized.</p>
                <p style="color:#888;font-size:14px">You can now close this window.</p>
                <button onclick="window.opener && window.opener.checkGmailStatus && window.opener.checkGmailStatus(); window.close();">Close Window</button>
                </div></body></html>
            ''', name=account_name, email=account_email)

    except Exception as e:
        print(f"❌ OAuth callback error: {e}", flush=True)
        return render_template_string('''
            <!DOCTYPE html>
            <html>
            <head><title>Error</title>
            <style>body{font-family:system-ui;background:#1a1a2e;color:#fff;display:flex;justify-content:center;align-items:center;height:100vh;margin:0}
            .card{background:#16213e;padding:40px;border-radius:12px;text-align:center;max-width:400px}
            h1{color:#ef4444}</style>
            </head>
            <body><div class="card"><h1>Error</h1><p>{{ error }}</p></div></body></html>
        ''', error=str(e)), 500


@app.route("/api/gmail/disconnect/<account_email>", methods=["POST"])
@login_required
def gmail_disconnect(account_email):
    """Remove Gmail authorization for an account"""
    from pathlib import Path

    if account_email not in GMAIL_ACCOUNTS:
        return jsonify({'ok': False, 'error': f'Unknown account: {account_email}'}), 404

    account_info = GMAIL_ACCOUNTS[account_email]
    token_file = account_info['token_file']

    # Try to delete from multiple locations
    token_dirs = [
        Path('receipt-system/gmail_tokens'),
        Path('../Task/receipt-system/gmail_tokens'),
        Path('gmail_tokens'),
    ]

    deleted = False
    for token_dir in token_dirs:
        token_path = token_dir / token_file
        if token_path.exists():
            try:
                token_path.unlink()
                print(f"✅ Deleted token: {token_path}", flush=True)
                deleted = True
            except Exception as e:
                print(f"⚠️ Could not delete {token_path}: {e}", flush=True)

    return jsonify({
        'ok': True,
        'deleted': deleted,
        'message': f'Disconnected {account_email}' if deleted else f'No token found for {account_email}'
    })


# =============================================================================
# MERCHANT INTELLIGENCE PROCESSING ENDPOINT
# =============================================================================

@app.route("/process_mi", methods=["POST"])
def process_mi():
    """
    Process transactions through Merchant Intelligence
    Body: {"_index": int} for single transaction, or {"all": true} for all
    Returns: {"ok": bool, "processed": int, "message": str}
    """
    global df
    ensure_df()

    data = request.get_json(force=True) or {}

    try:
        # Process all transactions
        if data.get("all"):
            if process_all_mi:
                count = process_all_mi()
                if USE_DATABASE and db:
                    df = db.get_all_transactions()
                return jsonify({
                    "ok": True,
                    "processed": count,
                    "message": f"✅ Processed {count} transactions through Merchant Intelligence"
                })
            else:
                return jsonify({"ok": False, "message": "MI processing not available"}), 503

        # Process single transaction
        if "_index" in data:
            idx = int(data["_index"])

            if USE_DATABASE and db:
                df = db.get_all_transactions()

            mask = df["_index"] == idx
            if not mask.any():
                abort(404, f"_index {idx} not found")

            row = df[mask].iloc[0].to_dict()

            if process_transaction_mi:
                mi_result = process_transaction_mi(row)

                # Update database
                update_data = {
                    'mi_merchant': mi_result.get('mi_merchant', ''),
                    'mi_category': mi_result.get('mi_category', ''),
                    'mi_description': mi_result.get('mi_description', ''),
                    'mi_confidence': mi_result.get('mi_confidence', 0),
                    'mi_is_subscription': mi_result.get('mi_is_subscription', 0),
                    'mi_subscription_name': mi_result.get('mi_subscription_name', ''),
                    'mi_processed_at': mi_result.get('mi_processed_at', ''),
                }

                if USE_DATABASE and db:
                    db.update_transaction(idx, update_data)
                    df = db.get_all_transactions()

                return jsonify({
                    "ok": True,
                    "processed": 1,
                    "result": mi_result,
                    "message": f"✅ Processed transaction through MI: {mi_result.get('mi_merchant', '')}"
                })
            else:
                return jsonify({"ok": False, "message": "MI processing not available"}), 503

        return jsonify({"ok": False, "message": "Missing _index or all parameter"}), 400

    except Exception as e:
        return jsonify({"ok": False, "message": f"MI processing error: {str(e)}"}), 500


def generate_receipt_filename(merchant: str, date: str, amount: float, ext: str = ".jpg") -> str:
    """
    Generate standardized receipt filename: merchant_date_amount.ext
    Example: the_ups_store_2025-07-25_57_24.jpg
    """
    import re
    # Clean merchant name - lowercase, replace spaces/special chars with underscore
    merchant_clean = re.sub(r'[^a-z0-9]+', '_', merchant.lower().strip())
    merchant_clean = merchant_clean.strip('_')[:30]  # Limit length

    # Format amount - replace decimal with underscore
    amount_str = f"{amount:.2f}".replace('.', '_')

    # Ensure date is in correct format
    date_clean = date or datetime.now().strftime("%Y-%m-%d")

    return f"{merchant_clean}_{date_clean}_{amount_str}{ext}"


@app.route("/api/ocr/process", methods=["POST"])
@login_required
def api_ocr_process():
    """
    OCR endpoint using Gemini Vision AI.
    Upload a receipt image, OCR it, save with proper naming, and return data.

    Query params:
        save=true - Save the file with proper naming (default: false for preview)

    Returns: {
        "success": bool,
        "merchant": str,
        "date": str (YYYY-MM-DD),
        "total": float,
        "confidence": float (0-1),
        "engines_used": ["Gemini Vision"],
        "filename": str (if saved),
        "error": str (if failed)
    }
    """
    file = request.files.get("file")
    if not file:
        return jsonify({"success": False, "error": "No file uploaded"})

    save_file = request.args.get("save", "false").lower() == "true"

    # Save temp file
    RECEIPT_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    original_name = os.path.basename(file.filename or "receipt.jpg")
    _, ext = os.path.splitext(original_name)
    if not ext:
        ext = ".jpg"
    # Convert HEIC to JPG extension (we'll convert the actual file too)
    if ext.lower() == ".heic":
        ext = ".jpg"

    temp_filename = f"temp_ocr_{timestamp}_{original_name}"
    temp_path = RECEIPT_DIR / temp_filename

    try:
        file.save(temp_path)
        print(f"🔍 Gemini OCR processing: {temp_filename}", flush=True)

        # Convert HEIC to JPG if needed
        if original_name.lower().endswith('.heic'):
            try:
                from PIL import Image
                import pillow_heif
                pillow_heif.register_heif_opener()
                img = Image.open(temp_path)
                jpg_temp_path = temp_path.with_suffix('.jpg')
                img.convert('RGB').save(jpg_temp_path, 'JPEG', quality=95)
                temp_path.unlink(missing_ok=True)
                temp_path = jpg_temp_path
                print(f"   📷 Converted HEIC to JPG", flush=True)
            except Exception as e:
                print(f"   ⚠️ HEIC conversion failed: {e}", flush=True)

        # Use Gemini OCR
        ocr_data = gemini_ocr_extract(temp_path)

        if ocr_data.get("error"):
            temp_path.unlink(missing_ok=True)
            return jsonify({
                "success": False,
                "error": ocr_data["error"]
            })

        merchant = ocr_data.get("merchant") or "unknown"
        date = ocr_data.get("date") or datetime.now().strftime("%Y-%m-%d")
        total = ocr_data.get("total") or 0.0
        confidence = ocr_data.get("confidence", 0)

        print(f"   ✅ Extracted: {merchant} - ${total} on {date}", flush=True)

        # Generate proper filename and save
        final_filename = generate_receipt_filename(merchant, date, total, ext)
        final_path = RECEIPT_DIR / final_filename

        # Handle duplicates - append number if file exists
        counter = 1
        while final_path.exists():
            base, ext_part = os.path.splitext(final_filename)
            final_filename = f"{base}_{counter}{ext_part}"
            final_path = RECEIPT_DIR / final_filename
            counter += 1

        # Always save the file with proper naming (not just preview)
        temp_path.rename(final_path)
        print(f"   💾 Saved as: {final_filename}", flush=True)

        # Upload to R2 cloud storage
        r2_url = None
        if R2_ENABLED and upload_to_r2:
            try:
                success, result = upload_to_r2(final_path)
                if success:
                    r2_url = result
                    print(f"   ☁️ Uploaded to R2: {r2_url}", flush=True)
                else:
                    print(f"   ⚠️ R2 upload failed: {result}", flush=True)
            except Exception as e:
                print(f"   ⚠️ R2 upload error: {e}", flush=True)

        return jsonify({
            "success": True,
            "merchant": merchant,
            "date": date,
            "total": total,
            "confidence": (confidence / 100.0),  # Convert to 0-1 scale
            "engines_used": ["Gemini Vision"],
            "filename": final_filename,
            "receipt_url": r2_url,  # Standardized field name
            "r2_url": r2_url  # Keep for backwards compatibility
        })

    except Exception as e:
        temp_path.unlink(missing_ok=True)
        print(f"❌ OCR error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        })


@app.route("/process_mi_ocr", methods=["POST"])
def process_mi_ocr():
    """
    Process a single transaction through Merchant Intelligence WITH Donut OCR.
    This is the 'A' hotkey endpoint - does everything in one call.

    Body: {"_index": int} or {"id": int}
    Returns: {"ok": bool, "result": {...}, "message": str}
    """
    global df
    ensure_df()

    data = request.get_json(force=True) or {}

    try:
        # Get transaction ID
        idx = data.get("_index") or data.get("id")
        if not idx:
            return jsonify({"ok": False, "message": "Missing _index or id parameter"}), 400

        idx = int(idx)

        # Import the OCR processing function
        try:
            import importlib.util
            from pathlib import Path

            scripts_mi_path = Path(__file__).parent / "scripts" / "merchant_intelligence.py"
            spec = importlib.util.spec_from_file_location("scripts_merchant_intelligence", scripts_mi_path)
            scripts_mi = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(scripts_mi)

            # Process with OCR
            result = scripts_mi.process_single_with_ocr(idx)

            if "error" in result:
                return jsonify({"ok": False, "message": result["error"]}), 404

            # Reload dataframe to get updated data
            if USE_DATABASE and db:
                df = db.get_all_transactions()

            return jsonify({
                "ok": True,
                "result": result,
                "used_ocr": result.get("used_ocr", False),
                "message": f"✅ Processed with {'Donut OCR' if result.get('used_ocr') else 'patterns'}: {result.get('mi_merchant', '')} ({result.get('mi_confidence', 0):.0%})"
            })

        except Exception as e:
            return jsonify({"ok": False, "message": f"OCR processing error: {str(e)}"}), 500

    except Exception as e:
        return jsonify({"ok": False, "message": f"Error: {str(e)}"}), 500


@app.route("/process_mi_batch", methods=["POST"])
def process_mi_batch():
    """
    Batch process all transactions with smart skip.
    Only processes rows with low confidence or no MI data.
    Uses Donut OCR on matched receipts.

    Body: {"smart_skip": bool, "use_receipts": bool}
    Returns: {"ok": bool, "processed": int, "message": str}
    """
    global df
    ensure_df()

    data = request.get_json(force=True) or {}
    smart_skip = data.get("smart_skip", True)
    use_receipts = data.get("use_receipts", True)

    try:
        import importlib.util
        from pathlib import Path

        scripts_mi_path = Path(__file__).parent / "scripts" / "merchant_intelligence.py"
        spec = importlib.util.spec_from_file_location("scripts_merchant_intelligence", scripts_mi_path)
        scripts_mi = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(scripts_mi)

        # Process all with smart skip
        count = scripts_mi.process_all_transactions(smart_skip=smart_skip, use_receipts=use_receipts)

        # Reload dataframe
        if USE_DATABASE and db:
            df = db.get_all_transactions()

        return jsonify({
            "ok": True,
            "processed": count,
            "message": f"✅ Batch processed {count} transactions (smart_skip={smart_skip}, use_receipts={use_receipts})"
        })

    except Exception as e:
        return jsonify({"ok": False, "message": f"Batch processing error: {str(e)}"}), 500


# =============================================================================
# SMART SEARCH WITH LEARNING
# =============================================================================

def init_receipt_sources_table():
    """Initialize receipt_sources table for tracking where receipts are found"""
    import sqlite3

    # Only run for SQLite databases (MySQL handles its own schema)
    if not USE_DATABASE or not db:
        return

    # Skip if using MySQL - it initializes its own schema
    if not hasattr(db, 'db_path'):
        return

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    # Create table to track which source (gmail account, imessage, local) has receipts for each merchant
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS receipt_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            merchant_normalized TEXT NOT NULL,
            source_type TEXT NOT NULL,  -- 'gmail', 'imessage', 'local'
            source_detail TEXT,  -- email address if gmail, 'imessage' if imessage, null if local
            success_count INTEGER DEFAULT 1,
            last_found_date TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(merchant_normalized, source_type, source_detail)
        )
    ''')

    cursor.execute('CREATE INDEX IF NOT EXISTS idx_receipt_sources_merchant ON receipt_sources(merchant_normalized)')

    conn.commit()
    return_db_connection(conn)

    print("✅ Receipt sources tracking table initialized")

# Initialize on startup
init_receipt_sources_table()

def record_receipt_source(merchant, source_type, source_detail=None):
    """Record that a receipt was found from a specific source"""
    import sqlite3
    from datetime import datetime

    if not USE_DATABASE or not db:
        return

    # Skip if using MySQL
    if not hasattr(db, 'db_path'):
        return

    # Normalize merchant name
    from merchant_intelligence import normalize_merchant
    merchant_norm = normalize_merchant(merchant)

    conn = sqlite3.connect(db.db_path)
    cursor = conn.cursor()

    # Insert or update success count
    cursor.execute('''
        INSERT INTO receipt_sources (merchant_normalized, source_type, source_detail, success_count, last_found_date)
        VALUES (?, ?, ?, 1, ?)
        ON CONFLICT(merchant_normalized, source_type, source_detail)
        DO UPDATE SET
            success_count = success_count + 1,
            last_found_date = ?
    ''', (merchant_norm, source_type, source_detail, datetime.now().isoformat(), datetime.now().isoformat()))

    conn.commit()
    return_db_connection(conn)

    print(f"   📊 Recorded: {merchant_norm} → {source_type} ({source_detail or 'N/A'})")

def get_best_sources_for_merchant(merchant):
    """Get likely sources for a merchant based on history"""
    import sqlite3

    if not USE_DATABASE or not db:
        return []

    # Skip if using MySQL
    if not hasattr(db, 'db_path'):
        return []

    from merchant_intelligence import normalize_merchant
    merchant_norm = normalize_merchant(merchant)

    conn = sqlite3.connect(db.db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # Get sources ordered by success count
    cursor.execute('''
        SELECT source_type, source_detail, success_count, last_found_date
        FROM receipt_sources
        WHERE merchant_normalized = ?
        ORDER BY success_count DESC, last_found_date DESC
    ''', (merchant_norm,))

    results = cursor.fetchall()
    return_db_connection(conn)

    return [dict(row) for row in results]

@app.route('/smart_search_receipt', methods=['POST'])
def smart_search_receipt():
    """Smart search that learns which sources work for which merchants"""
    try:
        data = request.json
        row_index = data.get('_index')
        merchant = data.get('merchant', '')
        amount = data.get('amount', 0)
        date = data.get('date', '')
        requested_source = data.get('source', 'auto')  # 'auto', 'gmail', 'imessage'

        print(f"🔍 Smart Search: {merchant} ${amount} on {date} (source: {requested_source})", flush=True)

        # Check historical patterns
        if requested_source == 'auto':
            best_sources = get_best_sources_for_merchant(merchant)
            if best_sources:
                print(f"   📊 Historical data found for {merchant}:")
                for src in best_sources[:3]:
                    print(f"      - {src['source_type']} ({src['source_detail'] or 'N/A'}): {src['success_count']} successes")

        # Try the requested source (or auto-determine)
        if requested_source in ['auto', 'gmail']:
            # Try Gmail
            try:
                from gmail_receipt_search import load_gmail_service, search_gmail_for_receipt, GMAIL_ACCOUNTS

                found_count = 0
                found_account = None

                for account_email, token_file in GMAIL_ACCOUNTS:
                    service = load_gmail_service(token_file)
                    if not service:
                        continue

                    count = search_gmail_for_receipt(service, merchant, amount, date, account_email)
                    if count > 0:
                        found_count = count
                        found_account = account_email

                        # Record this success for future learning
                        record_receipt_source(merchant, 'gmail', account_email)

                        print(f"   ✅ Found {count} potential receipts in {account_email}", flush=True)

                        db.update_row(row_index, {
                            'Notes': f'Found {count} emails in {account_email} - download manually',
                            'Review Status': 'needs review'
                        })

                        return jsonify({
                            'ok': True,
                            'message': f'Found {count} potential receipts in Gmail',
                            'result': {
                                'found': True,
                                'receipt_file': None,
                                'source': f'Gmail ({account_email})',
                                'notes': f'Found {count} emails'
                            }
                        })

            except Exception as gmail_error:
                print(f"   ⚠️  Gmail search error: {gmail_error}", flush=True)

        if requested_source in ['auto', 'imessage']:
            # Try iMessage
            try:
                import sqlite3
                from pathlib import Path

                imessage_db = Path.home() / "Library" / "Messages" / "chat.db"

                if imessage_db.exists():
                    conn = sqlite3.connect(str(imessage_db))
                    cursor = conn.cursor()

                    query = """
                        SELECT
                            a.filename,
                            a.mime_type,
                            datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date
                        FROM attachment a
                        JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                        JOIN message m ON maj.message_id = m.ROWID
                        WHERE (a.mime_type LIKE 'image/%' OR a.mime_type LIKE 'application/pdf')
                        ORDER BY m.date DESC
                        LIMIT 10
                    """

                    cursor.execute(query)
                    results = cursor.fetchall()
                    return_db_connection(conn)

                    if results:
                        # Record this success
                        record_receipt_source(merchant, 'imessage', 'imessage')

                        print(f"   📱 Found {len(results)} recent attachments in iMessage", flush=True)

                        db.update_row(row_index, {
                            'Notes': f'Found {len(results)} attachments in iMessage - check Messages app',
                            'Review Status': 'needs review'
                        })

                        return jsonify({
                            'ok': True,
                            'message': f'Found {len(results)} potential receipts in iMessage',
                            'result': {
                                'found': True,
                                'receipt_file': None,
                                'source': 'iMessage',
                                'notes': f'Found {len(results)} attachments'
                            }
                        })

            except Exception as imessage_error:
                print(f"   ⚠️  iMessage search error: {imessage_error}", flush=True)

        # Not found
        print(f"   ⊘ Receipt not found", flush=True)
        return jsonify({
            'ok': False,
            'message': 'Receipt not found in any source',
            'result': {
                'found': False
            }
        })

    except Exception as e:
        print(f"❌ Smart search error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            'ok': False,
            'message': f'Smart search error: {str(e)}'
        }), 500


# =============================================================================
# GMAIL & IMESSAGE RECEIPT SEARCH
# =============================================================================

@app.route('/search_gmail_receipt', methods=['POST'])
def search_gmail_receipt():
    """Search Gmail for a single missing receipt"""
    try:
        data = request.json
        row_index = data.get('_index')
        merchant = data.get('merchant', '')
        amount = data.get('amount', 0)
        date = data.get('date', '')

        print(f"🔍 Searching Gmail for: {merchant} ${amount} on {date}", flush=True)

        # Import Gmail search functionality
        try:
            from gmail_receipt_search import load_gmail_service, search_gmail_for_receipt, GMAIL_ACCOUNTS

            # Search across all configured Gmail accounts
            found_count = 0

            for account_email, token_file in GMAIL_ACCOUNTS:
                service = load_gmail_service(token_file)
                if not service:
                    continue

                # Search this account
                count = search_gmail_for_receipt(service, merchant, amount, date, account_email)
                found_count += count

                if count > 0:
                    # Found something! For now, just report success
                    # In a full implementation, we'd download the attachment
                    print(f"   ✅ Found {count} potential receipts in {account_email}", flush=True)

                    # For now, mark as found but note manual download needed
                    db.update_row(row_index, {
                        'Notes': f'Found {count} emails in {account_email} - download manually',
                        'Review Status': 'needs review'
                    })

                    return jsonify({
                        'ok': True,
                        'message': f'Found {count} potential receipts in Gmail ({account_email})',
                        'result': {
                            'receipt_file': None,  # Would download here
                            'notes': f'Found {count} emails in {account_email}'
                        }
                    })

            if found_count == 0:
                print(f"   ⊘ Receipt not found in Gmail", flush=True)
                return jsonify({
                    'ok': False,
                    'message': 'Receipt not found in Gmail'
                })

        except ImportError as ie:
            print(f"   ⚠️  Gmail search module not available: {ie}", flush=True)
            import traceback
            traceback.print_exc()
            return jsonify({
                'ok': False,
                'message': 'Gmail search not available - check module installation'
            }), 500

    except Exception as e:
        print(f"❌ Gmail search error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            'ok': False,
            'message': f'Gmail search error: {str(e)}'
        }), 500


@app.route('/search_imessage_receipt', methods=['POST'])
def search_imessage_receipt():
    """Search iMessage for a single missing receipt"""
    try:
        data = request.json
        row_index = data.get('_index')
        merchant = data.get('merchant', '')
        amount = data.get('amount', 0)
        date = data.get('date', '')

        print(f"🔍 Searching iMessage for: {merchant} ${amount} on {date}", flush=True)

        # Check if iMessage database exists
        import os
        from pathlib import Path

        imessage_db = Path.home() / "Library" / "Messages" / "chat.db"

        if not imessage_db.exists():
            print(f"   ⚠️  iMessage database not accessible", flush=True)
            return jsonify({
                'ok': False,
                'message': 'iMessage database not accessible (grant Full Disk Access in System Preferences)'
            })

        # Import iMessage search functionality
        try:
            import sqlite3

            # Search iMessage for attachments around this date
            conn = sqlite3.connect(str(imessage_db))
            cursor = conn.cursor()

            # Query for attachments
            # iMessage stores dates in a special format (seconds since 2001-01-01)
            query = """
                SELECT
                    a.filename,
                    a.mime_type,
                    datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date
                FROM attachment a
                JOIN message_attachment_join maj ON a.ROWID = maj.attachment_id
                JOIN message m ON maj.message_id = m.ROWID
                WHERE a.mime_type LIKE 'image/%' OR a.mime_type LIKE 'application/pdf'
                ORDER BY m.date DESC
                LIMIT 10
            """

            cursor.execute(query)
            results = cursor.fetchall()
            return_db_connection(conn)

            if results:
                print(f"   📱 Found {len(results)} recent attachments in iMessage", flush=True)

                # Add note about findings
                db.update_row(row_index, {
                    'Notes': f'Found {len(results)} attachments in iMessage - check Messages app',
                    'Review Status': 'needs review'
                })

                return jsonify({
                    'ok': True,
                    'message': f'Found {len(results)} potential receipts in iMessage',
                    'result': {
                        'receipt_file': None,  # Would copy/process here
                        'notes': f'Found {len(results)} attachments'
                    }
                })
            else:
                print(f"   ⊘ No attachments found in iMessage", flush=True)
                return jsonify({
                    'ok': False,
                    'message': 'No attachments found in iMessage'
                })

        except Exception as search_error:
            print(f"   ⚠️  iMessage search error: {search_error}", flush=True)
            import traceback
            traceback.print_exc()
            return jsonify({
                'ok': False,
                'message': f'iMessage search error: {str(search_error)}'
            }), 500

    except Exception as e:
        print(f"❌ iMessage search error: {e}", flush=True)
        import traceback
        traceback.print_exc()
        return jsonify({
            'ok': False,
            'message': f'iMessage search error: {str(e)}'
        }), 500


# =============================================================================
# RECEIPT REJECTION TRACKING (PERMANENT)
# =============================================================================

@app.route("/api/rejected-receipts", methods=["GET"])
@login_required
def get_rejected_receipts():
    """
    Get list of all rejected receipts (for debugging/admin view)

    Returns list of receipts that user has manually blocked from transactions
    """
    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': True,
                'count': 0,
                'rejected_receipts': []
            })

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT
                id,
                transaction_date,
                transaction_description,
                transaction_amount,
                receipt_path,
                rejected_at,
                reason
            FROM rejected_receipts
            ORDER BY rejected_at DESC
        ''')

        rejected = [dict(row) for row in cursor.fetchall()]
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'count': len(rejected),
            'rejected_receipts': rejected
        })

    except Exception as e:
        error_str = str(e).lower()
        # Table doesn't exist yet (handle both SQLite and MySQL)
        if "no such table" in error_str or "doesn't exist" in error_str:
            return jsonify({
                'ok': True,
                'count': 0,
                'rejected_receipts': []
            })
        print(f"❌ Error fetching rejected receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/rejected-receipts/<int:rejection_id>", methods=["DELETE"])
@login_required
def delete_rejection(rejection_id):
    """
    Remove a rejection (allow the receipt to be matched again)

    Use this if you accidentally rejected a receipt
    """
    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, 'DELETE FROM rejected_receipts WHERE id = ?', (rejection_id,))
        conn.commit()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Rejection {rejection_id} removed - receipt can now be matched again'
        })

    except Exception as e:
        print(f"❌ Error deleting rejection: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# RECEIPT LIBRARY - ALL RECEIPTS FROM ALL SOURCES
# =============================================================================

@app.route("/api/library/receipts", methods=["GET"])
def get_library_receipts():
    """
    Get ALL receipts from all sources for the receipt library.
    Combines: transactions with receipts, incoming receipts (accepted/pending).

    Query params:
    - source: filter by source ('all', 'gmail', 'scanner', 'manual', 'imessage')
    - search: search merchant names
    - date_from: start date (YYYY-MM-DD)
    - date_to: end date (YYYY-MM-DD)
    - amount_min: minimum amount
    - amount_max: maximum amount
    - sort: sort field ('date', 'amount', 'merchant')
    - order: sort order ('asc', 'desc')
    - limit: max results (default 500)
    - offset: pagination offset
    - has_image: 'true' (default) to only show receipts with images, 'false' to show all
    - include_incoming: 'true' (default) to include incoming receipts, 'false' for transactions only
    """
    # Auth: admin_key OR session login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        # Parse query params
        source = request.args.get('source', 'all')
        search = request.args.get('search', '').strip()
        date_from = request.args.get('date_from', '')
        date_to = request.args.get('date_to', '')
        amount_min = request.args.get('amount_min', '')
        amount_max = request.args.get('amount_max', '')
        sort_field = request.args.get('sort', 'date')
        sort_order = request.args.get('order', 'desc')
        limit = int(request.args.get('limit', 500))
        offset = int(request.args.get('offset', 0))
        has_image = request.args.get('has_image', 'true').lower() != 'false'
        include_incoming = request.args.get('include_incoming', 'true').lower() != 'false'
        # New status filters: 'all', 'matched', 'waiting', 'verified', 'needs_review', 'mismatch', 'unverified', 'has_ocr'
        verification_filter = request.args.get('verification', 'all')
        match_status = request.args.get('match_status', 'all')  # 'all', 'matched', 'waiting'

        conn, db_type = get_db_connection()
        all_receipts = []

        # 1. Get receipts from transactions table
        # Use SELECT * to handle varying schemas between SQLite and MySQL
        tx_query = '''
            SELECT *
            FROM transactions
            WHERE (receipt_url IS NOT NULL AND receipt_url != '')
               OR (receipt_file IS NOT NULL AND receipt_file != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
        '''
        cursor = db_execute(conn, db_type, tx_query, ())
        tx_rows = cursor.fetchall()

        for row in tx_rows:
            tx = dict(row)
            receipt_source = tx.get('source') or 'manual'
            if receipt_source == 'mobile_scanner' or receipt_source == 'mobile_scanner_pwa':
                receipt_source = 'scanner'

            # Use r2_url first, then receipt_url, then receipt_file
            receipt_image = tx.get('r2_url') or tx.get('receipt_url') or tx.get('receipt_file')

            # Handle both SQLite (merchant, amount, date) and MySQL (chase_description, chase_amount, chase_date)
            merchant = tx.get('chase_description') or tx.get('merchant') or tx.get('description') or 'Unknown'
            amount = tx.get('chase_amount') or tx.get('amount') or 0
            date_val = tx.get('chase_date') or tx.get('date') or ''

            # Determine verification status based on OCR data
            ocr_verified = tx.get('ocr_verified', False)
            ocr_confidence = float(tx.get('ocr_confidence') or 0)
            ocr_verification_status = tx.get('ocr_verification_status') or ''
            has_ocr = bool(tx.get('ocr_merchant') or tx.get('ocr_amount'))

            # Calculate match status: matched (has receipt linked to transaction)
            # verification_status: verified (OCR confirmed), mismatch, needs_review, unverified
            if ocr_verification_status:
                verification_status = ocr_verification_status.lower()
            elif ocr_verified:
                verification_status = 'verified'
            elif has_ocr and ocr_confidence >= 0.8:
                verification_status = 'verified'
            elif has_ocr:
                verification_status = 'needs_review'
            else:
                verification_status = 'unverified'

            receipt = {
                'id': f"tx_{tx.get('id') or tx.get('_index')}",
                'type': 'transaction',
                'transaction_id': tx.get('id') or tx.get('_index'),
                '_index': tx.get('_index'),  # MySQL uses _index for linking
                'merchant': merchant,
                'amount': float(amount or 0),
                'date': str(date_val),
                'receipt_url': receipt_image,
                'thumbnail': receipt_image,
                'source': receipt_source,
                'business_type': tx.get('business_type') or 'Personal',
                'notes': tx.get('notes') or '',
                'ai_notes': tx.get('ai_notes') or '',
                'status': 'matched',
                'verification_status': verification_status,
                'created_at': str(date_val),
                # OCR data
                'ocr_merchant': tx.get('ocr_merchant') or '',
                'ocr_amount': float(tx.get('ocr_amount') or 0) if tx.get('ocr_amount') else None,
                'ocr_date': str(tx.get('ocr_date') or ''),
                'ocr_confidence': ocr_confidence,
                'ocr_verified': ocr_verified,
                'has_ocr': has_ocr
            }
            all_receipts.append(receipt)

        # 2. Get incoming receipts (accepted and pending) - only if include_incoming is true
        if include_incoming:
            try:
                # Only get incoming receipts that have actual receipt files
                # Note: incoming_receipts table uses receipt_url and file_path, not receipt_file
                inc_query = '''
                    SELECT *
                    FROM incoming_receipts
                    WHERE status IN ('accepted', 'pending')
                    AND (
                        (receipt_url IS NOT NULL AND receipt_url != '')
                        OR (file_path IS NOT NULL AND file_path != '')
                    )
                '''
                cursor = db_execute(conn, db_type, inc_query, ())
                inc_rows = cursor.fetchall()

                for row in inc_rows:
                    inc = dict(row)
                    receipt_source = inc.get('source') or 'gmail'
                    if receipt_source == 'mobile_scanner' or receipt_source == 'mobile_scanner_pwa':
                        receipt_source = 'scanner'

                    # Get the actual receipt file URL
                    receipt_file = inc.get('receipt_file') or inc.get('receipt_url') or inc.get('file_path') or ''

                    # Skip if no actual file (extra safety check)
                    if has_image and not receipt_file:
                        continue

                    # For incoming receipts, use received_date (email date) as the authoritative date
                    raw_date = inc.get('received_date') or inc.get('receipt_date') or ''
                    receipt_date = parse_email_date(raw_date) or raw_date

                    # If linked to a transaction, update that transaction's date with correct email date
                    tx_id = inc.get('transaction_id') or inc.get('accepted_as_transaction_id') or inc.get('matched_transaction_id')
                    if tx_id:
                        # Find and update the linked transaction with the correct email date
                        found_tx = False
                        for r in all_receipts:
                            if r['type'] == 'transaction':
                                r_tx_id = r.get('transaction_id') or r.get('_index')
                                if r_tx_id == tx_id or r.get('id') == f"tx_{tx_id}":
                                    r['date'] = str(receipt_date)
                                    r['incoming_id'] = inc.get('id')
                                    found_tx = True
                                    break
                        if found_tx:
                            continue  # Skip duplicate

                    # Extract merchant intelligently
                    merchant = inc.get('merchant') or ''
                    if not merchant or merchant == 'Unknown':
                        # Try to get from sender
                        sender = inc.get('sender') or ''
                        if sender:
                            # Clean up sender name (remove email parts)
                            merchant = sender.split('<')[0].strip().strip('"')
                        if not merchant:
                            # Try subject line
                            subject = inc.get('subject') or ''
                            if 'receipt' in subject.lower():
                                # Extract merchant from subject like "Your receipt from Merchant"
                                import re
                                match = re.search(r'(?:receipt|order|payment).*?(?:from|for)\s+([^#\d]+)', subject, re.I)
                                if match:
                                    merchant = match.group(1).strip()

                    if not merchant:
                        merchant = 'Unknown'

                    # Determine verification status for incoming receipts
                    inc_ocr_verified = inc.get('ocr_verified', False)
                    inc_ocr_confidence = float(inc.get('ocr_confidence') or 0)
                    inc_ocr_status = inc.get('ocr_verification_status') or ''
                    inc_has_ocr = bool(inc.get('ocr_merchant') or inc.get('ocr_amount'))
                    inc_status = inc.get('status') or 'pending'

                    # Verification status for incoming receipts
                    if inc_ocr_status:
                        inc_verification = inc_ocr_status.lower()
                    elif inc_ocr_verified:
                        inc_verification = 'verified'
                    elif inc_has_ocr and inc_ocr_confidence >= 0.8:
                        inc_verification = 'verified'
                    elif inc_has_ocr:
                        inc_verification = 'needs_review'
                    elif inc_status == 'pending':
                        inc_verification = 'waiting'  # Waiting for transaction match
                    else:
                        inc_verification = 'unverified'

                    receipt = {
                        'id': f"inc_{inc.get('id')}",
                        'type': 'incoming',
                        'incoming_id': inc.get('id'),
                        'merchant': merchant,
                        'amount': float(inc.get('amount') or 0),
                        'date': str(receipt_date),
                        'receipt_url': receipt_file,
                        'thumbnail': receipt_file,
                        'source': receipt_source,
                        'business_type': inc.get('business_type') or 'Personal',
                        'notes': inc.get('subject') or '',
                        'ai_notes': inc.get('ai_notes') or '',
                        'status': inc_status,
                        'verification_status': inc_verification,
                        'confidence': inc.get('confidence_score') or 0,
                        'sender': inc.get('sender') or '',
                        'created_at': str(inc.get('created_at') or receipt_date or ''),
                        # OCR data
                        'ocr_merchant': inc.get('ocr_merchant') or '',
                        'ocr_amount': float(inc.get('ocr_amount') or 0) if inc.get('ocr_amount') else None,
                        'ocr_date': str(inc.get('ocr_date') or ''),
                        'ocr_confidence': inc_ocr_confidence,
                        'ocr_verified': inc_ocr_verified,
                        'has_ocr': inc_has_ocr
                    }
                    all_receipts.append(receipt)
            except Exception as e:
                print(f"Note: Could not fetch incoming_receipts: {e}")

        return_db_connection(conn)

        # Apply filters

        # Filter to only receipts with VALID images (not placeholders or truncated URLs)
        def is_valid_receipt_url(url):
            if not url:
                return False
            # Filter out placeholder URLs
            if 'NO_RECEIPT' in url.upper():
                return False
            # Filter out truncated URLs (ends with /receipts without filename)
            if url.endswith('/receipts') or url.endswith('/receipts/'):
                return False
            # Filter out URLs with special unicode characters that often cause 404s
            # %E2%80%AF is narrow no-break space, common in macOS screenshot names
            if '%E2%80%AF' in url or '%E2%80' in url:
                return False
            # Filter out Screenshot filenames (often broken uploads)
            if 'Screenshot%20' in url or 'Screenshot ' in url:
                return False
            # Must have a file extension or be a valid path
            return True

        if has_image:
            all_receipts = [r for r in all_receipts
                          if is_valid_receipt_url(r.get('receipt_url')) or is_valid_receipt_url(r.get('thumbnail'))]

        # Filter out non-receipt transactions (interest charges, fees, etc.)
        non_receipt_keywords = ['INTEREST CHARGE', 'LATE FEE', 'ANNUAL FEE', 'FINANCE CHARGE', 'FOREIGN TRANSACTION FEE']
        all_receipts = [r for r in all_receipts
                       if not any(kw in (r.get('merchant') or '').upper() for kw in non_receipt_keywords)]

        # Filter out Unknown/blank merchants with zero amount
        all_receipts = [r for r in all_receipts
                       if not ((r.get('merchant') == 'Unknown' or not r.get('merchant')) and r.get('amount', 0) == 0)]

        if source != 'all':
            all_receipts = [r for r in all_receipts if r['source'] == source]

        if search:
            search_lower = search.lower()
            all_receipts = [r for r in all_receipts
                          if search_lower in (r.get('merchant') or '').lower()
                          or search_lower in (r.get('notes') or '').lower()
                          or search_lower in (r.get('ai_notes') or '').lower()]

        if date_from:
            all_receipts = [r for r in all_receipts if r.get('date', '') >= date_from]

        if date_to:
            all_receipts = [r for r in all_receipts if r.get('date', '') <= date_to]

        if amount_min:
            try:
                min_val = float(amount_min)
                all_receipts = [r for r in all_receipts if abs(r.get('amount', 0)) >= min_val]
            except: pass

        if amount_max:
            try:
                max_val = float(amount_max)
                all_receipts = [r for r in all_receipts if abs(r.get('amount', 0)) <= max_val]
            except: pass

        # Filter by match status (matched to transaction vs waiting)
        if match_status == 'matched':
            all_receipts = [r for r in all_receipts if r.get('status') == 'matched' or r.get('type') == 'transaction']
        elif match_status == 'waiting':
            all_receipts = [r for r in all_receipts if r.get('status') == 'pending' or r.get('verification_status') == 'waiting']

        # Filter by verification status
        if verification_filter == 'verified':
            all_receipts = [r for r in all_receipts if r.get('verification_status') == 'verified']
        elif verification_filter == 'needs_review':
            all_receipts = [r for r in all_receipts if r.get('verification_status') == 'needs_review']
        elif verification_filter == 'mismatch':
            all_receipts = [r for r in all_receipts if r.get('verification_status') == 'mismatch']
        elif verification_filter == 'unverified':
            all_receipts = [r for r in all_receipts if r.get('verification_status') == 'unverified']
        elif verification_filter == 'has_ocr':
            all_receipts = [r for r in all_receipts if r.get('has_ocr')]

        # Sort
        reverse = sort_order == 'desc'
        if sort_field == 'date':
            all_receipts.sort(key=lambda x: x.get('date', ''), reverse=reverse)
        elif sort_field == 'amount':
            all_receipts.sort(key=lambda x: abs(x.get('amount', 0)), reverse=reverse)
        elif sort_field == 'merchant':
            all_receipts.sort(key=lambda x: (x.get('merchant') or '').lower(), reverse=reverse)

        # Get counts by source before pagination
        source_counts = {}
        for r in all_receipts:
            src = r.get('source', 'other')
            source_counts[src] = source_counts.get(src, 0) + 1

        # Get counts by verification status
        verification_counts = {'verified': 0, 'needs_review': 0, 'mismatch': 0, 'unverified': 0, 'waiting': 0, 'has_ocr': 0}
        match_counts = {'matched': 0, 'waiting': 0}
        for r in all_receipts:
            vs = r.get('verification_status', 'unverified')
            if vs in verification_counts:
                verification_counts[vs] += 1
            if r.get('has_ocr'):
                verification_counts['has_ocr'] += 1
            # Match status
            if r.get('status') == 'matched' or r.get('type') == 'transaction':
                match_counts['matched'] += 1
            elif r.get('status') == 'pending' or r.get('verification_status') == 'waiting':
                match_counts['waiting'] += 1

        total = len(all_receipts)

        # Apply pagination
        all_receipts = all_receipts[offset:offset + limit]

        return jsonify({
            'ok': True,
            'receipts': all_receipts,
            'total': total,
            'source_counts': source_counts,
            'verification_counts': verification_counts,
            'match_counts': match_counts,
            'offset': offset,
            'limit': limit
        })

    except Exception as e:
        print(f"❌ Error fetching library receipts: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/library")
@app.route("/library.html")
@login_required
def serve_library():
    """Serve the Receipt Library page."""
    return send_from_directory(BASE_DIR, "receipt_library.html")


@app.route("/report-builder")
@app.route("/report-builder.html")
@login_required
def serve_report_builder():
    """Serve the Report Builder page - focused workflow for building expense reports."""
    return send_from_directory(BASE_DIR, "report_builder.html")


# =============================================================================
# ENHANCED RECEIPT LIBRARY - TAGS, FAVORITES, ANNOTATIONS, COLLECTIONS
# =============================================================================

# -----------------------------------------------------------------------------
# TAGS API
# -----------------------------------------------------------------------------

@app.route("/api/library/tags", methods=["GET"])
def get_receipt_tags():
    """Get all available receipt tags."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        if not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM receipt_tags ORDER BY usage_count DESC, name ASC")
        tags = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'tags': tags})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/tags", methods=["POST"])
def create_receipt_tag():
    """Create a new tag."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'Tag name required'}), 400

        color = data.get('color', '#00ff88')
        icon = data.get('icon', '')
        description = data.get('description', '')

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_tags (name, color, icon, description)
            VALUES (%s, %s, %s, %s)
        """, (name, color, icon, description))
        conn.commit()
        tag_id = cursor.lastrowid
        db.return_connection(conn)

        return jsonify({'ok': True, 'tag_id': tag_id, 'message': f'Tag "{name}" created'})
    except Exception as e:
        if 'Duplicate' in str(e):
            return jsonify({'ok': False, 'error': f'Tag "{name}" already exists'}), 409
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/tags/<int:tag_id>", methods=["PUT"])
def update_receipt_tag(tag_id):
    """Update a tag."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        updates = []
        params = []

        if 'name' in data:
            updates.append("name = %s")
            params.append(data['name'])
        if 'color' in data:
            updates.append("color = %s")
            params.append(data['color'])
        if 'icon' in data:
            updates.append("icon = %s")
            params.append(data['icon'])
        if 'description' in data:
            updates.append("description = %s")
            params.append(data['description'])

        if not updates:
            return jsonify({'ok': False, 'error': 'No fields to update'}), 400

        params.append(tag_id)
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(f"UPDATE receipt_tags SET {', '.join(updates)} WHERE id = %s", params)
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Tag updated'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/tags/<int:tag_id>", methods=["DELETE"])
def delete_receipt_tag(tag_id):
    """Delete a tag (cascades to assignments)."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM receipt_tags WHERE id = %s", (tag_id,))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Tag deleted'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/tags", methods=["GET"])
def get_receipt_tags_for_receipt(receipt_type, receipt_id):
    """Get tags assigned to a specific receipt."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    if receipt_type not in ('transaction', 'incoming', 'metadata'):
        return jsonify({'ok': False, 'error': 'Invalid receipt type'}), 400

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT t.* FROM receipt_tags t
            JOIN receipt_tag_assignments a ON t.id = a.tag_id
            WHERE a.receipt_type = %s AND a.receipt_id = %s
        """, (receipt_type, receipt_id))
        tags = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'tags': tags})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/tags", methods=["POST"])
def assign_tag_to_receipt(receipt_type, receipt_id):
    """Assign a tag to a receipt."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    if receipt_type not in ('transaction', 'incoming', 'metadata'):
        return jsonify({'ok': False, 'error': 'Invalid receipt type'}), 400

    try:
        data = request.get_json() or {}
        tag_id = data.get('tag_id')
        if not tag_id:
            return jsonify({'ok': False, 'error': 'tag_id required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()

        # Insert assignment
        cursor.execute("""
            INSERT INTO receipt_tag_assignments (receipt_type, receipt_id, tag_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE assigned_at = CURRENT_TIMESTAMP
        """, (receipt_type, receipt_id, tag_id))

        # Update usage count
        cursor.execute("UPDATE receipt_tags SET usage_count = usage_count + 1 WHERE id = %s", (tag_id,))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Tag assigned'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/tags/<int:tag_id>", methods=["DELETE"])
def remove_tag_from_receipt(receipt_type, receipt_id, tag_id):
    """Remove a tag from a receipt."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM receipt_tag_assignments
            WHERE receipt_type = %s AND receipt_id = %s AND tag_id = %s
        """, (receipt_type, receipt_id, tag_id))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Tag removed'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# FAVORITES API
# -----------------------------------------------------------------------------

@app.route("/api/library/favorites", methods=["GET"])
def get_favorites():
    """Get all favorited receipts."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM receipt_favorites ORDER BY priority DESC, favorited_at DESC")
        favorites = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'favorites': favorites})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/favorite", methods=["POST"])
def favorite_receipt(receipt_type, receipt_id):
    """Add a receipt to favorites."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    if receipt_type not in ('transaction', 'incoming', 'metadata'):
        return jsonify({'ok': False, 'error': 'Invalid receipt type'}), 400

    try:
        data = request.get_json() or {}
        priority = data.get('priority', 0)
        note = data.get('note', '')

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_favorites (receipt_type, receipt_id, priority, note)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE priority = VALUES(priority), note = VALUES(note)
        """, (receipt_type, receipt_id, priority, note))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Receipt favorited'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/favorite", methods=["DELETE"])
def unfavorite_receipt(receipt_type, receipt_id):
    """Remove a receipt from favorites."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM receipt_favorites WHERE receipt_type = %s AND receipt_id = %s
        """, (receipt_type, receipt_id))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Removed from favorites'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# ANNOTATIONS API
# -----------------------------------------------------------------------------

@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/annotations", methods=["GET"])
def get_receipt_annotations(receipt_type, receipt_id):
    """Get all annotations for a receipt."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM receipt_annotations
            WHERE receipt_type = %s AND receipt_id = %s
            ORDER BY created_at DESC
        """, (receipt_type, receipt_id))
        annotations = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'annotations': annotations})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/annotations", methods=["POST"])
def add_receipt_annotation(receipt_type, receipt_id):
    """Add an annotation to a receipt."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    if receipt_type not in ('transaction', 'incoming', 'metadata'):
        return jsonify({'ok': False, 'error': 'Invalid receipt type'}), 400

    try:
        data = request.get_json() or {}
        content = data.get('content', '').strip()
        if not content:
            return jsonify({'ok': False, 'error': 'Annotation content required'}), 400

        annotation_type = data.get('type', 'note')
        metadata = json.dumps(data.get('metadata', {}))

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_annotations (receipt_type, receipt_id, annotation_type, content, metadata)
            VALUES (%s, %s, %s, %s, %s)
        """, (receipt_type, receipt_id, annotation_type, content, metadata))
        conn.commit()
        annotation_id = cursor.lastrowid
        db.return_connection(conn)

        return jsonify({'ok': True, 'annotation_id': annotation_id, 'message': 'Annotation added'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/annotations/<int:annotation_id>", methods=["DELETE"])
def delete_annotation(annotation_id):
    """Delete an annotation."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM receipt_annotations WHERE id = %s", (annotation_id,))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Annotation deleted'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# ATTENDEES API
# -----------------------------------------------------------------------------

@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/attendees", methods=["GET"])
def get_receipt_attendees(receipt_type, receipt_id):
    """Get attendees for a receipt (meal receipts, events)."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM receipt_attendees
            WHERE receipt_type = %s AND receipt_id = %s
            ORDER BY attendee_name ASC
        """, (receipt_type, receipt_id))
        attendees = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'attendees': attendees})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/attendees", methods=["POST"])
def add_receipt_attendee(receipt_type, receipt_id):
    """Add an attendee to a receipt."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'Attendee name required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_attendees (receipt_type, receipt_id, attendee_name, attendee_email, attendee_company, relationship, contact_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (receipt_type, receipt_id, name, data.get('email'), data.get('company'), data.get('relationship'), data.get('contact_id')))
        conn.commit()
        attendee_id = cursor.lastrowid
        db.return_connection(conn)

        return jsonify({'ok': True, 'attendee_id': attendee_id, 'message': 'Attendee added'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/attendees/<int:attendee_id>", methods=["DELETE"])
def delete_attendee(attendee_id):
    """Remove an attendee from a receipt."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM receipt_attendees WHERE id = %s", (attendee_id,))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Attendee removed'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# COLLECTIONS API
# -----------------------------------------------------------------------------

@app.route("/api/library/collections", methods=["GET"])
def get_collections():
    """Get all receipt collections."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get collections with item counts
        cursor.execute("""
            SELECT c.*,
                   COUNT(i.id) as receipt_count,
                   COALESCE(SUM(
                       CASE
                           WHEN i.receipt_type = 'transaction' THEN (SELECT chase_amount FROM transactions WHERE _index = i.receipt_id)
                           WHEN i.receipt_type = 'incoming' THEN (SELECT amount FROM incoming_receipts WHERE id = i.receipt_id)
                           ELSE 0
                       END
                   ), 0) as total_amount
            FROM receipt_collections c
            LEFT JOIN receipt_collection_items i ON c.id = i.collection_id
            GROUP BY c.id
            ORDER BY c.is_active DESC, c.updated_at DESC
        """)
        collections = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        return jsonify({'ok': True, 'collections': collections})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/collections", methods=["POST"])
def create_collection():
    """Create a new receipt collection."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        name = data.get('name', '').strip()
        if not name:
            return jsonify({'ok': False, 'error': 'Collection name required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_collections (name, description, collection_type, color, icon, start_date, end_date, budget)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            name,
            data.get('description', ''),
            data.get('type', 'custom'),
            data.get('color', '#00ff88'),
            data.get('icon', ''),
            data.get('start_date'),
            data.get('end_date'),
            data.get('budget')
        ))
        conn.commit()
        collection_id = cursor.lastrowid
        db.return_connection(conn)

        return jsonify({'ok': True, 'collection_id': collection_id, 'message': f'Collection "{name}" created'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/collections/<int:collection_id>", methods=["GET"])
def get_collection(collection_id):
    """Get a collection with all its receipts."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get collection
        cursor.execute("SELECT * FROM receipt_collections WHERE id = %s", (collection_id,))
        collection = cursor.fetchone()
        if not collection:
            return jsonify({'ok': False, 'error': 'Collection not found'}), 404
        collection = dict(collection)

        # Get items
        cursor.execute("""
            SELECT i.*,
                   CASE i.receipt_type
                       WHEN 'transaction' THEN (SELECT chase_description FROM transactions WHERE _index = i.receipt_id)
                       WHEN 'incoming' THEN (SELECT merchant FROM incoming_receipts WHERE id = i.receipt_id)
                   END as merchant,
                   CASE i.receipt_type
                       WHEN 'transaction' THEN (SELECT chase_amount FROM transactions WHERE _index = i.receipt_id)
                       WHEN 'incoming' THEN (SELECT amount FROM incoming_receipts WHERE id = i.receipt_id)
                   END as amount,
                   CASE i.receipt_type
                       WHEN 'transaction' THEN (SELECT chase_date FROM transactions WHERE _index = i.receipt_id)
                       WHEN 'incoming' THEN (SELECT receipt_date FROM incoming_receipts WHERE id = i.receipt_id)
                   END as date
            FROM receipt_collection_items i
            WHERE i.collection_id = %s
            ORDER BY date DESC
        """, (collection_id,))
        items = [dict(row) for row in cursor.fetchall()]
        db.return_connection(conn)

        collection['items'] = items
        collection['receipt_count'] = len(items)
        collection['total_amount'] = sum(float(i.get('amount') or 0) for i in items)

        return jsonify({'ok': True, 'collection': collection})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/collections/<int:collection_id>/add", methods=["POST"])
def add_to_collection(collection_id):
    """Add a receipt to a collection."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        receipt_type = data.get('receipt_type')
        receipt_id = data.get('receipt_id')

        if not receipt_type or not receipt_id:
            return jsonify({'ok': False, 'error': 'receipt_type and receipt_id required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO receipt_collection_items (collection_id, receipt_type, receipt_id)
            VALUES (%s, %s, %s)
            ON DUPLICATE KEY UPDATE added_at = CURRENT_TIMESTAMP
        """, (collection_id, receipt_type, receipt_id))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Added to collection'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/collections/<int:collection_id>/remove", methods=["POST"])
def remove_from_collection(collection_id):
    """Remove a receipt from a collection."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        receipt_type = data.get('receipt_type')
        receipt_id = data.get('receipt_id')

        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("""
            DELETE FROM receipt_collection_items
            WHERE collection_id = %s AND receipt_type = %s AND receipt_id = %s
        """, (collection_id, receipt_type, receipt_id))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Removed from collection'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/collections/<int:collection_id>", methods=["DELETE"])
def delete_collection(collection_id):
    """Delete a collection (cascades to items)."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("DELETE FROM receipt_collections WHERE id = %s", (collection_id,))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'message': 'Collection deleted'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# STATISTICS & DASHBOARD API
# -----------------------------------------------------------------------------

@app.route("/api/library/stats", methods=["GET"])
def get_library_stats():
    """Get comprehensive receipt library statistics."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        conn = db.get_connection()
        cursor = conn.cursor()
        stats = {}

        # Total receipts by source
        cursor.execute("""
            SELECT
                COALESCE(source, 'manual') as source,
                COUNT(*) as count,
                SUM(chase_amount) as total_amount
            FROM transactions
            WHERE (receipt_file IS NOT NULL AND receipt_file != '')
               OR (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
            GROUP BY COALESCE(source, 'manual')
        """)
        stats['by_source'] = [dict(row) for row in cursor.fetchall()]

        # Monthly totals (last 12 months)
        cursor.execute("""
            SELECT
                DATE_FORMAT(chase_date, '%%Y-%%m') as month,
                COUNT(*) as receipt_count,
                SUM(chase_amount) as total_amount
            FROM transactions
            WHERE chase_date >= DATE_SUB(CURDATE(), INTERVAL 12 MONTH)
              AND ((receipt_file IS NOT NULL AND receipt_file != '')
               OR (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != ''))
            GROUP BY DATE_FORMAT(chase_date, '%%Y-%%m')
            ORDER BY month DESC
        """)
        stats['monthly'] = [dict(row) for row in cursor.fetchall()]

        # By business type
        cursor.execute("""
            SELECT
                COALESCE(business_type, 'Personal') as business_type,
                COUNT(*) as count,
                SUM(chase_amount) as total_amount
            FROM transactions
            WHERE (receipt_file IS NOT NULL AND receipt_file != '')
               OR (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
            GROUP BY COALESCE(business_type, 'Personal')
            ORDER BY total_amount DESC
        """)
        stats['by_business_type'] = [dict(row) for row in cursor.fetchall()]

        # Top merchants
        cursor.execute("""
            SELECT
                chase_description as merchant,
                COUNT(*) as receipt_count,
                SUM(chase_amount) as total_amount,
                AVG(chase_amount) as avg_amount
            FROM transactions
            WHERE (receipt_file IS NOT NULL AND receipt_file != '')
               OR (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
            GROUP BY chase_description
            ORDER BY receipt_count DESC
            LIMIT 20
        """)
        stats['top_merchants'] = [dict(row) for row in cursor.fetchall()]

        # OCR coverage
        cursor.execute("""
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN ocr_extracted_at IS NOT NULL THEN 1 ELSE 0 END) as with_ocr,
                SUM(CASE WHEN ocr_verified = TRUE THEN 1 ELSE 0 END) as verified,
                AVG(CASE WHEN ocr_confidence IS NOT NULL THEN ocr_confidence ELSE NULL END) as avg_confidence
            FROM transactions
            WHERE (receipt_file IS NOT NULL AND receipt_file != '')
               OR (receipt_url IS NOT NULL AND receipt_url != '')
               OR (r2_url IS NOT NULL AND r2_url != '')
        """)
        ocr_stats = cursor.fetchone()
        stats['ocr'] = dict(ocr_stats) if ocr_stats else {}

        # Tag usage
        cursor.execute("SELECT name, color, usage_count FROM receipt_tags ORDER BY usage_count DESC LIMIT 10")
        stats['top_tags'] = [dict(row) for row in cursor.fetchall()]

        # Collection summary
        cursor.execute("SELECT COUNT(*) as count FROM receipt_collections WHERE is_active = TRUE")
        stats['active_collections'] = cursor.fetchone().get('count', 0)

        # Favorites count
        cursor.execute("SELECT COUNT(*) as count FROM receipt_favorites")
        stats['favorites_count'] = cursor.fetchone().get('count', 0)

        db.return_connection(conn)

        return jsonify({'ok': True, 'stats': stats})
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# BULK OPERATIONS API
# -----------------------------------------------------------------------------

@app.route("/api/library/bulk/tag", methods=["POST"])
def bulk_tag_receipts():
    """Add a tag to multiple receipts at once."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        tag_id = data.get('tag_id')
        receipts = data.get('receipts', [])  # List of {type, id}

        if not tag_id or not receipts:
            return jsonify({'ok': False, 'error': 'tag_id and receipts required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()
        added = 0

        for r in receipts:
            try:
                cursor.execute("""
                    INSERT INTO receipt_tag_assignments (receipt_type, receipt_id, tag_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE assigned_at = CURRENT_TIMESTAMP
                """, (r['type'], r['id'], tag_id))
                added += 1
            except:
                pass

        # Update usage count
        cursor.execute("UPDATE receipt_tags SET usage_count = usage_count + %s WHERE id = %s", (added, tag_id))
        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'tagged': added, 'message': f'Tagged {added} receipts'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/library/bulk/collection", methods=["POST"])
def bulk_add_to_collection():
    """Add multiple receipts to a collection."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        collection_id = data.get('collection_id')
        receipts = data.get('receipts', [])

        if not collection_id or not receipts:
            return jsonify({'ok': False, 'error': 'collection_id and receipts required'}), 400

        conn = db.get_connection()
        cursor = conn.cursor()
        added = 0

        for r in receipts:
            try:
                cursor.execute("""
                    INSERT INTO receipt_collection_items (collection_id, receipt_type, receipt_id)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE added_at = CURRENT_TIMESTAMP
                """, (collection_id, r['type'], r['id']))
                added += 1
            except:
                pass

        conn.commit()
        db.return_connection(conn)

        return jsonify({'ok': True, 'added': added, 'message': f'Added {added} receipts to collection'})
    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# EXPORT API
# -----------------------------------------------------------------------------

@app.route("/api/library/export", methods=["POST"])
def export_receipts():
    """Export receipts in various formats (JSON, CSV)."""
    admin_key = request.json.get('admin_key') if request.json else None
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        data = request.get_json() or {}
        format_type = data.get('format', 'json')  # json, csv
        receipts = data.get('receipts', [])  # List of {type, id} or empty for all
        include_ocr = data.get('include_ocr', True)
        include_tags = data.get('include_tags', True)

        conn = db.get_connection()
        cursor = conn.cursor()

        export_data = []

        # If specific receipts provided
        if receipts:
            for r in receipts:
                if r['type'] == 'transaction':
                    cursor.execute("SELECT * FROM transactions WHERE _index = %s", (r['id'],))
                elif r['type'] == 'incoming':
                    cursor.execute("SELECT * FROM incoming_receipts WHERE id = %s", (r['id'],))
                row = cursor.fetchone()
                if row:
                    item = dict(row)
                    item['receipt_type'] = r['type']
                    export_data.append(item)
        else:
            # Export all with receipts
            cursor.execute("""
                SELECT *, 'transaction' as receipt_type FROM transactions
                WHERE (receipt_file IS NOT NULL AND receipt_file != '')
                   OR (receipt_url IS NOT NULL AND receipt_url != '')
                   OR (r2_url IS NOT NULL AND r2_url != '')
            """)
            export_data.extend([dict(row) for row in cursor.fetchall()])

        # Add tags if requested
        if include_tags:
            for item in export_data:
                cursor.execute("""
                    SELECT t.name FROM receipt_tags t
                    JOIN receipt_tag_assignments a ON t.id = a.tag_id
                    WHERE a.receipt_type = %s AND a.receipt_id = %s
                """, (item['receipt_type'], item.get('_index') or item.get('id')))
                item['tags'] = [row['name'] for row in cursor.fetchall()]

        db.return_connection(conn)

        if format_type == 'csv':
            import csv
            import io
            output = io.StringIO()
            if export_data:
                writer = csv.DictWriter(output, fieldnames=export_data[0].keys())
                writer.writeheader()
                for item in export_data:
                    # Convert complex types to strings
                    for k, v in item.items():
                        if isinstance(v, (list, dict)):
                            item[k] = json.dumps(v)
                    writer.writerow(item)
            return Response(
                output.getvalue(),
                mimetype='text/csv',
                headers={'Content-Disposition': 'attachment; filename=receipts_export.csv'}
            )
        else:
            return jsonify({
                'ok': True,
                'format': 'json',
                'count': len(export_data),
                'receipts': export_data
            })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# -----------------------------------------------------------------------------
# RECEIPT DETAILS (ENHANCED WITH LINE ITEMS)
# -----------------------------------------------------------------------------

@app.route("/api/library/receipts/<receipt_type>/<int:receipt_id>/details", methods=["GET"])
def get_receipt_full_details(receipt_type, receipt_id):
    """
    Get full receipt details including:
    - Basic receipt data
    - OCR data with line items
    - Tags
    - Annotations
    - Attendees
    - Collections it belongs to
    - Favorite status
    """
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not is_authenticated() and (not expected_key or admin_key != expected_key):
        return jsonify({'error': 'Authentication required', 'ok': False}), 401

    if receipt_type not in ('transaction', 'incoming', 'metadata'):
        return jsonify({'ok': False, 'error': 'Invalid receipt type'}), 400

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Get base receipt data
        if receipt_type == 'transaction':
            cursor.execute("SELECT * FROM transactions WHERE _index = %s", (receipt_id,))
        elif receipt_type == 'incoming':
            cursor.execute("SELECT * FROM incoming_receipts WHERE id = %s", (receipt_id,))
        else:
            cursor.execute("SELECT * FROM receipt_metadata WHERE id = %s", (receipt_id,))

        receipt = cursor.fetchone()
        if not receipt:
            return jsonify({'ok': False, 'error': 'Receipt not found'}), 404

        receipt = dict(receipt)

        # Parse line items from OCR
        line_items = receipt.get('ocr_line_items')
        if isinstance(line_items, str):
            try:
                receipt['line_items'] = json.loads(line_items)
            except:
                receipt['line_items'] = []
        elif line_items:
            receipt['line_items'] = line_items
        else:
            receipt['line_items'] = []

        # Get tags
        cursor.execute("""
            SELECT t.* FROM receipt_tags t
            JOIN receipt_tag_assignments a ON t.id = a.tag_id
            WHERE a.receipt_type = %s AND a.receipt_id = %s
        """, (receipt_type, receipt_id))
        receipt['tags'] = [dict(row) for row in cursor.fetchall()]

        # Get annotations
        cursor.execute("""
            SELECT * FROM receipt_annotations
            WHERE receipt_type = %s AND receipt_id = %s
            ORDER BY created_at DESC
        """, (receipt_type, receipt_id))
        receipt['annotations'] = [dict(row) for row in cursor.fetchall()]

        # Get attendees
        cursor.execute("""
            SELECT * FROM receipt_attendees
            WHERE receipt_type = %s AND receipt_id = %s
        """, (receipt_type, receipt_id))
        receipt['attendees'] = [dict(row) for row in cursor.fetchall()]

        # Get collections
        cursor.execute("""
            SELECT c.id, c.name, c.collection_type, c.color
            FROM receipt_collections c
            JOIN receipt_collection_items i ON c.id = i.collection_id
            WHERE i.receipt_type = %s AND i.receipt_id = %s
        """, (receipt_type, receipt_id))
        receipt['collections'] = [dict(row) for row in cursor.fetchall()]

        # Get favorite status
        cursor.execute("""
            SELECT * FROM receipt_favorites
            WHERE receipt_type = %s AND receipt_id = %s
        """, (receipt_type, receipt_id))
        fav = cursor.fetchone()
        receipt['is_favorite'] = fav is not None
        receipt['favorite_note'] = dict(fav).get('note') if fav else None

        db.return_connection(conn)

        return jsonify({'ok': True, 'receipt': receipt})

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# INCOMING RECEIPTS SYSTEM
# =============================================================================

@app.route("/api/incoming/receipts", methods=["GET"])
def get_incoming_receipts():
    """
    Get all incoming receipts from Gmail
    Supports admin_key authentication for API access.

    Query params:
    - status: 'pending', 'accepted', 'rejected', or 'all' (default: 'all')
    - limit: max number of results (default: 100)
    """
    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required', 'ok': False}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'Database not available'
            }), 500

        status = request.args.get('status', 'all')
        limit = int(request.args.get('limit', 500))  # Increased to show all emails including rejected

        conn, db_type = get_db_connection()

        # Build query based on status filter
        if status == 'all':
            query = '''
                SELECT * FROM incoming_receipts
                ORDER BY received_date DESC
                LIMIT ?
            '''
            cursor = db_execute(conn, db_type, query, (limit,))
        else:
            query = '''
                SELECT * FROM incoming_receipts
                WHERE status = ?
                ORDER BY received_date DESC
                LIMIT ?
            '''
            cursor = db_execute(conn, db_type, query, (status, limit))

        receipts = [dict(row) for row in cursor.fetchall()]

        # Get counts by status
        cursor = db_execute(conn, db_type, 'SELECT status, COUNT(*) as count FROM incoming_receipts GROUP BY status')
        status_counts = {row['status']: row['count'] for row in cursor.fetchall()}

        return_db_connection(conn)

        # Apply smart merchant extraction from subject lines
        try:
            from merchant_intelligence import normalize_merchant
        except ImportError:
            normalize_merchant = lambda x: x  # fallback to identity

        import re

        def extract_merchant_from_subject(subject):
            """Smart merchant extraction from email subject lines"""
            if not subject:
                return None

            subject = subject.strip()

            # Known merchant patterns in order of specificity
            patterns = [
                # "Your X invoice/receipt/order"
                (r'^Your\s+([A-Z][A-Za-z0-9\.\s]+?)\s+(?:invoice|receipt|order|payment|subscription)', 1),
                # "Invoice from X"
                (r'Invoice\s+from\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
                # "Payment request from X"
                (r'[Pp]ayment\s+(?:request\s+)?from\s+([^(\[\n#-]+?)(?:\s*[\(\[#-]|$)', 1),
                # "Receipt from X"
                (r'[Rr]eceipt\s+from\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
                # "Your order from X"
                (r'[Yy]our\s+order\s+(?:from|with)\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
                # "X Payment Confirmation/Receipt"
                (r'^([A-Z][A-Za-z0-9\s]+?)\s+(?:Payment|Receipt)\s*[-–]?\s*(?:Confirmation|Receipt)?', 1),
                # "Thank You for Your Order with X"
                (r'[Tt]hank\s+[Yy]ou\s+for\s+[Yy]our\s+[Oo]rder\s+with\s+([A-Za-z0-9\s]+)', 1),
                # "Shipped/Ordered: ..." (Amazon pattern)
                (r'^(?:Shipped|Ordered|Delivered):\s+"', None),  # Amazon indicator
                # "Your Amazon.com order"
                (r'[Yy]our\s+(Amazon\.?com?)\s+order', 1),
                # "X Parking Payment"
                (r'^([A-Z][A-Za-z]+)\s+Parking\s+Payment', 1),
                # "FW: Invoice from X"
                (r'(?:FW:|Fwd:)\s*Invoice\s+from\s+([^(\[\n#]+?)(?:\s*[\(\[#]|$)', 1),
            ]

            for pattern, group in patterns:
                if group is None:
                    # Special case: Amazon shipped/ordered
                    if re.match(pattern, subject):
                        return "Amazon"
                    continue
                match = re.search(pattern, subject, re.IGNORECASE)
                if match:
                    merchant = match.group(group).strip()
                    # Clean up
                    merchant = re.sub(r',?\s*(Inc\.?|LLC|Ltd\.?|PBC|Co\.?)$', '', merchant, flags=re.IGNORECASE).strip()
                    merchant = re.sub(r'\s+', ' ', merchant)  # normalize whitespace
                    if len(merchant) > 2 and len(merchant) < 50:
                        return merchant

            # Domain-based fallback patterns
            domain_merchants = {
                'cloudflare': 'Cloudflare',
                'hive': 'Hive',
                'simpletexting': 'SimpleTexting',
                'stripe': 'Stripe',
                'paypal': 'PayPal',
                'square': 'Square',
                'uber': 'Uber',
                'lyft': 'Lyft',
                'doordash': 'DoorDash',
                'grubhub': 'Grubhub',
                'spotify': 'Spotify',
                'netflix': 'Netflix',
                'apple': 'Apple',
                'google': 'Google',
                'microsoft': 'Microsoft',
                'adobe': 'Adobe',
                'amazon': 'Amazon',
                'costco': 'Costco',
                'walmart': 'Walmart',
                'target': 'Target',
                'starbucks': 'Starbucks',
                'chick-fil-a': 'Chick-fil-A',
                'anthropic': 'Anthropic',
                'openai': 'OpenAI',
                'cursor': 'Cursor',
                'github': 'GitHub',
                'digitalocean': 'DigitalOcean',
                'railway': 'Railway',
                'vercel': 'Vercel',
                'heroku': 'Heroku',
                'aws': 'AWS',
                'kia': 'Kia Finance',
                'verizon': 'Verizon',
                'att': 'AT&T',
                't-mobile': 'T-Mobile',
            }

            subject_lower = subject.lower()
            for key, merchant in domain_merchants.items():
                if key in subject_lower:
                    return merchant

            return None

        for receipt in receipts:
            subject = receipt.get('subject', '')
            original_merchant = receipt.get('merchant', '')

            # Ensure receipt_date is set - use received_date (email date) as authoritative
            # received_date is when the email was received, which is the correct date for Gmail receipts
            # transaction_date is OCR-extracted and may be wrong (e.g., Nov 20 shown on a Nov 28 email)
            if not receipt.get('receipt_date'):
                receipt['receipt_date'] = receipt.get('received_date') or receipt.get('transaction_date') or ''

            # Try to extract merchant from subject
            extracted = extract_merchant_from_subject(subject)

            if extracted:
                receipt['merchant'] = normalize_merchant(extracted)
                receipt['original_merchant'] = original_merchant
            elif original_merchant and len(original_merchant) > 2 and len(original_merchant) < 40:
                # Only use original if it looks valid (not garbage text)
                words = original_merchant.split()
                if len(words) <= 5 and not any(w.lower() in ['the', 'is', 'your', 'a', 'an', 'to', 'from', 'set'] for w in words[:2]):
                    receipt['merchant'] = normalize_merchant(original_merchant)
                else:
                    receipt['merchant'] = None  # Clear garbage
            else:
                receipt['merchant'] = None

            # Determine if this is a refund
            subject_lower = subject.lower() if subject else ''
            receipt['is_refund'] = 'refund' in subject_lower

        # Find potential expense matches for pending receipts
        conn2, db_type2 = get_db_connection()

        # Load all rejections to filter out blocked receipt+transaction combos
        rejection_map = {}  # transaction_id -> set of receipt_paths
        try:
            rej_cursor = db_execute(conn2, db_type2, '''
                SELECT transaction_id, receipt_path FROM rejected_receipts
                WHERE transaction_id IS NOT NULL
            ''', ())
            for rej_row in rej_cursor.fetchall():
                rej = dict(rej_row)
                tid = rej.get('transaction_id')
                rpath = rej.get('receipt_path', '')
                if tid and rpath:
                    if tid not in rejection_map:
                        rejection_map[tid] = set()
                    rejection_map[tid].add(rpath)
                    # Also add without 'receipts/' prefix for flexible matching
                    rejection_map[tid].add(rpath.replace('receipts/', ''))
        except Exception as rej_err:
            print(f"ℹ️ Could not load rejections for matching filter: {rej_err}")

        for receipt in receipts:
            if receipt.get('status') != 'pending':
                continue

            merchant = receipt.get('merchant', '') or ''
            amount = float(receipt.get('amount') or 0)
            receipt_date = receipt.get('receipt_date') or receipt.get('received_date') or ''
            receipt_file = receipt.get('receipt_file', '') or ''
            receipt_url = receipt.get('receipt_url', '') or ''

            if not merchant or not amount:
                receipt['potential_matches'] = []
                continue

            # Parse date
            if isinstance(receipt_date, str):
                # Handle various date formats
                receipt_date = receipt_date.split('T')[0].split(' ')[0] if receipt_date else ''

            try:
                # Find matching expenses (transactions without receipts, similar amount, within 7 days)
                # Note: Table uses chase_description, chase_amount, chase_date (not merchant, amount, date)
                if db_type2 == 'mysql':
                    match_query = '''
                        SELECT id, chase_description as merchant, chase_amount as amount, chase_date as date,
                               receipt_url, receipt_file, card, mi_merchant, chase_description
                        FROM transactions
                        WHERE ABS(ABS(chase_amount) - ?) < 1.00
                        AND (receipt_url IS NULL OR receipt_url = '' OR receipt_file IS NULL OR receipt_file = '')
                        ORDER BY ABS(ABS(chase_amount) - ?) ASC, chase_date DESC
                        LIMIT 5
                    '''
                else:
                    match_query = '''
                        SELECT id, chase_description as merchant, chase_amount as amount, chase_date as date,
                               receipt_url, receipt_file, card, mi_merchant, chase_description
                        FROM transactions
                        WHERE ABS(ABS(chase_amount) - ?) < 1.00
                        AND (receipt_url IS NULL OR receipt_url = '' OR receipt_file IS NULL OR receipt_file = '')
                        ORDER BY ABS(ABS(chase_amount) - ?) ASC, chase_date DESC
                        LIMIT 5
                    '''

                cursor2 = db_execute(conn2, db_type2, match_query, (amount, amount))
                matches = []

                merchant_lower = merchant.lower()
                for row in cursor2.fetchall():
                    tx = dict(row)
                    tx_id = tx.get('id')
                    tx_merchant = (tx.get('mi_merchant') or tx.get('merchant') or tx.get('chase_description') or '').lower()

                    # ===== CHECK FOR REJECTION BLOCK =====
                    # Skip this transaction if the receipt was previously rejected from it
                    if tx_id in rejection_map:
                        rejected_paths = rejection_map[tx_id]
                        is_blocked = False
                        # Check if current receipt matches any rejected path
                        for rpath in rejected_paths:
                            if receipt_file and (rpath in receipt_file or receipt_file in rpath):
                                is_blocked = True
                                break
                            if receipt_url and (rpath in receipt_url or receipt_url in rpath):
                                is_blocked = True
                                break
                        if is_blocked:
                            continue  # Skip this transaction - receipt was previously rejected from it

                    # Calculate match score
                    score = 0

                    # Amount match (within $0.10 = 40 points, within $1 = 20 points)
                    amount_diff = abs(abs(float(tx.get('amount', 0))) - amount)
                    if amount_diff < 0.10:
                        score += 40
                    elif amount_diff < 1.00:
                        score += 20

                    # Merchant match
                    if merchant_lower in tx_merchant or tx_merchant in merchant_lower:
                        score += 50
                    elif merchant_lower[:4] == tx_merchant[:4] if len(merchant_lower) > 3 and len(tx_merchant) > 3 else False:
                        score += 30

                    if score >= 20:  # Only include reasonable matches
                        matches.append({
                            'id': tx_id,
                            'merchant': tx.get('mi_merchant') or tx.get('merchant') or tx.get('chase_description'),
                            'amount': float(tx.get('amount', 0)),
                            'date': str(tx.get('date', '')),
                            'card': tx.get('card', ''),
                            'score': score,
                            'needs_receipt': not bool(tx.get('receipt_url') or tx.get('receipt_file'))
                        })

                # Sort by score and take top 3
                matches.sort(key=lambda x: x['score'], reverse=True)
                receipt['potential_matches'] = matches[:3]
                receipt['best_match'] = matches[0] if matches else None

            except Exception as match_err:
                print(f"⚠️ Match finding error: {match_err}")
                receipt['potential_matches'] = []
                receipt['best_match'] = None

        conn2.close()

        return jsonify({
            'ok': True,
            'receipts': receipts,
            'counts': status_counts,
            'total': len(receipts)
        })

    except Exception as e:
        error_str = str(e).lower()
        # Table doesn't exist yet (handle both SQLite and MySQL error messages)
        if "no such table" in error_str or "doesn't exist" in error_str or "table" in error_str:
            print(f"⚠️  incoming_receipts table not found: {e}")
            return jsonify({
                'ok': True,
                'receipts': [],
                'counts': {},
                'total': 0,
                'message': 'Incoming receipts table not initialized yet'
            })
        print(f"❌ Error fetching incoming receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/check-duplicate", methods=["POST"])
@login_required
def check_duplicate_transaction():
    """
    Check if a transaction already exists with similar merchant/amount/date.
    Returns potential duplicates to warn user before accepting.

    Body: { "merchant": "Anthropic", "amount": 20.00, "date": "2024-11-15" }
    """
    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': True, 'duplicates': []})

        data = request.json
        merchant = data.get('merchant', '').strip().lower()
        amount = float(data.get('amount', 0))
        trans_date = data.get('date', '')

        if not merchant or not amount:
            return jsonify({'ok': True, 'duplicates': []})

        conn, db_type = get_db_connection()

        # Look for transactions within 3 days with same amount
        # MySQL uses DATE_SUB/DATE_ADD, SQLite uses date()
        # Note: Table uses chase_description, chase_amount, chase_date (not merchant, amount, date)
        if db_type == 'mysql':
            query = '''
                SELECT id, chase_description as merchant, chase_amount as amount, chase_date as date, receipt_url, receipt_file
                FROM transactions
                WHERE ABS(chase_amount) BETWEEN ? - 0.01 AND ? + 0.01
                AND chase_date BETWEEN DATE_SUB(?, INTERVAL 3 DAY) AND DATE_ADD(?, INTERVAL 3 DAY)
                ORDER BY chase_date DESC
                LIMIT 10
            '''
            params = (abs(amount), abs(amount), trans_date, trans_date)
        else:
            query = '''
                SELECT id, chase_description as merchant, chase_amount as amount, chase_date as date, receipt_url, receipt_file
                FROM transactions
                WHERE ABS(chase_amount) BETWEEN ? - 0.01 AND ? + 0.01
                AND chase_date BETWEEN date(?, '-3 days') AND date(?, '+3 days')
                ORDER BY chase_date DESC
                LIMIT 10
            '''
            params = (abs(amount), abs(amount), trans_date, trans_date)

        cursor = db_execute(conn, db_type, query, params)
        rows = cursor.fetchall()

        duplicates = []
        for row in rows:
            tx = dict(row)
            tx_merchant = (tx.get('merchant') or '').lower()

            # Check if merchant names are similar
            # Simple match: contains or Levenshtein-like comparison
            if merchant in tx_merchant or tx_merchant in merchant or \
               (len(merchant) > 3 and merchant[:4] == tx_merchant[:4]):
                # Has receipt attached?
                has_receipt = bool(tx.get('receipt_url') or tx.get('receipt_file'))
                duplicates.append({
                    'id': tx.get('id'),
                    'merchant': tx.get('merchant'),
                    'amount': float(tx.get('amount', 0)),
                    'date': str(tx.get('date', '')),
                    'has_receipt': has_receipt
                })

        return_db_connection(conn)
        return jsonify({
            'ok': True,
            'duplicates': duplicates,
            'has_duplicates': len(duplicates) > 0
        })

    except Exception as e:
        print(f"❌ Error checking duplicates: {e}")
        return jsonify({'ok': True, 'duplicates': []})


@app.route("/api/incoming/attach-to-transaction", methods=["POST"])
@login_required
def attach_receipt_to_transaction():
    """
    Attach an incoming receipt to an existing transaction (for duplicates).

    Body: { "receipt_id": 123, "transaction_id": 456 }

    IMPORTANT: Checks rejected_receipts table to prevent re-attaching
    receipts that were previously detached from this specific transaction.
    """
    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.json
        receipt_id = data.get('receipt_id')
        transaction_id = data.get('transaction_id')

        if not receipt_id or not transaction_id:
            return jsonify({'ok': False, 'error': 'Missing receipt_id or transaction_id'}), 400

        conn, db_type = get_db_connection()

        # Get the incoming receipt
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = ?', (receipt_id,))
        receipt_row = cursor.fetchone()

        if not receipt_row:
            return_db_connection(conn)
            return jsonify({'ok': False, 'error': 'Receipt not found'}), 404

        receipt = dict(receipt_row)

        # Get receipt file from incoming receipt
        receipt_file = receipt.get('receipt_file', '') or ''
        receipt_url = receipt.get('receipt_url', '') or ''

        # ===== CHECK FOR REJECTION BLOCK =====
        # Prevent re-attaching a receipt that was previously detached from this transaction
        try:
            cursor = db_execute(conn, db_type, '''
                SELECT id, receipt_path, reason FROM rejected_receipts
                WHERE transaction_id = ?
            ''', (transaction_id,))
            rejections = cursor.fetchall()

            for rejection in rejections:
                rej = dict(rejection)
                rejected_path = rej.get('receipt_path', '')
                # Check if the receipt file matches the rejected one
                if receipt_file and rejected_path and (
                    rejected_path in receipt_file or
                    receipt_file in rejected_path or
                    receipt_file.replace('receipts/', '') == rejected_path.replace('receipts/', '')
                ):
                    return_db_connection(conn)
                    print(f"🚫 BLOCKED: Receipt '{receipt_file}' was previously rejected from transaction #{transaction_id}")
                    return jsonify({
                        'ok': False,
                        'error': 'This receipt was previously removed from this expense and cannot be re-attached',
                        'blocked': True,
                        'reason': rej.get('reason', 'user_manually_removed')
                    }), 400

                # Also check by receipt_url
                if receipt_url and rejected_path and (
                    rejected_path in receipt_url or
                    receipt_url in rejected_path
                ):
                    return_db_connection(conn)
                    print(f"🚫 BLOCKED: Receipt URL '{receipt_url}' was previously rejected from transaction #{transaction_id}")
                    return jsonify({
                        'ok': False,
                        'error': 'This receipt was previously removed from this expense and cannot be re-attached',
                        'blocked': True,
                        'reason': rej.get('reason', 'user_manually_removed')
                    }), 400

        except Exception as rej_error:
            # If rejected_receipts table doesn't exist or has issues, continue anyway
            print(f"ℹ️ Could not check rejections: {rej_error}")

        # Update the existing transaction with the receipt
        if receipt_file or receipt_url:
            db_execute(conn, db_type,
                'UPDATE transactions SET receipt_file = ?, receipt_url = ?, ai_notes = COALESCE(ai_notes, ?) WHERE id = ?',
                (receipt_file, receipt_url or receipt_file, receipt.get('ai_notes', ''), transaction_id))

        # Mark incoming receipt as accepted
        db_execute(conn, db_type,
            'UPDATE incoming_receipts SET status = ?, transaction_id = ? WHERE id = ?',
            ('accepted', transaction_id, receipt_id))

        conn.commit()
        return_db_connection(conn)

        # Auto-run OCR extraction on attached receipt (async-friendly)
        ocr_result = None
        if receipt_file and OCR_SERVICE_AVAILABLE:
            try:
                from ocr_integration import auto_ocr_on_receipt_match
                # Get transaction _index from id
                conn2, _ = get_db_connection()
                cursor2 = db_execute(conn2, db_type, 'SELECT _index FROM transactions WHERE id = ?', (transaction_id,))
                tx_row = cursor2.fetchone()
                return_db_connection(conn2)

                if tx_row:
                    tx_index = tx_row.get('_index')
                    print(f"🔍 Running OCR on attached receipt for transaction {tx_index}...")
                    ocr_result = auto_ocr_on_receipt_match(tx_index, receipt_file)
            except Exception as ocr_err:
                print(f"⚠️ OCR extraction failed (non-blocking): {ocr_err}")

        print(f"✅ Receipt {receipt_id} attached to transaction {transaction_id}")
        return jsonify({
            'ok': True,
            'transaction_id': transaction_id,
            'message': 'Receipt attached to existing transaction',
            'ocr_extracted': bool(ocr_result)
        })

    except Exception as e:
        print(f"❌ Error attaching receipt: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/accept", methods=["POST"])
@api_key_required
def accept_incoming_receipt():
    """
    Accept an incoming receipt and create a transaction (or attach to existing)

    Body:
    {
        "receipt_id": 123,
        "merchant": "Anthropic",
        "amount": 20.00,
        "date": "2024-11-15",
        "business_type": "Personal"
    }
    """
    from datetime import datetime
    import json

    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'Database not available'
            }), 500

        data = request.json
        receipt_id = data.get('receipt_id')

        # Only receipt_id is required - we'll fetch other data from the receipt itself if not provided
        if not receipt_id:
            return jsonify({
                'ok': False,
                'error': 'Missing required field: receipt_id'
            }), 400

        conn, db_type = get_db_connection()

        # Get the receipt data first (needed to fill in missing fields)
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = ?', (receipt_id,))
        receipt_row = cursor.fetchone()

        if not receipt_row:
            return_db_connection(conn)
            return jsonify({
                'ok': False,
                'error': 'Receipt not found'
            }), 404

        # Convert to dict for safe access
        receipt_data = dict(receipt_row)

        # Use provided values or fall back to receipt data
        merchant = data.get('merchant') or receipt_data.get('merchant') or receipt_data.get('subject', 'Unknown')[:100]
        amount = float(data.get('amount', 0)) or float(receipt_data.get('amount', 0) or 0)

        # IMPORTANT: Use receipt_date (actual purchase date) first, then received_date as fallback
        # The receipt_date is the date on the receipt itself (from OCR), received_date is when email arrived
        trans_date = data.get('date') or receipt_data.get('receipt_date') or receipt_data.get('received_date', '')
        if trans_date and 'T' in str(trans_date):
            trans_date = str(trans_date).split('T')[0]
        # Handle date objects (from database)
        if hasattr(trans_date, 'strftime'):
            trans_date = trans_date.strftime('%Y-%m-%d')
        # Handle RFC 2822 email date format (e.g., 'Sun, 26 Oct 2025 10:35:00 +0000')
        if trans_date and isinstance(trans_date, str) and ',' in trans_date:
            try:
                from email.utils import parsedate_to_datetime
                parsed_dt = parsedate_to_datetime(trans_date)
                trans_date = parsed_dt.strftime('%Y-%m-%d')
            except Exception:
                # Fallback: try to extract date parts manually
                import re
                match = re.search(r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})', trans_date)
                if match:
                    day, month_str, year = match.groups()
                    month_map = {'Jan': '01', 'Feb': '02', 'Mar': '03', 'Apr': '04', 'May': '05', 'Jun': '06',
                                 'Jul': '07', 'Aug': '08', 'Sep': '09', 'Oct': '10', 'Nov': '11', 'Dec': '12'}
                    trans_date = f"{year}-{month_map.get(month_str, '01')}-{day.zfill(2)}"
        business_type = data.get('business_type', 'Personal')

        # Validate we have minimum required data
        if not merchant:
            merchant = "Unknown Merchant"
        if not amount:
            amount = 0.01  # Use minimum amount if not provided
        if not trans_date:
            trans_date = datetime.now().strftime('%Y-%m-%d')

        # Use receipt_data instead of receipt_row for the rest of the function
        receipt = receipt_data

        # Helper for safe column access (already have receipt dict)
        def get_col(name, default=None):
            return receipt.get(name) if receipt.get(name) else default

        subject_preview = get_col('subject', 'No subject')
        if subject_preview:
            subject_preview = subject_preview[:50]
        else:
            subject_preview = 'No subject'
        print(f"📧 Processing receipt {receipt_id}: {subject_preview}")

        # Check the source to determine how to get receipt files
        source = get_col('source', 'gmail')
        receipt_files = []

        if source == 'mobile_scanner':
            # Mobile scanner - receipt file is already stored locally
            existing_file = get_col('receipt_file')
            if existing_file:
                # The file is already stored, just use the path
                # Ensure it has the receipts/ prefix for the full path
                full_path = RECEIPT_DIR / existing_file
                if full_path.exists():
                    receipt_files = [f"receipts/{existing_file}"]
                    print(f"   📱 Using existing mobile receipt: {existing_file}")
                else:
                    print(f"   ⚠️  Mobile receipt file not found: {full_path}")
        else:
            # Gmail source - download from Gmail
            gmail_account = get_col('gmail_account')
            email_id = get_col('email_id')

            if gmail_account and email_id:
                # Import Gmail service only when needed
                import sys
                sys.path.insert(0, str(BASE_DIR))
                from incoming_receipts_service import process_receipt_files, load_gmail_service
                service = load_gmail_service(gmail_account)

                if service:
                    try:
                        # Get full message to extract HTML body
                        msg_data = service.users().messages().get(
                            userId='me',
                            id=email_id,
                            format='full'
                        ).execute()

                        # Extract HTML body for screenshots
                        def get_html_body(payload):
                            body = ''
                            if 'parts' in payload:
                                for part in payload['parts']:
                                    if part.get('mimeType') == 'text/html':
                                        import base64
                                        data = part.get('body', {}).get('data', '')
                                        if data:
                                            body = base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                                            break
                            return body

                        html_body = get_html_body(msg_data.get('payload', {}))

                        # Parse attachments info
                        attachments_str = get_col('attachments', '[]')
                        attachments = json.loads(attachments_str)

                        # Download and process receipt files
                        print(f"   📎 Downloading receipt files from Gmail...")
                        receipt_files = process_receipt_files(
                            service, email_id, attachments, html_body,
                            merchant=merchant, amount=amount, receipt_date=trans_date
                        )
                        print(f"   ✓ Downloaded {len(receipt_files)} file(s)")
                    except Exception as e:
                        print(f"   ⚠️  Warning: Could not download receipt files: {e}")
            else:
                # No Gmail info - check if there's an existing receipt_file path
                existing_file = get_col('receipt_file')
                if existing_file:
                    full_path = RECEIPT_DIR / existing_file
                    if full_path.exists():
                        receipt_files = [f"receipts/{existing_file}"]
                        print(f"   📁 Using existing receipt file: {existing_file}")

        # Prepare notes (handle null fields for mobile scanner)
        notes = []
        description = get_col('description')
        is_subscription = get_col('is_subscription')
        subject = get_col('subject', merchant)
        notes_from_db = get_col('notes')

        if description:
            notes.append(description)
        if is_subscription:
            notes.append('[Subscription]')
        if notes_from_db:
            notes.append(notes_from_db)
        if source == 'mobile_scanner':
            notes.append(f"[Mobile Scanner]")
        else:
            notes.append(f"From: {subject}")
        notes_text = ' | '.join(notes) if notes else ''

        # Check for duplicate transactions (same merchant, amount, date within ±3 days)
        from datetime import datetime, timedelta
        trans_datetime = datetime.strptime(trans_date, '%Y-%m-%d')
        date_start = (trans_datetime - timedelta(days=3)).strftime('%Y-%m-%d')
        date_end = (trans_datetime + timedelta(days=3)).strftime('%Y-%m-%d')

        cursor = db_execute(conn, db_type, '''
            SELECT _index, chase_description, chase_amount, chase_date, receipt_file
            FROM transactions
            WHERE chase_description LIKE ?
            AND ABS(chase_amount - ?) < 0.01
            AND chase_date BETWEEN ? AND ?
            ORDER BY chase_date DESC
            LIMIT 1
        ''', (f'%{merchant}%', abs(amount), date_start, date_end))

        existing_transaction = cursor.fetchone()

        # Note: We no longer auto-reject duplicates since multiple receipts might have same amount
        # (e.g., two separate Kit refunds). Instead we just warn in the log.
        if existing_transaction and existing_transaction['receipt_file']:
            print(f"   ℹ️  Similar transaction #{existing_transaction['_index']} exists with receipt (proceeding anyway)")
            # Continue to create new transaction - user explicitly clicked accept

        # Check if this should attach to existing transaction
        match_type = get_col('match_type')
        matched_transaction_id = get_col('matched_transaction_id')

        # Use the found existing transaction if no matched_transaction_id
        if existing_transaction and not existing_transaction['receipt_file']:
            matched_transaction_id = existing_transaction['_index']
            match_type = 'needs_receipt'
            print(f"   📎 Found existing transaction #{matched_transaction_id} without receipt")

        # Separate R2 URLs from local file paths
        r2_urls = [f for f in receipt_files if f.startswith('http')]
        local_files = [f for f in receipt_files if not f.startswith('http')]

        # For receipt_file, use local paths; for receipt_url, use R2 URLs
        receipt_file_str = ', '.join([f.replace('receipts/', '') for f in local_files]) if local_files else ''
        receipt_url_str = r2_urls[0] if r2_urls else ''  # Primary R2 URL

        if match_type == 'needs_receipt' and matched_transaction_id:
            # Attach to existing transaction
            print(f"   📎 Attaching to existing transaction #{matched_transaction_id}")

            # Use CONCAT for MySQL, || for SQLite
            if db_type == 'mysql':
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET receipt_file = COALESCE(NULLIF(?, ''), receipt_file),
                        receipt_url = COALESCE(NULLIF(?, ''), receipt_url),
                        notes = CONCAT(COALESCE(notes, ''), ?)
                    WHERE _index = ?
                ''', (receipt_file_str, receipt_url_str, f'\n[From incoming receipt: {notes_text}]', matched_transaction_id))
            else:
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET receipt_file = COALESCE(NULLIF(?, ''), receipt_file),
                        receipt_url = COALESCE(NULLIF(?, ''), receipt_url),
                        notes = COALESCE(notes, '') || ?
                    WHERE _index = ?
                ''', (receipt_file_str, receipt_url_str, f'\n[From incoming receipt: {notes_text}]', matched_transaction_id))

            transaction_id = matched_transaction_id
            action = 'attached'
        else:
            # Create new transaction
            print(f"   ➕ Creating new transaction")

            # Get next _index value
            cursor = db_execute(conn, db_type, 'SELECT COALESCE(MAX(_index), 0) + 1 FROM transactions')
            row = cursor.fetchone()
            # Handle dict (MySQL DictCursor) vs tuple (SQLite)
            next_index = list(row.values())[0] if isinstance(row, dict) else row[0]

            cursor = db_execute(conn, db_type, '''
                INSERT INTO transactions (
                    _index, chase_description, chase_amount, chase_date,
                    business_type, review_status, notes,
                    receipt_file, receipt_url, source
                ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, ?, 'incoming_receipt')
            ''', (next_index, merchant, amount, trans_date, business_type, notes_text, receipt_file_str, receipt_url_str))

            transaction_id = next_index
            action = 'created'

        # COMMIT the transaction insert first to ensure it's saved
        conn.commit()
        print(f"   💾 Transaction #{transaction_id} committed to database")

        # Update incoming receipt status (separate try block so transaction is preserved)
        try:
            cursor = db_execute(conn, db_type, '''
                UPDATE incoming_receipts
                SET status = 'accepted',
                    accepted_as_transaction_id = ?,
                    reviewed_at = ?,
                    receipt_files = ?
                WHERE id = ?
            ''', (transaction_id, datetime.now().isoformat(), json.dumps(receipt_files), receipt_id))
            conn.commit()
        except Exception as update_err:
            print(f"   ⚠️  Could not update incoming_receipts status: {update_err}")
            # Transaction was already committed, so we continue

        return_db_connection(conn)

        # === CRITICAL: Update in-memory DataFrame so viewer shows new transaction ===
        global df
        if action == 'created':
            # Append new transaction to DataFrame
            new_row = {
                '_index': transaction_id,
                'Chase Description': merchant,
                'Chase Amount': amount,
                'Chase Date': trans_date,
                'Business Type': business_type,
                'Review Status': 'accepted',
                'notes': notes_text,
                'Receipt File': receipt_file_str,
                'receipt_url': receipt_url_str,
                'source': 'incoming_receipt'
            }
            # Add missing columns with empty values
            for col in df.columns:
                if col not in new_row:
                    new_row[col] = ''

            df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
            print(f"   📊 Added transaction #{transaction_id} to in-memory DataFrame (now {len(df)} rows)")
        elif action == 'attached':
            # Update existing row in DataFrame
            mask = df['_index'] == matched_transaction_id
            if mask.any():
                df.loc[mask, 'Receipt File'] = receipt_file_str
                if receipt_url_str:
                    df.loc[mask, 'receipt_url'] = receipt_url_str
                print(f"   📊 Updated transaction #{matched_transaction_id} in DataFrame with receipt")

        print(f"✅ Accepted receipt {receipt_id} → transaction {transaction_id} ({action})")

        # === AUTO-SPLIT APPLE RECEIPTS ===
        # Check if this is an Apple receipt that needs splitting into personal/business
        apple_split_result = None
        if action == 'created' and receipt_files:
            # Get the first receipt file for analysis
            first_receipt = receipt_files[0] if receipt_files else None
            if first_receipt:
                # Convert to local path if needed
                if first_receipt.startswith('receipts/'):
                    receipt_path = str(RECEIPT_DIR / first_receipt.replace('receipts/', ''))
                else:
                    receipt_path = first_receipt
                apple_split_result = maybe_auto_split_apple_receipt(transaction_id, merchant, receipt_path)

        return jsonify({
            'ok': True,
            'message': f'Receipt accepted and transaction {action}',
            'transaction_id': transaction_id,
            'receipt_id': receipt_id,
            'action': action,
            'receipt_files': receipt_files,
            'apple_split': apple_split_result
        })

    except Exception as e:
        import traceback
        print(f"❌ Error accepting receipt: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/reject", methods=["POST"])
@api_key_required
def reject_incoming_receipt():
    """
    Reject an incoming receipt and learn from the pattern

    Body:
    {
        "receipt_id": 123,
        "reason": "marketing" (optional)
    }
    """
    from datetime import datetime

    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'Database not available'
            }), 500

        data = request.json
        receipt_id = data.get('receipt_id')
        reason = data.get('reason', 'user_rejected')

        if not receipt_id:
            return jsonify({
                'ok': False,
                'error': 'Missing receipt_id'
            }), 400

        conn, db_type = get_db_connection()

        # Get the receipt data
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = ?', (receipt_id,))
        receipt = cursor.fetchone()

        if not receipt:
            return_db_connection(conn)
            return jsonify({
                'ok': False,
                'error': 'Receipt not found'
            }), 404

        # Update receipt status
        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'rejected',
                rejection_reason = ?,
                reviewed_at = ?
            WHERE id = ?
        ''', (reason, datetime.now().isoformat(), receipt_id))

        # Learn from rejection - record pattern
        from_email = receipt['from_email'] if isinstance(receipt, dict) else receipt[receipt.keys().index('from_email')] if hasattr(receipt, 'keys') else None
        domain = from_email.split('@')[-1] if from_email and '@' in from_email else None

        rejection_count = 0
        if domain:
            try:
                # SQLite uses ON CONFLICT, MySQL uses ON DUPLICATE KEY
                if db_type == 'mysql':
                    cursor = db_execute(conn, db_type, '''
                        INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
                        VALUES ('domain', ?, 1, ?)
                        ON DUPLICATE KEY UPDATE
                            rejection_count = rejection_count + 1,
                            last_rejected_at = ?
                    ''', (domain, datetime.now().isoformat(), datetime.now().isoformat()))
                else:
                    cursor = db_execute(conn, db_type, '''
                        INSERT INTO incoming_rejection_patterns (pattern_type, pattern_value, rejection_count, last_rejected_at)
                        VALUES ('domain', ?, 1, ?)
                        ON CONFLICT(pattern_type, pattern_value)
                        DO UPDATE SET
                            rejection_count = rejection_count + 1,
                            last_rejected_at = ?
                    ''', (domain, datetime.now().isoformat(), datetime.now().isoformat()))

                conn.commit()

                # Get updated rejection count for this domain
                cursor = db_execute(conn, db_type, '''
                    SELECT rejection_count FROM incoming_rejection_patterns
                    WHERE pattern_type = 'domain' AND pattern_value = ?
                ''', (domain,))

                result = cursor.fetchone()
                rejection_count = result['rejection_count'] if result else 0
            except Exception as pattern_err:
                print(f"⚠️  Could not record rejection pattern: {pattern_err}")
                conn.commit()  # Still commit the status update

        return_db_connection(conn)

        print(f"✅ Rejected incoming receipt {receipt_id} from {domain} (total rejections: {rejection_count})")

        learning_message = ''
        if rejection_count >= 2:
            learning_message = f' Future emails from {domain} will be auto-filtered.'

        return jsonify({
            'ok': True,
            'message': f'Receipt rejected.{learning_message}',
            'receipt_id': receipt_id,
            'learned': rejection_count >= 2
        })

    except Exception as e:
        print(f"❌ Error rejecting receipt: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/bulk-reject", methods=["POST"])
@api_key_required
def bulk_reject_incoming_receipts():
    """
    Bulk reject multiple incoming receipts at once.
    Supports admin_key for API access.

    Body:
    {
        "receipt_ids": [123, 456, 789],
        "reason": "spam" (optional)
    }
    """
    from datetime import datetime

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        data = request.json
        receipt_ids = data.get('receipt_ids', [])
        reason = data.get('reason', 'bulk_rejected')

        if not receipt_ids or not isinstance(receipt_ids, list):
            return jsonify({'ok': False, 'error': 'Missing or invalid receipt_ids array'}), 400

        conn, db_type = get_db_connection()
        rejected = 0
        errors = []

        for receipt_id in receipt_ids:
            try:
                # Update each receipt to rejected status
                if db_type == 'mysql':
                    db_execute(conn, db_type, '''
                        UPDATE incoming_receipts
                        SET status = 'rejected',
                            rejection_reason = %s,
                            reviewed_at = NOW()
                        WHERE id = %s AND status = 'pending'
                    ''', (reason, receipt_id))
                else:
                    db_execute(conn, db_type, '''
                        UPDATE incoming_receipts
                        SET status = 'rejected',
                            rejection_reason = ?,
                            reviewed_at = ?
                        WHERE id = ? AND status = 'pending'
                    ''', (reason, datetime.now().isoformat(), receipt_id))
                rejected += 1
            except Exception as e:
                errors.append(f"ID {receipt_id}: {str(e)}")

        conn.commit()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'rejected': rejected,
            'total_requested': len(receipt_ids),
            'errors': errors if errors else None
        })

    except Exception as e:
        print(f"Error bulk rejecting receipts: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/unreject", methods=["POST"])
@api_key_required
def unreject_incoming_receipt():
    """
    Unreject a previously rejected incoming receipt - moves it back to pending

    Body:
    {
        "receipt_id": 123
    }
    """
    from datetime import datetime

    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'Database not available'
            }), 500

        data = request.json
        receipt_id = data.get('receipt_id')

        if not receipt_id:
            return jsonify({
                'ok': False,
                'error': 'Missing receipt_id'
            }), 400

        conn, db_type = get_db_connection()

        # Get the receipt data to verify it exists and is rejected
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = ?', (receipt_id,))
        receipt = cursor.fetchone()

        if not receipt:
            return_db_connection(conn)
            return jsonify({
                'ok': False,
                'error': 'Receipt not found'
            }), 404

        # Check if it's actually rejected
        receipt_status = receipt['status'] if isinstance(receipt, dict) else receipt[list(receipt.keys()).index('status')]
        if receipt_status != 'rejected':
            return_db_connection(conn)
            return jsonify({
                'ok': False,
                'error': f'Receipt is not rejected (status: {receipt_status})'
            }), 400

        # Update receipt status back to pending
        cursor = db_execute(conn, db_type, '''
            UPDATE incoming_receipts
            SET status = 'pending',
                rejection_reason = NULL,
                reviewed_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), receipt_id))

        conn.commit()
        return_db_connection(conn)

        print(f"Unrejected incoming receipt {receipt_id}")

        return jsonify({
            'ok': True,
            'message': 'Receipt restored to pending',
            'receipt_id': receipt_id
        })

    except Exception as e:
        print(f"Error unrejecting receipt: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/reprocess-missing", methods=["GET", "POST"])
def reprocess_missing_receipts():
    """
    Re-process accepted incoming receipts that have no receipt files downloaded.
    This fixes receipts that were accepted but PDF conversion failed.
    Supports admin_key query param for API access.
    """
    import json
    import traceback
    import os as _os  # Explicit import to avoid scope shadowing with nested functions

    # Check admin key or login
    admin_key = request.args.get('admin_key')
    expected_key = _os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key and not session.get('logged_in'):
        return jsonify({'error': 'Authentication required'}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()

        # Find accepted incoming receipts where transaction has no receipt files
        query = '''
            SELECT
                ir.id as incoming_id,
                ir.email_id,
                ir.gmail_account,
                ir.subject,
                ir.merchant,
                ir.amount,
                ir.attachments,
                ir.accepted_as_transaction_id
            FROM incoming_receipts ir
            LEFT JOIN transactions t ON t._index = ir.accepted_as_transaction_id
            WHERE ir.status = 'accepted'
            AND ir.email_id IS NOT NULL
            AND ir.gmail_account IS NOT NULL
            AND (t.receipt_file IS NULL OR t.receipt_file = '')
            AND (t.receipt_url IS NULL OR t.receipt_url = '')
        '''

        cursor = db_execute(conn, db_type, query)
        rows = cursor.fetchall()

        if not rows:
            return_db_connection(conn)
            return jsonify({
                'ok': True,
                'message': 'No missing receipts found - all accepted incoming receipts have files!',
                'processed': 0,
                'success': 0,
                'failed': 0
            })

        print(f"🔄 Re-processing {len(rows)} accepted receipts with missing files...")

        # Inline helper functions instead of importing from incoming_receipts_service
        # (which has sqlite3 dependencies that fail on Railway)
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build
        from PIL import Image
        import fitz  # PyMuPDF

        def _load_gmail_service_inline(account_email):
            """Load Gmail service using existing credentials system"""
            creds, error = get_gmail_credentials_with_autorefresh(account_email)
            if error or not creds:
                print(f"   ⚠️ Gmail creds failed for {account_email}: {error}")
                return None
            try:
                return build('gmail', 'v1', credentials=creds)
            except Exception as e:
                print(f"   ⚠️ Gmail build failed: {e}")
                return None

        def _download_attachment(service, message_id, attachment_id):
            """Download attachment from Gmail"""
            try:
                attachment = service.users().messages().attachments().get(
                    userId='me', messageId=message_id, id=attachment_id
                ).execute()
                import base64
                return base64.urlsafe_b64decode(attachment['data'].encode('UTF-8'))
            except Exception as e:
                print(f"      ⚠️ Download error: {e}")
                return None

        def _convert_pdf_to_jpg(pdf_bytes, output_path):
            """Convert PDF to JPG using PyMuPDF"""
            try:
                doc = fitz.open(stream=pdf_bytes, filetype="pdf")
                page = doc[0]
                mat = fitz.Matrix(200/72, 200/72)
                pix = page.get_pixmap(matrix=mat)
                png_path = output_path.replace('.jpg', '_temp.png')
                pix.save(png_path)
                doc.close()
                with Image.open(png_path) as img:
                    if img.mode in ('RGBA', 'LA', 'P'):
                        img = img.convert('RGB')
                    img.save(output_path, 'JPEG', quality=90)
                if _os.path.exists(png_path):
                    _os.remove(png_path)
                return output_path
            except Exception as e:
                print(f"      ⚠️ PDF conversion failed: {e}")
                return None

        def _process_receipt_files_inline(service, email_id, attachments, html_body=None):
            """Process receipt files and upload to R2"""
            saved_files = []
            local_files = []
            receipts_dir = "receipts/incoming"
            _os.makedirs(receipts_dir, exist_ok=True)
            base_filename = f"receipt_{email_id[:12]}"

            for i, attachment in enumerate(attachments):
                filename = attachment.get('filename', '')
                attachment_id = attachment.get('attachment_id', '')
                if not attachment_id:
                    continue
                print(f"      📎 Downloading: {filename}")
                file_data = _download_attachment(service, email_id, attachment_id)
                if not file_data:
                    continue
                if filename.lower().endswith('.pdf'):
                    output_path = _os.path.join(receipts_dir, f"{base_filename}_att{i}.jpg")
                    result = _convert_pdf_to_jpg(file_data, output_path)
                    if result:
                        local_files.append(result)
                    else:
                        pdf_output = _os.path.join(receipts_dir, f"{base_filename}_att{i}.pdf")
                        with open(pdf_output, 'wb') as f:
                            f.write(file_data)
                        local_files.append(pdf_output)
                else:
                    output_path = _os.path.join(receipts_dir, f"{base_filename}_att{i}_{filename}")
                    with open(output_path, 'wb') as f:
                        f.write(file_data)
                    local_files.append(output_path)

            # Upload to R2
            try:
                from r2_service import upload_to_r2, R2_ENABLED
                if R2_ENABLED:
                    for local_path in local_files:
                        filename = _os.path.basename(local_path)
                        r2_key = f"receipts/incoming/{filename}"
                        success, result = upload_to_r2(local_path, r2_key)
                        if success:
                            saved_files.append(result)
                        else:
                            saved_files.append(local_path)
                else:
                    saved_files = local_files
            except ImportError:
                saved_files = local_files
            return saved_files

        success_count = 0
        fail_count = 0
        results = []

        for row in rows:
            row = dict(row)
            incoming_id = row['incoming_id']
            email_id = row['email_id']
            gmail_account = row['gmail_account']
            merchant = row.get('merchant') or 'Unknown'
            amount = row.get('amount') or 0
            txn_index = row.get('accepted_as_transaction_id')
            attachments_str = row.get('attachments') or '[]'

            print(f"📧 Processing: {merchant} ${amount} (Incoming #{incoming_id})")

            try:
                attachments = json.loads(attachments_str)
                if not attachments:
                    print(f"   ⚠️  No attachments")
                    fail_count += 1
                    results.append({'id': incoming_id, 'merchant': merchant, 'status': 'no_attachments'})
                    continue

                # Load Gmail service
                service = _load_gmail_service_inline(gmail_account)
                if not service:
                    print(f"   ❌ Gmail service failed")
                    fail_count += 1
                    results.append({'id': incoming_id, 'merchant': merchant, 'status': 'gmail_failed'})
                    continue

                # Get HTML body
                html_body = None
                try:
                    msg_data = service.users().messages().get(userId='me', id=email_id, format='full').execute()
                    def get_html_body(payload):
                        if 'parts' in payload:
                            for part in payload['parts']:
                                if part.get('mimeType') == 'text/html':
                                    import base64
                                    data = part.get('body', {}).get('data', '')
                                    if data:
                                        return base64.urlsafe_b64decode(data).decode('utf-8', errors='ignore')
                        return ''
                    html_body = get_html_body(msg_data.get('payload', {}))
                except Exception as e:
                    print(f"   ⚠️  Could not get email body: {e}")

                # Process receipt files
                receipt_files = _process_receipt_files_inline(service, email_id, attachments, html_body)

                if not receipt_files:
                    print(f"   ❌ No files downloaded")
                    fail_count += 1
                    results.append({'id': incoming_id, 'merchant': merchant, 'status': 'download_failed'})
                    continue

                print(f"   ✅ Downloaded {len(receipt_files)} file(s)")

                # Separate R2 URLs from local paths
                r2_urls = [f for f in receipt_files if f.startswith('http')]
                local_files = [f for f in receipt_files if not f.startswith('http')]
                import os
                receipt_file_str = ', '.join([os.path.basename(f) for f in local_files]) if local_files else ''
                receipt_url_str = r2_urls[0] if r2_urls else ''

                # Update transaction
                if txn_index:
                    db_execute(conn, db_type, '''
                        UPDATE transactions
                        SET receipt_file = COALESCE(NULLIF(?, ''), receipt_file),
                            receipt_url = COALESCE(NULLIF(?, ''), receipt_url)
                        WHERE _index = ?
                    ''', (receipt_file_str, receipt_url_str, txn_index))
                    conn.commit()

                # Update incoming_receipts
                db_execute(conn, db_type, 'UPDATE incoming_receipts SET receipt_files = ? WHERE id = ?',
                          (json.dumps(receipt_files), incoming_id))
                conn.commit()

                success_count += 1
                results.append({'id': incoming_id, 'merchant': merchant, 'status': 'success', 'files': len(receipt_files)})

            except Exception as e:
                print(f"   ❌ Error: {e}")
                fail_count += 1
                results.append({'id': incoming_id, 'merchant': merchant, 'status': 'error', 'error': str(e)})

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'Re-processed {len(rows)} receipts: {success_count} success, {fail_count} failed',
            'processed': len(rows),
            'success': success_count,
            'failed': fail_count,
            'results': results
        })

    except Exception as e:
        print(f"❌ Error reprocessing receipts: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/recategorize", methods=["POST"])
def recategorize_transactions():
    """
    Re-categorize all transactions using smart pattern matching.
    Fixes issues like AI tools being categorized as "Shopping".

    Body (optional):
    {
        "dry_run": true,  // Preview changes without applying them
        "limit": 100      // Limit number of transactions to process
    }
    """
    import re

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}
    dry_run = data.get('dry_run', False)
    limit = data.get('limit', 1000)

    # Smart categorization rules - Down Home exact categories
    # Uses pattern matching for known merchants
    CATEGORY_RULES = {
        # Software & Subscriptions - AI tools, dev tools, SaaS
        'Software subscriptions': [
            r'anthropic', r'claude\.ai', r'openai', r'chatgpt',
            r'cursor', r'midjourney', r'runway', r'ideogram', r'suno',
            r'huggingface', r'davinci', r'replicate', r'stability',
            r'cloudflare', r'vercel', r'netlify', r'railway',
            r'github', r'gitlab', r'bitbucket',
            r'notion', r'linear', r'figma', r'canva',
            r'spotify', r'apple\.com/bill', r'netflix', r'hulu', r'disney',
            r'adobe', r'dropbox', r'google storage', r'icloud',
            r'expensify', r'quickbooks', r'freshbooks',
            r'zoom', r'slack', r'discord nitro',
            r'every studio', r'replit', r'codespace',
            r'subscription', r'monthly fee', r'annual plan',
            r'stripe', r'aws', r'google cloud', r'azure',
            # Additional software found in Shopping
            r'im-ada\.ai', r'ada\.ai', r'calendarbridge', r'sourcegraph',
            r'chartmetric', r'elementor', r'shoeboxed', r'taskade',
            r'pika\.art', r'rostr', r'prime video', r'disco\b',
            r'dashlane', r'responsive-menu', r'topaz labs', r'obsidian',
            r'apple\.com', r'bestbuy\.com',
        ],
        # Travel - Airfare
        'DH: Travel Costs - Airfare': [
            r'southwest', r'southwes\b', r'delta', r'united', r'american air',
            r'jet ?blue', r'frontier', r'spirit', r'alaska air',
            r'airline', r'airways', r'air canada',
        ],
        # Travel - Hotel
        'DH: Travel Costs - Hotel': [
            r'hotel', r'marriott', r'hilton', r'hyatt', r'airbnb', r'vrbo',
            r'sheraton', r'westin', r'w hotel', r'intercontinental',
            r'holiday inn', r'hampton', r'embassy suites', r'omni',
            r'nobu hotel', r'soho grand', r'boutique hotel',
            r'lodging', r'resort', r'inn\b',
            # Specific Nashville hotels
            r'w nashville', r'le meridien', r'thompson nashville',
            r'hermitage hotel', r'hutton hotel', r'virgin hotels',
            r'joseph hotel', r'dream nashville', r'noelle',
        ],
        # Travel - Cab/Uber/Bus
        'DH: Travel Costs - Cab/Uber/Bus Fare': [
            r'\buber\b', r'\blyft\b', r'taxi', r'\bcab\b',
            r'yellow cab', r'curb', r'gett',
            r'greyhound', r'megabus', r'transit',
            r'amtrak', r'train',
        ],
        # Travel - Gas/Rental Car (including parking)
        'DH: Travel Costs - Gas/Rental Car': [
            r'hertz', r'enterprise', r'budget', r'avis', r'national car',
            r'rental car', r'car rental',
            r'shell', r'exxon', r'chevron', r'bp\b', r'mobil',
            r'gas station', r'fuel', r'gasoline',
            # Parking
            r'parking', r'pmc', r'metropolis', r'garage', r'spot hero',
            r'park happy', r'belcourt lot', r'park mobile', r'spothero',
            r'parkwhiz', r'bestparking', r'premier parking',
        ],
        # Meals - Travel
        'DH: Travel costs - Meals': [
            # This is contextual - meals while traveling
            # Will need business_type check in logic
        ],
        # Company Meetings and Meals (non-client internal)
        'Company Meetings and Meals': [
            # Soho House variations
            r'soho house', r'sh nashville', r'sh\s+nashville', r'\bsh\b.*nashville',
            # General dining
            r'restaurant', r'cafe',
            r'starbucks', r'dunkin', r'doordash', r'uber eats', r'grubhub',
            r'postmates', r'seamless', r'caviar',
            r'bar\b', r'grill', r'pub\b', r'tavern', r'taproom',
            r'kitchen', r'bistro', r'diner', r'eatery',
            r'pizza', r'burger', r'sushi', r'thai', r'mexican', r'italian',
            # Nashville specific venues
            r'optimist', r'britannia', r'hattie', r'pancho', r'catbird',
            r'husk', r'bastion', r'peninsula', r'redheaded stranger',
            r'adele', r'mas tacos', r'prince', r'bolton',
            # Generic food terms
            r'food', r'lunch', r'dinner', r'breakfast',
            r'coffee', r'bakery', r'deli',
            # Toast POS restaurants (TST* prefix)
            r'tst\*', r'tst\s',
            # Fast food chains
            r'chick-fil-a', r'wendys', r'taco bell', r'little caesars',
            r'jersey mike', r'port of sub', r'chipotle', r'mcdonalds',
            # Specific restaurants from Food & Drink
            r'del friscos', r'o-ku', r'char green', r'uncle julio',
            r'first watch', r'marsh house', r'audrey', r'mafiaoza',
            r'chuy', r'bongo java', r'losers', r'smokin thighs',
            r'fido', r'crows nest', r'il forno', r'flora.*bama',
            r'broadway brewhouse', r'americano lounge', r'binion',
            r'goat mount', r'sodexo', r'two hands', r'tony.*benny',
            r'urban juicer', r'wharf f', r'the forum.*levy',
            r'desert star', r'chow fun', r'cosmopol', r'blue ribbon',
            r'bonanno', r'nadeen', r'slim.*husk', r'lulu.*landing',
        ],
        # Client Business Meals (with DH prefix for Down Home client work)
        'DH: BD: Client Business Meals': [
            # Will be set based on ai_note mentioning "client" or specific known client names
        ],
        # Non-DH client meals
        'BD: Client Business Meals': [
            # For other business entities
        ],
        # Office Supplies
        'Office Supplies': [
            r'office depot', r'staples', r'office max',
            r'printer', r'scanner', r'paper', r'supplies',
            r'desk', r'chair', r'furniture',
            r'best buy', r'micro center',
        ],
        # Internet
        'Internet Costs': [
            r'comcast', r'xfinity', r'spectrum', r'cox',
            r'att.*internet', r'fiber', r'broadband',
            r'verizon fios', r'vzwrlss', r'verizon wireless',
            r't-mobile', r'at&t wireless',
        ],
        # Advertising
        'BD: Advertising & Promotion': [
            r'facebook ads', r'google ads', r'meta ads',
            r'linkedin ads', r'twitter ads', r'instagram ads',
            r'advertising', r'promotion', r'marketing',
            r'pr agency', r'billboard',
        ],
    }

    try:
        conn, db_type = get_db_connection()

        # Get all transactions with business_type for context
        cursor = db_execute(conn, db_type, '''
            SELECT _index, chase_description, chase_category, chase_amount,
                   business_type, ai_note
            FROM transactions
            ORDER BY chase_date DESC
            LIMIT ?
        ''', (limit,))

        transactions = [dict(row) for row in cursor.fetchall()]

        changes = []
        for tx in transactions:
            idx = tx['_index']
            desc = (tx['chase_description'] or '').lower()
            old_cat = tx['chase_category'] or ''
            biz_type = (tx['business_type'] or '').lower()
            ai_note = (tx['ai_note'] or '').lower()
            new_cat = None

            # Determine if this is Down Home business (for DH: prefix)
            is_dh = 'down home' in biz_type or 'downhome' in biz_type or 'dh' in biz_type

            # Check for client context (for BD: categories)
            is_client = 'client' in ai_note or 'meeting with' in ai_note

            # Try each category's patterns
            for category, patterns in CATEGORY_RULES.items():
                if not patterns:  # Skip empty pattern lists
                    continue
                for pattern in patterns:
                    if re.search(pattern, desc, re.IGNORECASE):
                        new_cat = category
                        break
                if new_cat:
                    break

            # Apply DH: prefix ONLY for Down Home business transactions
            # For non-DH businesses, use base category without prefix
            if new_cat and new_cat.startswith('DH: '):
                if not is_dh:
                    # Remove DH: prefix for non-Down Home transactions
                    new_cat = new_cat.replace('DH: ', '')

            # Special logic for meals - check if client-related
            if new_cat == 'Company Meetings and Meals' and is_client:
                if is_dh:
                    new_cat = 'DH: BD: Client Business Meals'
                else:
                    new_cat = 'BD: Client Business Meals'

            # Only record if category changed
            if new_cat and new_cat != old_cat:
                changes.append({
                    '_index': idx,
                    'description': tx['chase_description'],
                    'old_category': old_cat,
                    'new_category': new_cat,
                    'business_type': tx['business_type'] or ''
                })

        # Apply changes if not dry run
        updated_count = 0
        if not dry_run and changes:
            for change in changes:
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET chase_category = ?
                    WHERE _index = ?
                ''', (change['new_category'], change['_index']))
                updated_count += 1
            conn.commit()

        return_db_connection(conn)

        # Group changes by category for summary
        by_category = {}
        for c in changes:
            cat = c['new_category']
            if cat not in by_category:
                by_category[cat] = []
            by_category[cat].append(c['description'][:40])

        return jsonify({
            'ok': True,
            'dry_run': dry_run,
            'total_scanned': len(transactions),
            'changes_needed': len(changes),
            'changes_applied': updated_count if not dry_run else 0,
            'by_category': {k: len(v) for k, v in by_category.items()},
            'sample_changes': changes[:20]  # Show first 20 changes
        })

    except Exception as e:
        print(f"❌ Error recategorizing: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/fix-dates", methods=["POST"])
def fix_incoming_receipt_dates():
    """
    Fix transactions that came from incoming_receipts but have wrong dates.
    Updates chase_date to match the actual receipt date from incoming_receipts.

    Body (optional):
    {
        "dry_run": true  // Preview changes without applying them
    }
    """
    import traceback
    import pymysql

    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', False)

        conn, db_type = get_db_connection()
        if not conn:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        if db_type == 'mysql':
            cursor = conn.cursor(pymysql.cursors.DictCursor)
        else:
            cursor = conn.cursor()

        # Find transactions with wrong dates
        # These are transactions created from incoming_receipts where chase_date != received_date
        # First, check if receipt_date column exists (might be missing in older databases)
        has_receipt_date = True
        try:
            cursor.execute("SELECT receipt_date FROM incoming_receipts LIMIT 1")
            cursor.fetchone()
        except Exception:
            has_receipt_date = False
            # Add the column if it doesn't exist
            try:
                if db_type == 'mysql':
                    cursor.execute("ALTER TABLE incoming_receipts ADD COLUMN receipt_date DATE")
                    conn.commit()
                    print("Added receipt_date column to incoming_receipts")
            except Exception as e:
                print(f"Could not add receipt_date column: {e}")

        # Use appropriate query based on column availability
        if has_receipt_date:
            query = '''
                SELECT
                    ir.id as incoming_id,
                    ir.received_date as correct_date,
                    ir.receipt_date,
                    ir.merchant,
                    ir.amount,
                    ir.accepted_as_transaction_id as txn_id,
                    t._index,
                    t.chase_date as old_chase_date,
                    t.chase_description,
                    t.created_at
                FROM incoming_receipts ir
                INNER JOIN transactions t ON t._index = ir.accepted_as_transaction_id
                WHERE ir.status = 'accepted'
                AND ir.accepted_as_transaction_id IS NOT NULL
                AND DATE(t.chase_date) != DATE(COALESCE(ir.receipt_date, ir.received_date))
            '''
        else:
            # Fallback query using only received_date
            query = '''
                SELECT
                    ir.id as incoming_id,
                    ir.received_date as correct_date,
                    NULL as receipt_date,
                    ir.merchant,
                    ir.amount,
                    ir.accepted_as_transaction_id as txn_id,
                    t._index,
                    t.chase_date as old_chase_date,
                    t.chase_description,
                    t.created_at
                FROM incoming_receipts ir
                INNER JOIN transactions t ON t._index = ir.accepted_as_transaction_id
                WHERE ir.status = 'accepted'
                AND ir.accepted_as_transaction_id IS NOT NULL
                AND DATE(t.chase_date) != DATE(ir.received_date)
            '''

        cursor.execute(query)
        raw_rows = cursor.fetchall()

        # Convert to dicts for SQLite compatibility
        if db_type == 'sqlite':
            rows = [dict(r) for r in raw_rows]
        else:
            rows = raw_rows

        if not rows:
            cursor.close()
            return_db_connection(conn)
            return jsonify({
                'ok': True,
                'message': 'All transaction dates are correct!',
                'fixed': 0
            })

        results = []
        fixed_count = 0

        for row in rows:
            # Use received_date (email date) as authoritative - it's the correct_date column in our query
            correct_date = row['correct_date'] or row['receipt_date']
            if correct_date:
                # Ensure it's a string in YYYY-MM-DD format
                if hasattr(correct_date, 'strftime'):
                    correct_date = correct_date.strftime('%Y-%m-%d')
                else:
                    correct_date = str(correct_date).split('T')[0].split(' ')[0]

            result = {
                'txn_id': row['txn_id'],
                'merchant': row['merchant'] or row['chase_description'],
                'amount': float(row['amount']) if row['amount'] else 0,
                'old_date': str(row['old_chase_date']),
                'new_date': correct_date
            }

            if not dry_run and correct_date:
                # Update the transaction date - use ? for SQLite, %s for MySQL
                if db_type == 'mysql':
                    cursor.execute('''
                        UPDATE transactions
                        SET chase_date = %s
                        WHERE _index = %s
                    ''', (correct_date, row['txn_id']))
                else:
                    cursor.execute('''
                        UPDATE transactions
                        SET chase_date = ?
                        WHERE _index = ?
                    ''', (correct_date, row['txn_id']))
                fixed_count += 1
                result['fixed'] = True
            else:
                result['fixed'] = False

            results.append(result)

        if not dry_run:
            conn.commit()

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'{"Would fix" if dry_run else "Fixed"} {len(rows)} transaction dates',
            'dry_run': dry_run,
            'fixed': fixed_count if not dry_run else 0,
            'found': len(rows),
            'results': results
        })

    except Exception as e:
        print(f"❌ Error fixing dates: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/date-diagnosis", methods=["GET"])
def diagnose_incoming_dates():
    """
    Diagnostic endpoint to analyze date fields for incoming receipts.
    Shows received_date, transaction_date, receipt_date, and linked transaction dates.

    Query params:
    - merchants: comma-separated list of merchant names to filter (e.g., "railway,taskade,midjourney")
    """
    import pymysql

    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        merchants_filter = request.args.get('merchants', '').lower().split(',')
        merchants_filter = [m.strip() for m in merchants_filter if m.strip()]

        conn, db_type = get_db_connection()
        if not conn:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        if db_type == 'mysql':
            cursor = conn.cursor(pymysql.cursors.DictCursor)
        else:
            cursor = conn.cursor()

        # Get all incoming receipts with their date fields and linked transactions
        query = '''
            SELECT
                ir.id,
                ir.merchant,
                ir.amount,
                ir.received_date as email_date,
                ir.transaction_date as ocr_date,
                ir.receipt_date,
                ir.subject,
                ir.status,
                ir.accepted_as_transaction_id as linked_txn_id,
                t._index as txn_index,
                t.chase_date as txn_chase_date,
                t.chase_description,
                t.chase_amount as txn_amount
            FROM incoming_receipts ir
            LEFT JOIN transactions t ON t._index = ir.accepted_as_transaction_id
            ORDER BY ir.received_date DESC
            LIMIT 100
        '''

        cursor.execute(query)
        raw_rows = cursor.fetchall()

        if db_type == 'sqlite':
            rows = [dict(r) for r in raw_rows]
        else:
            rows = raw_rows

        cursor.close()
        return_db_connection(conn)

        # Filter by merchants if specified
        if merchants_filter:
            filtered_rows = []
            for row in rows:
                merchant = (row.get('merchant') or '').lower()
                subject = (row.get('subject') or '').lower()
                for m in merchants_filter:
                    if m in merchant or m in subject:
                        filtered_rows.append(row)
                        break
            rows = filtered_rows

        # Analyze each row
        results = []
        for row in rows:
            # Convert dates to strings
            email_date = str(row.get('email_date') or '')[:10]
            ocr_date = str(row.get('ocr_date') or '')[:10]
            receipt_date = str(row.get('receipt_date') or '')[:10]
            txn_chase_date = str(row.get('txn_chase_date') or '')[:10]

            # Determine what date SHOULD be used (email date from Gmail)
            correct_date = email_date

            # Check for issues
            issues = []
            if row.get('linked_txn_id') and txn_chase_date and txn_chase_date != email_date:
                issues.append(f"Transaction date {txn_chase_date} != email date {email_date}")
            if ocr_date and ocr_date != email_date:
                issues.append(f"OCR date {ocr_date} != email date {email_date}")

            results.append({
                'id': row.get('id'),
                'merchant': row.get('merchant'),
                'amount': float(row.get('amount') or 0),
                'status': row.get('status'),
                'dates': {
                    'email_date': email_date,
                    'ocr_date': ocr_date,
                    'receipt_date': receipt_date,
                    'correct_date': correct_date
                },
                'linked_transaction': {
                    'id': row.get('linked_txn_id'),
                    'chase_date': txn_chase_date,
                    'description': row.get('chase_description'),
                    'amount': float(row.get('txn_amount') or 0) if row.get('txn_amount') else None
                } if row.get('linked_txn_id') else None,
                'issues': issues,
                'subject': row.get('subject')
            })

        # Separate into categories
        with_issues = [r for r in results if r['issues']]

        return jsonify({
            'ok': True,
            'total': len(results),
            'with_issues': len(with_issues),
            'merchants_filtered': merchants_filter if merchants_filter else 'all',
            'results': results,
            'issues_only': with_issues
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/refetch-gmail-dates", methods=["POST"])
def refetch_gmail_dates():
    """
    Re-fetch the correct dates from Gmail for incoming receipts.
    Uses the stored email_id to query Gmail API and get the actual Date header.

    This fixes receipts where the received_date was stored with wrong year (2025 instead of 2024).

    Body (optional):
    {
        "dry_run": true,  // Preview changes without applying them
        "merchants": ["railway", "taskade", "midjourney"],  // specific merchants to fix
        "limit": 50  // max number of receipts to process
    }
    """
    import traceback
    import pymysql
    from email.utils import parsedate_to_datetime

    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', False)
        merchants_filter = data.get('merchants', [])
        limit = min(data.get('limit', 50), 100)  # Max 100 at a time

        conn, db_type = get_db_connection()
        if not conn:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        if db_type == 'mysql':
            cursor = conn.cursor(pymysql.cursors.DictCursor)
        else:
            cursor = conn.cursor()

        # Find receipts with potentially wrong dates (2025 in date string or needs fix)
        # Focus on receipts that have email_id stored
        if db_type == 'mysql':
            # Note: %% escapes % in Python string formatting for pymysql
            query = '''
                SELECT id, email_id, gmail_account, merchant, subject, received_date
                FROM incoming_receipts
                WHERE email_id IS NOT NULL
                AND email_id != ''
                AND (received_date LIKE '%%2025%%' OR received_date NOT LIKE '____-__-__')
                ORDER BY id DESC
                LIMIT %s
            '''
            cursor.execute(query, (limit,))
        else:
            query = '''
                SELECT id, email_id, gmail_account, merchant, subject, received_date
                FROM incoming_receipts
                WHERE email_id IS NOT NULL
                AND email_id != ''
                AND (received_date LIKE '%2025%' OR received_date NOT LIKE '____-__-__')
                ORDER BY id DESC
                LIMIT ?
            '''
            cursor.execute(query, (limit,))

        raw_rows = cursor.fetchall()

        # Convert to dicts for SQLite compatibility
        if db_type == 'sqlite':
            rows = [dict(r) for r in raw_rows]
        else:
            rows = list(raw_rows)

        if not rows:
            cursor.close()
            return_db_connection(conn)
            return jsonify({
                'ok': True,
                'message': 'No receipts with potentially wrong dates found',
                'processed': 0
            })

        # Filter by merchant if specified
        if merchants_filter:
            merchants_lower = [m.lower() for m in merchants_filter]
            rows = [r for r in rows if any(
                m in (r.get('merchant') or '').lower() or
                m in (r.get('subject') or '').lower()
                for m in merchants_lower
            )]

        results = []
        fixed_count = 0
        errors = []

        # Group by gmail_account to minimize service creation
        by_account = {}
        for row in rows:
            account = row.get('gmail_account', 'kaplan.brian@gmail.com')
            if account not in by_account:
                by_account[account] = []
            by_account[account].append(row)

        for account_email, account_rows in by_account.items():
            # Get Gmail service for this account
            service, error = get_gmail_service(account_email)
            if not service:
                errors.append({
                    'account': account_email,
                    'error': f'Could not get Gmail service: {error}',
                    'affected_count': len(account_rows)
                })
                continue

            for row in account_rows:
                email_id = row.get('email_id')
                old_date = row.get('received_date')

                result = {
                    'id': row.get('id'),
                    'email_id': email_id,
                    'merchant': row.get('merchant') or row.get('subject', '')[:50],
                    'old_date': old_date,
                    'new_date': None,
                    'fixed': False
                }

                try:
                    # Fetch the email from Gmail
                    msg = service.users().messages().get(
                        userId='me',
                        id=email_id,
                        format='metadata',
                        metadataHeaders=['Date']
                    ).execute()

                    # Extract the Date header
                    headers = msg.get('payload', {}).get('headers', [])
                    date_header = None
                    for h in headers:
                        if h.get('name', '').lower() == 'date':
                            date_header = h.get('value')
                            break

                    if date_header:
                        # Parse the RFC 2822 date to get proper datetime
                        try:
                            dt = parsedate_to_datetime(date_header)
                            new_date = dt.strftime('%Y-%m-%d')
                            result['new_date'] = new_date
                            result['raw_gmail_date'] = date_header

                            if not dry_run:
                                # Update the incoming_receipt with correct date
                                if db_type == 'mysql':
                                    cursor.execute('''
                                        UPDATE incoming_receipts
                                        SET received_date = %s
                                        WHERE id = %s
                                    ''', (new_date, row.get('id')))
                                else:
                                    cursor.execute('''
                                        UPDATE incoming_receipts
                                        SET received_date = ?
                                        WHERE id = ?
                                    ''', (new_date, row.get('id')))

                                fixed_count += 1
                                result['fixed'] = True
                        except Exception as parse_err:
                            result['error'] = f'Date parse error: {parse_err}'
                    else:
                        result['error'] = 'No Date header found in email'

                except Exception as gmail_err:
                    error_str = str(gmail_err)
                    if '404' in error_str or 'not found' in error_str.lower():
                        result['error'] = 'Email not found in Gmail (may be deleted)'
                    else:
                        result['error'] = f'Gmail API error: {gmail_err}'

                results.append(result)

        if not dry_run and fixed_count > 0:
            conn.commit()

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'message': f'{"Would fix" if dry_run else "Fixed"} {fixed_count} of {len(rows)} receipts',
            'dry_run': dry_run,
            'fixed': fixed_count,
            'processed': len(results),
            'results': results,
            'errors': errors if errors else None
        })

    except Exception as e:
        print(f"❌ Error refetching Gmail dates: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/scan", methods=["POST"])
def scan_incoming_receipts():
    """
    Trigger a manual scan of Gmail accounts for new receipts.
    Also runs auto-match after scanning to attach receipts to transactions.

    Body (optional):
    {
        "accounts": ["kaplan.brian@gmail.com"],  // specific accounts, or leave empty for all
        "since_date": "2024-09-01",  // optional date filter
        "auto_match": true  // automatically match receipts after scanning (default: true)
    }
    """
    import sqlite3
    from datetime import datetime

    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'SQLite not available'
            }), 500

        data = request.json or {}
        specific_accounts = data.get('accounts', [])
        since_date = data.get('since_date', '2024-09-01')

        # Import the scanning functions
        try:
            from incoming_receipts_service import scan_gmail_for_new_receipts, save_incoming_receipt
        except ImportError as e:
            return jsonify({
                'ok': False,
                'error': f'incoming_receipts_service.py not found: {e}'
            }), 500

        # Default accounts
        all_accounts = [
            'kaplan.brian@gmail.com',
            'brian@downhome.com',
            'brian@musiccityrodeo.com'
        ]

        # Use specific accounts if provided, otherwise all
        accounts_to_scan = specific_accounts if specific_accounts else all_accounts

        print(f"🔍 Scanning {len(accounts_to_scan)} Gmail account(s) for new receipts...")

        results = {
            'scanned_accounts': [],
            'total_found': 0,
            'total_new': 0,
            'errors': []
        }

        for account in accounts_to_scan:
            try:
                print(f"\n📧 Scanning {account}...")
                receipts = scan_gmail_for_new_receipts(account, since_date)

                new_count = 0
                for receipt in receipts:
                    receipt_id = save_incoming_receipt(receipt)
                    if receipt_id:
                        new_count += 1

                results['scanned_accounts'].append({
                    'account': account,
                    'found': len(receipts),
                    'new': new_count
                })

                results['total_found'] += len(receipts)
                results['total_new'] += new_count

            except Exception as scan_error:
                error_msg = f"Error scanning {account}: {str(scan_error)}"
                print(f"   ❌ {error_msg}")
                results['errors'].append(error_msg)

        print(f"\n✅ Scan complete: {results['total_new']} new receipts added")

        # Auto-match if enabled (default: true)
        auto_match_enabled = data.get('auto_match', True)
        auto_match_results = None

        if auto_match_enabled and results['total_new'] > 0:
            try:
                from smart_auto_matcher import auto_match_pending_receipts, ensure_hash_table

                conn, db_type = get_db_connection()
                if db_type == 'mysql':
                    print("🔄 Running auto-match on new receipts...")
                    ensure_hash_table(conn)
                    auto_match_results = auto_match_pending_receipts(conn)
                    print(f"   ✅ Auto-matched: {auto_match_results.get('auto_matched', 0)}")
                    print(f"   📋 Needs review: {auto_match_results.get('needs_review', 0)}")
                return_db_connection(conn)
            except Exception as match_err:
                print(f"   ⚠️ Auto-match failed: {match_err}")
                auto_match_results = {'error': str(match_err)}

        return jsonify({
            'ok': True,
            'message': f"Found {results['total_new']} new receipts",
            'results': results,
            'auto_match': auto_match_results
        })

    except Exception as e:
        print(f"❌ Error during scan: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/admin/cleanup-broken-receipt-urls", methods=["POST"])
def cleanup_broken_receipt_urls():
    """
    Clean up broken receipt URLs in the database.
    Removes URLs that are:
    - NO_RECEIPT placeholders
    - Screenshot URLs with unicode characters (often 404)
    - Truncated /receipts URLs without filenames

    Admin key required.
    """
    admin_key = request.json.get('admin_key') if request.json else request.args.get('admin_key')
    admin_key = admin_key or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not expected_key or admin_key != expected_key:
        return jsonify({'error': 'Admin key required', 'ok': False}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Patterns to clean up
        cleanup_results = {
            'no_receipt_placeholders': 0,
            'screenshot_urls': 0,
            'truncated_urls': 0,
            'total_cleaned': 0
        }

        # 1. Clear NO_RECEIPT placeholder URLs
        cursor.execute("""
            UPDATE transactions
            SET receipt_url = NULL, r2_url = NULL
            WHERE (receipt_url LIKE '%NO_RECEIPT%' OR r2_url LIKE '%NO_RECEIPT%')
        """)
        cleanup_results['no_receipt_placeholders'] = cursor.rowcount

        # 2. Clear Screenshot URLs with unicode characters (broken uploads)
        cursor.execute("""
            UPDATE transactions
            SET receipt_url = NULL, r2_url = NULL
            WHERE (receipt_url LIKE '%Screenshot%%' AND receipt_url LIKE '%%E2%%80%%')
               OR (r2_url LIKE '%Screenshot%%' AND r2_url LIKE '%%E2%%80%%')
        """)
        cleanup_results['screenshot_urls'] = cursor.rowcount

        # 3. Clear truncated URLs ending with /receipts
        cursor.execute("""
            UPDATE transactions
            SET receipt_url = NULL, r2_url = NULL
            WHERE receipt_url LIKE '%/receipts'
               OR r2_url LIKE '%/receipts'
        """)
        cleanup_results['truncated_urls'] = cursor.rowcount

        conn.commit()
        return_db_connection(conn)

        cleanup_results['total_cleaned'] = (
            cleanup_results['no_receipt_placeholders'] +
            cleanup_results['screenshot_urls'] +
            cleanup_results['truncated_urls']
        )

        return jsonify({
            'ok': True,
            'message': f"Cleaned up {cleanup_results['total_cleaned']} broken receipt URLs",
            'details': cleanup_results
        })

    except Exception as e:
        print(f"❌ Error cleaning up broken URLs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/admin/sync-receipt-urls", methods=["POST"])
@login_required
def sync_receipt_urls():
    """
    Sync receipt URLs from the bundled CSV file to MySQL.
    This is needed because the initial SQLite→MySQL migration didn't include receipt_url.
    """
    import csv

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        # Try to load the bundled CSV file
        csv_path = BASE_DIR / 'receipt_urls_export.csv'
        if not csv_path.exists():
            return jsonify({
                'ok': False,
                'error': f'receipt_urls_export.csv not found at {csv_path}'
            }), 404

        # Read the CSV file
        url_mappings = []
        with open(csv_path, 'r') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get('receipt_url') and row.get('_index'):
                    url_mappings.append({
                        '_index': int(row['_index']),
                        'receipt_url': row['receipt_url']
                    })

        print(f"📦 Loaded {len(url_mappings)} receipt URL mappings from CSV")

        if len(url_mappings) == 0:
            return jsonify({'ok': True, 'message': 'No URLs to sync', 'updated': 0})

        # Update MySQL
        if hasattr(db, 'use_mysql') and db.use_mysql:
            conn = db.get_connection()
            cursor = conn.cursor()

            # First check if receipt_url column exists
            cursor.execute("DESCRIBE transactions")
            columns = [row[0] if isinstance(row, tuple) else row.get('Field', '') for row in cursor.fetchall()]
            print(f"📋 MySQL transactions columns: {columns}")

            if 'receipt_url' not in columns:
                # Add the column if missing
                print("⚠️  receipt_url column missing, adding it...")
                cursor.execute("ALTER TABLE transactions ADD COLUMN receipt_url VARCHAR(1000)")
                conn.commit()

            if 'r2_url' not in columns:
                print("⚠️  r2_url column missing, adding it...")
                cursor.execute("ALTER TABLE transactions ADD COLUMN r2_url VARCHAR(1000)")
                conn.commit()

            # Check how many transactions exist
            cursor.execute("SELECT COUNT(*) as cnt FROM transactions")
            total_transactions = cursor.fetchone()
            total_count = total_transactions[0] if isinstance(total_transactions, tuple) else total_transactions.get('cnt', 0)
            print(f"📊 MySQL has {total_count} transactions total")

            # Sample some _index values from MySQL
            cursor.execute("SELECT _index FROM transactions ORDER BY _index LIMIT 5")
            sample_indices = [row[0] if isinstance(row, tuple) else row.get('_index') for row in cursor.fetchall()]
            print(f"📊 Sample MySQL _index values: {sample_indices}")

            updated = 0
            failed = 0
            not_found = 0
            errors = []

            for mapping in url_mappings:
                try:
                    cursor.execute("""
                        UPDATE transactions
                        SET receipt_url = %s, r2_url = %s
                        WHERE _index = %s
                    """, (mapping['receipt_url'], mapping['receipt_url'], mapping['_index']))

                    if cursor.rowcount > 0:
                        updated += 1
                    else:
                        not_found += 1
                        if not_found <= 3:
                            print(f"⚠️  _index {mapping['_index']} not found in MySQL")
                except Exception as e:
                    failed += 1
                    errors.append(str(e))
                    if failed <= 5:
                        print(f"❌ Failed to update _index {mapping['_index']}: {e}")

            conn.commit()
            cursor.close()
            return_db_connection(conn)

            print(f"✅ Updated {updated} receipt URLs in MySQL (not_found: {not_found}, failed: {failed})")

            return jsonify({
                'ok': True,
                'message': f'Updated {updated} receipt URLs ({not_found} not found)',
                'updated': updated,
                'not_found': not_found,
                'failed': failed,
                'total_transactions': total_count,
                'errors': errors[:5] if errors else []
            })
        else:
            # SQLite update
            conn = sqlite3.connect(str(db.db_path))
            cursor = conn.cursor()

            updated = 0
            for mapping in url_mappings:
                try:
                    cursor.execute("""
                        UPDATE transactions
                        SET receipt_url = ?
                        WHERE _index = ?
                    """, (mapping['receipt_url'], mapping['_index']))
                    updated += 1
                except Exception as e:
                    print(f"⚠️  Failed to update _index {mapping['_index']}: {e}")

            conn.commit()
            return_db_connection(conn)

            return jsonify({
                'ok': True,
                'message': f'Updated {updated} receipt URLs',
                'updated': updated
            })

    except Exception as e:
        print(f"❌ Error syncing receipt URLs: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/admin/fix-missing-receipt-urls", methods=["POST"])
def fix_missing_receipt_urls():
    """
    Find transactions with receipt_file but no receipt_url and generate R2 URLs.
    This doesn't upload files - it just sets the URL assuming the file is already in R2.

    Can be called with admin_key query param or logged in session.
    """
    # Allow admin key or login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()

        # Find transactions with receipt_file but no receipt_url
        cursor = db_execute(conn, db_type, '''
            SELECT _index, receipt_file, receipt_url
            FROM transactions
            WHERE receipt_file IS NOT NULL
            AND receipt_file != ''
            AND (receipt_url IS NULL OR receipt_url = '')
        ''')

        rows = cursor.fetchall()
        print(f"📋 Found {len(rows)} transactions with receipt_file but no receipt_url")

        if not rows:
            return_db_connection(conn)
            return jsonify({
                'ok': True,
                'message': 'No transactions need fixing',
                'fixed': 0
            })

        # R2 public URL base
        R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev')

        fixed = 0
        errors = []

        for row in rows:
            try:
                idx = row['_index']
                receipt_file = row['receipt_file']

                # Generate R2 URL from receipt_file
                # Handle various formats: "file.jpg", "incoming/file.jpg", "receipts/file.jpg"
                filename = receipt_file.split(',')[0].strip()  # Take first file if multiple

                # Clean up the path
                if filename.startswith('receipts/'):
                    filename = filename[9:]

                # Build R2 URL
                receipt_url = f"{R2_PUBLIC_URL}/receipts/{filename}"

                # Update the transaction
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET receipt_url = ?
                    WHERE _index = ?
                ''', (receipt_url, idx))

                fixed += 1
                if fixed <= 10:
                    print(f"   ✓ #{idx}: {receipt_file} → {receipt_url}")

            except Exception as e:
                errors.append(f"#{row.get('_index', '?')}: {str(e)}")
                if len(errors) <= 5:
                    print(f"   ❌ Error: {e}")

        conn.commit()
        return_db_connection(conn)

        print(f"✅ Fixed {fixed} receipt URLs")

        return jsonify({
            'ok': True,
            'message': f'Fixed {fixed} receipt URLs',
            'fixed': fixed,
            'errors': errors[:10] if errors else []
        })

    except Exception as e:
        print(f"❌ Error fixing receipt URLs: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# ============================================================================
# SMART AUTO-MATCHING API
# ============================================================================

@app.route("/api/auto-match/run", methods=["POST"])
def run_auto_match():
    """
    Run smart auto-matching to connect Gmail receipts with bank transactions.
    Matches based on amount + date + merchant similarity.
    High confidence matches (75%+) are auto-attached.
    Medium confidence (50-75%) are marked for review.
    """
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        from smart_auto_matcher import (
            SmartAutoMatcher, get_unmatched_transactions, get_pending_receipts,
            auto_match_pending_receipts, ensure_hash_table
        )

        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()
        if db_type != 'mysql':
            return jsonify({'ok': False, 'error': 'Auto-match requires MySQL database'}), 400

        # Ensure hash table exists
        ensure_hash_table(conn)

        # Run auto-matching
        print("🔄 Running smart auto-match...")
        result = auto_match_pending_receipts(conn)

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            **result
        })

    except ImportError as e:
        return jsonify({'ok': False, 'error': f'Module not available: {e}'}), 500
    except Exception as e:
        print(f"❌ Auto-match error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/auto-match/preview", methods=["GET"])
def preview_auto_match():
    """
    Preview potential matches without making changes.
    Shows what would be matched if auto-match runs.
    """
    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        from smart_auto_matcher import (
            SmartAutoMatcher, get_unmatched_transactions, get_pending_receipts
        )

        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()
        if db_type != 'mysql':
            return jsonify({'ok': False, 'error': 'Preview requires MySQL database'}), 400

        # Get data
        transactions = get_unmatched_transactions(conn, days_back=90)
        receipts = get_pending_receipts(conn)

        return_db_connection(conn)

        if not transactions:
            return jsonify({
                'ok': True,
                'message': 'No unmatched transactions found',
                'transactions_count': 0,
                'receipts_count': len(receipts) if receipts else 0,
                'potential_matches': []
            })

        if not receipts:
            return jsonify({
                'ok': True,
                'message': 'No pending receipts to match',
                'transactions_count': len(transactions),
                'receipts_count': 0,
                'potential_matches': []
            })

        # Find potential matches (preview only)
        matcher = SmartAutoMatcher()

        # Convert receipts to matcher format
        receipt_dicts = []
        for r in receipts:
            receipt_dicts.append({
                'id': r['id'],
                'email_id': r['email_id'],
                'merchant': r['merchant'],
                'amount': r['amount'],
                'date': r['transaction_date'],
                'confidence_score': r['confidence_score'],
                'is_subscription': r['is_subscription'],
            })

        matches = matcher.find_matches_for_receipts(receipt_dicts, transactions)

        potential_matches = []
        for m in matches:
            if not m.get('no_match_found') and m.get('transaction'):
                potential_matches.append({
                    'receipt': {
                        'merchant': m['receipt'].get('merchant'),
                        'amount': m['receipt'].get('amount'),
                        'date': str(m['receipt'].get('date')),
                    },
                    'transaction': {
                        'index': m['transaction'].get('_index'),
                        'merchant': m['transaction'].get('chase_description'),
                        'amount': float(m['transaction'].get('chase_amount', 0)),
                        'date': str(m['transaction'].get('chase_date')),
                    },
                    'score': round(m['score'] * 100, 1),
                    'auto_match': m.get('auto_match', False),
                    'needs_review': m.get('needs_review', False),
                    'details': m.get('details', {})
                })

        return jsonify({
            'ok': True,
            'transactions_count': len(transactions),
            'receipts_count': len(receipts),
            'potential_matches': potential_matches,
            'auto_match_count': sum(1 for m in potential_matches if m['auto_match']),
            'review_count': sum(1 for m in potential_matches if m['needs_review']),
        })

    except ImportError as e:
        return jsonify({'ok': False, 'error': f'Module not available: {e}'}), 500
    except Exception as e:
        print(f"❌ Preview error: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/auto-match/check-duplicate", methods=["POST"])
def check_duplicate_receipt():
    """
    Check if a receipt image is a duplicate of an existing one.
    POST with 'file' (multipart) or 'url' (JSON body).
    """
    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        from smart_auto_matcher import DuplicateDetector

        detector = DuplicateDetector()

        # Get image data from file upload or URL
        if 'file' in request.files:
            file = request.files['file']
            image_data = file.read()
            filename = file.filename
        elif request.is_json and request.json.get('url'):
            url = request.json['url']
            response = requests.get(url, timeout=10)
            image_data = response.content
            filename = url.split('/')[-1]
        else:
            return jsonify({'ok': False, 'error': 'No file or URL provided'}), 400

        # Check for duplicate
        result = detector.is_duplicate(image_data, filename)
        is_dup, matching_file = result

        return jsonify({
            'ok': True,
            'is_duplicate': is_dup,
            'matching_file': matching_file,
            'filename': filename
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/auto-match/stats", methods=["GET"])
def auto_match_stats():
    """Get statistics about auto-matching status."""
    # Auth: admin_key OR login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        conn, db_type = get_db_connection()

        cursor = db_execute(conn, db_type, '''
            SELECT
                COUNT(*) as total_transactions,
                SUM(CASE WHEN receipt_file IS NOT NULL AND receipt_file != '' THEN 1 ELSE 0 END) as with_receipt_file,
                SUM(CASE WHEN receipt_url IS NOT NULL AND receipt_url != '' THEN 1 ELSE 0 END) as with_receipt_url,
                SUM(CASE WHEN (receipt_file IS NULL OR receipt_file = '') AND (receipt_url IS NULL OR receipt_url = '') THEN 1 ELSE 0 END) as missing_receipt
            FROM transactions
            WHERE chase_date >= DATE_SUB(CURDATE(), INTERVAL 90 DAY)
        ''')
        tx_stats = cursor.fetchone()

        # Get incoming receipts stats
        try:
            cursor = db_execute(conn, db_type, '''
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'auto_matched' THEN 1 ELSE 0 END) as auto_matched,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' THEN 1 ELSE 0 END) as rejected,
                    SUM(CASE WHEN match_type = 'needs_review' THEN 1 ELSE 0 END) as needs_review
                FROM incoming_receipts
            ''')
            receipt_stats = cursor.fetchone()
        except:
            receipt_stats = {'total': 0, 'pending': 0, 'auto_matched': 0, 'accepted': 0, 'rejected': 0, 'needs_review': 0}

        return_db_connection(conn)

        return jsonify({
            'ok': True,
            'transactions': {
                'total': tx_stats.get('total_transactions', 0),
                'with_receipt': tx_stats.get('with_receipt_url', 0) or tx_stats.get('with_receipt_file', 0),
                'missing_receipt': tx_stats.get('missing_receipt', 0),
            },
            'incoming_receipts': {
                'total': receipt_stats.get('total', 0) if receipt_stats else 0,
                'pending': receipt_stats.get('pending', 0) if receipt_stats else 0,
                'auto_matched': receipt_stats.get('auto_matched', 0) if receipt_stats else 0,
                'accepted': receipt_stats.get('accepted', 0) if receipt_stats else 0,
                'rejected': receipt_stats.get('rejected', 0) if receipt_stats else 0,
                'needs_review': receipt_stats.get('needs_review', 0) if receipt_stats else 0,
            }
        })

    except Exception as e:
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/admin/rematch-missing-receipts", methods=["POST"])
def rematch_missing_receipts():
    """
    Search R2 storage for receipts matching transactions with missing receipts.
    OCR verifies each candidate and ONLY attaches if verified.

    POST body:
    {
        "admin_key": "tallyups-admin-2024",  # required for auth
        "business_type": "Down Home",  # optional filter
        "limit": 50  # max transactions to process
    }
    """
    import boto3
    from botocore.config import Config
    import requests
    import google.generativeai as genai

    data = request.get_json(force=True) or {}

    # Check admin key
    ADMIN_KEY = os.environ.get('ADMIN_KEY', 'tallyups-admin-2024')
    if data.get('admin_key') != ADMIN_KEY:
        return jsonify({'ok': False, 'error': 'Invalid admin key'}), 401
    business_type = data.get('business_type')
    limit = min(int(data.get('limit', 50)), 100)

    # R2 config from environment
    R2_ACCOUNT_ID = os.environ.get('R2_ACCOUNT_ID', '0e5e0352d7e86c3ad2950c3c6a7f2192')
    R2_ACCESS_KEY = os.environ.get('R2_ACCESS_KEY_ID', '95db0c86dbb6d49fb1a1a9cfce31546d')
    R2_SECRET_KEY = os.environ.get('R2_SECRET_ACCESS_KEY', '1fb14eec34e2eac2f4ee89d3d64eea41ba7a7a430839bdabe46a2f3dd51dde23')
    R2_BUCKET = os.environ.get('R2_BUCKET', 'tallyups-receipts')
    R2_PUBLIC_URL = os.environ.get('R2_PUBLIC_URL', 'https://pub-f0fa143240d4452e836320be0bac6138.r2.dev')

    GEMINI_KEYS = [
        os.environ.get('GEMINI_API_KEY_1', os.environ.get('GEMINI_API_KEY', '')),
        os.environ.get('GEMINI_API_KEY_2', ''),
        os.environ.get('GEMINI_API_KEY_3', '')
    ]
    GEMINI_KEYS = [k for k in GEMINI_KEYS if k]

    if not GEMINI_KEYS:
        return jsonify({'ok': False, 'error': 'No Gemini API keys configured'}), 500

    try:
        # Connect to R2
        s3_client = boto3.client(
            's3',
            endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=R2_ACCESS_KEY,
            aws_secret_access_key=R2_SECRET_KEY,
            config=Config(signature_version='s3v4'),
            region_name='auto'
        )

        # Get missing receipts from database
        import pymysql
        conn = db.get_connection()
        cursor = conn.cursor(pymysql.cursors.DictCursor)

        query = '''
            SELECT _index, chase_description, chase_amount, chase_date
            FROM transactions
            WHERE deleted = FALSE
            AND (r2_url IS NULL OR r2_url = '')
            AND (receipt_url IS NULL OR receipt_url = '')
        '''
        params = []

        if business_type:
            query += ' AND business_type = %s'
            params.append(business_type)

        query += ' ORDER BY chase_date DESC LIMIT %s'
        params.append(limit)

        cursor.execute(query, params)
        missing = cursor.fetchall()

        if not missing:
            conn.close()
            return jsonify({
                'ok': True,
                'message': 'No missing receipts found',
                'stats': {'processed': 0, 'verified': 0, 'no_match': 0}
            })

        # Helper: normalize merchant name
        def normalize_merchant(name):
            if not name:
                return ''
            name = name.lower()
            name = re.sub(r'\s*(inc\.?|llc|corp\.?|ltd\.?|co\.?)\s*$', '', name, flags=re.I)
            name = re.sub(r'[^a-z0-9\s]', '', name)
            name = re.sub(r'\s+', ' ', name).strip()
            return name

        # Helper: search R2 for merchant
        def search_r2(merchant):
            matches = []
            keywords = [w for w in normalize_merchant(merchant).split() if len(w) > 2][:3]
            if not keywords:
                return matches

            seen = set()
            for prefix in ['receipts/', 'incoming/', '']:
                try:
                    paginator = s3_client.get_paginator('list_objects_v2')
                    for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=prefix, MaxKeys=1000):
                        for obj in page.get('Contents', []):
                            key = obj['Key']
                            if key in seen:
                                continue
                            seen.add(key)
                            filename = key.lower()
                            if not any(filename.endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.pdf']):
                                continue
                            # Check keyword match
                            for kw in keywords:
                                if kw in filename:
                                    matches.append({
                                        'key': key,
                                        'url': f"{R2_PUBLIC_URL}/{key}",
                                        'size': obj.get('Size', 0)
                                    })
                                    break
                except Exception:
                    continue
            return matches[:10]  # Return top 10

        # Helper: OCR verify receipt
        def ocr_verify(r2_url, tx_merchant, tx_amount, tx_date, key_idx):
            api_key = GEMINI_KEYS[key_idx % len(GEMINI_KEYS)]
            genai.configure(api_key=api_key)

            try:
                img_response = requests.get(r2_url, timeout=30)
                if img_response.status_code != 200:
                    return {'verdict': 'DOWNLOAD_ERROR'}
                img_data = img_response.content
            except Exception:
                return {'verdict': 'DOWNLOAD_ERROR'}

            mime_type = "image/jpeg"
            if r2_url.lower().endswith('.png'):
                mime_type = "image/png"
            elif r2_url.lower().endswith('.pdf'):
                mime_type = "application/pdf"

            prompt = f"""Analyze this receipt and verify against bank transaction.
TRANSACTION: {tx_merchant} ${float(tx_amount):.2f} {tx_date}

Return JSON: {{"ocr_merchant":"...", "ocr_amount":0.00, "verdict":"VERIFIED" or "MISMATCH", "reasoning":"..."}}
VERIFIED: amounts match within $2, merchants similar. MISMATCH: different merchant or amount differs >$5."""

            try:
                model = genai.GenerativeModel('gemini-2.0-flash')
                response = model.generate_content([prompt, {"mime_type": mime_type, "data": img_data}])
                text = response.text.strip()
                json_match = re.search(r'\{[\s\S]*\}', text)
                if json_match:
                    return json.loads(json_match.group())
                return {'verdict': 'PARSE_ERROR'}
            except Exception as e:
                if "429" in str(e) or "quota" in str(e).lower():
                    return {'verdict': 'RATE_LIMITED'}
                return {'verdict': 'API_ERROR'}

        # Process each missing receipt
        stats = {'processed': 0, 'verified': 0, 'no_match': 0, 'mismatch': 0, 'errors': 0}
        results = []
        key_idx = 0

        for tx in missing:
            idx = tx['_index']
            merchant = tx['chase_description']
            amount = float(tx['chase_amount'])
            date_str = str(tx['chase_date']) if tx['chase_date'] else ''

            stats['processed'] += 1

            # Search R2
            candidates = search_r2(merchant)
            if not candidates:
                stats['no_match'] += 1
                results.append({'_index': idx, 'status': 'no_candidates'})
                continue

            # Try each candidate
            matched = False
            for candidate in candidates[:5]:
                result = ocr_verify(candidate['url'], merchant, amount, date_str, key_idx)
                key_idx += 1

                verdict = result.get('verdict', 'UNCLEAR')

                if verdict == 'VERIFIED':
                    # Attach receipt
                    cursor.execute('''
                        UPDATE transactions SET
                            r2_url = %s,
                            receipt_validation_status = 'matched',
                            receipt_validated = 1,
                            receipt_validation_note = 'Re-matched via API',
                            ocr_merchant = %s,
                            ocr_amount = %s,
                            ocr_verified = 1,
                            ocr_verification_status = 'verified',
                            ocr_method = 'gemini',
                            ocr_extracted_at = NOW()
                        WHERE _index = %s
                    ''', (candidate['url'], result.get('ocr_merchant'), result.get('ocr_amount'), idx))
                    conn.commit()

                    stats['verified'] += 1
                    results.append({
                        '_index': idx,
                        'status': 'verified',
                        'r2_url': candidate['url'],
                        'ocr_merchant': result.get('ocr_merchant')
                    })
                    matched = True
                    break
                elif verdict == 'RATE_LIMITED':
                    stats['errors'] += 1
                    results.append({'_index': idx, 'status': 'rate_limited'})
                    matched = True  # Stop trying
                    break

            if not matched:
                stats['mismatch'] += 1
                results.append({'_index': idx, 'status': 'no_verified_match'})

        conn.close()

        return jsonify({
            'ok': True,
            'stats': stats,
            'results': results
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/admin/full-migration", methods=["POST"])
@login_required
def full_migration():
    """
    Complete migration from bundled JSON files to MySQL.
    This migrates ALL tables and ALL data.
    """
    import json

    try:
        if not USE_DATABASE or not db:
            return jsonify({'ok': False, 'error': 'Database not available'}), 500

        if not hasattr(db, 'use_mysql') or not db.use_mysql:
            return jsonify({'ok': False, 'error': 'MySQL not configured'}), 500

        migration_dir = BASE_DIR / 'migration_data'
        if not migration_dir.exists():
            return jsonify({
                'ok': False,
                'error': f'migration_data directory not found at {migration_dir}'
            }), 404

        conn = db.get_connection()
        cursor = conn.cursor()

        results = {}

        # 1. Migrate transactions
        trans_file = migration_dir / 'transactions.json'
        if trans_file.exists():
            with open(trans_file, 'r') as f:
                transactions = json.load(f)

            print(f"📦 Migrating {len(transactions)} transactions...")
            migrated = 0
            for row in transactions:
                try:
                    cursor.execute("""
                        INSERT INTO transactions
                        (_index, chase_date, chase_description, chase_amount, chase_category, chase_type,
                         receipt_file, receipt_url, r2_url, business_type, notes, ai_note, ai_confidence,
                         ai_receipt_merchant, ai_receipt_date, ai_receipt_total, review_status,
                         category, report_id, source, mi_merchant, mi_category, mi_description,
                         mi_confidence, mi_is_subscription, mi_subscription_name, mi_processed_at,
                         deleted_by_user, already_submitted)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            chase_date = VALUES(chase_date),
                            chase_description = VALUES(chase_description),
                            chase_amount = VALUES(chase_amount),
                            receipt_file = VALUES(receipt_file),
                            receipt_url = VALUES(receipt_url),
                            r2_url = VALUES(r2_url),
                            business_type = VALUES(business_type),
                            notes = VALUES(notes),
                            review_status = VALUES(review_status),
                            category = VALUES(category),
                            report_id = VALUES(report_id),
                            mi_merchant = VALUES(mi_merchant),
                            mi_category = VALUES(mi_category),
                            mi_description = VALUES(mi_description),
                            already_submitted = VALUES(already_submitted)
                    """, (
                        row.get('_index'),
                        row.get('chase_date') if row.get('chase_date') else None,
                        row.get('chase_description'),
                        row.get('chase_amount'),
                        row.get('chase_category'),
                        row.get('chase_type'),
                        row.get('receipt_file'),
                        row.get('receipt_url'),
                        row.get('receipt_url'),  # r2_url = receipt_url
                        row.get('business_type'),
                        row.get('notes'),
                        row.get('ai_note'),
                        row.get('ai_confidence'),
                        row.get('ai_receipt_merchant'),
                        row.get('ai_receipt_date'),
                        row.get('ai_receipt_total'),
                        row.get('review_status'),
                        row.get('category'),
                        row.get('report_id'),
                        row.get('source'),
                        row.get('mi_merchant'),
                        row.get('mi_category'),
                        row.get('mi_description'),
                        row.get('mi_confidence'),
                        row.get('mi_is_subscription'),
                        row.get('mi_subscription_name'),
                        row.get('mi_processed_at'),
                        row.get('deleted_by_user'),
                        row.get('already_submitted')
                    ))
                    migrated += 1
                except Exception as e:
                    if migrated < 5:
                        print(f"  ⚠️  Transaction error: {e}")
            conn.commit()
            results['transactions'] = migrated
            print(f"  ✅ Migrated {migrated} transactions")

        # 2. Migrate reports
        reports_file = migration_dir / 'reports.json'
        if reports_file.exists():
            with open(reports_file, 'r') as f:
                reports = json.load(f)

            print(f"📦 Migrating {len(reports)} reports...")
            migrated = 0
            for row in reports:
                try:
                    cursor.execute("""
                        INSERT INTO reports (report_id, report_name, business_type, expense_count, total_amount, created_at)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            report_name = VALUES(report_name),
                            expense_count = VALUES(expense_count),
                            total_amount = VALUES(total_amount)
                    """, (
                        row.get('report_id'),
                        row.get('report_name'),
                        row.get('business_type'),
                        row.get('expense_count'),
                        row.get('total_amount'),
                        row.get('created_at')
                    ))
                    migrated += 1
                except Exception as e:
                    print(f"  ⚠️  Report error: {e}")
            conn.commit()
            results['reports'] = migrated
            print(f"  ✅ Migrated {migrated} reports")

        # 3. Migrate incoming_receipts
        incoming_file = migration_dir / 'incoming_receipts.json'
        if incoming_file.exists():
            with open(incoming_file, 'r') as f:
                incoming = json.load(f)

            print(f"📦 Migrating {len(incoming)} incoming_receipts...")
            migrated = 0
            for row in incoming:
                try:
                    cursor.execute("""
                        INSERT INTO incoming_receipts
                        (email_id, gmail_account, subject, from_email, from_domain, received_date,
                         body_snippet, has_attachment, attachment_count, receipt_files, merchant,
                         amount, transaction_date, ocr_confidence, is_receipt, is_marketing,
                         confidence_score, status, reviewed_at, accepted_as_transaction_id,
                         rejection_reason, processed_at, description, is_subscription,
                         matched_transaction_id, match_type, attachments)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            status = VALUES(status),
                            merchant = VALUES(merchant),
                            amount = VALUES(amount)
                    """, (
                        row.get('email_id'),
                        row.get('gmail_account'),
                        row.get('subject'),
                        row.get('from_email'),
                        row.get('from_domain'),
                        row.get('received_date'),
                        row.get('body_snippet'),
                        row.get('has_attachment'),
                        row.get('attachment_count'),
                        row.get('receipt_files'),
                        row.get('merchant'),
                        row.get('amount'),
                        row.get('transaction_date'),
                        row.get('ocr_confidence'),
                        row.get('is_receipt'),
                        row.get('is_marketing'),
                        row.get('confidence_score'),
                        row.get('status'),
                        row.get('reviewed_at'),
                        row.get('accepted_as_transaction_id'),
                        row.get('rejection_reason'),
                        row.get('processed_at'),
                        row.get('description'),
                        row.get('is_subscription'),
                        row.get('matched_transaction_id'),
                        row.get('match_type'),
                        row.get('attachments')
                    ))
                    migrated += 1
                except Exception as e:
                    if migrated < 5:
                        print(f"  ⚠️  Incoming error: {e}")
            conn.commit()
            results['incoming_receipts'] = migrated
            print(f"  ✅ Migrated {migrated} incoming_receipts")

        # 4. Migrate rejected_receipts
        rejected_file = migration_dir / 'rejected_receipts.json'
        if rejected_file.exists():
            with open(rejected_file, 'r') as f:
                rejected = json.load(f)

            print(f"📦 Migrating {len(rejected)} rejected_receipts...")
            migrated = 0
            for row in rejected:
                try:
                    cursor.execute("""
                        INSERT INTO rejected_receipts
                        (transaction_date, transaction_description, transaction_amount, receipt_path, rejected_at, reason)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            reason = VALUES(reason)
                    """, (
                        row.get('transaction_date'),
                        row.get('transaction_description'),
                        row.get('transaction_amount'),
                        row.get('receipt_path'),
                        row.get('rejected_at'),
                        row.get('reason')
                    ))
                    migrated += 1
                except Exception as e:
                    print(f"  ⚠️  Rejected error: {e}")
            conn.commit()
            results['rejected_receipts'] = migrated
            print(f"  ✅ Migrated {migrated} rejected_receipts")

        # 5. Migrate merchants
        merchants_file = migration_dir / 'merchants.json'
        if merchants_file.exists():
            with open(merchants_file, 'r') as f:
                merchants = json.load(f)

            print(f"📦 Migrating {len(merchants)} merchants...")
            migrated = 0
            for row in merchants:
                try:
                    cursor.execute("""
                        INSERT INTO merchants
                        (raw_description, normalized_name, category, is_subscription, frequency, avg_amount, primary_business_type, aliases)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            normalized_name = VALUES(normalized_name),
                            category = VALUES(category)
                    """, (
                        row.get('raw_description'),
                        row.get('normalized_name'),
                        row.get('category'),
                        row.get('is_subscription'),
                        row.get('frequency'),
                        row.get('avg_amount'),
                        row.get('primary_business_type'),
                        row.get('aliases')
                    ))
                    migrated += 1
                except Exception as e:
                    print(f"  ⚠️  Merchant error: {e}")
            conn.commit()
            results['merchants'] = migrated
            print(f"  ✅ Migrated {migrated} merchants")

        # 6. Migrate contacts
        contacts_file = migration_dir / 'contacts.json'
        if contacts_file.exists():
            with open(contacts_file, 'r') as f:
                contacts = json.load(f)

            print(f"📦 Migrating {len(contacts)} contacts...")
            migrated = 0
            for row in contacts:
                try:
                    cursor.execute("""
                        INSERT INTO contacts
                        (name, first_name, last_name, title, company, category, priority, notes, relationship, status, strategic_notes, connected_on, name_tokens)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON DUPLICATE KEY UPDATE
                            name = VALUES(name)
                    """, (
                        row.get('name'),
                        row.get('first_name'),
                        row.get('last_name'),
                        row.get('title'),
                        row.get('company'),
                        row.get('category'),
                        row.get('priority'),
                        row.get('notes'),
                        row.get('relationship'),
                        row.get('status'),
                        row.get('strategic_notes'),
                        row.get('connected_on'),
                        row.get('name_tokens')
                    ))
                    migrated += 1
                except Exception as e:
                    if migrated < 5:
                        print(f"  ⚠️  Contact error: {e}")
            conn.commit()
            results['contacts'] = migrated
            print(f"  ✅ Migrated {migrated} contacts")

        cursor.close()
        return_db_connection(conn)

        # Verify receipt URLs
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions WHERE receipt_url IS NOT NULL AND receipt_url != ''")
        url_count = cursor.fetchone()
        url_count = url_count['cnt'] if isinstance(url_count, dict) else url_count[0]
        cursor.close()
        return_db_connection(conn)

        results['receipt_urls'] = url_count

        print(f"\n✅ Full migration complete!")
        return jsonify({
            'ok': True,
            'message': 'Full migration complete',
            'results': results
        })

    except Exception as e:
        print(f"❌ Migration error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# MISSING RECEIPT FORM PDF GENERATION
# =============================================================================

@app.route("/generate_missing_receipt_form", methods=["POST"])
def generate_missing_receipt_form():
    """
    Generate a filled-out Missing Receipt Form PDF for a transaction.

    Required fields in request JSON:
    - _index: transaction index
    - reason: reason receipt was lost
    - company: 'downhome' or 'mcr' (Music City Rodeo)

    Optional fields:
    - meal_attendees: list of attendee names (for meal receipts)
    - meal_purpose: business purpose for the meal
    """
    global df  # Need to update the cached dataframe
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    from reportlab.lib.units import inch
    from reportlab.lib.colors import black, gray
    from datetime import datetime
    import uuid

    try:
        data = request.get_json()
        row_index = data.get('_index')
        reason = data.get('reason', 'Receipt not provided by vendor')
        company = data.get('company', 'downhome')  # 'downhome' or 'mcr'
        meal_attendees = data.get('meal_attendees', '')
        meal_purpose = data.get('meal_purpose', '')

        if row_index is None:
            return jsonify({'ok': False, 'error': 'Missing _index'}), 400

        # Get transaction data
        if USE_DATABASE and db:
            row = db.get_transaction_by_index(row_index)
            if not row:
                return jsonify({'ok': False, 'error': 'Transaction not found'}), 404
        else:
            row = df[df['_index'] == row_index].iloc[0].to_dict()

        # Extract transaction details
        trans_date = row.get('Chase Date') or row.get('chase_date', '')
        trans_amount = row.get('Chase Amount') or row.get('chase_amount', 0)
        merchant = row.get('mi_merchant') or row.get('MI Merchant') or row.get('Chase Description') or row.get('chase_description', 'Unknown')
        description = row.get('mi_description') or row.get('MI Description') or row.get('Notes') or row.get('notes', '')
        category = row.get('mi_category') or row.get('MI Category') or row.get('Category') or ''

        # Format date
        try:
            if isinstance(trans_date, str) and trans_date:
                dt_obj = datetime.strptime(trans_date.split()[0], '%Y-%m-%d')
                formatted_date = dt_obj.strftime('%m/%d/%Y')
            else:
                formatted_date = datetime.now().strftime('%m/%d/%Y')
        except:
            formatted_date = str(trans_date) if trans_date else datetime.now().strftime('%m/%d/%Y')

        # Format amount
        try:
            amount_val = abs(float(trans_amount))
            formatted_amount = f"{amount_val:.2f}"
        except:
            formatted_amount = str(trans_amount)

        # Company details
        if company == 'mcr':
            company_name = "Music City Rodeo"
            company_header = "Music City Rodeo"
        else:
            company_name = "Down Home Media LLC"
            company_header = "Down Home Media LLC"

        # Generate unique filename
        form_id = str(uuid.uuid4())[:8]
        filename = f"missing_receipt_{company}_{formatted_date.replace('/', '-')}_{form_id}.pdf"
        output_path = RECEIPT_DIR / filename

        # Create PDF
        c = canvas.Canvas(str(output_path), pagesize=letter)
        width, height = letter

        # Company Header
        c.setFont("Helvetica-Bold", 16)
        c.setFillColor(gray)
        c.drawString(1*inch, height - 1*inch, company_header)

        # Title
        c.setFillColor(black)
        c.setFont("Helvetica-Bold", 18)
        c.drawCentredString(width/2, height - 1.5*inch, "MISSING RECEIPT FORM")

        # Certification text
        c.setFont("Helvetica", 10)
        cert_text = "I hereby certify that the original receipt was lost, accidentally destroyed or unobtainable and that the"
        cert_text2 = "information detailed below is complete and accurate."
        c.drawString(1*inch, height - 2*inch, cert_text)
        c.drawString(1*inch, height - 2.2*inch, cert_text2)

        # Section header
        c.setFont("Helvetica-Bold", 11)
        c.drawString(1*inch, height - 2.6*inch, "Receipt Information:")
        c.line(1*inch, height - 2.65*inch, 2.5*inch, height - 2.65*inch)

        # Form fields
        c.setFont("Helvetica", 11)
        y_pos = height - 3*inch

        # Date of Receipt
        c.drawString(1.2*inch, y_pos, "Date of Receipt:")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(3*inch, y_pos, formatted_date)
        c.line(3*inch, y_pos - 2, 5*inch, y_pos - 2)

        # Total Amount
        y_pos -= 0.4*inch
        c.setFont("Helvetica", 11)
        c.drawString(1.2*inch, y_pos, "Total Amount of Receipt (including taxes): $")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(4.5*inch, y_pos, formatted_amount)
        c.line(4.5*inch, y_pos - 2, 6*inch, y_pos - 2)

        # Vendor Name
        y_pos -= 0.4*inch
        c.setFont("Helvetica", 11)
        c.drawString(1.2*inch, y_pos, "Vendor Name:")
        c.setFont("Helvetica-Bold", 11)
        c.drawString(2.5*inch, y_pos, merchant[:50])  # Truncate long names
        c.line(2.5*inch, y_pos - 2, 7*inch, y_pos - 2)

        # Description of Goods/Services
        y_pos -= 0.5*inch
        c.setFont("Helvetica", 11)
        c.drawString(1.2*inch, y_pos, "Description of Goods and/or Services:")

        # Description box
        y_pos -= 0.3*inch
        c.rect(1.2*inch, y_pos - 0.8*inch, 6*inch, 1*inch)

        # Fill description
        desc_text = description if description else f"{category} - {merchant}"
        c.setFont("Helvetica", 10)
        # Word wrap description
        words = desc_text.split()
        line = ""
        text_y = y_pos - 0.15*inch
        for word in words:
            if c.stringWidth(line + word, "Helvetica", 10) < 5.8*inch:
                line += word + " "
            else:
                c.drawString(1.3*inch, text_y, line.strip())
                text_y -= 0.2*inch
                line = word + " "
        if line:
            c.drawString(1.3*inch, text_y, line.strip())

        # Reason Receipt Was Lost
        y_pos -= 1.2*inch
        c.setFont("Helvetica", 11)
        c.drawString(1.2*inch, y_pos, "Reason Receipt Was Lost:")
        c.setFont("Helvetica-Bold", 10)
        c.drawString(3.5*inch, y_pos, reason[:60])
        c.line(3.5*inch, y_pos - 2, 7.5*inch, y_pos - 2)

        # Meal receipt section (if applicable)
        y_pos -= 0.6*inch
        c.setFont("Helvetica", 10)
        meal_text = 'If a "lost" meal receipt, does the receipt cover more than one individual? If so, please note individual'
        meal_text2 = "name(s) and business purpose:"
        c.drawString(1.2*inch, y_pos, meal_text)
        y_pos -= 0.2*inch
        c.drawString(1.2*inch, y_pos, meal_text2)

        y_pos -= 0.3*inch
        c.line(1.2*inch, y_pos, 7.5*inch, y_pos)
        if meal_attendees:
            c.setFont("Helvetica", 10)
            c.drawString(1.3*inch, y_pos + 0.1*inch, f"{meal_attendees} - {meal_purpose}")

        # Signature section
        y_pos -= 0.8*inch

        # Draw signature line
        c.line(1.2*inch, y_pos, 3.5*inch, y_pos)
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(1.2*inch, y_pos - 0.15*inch, "Contractor/Employee Signature")

        # Load and draw signature image
        sig_path = BASE_DIR / "assets" / "brian_kaplan_signature.png"
        if sig_path.exists():
            try:
                # Position signature to sit nicely on the line
                # Width 2.2 inches, auto-height to preserve aspect ratio
                c.drawImage(str(sig_path), 1.2*inch, y_pos + 0.02*inch, width=2.2*inch, height=0.6*inch, preserveAspectRatio=True, mask='auto')
            except Exception as sig_error:
                print(f"Could not add signature image: {sig_error}")

        # Expense Approver line
        c.line(5*inch, y_pos, 7.5*inch, y_pos)
        c.drawString(5.5*inch, y_pos - 0.15*inch, "Expense Approver")

        # Date line
        y_pos -= 0.6*inch
        c.line(3.5*inch, y_pos, 5*inch, y_pos)
        c.drawString(4*inch, y_pos - 0.15*inch, "Date")
        c.setFont("Helvetica", 10)
        c.drawString(3.5*inch, y_pos + 0.1*inch, datetime.now().strftime('%m/%d/%Y'))

        # Footer
        y_pos -= 0.5*inch
        c.setFont("Helvetica-Bold", 10)
        c.drawCentredString(width/2, y_pos, "Please attach this form to your Expense Report Form")

        # Revision date
        c.setFont("Helvetica", 8)
        c.setFillColor(gray)
        c.drawString(6*inch, 0.5*inch, "Revision Date: May 2012")

        c.save()

        print(f"✅ Generated missing receipt form PDF: {filename}")

        # Convert PDF to JPG using ImageMagick (convert command)
        jpg_filename = filename.replace('.pdf', '.jpg')
        jpg_path = RECEIPT_DIR / jpg_filename

        try:
            import subprocess
            # Use ImageMagick to convert PDF to JPG at 200 DPI
            result = subprocess.run([
                'magick', 'convert',
                '-density', '200',
                '-quality', '95',
                '-background', 'white',
                '-flatten',
                str(output_path),
                str(jpg_path)
            ], capture_output=True, text=True, timeout=30)

            if result.returncode != 0:
                # Try older ImageMagick syntax
                result = subprocess.run([
                    'convert',
                    '-density', '200',
                    '-quality', '95',
                    '-background', 'white',
                    '-flatten',
                    str(output_path),
                    str(jpg_path)
                ], capture_output=True, text=True, timeout=30)

            if result.returncode == 0 and jpg_path.exists():
                # Delete the PDF, keep only JPG
                output_path.unlink()
                final_filename = jpg_filename
                print(f"✅ Converted to JPG: {jpg_filename}")
            else:
                # Fall back to PDF if conversion fails
                final_filename = filename
                print(f"⚠️ PDF to JPG conversion failed, keeping PDF: {result.stderr}")

        except Exception as convert_error:
            print(f"⚠️ Could not convert PDF to JPG: {convert_error}")
            final_filename = filename

        # Update the transaction to attach this form as the receipt
        if USE_DATABASE and db:
            db.update_transaction(row_index, {
                'receipt_file': final_filename,
                'Receipt File': final_filename,
                'Review Status': 'good',
                'Notes': f"Missing Receipt Form - {reason}"
            })

        # Also update the global df cache so refresh works without server restart
        if df is not None:
            mask = df['_index'] == row_index
            if mask.any():
                df.loc[mask, 'Receipt File'] = final_filename
                df.loc[mask, 'receipt_file'] = final_filename
                df.loc[mask, 'Review Status'] = 'good'
                df.loc[mask, 'review_status'] = 'good'
                df.loc[mask, 'Notes'] = f"Missing Receipt Form - {reason}"
                df.loc[mask, 'notes'] = f"Missing Receipt Form - {reason}"

        return jsonify({
            'ok': True,
            'message': f'Missing receipt form generated: {final_filename}',
            'filename': final_filename,
            'path': str(RECEIPT_DIR / final_filename)
        })

    except Exception as e:
        print(f"❌ Error generating missing receipt form: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# ATLAS CONTACT HUB - Full CRM Integration
# =============================================================================

@app.route("/contact-hub")
@app.route("/contacts")
@app.route("/contacts.html")
@login_required
def contact_hub_page():
    """ATLAS Contact Hub - Relationship Intelligence Dashboard"""
    response = send_from_directory(BASE_DIR, "contacts.html")
    # Prevent browser caching to ensure latest UI version is always served
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response


@app.route("/api/contact-hub/contacts", methods=["GET"])
@login_required
def api_contact_hub_list():
    """List contacts with ATLAS relationship data"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)
        search = request.args.get("search", "")
        relationship_type = request.args.get("type", "")
        touch_needed = request.args.get("touch_needed", "false").lower() == "true"
        sort_by = request.args.get("sort", "name")

        result = db.atlas_get_contacts(
            limit=limit,
            offset=offset,
            search=search if search else None,
            relationship_type=relationship_type if relationship_type else None,
            touch_needed=touch_needed,
            sort_by=sort_by
        )

        return jsonify(safe_json(result))
    except Exception as e:
        print(f"Contact list error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/contacts/<int:contact_id>", methods=["GET"])
@login_required
def api_contact_hub_get(contact_id):
    """Get single contact with full relationship data"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        contact = db.atlas_get_contact(contact_id)
        if not contact:
            return jsonify({"error": "Contact not found"}), 404
        return jsonify(safe_json(contact))
    except Exception as e:
        print(f"Contact get error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/contacts", methods=["POST"])
@login_required
def api_contact_hub_create():
    """Create new contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        contact_id = db.atlas_create_contact(data)
        if contact_id:
            return jsonify({"ok": True, "id": contact_id})
        return jsonify({"error": "Failed to create contact"}), 500
    except Exception as e:
        print(f"Contact create error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/contacts/<int:contact_id>", methods=["PUT", "PATCH"])
@login_required
def api_contact_hub_update(contact_id):
    """Update contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        success = db.atlas_update_contact(contact_id, data)
        if success:
            return jsonify({"ok": True})
        return jsonify({"error": "Failed to update contact"}), 500
    except Exception as e:
        print(f"Contact update error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/interactions", methods=["GET"])
@login_required
def api_contact_hub_interactions():
    """Get interactions"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        contact_id = request.args.get("contact_id", type=int)
        interaction_type = request.args.get("type", "")
        limit = request.args.get("limit", 50, type=int)
        offset = request.args.get("offset", 0, type=int)

        result = db.atlas_get_interactions(
            contact_id=contact_id,
            interaction_type=interaction_type if interaction_type else None,
            limit=limit,
            offset=offset
        )

        return jsonify(safe_json(result))
    except Exception as e:
        print(f"Interactions error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/interactions", methods=["POST"])
@login_required
def api_contact_hub_create_interaction():
    """Create interaction (call, meeting, note, etc.)"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        interaction_id = db.atlas_create_interaction(data)
        if interaction_id:
            return jsonify({"ok": True, "id": interaction_id})
        return jsonify({"error": "Failed to create interaction"}), 500
    except Exception as e:
        print(f"Interaction create error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/touch-needed", methods=["GET"])
@login_required
def api_contact_hub_touch_needed():
    """Get contacts needing touch"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = request.args.get("limit", 20, type=int)
        contacts = db.atlas_get_touch_needed(limit=limit)
        return jsonify(safe_json({"items": contacts}))
    except Exception as e:
        print(f"Touch needed error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/timeline/<int:contact_id>", methods=["GET"])
@login_required
def api_contact_hub_timeline(contact_id):
    """Get unified timeline for a contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = request.args.get("limit", 50, type=int)
        timeline = db.atlas_get_contact_timeline(contact_id, limit=limit)
        return jsonify(safe_json({"items": timeline}))
    except Exception as e:
        print(f"Timeline error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/digest", methods=["GET"])
@login_required
def api_contact_hub_digest():
    """Get relationship intelligence digest"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        digest = db.atlas_get_relationship_digest()
        return jsonify(safe_json(digest))
    except Exception as e:
        print(f"Digest error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/link-expense", methods=["POST"])
@login_required
def api_contact_hub_link_expense():
    """Link expense to contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        contact_id = data.get("contact_id")
        transaction_index = data.get("transaction_index")
        link_type = data.get("link_type", "attendee")
        notes = data.get("notes")

        if not contact_id or not transaction_index:
            return jsonify({"error": "Missing contact_id or transaction_index"}), 400

        success = db.atlas_link_expense_to_contact(
            contact_id=contact_id,
            transaction_index=transaction_index,
            link_type=link_type,
            notes=notes
        )

        if success:
            return jsonify({"ok": True})
        return jsonify({"error": "Failed to link expense"}), 500
    except Exception as e:
        print(f"Link expense error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/reminders", methods=["GET"])
@login_required
def api_contact_hub_reminders():
    """Get reminders"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        status = request.args.get("status", "pending")
        limit = request.args.get("limit", 20, type=int)
        reminders = db.atlas_get_reminders(status=status, limit=limit)
        return jsonify(safe_json({"items": reminders}))
    except Exception as e:
        print(f"Reminders error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/reminders", methods=["POST"])
@login_required
def api_contact_hub_create_reminder():
    """Create reminder"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        reminder_id = db.atlas_create_reminder(data)
        if reminder_id:
            return jsonify({"ok": True, "id": reminder_id})
        return jsonify({"error": "Failed to create reminder"}), 500
    except Exception as e:
        print(f"Reminder create error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Contact-Expense Integration Endpoints
# ============================================================================

@app.route("/api/contact-hub/contacts/<int:contact_id>/expenses", methods=["GET"])
@login_required
def api_contact_hub_contact_expenses(contact_id):
    """Get all expenses linked to a contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 50))
        expenses = db.atlas_get_contact_expenses(contact_id, limit)
        return jsonify({"ok": True, "expenses": expenses})
    except Exception as e:
        print(f"Contact expenses error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/unlink-expense", methods=["POST"])
@login_required
def api_contact_hub_unlink_expense():
    """Remove a contact-expense link"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')
        transaction_index = data.get('transaction_index')

        if not contact_id or transaction_index is None:
            return jsonify({"error": "Missing contact_id or transaction_index"}), 400

        success = db.atlas_unlink_expense(contact_id, transaction_index)
        return jsonify({"ok": success})
    except Exception as e:
        print(f"Unlink expense error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/suggest-contacts/<int:transaction_index>", methods=["GET"])
@login_required
def api_contact_hub_suggest_contacts(transaction_index):
    """Suggest contacts for an expense based on merchant name"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 5))
        suggestions = db.atlas_suggest_contacts_for_expense(transaction_index, limit)
        return jsonify({"ok": True, "suggestions": suggestions})
    except Exception as e:
        print(f"Suggest contacts error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/expense-contacts/<int:transaction_index>", methods=["GET"])
@login_required
def api_contact_hub_expense_contacts(transaction_index):
    """Get all contacts linked to an expense"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        contacts = db.atlas_get_expense_contacts(transaction_index)
        return jsonify({"ok": True, "contacts": contacts})
    except Exception as e:
        print(f"Expense contacts error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/auto-link-expenses", methods=["POST"])
@login_required
def api_contact_hub_auto_link_expenses():
    """Auto-link expenses to contacts by matching merchant to company"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json() or {}
        dry_run = data.get('dry_run', True)
        result = db.atlas_auto_link_expenses(dry_run=dry_run)
        return jsonify({"ok": True, **result})
    except Exception as e:
        print(f"Auto-link error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/spending-by-contact", methods=["GET"])
@login_required
def api_contact_hub_spending_by_contact():
    """Get spending summary by contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 20))
        spending = db.atlas_get_spending_by_contact(limit)
        return jsonify({"ok": True, "spending": spending})
    except Exception as e:
        print(f"Spending by contact error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/create-from-merchant", methods=["POST"])
@login_required
def api_contact_hub_create_from_merchant():
    """Create a new contact from a merchant name"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        merchant = data.get('merchant')
        transaction_index = data.get('transaction_index')

        if not merchant:
            return jsonify({"error": "Merchant name required"}), 400

        contact_id = db.atlas_create_contact_from_merchant(merchant, transaction_index)
        if contact_id:
            return jsonify({"ok": True, "contact_id": contact_id})
        return jsonify({"error": "Failed to create contact"}), 500
    except Exception as e:
        print(f"Create from merchant error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# AI-Powered Relationship Intelligence Endpoints
# ============================================================================

@app.route("/api/contact-hub/intelligence/strength/<int:contact_id>", methods=["GET"])
@login_required
def api_contact_hub_relationship_strength(contact_id):
    """Calculate and return relationship strength for a contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        strength = db.atlas_calculate_relationship_strength(contact_id)
        return jsonify({"ok": True, **strength})
    except Exception as e:
        print(f"Relationship strength error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/intelligence/insights/<int:contact_id>", methods=["GET"])
@login_required
def api_contact_hub_relationship_insights(contact_id):
    """Get relationship insights for a contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        insights = db.atlas_get_relationship_insights(contact_id)
        return jsonify({"ok": True, **insights})
    except Exception as e:
        print(f"Relationship insights error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/intelligence/recommendations", methods=["GET"])
@login_required
def api_contact_hub_recommendations():
    """Get recommended actions for contacts"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        limit = int(request.args.get('limit', 10))
        recommendations = db.atlas_get_contact_recommendations(limit)
        return jsonify({"ok": True, "recommendations": recommendations})
    except Exception as e:
        print(f"Recommendations error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/intelligence/analysis", methods=["GET"])
@login_required
def api_contact_hub_interaction_analysis():
    """Analyze interaction patterns"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        days = int(request.args.get('days', 30))
        analysis = db.atlas_get_interaction_analysis(days)
        return jsonify({"ok": True, **analysis})
    except Exception as e:
        print(f"Interaction analysis error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/intelligence/ai-summary/<int:contact_id>", methods=["GET"])
@login_required
def api_contact_hub_ai_summary(contact_id):
    """Get AI-ready summary for a contact"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        summary = db.atlas_generate_ai_summary(contact_id)
        return jsonify({"ok": True, "summary": summary})
    except Exception as e:
        print(f"AI summary error: {e}")
        return jsonify({"error": str(e)}), 500


# ============================================================================
# Calendar Sync and Interaction Logging Endpoints
# ============================================================================

@app.route("/api/contact-hub/calendar/sync", methods=["POST"])
def api_contact_hub_calendar_sync():
    """Sync calendar events to ATLAS"""
    # Auth check - allow admin_key or login
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        stats = db.atlas_sync_all_calendar_events()
        return jsonify({"ok": True, **stats})
    except Exception as e:
        print(f"Calendar sync error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/calendar/events", methods=["GET"])
@login_required
def api_contact_hub_calendar_events():
    """Get calendar events"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        contact_id = request.args.get('contact_id', type=int)
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        limit = request.args.get('limit', 50, type=int)

        events = db.atlas_get_calendar_events(contact_id, start_date, end_date, limit)
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        print(f"Calendar events error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/calendar/upcoming", methods=["GET"])
@login_required
def api_contact_hub_upcoming_events():
    """Get upcoming events with matched contacts"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        days = request.args.get('days', 7, type=int)
        events = db.atlas_get_upcoming_events_with_contacts(days)
        return jsonify({"ok": True, "events": events})
    except Exception as e:
        print(f"Upcoming events error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/interactions/log", methods=["POST"])
@login_required
def api_contact_hub_log_interaction():
    """Log a new interaction"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        interaction_id = db.atlas_log_interaction(data)
        if interaction_id:
            return jsonify({"ok": True, "id": interaction_id})
        return jsonify({"error": "Failed to log interaction"}), 500
    except Exception as e:
        print(f"Log interaction error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/contact-hub/interactions/quick-log", methods=["POST"])
@login_required
def api_contact_hub_quick_log():
    """Quick log an interaction (call, meeting, email, note)"""
    if not USE_DATABASE or not db:
        return jsonify({"error": "Database not available"}), 500

    try:
        data = request.get_json()
        contact_id = data.get('contact_id')
        interaction_type = data.get('type', 'note')
        note = data.get('note')

        if not contact_id:
            return jsonify({"error": "contact_id required"}), 400

        success = db.atlas_quick_log(contact_id, interaction_type, note)
        return jsonify({"ok": success})
    except Exception as e:
        print(f"Quick log error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/api/atlas/contacts/calculate-scores", methods=["POST"])
def api_atlas_calculate_relationship_scores():
    """Calculate relationship scores based on interaction data"""
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        updated = 0

        # Get all contacts with their interaction data from contact_interactions
        cursor.execute("""
            SELECT c.id, c.email, c.name,
                   COUNT(ci.id) as interaction_count,
                   MAX(ci.interaction_date) as last_interaction
            FROM contacts c
            LEFT JOIN contact_interactions ci ON ci.contact_id = c.id
            GROUP BY c.id, c.email, c.name
        """)

        contacts = cursor.fetchall()

        for contact in contacts:
            contact_id = contact['id']
            interaction_count = contact['interaction_count'] or 0
            last_interaction = contact['last_interaction']

            # Calculate relationship score (0-100)
            # Score is based on:
            # - Number of interactions (up to 50 points)
            # - Recency of last interaction (up to 50 points)
            score = 0

            # Interaction count scoring (log scale, max 50 points)
            if interaction_count > 0:
                import math
                score += min(50, int(math.log2(interaction_count + 1) * 10))

            # Recency scoring (max 50 points)
            if last_interaction:
                from datetime import datetime, timedelta
                if isinstance(last_interaction, str):
                    try:
                        last_interaction = datetime.fromisoformat(last_interaction.replace('Z', '+00:00'))
                    except:
                        last_interaction = None

                if last_interaction:
                    now = datetime.utcnow()
                    if hasattr(last_interaction, 'tzinfo') and last_interaction.tzinfo:
                        last_interaction = last_interaction.replace(tzinfo=None)

                    days_ago = (now - last_interaction).days

                    if days_ago <= 7:
                        score += 50  # Very recent
                    elif days_ago <= 30:
                        score += 40
                    elif days_ago <= 90:
                        score += 25
                    elif days_ago <= 180:
                        score += 15
                    elif days_ago <= 365:
                        score += 5

            # Update the contact's relationship score
            cursor.execute("""
                UPDATE contacts
                SET relationship_score = %s,
                    interaction_count = %s,
                    last_interaction = %s
                WHERE id = %s
            """, (score, interaction_count, last_interaction, contact_id))
            updated += 1

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "updated": updated,
            "message": f"Updated relationship scores for {updated} contacts"
        })

    except Exception as e:
        print(f"Calculate scores error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/atlas/contacts/sync-email-interactions", methods=["POST"])
def api_atlas_sync_email_interactions():
    """Scan Gmail for emails and populate contact interactions"""
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        # get_gmail_service is defined in this file (viewer_server.py)
        # No import needed - just use it directly

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get all contacts with emails
        cursor.execute("SELECT id, email, name FROM contacts WHERE email IS NOT NULL AND email != ''")
        contacts_with_email = {c['email'].lower(): c for c in cursor.fetchall() if c['email']}

        interactions_created = 0
        emails_scanned = 0
        accounts_checked = []
        accounts_with_errors = []

        # Get Gmail accounts from GMAIL_ACCOUNTS dictionary
        gmail_accounts = list(GMAIL_ACCOUNTS.keys())

        for account_email in gmail_accounts:
            try:
                service, error = get_gmail_service(account_email)
                if not service or error:
                    accounts_with_errors.append({'email': account_email, 'error': error or 'No service'})
                    continue
                accounts_checked.append(account_email)

                # Get recent emails (last 30 days)
                from datetime import datetime, timedelta
                after_date = (datetime.utcnow() - timedelta(days=30)).strftime('%Y/%m/%d')

                try:
                    results = service.users().messages().list(
                        userId='me',
                        q=f'after:{after_date}',
                        maxResults=100
                    ).execute()
                    messages = results.get('messages', [])
                    accounts_checked[-1] = f"{account_email} ({len(messages)} msgs)"
                except Exception as api_err:
                    accounts_with_errors.append({'email': account_email, 'error': f'API error: {str(api_err)}'})
                    continue

                for msg in messages:
                    try:
                        message = service.users().messages().get(
                            userId='me',
                            id=msg['id'],
                            format='metadata',
                            metadataHeaders=['From', 'To', 'Subject', 'Date']
                        ).execute()

                        emails_scanned += 1

                        headers = {h['name'].lower(): h['value'] for h in message.get('payload', {}).get('headers', [])}

                        from_email = headers.get('from', '')
                        to_email = headers.get('to', '')
                        subject = headers.get('subject', '')
                        date_str = headers.get('date', '')

                        # Extract email addresses
                        import re
                        from_match = re.search(r'<([^>]+)>', from_email) or re.search(r'[\w\.-]+@[\w\.-]+', from_email)
                        to_match = re.search(r'<([^>]+)>', to_email) or re.search(r'[\w\.-]+@[\w\.-]+', to_email)

                        from_addr = (from_match.group(1) if from_match and '<' in from_email else from_match.group() if from_match else '').lower()
                        to_addr = (to_match.group(1) if to_match and '<' in to_email else to_match.group() if to_match else '').lower()

                        # Determine the contact (the other party)
                        contact_email = None
                        interaction_type = None

                        if from_addr == account_email.lower():
                            # We sent this email
                            contact_email = to_addr
                            interaction_type = 'email_sent'
                        elif from_addr in contacts_with_email:
                            # We received this email
                            contact_email = from_addr
                            interaction_type = 'email_received'

                        if contact_email and contact_email in contacts_with_email:
                            contact = contacts_with_email[contact_email]

                            # Parse date
                            try:
                                import email.utils
                                parsed_date = email.utils.parsedate_to_datetime(date_str)
                            except:
                                parsed_date = datetime.utcnow()

                            # Check if interaction already exists
                            cursor.execute("""
                                SELECT id FROM contact_interactions
                                WHERE contact_id = %s AND source_id = %s
                            """, (contact['id'], msg['id']))

                            if not cursor.fetchone():
                                # Create interaction
                                cursor.execute("""
                                    INSERT INTO contact_interactions
                                    (contact_id, interaction_type, interaction_date, source, source_id, subject)
                                    VALUES (%s, %s, %s, %s, %s, %s)
                                """, (
                                    contact['id'],
                                    interaction_type,
                                    parsed_date,
                                    'gmail',
                                    msg['id'],
                                    subject[:500] if subject else None
                                ))
                                interactions_created += 1

                    except Exception as e:
                        print(f"Error processing message: {e}")
                        continue

            except Exception as e:
                print(f"Error scanning Gmail for {account_email}: {e}")
                continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "emails_scanned": emails_scanned,
            "interactions_created": interactions_created,
            "contacts_with_email": len(contacts_with_email),
            "accounts_checked": accounts_checked,
            "accounts_with_errors": accounts_with_errors,
            "gmail_accounts_configured": gmail_accounts
        })

    except Exception as e:
        print(f"Sync email interactions error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/atlas/contacts/sync-imessage-interactions", methods=["POST"])
def api_atlas_sync_imessage_interactions():
    """Scan iMessage (chat.db) for messages and populate contact interactions"""
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        import sqlite3
        from pathlib import Path
        from datetime import datetime, timedelta

        # Check if iMessage DB is accessible (macOS only)
        chat_db_path = Path.home() / "Library" / "Messages" / "chat.db"
        if not chat_db_path.exists():
            return jsonify({
                "ok": False,
                "error": "iMessage database not found (macOS only)",
                "path": str(chat_db_path)
            }), 400

        # Get days parameter (default 90 days)
        days = request.args.get('days', 90, type=int)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get all contacts with phone numbers
        cursor.execute("SELECT id, phone, name, email FROM contacts WHERE phone IS NOT NULL AND phone != ''")
        contacts_with_phone = {}
        for c in cursor.fetchall():
            if c['phone']:
                # Normalize phone number - extract just digits
                phone_digits = ''.join(ch for ch in c['phone'] if ch.isdigit())
                # Store last 10 digits (US format) for matching
                if len(phone_digits) >= 10:
                    phone_key = phone_digits[-10:]
                    contacts_with_phone[phone_key] = c

        if not contacts_with_phone:
            cursor.close()
            return_db_connection(conn)
            return jsonify({
                "ok": True,
                "message": "No contacts with phone numbers found",
                "contacts_with_phone": 0
            })

        # Connect to iMessage database
        try:
            imsg_conn = sqlite3.connect(str(chat_db_path))
            imsg_conn.row_factory = sqlite3.Row
            imsg_cursor = imsg_conn.cursor()
        except Exception as e:
            cursor.close()
            return_db_connection(conn)
            return jsonify({
                "ok": False,
                "error": f"Cannot access iMessage database: {e}. Grant Full Disk Access to Terminal/Python in System Preferences."
            }), 400

        # Calculate date threshold (Apple timestamp is nanoseconds since 2001-01-01)
        threshold_date = datetime.now() - timedelta(days=days)
        apple_epoch = datetime(2001, 1, 1)
        threshold_ns = int((threshold_date - apple_epoch).total_seconds() * 1e9)

        # Query recent messages
        imsg_cursor.execute("""
            SELECT
                m.ROWID as msg_id,
                m.text,
                m.is_from_me,
                m.date,
                datetime(m.date/1000000000 + strftime('%s', '2001-01-01'), 'unixepoch', 'localtime') as message_date,
                h.id as handle_id
            FROM message m
            JOIN handle h ON m.handle_id = h.ROWID
            WHERE m.date > ?
            AND m.text IS NOT NULL
            AND m.text != ''
            ORDER BY m.date DESC
            LIMIT 5000
        """, (threshold_ns,))

        messages = imsg_cursor.fetchall()
        imsg_conn.close()

        interactions_created = 0
        messages_scanned = len(messages)
        contacts_matched = set()
        handle_stats = {}

        for msg in messages:
            handle = msg['handle_id'] or ''

            # Track handle stats
            if handle not in handle_stats:
                handle_stats[handle] = {'count': 0, 'matched': False}
            handle_stats[handle]['count'] += 1

            # Extract phone digits from handle (could be phone or email)
            handle_digits = ''.join(ch for ch in handle if ch.isdigit())
            if len(handle_digits) >= 10:
                handle_key = handle_digits[-10:]
            else:
                continue  # Skip if not a phone number

            # Try to match to a contact
            if handle_key in contacts_with_phone:
                contact = contacts_with_phone[handle_key]
                handle_stats[handle]['matched'] = True
                contacts_matched.add(contact['id'])

                # Check if interaction already exists
                msg_date = msg['message_date']
                interaction_type = 'imessage_sent' if msg['is_from_me'] else 'imessage_received'

                # Check for duplicate using external_id
                cursor.execute("""
                    SELECT id FROM interactions
                    WHERE source = 'imessage' AND external_id = %s
                    LIMIT 1
                """, (str(msg['msg_id']),))

                if cursor.fetchone():
                    continue  # Already exists

                # Create interaction
                try:
                    text_preview = (msg['text'] or '')[:500]
                    is_outgoing = msg['is_from_me']

                    cursor.execute("""
                        INSERT INTO interactions (
                            interaction_type, channel, occurred_at, summary, content,
                            source, external_id, is_outgoing
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                    """, (
                        interaction_type,
                        'imessage',
                        msg_date,
                        text_preview[:200],
                        text_preview,
                        'imessage',
                        str(msg['msg_id']),
                        is_outgoing
                    ))
                    interaction_id = cursor.lastrowid

                    # Link to contact via junction table
                    cursor.execute("""
                        INSERT INTO interaction_contacts (interaction_id, contact_id, role)
                        VALUES (%s, %s, %s)
                    """, (interaction_id, contact['id'], 'participant'))

                    interactions_created += 1

                    # Update contact's last touch date and interaction count
                    cursor.execute("""
                        UPDATE contacts
                        SET last_touch_date = GREATEST(COALESCE(last_touch_date, '1970-01-01'), %s),
                            interaction_count = COALESCE(interaction_count, 0) + 1
                        WHERE id = %s
                    """, (msg_date, contact['id']))

                except Exception as e:
                    print(f"Error creating iMessage interaction: {e}")
                    continue

        conn.commit()
        cursor.close()
        return_db_connection(conn)

        # Build handle summary for debugging
        top_handles = sorted(handle_stats.items(), key=lambda x: x[1]['count'], reverse=True)[:20]

        return jsonify({
            "ok": True,
            "messages_scanned": messages_scanned,
            "interactions_created": interactions_created,
            "contacts_with_phone": len(contacts_with_phone),
            "contacts_matched": len(contacts_matched),
            "days_scanned": days,
            "top_handles": [{"handle": h, "count": s['count'], "matched": s['matched']} for h, s in top_handles]
        })

    except Exception as e:
        print(f"Sync iMessage interactions error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.route("/api/atlas/contacts/sync-all-interactions", methods=["POST"])
def api_atlas_sync_all_interactions():
    """Sync interactions from all sources (Gmail + iMessage) and recalculate scores"""
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    results = {
        "gmail": None,
        "imessage": None,
        "scores_updated": 0
    }

    # Sync Gmail
    try:
        with app.test_request_context():
            gmail_response = api_atlas_sync_email_interactions()
            if hasattr(gmail_response, 'get_json'):
                results["gmail"] = gmail_response.get_json()
            else:
                results["gmail"] = {"error": "Gmail sync failed"}
    except Exception as e:
        results["gmail"] = {"error": str(e)}

    # Sync iMessage
    try:
        with app.test_request_context():
            imessage_response = api_atlas_sync_imessage_interactions()
            if hasattr(imessage_response, 'get_json'):
                results["imessage"] = imessage_response.get_json()
            else:
                results["imessage"] = {"error": "iMessage sync failed"}
    except Exception as e:
        results["imessage"] = {"error": str(e)}

    # Recalculate interaction counts for all contacts
    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Update interaction counts from the interactions table (using junction table)
        cursor.execute("""
            UPDATE contacts c
            SET interaction_count = (
                SELECT COUNT(*) FROM interaction_contacts ic WHERE ic.contact_id = c.id
            )
        """)

        # Update last touch dates from interactions (using junction table)
        cursor.execute("""
            UPDATE contacts c
            SET last_touch_date = (
                SELECT MAX(i.occurred_at)
                FROM interactions i
                JOIN interaction_contacts ic ON i.id = ic.interaction_id
                WHERE ic.contact_id = c.id
            )
            WHERE EXISTS (SELECT 1 FROM interaction_contacts ic WHERE ic.contact_id = c.id)
        """)

        results["scores_updated"] = cursor.rowcount
        conn.commit()
        cursor.close()
        return_db_connection(conn)
    except Exception as e:
        results["score_update_error"] = str(e)

    return jsonify({
        "ok": True,
        **results
    })


@app.route("/api/atlas/contacts/frequency-stats", methods=["GET"])
def api_atlas_frequency_stats():
    """Get contacts sorted by interaction frequency with detailed stats"""
    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key != expected_key:
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    try:
        limit = request.args.get('limit', 50, type=int)
        days = request.args.get('days', 90, type=int)

        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get contacts with interaction stats (using junction table)
        cursor.execute("""
            SELECT
                c.id, c.name, c.email, c.phone, c.company, c.photo_url,
                COALESCE(c.interaction_count, 0) as total_interactions,
                c.last_touch_date,
                (SELECT COUNT(*)
                 FROM interaction_contacts ic
                 JOIN interactions i ON i.id = ic.interaction_id
                 WHERE ic.contact_id = c.id
                 AND i.occurred_at >= DATE_SUB(NOW(), INTERVAL %s DAY)) as recent_interactions,
                (SELECT COUNT(*)
                 FROM interaction_contacts ic
                 JOIN interactions i ON i.id = ic.interaction_id
                 WHERE ic.contact_id = c.id AND i.is_outgoing = TRUE) as sent_count,
                (SELECT COUNT(*)
                 FROM interaction_contacts ic
                 JOIN interactions i ON i.id = ic.interaction_id
                 WHERE ic.contact_id = c.id AND i.is_outgoing = FALSE) as received_count
            FROM contacts c
            WHERE c.interaction_count > 0 OR c.last_touch_date IS NOT NULL
            ORDER BY COALESCE(c.interaction_count, 0) DESC
            LIMIT %s
        """, (days, limit))

        contacts = []
        for row in cursor.fetchall():
            days_since = None
            if row['last_touch_date']:
                try:
                    last_touch = row['last_touch_date']
                    if isinstance(last_touch, str):
                        last_touch = datetime.fromisoformat(last_touch.replace('Z', '+00:00'))
                    days_since = (datetime.now() - last_touch.replace(tzinfo=None)).days
                except:
                    pass

            contacts.append({
                "id": row['id'],
                "name": row['name'],
                "email": row['email'],
                "phone": row['phone'],
                "company": row['company'],
                "photo_url": row['photo_url'],
                "total_interactions": row['total_interactions'],
                "recent_interactions": row['recent_interactions'],
                "sent_count": row['sent_count'],
                "received_count": row['received_count'],
                "last_touch_date": str(row['last_touch_date']) if row['last_touch_date'] else None,
                "days_since_contact": days_since
            })

        cursor.close()
        return_db_connection(conn)

        return jsonify({
            "ok": True,
            "contacts": contacts,
            "count": len(contacts),
            "period_days": days
        })

    except Exception as e:
        print(f"Frequency stats error: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


# Contact Hub HTML Template (PWA-ready)
CONTACT_HUB_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#1a1a2e">
    <title>Contact Hub - ATLAS</title>
    <link rel="manifest" href="/static/manifest.json">
    <style>
        :root {
            --bg-primary: #0f0f1a;
            --bg-secondary: #1a1a2e;
            --bg-card: #252540;
            --text-primary: #ffffff;
            --text-secondary: #a0a0b0;
            --accent-blue: #4a9eff;
            --accent-green: #4ade80;
            --accent-orange: #fb923c;
            --accent-purple: #a78bfa;
            --accent-red: #f87171;
            --border-color: #3a3a5a;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: var(--bg-primary);
            color: var(--text-primary);
            min-height: 100vh;
            padding-bottom: 80px;
        }

        .header {
            background: linear-gradient(135deg, var(--bg-secondary) 0%, var(--bg-card) 100%);
            padding: 20px;
            position: sticky;
            top: 0;
            z-index: 100;
            border-bottom: 1px solid var(--border-color);
        }

        .header-top {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 15px;
        }

        .header h1 {
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .search-box {
            display: flex;
            gap: 10px;
        }

        .search-box input {
            flex: 1;
            padding: 12px 16px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-primary);
            color: var(--text-primary);
            font-size: 16px;
        }

        .btn {
            padding: 12px 20px;
            border-radius: 12px;
            border: none;
            font-size: 14px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s;
        }

        .btn-primary {
            background: var(--accent-blue);
            color: white;
        }

        .btn-primary:hover {
            background: #3a8eff;
            transform: translateY(-1px);
        }

        .stats-bar {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 12px;
            padding: 15px 20px;
            background: var(--bg-secondary);
            border-bottom: 1px solid var(--border-color);
        }

        .stat-item {
            text-align: center;
        }

        .stat-value {
            font-size: 24px;
            font-weight: 700;
            color: var(--accent-blue);
        }

        .stat-label {
            font-size: 11px;
            color: var(--text-secondary);
            text-transform: uppercase;
        }

        .tabs {
            display: flex;
            gap: 5px;
            padding: 15px 20px;
            background: var(--bg-secondary);
            overflow-x: auto;
        }

        .tab {
            padding: 10px 20px;
            border-radius: 20px;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            white-space: nowrap;
            background: var(--bg-card);
            color: var(--text-secondary);
            border: 1px solid transparent;
            transition: all 0.2s;
        }

        .tab.active {
            background: var(--accent-blue);
            color: white;
        }

        .tab:hover:not(.active) {
            border-color: var(--accent-blue);
            color: var(--text-primary);
        }

        .content {
            padding: 20px;
        }

        .contact-grid {
            display: grid;
            grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
            gap: 15px;
        }

        .contact-card {
            background: var(--bg-card);
            border-radius: 16px;
            padding: 20px;
            cursor: pointer;
            transition: all 0.2s;
            border: 1px solid var(--border-color);
        }

        .contact-card:hover {
            transform: translateY(-2px);
            border-color: var(--accent-blue);
            box-shadow: 0 8px 30px rgba(74, 158, 255, 0.15);
        }

        .contact-header {
            display: flex;
            gap: 15px;
            align-items: flex-start;
            margin-bottom: 15px;
        }

        .avatar {
            width: 50px;
            height: 50px;
            border-radius: 50%;
            background: linear-gradient(135deg, var(--accent-purple), var(--accent-blue));
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 20px;
            font-weight: 700;
            flex-shrink: 0;
        }

        .avatar img {
            width: 100%;
            height: 100%;
            border-radius: 50%;
            object-fit: cover;
        }

        .contact-info h3 {
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 4px;
        }

        .contact-info .company {
            font-size: 13px;
            color: var(--text-secondary);
        }

        .contact-meta {
            display: flex;
            gap: 15px;
            flex-wrap: wrap;
        }

        .meta-item {
            display: flex;
            align-items: center;
            gap: 6px;
            font-size: 12px;
            color: var(--text-secondary);
        }

        .tag {
            display: inline-block;
            padding: 4px 10px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 500;
        }

        .tag-vip {
            background: rgba(251, 146, 60, 0.2);
            color: var(--accent-orange);
        }

        .tag-touch {
            background: rgba(248, 113, 113, 0.2);
            color: var(--accent-red);
        }

        .touch-needed-section {
            background: linear-gradient(135deg, rgba(248, 113, 113, 0.1), rgba(251, 146, 60, 0.1));
            border: 1px solid rgba(248, 113, 113, 0.3);
            border-radius: 16px;
            padding: 20px;
            margin-bottom: 25px;
        }

        .touch-needed-section h2 {
            font-size: 18px;
            margin-bottom: 15px;
            display: flex;
            align-items: center;
            gap: 10px;
        }

        .touch-list {
            display: flex;
            gap: 12px;
            overflow-x: auto;
            padding-bottom: 10px;
        }

        .touch-item {
            flex-shrink: 0;
            background: var(--bg-card);
            border-radius: 12px;
            padding: 15px;
            min-width: 200px;
            border: 1px solid var(--border-color);
        }

        .touch-item h4 {
            font-size: 14px;
            margin-bottom: 5px;
        }

        .touch-item .days {
            font-size: 12px;
            color: var(--accent-red);
        }

        .modal-overlay {
            display: none;
            position: fixed;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: rgba(0,0,0,0.8);
            z-index: 1000;
            align-items: center;
            justify-content: center;
        }

        .modal-overlay.active {
            display: flex;
        }

        .modal {
            background: var(--bg-secondary);
            border-radius: 20px;
            width: 90%;
            max-width: 600px;
            max-height: 90vh;
            overflow-y: auto;
            border: 1px solid var(--border-color);
        }

        .modal-header {
            padding: 20px;
            border-bottom: 1px solid var(--border-color);
            display: flex;
            justify-content: space-between;
            align-items: center;
        }

        .modal-body {
            padding: 20px;
        }

        .form-group {
            margin-bottom: 20px;
        }

        .form-group label {
            display: block;
            margin-bottom: 8px;
            font-size: 13px;
            color: var(--text-secondary);
        }

        .form-group input, .form-group select, .form-group textarea {
            width: 100%;
            padding: 12px 16px;
            border-radius: 12px;
            border: 1px solid var(--border-color);
            background: var(--bg-primary);
            color: var(--text-primary);
            font-size: 16px;
        }

        .form-row {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }

        .timeline {
            padding: 20px;
        }

        .timeline-item {
            display: flex;
            gap: 15px;
            padding: 15px 0;
            border-bottom: 1px solid var(--border-color);
        }

        .timeline-icon {
            width: 40px;
            height: 40px;
            border-radius: 50%;
            display: flex;
            align-items: center;
            justify-content: center;
            flex-shrink: 0;
        }

        .timeline-icon.call { background: rgba(74, 158, 255, 0.2); color: var(--accent-blue); }
        .timeline-icon.meeting { background: rgba(167, 139, 250, 0.2); color: var(--accent-purple); }
        .timeline-icon.email { background: rgba(74, 222, 128, 0.2); color: var(--accent-green); }
        .timeline-icon.expense { background: rgba(251, 146, 60, 0.2); color: var(--accent-orange); }
        .timeline-icon.note { background: rgba(160, 160, 176, 0.2); color: var(--text-secondary); }

        .nav-bottom {
            position: fixed;
            bottom: 0;
            left: 0;
            right: 0;
            background: var(--bg-secondary);
            border-top: 1px solid var(--border-color);
            display: flex;
            justify-content: space-around;
            padding: 10px 0 20px 0;
            z-index: 100;
        }

        .nav-item {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 4px;
            color: var(--text-secondary);
            text-decoration: none;
            font-size: 11px;
        }

        .nav-item.active {
            color: var(--accent-blue);
        }

        @media (max-width: 768px) {
            .stats-bar {
                grid-template-columns: repeat(2, 1fr);
            }
            .contact-grid {
                grid-template-columns: 1fr;
            }
            .form-row {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-top">
            <h1>Contact Hub</h1>
            <button class="btn btn-primary" onclick="showAddContact()">+ Add Contact</button>
        </div>
        <div class="search-box">
            <input type="text" id="searchInput" placeholder="Search contacts..." onkeyup="debounceSearch()">
        </div>
    </div>

    <div class="stats-bar" id="statsBar">
        <div class="stat-item">
            <div class="stat-value" id="statTotal">-</div>
            <div class="stat-label">Total</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="statTouch">-</div>
            <div class="stat-label">Need Touch</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="statVIP">-</div>
            <div class="stat-label">VIP</div>
        </div>
        <div class="stat-item">
            <div class="stat-value" id="statRecent">-</div>
            <div class="stat-label">This Week</div>
        </div>
    </div>

    <div class="tabs">
        <div class="tab active" data-filter="all" onclick="setFilter('all')">All</div>
        <div class="tab" data-filter="professional" onclick="setFilter('professional')">Professional</div>
        <div class="tab" data-filter="friend" onclick="setFilter('friend')">Friends</div>
        <div class="tab" data-filter="family" onclick="setFilter('family')">Family</div>
        <div class="tab" data-filter="client" onclick="setFilter('client')">Clients</div>
    </div>

    <div class="content">
        <div class="touch-needed-section" id="touchNeededSection">
            <h2>Needs Your Attention</h2>
            <div class="touch-list" id="touchList"></div>
        </div>

        <div class="contact-grid" id="contactGrid"></div>
    </div>

    <!-- Contact Modal -->
    <div class="modal-overlay" id="contactModal">
        <div class="modal">
            <div class="modal-header">
                <h2 id="modalTitle">Add Contact</h2>
                <button onclick="closeModal()" style="background:none;border:none;color:var(--text-primary);font-size:24px;cursor:pointer;">&times;</button>
            </div>
            <div class="modal-body">
                <form id="contactForm" onsubmit="saveContact(event)">
                    <input type="hidden" id="contactId">
                    <div class="form-row">
                        <div class="form-group">
                            <label>Name *</label>
                            <input type="text" id="contactName" required>
                        </div>
                        <div class="form-group">
                            <label>Company</label>
                            <input type="text" id="contactCompany">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Email</label>
                            <input type="email" id="contactEmail">
                        </div>
                        <div class="form-group">
                            <label>Phone</label>
                            <input type="tel" id="contactPhone">
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Title</label>
                            <input type="text" id="contactTitle">
                        </div>
                        <div class="form-group">
                            <label>Relationship</label>
                            <select id="contactRelationship">
                                <option value="professional">Professional</option>
                                <option value="friend">Friend</option>
                                <option value="family">Family</option>
                                <option value="client">Client</option>
                                <option value="vendor">Vendor</option>
                            </select>
                        </div>
                    </div>
                    <div class="form-row">
                        <div class="form-group">
                            <label>Touch Frequency (days)</label>
                            <input type="number" id="contactFrequency" value="30" min="1">
                        </div>
                        <div class="form-group">
                            <label>Team/Category</label>
                            <input type="text" id="contactTeam" placeholder="e.g., MCR, DownHome">
                        </div>
                    </div>
                    <div class="form-group">
                        <label>Context (how you know them)</label>
                        <textarea id="contactContext" rows="2"></textarea>
                    </div>
                    <div class="form-group">
                        <label>Notes</label>
                        <textarea id="contactNotes" rows="3"></textarea>
                    </div>
                    <div class="form-group">
                        <label style="display:flex;align-items:center;gap:10px;">
                            <input type="checkbox" id="contactVIP"> Mark as VIP
                        </label>
                    </div>
                    <button type="submit" class="btn btn-primary" style="width:100%;">Save Contact</button>
                </form>
            </div>
        </div>
    </div>

    <!-- Contact Detail Modal -->
    <div class="modal-overlay" id="detailModal">
        <div class="modal" style="max-width:700px;">
            <div class="modal-header">
                <h2 id="detailName">Contact Details</h2>
                <button onclick="closeDetailModal()" style="background:none;border:none;color:var(--text-primary);font-size:24px;cursor:pointer;">&times;</button>
            </div>
            <div class="modal-body" id="detailContent">
                <!-- Filled dynamically -->
            </div>
        </div>
    </div>

    <nav class="nav-bottom">
        <a href="/library" class="nav-item">
            <span style="font-size:20px;">📊</span>
            <span>Expenses</span>
        </a>
        <a href="/contact-hub" class="nav-item active">
            <span style="font-size:20px;">👥</span>
            <span>Contacts</span>
        </a>
        <a href="/reports" class="nav-item">
            <span style="font-size:20px;">📋</span>
            <span>Reports</span>
        </a>
        <a href="/incoming" class="nav-item">
            <span style="font-size:20px;">📥</span>
            <span>Incoming</span>
        </a>
    </nav>

    <script>
        let contacts = [];
        let currentFilter = 'all';
        let searchTimeout;

        async function loadData() {
            try {
                // Load digest stats
                const digestRes = await fetch('/api/contact-hub/digest');
                const digest = await digestRes.json();

                document.getElementById('statTouch').textContent = digest.touch_needed_count || 0;
                document.getElementById('statVIP').textContent = digest.vip_touch_needed || 0;
                document.getElementById('statRecent').textContent = digest.recent_interactions || 0;

                // Load touch needed
                const touchRes = await fetch('/api/contact-hub/touch-needed?limit=10');
                const touchData = await touchRes.json();
                renderTouchNeeded(touchData.items || []);

                // Load contacts
                await loadContacts();
            } catch (e) {
                console.error('Load error:', e);
            }
        }

        async function loadContacts() {
            const search = document.getElementById('searchInput').value;
            const typeFilter = currentFilter !== 'all' ? `&type=${currentFilter}` : '';

            try {
                const res = await fetch(`/api/contact-hub/contacts?limit=100&search=${encodeURIComponent(search)}${typeFilter}`);
                const data = await res.json();
                contacts = data.items || [];
                document.getElementById('statTotal').textContent = data.total || contacts.length;
                renderContacts();
            } catch (e) {
                console.error('Load contacts error:', e);
            }
        }

        function renderTouchNeeded(items) {
            const container = document.getElementById('touchList');
            if (!items.length) {
                document.getElementById('touchNeededSection').style.display = 'none';
                return;
            }

            document.getElementById('touchNeededSection').style.display = 'block';
            container.innerHTML = items.map(c => `
                <div class="touch-item" onclick="showContactDetail(${c.id})">
                    <h4>${c.name}</h4>
                    <div class="days">${c.days_since_touch || 0} days since touch</div>
                    ${c.company ? `<div style="font-size:12px;color:var(--text-secondary);margin-top:5px;">${c.company}</div>` : ''}
                </div>
            `).join('');
        }

        function renderContacts() {
            const grid = document.getElementById('contactGrid');
            grid.innerHTML = contacts.map(c => `
                <div class="contact-card" onclick="showContactDetail(${c.id})">
                    <div class="contact-header">
                        <div class="avatar">
                            ${c.photo_url ? `<img src="${c.photo_url}" alt="">` : getInitials(c.name)}
                        </div>
                        <div class="contact-info">
                            <h3>${c.name} ${c.is_vip ? '<span class="tag tag-vip">VIP</span>' : ''}</h3>
                            ${c.company ? `<div class="company">${c.title ? c.title + ' at ' : ''}${c.company}</div>` : ''}
                        </div>
                    </div>
                    <div class="contact-meta">
                        ${c.email ? `<div class="meta-item">📧 ${c.email}</div>` : ''}
                        ${c.phone ? `<div class="meta-item">📱 ${c.phone}</div>` : ''}
                        ${c.interaction_count ? `<div class="meta-item">💬 ${c.interaction_count}</div>` : ''}
                        ${c.expense_count ? `<div class="meta-item">💰 ${c.expense_count}</div>` : ''}
                    </div>
                </div>
            `).join('');
        }

        function getInitials(name) {
            return name.split(' ').map(n => n[0]).join('').toUpperCase().slice(0,2);
        }

        function setFilter(filter) {
            currentFilter = filter;
            document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
            document.querySelector(`.tab[data-filter="${filter}"]`).classList.add('active');
            loadContacts();
        }

        function debounceSearch() {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(loadContacts, 300);
        }

        function showAddContact() {
            document.getElementById('contactId').value = '';
            document.getElementById('contactForm').reset();
            document.getElementById('modalTitle').textContent = 'Add Contact';
            document.getElementById('contactModal').classList.add('active');
        }

        function closeModal() {
            document.getElementById('contactModal').classList.remove('active');
        }

        async function saveContact(e) {
            e.preventDefault();
            const id = document.getElementById('contactId').value;
            const data = {
                name: document.getElementById('contactName').value,
                company: document.getElementById('contactCompany').value,
                email: document.getElementById('contactEmail').value,
                phone: document.getElementById('contactPhone').value,
                title: document.getElementById('contactTitle').value,
                relationship_type: document.getElementById('contactRelationship').value,
                touch_frequency_days: parseInt(document.getElementById('contactFrequency').value),
                team: document.getElementById('contactTeam').value,
                context: document.getElementById('contactContext').value,
                notes: document.getElementById('contactNotes').value,
                is_vip: document.getElementById('contactVIP').checked
            };

            try {
                const url = id ? `/api/contact-hub/contacts/${id}` : '/api/contact-hub/contacts';
                const method = id ? 'PUT' : 'POST';

                const res = await fetch(url, {
                    method,
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(data)
                });

                const result = await res.json();
                if (result.ok || result.id) {
                    closeModal();
                    loadData();
                } else {
                    alert(result.error || 'Failed to save');
                }
            } catch (e) {
                alert('Error: ' + e.message);
            }
        }

        async function showContactDetail(id) {
            try {
                const res = await fetch(`/api/contact-hub/contacts/${id}`);
                const contact = await res.json();

                document.getElementById('detailName').textContent = contact.name;

                const content = document.getElementById('detailContent');
                content.innerHTML = `
                    <div style="display:flex;gap:20px;margin-bottom:20px;">
                        <div class="avatar" style="width:80px;height:80px;font-size:32px;">
                            ${contact.photo_url ? `<img src="${contact.photo_url}" alt="">` : getInitials(contact.name)}
                        </div>
                        <div>
                            <h2>${contact.name} ${contact.is_vip ? '<span class="tag tag-vip">VIP</span>' : ''}</h2>
                            ${contact.title ? `<div>${contact.title}</div>` : ''}
                            ${contact.company ? `<div style="color:var(--text-secondary);">${contact.company}</div>` : ''}
                            <div style="margin-top:10px;display:flex;gap:10px;">
                                ${contact.email ? `<a href="mailto:${contact.email}" class="btn btn-primary" style="padding:8px 15px;font-size:12px;">Email</a>` : ''}
                                ${contact.phone ? `<a href="tel:${contact.phone}" class="btn btn-primary" style="padding:8px 15px;font-size:12px;">Call</a>` : ''}
                                <button onclick="editContact(${contact.id})" class="btn" style="background:var(--bg-card);color:var(--text-primary);padding:8px 15px;font-size:12px;">Edit</button>
                            </div>
                        </div>
                    </div>

                    <div style="display:grid;grid-template-columns:1fr 1fr;gap:15px;margin-bottom:20px;">
                        <div style="background:var(--bg-card);padding:15px;border-radius:12px;">
                            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:5px;">Last Touch</div>
                            <div>${contact.last_touch_date || 'Never'}</div>
                        </div>
                        <div style="background:var(--bg-card);padding:15px;border-radius:12px;">
                            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:5px;">Interactions</div>
                            <div>${contact.total_interactions || 0}</div>
                        </div>
                    </div>

                    ${contact.context ? `
                        <div style="background:var(--bg-card);padding:15px;border-radius:12px;margin-bottom:20px;">
                            <div style="font-size:12px;color:var(--text-secondary);margin-bottom:5px;">Context</div>
                            <div>${contact.context}</div>
                        </div>
                    ` : ''}

                    <h3 style="margin:20px 0 15px;">Recent Activity</h3>
                    <div class="timeline">
                        ${(contact.recent_interactions || []).map(i => `
                            <div class="timeline-item">
                                <div class="timeline-icon ${i.interaction_type}">${getIcon(i.interaction_type)}</div>
                                <div>
                                    <div style="font-weight:500;">${i.summary || i.interaction_type}</div>
                                    <div style="font-size:12px;color:var(--text-secondary);">${formatDate(i.occurred_at)}</div>
                                </div>
                            </div>
                        `).join('') || '<div style="color:var(--text-secondary);">No recent activity</div>'}
                    </div>

                    ${(contact.linked_expenses || []).length ? `
                        <h3 style="margin:20px 0 15px;">Linked Expenses</h3>
                        ${contact.linked_expenses.map(e => `
                            <div style="background:var(--bg-card);padding:12px;border-radius:8px;margin-bottom:10px;display:flex;justify-content:space-between;">
                                <div>
                                    <div>${e.mi_merchant || e.chase_description}</div>
                                    <div style="font-size:12px;color:var(--text-secondary);">${e.chase_date}</div>
                                </div>
                                <div style="font-weight:600;color:var(--accent-green);">$${Math.abs(e.chase_amount).toFixed(2)}</div>
                            </div>
                        `).join('')}
                    ` : ''}
                `;

                document.getElementById('detailModal').classList.add('active');
            } catch (e) {
                console.error('Detail error:', e);
            }
        }

        function closeDetailModal() {
            document.getElementById('detailModal').classList.remove('active');
        }

        async function editContact(id) {
            closeDetailModal();
            try {
                const res = await fetch(`/api/contact-hub/contacts/${id}`);
                const c = await res.json();

                document.getElementById('contactId').value = c.id;
                document.getElementById('contactName').value = c.name || '';
                document.getElementById('contactCompany').value = c.company || '';
                document.getElementById('contactEmail').value = c.email || '';
                document.getElementById('contactPhone').value = c.phone || '';
                document.getElementById('contactTitle').value = c.title || '';
                document.getElementById('contactRelationship').value = c.relationship_type || 'professional';
                document.getElementById('contactFrequency').value = c.touch_frequency_days || 30;
                document.getElementById('contactTeam').value = c.team || '';
                document.getElementById('contactContext').value = c.context || '';
                document.getElementById('contactNotes').value = c.notes || '';
                document.getElementById('contactVIP').checked = c.is_vip || false;

                document.getElementById('modalTitle').textContent = 'Edit Contact';
                document.getElementById('contactModal').classList.add('active');
            } catch (e) {
                console.error('Edit error:', e);
            }
        }

        function getIcon(type) {
            const icons = {
                call: '📞', meeting: '📅', email: '📧', note: '📝',
                imessage_sent: '💬', imessage_received: '💬', expense: '💰'
            };
            return icons[type] || '📌';
        }

        function formatDate(dateStr) {
            if (!dateStr) return '';
            const d = new Date(dateStr);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
        }

        // Init
        loadData();
    </script>
</body>
</html>
'''


# =============================================================================
# AUTOMATIC INTERACTION SYNC (Background)
# =============================================================================

_last_interaction_sync = None
_interaction_sync_interval = 3600  # Sync every hour (in seconds)

def should_sync_interactions():
    """Check if enough time has passed since last sync"""
    global _last_interaction_sync
    if _last_interaction_sync is None:
        return True
    from datetime import datetime, timedelta
    return (datetime.now() - _last_interaction_sync).total_seconds() > _interaction_sync_interval

def background_sync_interactions():
    """Run interaction sync in background thread"""
    global _last_interaction_sync
    import threading
    from datetime import datetime

    def do_sync():
        global _last_interaction_sync
        try:
            print("🔄 Starting automatic interaction sync...")

            # Sync iMessage (if on macOS)
            imessage_result = None
            try:
                from pathlib import Path
                chat_db = Path.home() / "Library" / "Messages" / "chat.db"
                if chat_db.exists():
                    with app.test_request_context():
                        response = api_atlas_sync_imessage_interactions()
                        if hasattr(response, 'get_json'):
                            imessage_result = response.get_json()
                            if imessage_result.get('ok'):
                                print(f"  ✅ iMessage: {imessage_result.get('interactions_created', 0)} new interactions")
            except Exception as e:
                print(f"  ⚠️ iMessage sync error: {e}")

            # Update interaction counts
            try:
                conn, db_type = get_db_connection()
                if conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE contacts c
                        SET interaction_count = (
                            SELECT COUNT(*) FROM interaction_contacts ic WHERE ic.contact_id = c.id
                        )
                    """)
                    cursor.execute("""
                        UPDATE contacts c
                        SET last_touch_date = (
                            SELECT MAX(i.occurred_at)
                            FROM interactions i
                            JOIN interaction_contacts ic ON i.id = ic.interaction_id
                            WHERE ic.contact_id = c.id
                        )
                        WHERE EXISTS (SELECT 1 FROM interaction_contacts ic WHERE ic.contact_id = c.id)
                    """)
                    conn.commit()
                    cursor.close()
                    return_db_connection(conn)
                    print("  ✅ Interaction counts updated")
            except Exception as e:
                print(f"  ⚠️ Count update error: {e}")

            _last_interaction_sync = datetime.now()
            print("✅ Automatic interaction sync complete")

        except Exception as e:
            print(f"❌ Background sync error: {e}")

    # Run in background thread
    thread = threading.Thread(target=do_sync, daemon=True)
    thread.start()


def trigger_sync_if_needed():
    """Trigger background sync if enough time has passed"""
    if should_sync_interactions():
        background_sync_interactions()


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    import argparse
    import shutil
    from datetime import datetime as dt

    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5050)
    args = parser.parse_args()

    # Lightweight backup of the current CSV
    if CSV_PATH.exists():
        ts = dt.now().strftime("%Y%m%d-%H%M%S")
        backup_path = CSV_PATH.with_suffix(f".backup.{ts}.csv")
        shutil.copy2(CSV_PATH, backup_path)
        print(f"💾 Backup created for {CSV_PATH.name} → {backup_path.name}")

    # Validate SQLite database before starting (only for local SQLite)
    if USE_DATABASE and db and hasattr(db, 'use_sqlite') and db.use_sqlite and Path("receipts.db").exists():
        print("🔍 Validating database integrity...")
        try:
            import subprocess
            result = subprocess.run(
                ["python3", "validate_database.py"],
                capture_output=True,
                text=True,
                timeout=30
            )
            if result.returncode != 0:
                print("⚠️  Database validation failed - check validate_database.py output")
        except Exception as e:
            print(f"⚠️  Could not run database validation: {e}")

    load_csv()
    RECEIPT_DIR.mkdir(exist_ok=True)
    TRASH_DIR.mkdir(exist_ok=True)
    load_receipt_meta()

    # Trigger initial interaction sync in background
    print("🔄 Triggering initial interaction sync...")
    trigger_sync_if_needed()

    print(f"🚀 Starting Flask on port {args.port}...")
    # debug=True to keep hot-reloading while you iterate
    app.run(host="0.0.0.0", port=args.port, debug=True)
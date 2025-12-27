"""
================================================================================
OCR (Optical Character Recognition) API Routes
================================================================================
Flask Blueprint for receipt OCR processing and verification.

ENDPOINTS:
----------
Core OCR:
    POST /ocr                           - Mobile scanner OCR with calendar context
    POST /api/ocr/extract               - Full receipt extraction (Mindee-quality)
    POST /api/ocr/process               - Process receipt with Gemini

Verification:
    POST /api/ocr/verify                - Verify receipt matches transaction
    POST /api/ocr/verify-batch          - Batch verify multiple receipts
    POST /api/ocr/verify-transactions   - Verify transactions with receipts

Cache Management:
    GET  /api/ocr/cache-stats           - Get OCR cache statistics
    POST /api/ocr/cache-cleanup         - Clean up expired cache entries

Transaction Integration:
    POST /api/ocr/extract-for-transaction/<id> - Extract OCR for transaction
    GET  /api/ocr/transaction/<id>      - Get OCR data for transaction
    POST /api/ocr/pre-extract           - Pre-extract OCR before matching

Receipt Library:
    GET  /api/ocr/receipt-library       - List receipts with OCR data
    GET  /api/ocr/receipt-library/<filename> - Get specific receipt OCR

================================================================================
"""

import os
import logging
import tempfile
from pathlib import Path
from datetime import datetime
from flask import Blueprint, request, jsonify

# Create blueprint
ocr_bp = Blueprint('ocr', __name__)

# Logger setup
try:
    from logging_config import get_logger
    logger = get_logger(__name__)
except ImportError:
    logger = logging.getLogger(__name__)


# =============================================================================
# LAZY IMPORTS - Avoid circular imports
# =============================================================================

def get_ocr_service():
    """Lazy import OCR service"""
    try:
        from receipt_ocr_service import (
            ReceiptOCRService, extract_receipt, verify_receipt,
            verify_receipts_batch, get_cache_stats
        )
        return {
            'available': True,
            'ReceiptOCRService': ReceiptOCRService,
            'extract_receipt': extract_receipt,
            'verify_receipt': verify_receipt,
            'verify_receipts_batch': verify_receipts_batch,
            'get_cache_stats': get_cache_stats
        }
    except ImportError as e:
        logger.warning(f"OCR service not available: {e}")
        return {'available': False}

def get_gemini_utils():
    """Lazy import Gemini utilities"""
    try:
        from gemini_utils import get_model as get_gemini_model
        from viewer_server import gemini_ocr_extract
        return {
            'available': True,
            'get_model': get_gemini_model,
            'extract': gemini_ocr_extract
        }
    except ImportError as e:
        logger.warning(f"Gemini utils not available: {e}")
        return {'available': False}

def get_auth_helpers():
    """Lazy import auth helpers"""
    from auth import login_required, is_authenticated
    from viewer_server import secure_compare_api_key
    return login_required, is_authenticated, secure_compare_api_key

def get_db_helpers():
    """Lazy import database helpers"""
    from viewer_server import get_db_connection, return_db_connection, db, USE_DATABASE
    return get_db_connection, return_db_connection, db, USE_DATABASE


# =============================================================================
# CORE OCR ENDPOINTS
# =============================================================================

@ocr_bp.route("/ocr", methods=["POST"])
def ocr_endpoint():
    """
    OCR endpoint for mobile scanner using Gemini.
    Extracts merchant, amount, date from receipt image with calendar context.
    """
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    gemini = get_gemini_utils()
    if not gemini['available']:
        return jsonify({"error": "Gemini OCR not available"}), 503

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        import json as json_module
        import PIL.Image

        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        try:
            # Get Gemini model
            model = gemini['get_model']()

            # Load image
            img = PIL.Image.open(tmp_path)

            # Basic extraction first
            basic_result = gemini['extract'](tmp_path)
            receipt_date = basic_result.get('date') or datetime.now().strftime('%Y-%m-%d')

            # Get calendar context for contextual notes
            calendar_context = ""
            try:
                from calendar_service import get_events_around_date, format_events_for_prompt
                events = get_events_around_date(receipt_date, days_before=1, days_after=1)
                if events:
                    calendar_context = format_events_for_prompt(events)
                    logger.info(f"Calendar context for {receipt_date}: {len(events)} events")
            except Exception as cal_err:
                logger.debug(f"Calendar lookup skipped: {cal_err}")

            # Enhanced extraction with calendar context
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

For the "note" field, match the expense to relevant calendar events.

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
                    result = basic_result
                    result['note'] = None
            else:
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

            if result.get('note'):
                logger.info(f"AI Note: {result['note']}")

            return jsonify(result)

        except Exception as e:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            logger.error(f"OCR error: {e}")
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


@ocr_bp.route("/api/ocr/extract", methods=["POST"])
def ocr_extract_full():
    """
    Full receipt extraction using unified OCR service (Mindee-quality).
    Returns complete receipt data including line items.
    """
    _, is_authenticated, secure_compare_api_key = get_auth_helpers()

    admin_key = request.form.get('admin_key') or request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
        return jsonify({"error": "OCR service not available"}), 503

    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        ext = Path(file.filename).suffix.lower() or '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        result = ocr_service['extract_receipt'](tmp_path)
        os.unlink(tmp_path)

        return jsonify(result)

    except Exception as e:
        logger.error(f"OCR extract error: {e}")
        return jsonify({"error": str(e)}), 500


@ocr_bp.route("/api/ocr/verify", methods=["POST"])
def ocr_verify_receipt():
    """Verify a receipt matches expected transaction data."""
    _, is_authenticated, secure_compare_api_key = get_auth_helpers()

    admin_key = request.form.get('admin_key') or request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
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
        ext = Path(file.filename).suffix.lower() or '.jpg'
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            file.save(tmp.name)
            tmp_path = tmp.name

        result = ocr_service['verify_receipt'](
            tmp_path,
            merchant=expected_merchant,
            amount=float(expected_amount),
            date=expected_date
        )

        os.unlink(tmp_path)
        return jsonify(result)

    except Exception as e:
        logger.error(f"OCR verify error: {e}")
        return jsonify({"error": str(e)}), 500


@ocr_bp.route("/api/ocr/verify-batch", methods=["POST"])
def ocr_verify_batch():
    """Batch verify multiple receipts against transactions."""
    _, _, secure_compare_api_key = get_auth_helpers()

    admin_key = (request.json or {}).get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        return jsonify({'error': 'Admin key required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
        return jsonify({"error": "OCR service not available"}), 503

    data = request.get_json()
    if not data or 'items' not in data:
        return jsonify({"error": "Request must include 'items' array"}), 400

    items = data['items']
    if not items:
        return jsonify({"error": "Items array is empty"}), 400

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

    try:
        import time
        start = time.time()
        results = ocr_service['verify_receipts_batch'](batch_items)
        duration = time.time() - start

        verified = sum(1 for r in results if r.get('overall_match'))
        failed = sum(1 for r in results if not r.get('overall_match') and not r.get('error'))
        errors = sum(1 for r in results if r.get('error'))

        return jsonify({
            "total": len(items),
            "verified": verified,
            "failed": failed,
            "errors": errors,
            "duration_seconds": round(duration, 2),
            "results": results
        })
    except Exception as e:
        logger.error(f"OCR batch verify error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

@ocr_bp.route("/api/ocr/cache-stats", methods=["GET"])
def ocr_cache_stats():
    """Get OCR cache statistics."""
    # SECURITY: Require authentication for cache stats
    _, is_authenticated, _ = get_auth_helpers()
    if not is_authenticated():
        return jsonify({'error': 'Authentication required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
        return jsonify({"error": "OCR service not available"}), 503

    try:
        stats = ocr_service['get_cache_stats']()
        return jsonify({"ok": True, "stats": stats})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@ocr_bp.route("/api/ocr/cache-cleanup", methods=["POST"])
def ocr_cache_cleanup():
    """Clean up expired OCR cache entries."""
    _, _, secure_compare_api_key = get_auth_helpers()

    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        return jsonify({'error': 'Admin key required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
        return jsonify({"error": "OCR service not available"}), 503

    try:
        # Import cleanup function
        from receipt_ocr_service import cleanup_cache
        result = cleanup_cache()
        return jsonify({"ok": True, "cleaned": result})
    except Exception as e:
        logger.error(f"Cache cleanup error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# TRANSACTION INTEGRATION
# =============================================================================

@ocr_bp.route("/api/ocr/extract-for-transaction/<int:tx_index>", methods=["POST"])
def ocr_extract_for_transaction(tx_index):
    """Extract OCR data for a specific transaction."""
    _, is_authenticated, secure_compare_api_key = get_auth_helpers()

    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    ocr_service = get_ocr_service()
    if not ocr_service['available']:
        return jsonify({"error": "OCR service not available"}), 503

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        # Get transaction with receipt URL
        cursor.execute("""
            SELECT _index, r2_url, chase_description, chase_amount, chase_date
            FROM transactions WHERE _index = %s
        """, (tx_index,))
        tx = cursor.fetchone()

        if not tx:
            cursor.close()
            return_db_connection(conn)
            return jsonify({"error": "Transaction not found"}), 404

        receipt_url = tx.get('r2_url') if isinstance(tx, dict) else tx[1]
        if not receipt_url:
            cursor.close()
            return_db_connection(conn)
            return jsonify({"error": "Transaction has no receipt"}), 400

        # Extract OCR from receipt URL
        import requests
        import io

        response = requests.get(receipt_url, timeout=30)
        if response.status_code != 200:
            cursor.close()
            return_db_connection(conn)
            return jsonify({"error": f"Failed to fetch receipt: {response.status_code}"}), 500

        # Save to temp file and extract
        with tempfile.NamedTemporaryFile(delete=False, suffix='.jpg') as tmp:
            tmp.write(response.content)
            tmp_path = tmp.name

        result = ocr_service['extract_receipt'](tmp_path)
        os.unlink(tmp_path)

        # Store OCR data in transaction
        import json
        cursor.execute("""
            UPDATE transactions
            SET ocr_data = %s, ocr_verified = 1
            WHERE _index = %s
        """, (json.dumps(result), tx_index))
        conn.commit()

        cursor.close()
        return_db_connection(conn)

        return jsonify({"ok": True, "ocr_data": result})

    except Exception as e:
        logger.error(f"OCR extract for transaction error: {e}")
        return jsonify({"error": str(e)}), 500


@ocr_bp.route("/api/ocr/transaction/<int:tx_index>", methods=["GET"])
def ocr_get_transaction(tx_index):
    """Get OCR data for a transaction."""
    _, is_authenticated, secure_compare_api_key = get_auth_helpers()

    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not secure_compare_api_key(admin_key, expected_key):
        if not is_authenticated():
            return jsonify({'error': 'Authentication required'}), 401

    get_db_connection, return_db_connection, _, _ = get_db_helpers()

    try:
        conn, db_type = get_db_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT ocr_data, ocr_verified, ocr_verification_status
            FROM transactions WHERE _index = %s
        """, (tx_index,))
        row = cursor.fetchone()

        cursor.close()
        return_db_connection(conn)

        if not row:
            return jsonify({"error": "Transaction not found"}), 404

        import json
        ocr_data = row.get('ocr_data') if isinstance(row, dict) else row[0]
        if ocr_data and isinstance(ocr_data, str):
            try:
                ocr_data = json.loads(ocr_data)
            except:
                pass

        return jsonify({
            "ok": True,
            "ocr_data": ocr_data,
            "ocr_verified": row.get('ocr_verified') if isinstance(row, dict) else row[1],
            "ocr_verification_status": row.get('ocr_verification_status') if isinstance(row, dict) else row[2]
        })

    except Exception as e:
        logger.error(f"OCR get transaction error: {e}")
        return jsonify({"error": str(e)}), 500


# =============================================================================
# NOTE: The following routes remain in viewer_server.py for now:
# - /api/ocr/verify-transactions (complex with dataframe dependencies)
# - /api/ocr/receipt-library/* (complex library integration)
# - /api/ocr/pre-extract (complex matching logic)
# - /api/ocr/process (duplicate of extract)
# =============================================================================

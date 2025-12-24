"""
Smart Notes API Blueprint
=========================
Claude-powered contextual notes for transactions.
Combines transaction data, receipt OCR, calendar events, and contacts.
"""

import asyncio
import os
from flask import Blueprint, request, jsonify, session

from logging_config import get_logger

logger = get_logger("routes.notes")

# Create blueprint
notes_bp = Blueprint('notes', __name__, url_prefix='/api/notes')


def get_dependencies():
    """
    Lazy import dependencies to avoid circular imports.
    Returns tuple of (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service,
                      ensure_df, df, parse_amount_str, update_row_by_index,
                      gemini_generate_ai_note)
    """
    # Import from main app
    from viewer_server import (
        SMART_NOTES_SERVICE_AVAILABLE,
        get_smart_notes_service,
        ensure_df,
        df,
        parse_amount_str,
        update_row_by_index,
    )

    # Try to get gemini fallback
    try:
        from viewer_server import gemini_generate_ai_note
    except ImportError:
        gemini_generate_ai_note = None

    return (
        SMART_NOTES_SERVICE_AVAILABLE,
        get_smart_notes_service,
        ensure_df,
        df,
        parse_amount_str,
        update_row_by_index,
        gemini_generate_ai_note
    )


def check_auth():
    """Check if request is authenticated using constant-time comparison."""
    import secrets
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    # SECURITY: Use constant-time comparison to prevent timing attacks
    if admin_key and expected_key and secrets.compare_digest(str(admin_key), str(expected_key)):
        return True
    if session.get('authenticated'):
        return True
    return False


@notes_bp.route("/generate", methods=["POST"])
def api_smart_notes_generate():
    """
    Generate an intelligent, contextual note for a transaction using Claude.
    Combines transaction data, receipt OCR, calendar events, and contacts.

    POST body:
    {
        "_index": int,  # Transaction index (optional if providing details directly)
        "merchant": str,
        "amount": float,
        "date": str,  # YYYY-MM-DD format
        "category": str,
        "business_type": str,
        "receipt_path": str,  # Optional path to receipt image
        "additional_context": str  # Optional user-provided context
    }

    Returns:
    {
        "ok": true,
        "note": str,
        "attendees": [{"name": str, "relationship": str, "company": str}],
        "attendee_count": int,
        "calendar_event": {"title": str, "start": str, "attendees": [str]} | null,
        "business_purpose": str,
        "tax_category": str,
        "confidence": float,
        "data_sources": [str],
        "needs_review": bool
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service, ensure_df,
     df, parse_amount_str, update_row_by_index, _) = get_dependencies()

    if not SMART_NOTES_SERVICE_AVAILABLE:
        return jsonify({'ok': False, 'error': 'Smart notes service not available'}), 503

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
        date_str = row.get("Chase Date") or row.get("transaction_date") or ""
        category = row.get("Chase Category") or row.get("category") or ""
        business_type = row.get("Business Type") or ""
        receipt_path = row.get("Receipt Path") or row.get("receipt_path") or ""
    else:
        merchant = data.get("merchant", "")
        amount = float(data.get("amount", 0))
        date_str = data.get("date", "")
        category = data.get("category", "")
        business_type = data.get("business_type", "")
        receipt_path = data.get("receipt_path", "")
        idx = None

    additional_context = data.get("additional_context", "")

    if not merchant:
        return jsonify({"ok": False, "error": "No merchant provided"}), 400

    try:
        service = get_smart_notes_service()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                service.generate_note(
                    merchant=merchant,
                    amount=amount,
                    date=date_str,
                    category=category,
                    business_type=business_type,
                    receipt_path=receipt_path,
                    additional_context=additional_context
                )
            )
        finally:
            loop.close()

        # If _index provided, save the note
        if idx is not None and result.note:
            update_row_by_index(idx, {"AI Note": result.note}, source="smart_notes_generate")

        response = {
            "ok": True,
            "note": result.note,
            "attendees": [
                {
                    "name": a.name,
                    "relationship": a.relationship or "",
                    "company": a.company or ""
                } for a in result.attendees
            ],
            "attendee_count": result.attendee_count,
            "calendar_event": None,
            "business_purpose": result.business_purpose,
            "tax_category": result.tax_category,
            "confidence": result.confidence,
            "data_sources": result.data_sources,
            "needs_review": result.needs_review,
            "_index": idx
        }

        if result.calendar_event:
            response["calendar_event"] = {
                "title": result.calendar_event.title,
                "start": result.calendar_event.start.isoformat() if result.calendar_event.start else None,
                "end": result.calendar_event.end.isoformat() if result.calendar_event.end else None,
                "attendees": result.calendar_event.attendees
            }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Smart notes generation error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@notes_bp.route("/batch", methods=["POST"])
def api_smart_notes_batch():
    """
    Generate intelligent notes for multiple transactions in batch.

    POST body:
    {
        "indexes": [int, ...],  # List of _index values
        "limit": 50,  # Max transactions (default 50)
        "skip_existing": true  # Skip transactions that already have AI notes
    }

    Returns:
    {
        "ok": true,
        "processed": int,
        "results": [
            {
                "_index": int,
                "merchant": str,
                "note": str,
                "confidence": float,
                "success": bool,
                "error": str | null
            }
        ]
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service, ensure_df,
     df, parse_amount_str, update_row_by_index, gemini_generate_ai_note) = get_dependencies()

    data = request.get_json(force=True) or {}
    indexes = data.get("indexes", [])
    limit = min(int(data.get("limit", 50)), 200)
    skip_existing = data.get("skip_existing", True)
    use_gemini_fallback = data.get("use_gemini_fallback", True)

    ensure_df()

    # Build list of transactions to process
    transactions = []

    if indexes:
        for idx in indexes[:limit]:
            mask = df["_index"] == idx
            if mask.any():
                row = df[mask].iloc[0].to_dict()
                if skip_existing and row.get("AI Note"):
                    continue
                transactions.append({
                    "_index": idx,
                    "merchant": row.get("Chase Description") or row.get("merchant") or "",
                    "amount": parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0),
                    "date": row.get("Chase Date") or row.get("transaction_date") or "",
                    "category": row.get("Chase Category") or row.get("category") or "",
                    "business_type": row.get("Business Type") or "",
                    "receipt_path": row.get("Receipt Path") or "",
                    "row": row
                })
    else:
        for _, row in df.head(limit * 2).iterrows():
            if skip_existing and row.get("AI Note"):
                continue
            if len(transactions) >= limit:
                break
            row_dict = row.to_dict()
            transactions.append({
                "_index": row.get("_index"),
                "merchant": row.get("Chase Description") or row.get("merchant") or "",
                "amount": parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0),
                "date": row.get("Chase Date") or row.get("transaction_date") or "",
                "category": row.get("Chase Category") or row.get("category") or "",
                "business_type": row.get("Business Type") or "",
                "receipt_path": row.get("Receipt Path") or "",
                "row": row_dict
            })

    if not transactions:
        return jsonify({"ok": True, "processed": 0, "results": []})

    output = []

    # Try smart notes service first
    if SMART_NOTES_SERVICE_AVAILABLE:
        try:
            service = get_smart_notes_service()

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                results = loop.run_until_complete(
                    service.generate_batch(transactions)
                )
            finally:
                loop.close()

            for tx, result in zip(transactions, results):
                idx = tx["_index"]
                if result.note:
                    update_row_by_index(idx, {"AI Note": result.note}, source="smart_notes_batch")
                    output.append({
                        "_index": idx,
                        "merchant": tx["merchant"],
                        "note": result.note,
                        "confidence": result.confidence,
                        "success": True,
                        "error": None
                    })
                else:
                    output.append({
                        "_index": idx,
                        "merchant": tx["merchant"],
                        "note": "",
                        "confidence": 0,
                        "success": False,
                        "error": "Failed to generate note"
                    })

            return jsonify({
                "ok": True,
                "processed": len(output),
                "results": output,
                "service": "smart_notes"
            })

        except Exception as e:
            logger.warning(f"Smart notes batch error, trying Gemini fallback: {e}")
            if not use_gemini_fallback:
                return jsonify({"ok": False, "error": str(e)}), 500

    # Fallback to Gemini for batch note generation
    if gemini_generate_ai_note:
        logger.info("Using Gemini fallback for batch note generation")
        for tx in transactions:
            idx = tx["_index"]
            try:
                result = gemini_generate_ai_note(
                    tx["merchant"],
                    tx["amount"],
                    tx["date"],
                    tx["category"],
                    tx["business_type"],
                    row=tx.get("row")
                )

                note = result.get("note", "")
                if note:
                    update_row_by_index(idx, {"AI Note": note}, source="gemini_batch")
                    output.append({
                        "_index": idx,
                        "merchant": tx["merchant"],
                        "note": note,
                        "confidence": 0.7,
                        "success": True,
                        "error": None
                    })
                else:
                    output.append({
                        "_index": idx,
                        "merchant": tx["merchant"],
                        "note": "",
                        "confidence": 0,
                        "success": False,
                        "error": "Gemini failed to generate note"
                    })

            except Exception as e:
                output.append({
                    "_index": idx,
                    "merchant": tx["merchant"],
                    "note": "",
                    "confidence": 0,
                    "success": False,
                    "error": str(e)
                })

    return jsonify({
        "ok": True,
        "processed": len(output),
        "results": output,
        "service": "gemini_fallback"
    })


@notes_bp.route("/<int:tx_id>", methods=["PUT"])
def api_smart_notes_update(tx_id: int):
    """
    Update/edit a transaction note. The system learns from user corrections.

    PUT body:
    {
        "note": str,  # The edited note
        "feedback": str  # Optional feedback about what was wrong
    }

    Returns:
    {
        "ok": true,
        "note": str,
        "learned": bool
    }
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service, ensure_df,
     df, parse_amount_str, update_row_by_index, _) = get_dependencies()

    data = request.get_json(force=True) or {}
    new_note = data.get("note", "").strip()
    feedback = data.get("feedback", "")

    if not new_note:
        return jsonify({"ok": False, "error": "No note provided"}), 400

    ensure_df()
    mask = df["_index"] == tx_id
    if not mask.any():
        return jsonify({"ok": False, "error": f"Transaction {tx_id} not found"}), 404

    row = df[mask].iloc[0].to_dict()
    original_note = row.get("AI Note", "")
    merchant = row.get("Chase Description") or row.get("merchant") or ""

    update_row_by_index(tx_id, {"AI Note": new_note}, source="smart_notes_edit")

    learned = False
    if SMART_NOTES_SERVICE_AVAILABLE and original_note and original_note != new_note:
        try:
            service = get_smart_notes_service()
            service.learn_from_edit(
                merchant=merchant,
                original_note=original_note,
                edited_note=new_note,
                context={
                    "amount": parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0),
                    "date": row.get("Chase Date") or row.get("transaction_date") or "",
                    "category": row.get("Chase Category") or row.get("category") or "",
                    "feedback": feedback
                }
            )
            learned = True
        except Exception as e:
            logger.warning(f"Failed to record note learning: {e}")

    return jsonify({
        "ok": True,
        "note": new_note,
        "learned": learned
    })


@notes_bp.route("/regenerate", methods=["POST"])
def api_smart_notes_regenerate():
    """
    Regenerate a note with updated context or different parameters.

    POST body:
    {
        "_index": int,
        "additional_context": str,
        "force_calendar_refresh": bool,
        "style": str  # "detailed" | "concise" | "audit"
    }

    Returns: Same as /api/notes/generate
    """
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service, ensure_df,
     df, parse_amount_str, update_row_by_index, _) = get_dependencies()

    if not SMART_NOTES_SERVICE_AVAILABLE:
        return jsonify({'ok': False, 'error': 'Smart notes service not available'}), 503

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
    date_str = row.get("Chase Date") or row.get("transaction_date") or ""
    category = row.get("Chase Category") or row.get("category") or ""
    business_type = row.get("Business Type") or ""
    receipt_path = row.get("Receipt Path") or ""

    additional_context = data.get("additional_context", "")
    force_refresh = data.get("force_calendar_refresh", False)
    style = data.get("style", "detailed")

    try:
        service = get_smart_notes_service()

        if force_refresh:
            service.context_cache.clear()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(
                service.regenerate_note(
                    merchant=merchant,
                    amount=amount,
                    date=date_str,
                    additional_context=additional_context,
                    style=style,
                    category=category,
                    business_type=business_type,
                    receipt_path=receipt_path
                )
            )
        finally:
            loop.close()

        if result.note:
            update_row_by_index(idx, {"AI Note": result.note}, source="smart_notes_regenerate")

        response = {
            "ok": True,
            "note": result.note,
            "attendees": [
                {
                    "name": a.name,
                    "relationship": a.relationship or "",
                    "company": a.company or ""
                } for a in result.attendees
            ],
            "attendee_count": result.attendee_count,
            "calendar_event": None,
            "business_purpose": result.business_purpose,
            "tax_category": result.tax_category,
            "confidence": result.confidence,
            "data_sources": result.data_sources,
            "needs_review": result.needs_review,
            "_index": idx
        }

        if result.calendar_event:
            response["calendar_event"] = {
                "title": result.calendar_event.title,
                "start": result.calendar_event.start.isoformat() if result.calendar_event.start else None,
                "end": result.calendar_event.end.isoformat() if result.calendar_event.end else None,
                "attendees": result.calendar_event.attendees
            }

        return jsonify(response)

    except Exception as e:
        logger.error(f"Smart notes regeneration error: {e}")
        return jsonify({"ok": False, "error": str(e)}), 500


@notes_bp.route("/status", methods=["GET"])
def api_smart_notes_status():
    """
    Get the status of the smart notes service.

    Returns:
    {
        "ok": true,
        "available": bool,
        "cache_stats": {...},
        "learning_stats": {...}
    }
    """
    # Security fix: Add authentication check
    if not check_auth():
        return jsonify({'error': 'Authentication required'}), 401

    (SMART_NOTES_SERVICE_AVAILABLE, get_smart_notes_service,
     _, _, _, _, _) = get_dependencies()

    if not SMART_NOTES_SERVICE_AVAILABLE:
        return jsonify({
            "ok": True,
            "available": False,
            "reason": "Smart notes service not loaded"
        })

    try:
        service = get_smart_notes_service()

        cache_stats = {
            "calendar_entries": len(service.context_cache._calendar_cache),
            "contacts_entries": len(service.context_cache._contacts_cache)
        }

        learning_stats = {
            "total_corrections": len(service.learning.corrections)
        }

        return jsonify({
            "ok": True,
            "available": True,
            "cache_stats": cache_stats,
            "learning_stats": learning_stats
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "available": False,
            "error": str(e)
        })

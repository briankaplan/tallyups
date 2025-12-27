"""
AI Routes Blueprint
====================
Gemini-powered AI endpoints for transaction categorization, note generation,
and Apple receipt splitting.

Routes (11 total):
- POST /api/ai/categorize           - AI transaction categorization
- POST /api/ai/note                 - AI note generation
- POST /api/ai/auto-process         - One-click categorize + note
- POST /api/ai/regenerate-notes     - Regenerate notes by criteria
- GET  /api/ai/find-problematic-notes - Find problematic notes
- POST /api/ai/regenerate-birthday-notes - Fix birthday-referenced notes
- POST /api/ai/batch-categorize     - Batch categorization
- POST /api/ai/apple-split-analyze  - Analyze Apple receipt for splitting
- POST /api/ai/apple-split-execute  - Execute Apple receipt split
- GET  /api/ai/apple-split-candidates - Find Apple split candidates
- POST /api/ai/apple-split-all      - Process all Apple splits

Dependencies:
- Gemini AI service for categorization/notes
- Apple receipt splitter service (optional)
- Database for transaction storage
"""

import os
from flask import Blueprint, request, jsonify, session

# Create blueprint
ai_bp = Blueprint('ai', __name__, url_prefix='/api/ai')


def get_ai_services():
    """
    Lazy import AI services to avoid circular dependencies.
    Returns dict with service availability and functions.
    """
    services = {
        'available': False,
        'gemini_available': False,
        'apple_splitter_available': False,
        'error': None
    }

    try:
        # Try to import Gemini AI functions
        from viewer_server import (
            gemini_categorize_transaction,
            gemini_generate_ai_note,
            parse_amount_str,
            ensure_df,
            update_row_by_index,
            load_data,
            get_db_connection,
            return_db_connection,
            db_execute,
            secure_compare_api_key,
            df,
            db,
            USE_DATABASE,
            RECEIPT_DIR
        )

        services['gemini_categorize'] = gemini_categorize_transaction
        services['gemini_note'] = gemini_generate_ai_note
        services['parse_amount'] = parse_amount_str
        services['ensure_df'] = ensure_df
        services['update_row'] = update_row_by_index
        services['load_data'] = load_data
        services['get_db'] = get_db_connection
        services['return_db'] = return_db_connection
        services['db_execute'] = db_execute
        services['secure_compare'] = secure_compare_api_key
        services['RECEIPT_DIR'] = RECEIPT_DIR
        services['USE_DATABASE'] = USE_DATABASE
        services['gemini_available'] = True
        services['available'] = True

    except ImportError as e:
        services['error'] = f"AI services not available: {e}"
        return services

    # Try to import Apple splitter (optional)
    try:
        from apple_receipt_splitter import (
            split_apple_receipt,
            auto_split_transaction,
            find_apple_transactions_to_split,
            process_all_apple_splits
        )
        services['split_apple'] = split_apple_receipt
        services['auto_split'] = auto_split_transaction
        services['find_apple_candidates'] = find_apple_transactions_to_split
        services['process_all_splits'] = process_all_apple_splits
        services['apple_splitter_available'] = True
    except ImportError:
        # Apple splitter is optional
        services['apple_splitter_available'] = False

    return services


def get_current_df():
    """Get current dataframe from viewer_server."""
    try:
        from viewer_server import df
        return df
    except ImportError:
        return None


def get_db_status():
    """Get database availability status."""
    try:
        from viewer_server import db, USE_DATABASE
        return db, USE_DATABASE
    except ImportError:
        return None, False


# =============================================================================
# AI CATEGORIZATION ENDPOINTS
# =============================================================================

@ai_bp.route("/categorize", methods=["POST"])
def api_ai_categorize():
    """
    Gemini-powered AI transaction categorization.

    POST body: {"_index": int} or {"merchant": str, "amount": float, "date": str}
    Returns: {"ok": true, "category": str, "business_type": str, "confidence": int, "reasoning": str}
    """
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available', 'details': services.get('error')}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    # Get transaction data either from _index or direct params
    if "_index" in data:
        services['ensure_df']()
        df = get_current_df()
        idx = int(data["_index"])
        mask = df["_index"] == idx
        if not mask.any():
            return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404
        row = df[mask].iloc[0].to_dict()
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = services['parse_amount'](row.get("Chase Amount") or row.get("amount") or 0)
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
    result = services['gemini_categorize'](merchant, amount, date, category_hint)

    # If _index provided, save the categorization
    if idx is not None and result.get("confidence", 0) >= 60:
        update_data = {}
        if result.get("category"):
            update_data["category"] = result["category"]
        if result.get("business_type"):
            update_data["Business Type"] = result["business_type"]
        if update_data:
            services['update_row'](idx, update_data, source="ai_categorize")

    return jsonify({
        "ok": True,
        "category": result.get("category"),
        "business_type": result.get("business_type"),
        "confidence": result.get("confidence", 0),
        "reasoning": result.get("reasoning", ""),
        "_index": idx
    })


@ai_bp.route("/note", methods=["POST"])
def api_ai_note():
    """
    Gemini-powered AI note generation.

    POST body: {"_index": int} or {"merchant": str, "amount": float, "date": str, "category": str, "business_type": str}
    Returns: {"ok": true, "note": str, "confidence": int}
    """
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    # Get transaction data either from _index or direct params
    if "_index" in data:
        services['ensure_df']()
        df = get_current_df()
        idx = int(data["_index"])
        mask = df["_index"] == idx
        if not mask.any():
            return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404
        row = df[mask].iloc[0].to_dict()
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = services['parse_amount'](row.get("Chase Amount") or row.get("amount") or 0)
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
    result = services['gemini_note'](merchant, amount, date, category, business_type)

    # If _index provided, save the note
    if idx is not None and result.get("note"):
        services['update_row'](idx, {"AI Note": result["note"]}, source="ai_note_gemini")

    return jsonify({
        "ok": True,
        "note": result.get("note", ""),
        "confidence": result.get("confidence", 0),
        "_index": idx
    })


@ai_bp.route("/auto-process", methods=["POST"])
def api_ai_auto_process():
    """
    One-click AI processing: categorize + generate note in one call.

    POST body: {"_index": int}
    Returns: {"ok": true, "category": str, "business_type": str, "note": str, "confidence": int}
    """
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}

    if "_index" not in data:
        return jsonify({"ok": False, "error": "Missing _index"}), 400

    services['ensure_df']()
    df = get_current_df()
    idx = int(data["_index"])
    mask = df["_index"] == idx
    if not mask.any():
        return jsonify({"ok": False, "error": f"_index {idx} not found"}), 404

    row = df[mask].iloc[0].to_dict()
    merchant = row.get("Chase Description") or row.get("merchant") or ""
    amount = services['parse_amount'](row.get("Chase Amount") or row.get("amount") or 0)
    date = row.get("Chase Date") or row.get("transaction_date") or ""
    category_hint = row.get("Chase Category") or row.get("category") or ""

    if not merchant:
        return jsonify({"ok": False, "error": "No merchant in transaction"}), 400

    # Step 1: Categorize (pass full row for context)
    cat_result = services['gemini_categorize'](merchant, amount, date, category_hint, row=row)

    # Step 2: Generate note with category context (pass full row)
    note_result = services['gemini_note'](
        merchant, amount, date,
        cat_result.get("category", ""),
        cat_result.get("business_type", "Business"),
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
        services['update_row'](idx, update_data, source="ai_auto_process")

    return jsonify({
        "ok": True,
        "category": cat_result.get("category"),
        "business_type": cat_result.get("business_type"),
        "note": note_result.get("note"),
        "confidence": min(cat_result.get("confidence", 0), note_result.get("confidence", 0)),
        "reasoning": cat_result.get("reasoning", ""),
        "_index": idx
    })


@ai_bp.route("/batch-categorize", methods=["POST"])
def api_ai_batch_categorize():
    """
    Batch AI categorization for multiple transactions.

    POST body: {"indexes": [int, int, ...], "limit": 50}
    Returns: {"ok": true, "processed": int, "results": [...]}
    """
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}
    indexes = data.get("indexes", [])
    limit = min(data.get("limit", 50), 100)  # Max 100 at once

    services['ensure_df']()
    df = get_current_df()

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
            amount = services['parse_amount'](row.get("Chase Amount") or row.get("amount") or 0)
            date = row.get("Chase Date") or row.get("transaction_date") or ""
            category_hint = row.get("Chase Category") or ""

            if not merchant:
                continue

            result = services['gemini_categorize'](merchant, amount, date, category_hint)

            # Save if confident
            if result.get("confidence", 0) >= 50:
                update_data = {}
                if result.get("category"):
                    update_data["category"] = result["category"]
                if result.get("business_type"):
                    update_data["Business Type"] = result["business_type"]
                if update_data:
                    services['update_row'](idx, update_data, source="batch_categorize")

            results.append({
                "_index": idx,
                "merchant": merchant,
                "category": result.get("category"),
                "business_type": result.get("business_type"),
                "confidence": result.get("confidence", 0)
            })

        except Exception as e:
            print(f"Batch categorize error for {idx}: {e}")
            continue

    return jsonify({
        "ok": True,
        "processed": len(results),
        "results": results
    })


# =============================================================================
# NOTE REGENERATION ENDPOINTS
# =============================================================================

@ai_bp.route("/find-problematic-notes", methods=["GET"])
def api_ai_find_problematic_notes():
    """
    Find transactions with AI notes that reference birthdays or are too vague.

    Query params:
    - filter: "birthday" | "vague" | "all" (default: "birthday")
    - limit: max results (default: 100)

    Returns: {"ok": true, "count": int, "transactions": [...]}
    """
    services = get_ai_services()
    if not services['available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check - SECURITY: Use constant-time comparison to prevent timing attacks
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    key_valid = services['secure_compare'](admin_key, expected_key) or services['secure_compare'](admin_key, auth_password)
    if not key_valid:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    filter_type = request.args.get("filter", "birthday")
    limit = min(int(request.args.get("limit", 100)), 500)

    services['ensure_df']()
    df = get_current_df()

    # Keywords
    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']
    vague_keywords = ['business expense', 'business meal', 'client meeting', 'software subscription',
                      'travel expense', 'meal with team', 'various business']

    matches = []

    for _, row in df.iterrows():
        # Check all possible note fields
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


@ai_bp.route("/regenerate-notes", methods=["POST"])
def api_ai_regenerate_notes():
    """
    Regenerate AI notes for transactions matching certain criteria.

    POST body:
    {
        "filter": "birthday" | "vague" | "all",
        "indexes": [int, ...],  # Optional: specific indexes
        "limit": 50,
        "dry_run": false
    }

    Returns: {"ok": true, "processed": int, "updated": int, "results": [...]}
    """
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check - SECURITY: Use constant-time comparison to prevent timing attacks
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    key_valid = services['secure_compare'](admin_key, expected_key) or services['secure_compare'](admin_key, auth_password)
    if not key_valid:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    data = request.get_json(force=True) or {}
    filter_type = data.get("filter", "birthday")
    indexes = data.get("indexes", [])
    limit = min(data.get("limit", 50), 200)
    dry_run = data.get("dry_run", False)

    services['ensure_df']()
    df = get_current_df()

    # Keywords that indicate problematic notes
    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']
    vague_keywords = ['business expense', 'business meal', 'client meeting', 'software subscription',
                      'travel expense', 'meal with team', 'various business']

    results = []
    updated_count = 0

    # Get transactions to check
    if indexes:
        candidates = df[df["_index"].isin(indexes)]
    else:
        # Find all transactions with notes
        note_cols = ["AI Note", "ai_note", "notes"]
        has_notes = None
        for col in note_cols:
            if col in df.columns:
                col_has_notes = df[col].fillna("").str.len() > 0
                has_notes = col_has_notes if has_notes is None else (has_notes | col_has_notes)

        if has_notes is not None:
            candidates = df[has_notes]
        else:
            candidates = df.head(0)

    # Filter by criteria
    filtered_rows = []
    for _, row in candidates.head(limit * 3).iterrows():
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
        amount = services['parse_amount'](row.get("Chase Amount") or row.get("amount") or 0)
        date = row.get("Chase Date") or row.get("transaction_date") or ""
        category = row.get("category") or row.get("Chase Category") or ""
        business_type = row.get("Business Type") or "Business"

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
            note_result = services['gemini_note'](
                merchant, amount, date, category, business_type,
                row=row.to_dict()
            )

            new_note = note_result.get("note", "")

            if new_note and new_note != old_note:
                services['update_row'](idx, {"AI Note": new_note}, source="ai_regenerate")
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


@ai_bp.route("/regenerate-birthday-notes", methods=["POST"])
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
    services = get_ai_services()
    if not services['gemini_available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check - SECURITY: Use constant-time comparison to prevent timing attacks
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    auth_password = os.getenv('AUTH_PASSWORD')
    key_valid = services['secure_compare'](admin_key, expected_key) or services['secure_compare'](admin_key, auth_password)
    if not key_valid:
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    db, USE_DATABASE = get_db_status()
    if not USE_DATABASE or not db:
        return jsonify({'error': 'Database not available'}), 503

    data = request.get_json(force=True) or {}
    dry_run = data.get("dry_run", True)
    limit = min(int(data.get("limit", 100)), 200)

    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']

    # Build SQL LIKE clauses
    like_clauses = []
    for kw in birthday_keywords:
        escaped_kw = kw.replace("'", "''")
        like_clauses.append(f"LOWER(ai_note) LIKE '%{escaped_kw}%'")

    conn, _ = services['get_db']()
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
        services['return_db'](conn)
        return jsonify({'error': f'Query failed: {e}'}), 500

    if not rows:
        services['return_db'](conn)
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
        amount = services['parse_amount'](row.get('chase_amount', 0))
        date = row.get('chase_date', '')
        category = row.get('chase_category', '')
        business_type = row.get('business_type', 'Business')
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

        # Regenerate note using Gemini
        try:
            note_result = services['gemini_note'](
                merchant, amount, str(date), category, business_type
            )
            new_note = note_result.get('note', '')

            if new_note and new_note != old_note:
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

    services['return_db'](conn)

    # Reload df to sync with database changes
    if updated_count > 0:
        services['load_data'](force_refresh=True)

    return jsonify({
        'ok': True,
        'dry_run': dry_run,
        'found': len(rows),
        'updated': updated_count,
        'results': results
    })


# =============================================================================
# APPLE RECEIPT SPLITTER ENDPOINTS
# =============================================================================

@ai_bp.route("/apple-split-analyze", methods=["POST"])
def api_ai_apple_split_analyze():
    """
    Analyze an Apple receipt image to identify personal vs business items.
    Does NOT create split transactions - just returns the analysis.

    POST body: {"receipt_path": "applecombill_xxx.jpg"} or {"transaction_id": 123}
    Returns: Analysis with items classified by business type
    """
    services = get_ai_services()
    if not services['available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not services['apple_splitter_available']:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    receipt_path = data.get("receipt_path")
    transaction_id = data.get("transaction_id")

    # If transaction_id provided, look up the receipt
    if transaction_id and not receipt_path:
        try:
            conn, db_type = services['get_db']()
            cursor = services['db_execute'](conn, db_type,
                "SELECT receipt_file FROM transactions WHERE id = ?",
                (transaction_id,))
            row = cursor.fetchone()
            services['return_db'](conn)
            if row and row.get('receipt_file'):
                receipt_path = row['receipt_file']
            else:
                return jsonify({'error': f'No receipt found for transaction {transaction_id}'}), 404
        except Exception as e:
            return jsonify({'error': f'Database error: {e}'}), 500

    if not receipt_path:
        return jsonify({'error': 'receipt_path or transaction_id required'}), 400

    # Build full path
    RECEIPT_DIR = services['RECEIPT_DIR']
    if not receipt_path.startswith('/'):
        full_path = str(RECEIPT_DIR / receipt_path)
    else:
        full_path = receipt_path

    if not os.path.exists(full_path):
        return jsonify({'error': f'Receipt file not found: {receipt_path}'}), 404

    try:
        result = services['split_apple'](full_path)
        return jsonify({
            "ok": True,
            "analysis": result
        })
    except Exception as e:
        print(f"Apple split analyze error: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route("/apple-split-execute", methods=["POST"])
def api_ai_apple_split_execute():
    """
    Execute an Apple receipt split - creates new split transactions in the database.
    Links the SAME receipt to ALL split transactions.

    POST body: {"transaction_id": 123} or {"transaction_id": 123, "receipt_path": "xxx.jpg"}
    Returns: Created split transactions with linked receipt
    """
    services = get_ai_services()
    if not services['available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not services['apple_splitter_available']:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    transaction_id = data.get("transaction_id")
    receipt_path = data.get("receipt_path")

    if not transaction_id:
        return jsonify({'error': 'transaction_id required'}), 400

    try:
        result = services['auto_split'](transaction_id, receipt_path)

        if result.get('error'):
            return jsonify({'error': result['error']}), 400

        # Refresh dataframe to pick up new transactions
        services['load_data'](force_refresh=True)

        return jsonify({
            "ok": True,
            "result": result
        })
    except Exception as e:
        print(f"Apple split execute error: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route("/apple-split-candidates", methods=["GET"])
def api_ai_apple_split_candidates():
    """
    Find Apple transactions that might need splitting.

    Query params: limit (default 50)
    Returns: List of Apple transactions with their receipts
    """
    services = get_ai_services()
    if not services['available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not services['apple_splitter_available']:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    limit = request.args.get('limit', 50, type=int)

    try:
        candidates = services['find_apple_candidates'](limit=limit)
        return jsonify({
            "ok": True,
            "count": len(candidates),
            "candidates": candidates
        })
    except Exception as e:
        print(f"Apple split candidates error: {e}")
        return jsonify({'error': str(e)}), 500


@ai_bp.route("/apple-split-all", methods=["POST"])
def api_ai_apple_split_all():
    """
    Process all Apple transactions - analyze and split where needed.

    POST body: {"dry_run": true/false, "limit": 50}
    Returns: Summary of splits performed
    """
    services = get_ai_services()
    if not services['available']:
        return jsonify({'error': 'AI services not available'}), 503

    # Auth check
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if not services['secure_compare'](admin_key, expected_key):
        if not session.get('authenticated'):
            return jsonify({'error': 'Authentication required'}), 401

    if not services['apple_splitter_available']:
        return jsonify({'error': 'Apple receipt splitter not available'}), 503

    data = request.get_json(force=True) or {}
    dry_run = data.get("dry_run", True)
    limit = data.get("limit", 50)

    try:
        results = services['process_all_splits'](dry_run=dry_run, limit=limit)

        # Refresh dataframe if we made changes
        if not dry_run and results.get('splits_created', 0) > 0:
            services['load_data'](force_refresh=True)

        return jsonify({
            "ok": True,
            "dry_run": dry_run,
            "results": results
        })
    except Exception as e:
        print(f"Apple split all error: {e}")
        return jsonify({'error': str(e)}), 500

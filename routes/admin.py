from flask import Blueprint, request, jsonify, abort
import os
import logging

logger = logging.getLogger(__name__)

admin_bp = Blueprint("admin", __name__)

@admin_bp.route("/plaid-import-debug", methods=["POST"])
def plaid_import_debug():
    data = request.get_json(silent=True) or {}
    if data.get("admin_key") != os.getenv("ADMIN_KEY"):
        abort(404)

    try:
        from services.plaid_service import get_plaid_service
        plaid = get_plaid_service()

        # Run import
        result = plaid.import_to_transactions()

        return jsonify({
            "ok": True,
            "result": result
        })
    except Exception as e:
        logger.error(f"Plaid import debug error: {e}")
        return jsonify({
            "ok": False,
            "error": str(e)
        }), 500

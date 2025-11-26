#!/usr/bin/env python3
import os
import math
import json
import base64
import random
import re
import zipfile
import io
import sqlite3
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime, date

from flask import Flask, send_from_directory, jsonify, request, abort, Response, make_response, send_file
from werkzeug.middleware.proxy_fix import ProxyFix
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

# === DATABASE ===
USE_DATABASE = False
db = None

# Try MySQL first (best for Railway deployment)
try:
    from db_mysql import get_mysql_db
    db = get_mysql_db()
    if db.use_mysql:
        USE_DATABASE = True
        print(f"✅ Using MySQL database")
    else:
        db = None
except Exception as e:
    print(f"ℹ️  MySQL not available: {e}")

# Fall back to SQLite if MySQL not available
if not USE_DATABASE:
    try:
        from db_sqlite import get_db
        db = get_db()
        if db.use_sqlite:
            USE_DATABASE = True
            print(f"✅ Using SQLite database: receipts.db")
        else:
            db = None
    except Exception as e:
        print(f"⚠️ Could not load SQLite: {e}")

# Final fallback to CSV mode
if not USE_DATABASE:
    print(f"ℹ️  No database available, using CSV mode")
    USE_DATABASE = False
    db = None

# Maintain backward compatibility with old variable name
# Legacy alias - all code should use USE_DATABASE
# Note: This is assigned after database init, so it reflects the correct value
USE_SQLITE = USE_DATABASE

# === DATABASE HELPER FUNCTIONS ===
def get_db_connection():
    """
    Get a database connection that works for both MySQL and SQLite.

    Returns: (conn, db_type) tuple where:
    - conn: database connection object
    - db_type: 'mysql' or 'sqlite'

    IMPORTANT: Caller must close the connection when done!
    For MySQL, cursor is already DictCursor.
    For SQLite, set row_factory after getting connection.
    """
    if not USE_DATABASE or not db:
        raise RuntimeError("No database available")

    if hasattr(db, 'use_mysql') and db.use_mysql:
        return db.get_connection(), 'mysql'
    else:
        conn = sqlite3.connect(str(db.db_path))
        conn.row_factory = sqlite3.Row
        return conn, 'sqlite'


def db_execute(conn, db_type, sql, params=None):
    """
    Execute SQL with proper placeholder syntax for each database type.

    For MySQL: use %s placeholders
    For SQLite: use ? placeholders

    Automatically converts ? to %s for MySQL.
    """
    if db_type == 'mysql':
        # Convert SQLite ? placeholders to MySQL %s
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

# =============================================================================
# PATHS / GLOBALS
# =============================================================================
BASE_DIR = Path(__file__).resolve().parent

CSV_PATH = BASE_DIR / "FINAL_MASTER_RECONCILED.csv"
RECEIPT_DIR = BASE_DIR / "receipts"
TRASH_DIR = BASE_DIR / "receipts_trash"
RECEIPT_META_PATH = BASE_DIR / "receipt_ai_metadata.csv"

app = Flask(__name__)

# Configure app to trust Railway proxy headers (for HTTPS detection)
if os.environ.get('RAILWAY_ENVIRONMENT'):
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

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


OPENAI_API_KEY = require_env("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


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
# CSV LOAD / SAVE (with corruption diagnostics + auto-repair)
# =============================================================================

def load_csv():
    """Load data from database (if available) or CSV (fallback). Diagnose corruption and attempt auto-repair."""
    global df

    # Try database first (MySQL or SQLite)
    if USE_DATABASE and db:
        try:
            df = db.get_all_transactions()
            # Ensure _index is integer for proper comparisons
            if '_index' in df.columns:
                df['_index'] = pd.to_numeric(df['_index'], errors='coerce').fillna(0).astype(int)
            db_type = "MySQL" if hasattr(db, 'use_mysql') and db.use_mysql else "SQLite"
            print(f"✅ Loaded {len(df)} transactions from {db_type}")
            return
        except Exception as e:
            print(f"⚠️  Database load failed: {e}, falling back to CSV")

    # Fallback to CSV
    if not CSV_PATH.exists():
        raise FileNotFoundError(f"CSV not found at {CSV_PATH}")

    try:
        raw = pd.read_csv(
            CSV_PATH,
            dtype=str,
            keep_default_na=False,
            quotechar='"',
            escapechar='\\'
        )
        used_path = CSV_PATH
        print(f"✅ Loaded CSV: {len(raw)} rows from {CSV_PATH.name}")
    except Exception as e:
        print("\n" + "=" * 80)
        print("❌ CSV PARSE FAILURE — DIAGNOSTICS".center(80))
        print("=" * 80 + "\n")

        print(f"📄 File: {CSV_PATH}")
        print(f"⚠️ Pandas Error: {e}\n")

        # Try to isolate corruption manually
        print("🔍 Scanning file to identify corrupt line(s)...\n")

        expected_cols = None
        corrupt_lines = []

        with open(CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
            for i, line in enumerate(f, start=1):
                cols = line.count(",") + 1
                if expected_cols is None:
                    expected_cols = cols  # first line (header)
                elif cols != expected_cols:
                    corrupt_lines.append((i, cols, line.strip()))

        if corrupt_lines:
            print(f"❗ Found {len(corrupt_lines)} malformed line(s):\n")
            for line_no, col_count, text in corrupt_lines[:10]:
                print(f"  • Line {line_no}: {col_count} columns (expected {expected_cols})")
                preview = text[:200]
                if len(text) > 200:
                    preview += "..."
                print(f"    → {preview}\n")

            if len(corrupt_lines) > 10:
                print(f"  …and {len(corrupt_lines) - 10} more.\n")
        else:
            print("⚠️ No obvious malformed rows. The issue may be due to quotes or escape characters.\n")

        print("=" * 80)
        print("🛠 SUGGESTED FIXES".center(80))
        print("=" * 80)
        print(
            """
• Check for embedded commas inside fields not wrapped in quotes.
• Check for unescaped quotes. Example:
    7pm "Dinner"  →  "7pm \"Dinner\""
• Look for double line breaks or pasted multi-line text in a single cell.
• Make sure every non-header row has the same number of commas as the header.
• If the file was edited in Excel/Numbers, re-export as CSV UTF-8.

Tip: This server will also attempt a 'repaired' version:
    FINAL_MASTER_RECONCILED.repaired.csv

"""
        )
        print("=" * 80)
        print("\n🛠 Attempting to auto-repair CSV…")

        # Damage-control pass
        with open(CSV_PATH, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()

        repaired = []
        for ln in lines:
            # remove null bytes
            ln = ln.replace("\x00", "")
            # if odd number of quotes, strip them (prevents broken CSV state)
            if ln.count('"') % 2 != 0:
                ln = ln.replace('"', "")
            repaired.append(ln)

        repaired_path = CSV_PATH.with_suffix(".repaired.csv")
        with open(repaired_path, "w", encoding="utf-8") as f:
            f.writelines(repaired)

        print(f"📄 Wrote repaired candidate CSV → {repaired_path.name}")

        raw = pd.read_csv(
            repaired_path,
            dtype=str,
            keep_default_na=False,
            on_bad_lines="skip",
            engine="python",
        )
        used_path = repaired_path
        print("✅ Loaded repaired CSV successfully.")

    # Ensure core columns
    if "_index" not in raw.columns:
        raw["_index"] = list(range(len(raw)))
    else:
        try:
            raw["_index"] = raw["_index"].astype(int)
        except Exception:
            raw["_index"] = list(range(len(raw)))

    # Make sure our "AI columns" exist
    needed_cols = [
        "ai_receipt_merchant",
        "ai_receipt_date",
        "ai_receipt_total",
        "ai_match_raw",
        "ai_match",
        "ai_confidence",
        "ai_reason",
        # Option B extra AI columns:
        "ai_people",
        "ai_business_rationale",
        "ai_subscription_reason",
        "ai_location_reason",
        "ai_merchant_normalized",
        "ai_report_block",
    ]
    for col in needed_cols:
        if col not in raw.columns:
            raw[col] = ""

    df_clean = sanitize_csv(raw)
    df = df_clean
    return df


def save_csv():
    """Persist df to disk (SQLite if available, otherwise CSV)."""
    global df
    if df is None:
        return

    # Save to SQLite if available
    if USE_SQLITE and db:
        # SQLite updates happen per-row, so this is mostly for CSV export
        try:
            db.export_to_csv(str(CSV_PATH))
            print("💾 Saved to SQLite + exported CSV", flush=True)
        except Exception as e:
            print(f"⚠️  SQLite save failed: {e}, saving to CSV only")
            df.to_csv(CSV_PATH, index=False)
            print("💾 Saved CSV", flush=True)
    else:
        # CSV mode
        df.to_csv(CSV_PATH, index=False)
        print("💾 Saved CSV", flush=True)


def ensure_df():
    """Lazy loader used by all routes."""
    global df
    if df is None:
        load_csv()
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
    Apply patch to df row with given _index, then save to SQLite + CSV.

    CRITICAL FIX: This function now:
    1. Saves changes to SQLite IMMEDIATELY using db.update_transaction()
    2. Logs all changes to audit log for tracking
    3. Updates in-memory DataFrame
    4. Exports to CSV for backward compatibility

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

    # === STEP 1: Update SQLite FIRST (most important) ===
    if USE_SQLITE and db:
        try:
            success = db.update_transaction(idx, patch)
            if not success:
                print(f"❌ SQLite update failed for row #{idx}", flush=True)
                return False
            print(f"💾 SQLite updated: row #{idx}", flush=True)
        except Exception as e:
            print(f"❌ SQLite error for row #{idx}: {e}", flush=True)
            return False
    else:
        print(f"⚠️  SQLite not available, CSV mode only", flush=True)

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

    # === STEP 4: Export to CSV (backward compatibility) ===
    try:
        if USE_SQLITE and db:
            db.export_to_csv(str(CSV_PATH))
        else:
            df.to_csv(CSV_PATH, index=False)
        print(f"📄 CSV exported", flush=True)
    except Exception as e:
        print(f"⚠️  CSV export failed: {e}", flush=True)
        # Don't fail the update if CSV export fails

    return True


# =============================================================================
# RECEIPT META CACHE (VISION ONCE PER FILE)
# =============================================================================

def load_receipt_meta():
    global receipt_meta_cache
    receipt_meta_cache = {}
    if not RECEIPT_META_PATH.exists():
        print("ℹ️ No receipt metadata CSV yet")
        return
    try:
        meta_df = pd.read_csv(RECEIPT_META_PATH, dtype=str, keep_default_na=False)
        for _, row in meta_df.iterrows():
            filename = row["filename"]
            receipt_meta_cache[filename] = {
                "filename": filename,
                "merchant_name": row.get("merchant_name", ""),
                "merchant_normalized": row.get("merchant_normalized", ""),
                "receipt_date": row.get("receipt_date", ""),
                "total_amount": parse_amount_str(row.get("total_amount", "")),
                "subtotal_amount": parse_amount_str(row.get("subtotal_amount", "")),
                "tip_amount": parse_amount_str(row.get("tip_amount", "")),
                "raw_json": row.get("raw_json", ""),
            }
        print(f"📑 Loaded receipt metadata for {len(receipt_meta_cache)} files")
    except Exception as e:
        print(f"⚠️ Could not load receipt metadata: {e}")


def save_receipt_meta():
    global receipt_meta_cache
    if not receipt_meta_cache:
        return
    rows = []
    for meta in receipt_meta_cache.values():
        rows.append({
            "filename": meta.get("filename", ""),
            "merchant_name": meta.get("merchant_name", ""),
            "merchant_normalized": meta.get("merchant_normalized", ""),
            "receipt_date": meta.get("receipt_date", ""),
            "total_amount": meta.get("total_amount", ""),
            "subtotal_amount": meta.get("subtotal_amount", ""),
            "tip_amount": meta.get("tip_amount", ""),
            "raw_json": meta.get("raw_json", ""),
        })
    meta_df = pd.DataFrame(rows)
    meta_df.to_csv(RECEIPT_META_PATH, index=False)
    print(f"📑 Saved receipt metadata for {len(rows)} files")


def encode_image_base64(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


def extract_receipt_with_vision(path: Path) -> dict | None:
    """
    Extract receipt fields using Donut (primary) with GPT-4.1 fallback.

    Returns:
      - merchant_name
      - receipt_date (YYYY-MM-DD if possible)
      - subtotal_amount
      - tip_amount
      - total_amount (final charged total, including handwritten tip if present)
    """
    print(f"👁️  Vision extracting {path}", flush=True)

    # Try Donut first (FREE, FAST, 97-98% accuracy)
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
    """Serve the HTML viewer."""
    return send_from_directory(BASE_DIR, "receipt_reconciler_viewer.html")


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


@app.route("/manifest.json")
def pwa_manifest():
    """Serve PWA manifest."""
    return send_from_directory(BASE_DIR, "manifest.json", mimetype='application/manifest+json')


@app.route("/sw.js")
def service_worker():
    """Serve service worker."""
    return send_from_directory(BASE_DIR, "sw.js", mimetype='application/javascript')


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
    # Check R2 storage configuration
    r2_configured = bool(
        os.environ.get('R2_ACCOUNT_ID') and
        os.environ.get('R2_ACCESS_KEY_ID') and
        os.environ.get('R2_SECRET_ACCESS_KEY')
    )

    # Check Gemini API configuration
    gemini_configured = bool(os.environ.get('GEMINI_API_KEY'))

    return jsonify({
        "status": "ok",
        "database": "connected" if db else "none",
        "storage": "ok" if r2_configured else "not_configured",
        "r2_connected": r2_configured,
        "ai": "ok" if gemini_configured else "not_configured",
        "gemini_configured": gemini_configured
    })


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


@app.route("/mobile-upload", methods=["POST"])
@login_required
def mobile_upload():
    """
    Handle receipt uploads from mobile scanner PWA.
    Creates an incoming receipt entry tagged with source=mobile_scanner.
    """
    if 'file' not in request.files:
        return jsonify({"error": "No file provided"}), 400

    file = request.files['file']
    if not file.filename:
        return jsonify({"error": "No file selected"}), 400

    try:
        # Get form data
        merchant = request.form.get('merchant', 'Unknown')
        amount = request.form.get('amount', '0.00')
        date_str = request.form.get('date', datetime.now().strftime('%Y-%m-%d'))
        category = request.form.get('category', '')
        business = request.form.get('business', '')
        notes = request.form.get('notes', '')
        source = request.form.get('source', 'mobile_scanner')

        # Parse amount
        try:
            amount_float = float(amount.replace('$', '').replace(',', ''))
        except:
            amount_float = 0.0

        # Save receipt file to incoming folder
        incoming_dir = RECEIPTS_DIR / "incoming"
        incoming_dir.mkdir(parents=True, exist_ok=True)

        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_merchant = re.sub(r'[^\w\-]', '_', merchant)[:30]
        ext = Path(file.filename).suffix or '.jpg'
        filename = f"mobile_{safe_merchant}_{timestamp}{ext}"

        file_path = incoming_dir / filename
        file.save(str(file_path))

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

                # Insert the incoming receipt
                cursor = db_execute(conn, db_type, '''
                    INSERT INTO incoming_receipts
                    (source, sender, subject, receipt_date, merchant, amount, category,
                     business_type, receipt_file, status, notes, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                ''', (
                    source,
                    'Mobile Scanner',
                    f'Receipt from {merchant}',
                    date_str,
                    merchant,
                    amount_float,
                    category,
                    business,
                    f"incoming/{filename}",
                    notes,
                    datetime.now().isoformat()
                ))

                receipt_id = cursor.lastrowid
                conn.commit()
                conn.close()

                print(f"📱 Mobile receipt uploaded: {merchant} ${amount_float:.2f} -> {filename}")

            except Exception as e:
                print(f"⚠️ Database error saving mobile receipt: {e}")

        return jsonify({
            "success": True,
            "id": receipt_id,
            "filename": filename,
            "merchant": merchant,
            "amount": amount_float,
            "message": "Receipt uploaded to incoming queue"
        })

    except Exception as e:
        print(f"❌ Mobile upload error: {e}")
        return jsonify({"error": str(e)}), 500


@app.route("/csv")
@app.route("/api/transactions")
@login_required
def get_transactions():
    """
    Return all transactions as JSON from SQLite.

    Routes:
    - /api/transactions (preferred)
    - /csv (legacy, kept for backwards compatibility)

    PURE SQL MODE: Always reads fresh from database, no caching!

    Query params:
    - show_submitted=true: Include submitted transactions (default: hide them)
    """
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
                conn.close()  # Close the NEW connection we got

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

                conn.close()

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

    # Use database if available (MySQL or SQLite)
    if USE_DATABASE and db:
        try:
            success = db.update_transaction(idx, patch)
            if not success:
                abort(404, f"_index {idx} not found")

            # Reload df to stay in sync
            df = db.get_all_transactions()
            return jsonify(safe_json({"ok": True}))
        except Exception as e:
            print(f"⚠️  SQLite update failed: {e}, falling back to CSV")
            # Fall through to CSV mode

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
                if USE_SQLITE and db:
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
                if USE_SQLITE and db:
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
            if USE_SQLITE and db:
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
            if USE_SQLITE and db:
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
    if USE_SQLITE and db:
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
            if USE_SQLITE and db:
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
            # Confidence too low, return suggestion
            temp_path.unlink(missing_ok=True)
            return jsonify(safe_json({
                "ok": True,
                "matched": True,
                "auto_attached": False,
                "ocr_data": ocr_data,
                "transaction": match["row"],
                "confidence": confidence,
                "message": f"Found possible match ({confidence}% confidence). Please verify and attach manually."
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
            conn.close()

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
    Body: { "_index": int }

    Moves file (if exists) to receipts_trash, clears Receipt File columns,
    and PERMANENTLY tracks the rejection so it NEVER comes back.
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

    mask = df["_index"] == idx
    if not mask.any():
        abort(404, f"_index {idx} not found")

    row = df.loc[mask].iloc[0]

    # Get transaction details for rejection tracking
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

        # CRITICAL: Save rejection to database so it NEVER comes back
        if USE_DATABASE and db:
            try:
                conn, db_type = get_db_connection()

                # Create rejected_receipts table if it doesn't exist (SQLite only, MySQL has it in init)
                if db_type == 'sqlite':
                    cursor = conn.cursor()
                    cursor.execute('''
                        CREATE TABLE IF NOT EXISTS rejected_receipts (
                            id INTEGER PRIMARY KEY AUTOINCREMENT,
                            transaction_date TEXT NOT NULL,
                            transaction_description TEXT NOT NULL,
                            transaction_amount TEXT NOT NULL,
                            receipt_path TEXT NOT NULL,
                            rejected_at TEXT DEFAULT CURRENT_TIMESTAMP,
                            reason TEXT DEFAULT 'user_manually_removed',
                            UNIQUE(transaction_date, transaction_description, transaction_amount, receipt_path)
                        )
                    ''')

                # Record the rejection permanently
                # MySQL uses ON DUPLICATE KEY, SQLite uses INSERT OR REPLACE
                if db_type == 'mysql':
                    cursor = db_execute(conn, db_type, '''
                        INSERT INTO rejected_receipts
                        (transaction_date, transaction_description, transaction_amount, receipt_path, reason)
                        VALUES (?, ?, ?, ?, ?)
                        ON DUPLICATE KEY UPDATE reason = VALUES(reason), rejected_at = NOW()
                    ''', (str(transaction_date), str(transaction_desc), str(transaction_amount), filename, 'user_manually_removed'))
                else:
                    cursor = db_execute(conn, db_type, '''
                        INSERT OR REPLACE INTO rejected_receipts
                        (transaction_date, transaction_description, transaction_amount, receipt_path, reason)
                        VALUES (?, ?, ?, ?, ?)
                    ''', (str(transaction_date), str(transaction_desc), str(transaction_amount), filename, 'user_manually_removed'))

                conn.commit()
                conn.close()

                print(f"✅ PERMANENTLY REJECTED: {filename} from {transaction_desc}")

            except Exception as db_error:
                print(f"⚠️ Could not save rejection to database: {db_error}")

    # Clear receipt file columns
    for col in ("Receipt File", "receipt_file"):
        if col in df.columns:
            df.loc[mask, col] = ""

    # CRITICAL: Set Review Status to empty (Missing Receipt)
    # This moves the transaction OUT of Needs Review/Good/Bad
    # and INTO Missing Receipt immediately
    if "Review Status" in df.columns:
        df.loc[mask, "Review Status"] = ""
        print(f"📋 Status changed to 'Missing Receipt' for index {idx}", flush=True)

    # Also clear AI-related fields since receipt was removed
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
      "receipt_file": "Optional filename from OCR"
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

    # Get receipt file if provided
    receipt_file = data.get("receipt_file", "")

    # Create new expense row
    new_expense = {
        "_index": new_index,
        "Chase Date": data["date"],
        "Chase Description": data["merchant"],
        "Chase Amount": float(data["amount"]),
        "Chase Category": "",
        "Chase Type": "Purchase",
        "Receipt File": receipt_file,
        "Business Type": data["business_type"],
        "Notes": data.get("notes", ""),
        "AI Note": "",
        "AI Confidence": 0,
        "ai_receipt_merchant": data["merchant"] if receipt_file else "",
        "ai_receipt_date": data["date"] if receipt_file else "",
        "ai_receipt_total": str(data["amount"]) if receipt_file else "",
        "Review Status": "good" if receipt_file else "",
        "Category": data.get("category", ""),
        "Report ID": "",
        "Source": "Manual Entry"
    }

    # Database mode (MySQL or SQLite)
    if USE_SQLITE and db:
        try:
            # Build INSERT statement - handle both MySQL and SQLite
            columns = [
                "_index", "chase_date", "chase_description", "chase_amount",
                "chase_category", "chase_type", "receipt_file", "business_type",
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
                receipt_file,  # Now using the receipt_file from OCR
                data["business_type"],
                data.get("notes", ""),
                "",
                0,
                data["merchant"] if receipt_file else "",  # ai_receipt_merchant
                data["date"] if receipt_file else "",  # ai_receipt_date
                str(data["amount"]) if receipt_file else "",  # ai_receipt_total
                "good" if receipt_file else "",  # review_status
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
                conn.close()
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
    """Get expenses for a specific report"""
    if not USE_DATABASE or not db:
        abort(503, "Reports require database mode")

    try:
        expenses = db.get_report_expenses(report_id)

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
            "report_id": report_id,
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

        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            receipt_count = 0

            for exp in expenses:
                receipt_file = exp.get("receipt_file")
                if receipt_file:
                    receipt_path = Path(RECEIPTS_DIR) / receipt_file
                    if receipt_path.exists():
                        # Add to ZIP with a cleaned filename
                        merchant = exp.get("chase_description", "expense")
                        date = exp.get("chase_date", "")
                        amount = exp.get("chase_amount", 0)

                        # Create descriptive filename
                        ext = receipt_path.suffix
                        clean_filename = f"{date}_{merchant}_{amount}{ext}".replace(" ", "_").replace("/", "-")[:100]

                        # Add file to ZIP
                        zip_file.write(receipt_path, clean_filename)
                        receipt_count += 1

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
    receipt_path = Path(RECEIPTS_DIR) / filename

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
# GMAIL SETTINGS ENDPOINTS
# =============================================================================

@app.route("/settings/gmail/status", methods=["GET"])
def gmail_status():
    """Get status of all Gmail accounts"""
    import sys
    sys.path.insert(0, '../Task')

    from pathlib import Path
    import json
    from datetime import datetime

    TOKEN_DIR = Path('../Task/receipt-system/gmail_tokens')
    ACCOUNTS = [
        {'email': 'brian@downhome.com', 'token_file': 'tokens_brian_downhome_com.json'},
        {'email': 'kaplan.brian@gmail.com', 'token_file': 'tokens_kaplan_brian_gmail_com.json'},
        {'email': 'brian@musiccityrodeo.com', 'token_file': 'tokens_brian_musiccityrodeo_com.json'},
    ]

    statuses = []
    for account in ACCOUNTS:
        token_path = TOKEN_DIR / account['token_file']

        status = {
            'email': account['email'],
            'token_file': account['token_file'],
            'exists': token_path.exists(),
            'has_refresh_token': False,
            'expired': None,
            'expiry': None
        }

        if token_path.exists():
            try:
                with open(token_path, 'r') as f:
                    token_data = json.load(f)

                status['has_refresh_token'] = 'refresh_token' in token_data and token_data['refresh_token']

                if 'expiry' in token_data:
                    expiry = datetime.fromisoformat(token_data['expiry'].replace('Z', '+00:00'))
                    status['expiry'] = token_data['expiry']
                    status['expired'] = expiry < datetime.now(expiry.tzinfo)
            except Exception as e:
                status['error'] = str(e)

        statuses.append(status)

    return jsonify(safe_json({
        'ok': True,
        'accounts': statuses
    }))


@app.route("/settings/gmail/refresh/<account_email>", methods=["POST"])
def gmail_refresh_account(account_email):
    """Trigger OAuth re-authorization for a specific Gmail account"""
    import sys
    sys.path.insert(0, '../Task')
    import subprocess
    from pathlib import Path

    # Map email to account info
    ACCOUNTS = {
        'brian@downhome.com': {'email': 'brian@downhome.com', 'token_file': 'tokens_brian_downhome_com.json', 'port': 8080},
        'kaplan.brian@gmail.com': {'email': 'kaplan.brian@gmail.com', 'token_file': 'tokens_kaplan_brian_gmail_com.json', 'port': 8081},
        'brian@musiccityrodeo.com': {'email': 'brian@musiccityrodeo.com', 'token_file': 'tokens_brian_musiccityrodeo_com.json', 'port': 8082},
    }

    if account_email not in ACCOUNTS:
        abort(404, f"Account {account_email} not found")

    account = ACCOUNTS[account_email]

    # Create a single-account reauth script
    reauth_script = Path('../Task/reauth_single_account.py')

    script_content = f"""#!/usr/bin/env python3
import os
import sys
from pathlib import Path
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
TOKEN_DIR = Path('receipt-system/gmail_tokens')
CREDENTIALS_FILE = Path('receipt-system/config/credentials.json')

def reauth_account():
    print(f"🔐 Re-authorizing: {account['email']}")
    print("-" * 60)

    token_path = TOKEN_DIR / '{account['token_file']}'

    # Remove old token
    if token_path.exists():
        print(f"  Removing expired token...")
        token_path.unlink()

    # Start OAuth flow
    print(f"  Opening browser for authorization...")
    print(f"  Using port: {account['port']}")
    print(f"  ⚠️  IMPORTANT: Please log in as: {account['email']}")
    print()

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(CREDENTIALS_FILE),
            SCOPES,
            redirect_uri=f'http://localhost:{account['port']}/'
        )

        # CRITICAL FIX: Request offline access to get refresh tokens
        creds = flow.run_local_server(
            port={account['port']},
            open_browser=True,
            access_type='offline',
            prompt='consent'
        )

        # Save new token
        token_path.parent.mkdir(parents=True, exist_ok=True)
        with open(token_path, 'w') as f:
            f.write(creds.to_json())

        # Test the connection
        service = build('gmail', 'v1', credentials=creds)
        profile = service.users().getProfile(userId='me').execute()

        print(f"  ✅ SUCCESS: {{profile['emailAddress']}}")
        print(f"  Token saved to: {{token_path}}")
        return True

    except Exception as e:
        print(f"  ❌ FAILED: {{e}}")
        return False

if __name__ == '__main__':
    reauth_account()
"""

    # Write the script
    with open(reauth_script, 'w') as f:
        f.write(script_content)

    reauth_script.chmod(0o755)

    # Run the script in the background
    try:
        # Start the OAuth flow
        result = subprocess.Popen(
            [sys.executable, str(reauth_script)],
            cwd='../Task',
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE
        )

        return jsonify(safe_json({
            'ok': True,
            'message': f'OAuth flow started for {account_email}. Please check your browser to authorize.',
            'account': account_email
        }))

    except Exception as e:
        return jsonify(safe_json({
            'ok': False,
            'error': str(e)
        })), 500


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
                if USE_SQLITE and db:
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

            if USE_SQLITE and db:
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

                if USE_SQLITE and db:
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

        return jsonify({
            "success": True,
            "merchant": merchant,
            "date": date,
            "total": total,
            "confidence": (confidence / 100.0),  # Convert to 0-1 scale
            "engines_used": ["Gemini Vision"],
            "filename": final_filename
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
            if USE_SQLITE and db:
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
        if USE_SQLITE and db:
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
    conn.close()

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
    conn.close()

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
    conn.close()

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
                    conn.close()

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
            conn.close()

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
        conn.close()

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
        conn.close()

        return jsonify({
            'ok': True,
            'message': f'Rejection {rejection_id} removed - receipt can now be matched again'
        })

    except Exception as e:
        print(f"❌ Error deleting rejection: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


# =============================================================================
# INCOMING RECEIPTS SYSTEM
# =============================================================================

@app.route("/api/incoming/receipts", methods=["GET"])
@login_required
def get_incoming_receipts():
    """
    Get all incoming receipts from Gmail

    Query params:
    - status: 'pending', 'accepted', 'rejected', or 'all' (default: 'all')
    - limit: max number of results (default: 100)
    """
    try:
        if not USE_DATABASE or not db:
            return jsonify({
                'ok': False,
                'error': 'Database not available'
            }), 500

        status = request.args.get('status', 'all')
        limit = int(request.args.get('limit', 100))

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

        conn.close()

        # Apply merchant intelligence to normalize merchant names
        try:
            from merchant_intelligence import normalize_merchant
            import re
            for receipt in receipts:
                subject = receipt.get('subject', '')
                original_merchant = receipt.get('merchant', '')

                # Extract the real merchant from subject "Your receipt/refund from X #1234"
                match = re.search(r'(?:receipt|refund|payment)\s+from\s+([^#\n]+?)(?:\s*#|$)', subject, re.IGNORECASE)
                if match:
                    real_merchant = match.group(1).strip()
                    # Clean up common patterns like "Inc", "Inc.", "LLC"
                    real_merchant = re.sub(r',?\s*(Inc\.?|LLC|Ltd\.?|PBC)$', '', real_merchant, flags=re.IGNORECASE).strip()
                    receipt['merchant'] = normalize_merchant(real_merchant)
                    receipt['original_merchant'] = original_merchant
                elif original_merchant:
                    receipt['merchant'] = normalize_merchant(original_merchant)
                    receipt['original_merchant'] = original_merchant

                # Determine if this is a refund (positive amount) or charge (negative amount)
                subject_lower = subject.lower()
                receipt['is_refund'] = 'refund' in subject_lower

        except ImportError:
            print("⚠️  merchant_intelligence not available for normalization")

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


@app.route("/api/incoming/accept", methods=["POST"])
@login_required
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
        merchant = data.get('merchant')
        amount = float(data.get('amount', 0))
        trans_date = data.get('date')
        business_type = data.get('business_type', 'Personal')

        if not all([receipt_id, merchant, amount, trans_date]):
            return jsonify({
                'ok': False,
                'error': 'Missing required fields'
            }), 400

        conn, db_type = get_db_connection()

        # Get the receipt data
        cursor = db_execute(conn, db_type, 'SELECT * FROM incoming_receipts WHERE id = ?', (receipt_id,))
        receipt_row = cursor.fetchone()

        if not receipt_row:
            conn.close()
            return jsonify({
                'ok': False,
                'error': 'Receipt not found'
            }), 404

        # Convert to dict for safe access (handles missing columns)
        receipt = dict(receipt_row)

        # Helper for safe column access
        def get_col(name, default=None):
            return receipt.get(name) if receipt.get(name) else default

        subject_preview = get_col('subject', 'No subject')[:50]
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
                full_path = RECEIPTS_DIR / existing_file
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
                        receipt_files = process_receipt_files(service, email_id, attachments, html_body)
                        print(f"   ✓ Downloaded {len(receipt_files)} file(s)")
                    except Exception as e:
                        print(f"   ⚠️  Warning: Could not download receipt files: {e}")
            else:
                # No Gmail info - check if there's an existing receipt_file path
                existing_file = get_col('receipt_file')
                if existing_file:
                    full_path = RECEIPTS_DIR / existing_file
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

        if match_type == 'needs_receipt' and matched_transaction_id:
            # Attach to existing transaction
            print(f"   📎 Attaching to existing transaction #{matched_transaction_id}")

            # Update existing transaction with receipt files
            # Keep incoming/ prefix for files in that subfolder
            receipt_file_str = ', '.join([f.replace('receipts/', '') for f in receipt_files]) if receipt_files else ''
            # Use CONCAT for MySQL, || for SQLite
            if db_type == 'mysql':
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET receipt_file = ?,
                        notes = CONCAT(COALESCE(notes, ''), ?)
                    WHERE _index = ?
                ''', (receipt_file_str, f'\n[From incoming receipt: {notes_text}]', matched_transaction_id))
            else:
                cursor = db_execute(conn, db_type, '''
                    UPDATE transactions
                    SET receipt_file = ?,
                        notes = COALESCE(notes, '') || ?
                    WHERE _index = ?
                ''', (receipt_file_str, f'\n[From incoming receipt: {notes_text}]', matched_transaction_id))

            transaction_id = matched_transaction_id
            action = 'attached'
        else:
            # Create new transaction
            print(f"   ➕ Creating new transaction")

            # Keep incoming/ prefix for files in that subfolder
            receipt_file_str = ', '.join([f.replace('receipts/', '') for f in receipt_files]) if receipt_files else ''

            # Get next _index value
            cursor = db_execute(conn, db_type, 'SELECT COALESCE(MAX(_index), 0) + 1 FROM transactions')
            row = cursor.fetchone()
            # Handle dict (MySQL DictCursor) vs tuple (SQLite)
            next_index = list(row.values())[0] if isinstance(row, dict) else row[0]

            cursor = db_execute(conn, db_type, '''
                INSERT INTO transactions (
                    _index, chase_description, chase_amount, chase_date,
                    business_type, review_status, notes,
                    receipt_file, source
                ) VALUES (?, ?, ?, ?, ?, 'accepted', ?, ?, 'incoming_receipt')
            ''', (next_index, merchant, amount, trans_date, business_type, notes_text, receipt_file_str))

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

        conn.close()

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
                print(f"   📊 Updated transaction #{matched_transaction_id} in DataFrame with receipt")

        print(f"✅ Accepted receipt {receipt_id} → transaction {transaction_id} ({action})")

        return jsonify({
            'ok': True,
            'message': f'Receipt accepted and transaction {action}',
            'transaction_id': transaction_id,
            'receipt_id': receipt_id,
            'action': action,
            'receipt_files': receipt_files
        })

    except Exception as e:
        import traceback
        print(f"❌ Error accepting receipt: {e}")
        traceback.print_exc()
        return jsonify({'ok': False, 'error': str(e)}), 500


@app.route("/api/incoming/reject", methods=["POST"])
@login_required
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
            conn.close()
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

        conn.close()

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


@app.route("/api/incoming/scan", methods=["POST"])
@login_required
def scan_incoming_receipts():
    """
    Trigger a manual scan of Gmail accounts for new receipts

    Body (optional):
    {
        "accounts": ["kaplan.brian@gmail.com"],  // specific accounts, or leave empty for all
        "since_date": "2024-09-01"  // optional date filter
    }
    """
    import sqlite3
    from datetime import datetime

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

        return jsonify({
            'ok': True,
            'message': f"Found {results['total_new']} new receipts",
            'results': results
        })

    except Exception as e:
        print(f"❌ Error during scan: {e}")
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
            conn.close()

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
            conn.close()

            return jsonify({
                'ok': True,
                'message': f'Updated {updated} receipt URLs',
                'updated': updated
            })

    except Exception as e:
        print(f"❌ Error syncing receipt URLs: {e}")
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
        conn.close()

        # Verify receipt URLs
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions WHERE receipt_url IS NOT NULL AND receipt_url != ''")
        url_count = cursor.fetchone()
        url_count = url_count['cnt'] if isinstance(url_count, dict) else url_count[0]
        cursor.close()
        conn.close()

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
        if USE_SQLITE and db:
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
        if USE_SQLITE and db:
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

    # Validate database before starting
    if USE_SQLITE and Path("receipts.db").exists():
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

    print(f"🚀 Starting Flask on port {args.port}...")
    # debug=True to keep hot-reloading while you iterate
    app.run(host="0.0.0.0", port=args.port, debug=True)
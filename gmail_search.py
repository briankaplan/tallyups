#!/usr/bin/env python3
"""
gmail_search.py

Gmail escalation layer for ReceiptAI.

- Uses your 3 Gmail accounts (via existing token_*.pickle files)
- Searches for possible receipts for a given Chase transaction row
- Downloads PDF/image attachments to receipts/
- Runs GPT-4.1 vision on each attachment to extract:
    merchant_name, normalized merchant, date, subtotal, tip, total
- Scores candidates against Chase (amount + merchant + date)
- Returns all candidates AND a convenience helper to get best one
- Shares the same metadata CSV as viewer_server.py so vision is cached:
    receipt_ai_metadata.csv
"""

from __future__ import annotations

import os
import io
import math
import json
import base64
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime, date, timedelta

import pandas as pd

from openai import OpenAI

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.oauth2.credentials import Credentials

# Import local OCR system (Donut primary with ensemble fallback)
try:
    from receipt_ocr_local import extract_receipt_fields_local
    LOCAL_OCR_AVAILABLE = True
except Exception:
    LOCAL_OCR_AVAILABLE = False

# Import merchant intelligence for perfect normalization
try:
    from merchant_intelligence import get_merchant_intelligence
    merchant_intel = get_merchant_intelligence()
except Exception:
    merchant_intel = None

# Import intelligence layer
from gmail_intelligence import (
    get_intelligence,
    build_smart_query,
    should_process_attachment,
)

# Import email screenshot service (Playwright - for local dev)
try:
    from scripts.misc.email_screenshot import create_email_receipt_screenshot
    SCREENSHOT_AVAILABLE = True
except ImportError:
    try:
        from email_screenshot import create_email_receipt_screenshot
        SCREENSHOT_AVAILABLE = True
    except ImportError:
        SCREENSHOT_AVAILABLE = False
        create_email_receipt_screenshot = None

# Import Gemini HTML extraction (Railway fallback - no browser needed)
try:
    from gemini_utils import extract_receipt_from_html_email
    GEMINI_HTML_AVAILABLE = True
except ImportError:
    GEMINI_HTML_AVAILABLE = False
    extract_receipt_from_html_email = None


# =============================================================================
# PATHS / GLOBALS
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent
RECEIPT_DIR = BASE_DIR / "receipts"
RECEIPT_META_PATH = BASE_DIR / "receipt_ai_metadata.csv"

RECEIPT_DIR.mkdir(exist_ok=True)

# Gmail token files (JSON format from ../Task/receipt-system)
GMAIL_TOKEN_DIR = BASE_DIR.parent / "Task" / "receipt-system" / "gmail_tokens"
GMAIL_ACCOUNTS = [
    {
        "name": "brian_personal",
        "token": GMAIL_TOKEN_DIR / "tokens_kaplan_brian_gmail_com.json",
    },
    {
        "name": "brian_mcr",
        "token": GMAIL_TOKEN_DIR / "tokens_brian_musiccityrodeo_com.json",
    },
    {
        "name": "brian_downhome",
        "token": GMAIL_TOKEN_DIR / "tokens_brian_downhome_com.json",
    },
]

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set in environment")
client = OpenAI(api_key=OPENAI_API_KEY)


# =============================================================================
# NORMALIZATION / UTIL
# =============================================================================

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


def parse_date_fuzzy(s: Optional[str]) -> Optional[date]:
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


def norm_text_for_match(s: Optional[str]) -> str:
    if not s:
        return ""
    s = s.lower()
    kept = []
    for ch in s:
        if ch.isalnum():
            kept.append(ch)
        elif ch.isspace():
            kept.append(" ")
    return " ".join("".join(kept).split())


def normalize_merchant_name(s: Optional[str]) -> str:
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

    return norm_text_for_match(low)


def date_window_for_chase(chase_date: Optional[date]) -> Tuple[Optional[date], Optional[date]]:
    """
    Build a search window around a Chase date:
      - Start: 5 days before
      - End:   5 days after
    """
    if not chase_date:
        return None, None
    return chase_date - timedelta(days=5), chase_date + timedelta(days=5)


# =============================================================================
# RECEIPT META CACHE (SHARED WITH VIEWER)
# =============================================================================

_receipt_meta_cache: Dict[str, Dict[str, Any]] = {}
_receipt_meta_loaded = False


def load_receipt_meta() -> None:
    global _receipt_meta_cache, _receipt_meta_loaded
    if _receipt_meta_loaded:
        return
    _receipt_meta_cache = {}
    if not RECEIPT_META_PATH.exists():
        _receipt_meta_loaded = True
        return
    try:
        df = pd.read_csv(RECEIPT_META_PATH, dtype=str, keep_default_na=False)
        for _, row in df.iterrows():
            filename = row["filename"]
            _receipt_meta_cache[filename] = {
                "filename": filename,
                "merchant_name": row.get("merchant_name", ""),
                "merchant_normalized": row.get("merchant_normalized", ""),
                "receipt_date": row.get("receipt_date", ""),
                "total_amount": parse_amount_str(row.get("total_amount", "")),
                "subtotal_amount": parse_amount_str(row.get("subtotal_amount", "")),
                "tip_amount": parse_amount_str(row.get("tip_amount", "")),
                "raw_json": row.get("raw_json", ""),
            }
    except Exception as e:
        print(f"⚠️ Could not load receipt metadata: {e}")
    _receipt_meta_loaded = True


def save_receipt_meta() -> None:
    global _receipt_meta_cache
    if not _receipt_meta_cache:
        return
    rows = []
    for meta in _receipt_meta_cache.values():
        rows.append({
            "filename": meta.get("filename", ""),
            "merchant_name": meta.get("merchant_name", ""),
            "merchant_normalized": meta.get("merchant_normalized", ""),
            "receipt_date": meta.get("receipt_date", ""),
            "total_amount": meta.get("total_amount", 0.0),
            "subtotal_amount": meta.get("subtotal_amount", 0.0),
            "tip_amount": meta.get("tip_amount", 0.0),
            "raw_json": meta.get("raw_json", ""),
        })
    df = pd.DataFrame(rows)
    df.to_csv(RECEIPT_META_PATH, index=False)
    print(f"📑 Saved receipt metadata for {len(rows)} files (gmail_search)")


def get_cached_meta(filename: str) -> Optional[Dict[str, Any]]:
    load_receipt_meta()
    return _receipt_meta_cache.get(filename)


def set_cached_meta(meta: Dict[str, Any]) -> None:
    load_receipt_meta()
    fname = meta.get("filename")
    if not fname:
        return
    _receipt_meta_cache[fname] = meta
    save_receipt_meta()


# =============================================================================
# OPENAI VISION (BYTES → JSON)
# =============================================================================

def extract_receipt_with_vision_from_bytes(content: bytes, filename_hint: str = "") -> Optional[Dict[str, Any]]:
    """
    Use Local OCR (Llama 3.2 Vision) first, fallback to GPT-4.1 vision on bytes (PDF or image) to extract receipt fields.
    """
    if not content:
        return None

    print(f"👁️  Vision extracting (gmail) {filename_hint}", flush=True)

    # Try Donut OCR first (FREE, FAST, 97-98% accuracy)
    if LOCAL_OCR_AVAILABLE:
        try:
            print(f"   🔄 Using Donut OCR for Gmail receipt...", flush=True)

            # Save bytes to temp file for Donut OCR
            import tempfile
            # Determine extension from filename
            lower = filename_hint.lower()
            if lower.endswith(".pdf"):
                suffix = ".pdf"
            elif lower.endswith(".png"):
                suffix = ".png"
            elif lower.endswith(".webp"):
                suffix = ".webp"
            else:
                suffix = ".jpg"

            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                temp_path = tmp.name
                tmp.write(content)

            # Process with Donut OCR
            from pathlib import Path
            local_result = extract_receipt_fields_local(temp_path)

            # Clean up temp file
            Path(temp_path).unlink(missing_ok=True)

            if local_result and local_result.get("success"):
                # Map Donut results to expected format (includes subtotal/tip)
                merchant_name = local_result.get("Receipt Merchant", "").strip()
                merchant_norm = normalize_merchant_name(merchant_name)
                receipt_date = local_result.get("Receipt Date", "")
                total = local_result.get("Receipt Total", 0.0)
                subtotal = local_result.get("subtotal_amount", 0.0)
                tip = local_result.get("tip_amount", 0.0)
                ocr_method = local_result.get("ocr_method", "Donut")
                confidence = local_result.get("confidence_score", 0.0)

                meta = {
                    "filename": filename_hint,
                    "merchant_name": merchant_name,
                    "merchant_normalized": merchant_norm,
                    "receipt_date": receipt_date,
                    "subtotal_amount": subtotal,
                    "tip_amount": tip,
                    "total_amount": total,
                    "raw_json": json.dumps(local_result, ensure_ascii=False),
                    "ocr_source": f"gmail_{ocr_method.lower()}",
                    "confidence_score": confidence
                }

                print(f"   ✅ {ocr_method} success (gmail): {merchant_name} · ${total:.2f} · {receipt_date} (conf: {confidence:.0%})", flush=True)
                return meta
            else:
                print(f"   ⚠️ Donut OCR failed: {local_result.get('error', 'Unknown error')}", flush=True)
                print(f"   🔄 Falling back to GPT-4.1 Vision...", flush=True)
        except Exception as e:
            print(f"   ⚠️ Donut OCR exception: {e}", flush=True)
            print(f"   🔄 Falling back to GPT-4.1 Vision...", flush=True)

    # Fallback to GPT-4.1 Vision (API cost, but more reliable)
    # Rough content type guessing
    lower = filename_hint.lower()
    if lower.endswith(".pdf"):
        mime = "application/pdf"
    elif any(lower.endswith(ext) for ext in [".png", ".webp"]):
        mime = "image/png"
    else:
        mime = "image/jpeg"

    b64 = base64.b64encode(content).decode("utf-8")
    url = f"data:{mime};base64,{b64}"

    prompt = """
You are a world-class receipt parser.

Look at the attached receipt and extract:
- merchant_name: business or venue name
- merchant_normalized: normalized merchant name (cluster Soho House, Anthropic, etc.)
- receipt_date: transaction date in YYYY-MM-DD if possible; else empty string
- subtotal_amount: numeric subtotal before tip, if visible
- tip_amount: numeric tip amount, including handwritten tips, if visible
- total_amount: FINAL charged total including tip (printed or computed)

Normalization:
- Any variation of "Anthropic", "Claude", "Anthropic AI" → merchant_normalized = "Anthropic / Claude"
- Any variation of "SH Nashville", "Soho House", "SHN" → merchant_normalized = "Soho House Nashville"

Respond ONLY with JSON:
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
                    "content": "You convert receipts to structured JSON.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": url,
                                "detail": "high",
                            },
                        },
                    ],
                },
            ],
        )
        content_json = resp.choices[0].message.content
        data = json.loads(content_json)

        merchant_name = (data.get("merchant_name") or "").strip()
        merchant_norm = (data.get("merchant_normalized") or "").strip()
        if not merchant_norm:
            merchant_norm = normalize_merchant_name(merchant_name)

        receipt_date = (data.get("receipt_date") or "").strip()
        subtotal = parse_amount_str(data.get("subtotal_amount"))
        tip = parse_amount_str(data.get("tip_amount"))
        total = parse_amount_str(data.get("total_amount"))

        meta = {
            "filename": filename_hint,
            "merchant_name": merchant_name,
            "merchant_normalized": merchant_norm,
            "receipt_date": receipt_date,
            "subtotal_amount": subtotal,
            "tip_amount": tip,
            "total_amount": total,
            "raw_json": json.dumps(data, ensure_ascii=False),
            "ocr_source": "gpt41_vision"
        }

        print(f"   ✅ GPT-4.1 Vision success (gmail): {merchant_name} · ${total:.2f} · {receipt_date}", flush=True)
        return meta
    except Exception as e:
        print(f"⚠️ Vision error (gmail {filename_hint}): {e}", flush=True)
        return None


# =============================================================================
# GMAIL HELPERS
# =============================================================================

def load_gmail_service(token_path: Path):
    if not token_path.exists():
        print(f"⚠️ Gmail token not found: {token_path}")
        return None
    try:
        # Load JSON credentials (OAuth2 format)
        with token_path.open("r") as f:
            token_data = json.load(f)

        creds = Credentials(
            token=token_data["token"],
            refresh_token=token_data.get("refresh_token"),
            token_uri=token_data["token_uri"],
            client_id=token_data["client_id"],
            client_secret=token_data["client_secret"],
            scopes=token_data.get("scopes", [])
        )

        # Auto-refresh if token is expired
        if creds.expired and creds.refresh_token:
            try:
                from google.auth.transport.requests import Request
                creds.refresh(Request())
                print(f"   ✅ Refreshed Gmail token for {token_path.stem}")
                # Save the refreshed token
                updated_token_data = {
                    "token": creds.token,
                    "refresh_token": creds.refresh_token,
                    "token_uri": creds.token_uri,
                    "client_id": creds.client_id,
                    "client_secret": creds.client_secret,
                    "scopes": list(creds.scopes) if creds.scopes else token_data.get("scopes", []),
                    "expiry": creds.expiry.isoformat() if creds.expiry else None
                }
                with token_path.open("w") as f:
                    json.dump(updated_token_data, f, indent=2)
            except Exception as refresh_err:
                print(f"   ⚠️ Token refresh failed for {token_path.stem}: {refresh_err}")
                # Continue with expired token - might still work briefly

        service = build("gmail", "v1", credentials=creds)
        return service
    except Exception as e:
        print(f"⚠️ Could not load Gmail service for {token_path}: {e}")
        return None


def build_gmail_query_for_row(row: Dict[str, Any]) -> str:
    """
    INTELLIGENT Gmail search query using merchant variations and smart filtering.

    Uses gmail_intelligence.py to:
    - Build query with merchant variations (Cambria = Choice Hotels)
    - Use amount for text matching
    - Use date windows
    - Skip generic terms that find business docs
    """
    desc = (row.get("Chase Description") or row.get("merchant") or "").strip()
    amt = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
    date_raw = row.get("Chase Date") or row.get("transaction_date") or ""
    chase_date = parse_date_fuzzy(date_raw)

    # Date window (convert to YYYY/MM/DD format for Gmail)
    start, end = date_window_for_chase(chase_date)
    date_after = start.strftime('%Y/%m/%d') if start else ""
    date_before = (end + timedelta(days=1)).strftime('%Y/%m/%d') if end else ""

    # Use intelligent query builder
    q = build_smart_query(
        merchant=desc,
        amount=abs(amt) if amt else 0,
        date_after=date_after,
        date_before=date_before
    )

    print(f"🔍 Smart Gmail query: {q}")
    return q


@dataclass
class GmailReceiptCandidate:
    account: str
    message_id: str
    attachment_id: str
    gmail_subject: str
    gmail_sender: str  # For learning which senders send receipts
    filename: str
    saved_filename: str
    total_amount: float
    merchant_name: str
    merchant_normalized: str
    receipt_date: str
    score: float
    amount_score: float
    merchant_score: float
    date_score: float

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# =============================================================================
# SCORING LOGIC
# =============================================================================

def score_candidate(
    chase_amount: float,
    chase_merchant_norm: str,
    chase_date: Optional[date],
    meta: Dict[str, Any],
) -> Tuple[float, float, float, float]:
    """
    Return (final_score, amount_score, merchant_score, date_score)
    mirroring the viewer_server weighting:
      score = 0.6 * amount + 0.3 * merchant + 0.1 * date
    """
    r_total = meta.get("total_amount") or 0.0
    r_merchant_norm = meta.get("merchant_normalized") or ""
    r_date_raw = meta.get("receipt_date") or ""
    r_date = parse_date_fuzzy(r_date_raw)

    # amount score (compare absolute values to handle negative transactions)
    amount_score = 0.0
    if chase_amount != 0 and r_total != 0:
        diff = abs(abs(chase_amount) - abs(r_total))
        scale = max(1.0, 0.10 * abs(chase_amount))
        amount_score = max(0.0, 1.0 - (diff / scale))

    # merchant score
    merch_score = 0.0
    if chase_merchant_norm and r_merchant_norm:
        # Case-insensitive comparison
        chase_lower = chase_merchant_norm.lower()
        receipt_lower = r_merchant_norm.lower()

        # Check for substring match first (e.g., "uber" in "uber trip")
        if receipt_lower in chase_lower or chase_lower in receipt_lower:
            merch_score = 0.95  # High confidence for substring matches
        else:
            # Fallback to fuzzy matching for partial matches
            from difflib import SequenceMatcher
            merch_score = SequenceMatcher(None, chase_lower, receipt_lower).ratio()

    # date score
    date_score = 0.0
    if chase_date and r_date:
        delta_days = abs((chase_date - r_date).days)
        if delta_days == 0:
            date_score = 1.0
        elif delta_days <= 1:
            date_score = 0.8
        elif delta_days <= 3:
            date_score = 0.5
        elif delta_days <= 7:
            date_score = 0.2

    # 🚨 CRITICAL: Different merchant = ZERO SCORE
    # Don't calculate weighted average if merchants are too different
    MERCHANT_MINIMUM = 0.30  # Below 30% = completely different merchant (was 50% - too strict!)
    if merch_score < MERCHANT_MINIMUM:
        # Return zero score - no point matching different merchants
        return 0.0, float(amount_score), float(merch_score), float(date_score)

    final = 0.6 * amount_score + 0.3 * merch_score + 0.1 * date_score
    return float(final), float(amount_score), float(merch_score), float(date_score)


# =============================================================================
# MAIN PUBLIC API
# =============================================================================

def search_gmail_receipts_for_row(
    row: Dict[str, Any],
    max_results_per_account: int = 25,
) -> List[GmailReceiptCandidate]:
    """
    Search all configured Gmail accounts for receipt candidates for a Chase row.

    Does:
      - Gmail search using built query
      - Downloads attachments that look like receipts (pdf / image)
      - Runs GPT-4.1 vision for structured data (with caching)
      - Scores each candidate against the Chase transaction
      - Returns list of GmailReceiptCandidate sorted by score desc
    """
    desc = (row.get("Chase Description") or row.get("merchant") or "").strip()
    chase_amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
    date_raw = row.get("Chase Date") or row.get("transaction_date") or ""
    chase_date = parse_date_fuzzy(date_raw)
    chase_merchant_norm = normalize_merchant_name(desc)

    q = build_gmail_query_for_row(row)
    candidates: List[GmailReceiptCandidate] = []

    # INTELLIGENT ACCOUNT PRIORITIZATION - Search most likely accounts first
    intelligence = get_intelligence()
    priority_account_names = intelligence.get_priority_accounts(desc)

    # Reorder GMAIL_ACCOUNTS based on priority
    accounts_sorted = []
    for priority_name in priority_account_names:
        for acct in GMAIL_ACCOUNTS:
            if acct["name"] == priority_name:
                accounts_sorted.append(acct)
                break
    # Add any accounts not in priority list
    for acct in GMAIL_ACCOUNTS:
        if acct not in accounts_sorted:
            accounts_sorted.append(acct)

    for acct in accounts_sorted:
        name = acct["name"]
        token_path: Path = acct["token"]
        service = load_gmail_service(token_path)
        if not service:
            continue

        # Record that we're searching this account (for learning)
        intelligence.record_search(name)

        try:
            resp = service.users().messages().list(
                userId="me",
                q=q,
                maxResults=max_results_per_account,
            ).execute()
        except HttpError as e:
            print(f"⚠️ Gmail search error for {name}: {e}")
            continue

        msgs = resp.get("messages", []) or []
        print(f"📬 {name}: found {len(msgs)} messages")

        for m in msgs:
            msg_id = m["id"]
            try:
                msg = service.users().messages().get(
                    userId="me",
                    id=msg_id,
                    format="full",
                ).execute()
            except HttpError as e:
                print(f"⚠️ Gmail get error {name}/{msg_id}: {e}")
                continue

            headers = msg.get("payload", {}).get("headers", [])
            subject = ""
            sender = ""
            for h in headers:
                h_name = h.get("name", "").lower()
                if h_name == "subject":
                    subject = h.get("value", "")
                elif h_name == "from":
                    sender = h.get("value", "")

            # Traverse payloads for attachments
            def iter_parts(payload):
                if "parts" in payload:
                    for p in payload["parts"]:
                        yield from iter_parts(p)
                else:
                    yield payload

            # Track if any attachments were processed for this message
            attachments_processed = 0

            for part in iter_parts(msg.get("payload", {})):
                body = part.get("body", {})
                att_id = body.get("attachmentId")
                filename = part.get("filename") or ""
                mime_type = part.get("mimeType") or ""

                if not att_id:
                    continue

                # INTELLIGENT FILTERING - Skip PDFs, business docs, contracts BEFORE downloading
                should_process, reason = should_process_attachment(filename, mime_type)
                if not should_process:
                    # print(f"   ⏭️  Skipping {filename or 'unnamed'}: {reason}")
                    continue

                try:
                    att = service.users().messages().attachments().get(
                        userId="me",
                        messageId=msg_id,
                        id=att_id,
                    ).execute()
                    data_b64 = att.get("data")
                    if not data_b64:
                        continue
                    content = base64.urlsafe_b64decode(data_b64)
                except HttpError as e:
                    print(f"⚠️ Attachment error {name}/{msg_id}/{att_id}: {e}")
                    continue

                # Save file to receipts/ with stable filename
                safe_filename = filename or f"gmail_{msg_id}_{att_id}.bin"
                safe_filename = safe_filename.replace("/", "_")
                saved_filename = f"gmail_{name}_{msg_id}_{safe_filename}"
                saved_path = RECEIPT_DIR / saved_filename

                if not saved_path.exists():
                    with saved_path.open("wb") as f:
                        f.write(content)
                    print(f"📎 Saved Gmail attachment → {saved_path.name}")

                # Vision metadata (with shared caching)
                meta = get_cached_meta(saved_filename)
                if not meta:
                    meta = extract_receipt_with_vision_from_bytes(
                        content, filename_hint=saved_filename
                    )
                    if meta:
                        meta["filename"] = saved_filename
                        set_cached_meta(meta)
                if not meta:
                    continue  # no vision data, skip

                final_score, amount_score, merch_score, date_score = score_candidate(
                    chase_amount,
                    chase_merchant_norm,
                    chase_date,
                    meta,
                )

                cand = GmailReceiptCandidate(
                    account=name,
                    message_id=msg_id,
                    attachment_id=att_id,
                    gmail_subject=subject,
                    gmail_sender=sender,
                    filename=filename or saved_filename,
                    saved_filename=saved_filename,
                    total_amount=meta.get("total_amount") or 0.0,
                    merchant_name=meta.get("merchant_name") or "",
                    merchant_normalized=meta.get("merchant_normalized") or "",
                    receipt_date=meta.get("receipt_date") or "",
                    score=final_score,
                    amount_score=amount_score,
                    merchant_score=merch_score,
                    date_score=date_score,
                )
                candidates.append(cand)
                attachments_processed += 1

            # HTML EMAIL PROCESSING - If no attachments found, try HTML body extraction
            if attachments_processed == 0 and (SCREENSHOT_AVAILABLE or GEMINI_HTML_AVAILABLE):
                # Extract HTML body from message
                html_body = None
                for part in iter_parts(msg.get("payload", {})):
                    mime_type = part.get("mimeType", "")
                    if mime_type == "text/html":
                        body_data = part.get("body", {}).get("data")
                        if body_data:
                            try:
                                html_body = base64.urlsafe_b64decode(body_data).decode("utf-8", errors="ignore")
                                break
                            except Exception:
                                continue

                if html_body:
                    # Check if HTML contains monetary amounts (e.g., $1,234.56)
                    import re
                    money_pattern = r'\$\s*\d{1,3}(?:,\d{3})*(?:\.\d{2})?'
                    if re.search(money_pattern, html_body):
                        meta = None
                        saved_filename = None

                        # METHOD 1: Playwright screenshot (local dev - better quality)
                        if SCREENSHOT_AVAILABLE and create_email_receipt_screenshot:
                            print(f"📧 Email body has receipt data, creating screenshot...")

                            # Screenshot the HTML
                            screenshot_path = create_email_receipt_screenshot(
                                html_body,
                                subject,
                                msg_id,
                                RECEIPT_DIR
                            )

                            if screenshot_path and screenshot_path.exists():
                                # Read screenshot as bytes
                                with screenshot_path.open("rb") as f:
                                    screenshot_bytes = f.read()

                                # Process with vision AI
                                saved_filename = screenshot_path.name
                                meta = get_cached_meta(saved_filename)
                                if not meta:
                                    meta = extract_receipt_with_vision_from_bytes(
                                        screenshot_bytes,
                                        filename_hint=saved_filename
                                    )
                                    if meta:
                                        meta["filename"] = saved_filename
                                        set_cached_meta(meta)

                        # METHOD 2: Gemini HTML extraction (Railway - no browser)
                        if not meta and GEMINI_HTML_AVAILABLE and extract_receipt_from_html_email:
                            print(f"📧 Extracting receipt from HTML email via Gemini...")
                            meta = extract_receipt_from_html_email(html_body, subject, sender)

                            if meta:
                                # Create a placeholder filename for the metadata
                                import hashlib
                                msg_hash = hashlib.md5(msg_id.encode()).hexdigest()[:8]
                                safe_subject = re.sub(r'[^\w\s-]', '', subject)[:30]
                                safe_subject = re.sub(r'[-\s]+', '_', safe_subject)
                                saved_filename = f"html_email_{safe_subject}_{msg_hash}.html"
                                meta["filename"] = saved_filename
                                set_cached_meta(meta)
                                print(f"   ✅ Gemini HTML extraction: {meta.get('merchant_name')} · ${meta.get('total_amount', 0):.2f}")

                        if meta and saved_filename:
                            # RENAME FILE: Merchant_date_amount.png (only for screenshots)
                            if saved_filename.endswith('.png') and SCREENSHOT_AVAILABLE:
                                merchant = meta.get("merchant_normalized") or meta.get("merchant_name") or "Unknown"
                                date_str = meta.get("receipt_date") or "NoDate"
                                amount = meta.get("total_amount") or 0.0

                                # Clean merchant name for filename
                                merchant_clean = re.sub(r'[^\w\s-]', '', merchant)[:30]
                                merchant_clean = re.sub(r'[-\s]+', '_', merchant_clean)

                                # Format amount
                                amount_str = f"{abs(amount):.2f}".replace(".", "_")

                                # Create new filename
                                new_filename = f"{merchant_clean}_{date_str}_{amount_str}.png"
                                new_path = RECEIPT_DIR / new_filename
                                old_path = RECEIPT_DIR / saved_filename

                                # Rename file if it doesn't already have the correct name
                                if old_path.exists() and saved_filename != new_filename and not new_path.exists():
                                    try:
                                        old_path.rename(new_path)
                                        print(f"📝 Renamed: {saved_filename} → {new_filename}")

                                        # Update metadata cache with new filename
                                        meta["filename"] = new_filename
                                        set_cached_meta(meta)

                                        # Update saved_filename to use new name
                                        saved_filename = new_filename
                                    except Exception as e:
                                        print(f"⚠️ Could not rename {saved_filename}: {e}")
                                elif new_path.exists():
                                    saved_filename = new_filename

                            # Score and add as candidate
                            final_score, amount_score, merch_score, date_score = score_candidate(
                                chase_amount,
                                chase_merchant_norm,
                                chase_date,
                                meta,
                            )

                            cand = GmailReceiptCandidate(
                                account=name,
                                message_id=msg_id,
                                attachment_id="",  # No attachment, HTML body extraction
                                gmail_subject=subject,
                                gmail_sender=sender,
                                filename=saved_filename,
                                saved_filename=saved_filename,
                                total_amount=meta.get("total_amount") or 0.0,
                                merchant_name=meta.get("merchant_name") or "",
                                merchant_normalized=meta.get("merchant_normalized") or "",
                                receipt_date=meta.get("receipt_date") or "",
                                score=final_score,
                                amount_score=amount_score,
                                merchant_score=merch_score,
                                date_score=date_score,
                            )
                            candidates.append(cand)
                            print(f"✅ HTML email processed: score={final_score:.2f}")

    candidates.sort(key=lambda c: c.score, reverse=True)
    print(f"✅ Gmail candidates total: {len(candidates)}")
    if candidates[:5]:
        print("   Top candidates:")
        for c in candidates[:5]:
            print(
                f"   • {c.account} :: {c.saved_filename} "
                f"score={c.score:.3f} "
                f"amt={c.amount_score:.2f} merch={c.merchant_score:.2f} date={c.date_score:.2f} "
                f"merchant={c.merchant_name!r} total={c.total_amount:.2f} "
                f"date={c.receipt_date}"
            )
    return candidates


def find_best_gmail_receipt_for_row(
    row: Dict[str, Any],
    threshold: float = 0.70,
    max_results_per_account: int = 25,
) -> Optional[GmailReceiptCandidate]:
    """
    Convenience helper:
      - runs search_gmail_receipts_for_row
      - returns the best candidate above threshold, or None
      - LEARNS from successful matches for future prioritization
    """
    desc = (row.get("Chase Description") or row.get("merchant") or "").strip()

    cands = search_gmail_receipts_for_row(row, max_results_per_account=max_results_per_account)
    if not cands:
        return None
    best = cands[0]
    if best.score >= threshold:
        print(f"🏆 Best Gmail receipt: {best.saved_filename} (score {best.score:.3f})")

        # LEARN FROM SUCCESS - Record merchant→account mapping and sender pattern
        intelligence = get_intelligence()
        intelligence.learn_success(
            merchant=desc,
            account=best.account,
            sender=best.gmail_sender
        )

        return best
    print(f"ℹ️ Best Gmail candidate below threshold: {best.score:.3f} < {threshold}")
    return None


# =============================================================================
# CLI TEST HARNESS
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Test Gmail receipt search for a single Chase row."
    )
    parser.add_argument("--date", help="Chase Date (YYYY-MM-DD or similar)")
    parser.add_argument("--desc", help="Chase Description", required=True)
    parser.add_argument("--amount", help="Chase Amount, e.g. 58.16", required=True)
    parser.add_argument("--category", help="Chase Category", default="")
    parser.add_argument("--biz", help="Business Type", default="Unassigned")
    args = parser.parse_args()

    row = {
        "Chase Date": args.date or "",
        "Chase Description": args.desc,
        "Chase Amount": args.amount,
        "Chase Category": args.category,
        "Business Type": args.biz,
    }

    best = find_best_gmail_receipt_for_row(row)
    if best:
        print("\n=== BEST MATCH ===")
        print(json.dumps(best.to_dict(), indent=2, ensure_ascii=False))
    else:
        print("\nNo Gmail receipt found above threshold.")
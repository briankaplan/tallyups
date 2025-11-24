"""
AI Receipt Locator — Brian Kaplan
---------------------------------

This module does the heavy lifting for:
 - Vision extraction (Local OCR with Llama 3.2 Vision + GPT-4.1 fallback)
 - Matching receipts to Chase rows
 - Using master_receipts.csv as supplemental intelligence
 - Smart merchant normalization (Soho House, Anthropic, etc.)
 - Preparing for future Gmail escalation

It is imported by viewer_server.py.

"""

import os
import json
import base64
import math
import shutil
from pathlib import Path
from difflib import SequenceMatcher
from datetime import datetime, date
import pandas as pd
from openai import OpenAI

# Import local OCR system (Donut primary with ensemble fallback)
try:
    from receipt_ocr_local import extract_receipt_fields_local, validate_extraction
    LOCAL_OCR_AVAILABLE = True
    print("✅ Local OCR (Donut 97-98% accuracy) enabled with validation")
except Exception as e:
    LOCAL_OCR_AVAILABLE = False
    validate_extraction = None
    print(f"⚠️ Local OCR not available: {e}")

# Import merchant intelligence for perfect normalization
try:
    from merchant_intelligence import get_merchant_intelligence
    merchant_intel = get_merchant_intelligence()
    print("✅ Merchant intelligence loaded for AI locator")
except Exception as e:
    print(f"⚠️ Merchant intelligence not available: {e}")
    merchant_intel = None

# =============================================================================
# CONFIG
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent
RECEIPT_DIR = BASE_DIR / "receipts"
RECEIPT_META_PATH = BASE_DIR / "receipt_ai_metadata.csv"
MASTER_RECEIPTS_PATH = BASE_DIR / "master_receipts.csv"

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)

# Cache to avoid re-visioning files
receipt_meta = {}


# =============================================================================
# HELPERS
# =============================================================================

def sanitize_str(s):
    if not s:
        return ""
    return str(s).strip().replace("\r", " ").replace("\n", " ")


def parse_amount(val):
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


def normalize_merchant(s):
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
    s = s.strip().lower()

    # Special intelligence - Soho House variations (legacy fallback)
    if "soho" in s or "sh nash" in s or "sh nashville" in s or s.startswith("sh "):
        return "soho house"

    # Anthropic / Claude variations (legacy fallback)
    if "anthropic" in s or "claude" in s:
        return "anthropic"

    # Parking
    if "park happy" in s or "parkhappy" in s:
        return "Park Happy Parking"

    # Hotel brands - Choice Hotels owns Cambria, Comfort, etc.
    if "cambria" in s or "choice hotel" in s:
        return "Cambria Hotel"
    if "comfort inn" in s or "comfort suites" in s:
        return "Comfort Inn"

    # Hotel Tonight - extract actual hotel name after the "*"
    if "hotel tonight" in s or "hoteltonight" in s:
        # Extract the hotel name after the "*"
        # "hoteltonight*arthouse" → "arthouse"
        if "*" in s:
            parts = s.split("*")
            hotel_name = parts[-1].strip()  # Get the part after "*"
            if hotel_name:
                return hotel_name
        # Fallback: just remove "hotel tonight"
        return s.replace("hotel tonight", "").replace("hoteltonight", "").strip()

    # Common payment aggregator prefixes - extract merchant name after "*"
    # Examples: "SQ*MERCHANT", "TST*MERCHANT", "DD*MERCHANT", "SQ *MERCHANT"
    if "*" in s:
        # Common prefixes to strip: SQ, TST, DD, PAYPAL, etc.
        prefixes = ["sq", "tst", "dd", "paypal", "venmo", "stripe", "uber", "lyft"]
        for prefix in prefixes:
            # Handle both "SQ*" and "SQ *" (with space)
            if s.startswith(prefix + "*") or s.startswith(prefix + " *"):
                # Get everything after the first "*"
                parts = s.split("*", 1)
                if len(parts) > 1:
                    merchant_name = parts[1].strip()
                    # If there's another "*", take the last part (e.g., "DD*DOORDASH*KALAMATAS" → "KALAMATAS")
                    if "*" in merchant_name:
                        merchant_name = merchant_name.split("*")[-1].strip()
                    if merchant_name:
                        return merchant_name
                break

    # Common abbreviations
    if s.startswith("sq ") or "square " in s:
        return s.replace("sq ", "square ").replace("sq*", "square")

    # Very generic normalize
    cleaned = "".join(ch if ch.isalnum() else " " for ch in s)
    return " ".join(cleaned.split())


def parse_date_fuzzy(s):
    if not s:
        return None
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.strptime(s, fmt).date()
        except Exception:
            pass
    try:
        dt = pd.to_datetime(s, errors="coerce")
        if pd.isna(dt):
            return None
        return dt.date()
    except Exception:
        return None


# =============================================================================
# MASTER RECEIPTS CSV (SUPPLEMENTAL INTEL)
# =============================================================================

def load_master_receipts():
    """
    master_receipts.csv contains:
        filename, merchant, date, amount
    Used to pre-seed metadata or fill missing info before vision.
    """
    if not MASTER_RECEIPTS_PATH.exists():
        print("ℹ️ No master_receipts.csv found.")
        return {}

    try:
        df = pd.read_csv(MASTER_RECEIPTS_PATH, dtype=str, keep_default_na=False)
        out = {}
        for _, r in df.iterrows():
            fname = sanitize_str(r.get("filename"))
            if not fname:
                continue
            out[fname] = {
                "filename": fname,
                "merchant_name": sanitize_str(r.get("merchant")),
                "merchant_normalized": normalize_merchant(r.get("merchant")),
                "receipt_date": sanitize_str(r.get("date")),
                "total_amount": parse_amount(r.get("amount")),
                "source": "master_csv"
            }
        print(f"📑 Loaded master_receipts.csv intelligence for {len(out)} files")
        return out
    except Exception as e:
        print(f"⚠️ Error loading master_receipts.csv: {e}")
        return {}


master_receipts_intel = load_master_receipts()


# =============================================================================
# RECEIPT META CACHE
# =============================================================================

def load_meta_cache():
    global receipt_meta
    if not RECEIPT_META_PATH.exists():
        receipt_meta = {}
        return

    try:
        df = pd.read_csv(RECEIPT_META_PATH, dtype=str, keep_default_na=False)
        for _, r in df.iterrows():
            receipt_meta[r["filename"]] = {
                "filename": r["filename"],
                "merchant_name": sanitize_str(r.get("merchant_name")),
                "merchant_normalized": sanitize_str(r.get("merchant_normalized")),
                "receipt_date": sanitize_str(r.get("receipt_date")),
                "total_amount": parse_amount(r.get("total_amount")),
                "subtotal_amount": parse_amount(r.get("subtotal_amount")),
                "tip_amount": parse_amount(r.get("tip_amount")),
                "raw_json": sanitize_str(r.get("raw_json")),
            }
        print(f"📚 Loaded {len(receipt_meta)} cached vision receipts")
    except Exception as e:
        print(f"⚠️ Failed to load receipt_meta: {e}")
        receipt_meta = {}


def save_meta_cache():
    if not receipt_meta:
        return
    rows = []
    for meta in receipt_meta.values():
        rows.append(meta)
    pd.DataFrame(rows).to_csv(RECEIPT_META_PATH, index=False)
    print(f"💾 Saved {len(receipt_meta)} cached vision receipts")


load_meta_cache()


# =============================================================================
# VISION EXTRACTION
# =============================================================================

def encode_image(path: Path) -> str:
    with path.open("rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")


VISION_PROMPT = """
You are Brian Kaplan's top-tier receipt parser.

Return ONLY a JSON object:

{
 "merchant_name": "...",
 "merchant_normalized": "...",
 "receipt_date": "YYYY-MM-DD",
 "subtotal_amount": 0.0,
 "tip_amount": 0.0,
 "total_amount": 0.0
}

CRITICAL RULES FOR MERCHANT NAME:
1. **merchant_name** = THE BUSINESS/COMPANY NAME (e.g., "PMC", "Starbucks", "Whole Foods")
   - Look for the BUSINESS NAME at the TOP of the receipt (usually largest text, or in a logo)
   - DO NOT use street addresses (e.g., "2318 12th Ave S") as the merchant name
   - DO NOT use location descriptions as merchant name
   - Examples:
     * PMC (not "2318 12th Ave S Nashville")
     * Starbucks (not "123 Main Street")
     * Whole Foods (not "Nashville, TN 37203")

2. **merchant_normalized** = Clean version of merchant name (remove extra words, locations, etc.)
   - Remove city/state suffixes: "PMC Nashville" → "PMC"
   - Remove location markers: "Starbucks #1234" → "Starbucks"
   - Keep brand names consistent: "SH Nashville" or "Soho House Nashville" → "Soho House"

AMOUNT EXTRACTION RULES:
- Identify handwritten tips carefully
- If subtotal + tip = total, confirm the math
- If only subtotal + handwritten tip → compute total_amount
- Look for "Total", "Amount Due", "Balance Due" - these are the final charge
- For parking receipts: Look for "Total Due" or final payment amount

DATE EXTRACTION:
- Return in YYYY-MM-DD format
- Look for transaction date, not expiration dates or other dates

If unclear on any field, do your best intelligent guess.
"""

def vision_extract(path: Path):
    """
    Run Local OCR (Llama 3.2 Vision) on a single receipt, with GPT-4.1 fallback.
    """
    print(f"👁️  Vision extract: {path.name}")

    # Try local OCR first (Donut model - FREE, FAST, LOCAL, 97-98% accuracy)
    if LOCAL_OCR_AVAILABLE:
        try:
            print(f"   🔄 Using Donut OCR (trained on YOUR receipts)...")
            local_result = extract_receipt_fields_local(str(path), config={'validate': True})

            if local_result and local_result.get("success"):
                # Map local OCR results to expected format (handle None values)
                merchant = local_result.get("Receipt Merchant") or ""
                merchant = merchant.strip() if merchant else ""
                norm = normalize_merchant(merchant)
                date_s = local_result.get("Receipt Date") or ""
                total = local_result.get("Receipt Total") or 0.0

                # FILTER OUT NON-RECEIPTS (marketing emails, contracts, etc.)
                # If $0.00 total AND generic merchant → move to non-receipts/ folder
                merchant_lower = merchant.lower()
                is_generic_merchant = (
                    not merchant or
                    merchant_lower in ["unknown", "unknown merchant", "n/a", "none", ""] or
                    "unknown" in merchant_lower
                )

                if total == 0.0 and is_generic_merchant:
                    # Move to non-receipts folder
                    non_receipts_dir = BASE_DIR / "non-receipts"
                    non_receipts_dir.mkdir(exist_ok=True)
                    new_path = non_receipts_dir / path.name

                    # Move file (handle duplicates)
                    if new_path.exists():
                        # Add timestamp to avoid conflicts
                        stem = path.stem
                        suffix = path.suffix
                        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        new_path = non_receipts_dir / f"{stem}_{timestamp}{suffix}"

                    shutil.move(str(path), str(new_path))
                    print(f"   📁 FILTERED non-receipt → non-receipts/{new_path.name}")
                    print(f"      (Reason: $0.00 total + generic merchant '{merchant}')")
                    print(f"   ⏭️  Skipping GPT-4.1 Vision (saves API costs)")
                    return None

                # Extract subtotal and tip from Donut output
                subtotal = local_result.get("subtotal_amount") or 0.0
                tip = local_result.get("tip_amount") or 0.0
                ocr_method = local_result.get("ocr_method", "Donut")
                confidence = local_result.get("confidence_score", 0.0)

                # Get validation results if available
                validation = local_result.get("validation", {})
                validated_confidence = local_result.get("validated_confidence", confidence)

                meta = {
                    "filename": path.name,
                    "merchant_name": merchant,
                    "merchant_normalized": norm,
                    "receipt_date": date_s,
                    "subtotal_amount": subtotal,
                    "tip_amount": tip,
                    "total_amount": total,
                    "raw_json": json.dumps(local_result, ensure_ascii=False),
                    "ocr_source": f"local_{ocr_method.lower()}",
                    "confidence_score": confidence,
                    "validated_confidence": validated_confidence,
                    "validation_passed": local_result.get("validation_passed", True),
                    "validation_errors": validation.get("errors", []),
                    "validation_warnings": validation.get("warnings", []),
                }

                print(f"   ✅ {ocr_method} success: {merchant} · ${total:.2f} · {date_s} (conf: {confidence:.0%})")
                return meta
            else:
                print(f"   ⚠️ Local OCR failed: {local_result.get('error', 'Unknown error')}")
                print(f"   🔄 Falling back to GPT-4.1 Vision...")
        except Exception as e:
            print(f"   ⚠️ Local OCR exception: {e}")
            print(f"   🔄 Falling back to GPT-4.1 Vision...")

    # Fallback to GPT-4.1 Vision (API cost, but more reliable)
    b64 = encode_image(path)

    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            response_format={"type": "json_object"},
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {
                        "url": f"data:image/jpeg;base64,{b64}",
                        "detail": "high"
                    }}
                ]
            }]
        )
        out = json.loads(resp.choices[0].message.content)
    except Exception as e:
        print(f"⚠️ GPT-4.1 Vision error: {e}")
        return None

    merchant = out.get("merchant_name", "").strip()
    norm = out.get("merchant_normalized", "").strip() or normalize_merchant(merchant)
    date_s = out.get("receipt_date") or ""
    subtotal = parse_amount(out.get("subtotal_amount"))
    tip = parse_amount(out.get("tip_amount"))
    total = parse_amount(out.get("total_amount"))

    meta = {
        "filename": path.name,
        "merchant_name": merchant,
        "merchant_normalized": norm,
        "receipt_date": date_s,
        "subtotal_amount": subtotal,
        "tip_amount": tip,
        "total_amount": total,
        "raw_json": json.dumps(out, ensure_ascii=False),
        "ocr_source": "gpt41_vision"
    }

    print(f"   ✅ GPT-4.1 Vision success: {merchant} · ${total:.2f} · {date_s}")
    return meta


def get_meta(filename):
    """
    Get metadata from:
      1. Cache
      2. master_receipts.csv
      3. Vision
    """
    global receipt_meta

    if filename in receipt_meta:
        return receipt_meta[filename]

    # Master CSV fallback (instant)
    if filename in master_receipts_intel:
        receipt_meta[filename] = master_receipts_intel[filename]
        save_meta_cache()
        return receipt_meta[filename]

    path = RECEIPT_DIR / filename
    if not path.exists():
        return None

    meta = vision_extract(path)
    if meta:
        # Normalize again after vision
        meta["merchant_normalized"] = normalize_merchant(
            meta.get("merchant_normalized") or meta.get("merchant_name")
        )
        receipt_meta[filename] = meta
        save_meta_cache()
        return meta

    return None


# =============================================================================
# MATCHING ENGINE
# =============================================================================

def find_best_receipt(chase_row: dict):
    """
    This is called by viewer_server.py.
    Returns:
    {
      "file": "...",
      "score": float,
      "vision_meta": {...},
      "amount_score": float,
      "merchant_score": float,
      "date_score": float
    }
    or None
    """

    RECEIPT_DIR.mkdir(exist_ok=True)

    chase_amt = parse_amount(
        chase_row.get("Chase Amount") or chase_row.get("amount") or 0
    )
    chase_desc = normalize_merchant(
        chase_row.get("Chase Description") or chase_row.get("merchant") or ""
    )
    chase_date = parse_date_fuzzy(
        chase_row.get("Chase Date") or chase_row.get("transaction_date") or ""
    )

    best = None
    best_score = 0.0

    for fname in os.listdir(RECEIPT_DIR):
        if not fname.lower().endswith((".jpg", ".jpeg", ".png", ".webp")):
            continue

        meta = get_meta(fname)
        if not meta:
            continue

        # Amount score with restaurant tip detection
        r_total = meta.get("total_amount") or 0
        r_subtotal = meta.get("subtotal_amount") or 0

        # Check for restaurant tip scenario (customer copy vs final charge)
        # If transaction is ~15-25% more than receipt, likely added tip
        is_restaurant_tip = False
        amount_to_match = r_total

        if chase_amt and r_subtotal and r_subtotal > 0:
            # Check if transaction matches subtotal + tip (15-25% range)
            tip_range_low = r_subtotal * 1.15
            tip_range_high = r_subtotal * 1.25
            if tip_range_low <= chase_amt <= tip_range_high:
                is_restaurant_tip = True
                # Use subtotal for amount matching since tip varies
                amount_to_match = r_subtotal
                chase_amt_adjusted = chase_amt / 1.20  # Estimate pre-tip amount

        if chase_amt and amount_to_match:
            if is_restaurant_tip:
                # For restaurant tips, use the adjusted amount
                diff = abs(chase_amt_adjusted - amount_to_match)
            else:
                # Standard amount matching
                diff = abs(chase_amt - amount_to_match)

            # TIGHTER tolerance: $0.50 or 2% (whichever is larger)
            # This catches OCR errors but prevents wrong matches
            scale = max(0.50, 0.02 * abs(chase_amt))
            amount_score = max(0, 1 - diff / scale)
        else:
            amount_score = 0

        # Merchant score
        merch_score = SequenceMatcher(
            None, chase_desc.lower(), (meta.get("merchant_normalized") or "").lower()
        ).ratio()

        # =====================================================================
        # INTELLIGENT DATE SCORING (PERMISSIVE - USES OCR INTELLIGENCE)
        # =====================================================================
        r_date = parse_date_fuzzy(meta.get("receipt_date") or "")

        # NEW APPROACH: Calculate date score for ALL receipts (don't reject before scoring)
        # This allows OCR intelligence to find matches even with date mismatches
        if chase_date and r_date:
            delta = abs((chase_date - r_date).days)

            # SPECIAL CASE: Subscription billing cycles
            # Example: July 1 charge for June 1-30 service (receipt dated June 1)
            is_monthly_subscription = False
            if 28 <= delta <= 31:  # Monthly billing cycle (28-31 days)
                merch_lower = (meta.get("merchant_normalized") or "").lower()
                subscription_keywords = [
                    'netflix', 'spotify', 'apple', 'google', 'anthropic', 'claude',
                    'microsoft', 'adobe', 'amazon prime', 'hulu', 'disney',
                    'dropbox', 'github', 'cloudflare', 'aws', 'vercel', 'openai'
                ]
                if any(keyword in merch_lower for keyword in subscription_keywords):
                    is_monthly_subscription = True
                    print(f"   📅 Subscription billing cycle detected: {fname} ({delta} days)", flush=True)

            # DELIVERY SERVICE SPECIAL HANDLING (DoorDash, Uber Eats, etc.)
            # These often have date/amount mismatches due to tips and order timing
            is_delivery_service = False
            delivery_keywords = ['doordash', 'dd', 'uber eats', 'grubhub', 'postmates', 'caviar', 'instacart']
            if any(kw in chase_desc.lower() for kw in delivery_keywords):
                is_delivery_service = True
                # Allow up to 14 days for delivery services (order date vs charge date)
                if delta <= 14:
                    print(f"   🚚 Delivery service detected: {fname} (allowing {delta} day gap)", flush=True)

            # Calculate date score (PERMISSIVE - doesn't reject, just scores lower)
            if delta == 0:
                date_score = 1.0  # Perfect match
            elif delta == 1:
                date_score = 0.95  # Next day (common for tips/processing)
            elif delta <= 3:
                date_score = 0.90  # Weekend/processing delay
            elif delta <= 7:
                date_score = 0.85  # Week-long delay (hotel checkout, etc.)
            elif delta <= 14 and is_delivery_service:
                date_score = 0.75  # Delivery service timing variation
            elif is_monthly_subscription:
                date_score = 0.80  # Monthly subscription billing cycle
            elif delta <= 30:
                date_score = 0.50  # Possible match (1 month off)
            elif delta <= 60:
                date_score = 0.25  # Weak match (2 months off)
            else:
                date_score = 0.10  # Very weak (but still scored)
        else:
            # Missing date = low score (but don't reject - let merchant/amount match)
            date_score = 0.30  # Neutral - can still match on merchant + amount
            print(f"   ⚠️  {fname}: Missing date (tx:{chase_date} rcpt:{r_date})", flush=True)

        # =====================================================================
        # INTELLIGENT SCORING (USES OCR DATA)
        # =====================================================================

        # 🚨 CRITICAL FIRST CHECK: Merchant similarity must meet minimum threshold
        # If merchant is too different, score is ZERO (no point calculating weighted average)
        # This prevents OPTIMIST from matching Soho House just because amounts coincidentally align
        MERCHANT_MINIMUM = 0.30  # Below 30% similarity = completely different merchant (was 50% - too strict!)

        if merch_score < MERCHANT_MINIMUM:
            # Different merchant = ZERO SCORE (don't even consider)
            print(f"   ❌ SKIP: {fname} - Merchant too different ({merch_score*100:.0f}% < {MERCHANT_MINIMUM*100:.0f}%)", flush=True)
            continue  # Skip to next receipt

        # BALANCED FORMULA: All factors contribute to final score
        # Amount: 50% (primary match factor)
        # Merchant: 30% (handles variations)
        # Date: 20% (bonus for matching dates, penalty for mismatches)
        score = 0.5 * amount_score + 0.3 * merch_score + 0.2 * date_score

        if score > best_score:
            best_score = score
            best = {
                "file": fname,
                "score": round(score, 3),
                "vision_meta": meta,
                "amount_score": round(amount_score, 3),
                "merchant_score": round(merch_score, 3),
                "date_score": round(date_score, 3)
            }

    # =============================================================================
    # STRICT VALIDATION (PREVENT FALSE POSITIVES)
    # =============================================================================
    if best:
        # CRITICAL RULE: Merchant MUST be at least 75% similar
        # This prevents matching to completely different merchants
        # (e.g., OPTIMIST → Soho House, both in Nashville)
        if best["merchant_score"] < 0.75:
            print(f"   ❌ REJECTED: Merchant similarity too low ({best['merchant_score']*100:.0f}%)")
            print(f"       Merchant matching requires 75%+ similarity to prevent false positives")
            return None

        # RULE 1: Amount must be reasonable (within 20% OR exact match)
        amount_ok = best["amount_score"] >= 0.80  # Within ~$1 for typical receipts
        merchant_ok = best["merchant_score"] >= 0.80  # Strong merchant similarity

        # RULE 2: Must meet MINIMUM threshold for BOTH amount and merchant
        # (unless one is VERY strong)
        amount_terrible = best["amount_score"] < 0.50  # >50% off is terrible
        merchant_terrible = best["merchant_score"] < 0.40  # <40% similarity is terrible

        # Reject if BOTH are terrible
        if amount_terrible and merchant_terrible:
            print(f"   ❌ REJECTED: Both amount ({best['amount_score']*100:.0f}%) and merchant ({best['merchant_score']*100:.0f}%) too low")
            return None

        # Reject if amount is terrible AND merchant isn't excellent
        if amount_terrible and not merchant_ok:
            print(f"   ❌ REJECTED: Amount too far off ({best['amount_score']*100:.0f}%) and merchant not strong enough ({best['merchant_score']*100:.0f}%)")
            return None

        # Reject if merchant is terrible AND amount isn't excellent
        if merchant_terrible and not amount_ok:
            print(f"   ❌ REJECTED: Merchant too different ({best['merchant_score']*100:.0f}%) and amount not perfect ({best['amount_score']*100:.0f}%)")
            return None

    # INTELLIGENT THRESHOLD: 70% minimum (raised from 65% for safety)
    # Stricter than before to prevent false positives like OPTIMIST/Soho House
    if best and best["score"] >= 0.70:
        return best
    return None
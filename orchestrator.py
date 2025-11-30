#!/usr/bin/env python3
"""
orchestrator.py — Master Receipt Intelligence Coordinator
---------------------------------------------------------

This module coordinates ALL receipt matching sources for Brian Kaplan's system:
  1. Local receipts/ folder (vision-based matching)
  2. Gmail search across 3 accounts (with vision + scoring)
  3. iMessage search (text messages with receipt links)
  4. Contacts & merchant intelligence (for AI notes)
  5. AI note generation

Called by viewer_server.py for:
  - /ai_match endpoint
  - /ai_note endpoint
  - /find_missing_receipts batch processing
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime

from dotenv import load_dotenv
from openai import OpenAI

# Local modules
from helpers import parse_amount_str, normalize_merchant_name
from contacts_engine import (
    merchant_hint_for_row,
    guess_attendees_for_row,
)

load_dotenv()

# =============================================================================
# CONFIG
# =============================================================================

BASE_DIR = Path(__file__).resolve().parent
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Missing OPENAI_API_KEY in environment")

client = OpenAI(api_key=OPENAI_API_KEY)


# =============================================================================
# IMPORT RECEIPT MATCHERS (with graceful fallback)
# =============================================================================

try:
    from ai_receipt_locator import find_best_receipt as find_best_receipt_local
    LOCAL_RECEIPTS_AVAILABLE = True
except Exception:
    LOCAL_RECEIPTS_AVAILABLE = False
    find_best_receipt_local = None

try:
    from gmail_search import find_best_gmail_receipt_for_row
    GMAIL_SEARCH_AVAILABLE = True
except Exception:
    GMAIL_SEARCH_AVAILABLE = False
    find_best_gmail_receipt_for_row = None

try:
    from imessage_search import search_imessage, download_imessage_receipt
    IMESSAGE_SEARCH_AVAILABLE = True
except Exception:
    IMESSAGE_SEARCH_AVAILABLE = False
    search_imessage = None
    download_imessage_receipt = None


# =============================================================================
# UNIFIED MATCHING: LOCAL → GMAIL ESCALATION
# =============================================================================

def find_best_receipt_for_transaction(
    tx: Dict[str, Any],
    local_threshold: float = 0.65,
    gmail_threshold: float = 0.70,
    enable_gmail: bool = True,
) -> Dict[str, Any]:
    """
    Master receipt finder with 3-tier escalation logic:

    1. Try local receipts/ folder first (fast, cached vision)
    2. If no strong match, escalate to Gmail search (HTML email screenshots)
    3. If still no match, escalate to iMessage search (text messages with receipt links)
    4. Return unified result format for viewer_server.py

    Returns:
    {
        "receipt_file": "...",           # filename to attach
        "match_score": 0-100,            # confidence percentage
        "ai_receipt_merchant": "...",
        "ai_receipt_date": "...",
        "ai_receipt_total": 0.0,
        "ai_reason": "...",              # human explanation
        "ai_confidence": 0-100,
        "source": "local" | "gmail" | "imessage" | "none",
        "method": "vision" | "heuristic" | "url_download"
    }
    """

    desc = tx.get("Chase Description") or tx.get("merchant") or ""
    amt = parse_amount_str(tx.get("Chase Amount") or tx.get("amount") or 0)
    date = tx.get("Chase Date") or tx.get("transaction_date") or ""

    print(f"\n🔍 Orchestrator matching: {desc} · ${amt:.2f} · {date}")

    # -------------------------------------------------------------------------
    # PHASE 1: LOCAL RECEIPTS
    # -------------------------------------------------------------------------
    local_match = None
    if LOCAL_RECEIPTS_AVAILABLE and find_best_receipt_local:
        try:
            local_match = find_best_receipt_local(tx)
        except Exception as e:
            print(f"⚠️ Local receipt search error: {e}")

    if local_match and local_match.get("score", 0) >= local_threshold:
        meta = local_match.get("vision_meta") or {}
        score = local_match.get("score", 0)

        result = {
            "receipt_file": local_match.get("file", ""),
            "match_score": int(score * 100),
            "ai_receipt_merchant": meta.get("merchant_name", ""),
            "ai_receipt_date": meta.get("receipt_date", ""),
            "ai_receipt_total": meta.get("total_amount", 0.0),
            "ai_reason": (
                f"Local match: {meta.get('merchant_name')} · "
                f"${meta.get('total_amount', 0):.2f} · "
                f"{meta.get('receipt_date')} · "
                f"confidence {int(score * 100)}%"
            ),
            "ai_confidence": int(score * 100),
            "source": "local",
            "method": "vision",
        }

        print(f"✅ LOCAL MATCH: {result['receipt_file']} (score {score:.3f})")
        return result

    # -------------------------------------------------------------------------
    # PHASE 2: GMAIL ESCALATION
    # -------------------------------------------------------------------------
    if enable_gmail and GMAIL_SEARCH_AVAILABLE and find_best_gmail_receipt_for_row:
        print("📬 Escalating to Gmail search...")
        try:
            gmail_match = find_best_gmail_receipt_for_row(tx, threshold=gmail_threshold)
            if gmail_match:
                result = {
                    "receipt_file": gmail_match.saved_filename,
                    "match_score": int(gmail_match.score * 100),
                    "ai_receipt_merchant": gmail_match.merchant_name,
                    "ai_receipt_date": gmail_match.receipt_date,
                    "ai_receipt_total": gmail_match.total_amount,
                    "ai_reason": (
                        f"Gmail match from {gmail_match.account}: "
                        f"{gmail_match.merchant_name} · "
                        f"${gmail_match.total_amount:.2f} · "
                        f"{gmail_match.receipt_date} · "
                        f"confidence {int(gmail_match.score * 100)}%"
                    ),
                    "ai_confidence": int(gmail_match.score * 100),
                    "source": "gmail",
                    "method": "vision",
                }

                print(f"✅ GMAIL MATCH: {result['receipt_file']} (score {gmail_match.score:.3f})")
                return result
        except Exception as e:
            print(f"⚠️ Gmail search error: {e}")

    # -------------------------------------------------------------------------
    # PHASE 3: iMESSAGE SEARCH
    # -------------------------------------------------------------------------
    if enable_gmail and IMESSAGE_SEARCH_AVAILABLE and search_imessage:
        print("💬 Escalating to iMessage search...")
        try:
            imessage_candidates = search_imessage(tx)
            if imessage_candidates and len(imessage_candidates) > 0:
                # Get best candidate
                best_candidate = imessage_candidates[0]
                score = best_candidate['score']

                if score >= 0.70:  # 70% threshold for iMessage
                    # Download the receipt from URL
                    url = best_candidate['urls'][0]
                    downloaded_file = download_imessage_receipt(url, tx)

                    if downloaded_file:
                        result = {
                            "receipt_file": downloaded_file,
                            "match_score": int(score * 100),
                            "ai_receipt_merchant": desc,  # Use transaction merchant
                            "ai_receipt_date": date,
                            "ai_receipt_total": amt,
                            "ai_reason": (
                                f"iMessage match from {best_candidate['sender']}: "
                                f"{desc} · "
                                f"${amt:.2f} · "
                                f"{date} · "
                                f"confidence {int(score * 100)}%"
                            ),
                            "ai_confidence": int(score * 100),
                            "source": "imessage",
                            "method": "browser_screenshot",
                        }

                        print(f"✅ iMESSAGE MATCH: {result['receipt_file']} (score {score:.3f})")
                        return result
        except Exception as e:
            print(f"⚠️ iMessage search error: {e}")

    # -------------------------------------------------------------------------
    # NO MATCH FOUND
    # -------------------------------------------------------------------------
    best_score = 0
    if local_match:
        best_score = int(local_match.get("score", 0) * 100)

    result = {
        "receipt_file": "",
        "match_score": best_score,
        "ai_receipt_merchant": "",
        "ai_receipt_date": "",
        "ai_receipt_total": 0.0,
        "ai_reason": (
            f"No receipt found above threshold. "
            f"Best local score: {best_score}%"
        ),
        "ai_confidence": best_score,
        "source": "none",
        "method": "none",
    }

    print(f"❌ NO MATCH (best score: {best_score}%)")
    return result


# =============================================================================
# AI NOTE GENERATION (BUSINESS INTELLIGENCE)
# =============================================================================

def ai_generate_note(tx: Dict[str, Any]) -> str:
    """
    Generate a rich, context-aware note for a transaction using:
      - Merchant intelligence (from contacts_engine)
      - Guessed attendees (for meals/meetings)
      - OpenAI for natural language synthesis

    Returns a 1-2 sentence business-focused note.
    """

    desc = tx.get("Chase Description") or tx.get("merchant") or "Unknown"
    amt = parse_amount_str(tx.get("Chase Amount") or tx.get("amount") or 0)
    date = tx.get("Chase Date") or tx.get("transaction_date") or ""
    biz = tx.get("Business Type") or "Unassigned"
    cat = tx.get("Chase Category") or tx.get("category") or ""

    # Get merchant hint (from contacts_engine)
    hint = merchant_hint_for_row(tx)

    # Get likely attendees (for meals/meetings)
    attendees = guess_attendees_for_row(tx)
    attendees_str = ", ".join(attendees) if len(attendees) > 1 else ""

    prompt = f"""
You are Brian Kaplan's executive assistant. Generate a concise, professional note for this expense.

Transaction:
- Merchant: {desc}
- Amount: ${amt:.2f}
- Date: {date}
- Category: {cat}
- Business: {biz}

Context:
- Merchant Intelligence: {hint or "Standard business expense"}
- Likely Attendees: {attendees_str or "Brian Kaplan"}

Write a 1-2 sentence note explaining:
1. What this expense represents
2. Why it's business-relevant for {biz}

Keep it factual, concise, and professional. Focus on business value, not just describing the transaction.
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write concise business expense notes."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=150,
            temperature=0.7,
        )
        note = resp.choices[0].message.content.strip()
        return note
    except Exception as e:
        print(f"⚠️ AI note generation error: {e}")
        # Fallback to basic note
        if hint:
            return f"${amt:.2f} at {desc} on {date} · {hint}"
        return f"${amt:.2f} at {desc} on {date} · categorized as {biz}"


# =============================================================================
# AI REPORT BLOCK GENERATION (FOR EXPENSE REPORTS)
# =============================================================================

def ai_generate_report_block(tx: Dict[str, Any]) -> str:
    """
    Generate a formal expense report line item for accounting/reimbursement.

    Returns a structured text block ready for copy-paste into expense reports.
    """

    desc = tx.get("Chase Description") or "Unknown Merchant"
    amt = parse_amount_str(tx.get("Chase Amount") or tx.get("amount") or 0)
    date = tx.get("Chase Date") or tx.get("transaction_date") or ""
    biz = tx.get("Business Type") or "Unassigned"
    cat = tx.get("Chase Category") or ""

    attendees = guess_attendees_for_row(tx)
    hint = merchant_hint_for_row(tx)

    attendees_str = ", ".join(attendees)

    prompt = f"""
Generate a formal expense report entry for:

Merchant: {desc}
Amount: ${amt:.2f}
Date: {date}
Category: {cat}
Business Unit: {biz}
Attendees: {attendees_str}
Context: {hint or "Business expense"}

Format:
**Date:** {date}
**Merchant:** [merchant name]
**Amount:** ${amt:.2f}
**Business Purpose:** [1-2 sentence explanation]
**Attendees:** {attendees_str}

Keep it professional and accounting-friendly.
"""

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "You write formal expense report entries."},
                {"role": "user", "content": prompt}
            ],
            max_tokens=200,
            temperature=0.5,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"⚠️ Report block generation error: {e}")
        return f"**Date:** {date}\n**Merchant:** {desc}\n**Amount:** ${amt:.2f}\n**Business:** {biz}"


# =============================================================================
# LEGACY COMPATIBILITY SHIMS
# =============================================================================

def ai_match_for_row(tx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Legacy wrapper for find_best_receipt_for_transaction.
    Kept for backward compatibility with viewer_server.py imports.
    """
    return find_best_receipt_for_transaction(tx)


def ai_find_missing_receipts(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Batch process multiple rows to find missing receipts.
    Returns list of updated row dicts.
    """
    results = []
    for i, row in enumerate(rows):
        print(f"\n📋 Processing row {i+1}/{len(rows)}")
        result = find_best_receipt_for_transaction(row)
        results.append(result)
    return results


# =============================================================================
# CLI TEST HARNESS
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test orchestrator matching")
    parser.add_argument("--desc", required=True, help="Merchant description")
    parser.add_argument("--amount", required=True, type=float, help="Transaction amount")
    parser.add_argument("--date", default="", help="Transaction date")
    parser.add_argument("--biz", default="Personal", help="Business type")
    args = parser.parse_args()

    test_tx = {
        "Chase Description": args.desc,
        "Chase Amount": args.amount,
        "Chase Date": args.date,
        "Business Type": args.biz,
    }

    print("=" * 80)
    print("ORCHESTRATOR TEST".center(80))
    print("=" * 80)

    # Test matching
    match_result = find_best_receipt_for_transaction(test_tx)
    print("\n📄 MATCH RESULT:")
    print(json.dumps(match_result, indent=2, ensure_ascii=False))

    # Test note generation
    print("\n📝 AI NOTE:")
    note = ai_generate_note(test_tx)
    print(note)

    # Test report block
    print("\n📊 REPORT BLOCK:")
    report = ai_generate_report_block(test_tx)
    print(report)

    print("\n" + "=" * 80)

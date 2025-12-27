#!/usr/bin/env python3
"""
Apple Receipt Splitter
Analyzes Apple App Store receipts and splits line items into personal vs business categories.

Uses Gemini Vision to extract individual subscriptions/purchases and classify them.
"""

import os
import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from PIL import Image
from dotenv import load_dotenv

load_dotenv()

# Import Gemini for vision analysis
try:
    from gemini_utils import generate_content_with_fallback
    GEMINI_AVAILABLE = True
except:
    GEMINI_AVAILABLE = False
    generate_content_with_fallback = None

BASE_DIR = Path(__file__).parent
RECEIPTS_DIR = BASE_DIR / "receipts"


# =============================================================================
# SUBSCRIPTION CLASSIFICATION DATABASE
# =============================================================================

# Items that are clearly business-related for Brian Kaplan
BUSINESS_SUBSCRIPTIONS = {
    # AI & Productivity
    'chatgpt': 'Business',
    'openai': 'Business',
    'claude': 'Business',
    'anthropic': 'Business',
    'midjourney': 'Business',
    'runway': 'Business',
    'taskade': 'Business',
    'notion': 'Business',
    'obsidian': 'Business',
    'craft': 'Business',

    # Business Tools
    'linkedin': 'Business',
    'slack': 'Business',
    'zoom': 'Business',
    'microsoft 365': 'Business',
    'office': 'Business',
    'canva': 'Business',
    'adobe': 'Business',
    'figma': 'Business',

    # Security & VPN (for business travel)
    'nordvpn': 'Business',
    'expressvpn': 'Business',
    '1password': 'Business',
    'lastpass': 'Business',

    # Development
    'github': 'Business',
    'cursor': 'Business',
    'copilot': 'Business',
    'xcode': 'Business',

    # Music Industry
    'splice': 'Business',
    'distrokid': 'Business',
    'soundcloud': 'Business',
    'bandcamp': 'Business',
    'spotify for artists': 'Business',
}

# Items that are clearly personal
PERSONAL_SUBSCRIPTIONS = {
    # Entertainment
    'apple music': 'Personal',
    'apple tv': 'Personal',
    'apple arcade': 'Personal',
    'netflix': 'Personal',
    'disney': 'Personal',
    'hulu': 'Personal',
    'max': 'Personal',
    'hbo': 'Personal',
    'paramount': 'Personal',
    'peacock': 'Personal',
    'youtube premium': 'Personal',

    # Personal apps
    'stormwatch': 'Personal',
    'weather': 'Personal',
    'fitness': 'Personal',
    'headspace': 'Personal',
    'calm': 'Personal',
    'peloton': 'Personal',

    # Games
    'game': 'Personal',
    'clash': 'Personal',
    'candy crush': 'Personal',

    # Personal storage
    'icloud': 'Personal',  # Unless specifically for business
}

# Items that could be either (require context)
MIXED_SUBSCRIPTIONS = {
    'dropbox': 'ask',  # Could be personal or business
    'google one': 'ask',
    'spotify': 'ask',  # Entertainment but industry research
    'apple one': 'split',  # Bundle needs to be split
}


def classify_subscription(app_name: str, description: str = "") -> Tuple[str, str]:
    """
    Classify a subscription as Personal or Business (Business).

    Returns: (business_type, reasoning)
    """
    app_lower = app_name.lower()
    desc_lower = description.lower() if description else ""

    # Check business keywords first
    for keyword, biz_type in BUSINESS_SUBSCRIPTIONS.items():
        if keyword in app_lower or keyword in desc_lower:
            return (biz_type, f"Business tool: {keyword}")

    # Check personal keywords
    for keyword, biz_type in PERSONAL_SUBSCRIPTIONS.items():
        if keyword in app_lower or keyword in desc_lower:
            return (biz_type, f"Personal: {keyword}")

    # Check mixed keywords
    for keyword, action in MIXED_SUBSCRIPTIONS.items():
        if keyword in app_lower:
            if action == 'split':
                return ('Split', f"Bundle needs manual split: {keyword}")
            else:
                return ('Review', f"Could be personal or business: {keyword}")

    # Default: assume business for productivity apps
    productivity_hints = ['pro', 'premium', 'business', 'professional', 'plus', 'team']
    if any(hint in app_lower or hint in desc_lower for hint in productivity_hints):
        return ('Business', "Productivity subscription (likely business)")

    # Unknown - flag for review
    return ('Review', "Unknown subscription - needs manual classification")


def analyze_apple_receipt(image_path: str) -> Dict[str, Any]:
    """
    Analyze an Apple receipt image and extract all line items.

    Returns:
    {
        "receipt_date": "YYYY-MM-DD",
        "total_amount": 123.45,
        "line_items": [
            {
                "app_name": "ChatGPT",
                "description": "ChatGPT Plus (Monthly)",
                "amount": 19.99,
                "business_type": "Business",
                "reasoning": "AI business tool"
            },
            ...
        ],
        "personal_total": 0.00,
        "business_total": 0.00,
        "needs_review": []
    }
    """
    if not GEMINI_AVAILABLE:
        return {"error": "Gemini not available for receipt analysis"}

    result = {
        "receipt_date": "",
        "total_amount": 0.0,
        "subtotal": 0.0,
        "tax": 0.0,
        "line_items": [],
        "personal_total": 0.0,
        "business_total": 0.0,
        "needs_review": [],
        "source_file": str(image_path)
    }

    try:
        # Load image
        img = Image.open(image_path)

        # Prompt for Gemini to extract line items
        prompt = """Analyze this Apple App Store receipt and extract ALL line items.

For each item, extract:
1. App/Service name
2. Subscription description (e.g., "ChatGPT Plus (Monthly)")
3. Price (just the number, e.g., 19.99)

Also extract:
- Receipt date (YYYY-MM-DD format)
- Subtotal
- Tax
- Total

Return ONLY valid JSON in this exact format:
{
    "receipt_date": "2024-07-31",
    "subtotal": 21.08,
    "tax": 2.06,
    "total": 23.14,
    "items": [
        {"app_name": "StormWatch+", "description": "SW+ Alerts (1 Month)", "amount": 1.09},
        {"app_name": "ChatGPT", "description": "ChatGPT Plus (Monthly)", "amount": 19.99}
    ]
}

Extract ALL items visible on the receipt. Return only the JSON, no other text."""

        response = generate_content_with_fallback(prompt, img)

        if not response:
            return {"error": "Failed to get response from Gemini"}

        # Parse the response
        response = response.strip()
        if response.startswith('```'):
            response = response.split('\n', 1)[1]
        if response.endswith('```'):
            response = response.rsplit('```', 1)[0]
        response = response.strip()

        data = json.loads(response)

        result["receipt_date"] = data.get("receipt_date", "")
        result["subtotal"] = float(data.get("subtotal", 0))
        result["tax"] = float(data.get("tax", 0))
        result["total_amount"] = float(data.get("total", 0))

        # Process each line item
        for item in data.get("items", []):
            app_name = item.get("app_name", "")
            description = item.get("description", "")
            amount = float(item.get("amount", 0))

            # Classify the subscription
            business_type, reasoning = classify_subscription(app_name, description)

            line_item = {
                "app_name": app_name,
                "description": description,
                "amount": amount,
                "business_type": business_type,
                "reasoning": reasoning
            }

            result["line_items"].append(line_item)

            # Sum up totals by type
            if business_type == "Personal":
                result["personal_total"] += amount
            elif business_type in ["Business", "Secondary", "EM.co"]:
                result["business_total"] += amount
            else:
                result["needs_review"].append(line_item)

        # Round totals
        result["personal_total"] = round(result["personal_total"], 2)
        result["business_total"] = round(result["business_total"], 2)

    except Exception as e:
        result["error"] = str(e)

    return result


def split_apple_receipt(image_path: str) -> Dict[str, Any]:
    """
    Split an Apple receipt into personal and business expenses.
    Returns analysis with suggested transaction splits.
    """
    analysis = analyze_apple_receipt(image_path)

    if "error" in analysis:
        return analysis

    # Create split transaction suggestions
    splits = []

    # Group items by business type
    personal_items = [i for i in analysis["line_items"] if i["business_type"] == "Personal"]
    business_items = [i for i in analysis["line_items"] if i["business_type"] in ["Business", "Secondary", "EM.co"]]
    review_items = [i for i in analysis["line_items"] if i["business_type"] in ["Review", "Split"]]

    if personal_items:
        personal_names = ", ".join([i["app_name"] for i in personal_items])
        splits.append({
            "business_type": "Personal",
            "amount": analysis["personal_total"],
            "tax_portion": round(analysis["tax"] * (analysis["personal_total"] / analysis["subtotal"]), 2) if analysis["subtotal"] > 0 else 0,
            "items": personal_items,
            "description": f"Personal subscriptions: {personal_names}"
        })

    if business_items:
        business_names = ", ".join([i["app_name"] for i in business_items])
        splits.append({
            "business_type": "Business",
            "amount": analysis["business_total"],
            "tax_portion": round(analysis["tax"] * (analysis["business_total"] / analysis["subtotal"]), 2) if analysis["subtotal"] > 0 else 0,
            "items": business_items,
            "description": f"Business subscriptions: {business_names}"
        })

    if review_items:
        review_names = ", ".join([i["app_name"] for i in review_items])
        review_total = sum(i["amount"] for i in review_items)
        splits.append({
            "business_type": "Review Required",
            "amount": review_total,
            "tax_portion": round(analysis["tax"] * (review_total / analysis["subtotal"]), 2) if analysis["subtotal"] > 0 else 0,
            "items": review_items,
            "description": f"Needs classification: {review_names}"
        })

    return {
        "original_receipt": analysis,
        "splits": splits,
        "summary": {
            "total_amount": analysis["total_amount"],
            "personal_total": analysis["personal_total"],
            "business_total": analysis["business_total"],
            "review_total": sum(i["amount"] for i in review_items),
            "item_count": len(analysis["line_items"])
        }
    }


def process_all_apple_receipts() -> List[Dict]:
    """
    Process all Apple receipts in the receipts folder and generate split analysis.
    """
    results = []

    # Find all Apple receipts
    apple_receipts = list(RECEIPTS_DIR.glob("applecombill_*.jpg")) + list(RECEIPTS_DIR.glob("applecombill_*.png"))

    print(f"Found {len(apple_receipts)} Apple receipts to process")

    for i, receipt_path in enumerate(apple_receipts):
        print(f"\n[{i+1}/{len(apple_receipts)}] Processing {receipt_path.name}...")

        try:
            split_result = split_apple_receipt(str(receipt_path))

            if "error" not in split_result:
                summary = split_result.get("summary", {})
                print(f"   Total: ${summary.get('total_amount', 0):.2f}")
                print(f"   Personal: ${summary.get('personal_total', 0):.2f}")
                print(f"   Business: ${summary.get('business_total', 0):.2f}")
                if summary.get('review_total', 0) > 0:
                    print(f"   Needs Review: ${summary.get('review_total', 0):.2f}")
            else:
                print(f"   Error: {split_result['error']}")

            results.append({
                "file": receipt_path.name,
                "result": split_result
            })

        except Exception as e:
            print(f"   Error processing {receipt_path.name}: {e}")
            results.append({
                "file": receipt_path.name,
                "error": str(e)
            })

    return results


# =============================================================================
# DATABASE INTEGRATION - AUTO-SPLIT TRANSACTIONS
# =============================================================================

def auto_split_transaction(transaction_id: int, receipt_path: str = None) -> Dict[str, Any]:
    """
    Automatically split an Apple receipt transaction into personal/business parts.

    This will:
    1. Analyze the receipt image using Gemini
    2. Create new split transactions in the database
    3. Link the same receipt to ALL split transactions
    4. Mark the original as 'split' (or delete if requested)

    Returns dict with the split transaction IDs.
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()
        if not db.use_mysql:
            return {"error": "MySQL database not available"}
    except Exception as e:
        return {"error": f"Database connection failed: {e}"}

    result = {
        "original_transaction_id": transaction_id,
        "splits_created": [],
        "status": "pending"
    }

    try:
        # Get the original transaction
        conn = db.get_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT _index, chase_date, chase_description, chase_amount,
                   chase_category, business_type, receipt_file, receipt_url, notes
            FROM transactions
            WHERE _index = %s
        """, (transaction_id,))

        tx = cursor.fetchone()
        if not tx:
            return {"error": f"Transaction {transaction_id} not found"}

        original_date = tx['chase_date']
        original_desc = tx['chase_description']
        original_amount = float(tx['chase_amount'] or 0)
        receipt_file = tx['receipt_file'] or receipt_path
        receipt_url = tx.get('receipt_url', '')

        # Find the receipt image
        if receipt_file:
            receipt_full_path = RECEIPTS_DIR / receipt_file
            if not receipt_full_path.exists():
                # Try finding by pattern
                matches = list(RECEIPTS_DIR.glob(f"*{receipt_file}*"))
                if matches:
                    receipt_full_path = matches[0]
                else:
                    return {"error": f"Receipt file not found: {receipt_file}"}
        else:
            return {"error": "No receipt file linked to transaction"}

        # Analyze and split the receipt
        split_result = split_apple_receipt(str(receipt_full_path))

        if "error" in split_result:
            return split_result

        # Create split transactions
        splits = split_result.get("splits", [])

        if len(splits) <= 1:
            return {
                "status": "no_split_needed",
                "message": "Receipt has only one business type - no split needed",
                "original_transaction_id": transaction_id
            }

        for split in splits:
            biz_type = split["business_type"]
            amount = split["amount"] + split.get("tax_portion", 0)
            items = split.get("items", [])
            description = split.get("description", "")

            # Build new transaction description
            item_names = ", ".join([i["app_name"] for i in items])
            new_desc = f"Apple - {item_names}"

            # Create AI note
            ai_note = description

            # Insert new split transaction
            cursor.execute("""
                INSERT INTO transactions (
                    chase_date, chase_description, chase_amount, chase_category,
                    business_type, receipt_file, receipt_url, notes, ai_note,
                    source, review_status
                ) VALUES (
                    %s, %s, %s, 'App Store', %s, %s, %s, %s, %s,
                    'apple_split', 'good'
                )
            """, (
                original_date,
                new_desc,
                -abs(amount),  # Negative for expenses
                biz_type if biz_type != "Review Required" else "Review",
                receipt_file,
                receipt_url,
                f"Split from Apple receipt {receipt_file}",
                ai_note
            ))

            new_id = cursor.lastrowid
            result["splits_created"].append({
                "transaction_id": new_id,
                "business_type": biz_type,
                "amount": amount,
                "description": new_desc
            })

        # Mark original transaction as split
        cursor.execute("""
            UPDATE transactions
            SET notes = CONCAT(COALESCE(notes, ''), ' [SPLIT into: """ + ", ".join([str(s["transaction_id"]) for s in result["splits_created"]]) + """]'),
                review_status = 'split',
                deleted_by_user = 1
            WHERE _index = %s
        """, (transaction_id,))

        conn.commit()
        conn.close()

        result["status"] = "success"
        result["message"] = f"Split into {len(result['splits_created'])} transactions"

    except Exception as e:
        result["status"] = "error"
        result["error"] = str(e)

    return result


def find_apple_transactions_to_split() -> List[Dict]:
    """
    Find all Apple transactions that have multi-item receipts needing split.
    """
    try:
        from db_mysql import get_mysql_db
        db = get_mysql_db()
        if not db.use_mysql:
            return []
    except:
        return []

    candidates = []

    try:
        conn = db.get_connection()
        cursor = conn.cursor()

        # Find Apple transactions with receipts
        cursor.execute("""
            SELECT _index, chase_date, chase_description, chase_amount, receipt_file
            FROM transactions
            WHERE (chase_description LIKE '%apple%' OR chase_description LIKE '%APPLE%')
              AND receipt_file IS NOT NULL
              AND receipt_file LIKE 'applecombill_%'
              AND (review_status IS NULL OR review_status != 'split')
              AND (deleted_by_user IS NULL OR deleted_by_user = 0)
            ORDER BY chase_date DESC
        """)

        for row in cursor.fetchall():
            candidates.append({
                "transaction_id": row['_index'],
                "date": str(row['chase_date']),
                "description": row['chase_description'],
                "amount": float(row['chase_amount'] or 0),
                "receipt_file": row['receipt_file']
            })

        conn.close()

    except Exception as e:
        print(f"Error finding Apple transactions: {e}")

    return candidates


def process_all_apple_splits(dry_run: bool = True) -> Dict:
    """
    Process all Apple transactions and auto-split those with multiple items.

    Args:
        dry_run: If True, only analyze without creating split transactions

    Returns:
        Summary of splits found/created
    """
    candidates = find_apple_transactions_to_split()

    results = {
        "total_candidates": len(candidates),
        "splits_needed": 0,
        "splits_created": 0 if not dry_run else None,
        "no_split_needed": 0,
        "errors": 0,
        "details": []
    }

    for tx in candidates:
        try:
            receipt_path = RECEIPTS_DIR / tx["receipt_file"]
            if not receipt_path.exists():
                results["errors"] += 1
                continue

            split_result = split_apple_receipt(str(receipt_path))

            if "error" in split_result:
                results["errors"] += 1
                continue

            num_splits = len(split_result.get("splits", []))

            if num_splits > 1:
                results["splits_needed"] += 1

                detail = {
                    "transaction_id": tx["transaction_id"],
                    "date": tx["date"],
                    "original_amount": tx["amount"],
                    "receipt_file": tx["receipt_file"],
                    "splits": split_result["splits"]
                }

                if not dry_run:
                    # Actually perform the split
                    split_db_result = auto_split_transaction(
                        tx["transaction_id"],
                        tx["receipt_file"]
                    )
                    detail["db_result"] = split_db_result
                    if split_db_result.get("status") == "success":
                        results["splits_created"] += 1

                results["details"].append(detail)
            else:
                results["no_split_needed"] += 1

        except Exception as e:
            results["errors"] += 1
            print(f"Error processing {tx['receipt_file']}: {e}")

    return results


# =============================================================================
# CLI TEST
# =============================================================================

if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        # Process specific file
        receipt_path = sys.argv[1]
        print(f"Analyzing: {receipt_path}")
        print("=" * 60)

        result = split_apple_receipt(receipt_path)
        print(json.dumps(result, indent=2))
    else:
        # Test with a sample Apple receipt
        test_receipts = list(RECEIPTS_DIR.glob("applecombill_2024-07-31*.png"))
        if test_receipts:
            test_file = str(test_receipts[0])
            print(f"Testing with: {test_file}")
            print("=" * 60)

            result = split_apple_receipt(test_file)
            print(json.dumps(result, indent=2, default=str))
        else:
            print("No Apple receipts found for testing")
            print("Usage: python apple_receipt_splitter.py [receipt_path]")

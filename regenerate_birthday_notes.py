#!/usr/bin/env python3
"""
Script to regenerate AI notes for transactions that incorrectly reference birthdays.
Uses the deployed API endpoints with admin key authentication.

Usage:
    python regenerate_birthday_notes.py --dry-run       # Just find and list them
    python regenerate_birthday_notes.py --regenerate    # Actually regenerate
"""

import argparse
import json
import time
import urllib.request
import urllib.error

BASE_URL = "https://web-production-309e.up.railway.app"
ADMIN_KEY = "tallyups-admin-2024"

BIRTHDAY_KEYWORDS = ['birthday', 'bday', "b'day", 'anniversary', 'party for']


def fetch_all_transactions(limit=2000):
    """Fetch all transactions from the API."""
    url = f"{BASE_URL}/api/transactions?limit={limit}"
    headers = {"X-Admin-Key": ADMIN_KEY}

    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = json.loads(response.read().decode())
            # Handle both list and dict response formats
            if isinstance(data, list):
                return data
            return data.get('transactions', data)
    except Exception as e:
        print(f"Error fetching transactions: {e}")
        return []


def find_birthday_transactions(transactions):
    """Find transactions with birthday references in ai_note field."""
    matches = []

    for tx in transactions:
        ai_note = (tx.get('ai_note') or '').lower()

        for kw in BIRTHDAY_KEYWORDS:
            if kw in ai_note:
                matches.append({
                    'id': tx.get('id'),
                    '_index': tx.get('_index'),
                    'merchant': tx.get('chase_description') or tx.get('Chase Description') or '',
                    'amount': tx.get('chase_amount') or tx.get('Chase Amount') or '',
                    'date': tx.get('chase_date') or tx.get('Chase Date') or '',
                    'ai_note': tx.get('ai_note'),
                    'business_type': tx.get('business_type') or tx.get('Business Type') or '',
                    'keyword': kw
                })
                break

    return matches


def regenerate_note(transaction):
    """Regenerate AI note for a single transaction."""
    idx = transaction.get('_index')
    if idx is None:
        return None, "No _index found"

    url = f"{BASE_URL}/api/ai/note"
    headers = {
        "X-Admin-Key": ADMIN_KEY,
        "Content-Type": "application/json"
    }
    data = json.dumps({"_index": idx}).encode()

    req = urllib.request.Request(url, data=data, headers=headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode())
            if result.get('ok'):
                return result.get('note'), None
            return None, result.get('error', 'Unknown error')
    except urllib.error.HTTPError as e:
        return None, f"HTTP {e.code}: {e.reason}"
    except Exception as e:
        return None, str(e)


def main():
    parser = argparse.ArgumentParser(description="Regenerate birthday-referenced AI notes")
    parser.add_argument('--dry-run', action='store_true', help='Just find and list, do not regenerate')
    parser.add_argument('--regenerate', action='store_true', help='Regenerate the notes')
    parser.add_argument('--limit', type=int, default=2000, help='Max transactions to fetch')
    args = parser.parse_args()

    if not args.dry_run and not args.regenerate:
        print("Please specify --dry-run or --regenerate")
        return

    print(f"🔍 Fetching up to {args.limit} transactions...")
    transactions = fetch_all_transactions(args.limit)
    print(f"   Found {len(transactions)} transactions")

    print("\n🎂 Looking for birthday references in AI notes...")
    matches = find_birthday_transactions(transactions)
    print(f"   Found {len(matches)} with birthday keywords")

    if not matches:
        print("\n✅ No birthday-referenced notes found!")
        return

    print(f"\n📋 Transactions with birthday references:")
    for i, m in enumerate(matches[:20]):
        print(f"\n{i+1}. {m['merchant'][:50]}")
        print(f"   _index: {m['_index']}, Amount: {m['amount']}")
        print(f"   Old note: {m['ai_note'][:80]}...")
        print(f"   Matched: '{m['keyword']}'")

    if len(matches) > 20:
        print(f"\n   ... and {len(matches) - 20} more")

    if args.dry_run:
        print(f"\n📊 Summary: {len(matches)} notes need regeneration")
        print("   Run with --regenerate to fix them")
        return

    # Regenerate
    print(f"\n🔄 Regenerating {len(matches)} notes...")
    print("   (This may take a while due to API rate limits)\n")

    updated = 0
    failed = 0
    still_birthday = 0

    for i, m in enumerate(matches):
        old_note = m['ai_note']
        new_note, error = regenerate_note(m)

        if error:
            print(f"❌ {m['merchant'][:40]}: {error}")
            failed += 1
        elif new_note:
            # Check if new note still has birthday reference
            has_birthday = any(kw in new_note.lower() for kw in BIRTHDAY_KEYWORDS)

            if has_birthday:
                print(f"⚠️  {m['merchant'][:40]}: Still has birthday ref")
                print(f"   New: {new_note[:70]}...")
                still_birthday += 1
            else:
                print(f"✅ {m['merchant'][:40]}")
                print(f"   Old: {old_note[:50]}...")
                print(f"   New: {new_note[:50]}...")
                updated += 1
        else:
            print(f"❓ {m['merchant'][:40]}: No note returned")
            failed += 1

        # Rate limiting - don't hammer the API
        if (i + 1) % 5 == 0:
            print(f"\n   Progress: {i+1}/{len(matches)} processed...")
            time.sleep(1)  # Brief pause every 5 requests

    print(f"\n📊 Results:")
    print(f"   ✅ Successfully updated: {updated}")
    print(f"   ⚠️  Still has birthday: {still_birthday}")
    print(f"   ❌ Failed: {failed}")
    print(f"   Total processed: {len(matches)}")

    if still_birthday > 0:
        print(f"\n⚠️  {still_birthday} notes still reference birthdays.")
        print("   This likely means the new calendar filtering code isn't deployed yet.")
        print("   Check Railway deployment status and try again.")


if __name__ == "__main__":
    main()

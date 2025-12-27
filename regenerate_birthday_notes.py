#!/usr/bin/env python3
"""
Script to regenerate AI notes for transactions that incorrectly reference birthdays.

Two modes:
1. API mode: Uses deployed API (requires Railway deployment)
2. Direct mode: Generates notes via API, updates DB directly (bypasses deployment issues)

Usage:
    python regenerate_birthday_notes.py --dry-run       # Just find and list them
    python regenerate_birthday_notes.py --regenerate    # Regenerate via API (saves to DB)
    python regenerate_birthday_notes.py --direct        # Generate via API, update DB directly
"""

import argparse
import json
import os
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
                    'category': tx.get('chase_category') or tx.get('Chase Category') or '',
                    'ai_note': tx.get('ai_note'),
                    'business_type': tx.get('business_type') or tx.get('Business Type') or 'Business',
                    'keyword': kw
                })
                break

    return matches


def generate_note_via_api(merchant, amount, date, category, business_type):
    """Generate a new AI note using direct params (bypasses _index lookup)."""
    url = f"{BASE_URL}/api/ai/note"
    headers = {
        "X-Admin-Key": ADMIN_KEY,
        "Content-Type": "application/json"
    }

    # Clean up amount
    try:
        amount_float = float(str(amount).replace('$', '').replace(',', ''))
    except:
        amount_float = 0

    # Clean up date - extract just the date part
    date_str = str(date)
    if ',' in date_str:  # Format like "Sat, 04 Oct 2025 00:00:00 GMT"
        # Parse and reformat
        try:
            from datetime import datetime
            dt = datetime.strptime(date_str, "%a, %d %b %Y %H:%M:%S %Z")
            date_str = dt.strftime("%Y-%m-%d")
        except:
            date_str = ""

    payload = {
        "merchant": merchant,
        "amount": amount_float,
        "date": date_str,
        "category": category or "",
        "business_type": business_type or "Business"
    }

    data = json.dumps(payload).encode()
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


def get_db_connection():
    """Get MySQL connection using Railway environment or local config."""
    try:
        import pymysql
    except ImportError:
        print("Error: pymysql not installed. Run: pip install pymysql")
        return None

    # Try Railway-style env vars first
    host = os.getenv('MYSQL_HOST') or os.getenv('MYSQLHOST')
    user = os.getenv('MYSQL_USER') or os.getenv('MYSQLUSER')
    password = os.getenv('MYSQL_PASSWORD') or os.getenv('MYSQLPASSWORD')
    database = os.getenv('MYSQL_DATABASE') or os.getenv('MYSQLDATABASE')
    port = int(os.getenv('MYSQL_PORT') or os.getenv('MYSQLPORT') or 3306)

    if not all([host, user, password, database]):
        print("Error: MySQL environment variables not set.")
        print("Set MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
        return None

    try:
        conn = pymysql.connect(
            host=host,
            user=user,
            password=password,
            database=database,
            port=port,
            cursorclass=pymysql.cursors.DictCursor
        )
        return conn
    except Exception as e:
        print(f"Database connection error: {e}")
        return None


def update_note_in_db(conn, tx_id, new_note):
    """Update ai_note directly in database."""
    try:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE transactions SET ai_note = %s WHERE id = %s",
            (new_note, tx_id)
        )
        conn.commit()
        cursor.close()
        return True, None
    except Exception as e:
        return False, str(e)


def main():
    parser = argparse.ArgumentParser(description="Regenerate birthday-referenced AI notes")
    parser.add_argument('--dry-run', action='store_true', help='Just find and list, do not regenerate')
    parser.add_argument('--regenerate', action='store_true', help='Regenerate via full API (requires deployment)')
    parser.add_argument('--direct', action='store_true', help='Generate via API, update DB directly')
    parser.add_argument('--limit', type=int, default=2000, help='Max transactions to fetch')
    args = parser.parse_args()

    if not args.dry_run and not args.regenerate and not args.direct:
        print("Please specify --dry-run, --regenerate, or --direct")
        print("\n  --dry-run    : Just find and list birthday notes")
        print("  --regenerate : Use API to regenerate (requires Railway to have new code)")
        print("  --direct     : Generate via API, update DB directly (recommended)")
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
        print(f"   id: {m['id']}, Amount: {m['amount']}")
        print(f"   Old note: {m['ai_note'][:80]}...")
        print(f"   Matched: '{m['keyword']}'")

    if len(matches) > 20:
        print(f"\n   ... and {len(matches) - 20} more")

    if args.dry_run:
        print(f"\n📊 Summary: {len(matches)} notes need regeneration")
        print("   Run with --direct to fix them (recommended)")
        return

    # Direct mode - generate via API, update DB directly
    if args.direct:
        conn = get_db_connection()
        if not conn:
            print("\n❌ Cannot connect to database. Set MySQL environment variables:")
            print("   MYSQL_HOST, MYSQL_USER, MYSQL_PASSWORD, MYSQL_DATABASE")
            return

        print(f"\n🔄 Regenerating {len(matches)} notes (direct mode)...")
        print("   Generating notes via API, updating database directly\n")

        updated = 0
        failed = 0
        still_birthday = 0

        for i, m in enumerate(matches):
            old_note = m['ai_note']
            tx_id = m['id']

            # Generate new note via API (using direct params, not _index)
            new_note, error = generate_note_via_api(
                m['merchant'],
                m['amount'],
                m['date'],
                m['category'],
                m['business_type']
            )

            if error:
                print(f"❌ {m['merchant'][:40]}: {error}")
                failed += 1
                continue

            if not new_note:
                print(f"❓ {m['merchant'][:40]}: No note returned")
                failed += 1
                continue

            # Check if new note still has birthday reference
            has_birthday = any(kw in new_note.lower() for kw in BIRTHDAY_KEYWORDS)

            if has_birthday:
                print(f"⚠️  {m['merchant'][:40]}: Still has birthday ref")
                print(f"   New: {new_note[:70]}...")
                still_birthday += 1
                continue

            # Update in database directly
            success, db_error = update_note_in_db(conn, tx_id, new_note)

            if success:
                print(f"✅ {m['merchant'][:40]}")
                print(f"   Old: {old_note[:50]}...")
                print(f"   New: {new_note[:50]}...")
                updated += 1
            else:
                print(f"❌ {m['merchant'][:40]}: DB update failed: {db_error}")
                failed += 1

            # Rate limiting
            if (i + 1) % 5 == 0:
                print(f"\n   Progress: {i+1}/{len(matches)} processed...")
                time.sleep(0.5)

        conn.close()

        print(f"\n📊 Results:")
        print(f"   ✅ Successfully updated: {updated}")
        print(f"   ⚠️  Still has birthday: {still_birthday}")
        print(f"   ❌ Failed: {failed}")
        print(f"   Total processed: {len(matches)}")

        if still_birthday > 0:
            print(f"\n⚠️  {still_birthday} notes still reference birthdays.")
            print("   The calendar filtering code may not be deployed yet.")
            print("   Once deployed, re-run this script.")
        return

    # Regular regenerate mode (via full API)
    print(f"\n🔄 Regenerating {len(matches)} notes via API...")
    print("   Note: This requires the new code to be deployed on Railway\n")

    from urllib.request import Request, urlopen

    updated = 0
    failed = 0

    for i, m in enumerate(matches):
        idx = m.get('_index')
        if idx is None:
            print(f"❌ {m['merchant'][:40]}: No _index")
            failed += 1
            continue

        url = f"{BASE_URL}/api/ai/note"
        headers = {"X-Admin-Key": ADMIN_KEY, "Content-Type": "application/json"}
        data = json.dumps({"_index": idx}).encode()

        try:
            req = Request(url, data=data, headers=headers, method='POST')
            with urlopen(req, timeout=30) as response:
                result = json.loads(response.read().decode())
                if result.get('ok'):
                    new_note = result.get('note', '')
                    if new_note:
                        print(f"✅ {m['merchant'][:40]}: {new_note[:50]}...")
                        updated += 1
                    else:
                        print(f"❓ {m['merchant'][:40]}: Empty note")
                        failed += 1
                else:
                    print(f"❌ {m['merchant'][:40]}: {result.get('error')}")
                    failed += 1
        except Exception as e:
            print(f"❌ {m['merchant'][:40]}: {e}")
            failed += 1

        if (i + 1) % 5 == 0:
            print(f"\n   Progress: {i+1}/{len(matches)}...")
            time.sleep(1)

    print(f"\n📊 Results:")
    print(f"   ✅ Updated: {updated}")
    print(f"   ❌ Failed: {failed}")


if __name__ == "__main__":
    main()

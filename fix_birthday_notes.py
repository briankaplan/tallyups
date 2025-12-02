#!/usr/bin/env python3
"""
Script to find and fix AI notes that incorrectly reference birthdays or are too vague.

Run this script locally with your Railway environment variables set, OR
use curl against your deployed app.

Usage:
    # Option 1: Run locally with env vars
    export MYSQL_HOST=... MYSQL_USER=... MYSQL_PASSWORD=... MYSQL_DATABASE=...
    python fix_birthday_notes.py

    # Option 2: Run against deployed app
    python fix_birthday_notes.py --url https://your-app.railway.app --session YOUR_SESSION_COOKIE
"""

import argparse
import json
import os
import sys

def run_local():
    """Run locally with direct database access"""
    try:
        from db_mysql import get_db_connection, return_db_connection
    except ImportError:
        print("Error: db_mysql module not found. Make sure you're in the right directory.")
        sys.exit(1)

    # Keywords to search for
    birthday_keywords = ['birthday', 'bday', "b'day", 'anniversary', 'party for']
    vague_keywords = ['business expense', 'business meal', 'client meeting',
                      'software subscription', 'travel expense', 'meal with team']

    conn, db_type = get_db_connection()
    if not conn:
        print("Error: Could not connect to database")
        sys.exit(1)

    cursor = conn.cursor()

    # Find transactions with problematic notes
    print("\n🔍 Searching for transactions with birthday/vague AI notes...\n")

    # Build LIKE clauses for search
    like_clauses = []
    for kw in birthday_keywords + vague_keywords:
        like_clauses.append(f"LOWER(ai_note) LIKE '%{kw}%'")

    query = f"""
        SELECT id, merchant, amount, transaction_date, ai_note, category, business_type
        FROM transactions
        WHERE ai_note IS NOT NULL
        AND ai_note != ''
        AND ({' OR '.join(like_clauses)})
        ORDER BY transaction_date DESC
        LIMIT 200
    """

    cursor.execute(query)
    rows = cursor.fetchall()

    if not rows:
        print("✅ No transactions found with birthday or vague AI notes!")
        cursor.close()
        return_db_connection(conn)
        return

    print(f"Found {len(rows)} transactions with problematic notes:\n")

    # Categorize them
    birthday_matches = []
    vague_matches = []

    for row in rows:
        note = (row.get('ai_note') or '').lower()
        is_birthday = any(kw in note for kw in birthday_keywords)
        is_vague = any(kw in note for kw in vague_keywords)

        entry = {
            'id': row['id'],
            'merchant': row.get('merchant', ''),
            'amount': row.get('amount', 0),
            'date': str(row.get('transaction_date', '')),
            'note': row.get('ai_note', ''),
            'category': row.get('category', ''),
            'business_type': row.get('business_type', '')
        }

        if is_birthday:
            birthday_matches.append(entry)
            print(f"🎂 BIRTHDAY: {entry['merchant'][:40]}")
            print(f"   Note: {entry['note'][:80]}...")
            print()
        elif is_vague:
            vague_matches.append(entry)

    print(f"\n📊 Summary:")
    print(f"   Birthday-related: {len(birthday_matches)}")
    print(f"   Too vague: {len(vague_matches)}")
    print(f"   Total: {len(rows)}")

    cursor.close()
    return_db_connection(conn)

    # Ask to regenerate
    if birthday_matches:
        print(f"\n⚠️  Found {len(birthday_matches)} notes referencing birthdays!")
        response = input("\nRegenerate these notes? (y/n): ").strip().lower()

        if response == 'y':
            regenerate_notes([m['id'] for m in birthday_matches])

def regenerate_notes(transaction_ids):
    """Regenerate AI notes for given transaction IDs"""
    try:
        from viewer_server import gemini_generate_ai_note, update_row_by_index, df, ensure_df
        from viewer_server import parse_amount_str
    except ImportError as e:
        print(f"Error importing viewer_server: {e}")
        print("Make sure you're running from the correct directory with proper env vars.")
        return

    ensure_df()

    print(f"\n🔄 Regenerating {len(transaction_ids)} notes...\n")

    updated = 0
    for tx_id in transaction_ids:
        mask = df["_index"] == tx_id
        if not mask.any():
            print(f"   ⚠️ Transaction {tx_id} not found")
            continue

        row = df[mask].iloc[0].to_dict()
        merchant = row.get("Chase Description") or row.get("merchant") or ""
        amount = parse_amount_str(row.get("Chase Amount") or row.get("amount") or 0)
        date = row.get("Chase Date") or row.get("transaction_date") or ""
        category = row.get("category") or row.get("Chase Category") or ""
        business_type = row.get("Business Type") or "Down Home"

        try:
            result = gemini_generate_ai_note(merchant, amount, date, category, business_type, row=row)
            new_note = result.get("note", "")

            if new_note:
                update_row_by_index(tx_id, {"AI Note": new_note}, source="birthday_fix")
                print(f"   ✅ {merchant[:40]}")
                print(f"      New: {new_note[:70]}...")
                updated += 1
        except Exception as e:
            print(f"   ❌ Error regenerating {merchant}: {e}")

    print(f"\n✅ Updated {updated}/{len(transaction_ids)} notes")


def run_remote(url, session_cookie):
    """Run against deployed app via API"""
    import urllib.request
    import urllib.error

    headers = {
        'Content-Type': 'application/json',
        'Cookie': f'session={session_cookie}'
    }

    # First, find problematic notes
    print(f"\n🔍 Checking {url} for birthday-related notes...\n")

    find_url = f"{url}/api/ai/find-problematic-notes?filter=birthday&limit=100"
    req = urllib.request.Request(find_url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            data = json.loads(response.read().decode())
    except urllib.error.HTTPError as e:
        print(f"Error: {e.code} - {e.reason}")
        if e.code == 401:
            print("Authentication required. Make sure your session cookie is valid.")
        return
    except Exception as e:
        print(f"Error: {e}")
        return

    if not data.get('ok'):
        print(f"Error: {data.get('error', 'Unknown error')}")
        return

    transactions = data.get('transactions', [])
    count = len(transactions)

    if count == 0:
        print("✅ No transactions found with birthday references!")
        return

    print(f"Found {count} transactions with birthday-related notes:\n")

    for tx in transactions[:10]:  # Show first 10
        print(f"🎂 {tx['merchant'][:40]}")
        print(f"   Note: {tx['ai_note'][:80]}...")
        print(f"   Keywords: {', '.join(tx['matched_keywords'])}")
        print()

    if count > 10:
        print(f"   ... and {count - 10} more\n")

    # Ask to regenerate
    response = input(f"\nRegenerate these {count} notes? (y/n): ").strip().lower()

    if response != 'y':
        print("Aborted.")
        return

    # Regenerate
    print(f"\n🔄 Regenerating {count} notes...\n")

    regen_url = f"{url}/api/ai/regenerate-notes"
    regen_data = json.dumps({
        "filter": "birthday",
        "limit": 100,
        "dry_run": False
    }).encode()

    req = urllib.request.Request(regen_url, data=regen_data, headers=headers, method='POST')

    try:
        with urllib.request.urlopen(req, timeout=300) as response:
            result = json.loads(response.read().decode())
    except Exception as e:
        print(f"Error: {e}")
        return

    if result.get('ok'):
        print(f"\n✅ Processed: {result.get('processed', 0)}")
        print(f"✅ Updated: {result.get('updated', 0)}")

        # Show some results
        for r in result.get('results', [])[:5]:
            if r['status'] == 'updated':
                print(f"\n   {r['merchant'][:40]}")
                print(f"   Old: {r['old_note'][:60]}...")
                print(f"   New: {r['new_note'][:60]}...")
    else:
        print(f"Error: {result.get('error', 'Unknown error')}")


def main():
    parser = argparse.ArgumentParser(description="Fix AI notes with birthday references")
    parser.add_argument('--url', help='URL of deployed app (e.g., https://your-app.railway.app)')
    parser.add_argument('--session', help='Session cookie for authentication')
    parser.add_argument('--local', action='store_true', help='Run locally with direct DB access')
    args = parser.parse_args()

    if args.url and args.session:
        run_remote(args.url, args.session)
    elif args.local or os.getenv('MYSQL_HOST'):
        run_local()
    else:
        print("Usage:")
        print("  Local:  python fix_birthday_notes.py --local")
        print("  Remote: python fix_birthday_notes.py --url https://app.railway.app --session YOUR_COOKIE")
        print("\nOr set MYSQL_HOST environment variable for local mode.")


if __name__ == "__main__":
    main()

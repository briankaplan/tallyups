#!/usr/bin/env python3
"""
Vision verify ALL Business transactions and output to CSV.
No database updates - just verification and reporting.
"""

import os
import csv
import json
import base64
import requests
from datetime import datetime
from urllib.parse import urlparse
import pymysql

# Database connection
MYSQL_URL = os.environ.get('MYSQL_URL', 'mysql://root:HKJnPmBKRgPJgfTqHCVrZwarXVAPXvjp@monorail.proxy.rlwy.net:47470/railway')

def get_connection():
    """Get a fresh database connection"""
    parsed = urlparse(MYSQL_URL)
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path.lstrip('/'),
        cursorclass=pymysql.cursors.DictCursor,
        connect_timeout=30,
        read_timeout=120
    )

def fetch_all_transactions():
    """Fetch all Business transactions"""
    conn = get_connection()
    try:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT _index, chase_date, chase_amount, chase_description,
                   receipt_file, receipt_url, r2_url, review_status,
                   ai_confidence, ai_receipt_merchant, ai_receipt_total, ai_receipt_date
            FROM transactions
            WHERE business_type = 'Business'
            AND chase_date >= '2024-07-01'
            AND chase_date <= '2025-12-01'
            ORDER BY chase_date DESC
        ''')
        return cursor.fetchall()
    finally:
        conn.close()

def get_receipt_url(tx):
    """Get the best receipt URL for a transaction"""
    # Priority: r2_url > receipt_url > receipt_file
    if tx.get('r2_url') and tx['r2_url'].startswith('http'):
        return tx['r2_url']
    if tx.get('receipt_url') and tx['receipt_url'].startswith('http'):
        return tx['receipt_url']
    if tx.get('receipt_file'):
        # Try to construct R2 URL
        file_path = tx['receipt_file']
        if ',' in file_path:
            file_path = file_path.split(',')[0].strip()
        if not file_path.startswith('http'):
            return f"https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/{file_path}"
        return file_path
    return None

def verify_receipt_with_vision(receipt_url, tx_amount, tx_date, tx_merchant):
    """Use Gemini Vision to verify receipt matches transaction"""
    api_key = os.environ.get('GEMINI_API_KEY')
    if not api_key:
        return None, "No Gemini API key"

    try:
        # Fetch the image
        resp = requests.get(receipt_url, timeout=30)
        if resp.status_code != 200:
            return "UNCLEAR", f"Could not fetch image: {resp.status_code}"

        image_data = base64.b64encode(resp.content).decode('utf-8')
        content_type = resp.headers.get('content-type', 'image/jpeg')
        if 'png' in content_type.lower():
            mime_type = 'image/png'
        elif 'pdf' in content_type.lower():
            mime_type = 'application/pdf'
        else:
            mime_type = 'image/jpeg'

        # Call Gemini
        url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}"

        prompt = f"""Analyze this receipt image and compare it to the bank transaction:

Bank Transaction:
- Amount: ${abs(float(tx_amount)):.2f}
- Date: {tx_date}
- Merchant: {tx_merchant}

Extract from the receipt:
1. Total amount (look for "Total", "Amount Due", "Grand Total", etc.)
2. Date on receipt
3. Merchant/vendor name

Then determine if this receipt MATCHES the bank transaction:
- Amount must be within $1.00 OR within 20% for tips/gratuity
- Merchant name should reasonably match (variations OK)
- Date within 7 days is acceptable

Respond in this exact JSON format:
{{
    "receipt_total": "XX.XX",
    "receipt_date": "YYYY-MM-DD or null",
    "receipt_merchant": "name",
    "verdict": "VERIFIED" or "MISMATCH" or "UNCLEAR",
    "confidence": 0-100,
    "reasoning": "brief explanation"
}}"""

        payload = {
            "contents": [{
                "parts": [
                    {"text": prompt},
                    {"inline_data": {"mime_type": mime_type, "data": image_data}}
                ]
            }],
            "generationConfig": {"temperature": 0.1}
        }

        api_resp = requests.post(url, json=payload, timeout=60)
        if api_resp.status_code != 200:
            return "UNCLEAR", f"API error: {api_resp.status_code}"

        result = api_resp.json()
        text = result.get('candidates', [{}])[0].get('content', {}).get('parts', [{}])[0].get('text', '')

        # Parse JSON from response
        import re
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group())
            verdict = data.get('verdict', 'UNCLEAR')
            confidence = data.get('confidence', 0)
            reasoning = data.get('reasoning', '')
            receipt_total = data.get('receipt_total', '')
            receipt_merchant = data.get('receipt_merchant', '')
            return verdict, f"{confidence}%|{receipt_total}|{receipt_merchant}|{reasoning}"

        return "UNCLEAR", "Could not parse response"

    except Exception as e:
        return "UNCLEAR", str(e)

def main():
    print("=" * 60)
    print("BUSINESS VISION VERIFICATION - ALL TRANSACTIONS")
    print("=" * 60)

    # Fetch all transactions
    print("\nFetching transactions from database...")
    transactions = fetch_all_transactions()
    print(f"Found {len(transactions)} transactions")

    results = []
    verified = 0
    mismatch = 0
    unclear = 0
    no_receipt = 0

    for i, tx in enumerate(transactions, 1):
        idx = tx['_index']
        date = tx['chase_date']
        amount = tx['chase_amount']
        merchant = tx['chase_description']
        current_status = tx.get('review_status', '')

        print(f"\n[{i}/{len(transactions)}] {date} | ${amount} | {merchant[:40]}")

        receipt_url = get_receipt_url(tx)

        if not receipt_url:
            print("  → No receipt attached")
            results.append({
                'index': idx,
                'date': date,
                'amount': amount,
                'merchant': merchant,
                'receipt_url': '',
                'vision_result': 'NO_RECEIPT',
                'confidence': '',
                'receipt_total': '',
                'receipt_merchant': '',
                'reasoning': 'No receipt attached',
                'current_status': current_status
            })
            no_receipt += 1
            continue

        print(f"  → Verifying: {receipt_url[:60]}...")
        verdict, details = verify_receipt_with_vision(receipt_url, amount, date, merchant)

        # Parse details
        parts = details.split('|') if '|' in details else [details, '', '', details]
        confidence = parts[0] if len(parts) > 0 else ''
        receipt_total = parts[1] if len(parts) > 1 else ''
        receipt_merchant = parts[2] if len(parts) > 2 else ''
        reasoning = parts[3] if len(parts) > 3 else details

        print(f"  → {verdict} ({confidence})")

        if verdict == 'VERIFIED':
            verified += 1
        elif verdict == 'MISMATCH':
            mismatch += 1
            print(f"     ⚠️  {reasoning[:80]}")
        else:
            unclear += 1

        results.append({
            'index': idx,
            'date': date,
            'amount': amount,
            'merchant': merchant,
            'receipt_url': receipt_url,
            'vision_result': verdict,
            'confidence': confidence,
            'receipt_total': receipt_total,
            'receipt_merchant': receipt_merchant,
            'reasoning': reasoning,
            'current_status': current_status
        })

    # Write CSV
    output_file = 'vision_verification_results.csv'
    with open(output_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'index', 'date', 'amount', 'merchant', 'receipt_url',
            'vision_result', 'confidence', 'receipt_total', 'receipt_merchant',
            'reasoning', 'current_status'
        ])
        writer.writeheader()
        writer.writerows(results)

    print("\n" + "=" * 60)
    print("VERIFICATION COMPLETE")
    print("=" * 60)
    print(f"Total: {len(transactions)}")
    print(f"VERIFIED: {verified}")
    print(f"MISMATCH: {mismatch}")
    print(f"UNCLEAR: {unclear}")
    print(f"NO_RECEIPT: {no_receipt}")
    print(f"\nResults saved to: {output_file}")

    # Also write mismatches-only file
    mismatch_file = 'vision_mismatches.csv'
    with open(mismatch_file, 'w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=[
            'index', 'date', 'amount', 'merchant', 'receipt_url',
            'vision_result', 'confidence', 'receipt_total', 'receipt_merchant',
            'reasoning', 'current_status'
        ])
        writer.writeheader()
        for r in results:
            if r['vision_result'] == 'MISMATCH':
                writer.writerows([r])

    print(f"Mismatches saved to: {mismatch_file}")

if __name__ == '__main__':
    main()

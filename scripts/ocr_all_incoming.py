#!/usr/bin/env python3
"""
OCR All Incoming Receipts - Extract full receipt data using OpenAI Vision
==========================================================================

Processes all incoming_receipts that have images but no OCR data.
Extracts: merchant, amount, date, subtotal, tax, tip, payment_method, receipt_number

Usage:
    python3 scripts/ocr_all_incoming.py [--limit 100] [--batch-size 10]
"""

import pymysql
import pymysql.cursors
import json
import os
import sys
import re
import argparse
import time
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / '.env')

# MySQL connection
mysql_url = os.getenv('MYSQL_URL', '')
parts = mysql_url.replace('mysql://', '').split('@')
user_pass = parts[0].split(':')
host_port_db = parts[1].split('/')
host_port = host_port_db[0].split(':')

MYSQL_CONFIG = {
    'host': host_port[0],
    'port': int(host_port[1]),
    'user': user_pass[0],
    'password': user_pass[1],
    'database': host_port_db[1],
    'cursorclass': pymysql.cursors.DictCursor
}

from openai import OpenAI

def get_openai_client():
    api_key = os.getenv('OPENAI_API_KEY')
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")
    return OpenAI(api_key=api_key)

def extract_receipt_data_with_vision(image_url, subject=None):
    """Use OpenAI Vision to extract full receipt data from image"""
    client = get_openai_client()

    context = f"Email subject: {subject}" if subject else ""

    prompt = f"""Analyze this receipt image and extract ALL information you can find.
{context}

Look for and extract:
1. MERCHANT NAME - The store/business name (NOT Apple for Apple receipts - find the actual merchant like "App Store", "Spotify", etc.)
2. TOTAL AMOUNT - The final charged amount (look for "Total", "Grand Total", "Amount Charged", "You paid")
3. DATE - Transaction date (in YYYY-MM-DD format if possible)
4. SUBTOTAL - Pre-tax amount if shown
5. TAX - Tax amount if shown
6. TIP - Tip/gratuity amount if shown
7. PAYMENT METHOD - Card type and last 4 digits if shown (e.g., "Visa ***1234")
8. RECEIPT NUMBER - Order/receipt/confirmation number if shown
9. LINE ITEMS - List of items purchased with names and prices (VERY IMPORTANT - extract the specific product names!)

IMPORTANT RULES:
- For Apple receipts, the merchant is the APP/SERVICE name (Spotify, YouTube Premium, iCloud, etc.), NOT "Apple"
- For Uber/Lyft receipts, merchant is "Uber" or "Lyft"
- Amount should be a number only (no $ sign)
- Date format: YYYY-MM-DD
- LINE ITEMS are crucial - extract the actual product names like "USB-C to MagSafe 3 Cable" not just "Apple product"
- If you cannot find a field, use null

Return ONLY a valid JSON object like:
{{
    "merchant": "Store Name",
    "amount": 29.99,
    "date": "2024-12-10",
    "subtotal": 27.99,
    "tax": 2.00,
    "tip": null,
    "payment_method": "Visa ***1234",
    "receipt_number": "ORD-12345",
    "line_items": [
        {{"name": "USB-C to MagSafe 3 Cable (2m)", "price": 27.99}},
        {{"name": "Lightning Cable", "price": 19.99}}
    ]
}}

Do not include any other text, just the JSON object."""

    try:
        response = client.chat.completions.create(
            model="gpt-4o",  # Using full gpt-4o for better accuracy
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {"type": "image_url", "image_url": {"url": image_url, "detail": "high"}}
                    ]
                }
            ],
            max_tokens=500,
            temperature=0
        )

        result = response.choices[0].message.content.strip()

        # Handle markdown code blocks
        if '```' in result:
            match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', result, re.DOTALL)
            if match:
                result = match.group(1)

        # Clean up any leading/trailing non-JSON content
        result = result.strip()
        if not result.startswith('{'):
            # Find the first { and last }
            start = result.find('{')
            end = result.rfind('}')
            if start != -1 and end != -1:
                result = result[start:end+1]

        data = json.loads(result)
        return data

    except json.JSONDecodeError as e:
        print(f"    JSON parse error: {e}")
        print(f"    Raw response: {result[:200]}...")
        return None
    except Exception as e:
        print(f"    Vision error: {e}")
        return None

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=100, help='Max receipts to process')
    parser.add_argument('--batch-size', type=int, default=10, help='Batch size for commits')
    parser.add_argument('--apple-only', action='store_true', help='Only process Apple receipts')
    parser.add_argument('--refresh-items', action='store_true', help='Re-OCR receipts that have OCR but no line_items')
    args = parser.parse_args()

    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()

    # Get receipts to process
    if args.refresh_items:
        # Re-OCR receipts that have OCR data but no line_items
        print("Mode: Refreshing OCR for receipts missing line_items...")
        cursor.execute('''
            SELECT id, subject, receipt_image_url, from_email, amount
            FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
            AND receipt_image_url != ''
            AND ocr_merchant IS NOT NULL
            AND (ocr_line_items IS NULL OR ocr_line_items = '[]' OR ocr_line_items = 'null')
            ORDER BY received_date DESC
            LIMIT %s
        ''', (args.limit,))
    elif args.apple_only:
        cursor.execute('''
            SELECT id, subject, receipt_image_url, from_email, amount
            FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
            AND receipt_image_url != ''
            AND ocr_amount IS NULL
            AND (subject LIKE '%%Apple%%' OR from_email LIKE '%%apple%%')
            ORDER BY received_date DESC
            LIMIT %s
        ''', (args.limit,))
    else:
        cursor.execute('''
            SELECT id, subject, receipt_image_url, from_email, amount
            FROM incoming_receipts
            WHERE receipt_image_url IS NOT NULL
            AND receipt_image_url != ''
            AND ocr_amount IS NULL
            ORDER BY received_date DESC
            LIMIT %s
        ''', (args.limit,))

    rows = cursor.fetchall()
    print(f"Processing {len(rows)} receipts for OCR extraction...")
    print("=" * 60)

    success = 0
    failed = 0

    for i, row in enumerate(rows):
        receipt_id = row['id']
        subject = row['subject'] or 'Unknown'
        image_url = row['receipt_image_url']
        email_amount = row['amount']

        print(f"\n[{i+1}/{len(rows)}] {subject[:60]}...")
        if email_amount:
            email_amount = float(email_amount)
            print(f"    Email amount: ${email_amount:.2f}")

        if not image_url:
            print("    No image URL")
            failed += 1
            continue

        # Extract receipt data using Vision
        data = extract_receipt_data_with_vision(image_url, subject)

        if data:
            merchant = data.get('merchant')
            amount = data.get('amount')
            date = data.get('date')
            subtotal = data.get('subtotal')
            tax = data.get('tax')
            tip = data.get('tip')
            payment_method = data.get('payment_method')
            receipt_number = data.get('receipt_number')

            # Validate and convert types
            if amount is not None:
                try:
                    amount = float(amount)
                except:
                    amount = None

            if subtotal is not None:
                try:
                    subtotal = float(subtotal)
                except:
                    subtotal = None

            if tax is not None:
                try:
                    tax = float(tax)
                except:
                    tax = None

            if tip is not None:
                try:
                    tip = float(tip)
                except:
                    tip = None

            # Get line items
            line_items = data.get('line_items')
            line_items_json = json.dumps(line_items) if line_items else None

            # Update database
            cursor.execute('''
                UPDATE incoming_receipts
                SET ocr_merchant = %s,
                    ocr_amount = %s,
                    ocr_date = %s,
                    ocr_subtotal = %s,
                    ocr_tax = %s,
                    ocr_tip = %s,
                    ocr_payment_method = %s,
                    ocr_receipt_number = %s,
                    ocr_line_items = %s,
                    ocr_method = 'gpt-4o',
                    ocr_extracted_at = NOW()
                WHERE id = %s
            ''', (merchant, amount, date, subtotal, tax, tip, payment_method, receipt_number, line_items_json, receipt_id))

            conn.commit()

            print(f"    Merchant: {merchant}")
            print(f"    OCR Amount: ${amount:.2f}" if amount else "    OCR Amount: N/A")
            if email_amount and amount:
                diff = abs(email_amount - amount)
                if diff > 0.01:
                    print(f"    DIFF: ${diff:.2f}")
            print(f"    Date: {date}")
            if tip:
                print(f"    Tip: ${tip:.2f}")
            if line_items:
                item_names = [i.get('name', '')[:40] for i in line_items[:3]]
                print(f"    Items: {', '.join(item_names)}")
            success += 1
        else:
            print(f"    Could not extract OCR data")
            failed += 1

        # Rate limiting - be gentle with the API
        if (i + 1) % args.batch_size == 0:
            print(f"\n--- Batch checkpoint: {success} success, {failed} failed ---")
            time.sleep(1)

    conn.close()
    print(f"\n{'='*60}")
    print(f"Done! Success: {success}, Failed: {failed}")

    # Check remaining
    conn = pymysql.connect(**MYSQL_CONFIG)
    cursor = conn.cursor()
    cursor.execute('''
        SELECT COUNT(*) as remaining
        FROM incoming_receipts
        WHERE receipt_image_url IS NOT NULL
        AND receipt_image_url != ''
        AND ocr_amount IS NULL
    ''')
    remaining = cursor.fetchone()['remaining']
    conn.close()
    print(f"Remaining: {remaining} receipts without OCR")

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""
Test Railway MySQL and /csv endpoint to diagnose data display issue
"""

import os
import pymysql
from urllib.parse import urlparse
import requests

# MySQL connection - use environment variable
MYSQL_URL = os.environ.get('MYSQL_URL', 'mysql://root:password@localhost:3306/railway')
RAILWAY_URL = os.environ.get('RAILWAY_URL', 'https://tallyups.com')

def test_mysql():
    print("=" * 80)
    print("TEST 1: Direct MySQL Query")
    print("=" * 80)

    url = urlparse(MYSQL_URL)
    conn = pymysql.connect(
        host=url.hostname,
        port=url.port,
        user=url.username,
        password=url.password,
        database=url.path[1:]
    )
    cursor = conn.cursor(pymysql.cursors.DictCursor)

    cursor.execute('SELECT COUNT(*) as count FROM transactions')
    count = cursor.fetchone()['count']
    print(f"✓ Total transactions in MySQL: {count}")

    cursor.execute('SELECT * FROM transactions LIMIT 1')
    first = cursor.fetchone()

    if first:
        print(f"\n📝 First transaction fields:")
        print(f"  chase_date: {first.get('chase_date')}")
        print(f"  chase_description: {first.get('chase_description')}")
        print(f"  chase_amount: {first.get('chase_amount')}")
        print(f"  mi_merchant: {first.get('mi_merchant')}")
        print(f"  mi_category: {first.get('mi_category')}")
        print(f"  business_type: {first.get('business_type')}")
        print(f"  receipt_url: {first.get('receipt_url')}")

        print(f"\n🔑 All field names ({len(first.keys())} total):")
        for i, key in enumerate(list(first.keys())[:20]):
            print(f"  {i+1}. {key}")

    cursor.close()
    conn.close()

def test_railway_endpoint():
    print("\n" + "=" * 80)
    print("TEST 2: Railway /csv Endpoint")
    print("=" * 80)

    try:
        response = requests.get(f"{RAILWAY_URL}/csv", timeout=10)
        print(f"  Status Code: {response.status_code}")
        print(f"  Content-Type: {response.headers.get('Content-Type')}")
        print(f"  Content-Length: {len(response.text)} bytes")

        if response.status_code == 200:
            try:
                data = response.json()
                if isinstance(data, list):
                    print(f"  ✓ Got {len(data)} transactions")

                    if len(data) > 0:
                        first = data[0]
                        print(f"\n📝 First transaction from API:")
                        print(f"  Keys ({len(first.keys())} total): {list(first.keys())[:10]}...")

                        # Check if capitalized keys exist
                        print(f"\n🎯 Checking for expected frontend keys:")
                        print(f"  'Chase Date': {'✓' if 'Chase Date' in first else '✗'}")
                        print(f"  'Chase Description': {'✓' if 'Chase Description' in first else '✗'}")
                        print(f"  'Chase Amount': {'✓' if 'Chase Amount' in first else '✗'}")
                        print(f"  'MI Merchant': {'✓' if 'MI Merchant' in first else '✗'}")

                        # Check if lowercase keys exist
                        print(f"\n  'chase_date': {'✓' if 'chase_date' in first else '✗'}")
                        print(f"  'chase_description': {'✓' if 'chase_description' in first else '✗'}")
                        print(f"  'chase_amount': {'✓' if 'chase_amount' in first else '✗'}")
                        print(f"  'mi_merchant': {'✓' if 'mi_merchant' in first else '✗'}")
                else:
                    print(f"  ⚠️ Unexpected response type: {type(data)}")
                    print(f"  Data: {str(data)[:200]}")
            except ValueError as e:
                print(f"  ❌ JSON parse error: {e}")
                print(f"  Raw response: {response.text[:500]}")
        else:
            print(f"  ❌ Non-200 status code")
            print(f"  Response: {response.text[:500]}")
    except Exception as e:
        print(f"  ❌ Request failed: {e}")

if __name__ == '__main__':
    test_mysql()
    test_railway_endpoint()
    print("\n" + "=" * 80)
    print("✅ Diagnostics complete")
    print("=" * 80)

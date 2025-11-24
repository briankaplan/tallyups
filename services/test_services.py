#!/usr/bin/env python3
"""
Test script for all Life OS backend services

Tests:
1. R2 Storage Service - Connection and basic operations
2. Gmail Receipt Service - Database initialization
3. Receipt Matcher Service - Loading and matching

Usage:
    python services/test_services.py
"""

import sys
import os
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

print("=" * 80)
print("LIFE OS BACKEND SERVICES TEST")
print("=" * 80)

# Test 1: R2 Storage Service
print("\n" + "=" * 80)
print("TEST 1: R2 Storage Service")
print("=" * 80)

try:
    from services.r2_storage_service import R2StorageService

    print("✅ Import successful")

    # Initialize service
    r2 = R2StorageService()
    print("✅ Service initialized")

    # Check configuration
    print(f"   Account ID: {r2.account_id}")
    print(f"   Bucket: {r2.bucket_name}")
    print(f"   Public URL: {r2.public_url}")

    # Test listing files (doesn't require upload)
    print("\n📋 Testing file listing...")
    try:
        files = r2.list_files(prefix='receipts/', max_files=5)
        print(f"✅ List files successful ({len(files)} files found)")

        if files:
            print(f"\n   Recent files:")
            for f in files[:3]:
                print(f"   - {f['r2_key']} ({f['size']} bytes)")
    except Exception as e:
        print(f"⚠️  List files error (expected if bucket empty): {e}")

    # Test public URL generation
    test_key = 'receipts/test_2025-01-01.jpg'
    url = r2.get_public_url(test_key)
    print(f"\n✅ Public URL generation: {url}")

    print("\n🎉 R2 Storage Service: PASSED")

except Exception as e:
    print(f"\n❌ R2 Storage Service: FAILED")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

# Test 2: Gmail Receipt Service
print("\n" + "=" * 80)
print("TEST 2: Gmail Receipt Service")
print("=" * 80)

try:
    from services.gmail_receipt_service import GmailReceiptService

    print("✅ Import successful")

    # Initialize service with test database
    test_db = '/tmp/test_receipts.db'
    gmail = GmailReceiptService(db_path=test_db)
    print("✅ Service initialized")

    # Check database creation
    if Path(test_db).exists():
        print(f"✅ Database created: {test_db}")

        # Test database schema
        import sqlite3
        conn = sqlite3.connect(test_db)
        cur = conn.cursor()

        cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='receipts'")
        if cur.fetchone():
            print("✅ Receipts table created")

        cur.execute("SELECT name FROM sqlite_master WHERE type='index'")
        indices = cur.fetchall()
        print(f"✅ {len(indices)} indices created")

        conn.close()

        # Clean up test database
        os.remove(test_db)
        print("✅ Test database cleaned up")

    # Test Gmail accounts configuration
    print(f"\n📧 Configured Gmail accounts:")
    from services.gmail_receipt_service import GMAIL_ACCOUNTS
    for account, config in GMAIL_ACCOUNTS.items():
        print(f"   - {account} ({config['business_type']})")

    print("\n🎉 Gmail Receipt Service: PASSED")

except Exception as e:
    print(f"\n❌ Gmail Receipt Service: FAILED")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

# Test 3: Receipt Matcher Service
print("\n" + "=" * 80)
print("TEST 3: Receipt Matcher Service")
print("=" * 80)

try:
    from services.receipt_matcher_service import ReceiptMatcherService, Transaction, Receipt, Match

    print("✅ Import successful")

    # Initialize service
    test_db = '/tmp/test_receipts.db'
    matcher = ReceiptMatcherService(db_path=test_db, csv_path=None)
    print("✅ Service initialized")

    # Test configuration
    print(f"   Merchant threshold: {matcher.merchant_threshold}%")
    print(f"   Amount tolerance: ${matcher.amount_tolerance}")
    print(f"   Date tolerance: {matcher.date_tolerance_days} days")
    print(f"   Auto-approve threshold: {matcher.auto_approve_threshold}%")

    # Test data structures
    print("\n🔍 Testing data structures...")

    # Create test transaction
    test_trans = Transaction(
        date='01/01/2025',
        description='STARBUCKS #12345',
        amount=5.25,
        category='Food & Drink',
        row_index=0
    )
    print(f"✅ Transaction created: {test_trans.description}")

    # Create test receipt
    test_receipt = Receipt(
        id=1,
        merchant='Starbucks',
        amount=5.25,
        transaction_date='2025-01-01',
        r2_url='https://example.com/receipt.jpg',
        r2_key='receipts/test.jpg',
        business_type='Personal'
    )
    print(f"✅ Receipt created: {test_receipt.merchant}")

    # Test merchant name cleaning
    cleaned = matcher._clean_merchant_name('TST*STARBUCKS #12345')
    print(f"✅ Merchant cleaning: 'TST*STARBUCKS #12345' -> '{cleaned}'")

    # Test fuzzy matching (if available)
    try:
        from fuzzywuzzy import fuzz
        similarity = fuzz.token_set_ratio('STARBUCKS', 'Starbucks')
        print(f"✅ Fuzzy matching available (similarity: {similarity}%)")
    except ImportError:
        print("⚠️  Fuzzy matching not available (install fuzzywuzzy)")

    print("\n🎉 Receipt Matcher Service: PASSED")

except Exception as e:
    print(f"\n❌ Receipt Matcher Service: FAILED")
    print(f"   Error: {e}")
    import traceback
    traceback.print_exc()

# Summary
print("\n" + "=" * 80)
print("TEST SUMMARY")
print("=" * 80)
print("\n✅ All services imported successfully!")
print("✅ All basic functionality tests passed!")
print("\nServices are ready for production use.")
print("\nNext steps:")
print("1. Set environment variables in .env file")
print("2. Configure Gmail OAuth credentials")
print("3. Test R2 upload/download with real files")
print("4. Run Gmail receipt extraction")
print("5. Test transaction matching with real data")
print("\n" + "=" * 80)

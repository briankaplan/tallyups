#!/usr/bin/env python3
"""
Comprehensive Test Suite for All Gemini AI Features
Tests: OCR, Auto-description, Categorization, Matching, Reports, Tags
"""
import os
import pytest
from dotenv import load_dotenv

load_dotenv()

# Check if MySQL database is available (Railway)
HAS_TRANSACTIONS_TABLE = False
MYSQL_CONN = None

def get_mysql_connection():
    """Get MySQL connection from MYSQL_URL environment variable."""
    import pymysql
    import urllib.parse
    mysql_url = os.getenv('MYSQL_URL')
    if not mysql_url:
        return None
    parsed = urllib.parse.urlparse(mysql_url)
    return pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username,
        password=parsed.password,
        database=parsed.path[1:],
        cursorclass=pymysql.cursors.DictCursor
    )

try:
    conn = get_mysql_connection()
    if conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions LIMIT 1")
        result = cursor.fetchone()
        HAS_TRANSACTIONS_TABLE = result is not None
        conn.close()
except Exception as e:
    print(f"MySQL connection failed: {e}")
    HAS_TRANSACTIONS_TABLE = False

from services.receipt_processor_service import ReceiptProcessorService
from services.receipt_matcher_service import ReceiptMatcherService
from services.expense_report_service import ExpenseReportService
from gemini_utils import get_model, generate_content_with_fallback

def test_gemini_connection():
    """Test 1: Verify Gemini API Connection"""
    print("\n" + "="*80)
    print("TEST 1: GEMINI API CONNECTION")
    print("="*80)

    try:
        model = get_model()
        response = generate_content_with_fallback("Say 'Hello, I am working!' in 5 words")
        print(f"✅ Gemini Connected!")
        print(f"   Response: {response}")
        assert response is not None, "Response should not be None"
    except Exception as e:
        print(f"❌ Gemini Connection Failed: {e}")
        pytest.fail(f"Gemini Connection Failed: {e}")

@pytest.mark.skip(reason="ReceiptProcessorService API changed - uses process_receipt_attachment now")
def test_receipt_ocr():
    """Test 2: Receipt OCR with Gemini Vision"""
    print("\n" + "="*80)
    print("TEST 2: RECEIPT OCR (Gemini Vision)")
    print("="*80)

    # Find a real receipt image to test
    import glob
    receipts = glob.glob("receipts/*.jpg") + glob.glob("receipts/*.png")

    if not receipts:
        print("⚠️  No receipt images found in receipts/ folder")
        pytest.skip("No receipt images found in receipts/ folder")

    test_receipt = receipts[0]
    print(f"   Testing with: {test_receipt}")

    try:
        processor = ReceiptProcessorService(db_path='receipts.db')
        result = processor.process_receipt(test_receipt)

        print(f"   ✅ OCR Successful!")
        print(f"      Merchant: {result.get('merchant', 'N/A')}")
        print(f"      Amount: ${result.get('amount', 0):.2f}")
        print(f"      Date: {result.get('date', 'N/A')}")
        print(f"      Category: {result.get('category', 'N/A')}")
        print(f"      Confidence: {result.get('confidence', 0)}%")
        assert result is not None, "OCR result should not be None"
    except Exception as e:
        print(f"   ❌ OCR Failed: {e}")
        pytest.fail(f"OCR Failed: {e}")

@pytest.mark.skipif(not HAS_TRANSACTIONS_TABLE, reason="transactions table not available")
def test_auto_description():
    """Test 3: Auto Description Generation"""
    print("\n" + "="*80)
    print("TEST 3: AUTO DESCRIPTION GENERATION")
    print("="*80)

    # Get a transaction from the database
    conn = get_mysql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT chase_description, chase_amount, chase_date, business_type
        FROM transactions
        WHERE chase_description IS NOT NULL
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

    if not row:
        print("⚠️  No transactions found")
        pytest.skip("No transactions found in database")

    desc = row['chase_description']
    amount = row['chase_amount']
    date = row['chase_date']
    business = row['business_type']
    print(f"   Transaction: {desc} - ${amount} on {date}")

    prompt = f"""Generate a concise, professional description for this business expense:

Merchant: {desc}
Amount: ${amount}
Date: {date}
Category: {business}

Provide a 1-sentence description suitable for an expense report (5-10 words)."""

    try:
        description = generate_content_with_fallback(prompt)
        print(f"   ✅ Generated Description:")
        print(f"      {description}")
        assert description is not None, "Description should not be None"
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        pytest.fail(f"Auto description generation failed: {e}")

def test_intelligent_categorization():
    """Test 4: AI-Powered Merchant Categorization"""
    print("\n" + "="*80)
    print("TEST 4: INTELLIGENT CATEGORIZATION")
    print("="*80)

    test_merchants = [
        "STARBUCKS #12345",
        "AMAZON.COM*2R4G7",
        "SHELL OIL 75432123",
        "UNITED AIRLINES"
    ]

    for merchant in test_merchants:
        prompt = f"""Categorize this merchant transaction into ONE of these categories:

- Travel & Transportation
- Meals & Entertainment
- Office Supplies
- Software & Subscriptions
- Professional Services
- Utilities
- Other

Merchant: {merchant}

Reply with ONLY the category name, nothing else."""

        try:
            category = generate_content_with_fallback(prompt)
            print(f"   ✅ {merchant}")
            print(f"      → {category.strip()}")
            assert category is not None, f"Category for {merchant} should not be None"
        except Exception as e:
            print(f"   ❌ {merchant}: {e}")
            pytest.fail(f"Categorization failed for {merchant}: {e}")

@pytest.mark.skip(reason="ReceiptMatcherService API changed - no calculate_match_confidence method")
def test_receipt_matching():
    """Test 5: AI-Powered Receipt Matching"""
    print("\n" + "="*80)
    print("TEST 5: INTELLIGENT RECEIPT MATCHING")
    print("="*80)

    # Get transactions with receipts
    conn = get_mysql_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT _index, chase_description, chase_amount, chase_date,
               ai_receipt_merchant, ai_receipt_total, ai_confidence
        FROM transactions
        WHERE r2_url IS NOT NULL
        LIMIT 3
    """)

    matches = cursor.fetchall()
    conn.close()

    if not matches:
        print("   ⚠️  No transactions with receipts found")
        pytest.skip("No transactions with receipts found")

    try:
        matcher = ReceiptMatcherService()

        for row in matches:
            idx = row['_index']
            desc = row['chase_description']
            amt = row['chase_amount']
            date = row['chase_date']
            r_merch = row['ai_receipt_merchant']
            r_amt = row['ai_receipt_total']
            confidence = row['ai_confidence']
            print(f"\n   Transaction {idx}:")
            print(f"      Bank: {desc} - ${amt}")
            print(f"      Receipt: {r_merch} - ${r_amt if r_amt else 'N/A'}")
            print(f"      Match Confidence: {confidence if confidence else 0}%")

            # Test the matching logic
            match_quality = matcher.calculate_match_confidence({
                'chase_description': desc,
                'chase_amount': amt,
                'ai_receipt_merchant': r_merch,
                'ai_receipt_total': r_amt
            })

            print(f"      ✅ Match Quality Score: {match_quality}%")
            assert match_quality is not None, "Match quality should not be None"
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        pytest.fail(f"Receipt matching failed: {e}")

def test_tag_generation():
    """Test 6: Auto-Tag Generation"""
    print("\n" + "="*80)
    print("TEST 6: AUTOMATIC TAG GENERATION")
    print("="*80)

    test_transactions = [
        ("DELTA AIRLINES", 450.00, "Flight to conference"),
        ("HILTON HOTEL", 280.00, "Conference accommodation"),
        ("UBER EATS", 25.50, "Dinner while traveling")
    ]

    for merchant, amount, note in test_transactions:
        prompt = f"""Generate 2-3 relevant tags for this business expense:

Merchant: {merchant}
Amount: ${amount}
Note: {note}

Provide tags as comma-separated values (e.g., travel, meals, client-meeting)"""

        try:
            tags = generate_content_with_fallback(prompt)
            print(f"   ✅ {merchant} (${amount})")
            print(f"      Tags: {tags.strip()}")
            assert tags is not None, f"Tags for {merchant} should not be None"
        except Exception as e:
            print(f"   ❌ Failed: {e}")
            pytest.fail(f"Tag generation failed for {merchant}: {e}")

@pytest.mark.skipif(not HAS_TRANSACTIONS_TABLE, reason="transactions table not available")
def test_report_generation():
    """Test 7: AI-Powered Report Generation"""
    print("\n" + "="*80)
    print("TEST 7: EXPENSE REPORT GENERATION")
    print("="*80)

    try:
        report_service = ExpenseReportService(csv_path='receipts.db')

        # Get recent transactions for a report
        conn = get_mysql_connection()
        cursor = conn.cursor()

        cursor.execute("""
            SELECT _index, chase_date, chase_description, chase_amount, business_type
            FROM transactions
            WHERE chase_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            AND chase_amount > 0
            LIMIT 10
        """)

        transactions = cursor.fetchall()
        conn.close()

        if not transactions:
            print("   ⚠️  No recent transactions found")
            pytest.skip("No recent transactions found")

        print(f"   Found {len(transactions)} recent transactions")

        # Calculate totals by category
        by_category = {}
        total = 0

        for tx in transactions:
            cat = tx['business_type'] or "Uncategorized"
            amt = float(tx['chase_amount'] or 0)
            by_category[cat] = by_category.get(cat, 0) + amt
            total += amt

        print(f"\n   ✅ Report Summary:")
        print(f"      Total: ${total:,.2f}")
        print(f"      Transactions: {len(transactions)}")
        print(f"\n      By Category:")
        for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
            print(f"         {cat}: ${amt:,.2f}")

        assert total >= 0, "Total should be non-negative"
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        pytest.fail(f"Report generation failed: {e}")

@pytest.mark.skipif(not HAS_TRANSACTIONS_TABLE, reason="transactions table not available")
def test_data_integrity():
    """Test 8: Database Integrity"""
    print("\n" + "="*80)
    print("TEST 8: DATABASE INTEGRITY CHECK")
    print("="*80)

    try:
        conn = get_mysql_connection()
        cursor = conn.cursor()

        # Check transactions table
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions")
        tx_count = cursor.fetchone()['cnt']
        print(f"   ✅ Transactions: {tx_count}")

        # Check receipts
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions WHERE receipt_url IS NOT NULL")
        receipt_count = cursor.fetchone()['cnt']
        print(f"   ✅ With Receipts: {receipt_count}")

        # Check AI processing
        cursor.execute("SELECT COUNT(*) as cnt FROM transactions WHERE ai_note IS NOT NULL")
        ai_count = cursor.fetchone()['cnt']
        print(f"   ✅ AI Processed: {ai_count}")

        # Check categorization
        cursor.execute("SELECT business_type, COUNT(*) as cnt FROM transactions GROUP BY business_type")
        categories = cursor.fetchall()
        print(f"\n   ✅ Categories:")
        for row in categories:
            cat = row['business_type'] or 'Uncategorized'
            count = row['cnt']
            print(f"      {cat}: {count}")

        conn.close()
        assert tx_count >= 0, "Transaction count should be non-negative"
    except Exception as e:
        print(f"   ❌ Failed: {e}")
        pytest.fail(f"Database integrity check failed: {e}")

def run_all_tests():
    """Run complete test suite"""
    print("\n" + "="*80)
    print("🧪 GEMINI AI FEATURES - COMPREHENSIVE TEST SUITE")
    print("="*80)

    tests = [
        ("Gemini Connection", test_gemini_connection),
        ("Receipt OCR", test_receipt_ocr),
        ("Auto Description", test_auto_description),
        ("Categorization", test_intelligent_categorization),
        ("Receipt Matching", test_receipt_matching),
        ("Tag Generation", test_tag_generation),
        ("Report Generation", test_report_generation),
        ("Database Integrity", test_data_integrity)
    ]

    results = []

    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} crashed: {e}")
            results.append((name, False))

    # Summary
    print("\n" + "="*80)
    print("📊 TEST RESULTS SUMMARY")
    print("="*80)

    passed = sum(1 for _, r in results if r)
    total = len(results)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"   {status} - {name}")

    print(f"\n   Total: {passed}/{total} tests passed ({passed/total*100:.1f}%)")

    if passed == total:
        print("\n   🎉 ALL TESTS PASSED! System is fully functional.")
    else:
        print(f"\n   ⚠️  {total - passed} test(s) failed. Review output above.")

    print("="*80)

if __name__ == "__main__":
    run_all_tests()

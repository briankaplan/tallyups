#!/usr/bin/env python3
"""
Complete Integration Example for Life OS Backend Services

This script demonstrates how to use all three services together in a complete workflow:
1. Extract receipts from Gmail
2. Upload receipt attachments to R2
3. Match transactions to receipts
4. Generate report

Usage:
    python services/integration_example.py

Environment Variables Required:
    - R2 credentials (CLOUDFLARE_ACCOUNT_ID, R2_ACCESS_KEY_ID, etc.)
    - Gmail OAuth credentials (GMAIL_CREDENTIALS_*, GMAIL_TOKEN_*)
"""

import sys
import os
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from services.r2_storage_service import R2StorageService
from services.gmail_receipt_service import GmailReceiptService
from services.receipt_matcher_service import ReceiptMatcherService


def main():
    """
    Complete workflow demonstration
    """
    print("=" * 80)
    print("LIFE OS BACKEND SERVICES - INTEGRATION EXAMPLE")
    print("=" * 80)

    # Configuration
    DB_PATH = 'receipts.db'
    CSV_PATH = 'receipt-system/data/Chase_Activity_MATCHED.csv'

    # Check if CSV exists
    if not Path(CSV_PATH).exists():
        print(f"\n⚠️  CSV file not found: {CSV_PATH}")
        print("   Using example workflow without matching")
        CSV_PATH = None

    # Step 1: Initialize Services
    print("\n" + "=" * 80)
    print("STEP 1: Initialize Services")
    print("=" * 80)

    print("\n1️⃣  Initializing R2 Storage Service...")
    r2 = R2StorageService()
    print(f"   ✅ R2 connected to bucket: {r2.bucket_name}")

    print("\n2️⃣  Initializing Gmail Receipt Service...")
    gmail = GmailReceiptService(db_path=DB_PATH)
    print(f"   ✅ Gmail service ready (database: {DB_PATH})")

    if CSV_PATH:
        print("\n3️⃣  Initializing Receipt Matcher Service...")
        matcher = ReceiptMatcherService(db_path=DB_PATH, csv_path=CSV_PATH)
        print(f"   ✅ Matcher ready (CSV: {CSV_PATH})")

    # Step 2: Check R2 Storage Status
    print("\n" + "=" * 80)
    print("STEP 2: Check R2 Storage Status")
    print("=" * 80)

    print("\n📊 Checking existing receipts in R2...")
    existing_files = r2.list_files(prefix='receipts/', max_files=10)

    if existing_files:
        print(f"   ✅ Found {len(existing_files)} receipts in R2:")
        for i, file in enumerate(existing_files[:5], 1):
            size_kb = file['size'] / 1024
            print(f"      {i}. {file['r2_key']} ({size_kb:.1f} KB)")

        if len(existing_files) > 5:
            print(f"      ... and {len(existing_files) - 5} more")
    else:
        print("   ⚠️  No receipts found in R2 (expected for new setup)")

    # Step 3: Gmail Receipt Extraction (Demo)
    print("\n" + "=" * 80)
    print("STEP 3: Gmail Receipt Extraction")
    print("=" * 80)

    print("\n📧 Gmail Receipt Extraction Demo")
    print("   This would search your Gmail accounts for receipts:")
    print("   - brian@downhome.com")
    print("   - kaplan.brian@gmail.com")
    print("   - brian@musiccityrodeo.com")
    print("\n   To run actual extraction, authenticate Gmail accounts first:")
    print("   $ python services/gmail_receipt_service.py receipts.db")

    # Uncomment to run actual Gmail extraction (requires OAuth setup):
    # print("\n🔍 Searching Gmail for receipts...")
    # stats = gmail.search_and_save_receipts(days_back=30, max_results=50)
    # print(f"\n📊 Gmail Extraction Results:")
    # print(f"   Total found: {stats['total_found']}")
    # print(f"   Total saved: {stats['total_saved']}")
    # print(f"   Duplicates: {stats['total_duplicates']}")

    # Step 4: Receipt Matching (if CSV available)
    if CSV_PATH and Path(CSV_PATH).exists():
        print("\n" + "=" * 80)
        print("STEP 4: Receipt Matching")
        print("=" * 80)

        print("\n📄 Loading transactions from CSV...")
        transactions = matcher.load_transactions_from_csv()
        print(f"   ✅ Loaded {len(transactions)} transactions")

        print("\n📊 Loading receipts from database...")
        receipts = matcher.load_receipts_from_db()
        print(f"   ✅ Loaded {len(receipts)} receipts")

        if receipts:
            print("\n🔍 Matching transactions to receipts...")
            results = matcher.match_all_transactions()

            print("\n" + "=" * 80)
            print("MATCHING RESULTS")
            print("=" * 80)

            matcher.print_statistics()

            # Show sample matches
            if results['matches']:
                print("\n📋 Sample Matches (Top 5):")
                for i, match in enumerate(results['matches'][:5], 1):
                    print(f"\n   {i}. {match.transaction.description}")
                    print(f"      Amount: ${match.transaction.amount:.2f}")
                    print(f"      Matched to: {match.receipt.merchant}")
                    print(f"      Receipt: ${match.receipt.amount:.2f}")
                    print(f"      Confidence: {match.confidence_score}%")
                    print(f"      Status: {'🟢 AUTO-APPROVED' if match.auto_approve else '🟡 MANUAL REVIEW'}")

            # Export results
            if results['matches']:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                export_path = f'match_report_{timestamp}.csv'

                print(f"\n💾 Exporting matches to: {export_path}")
                matcher.export_matches_to_csv(results['matches'], export_path)
                print(f"   ✅ Export complete")

        else:
            print("\n   ⚠️  No receipts in database yet")
            print("   Run Gmail extraction first to populate receipts")

    # Step 5: Summary and Next Steps
    print("\n" + "=" * 80)
    print("SUMMARY & NEXT STEPS")
    print("=" * 80)

    print("\n✅ Integration Example Complete!")
    print("\nWhat's Working:")
    print("   ✅ R2 Storage Service - Connected and operational")
    print("   ✅ Gmail Receipt Service - Database initialized")
    if CSV_PATH:
        print("   ✅ Receipt Matcher Service - Ready to match")

    print("\nNext Steps to Complete Setup:")
    print("\n1. Configure Gmail OAuth:")
    print("   - Download credentials from Google Cloud Console")
    print("   - Place in credentials/ directory")
    print("   - Run: python services/gmail_receipt_service.py receipts.db")

    print("\n2. Extract receipts from Gmail:")
    print("   - Authenticate each Gmail account")
    print("   - Run extraction for last 30-60 days")
    print("   - Receipts will be saved to database")

    print("\n3. Upload receipt attachments to R2:")
    print("   - Use receipt_processor_service.py to download & upload")
    print("   - Attachments will be converted to JPG")
    print("   - Public URLs will be stored in database")

    print("\n4. Match transactions to receipts:")
    print("   - Export bank transactions to CSV")
    print("   - Run matcher with fuzzy matching")
    print("   - Auto-approve high-confidence matches")
    print("   - Review low-confidence matches manually")

    print("\n5. Generate expense reports:")
    print("   - Export matched transactions")
    print("   - Include receipt URLs")
    print("   - Submit to accounting/reimbursement")

    print("\n" + "=" * 80)
    print("For more information, see:")
    print("   services/README.md")
    print("=" * 80)


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  Interrupted by user")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

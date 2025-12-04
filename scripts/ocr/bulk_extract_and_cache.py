#!/usr/bin/env python3
"""
Bulk Receipt Extraction and Caching
Pre-extracts all receipts with Gemini and caches results in MySQL.
Run this script to pre-populate the cache for fast bulk verification.

Usage:
    python bulk_extract_and_cache.py [--limit 100] [--skip-cached]
"""

import os
import sys
import time
import argparse
from pathlib import Path
from datetime import datetime

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from receipt_ocr_service import ReceiptOCRService, get_ocr_cache
from db_mysql import get_mysql_db


def get_receipts_needing_extraction(limit: int = 100, skip_cached: bool = True) -> list:
    """Get receipt file paths that need OCR extraction"""
    db = get_mysql_db()
    if not db:
        print("ERROR: MySQL not available")
        return []

    conn = db.get_connection()
    cursor = conn.cursor()

    # Get receipts with file paths that need verification
    cursor.execute("""
        SELECT transaction_id, description, amount, date, receipt_file_path
        FROM receipt_reconciliation
        WHERE receipt_file_path IS NOT NULL
        AND receipt_file_path != ''
        ORDER BY date DESC
        LIMIT %s
    """, (limit * 2,))  # Get more to account for missing files

    rows = cursor.fetchall()
    db.return_connection(conn)

    # Filter to existing files
    results = []
    cache = get_ocr_cache() if skip_cached else None

    for row in rows:
        if len(results) >= limit:
            break

        path = row.get('receipt_file_path')
        if not path:
            continue

        # Check if file exists
        if not Path(path).exists():
            continue

        # Check if already cached
        if skip_cached and cache:
            cached = cache.get(path)
            if cached:
                continue

        results.append({
            'transaction_id': row.get('transaction_id'),
            'description': row.get('description'),
            'amount': float(row.get('amount', 0)),
            'date': str(row.get('date', '')),
            'receipt_file_path': path
        })

    return results


def bulk_extract(limit: int = 100, skip_cached: bool = True):
    """Pre-extract all receipts and cache results"""
    print("=" * 60)
    print("BULK RECEIPT EXTRACTION AND CACHING")
    print("=" * 60)

    # Initialize service
    service = ReceiptOCRService(use_cache=True)
    print(f"Gemini: {'Ready' if service.gemini_ready else 'Not available'}")
    print(f"Cache: {'Enabled' if service.cache else 'Disabled'}")

    initial_stats = service.get_cache_stats()
    print(f"Cache entries: {initial_stats.get('count', 0)}")
    print()

    # Get receipts
    print(f"Finding receipts needing extraction (limit {limit})...")
    receipts = get_receipts_needing_extraction(limit, skip_cached)
    print(f"Found {len(receipts)} receipts to process")
    print()

    if not receipts:
        print("No receipts need extraction. All cached!")
        return

    # Process each receipt
    start_time = time.time()
    processed = 0
    errors = 0
    cached_count = 0

    for i, receipt in enumerate(receipts):
        path = receipt['receipt_file_path']
        print(f"[{i+1}/{len(receipts)}] {Path(path).name}...", end=" ", flush=True)

        try:
            result = service.extract(path)

            if result.get('from_cache'):
                print(f"CACHED ({result.get('supplier_name', 'N/A')})")
                cached_count += 1
            elif result.get('confidence', 0) > 0.3:
                print(f"OK ({result.get('supplier_name', 'N/A')} ${result.get('total_amount', 0)})")
                processed += 1
            else:
                print(f"LOW CONFIDENCE ({result.get('ocr_method', 'unknown')})")
                processed += 1

        except Exception as e:
            print(f"ERROR: {e}")
            errors += 1

        # Rate limiting - avoid hitting Gemini API too fast
        if not result.get('from_cache') and i < len(receipts) - 1:
            time.sleep(0.5)  # 500ms between API calls

    # Summary
    duration = time.time() - start_time
    final_stats = service.get_cache_stats()

    print()
    print("=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(f"Total receipts: {len(receipts)}")
    print(f"Newly extracted: {processed}")
    print(f"Already cached: {cached_count}")
    print(f"Errors: {errors}")
    print(f"Duration: {duration:.1f}s")
    print(f"Avg per receipt: {duration/len(receipts):.2f}s")
    print()
    print(f"Cache entries: {initial_stats.get('count', 0)} -> {final_stats.get('count', 0)}")
    print()
    print("Now run verification with cached data for instant results!")


def main():
    parser = argparse.ArgumentParser(description="Bulk extract and cache receipts")
    parser.add_argument('--limit', type=int, default=100, help='Max receipts to process')
    parser.add_argument('--skip-cached', action='store_true', default=True, help='Skip already cached receipts')
    parser.add_argument('--no-skip-cached', dest='skip_cached', action='store_false', help='Re-extract even cached receipts')

    args = parser.parse_args()
    bulk_extract(args.limit, args.skip_cached)


if __name__ == '__main__':
    main()

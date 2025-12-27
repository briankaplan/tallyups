#!/usr/bin/env python3
"""
Create final comprehensive Down Home report merging all verification results.
"""

import csv
import json
import re
from collections import defaultdict
from datetime import datetime

print("=" * 80)
print("CREATING FINAL COMPREHENSIVE DOWN HOME REPORT")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# Store all verification results by index
all_results = defaultdict(lambda: {'gemini': None, 'llama': None, 'llava': None})

# 1. Parse Gemini vision_verification_complete.csv
print("\n1. Loading Gemini results...")
try:
    with open('vision_verification_complete.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('index', '')
            if idx:
                verdict = row.get('verdict', '')
                reasoning = row.get('reasoning', '')
                if '429' in reasoning:
                    verdict = 'RATE_LIMITED'
                all_results[idx]['gemini'] = verdict
    print(f"   Loaded Gemini results")
except FileNotFoundError:
    print("   File not found")

# 2. Parse Llama log file
print("\n2. Loading Llama results from log...")
try:
    with open('/tmp/llama_verify.log', 'r') as f:
        content = f.read()
        current_idx = None
        for line in content.split('\n'):
            idx_match = re.search(r'\[\d+/\d+\] Index (\d+):', line)
            if idx_match:
                current_idx = idx_match.group(1)
            elif current_idx:
                if '✓ VERIFIED' in line:
                    all_results[current_idx]['llama'] = 'VERIFIED'
                    current_idx = None
                elif '✗ MISMATCH' in line:
                    all_results[current_idx]['llama'] = 'MISMATCH'
                    current_idx = None
                elif '? ERROR' in line:
                    all_results[current_idx]['llama'] = 'ERROR'
                    current_idx = None
    print(f"   Loaded Llama results")
except FileNotFoundError:
    print("   File not found")

# 3. Parse LLaVA results
print("\n3. Loading LLaVA results...")
try:
    with open('LLAVA_VERIFICATION_FINAL.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('index', '')
            if idx:
                verdict = row.get('verdict', '')
                all_results[idx]['llava'] = verdict
    print(f"   Loaded LLaVA results")
except FileNotFoundError:
    print("   File not found")

# 4. Load all Down Home transactions
print("\n4. Loading all Down Home transactions...")
transactions = {}
try:
    with open('/tmp/all_downhome.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('Index', '')
            if idx:
                transactions[idx] = row
    print(f"   Loaded {len(transactions)} transactions")
except FileNotFoundError:
    print("   File not found")

# 5. Compile final results
print("\n5. Compiling final results...")

final_results = []
stats = defaultdict(int)

for idx, txn in transactions.items():
    merchant = txn.get('Merchant', '')

    # Skip Cursor as requested
    if 'CURSOR' in merchant.upper():
        stats['cursor_skipped'] += 1
        continue

    has_receipt = bool(txn.get('Receipt_URL'))

    gemini = all_results.get(idx, {}).get('gemini', '')
    llama = all_results.get(idx, {}).get('llama', '')
    llava = all_results.get(idx, {}).get('llava', '')

    # Determine final status - ANY source saying VERIFIED wins
    if gemini == 'VERIFIED' or llama == 'VERIFIED' or llava == 'VERIFIED':
        final_status = 'VERIFIED'
        stats['verified'] += 1
    elif gemini == 'MISMATCH' or llama == 'MISMATCH' or llava == 'MISMATCH':
        final_status = 'MISMATCH'
        stats['mismatch'] += 1
    elif not has_receipt:
        final_status = 'NO_RECEIPT'
        stats['no_receipt'] += 1
    elif has_receipt:
        final_status = 'UNVERIFIED'
        stats['unverified'] += 1
    else:
        final_status = 'UNKNOWN'
        stats['unknown'] += 1

    final_results.append({
        'index': idx,
        'date': txn.get('Date', ''),
        'amount': txn.get('Amount', ''),
        'merchant': merchant,
        'description': txn.get('Memo', txn.get('Description', '')),
        'receipt_url': txn.get('Receipt_URL', ''),
        'has_receipt': 'Yes' if has_receipt else 'No',
        'gemini_verdict': gemini,
        'llama_verdict': llama,
        'llava_verdict': llava,
        'final_status': final_status
    })

# Sort by index
final_results.sort(key=lambda x: int(x['index']) if x['index'].isdigit() else 0)

# Write comprehensive CSV
print("\n6. Writing DOWNHOME_COMPLETE_VERIFICATION.csv...")
fieldnames = ['index', 'date', 'amount', 'merchant', 'description', 'receipt_url',
              'has_receipt', 'gemini_verdict', 'llama_verdict', 'llava_verdict', 'final_status']

with open('DOWNHOME_COMPLETE_VERIFICATION.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(final_results)

# Print summary
print("\n" + "=" * 80)
print("FINAL COMPREHENSIVE SUMMARY")
print("=" * 80)
print(f"Total transactions (excl Cursor): {len(final_results)}")
print(f"Cursor skipped:                   {stats['cursor_skipped']}")
print("-" * 40)
print(f"✓ VERIFIED:                       {stats['verified']}")
print(f"✗ MISMATCH (needs review):        {stats['mismatch']}")
print(f"  NO_RECEIPT:                     {stats['no_receipt']}")
print(f"? UNVERIFIED:                     {stats['unverified']}")
print("-" * 40)

# Write summary JSON
summary = {
    'generated': datetime.now().isoformat(),
    'date_range': '2024-07-01 to 2025-12-01',
    'total_transactions': len(final_results),
    'cursor_skipped': stats['cursor_skipped'],
    'verified': stats['verified'],
    'mismatch': stats['mismatch'],
    'no_receipt': stats['no_receipt'],
    'unverified': stats['unverified'],
}

with open('DOWNHOME_FINAL_SUMMARY.json', 'w') as f:
    json.dump(summary, f, indent=2)

# Write separate status files
verified = [r for r in final_results if r['final_status'] == 'VERIFIED']
mismatches = [r for r in final_results if r['final_status'] == 'MISMATCH']
no_receipt = [r for r in final_results if r['final_status'] == 'NO_RECEIPT']

with open('DOWNHOME_ALL_VERIFIED.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(verified)
print(f"\nWrote DOWNHOME_ALL_VERIFIED.csv ({len(verified)} items)")

with open('DOWNHOME_ALL_MISMATCHES.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(mismatches)
print(f"Wrote DOWNHOME_ALL_MISMATCHES.csv ({len(mismatches)} items)")

with open('DOWNHOME_ALL_NO_RECEIPT.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(no_receipt)
print(f"Wrote DOWNHOME_ALL_NO_RECEIPT.csv ({len(no_receipt)} items)")

print("\nDONE!")

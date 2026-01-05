#!/usr/bin/env python3
"""
Parse ALL verification results from all sources (Gemini, Llama logs, CSVs).
"""

import csv
import re
from collections import defaultdict
from datetime import datetime

print("=" * 80)
print("PARSING ALL VERIFICATION RESULTS")
print(f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print("=" * 80)

# Store all results by index
all_results = defaultdict(lambda: {'gemini': None, 'llama': None, 'sources': []})

# 1. Parse Gemini vision_verification_complete.csv
print("\n1. Parsing vision_verification_complete.csv (Gemini)...")
gemini_count = 0
try:
    with open('vision_verification_complete.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('index', '')
            if idx:
                verdict = row.get('verdict', '')
                reasoning = row.get('reasoning', '')
                # Check if it was a 429 error
                if '429' in reasoning:
                    verdict = 'RATE_LIMITED'
                all_results[idx]['gemini'] = verdict
                all_results[idx]['gemini_reasoning'] = reasoning[:100]
                all_results[idx]['sources'].append('gemini_csv')
                gemini_count += 1
    print(f"   Loaded {gemini_count} Gemini results")
except FileNotFoundError:
    print("   File not found")

# 2. Parse targeted_verification_results.csv (Gemini targeted)
print("\n2. Parsing targeted_verification_results.csv...")
targeted_count = 0
try:
    with open('targeted_verification_results.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('index', '')
            if idx:
                verdict = row.get('verdict', '')
                if verdict and verdict not in ['RATE_LIMITED', 'UNCLEAR']:
                    all_results[idx]['gemini'] = verdict
                    all_results[idx]['sources'].append('targeted_csv')
                    targeted_count += 1
    print(f"   Loaded {targeted_count} targeted results")
except FileNotFoundError:
    print("   File not found")

# 3. Parse Llama log file
print("\n3. Parsing /tmp/llama_verify.log...")
llama_count = 0
try:
    with open('/tmp/llama_verify.log', 'r') as f:
        content = f.read()
        # Parse patterns like [1/196] Index 284: followed by verdict lines
        current_idx = None
        for line in content.split('\n'):
            # Match index line
            idx_match = re.search(r'\[\d+/\d+\] Index (\d+):', line)
            if idx_match:
                current_idx = idx_match.group(1)
            # Match verdict
            elif current_idx:
                if '✓ VERIFIED' in line:
                    all_results[current_idx]['llama'] = 'VERIFIED'
                    all_results[current_idx]['sources'].append('llama_log')
                    llama_count += 1
                    current_idx = None
                elif '✗ MISMATCH' in line:
                    reason = line.split('MISMATCH:')[-1].strip() if 'MISMATCH:' in line else ''
                    all_results[current_idx]['llama'] = 'MISMATCH'
                    all_results[current_idx]['llama_reason'] = reason[:100]
                    all_results[current_idx]['sources'].append('llama_log')
                    llama_count += 1
                    current_idx = None
                elif '? ERROR' in line:
                    all_results[current_idx]['llama'] = 'ERROR'
                    all_results[current_idx]['sources'].append('llama_log')
                    llama_count += 1
                    current_idx = None
    print(f"   Parsed {llama_count} Llama results from log")
except FileNotFoundError:
    print("   File not found")

# 4. Parse remaining_llama.log (first batch)
print("\n4. Parsing /tmp/remaining_llama.log...")
remaining1_count = 0
try:
    with open('/tmp/remaining_llama.log', 'r') as f:
        content = f.read()
        current_idx = None
        for line in content.split('\n'):
            idx_match = re.search(r'\[\d+/\d+\] Index (\d+):', line)
            if idx_match:
                current_idx = idx_match.group(1)
            elif current_idx:
                if '✓ VERIFIED' in line:
                    all_results[current_idx]['llama'] = 'VERIFIED'
                    all_results[current_idx]['sources'].append('remaining_log')
                    remaining1_count += 1
                    current_idx = None
                elif '✗ MISMATCH' in line:
                    all_results[current_idx]['llama'] = 'MISMATCH'
                    all_results[current_idx]['sources'].append('remaining_log')
                    remaining1_count += 1
                    current_idx = None
    print(f"   Parsed {remaining1_count} results from remaining log")
except FileNotFoundError:
    print("   File not found")

# 5. Parse REMAINING_LLAMA_RESUME.csv
print("\n5. Parsing REMAINING_LLAMA_RESUME.csv...")
resume_count = 0
try:
    with open('REMAINING_LLAMA_RESUME.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('index', '')
            if idx:
                verdict = row.get('verdict', '')
                if verdict:
                    all_results[idx]['llama'] = verdict
                    all_results[idx]['llama_reason'] = row.get('reason', '')[:100]
                    all_results[idx]['sources'].append('resume_csv')
                    resume_count += 1
    print(f"   Loaded {resume_count} resume results")
except FileNotFoundError:
    print("   File not found")

# 6. Load all Business transactions
print("\n6. Loading all Business transactions...")
transactions = {}
try:
    with open('/tmp/all_business.csv', 'r') as f:
        reader = csv.DictReader(f)
        for row in reader:
            idx = row.get('Index', '')
            if idx:
                transactions[idx] = row
    print(f"   Loaded {len(transactions)} transactions")
except FileNotFoundError:
    print("   File not found")

# 7. Compile final results
print("\n7. Compiling final results...")

final_results = []
stats = defaultdict(int)

for idx, txn in transactions.items():
    merchant = txn.get('Merchant', '')

    # Skip Cursor as requested
    if 'CURSOR' in merchant.upper():
        stats['cursor_skipped'] += 1
        continue

    has_receipt = bool(txn.get('Receipt_URL'))

    # Get verification results
    gemini = all_results.get(idx, {}).get('gemini', '')
    llama = all_results.get(idx, {}).get('llama', '')
    sources = all_results.get(idx, {}).get('sources', [])

    # Determine final status - prioritize VERIFIED, then MISMATCH
    if gemini == 'VERIFIED' or llama == 'VERIFIED':
        final_status = 'VERIFIED'
        stats['verified'] += 1
    elif gemini == 'MISMATCH' or llama == 'MISMATCH':
        final_status = 'MISMATCH'
        stats['mismatch'] += 1
    elif not has_receipt:
        final_status = 'NO_RECEIPT'
        stats['no_receipt'] += 1
    elif gemini == 'RATE_LIMITED' or gemini == 'UNCLEAR':
        if llama in ['ERROR', '']:
            final_status = 'UNVERIFIED'
            stats['unverified'] += 1
        else:
            final_status = 'UNVERIFIED'
            stats['unverified'] += 1
    elif has_receipt:
        final_status = 'HAS_RECEIPT_UNVERIFIED'
        stats['has_receipt_unverified'] += 1
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
        'final_status': final_status,
        'verification_sources': ','.join(sources)
    })

# Sort by index
final_results.sort(key=lambda x: int(x['index']) if x['index'].isdigit() else 0)

# Write comprehensive CSV
print("\n8. Writing BUSINESS_COMPREHENSIVE_STATUS.csv...")
fieldnames = ['index', 'date', 'amount', 'merchant', 'description', 'receipt_url',
              'has_receipt', 'gemini_verdict', 'llama_verdict', 'final_status', 'verification_sources']

with open('BUSINESS_COMPREHENSIVE_STATUS.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(final_results)

# Print summary
print("\n" + "=" * 80)
print("SUMMARY")
print("=" * 80)
print(f"Total transactions (excl Cursor): {len(final_results)}")
print(f"Cursor skipped:                   {stats['cursor_skipped']}")
print("-" * 40)
print(f"VERIFIED:                         {stats['verified']}")
print(f"MISMATCH:                         {stats['mismatch']}")
print(f"NO_RECEIPT:                       {stats['no_receipt']}")
print(f"UNVERIFIED (rate limited):        {stats['unverified']}")
print(f"HAS_RECEIPT_UNVERIFIED:           {stats['has_receipt_unverified']}")
print("-" * 40)

# Also summarize verification coverage
verified_indices = set()
for idx, data in all_results.items():
    if data.get('gemini') or data.get('llama'):
        verified_indices.add(idx)

print(f"\nTotal indices with ANY verification data: {len(verified_indices)}")
print(f"Total indices in transactions: {len(transactions)}")

# Write separate status files
verified = [r for r in final_results if r['final_status'] == 'VERIFIED']
mismatches = [r for r in final_results if r['final_status'] == 'MISMATCH']
no_receipt = [r for r in final_results if r['final_status'] == 'NO_RECEIPT']
unverified = [r for r in final_results if r['final_status'] in ['UNVERIFIED', 'HAS_RECEIPT_UNVERIFIED']]

with open('BUSINESS_VERIFIED_FINAL.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(verified)
print(f"\nWrote BUSINESS_VERIFIED_FINAL.csv ({len(verified)} items)")

with open('BUSINESS_MISMATCHES_FINAL.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(mismatches)
print(f"Wrote BUSINESS_MISMATCHES_FINAL.csv ({len(mismatches)} items)")

with open('BUSINESS_NO_RECEIPT.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(no_receipt)
print(f"Wrote BUSINESS_NO_RECEIPT.csv ({len(no_receipt)} items)")

with open('BUSINESS_UNVERIFIED.csv', 'w', newline='') as f:
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    writer.writerows(unverified)
print(f"Wrote BUSINESS_UNVERIFIED.csv ({len(unverified)} items)")

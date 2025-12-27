#!/usr/bin/env python3
"""
Create final comprehensive review CSV for Business transactions.
Uses metadata comparison (no vision API needed) to identify mismatches.
"""

import csv
from collections import defaultdict

# Read the full export
with open('/tmp/all_business.csv', 'r') as f:
    reader = csv.reader(f)
    header = next(reader)
    rows = list(reader)

print(f"Total transactions loaded: {len(rows)}")

# Categories for the report
results = {
    'VERIFIED_MATCH': [],        # Amount matches exactly, high confidence
    'LIKELY_MATCH': [],          # Amount close, good confidence
    'AMOUNT_MISMATCH': [],       # Amount differs significantly
    'DATE_MISMATCH': [],         # Date year differs significantly
    'NEEDS_REVIEW': [],          # Already flagged for review
    'NO_RECEIPT': [],            # No receipt attached
    'MISSING_DATA': [],          # Has receipt but no extracted data
}

# Soho House variations - relaxed matching (merchant + amount is enough)
SOHO_VARIATIONS = ['SH NASHVILLE', 'SOHO HOUSE', 'SCORPIOS MYKONOS', 'SHWD -']

def is_soho(merchant):
    m = merchant.upper()
    return any(v in m for v in SOHO_VARIATIONS)

def parse_amount(s):
    try:
        return float(s.replace('$', '').replace(',', ''))
    except:
        return None

def parse_date(d):
    try:
        parts = d.split('-')
        if len(parts) == 3:
            return int(parts[0]), int(parts[1]), int(parts[2])
    except:
        pass
    return None, None, None

for row in rows:
    if len(row) < 11:
        continue

    idx = row[0]
    date = row[1]
    amount = row[2]
    merchant = row[3]
    category = row[4] if len(row) > 4 else ''
    review_status = row[5] if len(row) > 5 else ''
    ai_confidence = row[6] if len(row) > 6 else ''
    receipt_merchant = row[7] if len(row) > 7 else ''
    receipt_total = row[8] if len(row) > 8 else ''
    receipt_date = row[9] if len(row) > 9 else ''
    receipt_url = row[10] if len(row) > 10 else ''
    notes = row[11] if len(row) > 11 else ''

    entry = {
        'idx': idx,
        'date': date,
        'amount': amount,
        'merchant': merchant,
        'category': category,
        'review_status': review_status,
        'ai_confidence': ai_confidence,
        'receipt_merchant': receipt_merchant,
        'receipt_total': receipt_total,
        'receipt_date': receipt_date,
        'receipt_url': receipt_url,
        'notes': notes[:200] if notes else '',
        'issue': '',
        'priority': ''
    }

    has_receipt = receipt_url and ('r2.dev' in receipt_url or receipt_url.startswith('http'))

    # Already flagged?
    if review_status.lower() in ['needs_review', 'bad', 'needs_manual_review']:
        entry['issue'] = f'Flagged as: {review_status}'
        entry['priority'] = 'HIGH'
        results['NEEDS_REVIEW'].append(entry)
        continue

    # No receipt?
    if not has_receipt:
        entry['issue'] = 'No receipt attached'
        entry['priority'] = 'HIGH'
        results['NO_RECEIPT'].append(entry)
        continue

    # Parse amounts
    bank_amt = parse_amount(amount)
    rcpt_amt = parse_amount(receipt_total) if receipt_total else None

    # No receipt data extracted?
    if rcpt_amt is None:
        entry['issue'] = 'No receipt total extracted'
        entry['priority'] = 'MEDIUM'
        results['MISSING_DATA'].append(entry)
        continue

    # Amount comparison
    if bank_amt and rcpt_amt:
        diff = abs(bank_amt - rcpt_amt)
        pct_diff = (diff / bank_amt * 100) if bank_amt > 0 else 100

        # Check confidence
        conf = 0
        if ai_confidence:
            try:
                conf = int(ai_confidence.replace('%', ''))
            except:
                conf = 0

        # Exact or very close match
        if diff <= 0.50 or pct_diff <= 2:
            if conf >= 90:
                entry['issue'] = 'PERFECT MATCH'
                entry['priority'] = 'OK'
                results['VERIFIED_MATCH'].append(entry)
            elif conf >= 75:
                entry['issue'] = f'Good match (conf: {conf}%)'
                entry['priority'] = 'OK'
                results['LIKELY_MATCH'].append(entry)
            else:
                entry['issue'] = f'Amount matches but low confidence ({conf}%)'
                entry['priority'] = 'LOW'
                results['LIKELY_MATCH'].append(entry)
            continue

        # Close match (within 5% or $2)
        elif diff <= 2.00 or pct_diff <= 5:
            if conf >= 80:
                entry['issue'] = f'Close match: ${bank_amt:.2f} vs ${rcpt_amt:.2f} (diff: ${diff:.2f})'
                entry['priority'] = 'OK'
                results['LIKELY_MATCH'].append(entry)
            else:
                entry['issue'] = f'Amount close but check: ${bank_amt:.2f} vs ${rcpt_amt:.2f}'
                entry['priority'] = 'LOW'
                results['LIKELY_MATCH'].append(entry)
            continue

        # Amount mismatch - but check if it's tip related (bank > receipt)
        elif diff > 2.00:
            if bank_amt > rcpt_amt and pct_diff <= 25:
                # Could be tip added
                entry['issue'] = f'Tip likely: Bank ${bank_amt:.2f} vs Receipt ${rcpt_amt:.2f} (+${diff:.2f})'
                entry['priority'] = 'LOW'
                results['LIKELY_MATCH'].append(entry)
            else:
                # Significant mismatch
                entry['issue'] = f'MISMATCH: Bank ${bank_amt:.2f} vs Receipt ${rcpt_amt:.2f} ({pct_diff:.1f}% diff)'
                entry['priority'] = 'HIGH'
                results['AMOUNT_MISMATCH'].append(entry)
            continue

    # Date check (only if not Soho House)
    if receipt_date and not is_soho(merchant):
        bank_y, bank_m, bank_d = parse_date(date)
        rcpt_y, rcpt_m, rcpt_d = parse_date(receipt_date)

        if bank_y and rcpt_y and abs(bank_y - rcpt_y) > 1:
            entry['issue'] = f'DATE YEAR MISMATCH: Bank {date} vs Receipt {receipt_date}'
            entry['priority'] = 'HIGH'
            results['DATE_MISMATCH'].append(entry)
            continue

    # Default to verified if we got here
    entry['issue'] = 'OK'
    entry['priority'] = 'OK'
    results['VERIFIED_MATCH'].append(entry)

# Print summary
print("\n" + "=" * 70)
print("BUSINESS COMPREHENSIVE REVIEW SUMMARY")
print("=" * 70)

total_ok = len(results['VERIFIED_MATCH']) + len(results['LIKELY_MATCH'])
total_issues = len(results['AMOUNT_MISMATCH']) + len(results['DATE_MISMATCH']) + len(results['NEEDS_REVIEW'])
total_missing = len(results['NO_RECEIPT']) + len(results['MISSING_DATA'])

print(f"\n{'VERIFIED (exact match):':<35} {len(results['VERIFIED_MATCH']):>5}")
print(f"{'LIKELY MATCH (close/tip):':<35} {len(results['LIKELY_MATCH']):>5}")
print(f"{'─' * 50}")
print(f"{'Total OK:':<35} {total_ok:>5}")

print(f"\n{'NEEDS REVIEW (flagged):':<35} {len(results['NEEDS_REVIEW']):>5}")
print(f"{'AMOUNT MISMATCH:':<35} {len(results['AMOUNT_MISMATCH']):>5}")
print(f"{'DATE YEAR MISMATCH:':<35} {len(results['DATE_MISMATCH']):>5}")
print(f"{'─' * 50}")
print(f"{'Total Issues to Review:':<35} {total_issues:>5}")

print(f"\n{'NO RECEIPT:':<35} {len(results['NO_RECEIPT']):>5}")
print(f"{'MISSING DATA:':<35} {len(results['MISSING_DATA']):>5}")
print(f"{'─' * 50}")
print(f"{'Total Missing:':<35} {total_missing:>5}")

# Write comprehensive CSV
all_entries = []
for category, entries in results.items():
    for e in entries:
        e['category_type'] = category
        all_entries.append(e)

# Sort by priority then date
priority_order = {'HIGH': 0, 'MEDIUM': 1, 'LOW': 2, 'OK': 3}
all_entries.sort(key=lambda x: (priority_order.get(x['priority'], 99), x['date']), reverse=True)

with open('BUSINESS_FINAL_REVIEW.csv', 'w', newline='') as f:
    fieldnames = ['priority', 'category_type', 'issue', 'idx', 'date', 'amount', 'merchant',
                  'receipt_total', 'receipt_merchant', 'receipt_date', 'ai_confidence',
                  'review_status', 'receipt_url', 'notes']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for e in all_entries:
        writer.writerow({k: e.get(k, '') for k in fieldnames})

print(f"\n{'='*70}")
print(f"OUTPUT: BUSINESS_FINAL_REVIEW.csv")
print(f"{'='*70}")

# Also write a focused "ACTION NEEDED" list
action_items = (results['NEEDS_REVIEW'] + results['AMOUNT_MISMATCH'] +
                results['DATE_MISMATCH'] + results['NO_RECEIPT'])

with open('BUSINESS_ACTION_NEEDED.csv', 'w', newline='') as f:
    fieldnames = ['priority', 'issue', 'idx', 'date', 'amount', 'merchant',
                  'receipt_total', 'receipt_merchant', 'receipt_url']
    writer = csv.DictWriter(f, fieldnames=fieldnames)
    writer.writeheader()
    for e in sorted(action_items, key=lambda x: (priority_order.get(x['priority'], 99), x['date']), reverse=True):
        writer.writerow({k: e.get(k, '') for k in fieldnames})

print(f"OUTPUT: BUSINESS_ACTION_NEEDED.csv ({len(action_items)} items)")

# Print HIGH priority items
print(f"\n{'='*70}")
print("HIGH PRIORITY ITEMS (need immediate attention):")
print("=" * 70)
high_priority = [e for e in all_entries if e['priority'] == 'HIGH']
for i, e in enumerate(high_priority[:30], 1):
    print(f"{i:>2}. [{e['category_type']}] {e['date']} | ${parse_amount(e['amount']) or 0:.2f} | {e['merchant'][:30]}")
    print(f"    Issue: {e['issue'][:70]}")
    if e['receipt_url']:
        print(f"    Receipt: {e['receipt_url'][:80]}")
    print()

if len(high_priority) > 30:
    print(f"... and {len(high_priority) - 30} more. See CSV for full list.")

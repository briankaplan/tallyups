#!/usr/bin/env python3
"""Debug dashboard calculation issues"""
import pandas as pd
from pathlib import Path

CSV_PATH = Path("FINAL_MASTER_RECONCILED.csv")

# Load CSV
df = pd.read_csv(CSV_PATH, dtype=str, keep_default_na=False)

print("🔍 Dashboard Debug Report\n")
print("="*60)

# Check Business Type values
print("\n1️⃣ Business Type Distribution:")
print("-"*60)
biz_counts = df['Business Type'].value_counts()
print(biz_counts)

# Check unique business types (to catch typos/case issues)
print("\n2️⃣ Unique Business Type Values:")
print("-"*60)
unique_biz = df['Business Type'].unique()
for biz in sorted(unique_biz):
    if biz:
        print(f"  '{biz}'")

# Calculate totals by business type
print("\n3️⃣ Expense Totals by Business Type (negative amounts only):")
print("-"*60)

for biz in ['Down Home', 'Music City Rodeo', 'Personal']:
    biz_rows = df[df['Business Type'] == biz]
    total = 0
    count = 0

    for _, row in biz_rows.iterrows():
        try:
            amt_str = row.get('Chase Amount', '0')
            amt = float(str(amt_str).replace('$', '').replace(',', ''))
            if amt > 0:  # Chase: positive = charges/expenses
                total += amt
                count += 1
        except:
            pass

    print(f"{biz:20} : ${total:,.2f} ({count} expense transactions)")

# Check refunds/credits
print("\n4️⃣ Refunds/Credits (negative amounts in Chase):")
print("-"*60)

refund_total = 0
refund_count = 0

for _, row in df.iterrows():
    try:
        amt_str = row.get('Chase Amount', '0')
        amt = float(str(amt_str).replace('$', '').replace(',', ''))
        if amt < 0:  # Chase: negative = refunds/credits
            refund_total += abs(amt)
            refund_count += 1
    except:
        pass

print(f"Total Refunds/Credits: ${refund_total:,.2f} ({refund_count} transactions)")

# Sample of refunds
print("\n5️⃣ Sample Refund Transactions:")
print("-"*60)

sample_count = 0
for _, row in df.iterrows():
    try:
        amt_str = row.get('Chase Amount', '0')
        amt = float(str(amt_str).replace('$', '').replace(',', ''))
        if amt > 0 and sample_count < 10:
            date = row.get('Chase Date', '')
            desc = row.get('Chase Description', '')
            biz = row.get('Business Type', '')
            print(f"{date} | {desc:30} | +${amt:,.2f} | {biz}")
            sample_count += 1
    except:
        pass

# Sample of Down Home expenses
print("\n6️⃣ Sample Down Home Expense Transactions:")
print("-"*60)

dh_rows = df[df['Business Type'] == 'Down Home']
sample_count = 0

for _, row in dh_rows.iterrows():
    try:
        amt_str = row.get('Chase Amount', '0')
        amt = float(str(amt_str).replace('$', '').replace(',', ''))
        if amt < 0 and sample_count < 10:
            date = row.get('Chase Date', '')
            desc = row.get('Chase Description', '')
            print(f"{date} | {desc:30} | -${abs(amt):,.2f}")
            sample_count += 1
    except:
        pass

print("\n" + "="*60)
print("✅ Debug report complete")
print("\nIf numbers don't match UI, check:")
print("  - Browser cache (hard refresh: Cmd+Shift+R)")
print("  - Amount parsing logic in HTML")
print("  - Exact Business Type string matching")

#!/usr/bin/env python3
"""
Run vision verification in batches via the server API.
Processes transactions in chunks to avoid timeout.
"""

import requests
import json
import csv
import time

BASE_URL = "https://web-production-309e.up.railway.app"
BATCH_SIZE = 50  # Process 50 at a time
TOTAL = 572

all_results = []
summary = {"verified": 0, "mismatch": 0, "unclear": 0, "no_receipt": 0}

print("=" * 60)
print("VISION VERIFICATION - BATCH PROCESSING")
print("=" * 60)

for offset in range(0, TOTAL, BATCH_SIZE):
    batch_num = (offset // BATCH_SIZE) + 1
    total_batches = (TOTAL + BATCH_SIZE - 1) // BATCH_SIZE

    print(f"\n[Batch {batch_num}/{total_batches}] Processing transactions {offset+1}-{min(offset+BATCH_SIZE, TOTAL)}...")

    try:
        resp = requests.post(
            f"{BASE_URL}/api/vision-verify",
            json={"all": True, "limit": BATCH_SIZE, "offset": offset},
            timeout=600  # 10 minute timeout per batch
        )

        if resp.status_code != 200:
            print(f"  ❌ Error: {resp.status_code}")
            print(f"     {resp.text[:200]}")
            continue

        data = resp.json()
        batch_results = data.get("results", [])
        batch_summary = data.get("summary", {})

        all_results.extend(batch_results)
        summary["verified"] += batch_summary.get("verified", 0)
        summary["mismatch"] += batch_summary.get("mismatch", 0)
        summary["unclear"] += batch_summary.get("unclear", 0)
        summary["no_receipt"] += batch_summary.get("no_receipt", 0)

        print(f"  ✓ Processed {len(batch_results)} transactions")
        print(f"    VERIFIED: {batch_summary.get('verified', 0)}, MISMATCH: {batch_summary.get('mismatch', 0)}, UNCLEAR: {batch_summary.get('unclear', 0)}")

        # Print mismatches
        for r in batch_results:
            if r.get("verdict") == "MISMATCH":
                print(f"    ⚠️  MISMATCH: {r['date']} | ${r['amount']:.2f} | {r['merchant'][:30]}")
                print(f"       Reason: {r.get('reasoning', '')[:80]}")

    except Exception as e:
        print(f"  ❌ Exception: {e}")

    # Small delay between batches
    time.sleep(2)

# Write results to CSV
output_file = "vision_verification_complete.csv"
with open(output_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "index", "date", "amount", "merchant", "receipt_url",
        "verdict", "confidence", "receipt_total", "receipt_merchant", "reasoning"
    ])
    writer.writeheader()
    writer.writerows(all_results)

# Write mismatches-only file
mismatch_file = "vision_mismatches_final.csv"
with open(mismatch_file, "w", newline="") as f:
    writer = csv.DictWriter(f, fieldnames=[
        "index", "date", "amount", "merchant", "receipt_url",
        "verdict", "confidence", "receipt_total", "receipt_merchant", "reasoning"
    ])
    writer.writeheader()
    for r in all_results:
        if r.get("verdict") == "MISMATCH":
            writer.writerow(r)

print("\n" + "=" * 60)
print("COMPLETE!")
print("=" * 60)
print(f"Total processed: {len(all_results)}")
print(f"VERIFIED: {summary['verified']}")
print(f"MISMATCH: {summary['mismatch']}")
print(f"UNCLEAR: {summary['unclear']}")
print(f"NO_RECEIPT: {summary['no_receipt']}")
print(f"\nFull results: {output_file}")
print(f"Mismatches only: {mismatch_file}")

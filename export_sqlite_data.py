#!/usr/bin/env python3
"""
Export all SQLite data to JSON files for MySQL import
"""

import sqlite3
import json
import os
from decimal import Decimal

SQLITE_PATH = 'receipts.db'
OUTPUT_DIR = 'migration_data'


class DecimalEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal):
            return float(obj)
        return super().default(obj)


def export_table(cursor, table_name, output_path):
    """Export a table to JSON"""
    cursor.execute(f"SELECT * FROM {table_name}")
    columns = [desc[0] for desc in cursor.description]
    rows = cursor.fetchall()

    data = []
    for row in rows:
        data.append(dict(zip(columns, row)))

    with open(output_path, 'w') as f:
        json.dump(data, f, indent=2, cls=DecimalEncoder)

    print(f"  ✅ Exported {len(data)} rows from {table_name}")
    return len(data)


def main():
    print("=" * 80)
    print("📦 Exporting SQLite data to JSON")
    print("=" * 80)

    os.makedirs(OUTPUT_DIR, exist_ok=True)

    conn = sqlite3.connect(SQLITE_PATH)
    cursor = conn.cursor()

    tables = [
        'transactions',
        'reports',
        'incoming_receipts',
        'rejected_receipts',
        'merchants',
        'contacts',
        'receipt_metadata',
        'incoming_rejection_patterns'
    ]

    total_rows = 0
    for table in tables:
        try:
            output_path = os.path.join(OUTPUT_DIR, f'{table}.json')
            rows = export_table(cursor, table, output_path)
            total_rows += rows
        except Exception as e:
            print(f"  ⚠️  Failed to export {table}: {e}")

    conn.close()

    print(f"\n✅ Exported {total_rows} total rows to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()

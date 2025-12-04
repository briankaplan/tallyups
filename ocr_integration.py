#!/usr/bin/env python3
"""
OCR Integration Module
Connects the OCR service to the rest of the system:
- Stores extracted data in transactions table
- Stores extracted data in incoming_receipts table
- Updates verification status
- Provides helper functions for auto-OCR on receipt match

Usage:
    from ocr_integration import (
        extract_and_store_for_transaction,
        extract_and_store_for_incoming,
        auto_ocr_on_receipt_match,
        get_ocr_data_for_transaction
    )
"""

import json
from datetime import datetime
from typing import Dict, Any, Optional
from pathlib import Path


def get_db():
    """Get database connection"""
    try:
        from db_mysql import get_mysql_db
        return get_mysql_db()
    except Exception as e:
        print(f"Database not available: {e}")
        return None


def get_ocr_service():
    """Get OCR service instance"""
    try:
        from receipt_ocr_service import get_ocr_service as _get_service
        return _get_service()
    except Exception as e:
        print(f"OCR service not available: {e}")
        return None


def extract_and_store_for_transaction(
    transaction_index: int,
    receipt_path: str,
    skip_if_exists: bool = True
) -> Optional[Dict[str, Any]]:
    """
    Extract OCR data from receipt and store in transactions table.

    Args:
        transaction_index: The _index of the transaction
        receipt_path: Path to the receipt file
        skip_if_exists: Skip if OCR data already exists

    Returns:
        Extracted OCR data or None on failure
    """
    db = get_db()
    if not db:
        return None

    service = get_ocr_service()
    if not service:
        return None

    # Check if already extracted
    if skip_if_exists:
        conn = db.get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT ocr_extracted_at FROM transactions WHERE _index = %s",
            (transaction_index,)
        )
        row = cursor.fetchone()
        db.return_connection(conn)

        if row and row.get('ocr_extracted_at'):
            print(f"  OCR already exists for transaction {transaction_index}")
            return None

    # Check file exists
    if not Path(receipt_path).exists():
        print(f"  Receipt file not found: {receipt_path}")
        return None

    # Extract OCR data
    try:
        ocr_data = service.extract(receipt_path)
    except Exception as e:
        print(f"  OCR extraction failed: {e}")
        return None

    if not ocr_data or ocr_data.get('confidence', 0) < 0.3:
        print(f"  OCR extraction low confidence")
        return None

    # Store in database
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE transactions SET
                ocr_merchant = %s,
                ocr_amount = %s,
                ocr_date = %s,
                ocr_subtotal = %s,
                ocr_tax = %s,
                ocr_tip = %s,
                ocr_receipt_number = %s,
                ocr_payment_method = %s,
                ocr_line_items = %s,
                ocr_confidence = %s,
                ocr_method = %s,
                ocr_extracted_at = %s
            WHERE _index = %s
        """, (
            ocr_data.get('supplier_name'),
            ocr_data.get('total_amount'),
            ocr_data.get('date'),
            ocr_data.get('subtotal'),
            ocr_data.get('tax_amount'),
            ocr_data.get('tip_amount'),
            ocr_data.get('receipt_number'),
            ocr_data.get('payment_method'),
            json.dumps(ocr_data.get('line_items', [])),
            ocr_data.get('confidence'),
            ocr_data.get('ocr_method'),
            datetime.now(),
            transaction_index
        ))
        conn.commit()
        print(f"  ✅ OCR stored for transaction {transaction_index}: {ocr_data.get('supplier_name')} ${ocr_data.get('total_amount')}")

    except Exception as e:
        print(f"  ❌ Failed to store OCR: {e}")
        conn.rollback()
        ocr_data = None
    finally:
        db.return_connection(conn)

    return ocr_data


def extract_and_store_for_incoming(
    incoming_id: int,
    receipt_path: str
) -> Optional[Dict[str, Any]]:
    """
    Extract OCR data from receipt and store in incoming_receipts table.

    Args:
        incoming_id: The id of the incoming receipt
        receipt_path: Path to the receipt file

    Returns:
        Extracted OCR data or None on failure
    """
    db = get_db()
    if not db:
        return None

    service = get_ocr_service()
    if not service:
        return None

    # Check file exists
    if not Path(receipt_path).exists():
        print(f"  Receipt file not found: {receipt_path}")
        return None

    # Extract OCR data
    try:
        ocr_data = service.extract(receipt_path)
    except Exception as e:
        print(f"  OCR extraction failed: {e}")
        return None

    if not ocr_data or ocr_data.get('confidence', 0) < 0.3:
        return None

    # Store in database
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE incoming_receipts SET
                ocr_merchant = %s,
                ocr_amount = %s,
                ocr_date = %s,
                ocr_subtotal = %s,
                ocr_tax = %s,
                ocr_tip = %s,
                ocr_receipt_number = %s,
                ocr_payment_method = %s,
                ocr_line_items = %s,
                ocr_confidence = %s,
                ocr_method = %s,
                ocr_extracted_at = %s,
                merchant = COALESCE(merchant, %s),
                amount = COALESCE(amount, %s),
                receipt_date = COALESCE(receipt_date, %s)
            WHERE id = %s
        """, (
            ocr_data.get('supplier_name'),
            ocr_data.get('total_amount'),
            ocr_data.get('date'),
            ocr_data.get('subtotal'),
            ocr_data.get('tax_amount'),
            ocr_data.get('tip_amount'),
            ocr_data.get('receipt_number'),
            ocr_data.get('payment_method'),
            json.dumps(ocr_data.get('line_items', [])),
            ocr_data.get('confidence'),
            ocr_data.get('ocr_method'),
            datetime.now(),
            # Also update merchant/amount/date if not set
            ocr_data.get('supplier_name'),
            ocr_data.get('total_amount'),
            ocr_data.get('date'),
            incoming_id
        ))
        conn.commit()
        print(f"  ✅ OCR stored for incoming {incoming_id}: {ocr_data.get('supplier_name')} ${ocr_data.get('total_amount')}")

    except Exception as e:
        print(f"  ❌ Failed to store OCR: {e}")
        conn.rollback()
        ocr_data = None
    finally:
        db.return_connection(conn)

    return ocr_data


def auto_ocr_on_receipt_match(
    transaction_index: int,
    receipt_path: str
) -> Optional[Dict[str, Any]]:
    """
    Called when a receipt is matched to a transaction.
    Extracts OCR data and stores it, also verifies the match.

    Args:
        transaction_index: The _index of the transaction
        receipt_path: Path to the matched receipt

    Returns:
        OCR data with verification status
    """
    db = get_db()
    if not db:
        return None

    service = get_ocr_service()
    if not service:
        return None

    # Get transaction details for verification
    conn = db.get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "SELECT chase_description, chase_amount, chase_date FROM transactions WHERE _index = %s",
        (transaction_index,)
    )
    tx = cursor.fetchone()
    db.return_connection(conn)

    if not tx:
        return None

    # Extract OCR data
    ocr_data = extract_and_store_for_transaction(transaction_index, receipt_path, skip_if_exists=False)
    if not ocr_data:
        return None

    # Verify match
    expected = {
        'merchant': tx.get('chase_description'),
        'amount': float(tx.get('chase_amount', 0)),
        'date': str(tx.get('chase_date', ''))
    }

    verification = service.verify_receipt(receipt_path, expected)

    # Update verification status
    conn = db.get_connection()
    cursor = conn.cursor()

    try:
        verification_status = 'verified' if verification.get('overall_match') else 'mismatch'
        cursor.execute("""
            UPDATE transactions SET
                ocr_verified = %s,
                ocr_verification_status = %s
            WHERE _index = %s
        """, (
            verification.get('overall_match', False),
            verification_status,
            transaction_index
        ))
        conn.commit()
        print(f"  ✅ Verification: {verification_status} (confidence: {verification.get('confidence', 0):.0%})")

    except Exception as e:
        print(f"  ❌ Failed to update verification: {e}")
        conn.rollback()
    finally:
        db.return_connection(conn)

    ocr_data['verification'] = verification
    return ocr_data


def get_ocr_data_for_transaction(transaction_index: int) -> Optional[Dict[str, Any]]:
    """
    Get stored OCR data for a transaction.

    Args:
        transaction_index: The _index of the transaction

    Returns:
        OCR data dict or None if not extracted
    """
    db = get_db()
    if not db:
        return None

    conn = db.get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            ocr_merchant, ocr_amount, ocr_date, ocr_subtotal, ocr_tax, ocr_tip,
            ocr_receipt_number, ocr_payment_method, ocr_line_items,
            ocr_confidence, ocr_method, ocr_extracted_at,
            ocr_verified, ocr_verification_status
        FROM transactions
        WHERE _index = %s
    """, (transaction_index,))

    row = cursor.fetchone()
    db.return_connection(conn)

    if not row or not row.get('ocr_extracted_at'):
        return None

    # Parse line items JSON
    line_items = row.get('ocr_line_items')
    if isinstance(line_items, str):
        try:
            line_items = json.loads(line_items)
        except:
            line_items = []

    return {
        'supplier_name': row.get('ocr_merchant'),
        'total_amount': float(row.get('ocr_amount', 0)) if row.get('ocr_amount') else None,
        'date': str(row.get('ocr_date', '')) if row.get('ocr_date') else None,
        'subtotal': float(row.get('ocr_subtotal', 0)) if row.get('ocr_subtotal') else None,
        'tax_amount': float(row.get('ocr_tax', 0)) if row.get('ocr_tax') else None,
        'tip_amount': float(row.get('ocr_tip', 0)) if row.get('ocr_tip') else None,
        'receipt_number': row.get('ocr_receipt_number'),
        'payment_method': row.get('ocr_payment_method'),
        'line_items': line_items,
        'confidence': row.get('ocr_confidence'),
        'ocr_method': row.get('ocr_method'),
        'extracted_at': str(row.get('ocr_extracted_at', '')),
        'verified': row.get('ocr_verified'),
        'verification_status': row.get('ocr_verification_status')
    }


def bulk_extract_for_transactions(
    limit: int = 100,
    skip_existing: bool = True
) -> Dict[str, Any]:
    """
    Bulk extract OCR data for transactions with receipts.

    Args:
        limit: Max transactions to process
        skip_existing: Skip transactions that already have OCR data

    Returns:
        Summary of extraction results
    """
    db = get_db()
    if not db:
        return {"error": "Database not available"}

    conn = db.get_connection()
    cursor = conn.cursor()

    # Get transactions with receipts
    if skip_existing:
        cursor.execute("""
            SELECT _index, receipt_file
            FROM transactions
            WHERE receipt_file IS NOT NULL
            AND receipt_file != ''
            AND ocr_extracted_at IS NULL
            AND deleted = FALSE
            LIMIT %s
        """, (limit,))
    else:
        cursor.execute("""
            SELECT _index, receipt_file
            FROM transactions
            WHERE receipt_file IS NOT NULL
            AND receipt_file != ''
            AND deleted = FALSE
            LIMIT %s
        """, (limit,))

    rows = cursor.fetchall()
    db.return_connection(conn)

    results = {
        'total': len(rows),
        'extracted': 0,
        'skipped': 0,
        'errors': 0
    }

    for row in rows:
        idx = row.get('_index')
        path = row.get('receipt_file')

        if not path or not Path(path).exists():
            results['skipped'] += 1
            continue

        result = extract_and_store_for_transaction(idx, path, skip_if_exists=skip_existing)
        if result:
            results['extracted'] += 1
        else:
            results['errors'] += 1

    return results


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python ocr_integration.py bulk [limit]    - Bulk extract for transactions")
        print("  python ocr_integration.py tx <index>      - Extract for specific transaction")
        sys.exit(1)

    cmd = sys.argv[1]

    if cmd == 'bulk':
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 100
        print(f"Bulk extracting OCR for up to {limit} transactions...")
        result = bulk_extract_for_transactions(limit)
        print(f"\nResults: {result}")

    elif cmd == 'tx':
        if len(sys.argv) < 3:
            print("Usage: python ocr_integration.py tx <index>")
            sys.exit(1)
        idx = int(sys.argv[2])
        print(f"Getting OCR data for transaction {idx}...")
        data = get_ocr_data_for_transaction(idx)
        if data:
            print(json.dumps(data, indent=2, default=str))
        else:
            print("No OCR data found")

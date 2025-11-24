#!/usr/bin/env python3
"""
Intelligent Receipt Matching Service

Fuzzy matching service for transactions and receipts
- Load transactions from CSV
- Load receipts from SQLite/R2
- Fuzzy match by:
  - Merchant name (fuzz ratio > 80%)
  - Amount (+/- $1 tolerance)
  - Date (+/- 3 days)
- Calculate confidence score
- Auto-approve if confidence > 90%
- Return match suggestions for manual review

Requirements: fuzzywuzzy, python-Levenshtein, pandas
"""

import os
import csv
import sqlite3
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from dataclasses import dataclass
import json

# Fuzzy matching imports - graceful degradation if not available
try:
    from fuzzywuzzy import fuzz
    from fuzzywuzzy import process
    FUZZYWUZZY_AVAILABLE = True
except ImportError:
    FUZZYWUZZY_AVAILABLE = False
    print("⚠️  fuzzywuzzy not available - fuzzy matching disabled")

# CSV handling
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False
    print("⚠️  pandas not available - using basic CSV reader")


@dataclass
class Transaction:
    """Transaction from bank CSV"""
    date: str
    description: str
    amount: float
    category: str
    match_status: str = 'UNMATCHED'
    receipt_path: str = ''
    receipt_merchant: str = ''
    receipt_amount: float = 0.0
    confidence: float = 0.0
    match_reasons: str = ''
    business_type: str = ''
    transaction_type: str = ''
    submission_status: str = ''
    row_index: int = 0


@dataclass
class Receipt:
    """Receipt from database"""
    id: int
    merchant: str
    amount: float
    transaction_date: str
    r2_url: str
    r2_key: str
    business_type: str
    gmail_account: str = ''
    order_number: str = ''
    confidence_score: float = 0.0


@dataclass
class Match:
    """Match between transaction and receipt"""
    transaction: Transaction
    receipt: Receipt
    confidence_score: float
    match_reasons: List[str]
    merchant_similarity: float
    amount_difference: float
    date_difference_days: int
    auto_approve: bool


class ReceiptMatcherService:
    """
    Intelligent Receipt Matching Service

    Matches bank transactions with receipts using fuzzy matching algorithms
    """

    def __init__(
        self,
        db_path: str = 'receipts.db',
        csv_path: str = None,
        merchant_threshold: float = 80.0,
        amount_tolerance: float = 1.0,
        date_tolerance_days: int = 3,
        auto_approve_threshold: float = 90.0
    ):
        """
        Initialize receipt matcher

        Args:
            db_path: Path to SQLite receipts database
            csv_path: Path to bank transactions CSV
            merchant_threshold: Minimum fuzzy match score for merchant (0-100)
            amount_tolerance: Maximum amount difference in dollars
            date_tolerance_days: Maximum date difference in days
            auto_approve_threshold: Confidence score for auto-approval (0-100)
        """
        self.db_path = db_path
        self.csv_path = csv_path
        self.merchant_threshold = merchant_threshold
        self.amount_tolerance = amount_tolerance
        self.date_tolerance_days = date_tolerance_days
        self.auto_approve_threshold = auto_approve_threshold

        # Cache for loaded data
        self.transactions = []
        self.receipts = []

        # Statistics
        self.stats = {
            'total_transactions': 0,
            'total_receipts': 0,
            'total_matches': 0,
            'auto_approved': 0,
            'manual_review': 0,
            'no_match': 0
        }

    def load_transactions_from_csv(self, csv_path: str = None) -> List[Transaction]:
        """
        Load transactions from CSV file

        Args:
            csv_path: Path to CSV file (uses self.csv_path if None)

        Returns:
            List of Transaction objects
        """
        csv_path = csv_path or self.csv_path

        if not csv_path:
            print("❌ No CSV path provided")
            return []

        csv_path = Path(csv_path)

        if not csv_path.exists():
            print(f"❌ CSV file not found: {csv_path}")
            return []

        print(f"📄 Loading transactions from: {csv_path}")

        transactions = []

        try:
            if PANDAS_AVAILABLE:
                # Use pandas for better CSV handling
                df = pd.read_csv(csv_path)

                for idx, row in df.iterrows():
                    # Parse amount (remove $ and convert to float)
                    amount_str = str(row.get('Amount', '0')).replace('$', '').replace(',', '')
                    try:
                        amount = float(amount_str)
                    except:
                        amount = 0.0

                    transaction = Transaction(
                        date=str(row.get('Date', '')),
                        description=str(row.get('Description', '')),
                        amount=amount,
                        category=str(row.get('Category', '')),
                        match_status=str(row.get('Match Status', 'UNMATCHED')),
                        receipt_path=str(row.get('Receipt Path', '')),
                        receipt_merchant=str(row.get('Receipt Merchant', '')),
                        receipt_amount=float(str(row.get('Receipt Amount', '0')).replace('$', '').replace(',', '') or 0),
                        confidence=float(str(row.get('Confidence', '0')).replace('%', '') or 0),
                        match_reasons=str(row.get('Match Reasons', '')),
                        business_type=str(row.get('Business-type', '')),
                        transaction_type=str(row.get('Transaction_Type', '')),
                        submission_status=str(row.get('submission-status', '')),
                        row_index=idx
                    )

                    transactions.append(transaction)

            else:
                # Use basic CSV reader
                with open(csv_path, 'r', encoding='utf-8') as f:
                    reader = csv.DictReader(f)

                    for idx, row in enumerate(reader):
                        # Parse amount
                        amount_str = row.get('Amount', '0').replace('$', '').replace(',', '')
                        try:
                            amount = float(amount_str)
                        except:
                            amount = 0.0

                        transaction = Transaction(
                            date=row.get('Date', ''),
                            description=row.get('Description', ''),
                            amount=amount,
                            category=row.get('Category', ''),
                            match_status=row.get('Match Status', 'UNMATCHED'),
                            receipt_path=row.get('Receipt Path', ''),
                            receipt_merchant=row.get('Receipt Merchant', ''),
                            receipt_amount=float(row.get('Receipt Amount', '0').replace('$', '').replace(',', '') or 0),
                            confidence=float(row.get('Confidence', '0').replace('%', '') or 0),
                            match_reasons=row.get('Match Reasons', ''),
                            business_type=row.get('Business-type', ''),
                            transaction_type=row.get('Transaction_Type', ''),
                            submission_status=row.get('submission-status', ''),
                            row_index=idx
                        )

                        transactions.append(transaction)

            print(f"✅ Loaded {len(transactions)} transactions")
            self.transactions = transactions
            self.stats['total_transactions'] = len(transactions)

            return transactions

        except Exception as e:
            print(f"❌ Error loading CSV: {e}")
            return []

    def load_receipts_from_db(self) -> List[Receipt]:
        """
        Load receipts from SQLite database

        Returns:
            List of Receipt objects
        """
        if not Path(self.db_path).exists():
            print(f"❌ Database not found: {self.db_path}")
            return []

        print(f"📊 Loading receipts from: {self.db_path}")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        try:
            cur.execute("""
                SELECT
                    id,
                    merchant,
                    amount,
                    transaction_date,
                    r2_url,
                    r2_key,
                    business_type,
                    gmail_account,
                    order_number,
                    confidence_score
                FROM receipts
                WHERE merchant IS NOT NULL
                AND amount IS NOT NULL
                AND transaction_date IS NOT NULL
                ORDER BY transaction_date DESC
            """)

            rows = cur.fetchall()

            receipts = []

            for row in rows:
                receipt = Receipt(
                    id=row['id'],
                    merchant=row['merchant'] or '',
                    amount=float(row['amount'] or 0),
                    transaction_date=row['transaction_date'] or '',
                    r2_url=row['r2_url'] or '',
                    r2_key=row['r2_key'] or '',
                    business_type=row['business_type'] or '',
                    gmail_account=row['gmail_account'] or '',
                    order_number=row['order_number'] or '',
                    confidence_score=float(row['confidence_score'] or 0)
                )

                receipts.append(receipt)

            print(f"✅ Loaded {len(receipts)} receipts")
            self.receipts = receipts
            self.stats['total_receipts'] = len(receipts)

            return receipts

        except Exception as e:
            print(f"❌ Error loading receipts: {e}")
            return []
        finally:
            conn.close()

    def _is_receipt_rejected(self, transaction: Transaction, receipt: Receipt) -> bool:
        """
        Check if this receipt was manually rejected for this transaction.

        Args:
            transaction: Transaction to check
            receipt: Receipt to check

        Returns:
            bool: True if user manually rejected this combo
        """
        try:
            # Check the rejected_receipts table
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute('''
                SELECT COUNT(*) FROM rejected_receipts
                WHERE transaction_date = ?
                  AND transaction_description = ?
                  AND transaction_amount = ?
                  AND receipt_path = ?
            ''', (transaction.date, transaction.description, str(transaction.amount), receipt.r2_url))

            count = cursor.fetchone()[0]
            conn.close()

            if count > 0:
                print(f"⛔ SKIPPING REJECTED: {receipt.r2_url} for {transaction.description}")
                return True

            return False

        except sqlite3.OperationalError:
            # Table doesn't exist yet - no rejections
            return False
        except Exception as e:
            print(f"⚠️ Error checking rejected receipts: {e}")
            return False

    def match_transaction_to_receipts(self, transaction: Transaction) -> List[Match]:
        """
        Find matching receipts for a transaction

        Args:
            transaction: Transaction to match

        Returns:
            List of Match objects (sorted by confidence score)
        """
        if not FUZZYWUZZY_AVAILABLE:
            print("❌ Fuzzy matching not available")
            return []

        matches = []

        # Parse transaction date
        try:
            trans_date = datetime.strptime(transaction.date, '%m/%d/%Y')
        except:
            try:
                trans_date = datetime.strptime(transaction.date, '%Y-%m-%d')
            except:
                print(f"⚠️  Could not parse transaction date: {transaction.date}")
                return []

        # Clean transaction description
        trans_merchant = self._clean_merchant_name(transaction.description)

        for receipt in self.receipts:
            # CRITICAL: Skip if user manually rejected this receipt for this transaction
            if self._is_receipt_rejected(transaction, receipt):
                continue
            # Parse receipt date
            try:
                receipt_date = datetime.strptime(receipt.transaction_date, '%Y-%m-%d')
            except:
                continue

            # Check date tolerance
            date_diff = abs((trans_date - receipt_date).days)
            if date_diff > self.date_tolerance_days:
                continue

            # Check amount tolerance
            amount_diff = abs(abs(transaction.amount) - receipt.amount)
            if amount_diff > self.amount_tolerance:
                continue

            # Calculate merchant similarity
            receipt_merchant = self._clean_merchant_name(receipt.merchant)
            merchant_similarity = fuzz.token_set_ratio(trans_merchant, receipt_merchant)

            if merchant_similarity < self.merchant_threshold:
                continue

            # Calculate confidence score
            confidence, reasons = self._calculate_match_confidence(
                transaction,
                receipt,
                merchant_similarity,
                amount_diff,
                date_diff
            )

            # Determine auto-approve
            auto_approve = confidence >= self.auto_approve_threshold

            match = Match(
                transaction=transaction,
                receipt=receipt,
                confidence_score=confidence,
                match_reasons=reasons,
                merchant_similarity=merchant_similarity,
                amount_difference=amount_diff,
                date_difference_days=date_diff,
                auto_approve=auto_approve
            )

            matches.append(match)

        # Sort by confidence score (descending)
        matches.sort(key=lambda m: m.confidence_score, reverse=True)

        return matches

    def _clean_merchant_name(self, name: str) -> str:
        """
        Clean merchant name for better matching

        Args:
            name: Raw merchant name

        Returns:
            str: Cleaned merchant name
        """
        # Remove common prefixes/suffixes
        name = name.upper()
        name = name.replace('TST*', '')
        name = name.replace('SQ *', '')
        name = name.replace('THE ', '')

        # Remove special characters
        import re
        name = re.sub(r'[^A-Z0-9\s]', ' ', name)

        # Remove extra whitespace
        name = ' '.join(name.split())

        return name

    def _calculate_match_confidence(
        self,
        transaction: Transaction,
        receipt: Receipt,
        merchant_similarity: float,
        amount_diff: float,
        date_diff: int
    ) -> Tuple[float, List[str]]:
        """
        Calculate confidence score for a match

        Args:
            transaction: Transaction object
            receipt: Receipt object
            merchant_similarity: Merchant fuzzy match score (0-100)
            amount_diff: Absolute amount difference
            date_diff: Date difference in days

        Returns:
            Tuple of (confidence_score, reasons)
        """
        reasons = []
        score = 0.0

        # Merchant similarity (40% weight)
        merchant_score = (merchant_similarity / 100) * 40
        score += merchant_score

        if merchant_similarity == 100:
            reasons.append('merchant_100')
        elif merchant_similarity >= 95:
            reasons.append('merchant_95')
        elif merchant_similarity >= 90:
            reasons.append('merchant_90')
        elif merchant_similarity >= 80:
            reasons.append('merchant_80')

        # Amount match (40% weight)
        if amount_diff == 0:
            score += 40
            reasons.append('exact_amount')
        elif amount_diff <= 0.01:
            score += 38
            reasons.append('amount_penny')
        elif amount_diff <= 0.50:
            score += 35
            reasons.append('amount_50cents')
        else:
            # Proportional scoring for larger differences
            amount_score = max(0, (1 - (amount_diff / self.amount_tolerance)) * 40)
            score += amount_score

        # Date match (20% weight)
        if date_diff == 0:
            score += 20
            reasons.append('exact_date')
        elif date_diff == 1:
            score += 18
            reasons.append('date_1day')
        elif date_diff <= 3:
            score += 15
            reasons.append('date_3days')
        else:
            # Proportional scoring
            date_score = max(0, (1 - (date_diff / self.date_tolerance_days)) * 20)
            score += date_score

        return round(score, 2), reasons

    def match_all_transactions(self) -> Dict:
        """
        Match all unmatched transactions to receipts

        Returns:
            Dict with matching results and statistics
        """
        if not self.transactions:
            print("⚠️  No transactions loaded")
            return {'error': 'No transactions loaded'}

        if not self.receipts:
            print("⚠️  No receipts loaded")
            return {'error': 'No receipts loaded'}

        print(f"\n🔍 Matching {len(self.transactions)} transactions to {len(self.receipts)} receipts...")

        results = {
            'matches': [],
            'auto_approved': [],
            'manual_review': [],
            'no_match': []
        }

        for i, transaction in enumerate(self.transactions, 1):
            # Skip already matched transactions
            if transaction.match_status == 'MATCHED':
                continue

            print(f"\n[{i}/{len(self.transactions)}] {transaction.description} ${transaction.amount}")

            # Find matches
            matches = self.match_transaction_to_receipts(transaction)

            if not matches:
                print(f"   ❌ No matches found")
                results['no_match'].append({
                    'transaction': transaction,
                    'reason': 'No matching receipts found'
                })
                continue

            # Get best match
            best_match = matches[0]

            print(f"   ✅ Best match: {best_match.receipt.merchant} (confidence: {best_match.confidence_score}%)")
            print(f"      Reasons: {', '.join(best_match.match_reasons)}")

            if best_match.auto_approve:
                print(f"      🟢 AUTO-APPROVED")
                results['auto_approved'].append(best_match)
            else:
                print(f"      🟡 Manual review needed")
                results['manual_review'].append(best_match)

            results['matches'].append(best_match)

        # Update statistics
        self.stats['total_matches'] = len(results['matches'])
        self.stats['auto_approved'] = len(results['auto_approved'])
        self.stats['manual_review'] = len(results['manual_review'])
        self.stats['no_match'] = len(results['no_match'])

        return results

    def export_matches_to_csv(self, matches: List[Match], output_path: str) -> bool:
        """
        Export matches to CSV file

        Args:
            matches: List of Match objects
            output_path: Path to output CSV file

        Returns:
            bool: True if successful
        """
        try:
            print(f"\n💾 Exporting matches to: {output_path}")

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow([
                    'Transaction Date',
                    'Transaction Description',
                    'Transaction Amount',
                    'Receipt Merchant',
                    'Receipt Amount',
                    'Receipt Date',
                    'Confidence Score',
                    'Match Reasons',
                    'Auto Approve',
                    'Merchant Similarity',
                    'Amount Difference',
                    'Date Difference (days)',
                    'Receipt URL',
                    'Business Type'
                ])

                # Write matches
                for match in matches:
                    writer.writerow([
                        match.transaction.date,
                        match.transaction.description,
                        f"${match.transaction.amount:.2f}",
                        match.receipt.merchant,
                        f"${match.receipt.amount:.2f}",
                        match.receipt.transaction_date,
                        f"{match.confidence_score}%",
                        ', '.join(match.match_reasons),
                        'YES' if match.auto_approve else 'NO',
                        f"{match.merchant_similarity}%",
                        f"${match.amount_difference:.2f}",
                        match.date_difference_days,
                        match.receipt.r2_url,
                        match.receipt.business_type
                    ])

            print(f"✅ Exported {len(matches)} matches")
            return True

        except Exception as e:
            print(f"❌ Export error: {e}")
            return False

    def update_csv_with_matches(self, matches: List[Match], output_path: str = None) -> bool:
        """
        Update original CSV with match information

        Args:
            matches: List of Match objects
            output_path: Path to output CSV (uses original path + _matched if None)

        Returns:
            bool: True if successful
        """
        if not self.csv_path:
            print("❌ No CSV path set")
            return False

        output_path = output_path or str(Path(self.csv_path).parent / f"{Path(self.csv_path).stem}_MATCHED.csv")

        try:
            print(f"\n💾 Updating CSV with matches: {output_path}")

            # Create match lookup
            match_lookup = {}
            for match in matches:
                key = (match.transaction.date, match.transaction.description, match.transaction.amount)
                match_lookup[key] = match

            # Read original CSV and update
            updated_transactions = []

            for transaction in self.transactions:
                key = (transaction.date, transaction.description, transaction.amount)

                if key in match_lookup:
                    match = match_lookup[key]

                    # Update transaction with match info
                    transaction.match_status = 'MATCHED'
                    transaction.receipt_path = match.receipt.r2_key
                    transaction.receipt_merchant = match.receipt.merchant
                    transaction.receipt_amount = match.receipt.amount
                    transaction.confidence = match.confidence_score
                    transaction.match_reasons = ', '.join(match.match_reasons)

                updated_transactions.append(transaction)

            # Write updated CSV
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)

                # Write header
                writer.writerow([
                    'Date',
                    'Description',
                    'Amount',
                    'Category',
                    'Match Status',
                    'Receipt Path',
                    'Receipt Merchant',
                    'Receipt Amount',
                    'Confidence',
                    'Match Reasons',
                    'Match_Batch',
                    'Business-type',
                    'Transaction_Type',
                    'submission-status'
                ])

                # Write transactions
                for t in updated_transactions:
                    writer.writerow([
                        t.date,
                        t.description,
                        f"${t.amount:.2f}",
                        t.category,
                        t.match_status,
                        t.receipt_path,
                        t.receipt_merchant,
                        f"${t.receipt_amount:.2f}" if t.receipt_amount else '',
                        f"{t.confidence}%" if t.confidence else '',
                        t.match_reasons,
                        '',  # Match_Batch
                        t.business_type,
                        t.transaction_type,
                        t.submission_status
                    ])

            print(f"✅ Updated CSV saved: {output_path}")
            return True

        except Exception as e:
            print(f"❌ Update error: {e}")
            return False

    def get_statistics(self) -> Dict:
        """
        Get matching statistics as a dictionary

        Returns:
            Dict containing statistics about matches
        """
        return {
            'total_transactions': self.stats.get('total_transactions', 0),
            'total_receipts': self.stats.get('total_receipts', 0),
            'total_matches': self.stats.get('total_matches', 0),
            'auto_approved': self.stats.get('auto_approved', 0),
            'manual_review': self.stats.get('manual_review', 0),
            'no_match': self.stats.get('no_match', 0),
            'match_rate': round((self.stats.get('total_matches', 0) / max(self.stats.get('total_transactions', 1), 1)) * 100, 2),
            'auto_approve_rate': round((self.stats.get('auto_approved', 0) / max(self.stats.get('total_matches', 1), 1)) * 100, 2)
        }

    def print_statistics(self):
        """Print matching statistics"""
        print("\n" + "=" * 80)
        print("MATCHING STATISTICS")
        print("=" * 80)
        print(f"Total transactions: {self.stats['total_transactions']}")
        print(f"Total receipts: {self.stats['total_receipts']}")
        print(f"Total matches: {self.stats['total_matches']}")
        print(f"Auto-approved: {self.stats['auto_approved']}")
        print(f"Manual review: {self.stats['manual_review']}")
        print(f"No match: {self.stats['no_match']}")
        print("=" * 80)


# Singleton instance
_receipt_matcher_service = None

def get_receipt_matcher_service(
    db_path: str = 'receipts.db',
    csv_path: str = None
) -> ReceiptMatcherService:
    """
    Get or create the receipt matcher service singleton

    Args:
        db_path: Path to SQLite database
        csv_path: Path to CSV file

    Returns:
        ReceiptMatcherService: Singleton instance
    """
    global _receipt_matcher_service
    if _receipt_matcher_service is None:
        _receipt_matcher_service = ReceiptMatcherService(db_path, csv_path)
    return _receipt_matcher_service


if __name__ == '__main__':
    """
    Test receipt matcher service
    """
    import sys

    print("=" * 80)
    print("RECEIPT MATCHER SERVICE")
    print("=" * 80)

    if len(sys.argv) < 3:
        print("\nUsage: python receipt_matcher_service.py <csv_file> <db_file>")
        print("\nExample:")
        print("  python receipt_matcher_service.py transactions.csv receipts.db")
        sys.exit(1)

    csv_path = sys.argv[1]
    db_path = sys.argv[2]

    # Initialize service
    matcher = ReceiptMatcherService(db_path=db_path, csv_path=csv_path)

    # Load data
    matcher.load_transactions_from_csv()
    matcher.load_receipts_from_db()

    # Match transactions
    results = matcher.match_all_transactions()

    # Print statistics
    matcher.print_statistics()

    # Export results
    if results['matches']:
        export_path = Path(csv_path).parent / f"{Path(csv_path).stem}_matches.csv"
        matcher.export_matches_to_csv(results['matches'], str(export_path))

        # Update original CSV
        matcher.update_csv_with_matches(results['matches'])

    print("\n✅ Matching complete!")

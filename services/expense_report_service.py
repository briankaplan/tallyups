"""
Expense Report Export Service

Features:
- Export by business entity (Business/Ragdoll/AMRF/EM.co/Personal)
- Monthly, quarterly, YTD reports
- Bank transaction reconciliation
- CSV/PDF export formats
- Custom date ranges
"""

import csv
from datetime import datetime, timedelta
from pathlib import Path
import json

# Business entities
BUSINESS_ENTITIES = {
    'business': 'Business',
    'ragdoll': 'Ragdoll',
    'amrf': 'AMRF',
    'emco': 'EM.co',
    'personal': 'Personal',
    'sec': 'Secondary'
}


class ExpenseReportService:
    """Generate expense reports by entity and date range"""

    def __init__(self, csv_path):
        self.csv_path = Path(csv_path)
        self.transactions = []
        self._load_transactions()

    def _load_transactions(self):
        """Load transactions from CSV"""
        try:
            with open(self.csv_path, 'r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                self.transactions = list(reader)
        except Exception as e:
            print(f"Error loading CSV: {e}")
            self.transactions = []

    def parse_date(self, date_str):
        """Parse date string to datetime"""
        try:
            # Try MM/DD/YYYY format
            return datetime.strptime(date_str, '%m/%d/%Y')
        except:
            try:
                # Try YYYY-MM-DD format
                return datetime.strptime(date_str, '%Y-%m-%d')
            except:
                return None

    def parse_amount(self, amount_str):
        """Parse amount string to float"""
        try:
            # Remove $ and commas, handle negative
            clean = amount_str.replace('$', '').replace(',', '').replace('-', '')
            return float(clean)
        except:
            return 0.0

    def filter_by_entity(self, entity):
        """Filter transactions by business entity"""
        if entity not in BUSINESS_ENTITIES:
            return []

        entity_name = BUSINESS_ENTITIES[entity]

        return [t for t in self.transactions
                if t.get('Business-type', '').strip() == entity_name]

    def filter_by_date_range(self, transactions, start_date, end_date):
        """Filter transactions by date range"""
        filtered = []

        for txn in transactions:
            txn_date = self.parse_date(txn.get('Date', ''))
            if txn_date and start_date <= txn_date <= end_date:
                filtered.append(txn)

        return filtered

    def get_monthly_report(self, entity, year, month):
        """Get monthly report for entity"""
        # Get first and last day of month
        start_date = datetime(year, month, 1)
        if month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, month + 1, 1) - timedelta(days=1)

        # Filter transactions
        entity_txns = self.filter_by_entity(entity)
        monthly_txns = self.filter_by_date_range(entity_txns, start_date, end_date)

        return self._generate_report(monthly_txns, entity, 'Monthly', f"{year}-{month:02d}")

    def get_quarterly_report(self, entity, year, quarter):
        """Get quarterly report for entity (Q1, Q2, Q3, Q4)"""
        # Calculate quarter dates
        start_month = (quarter - 1) * 3 + 1
        start_date = datetime(year, start_month, 1)

        end_month = start_month + 2
        if end_month == 12:
            end_date = datetime(year + 1, 1, 1) - timedelta(days=1)
        else:
            end_date = datetime(year, end_month + 1, 1) - timedelta(days=1)

        # Filter transactions
        entity_txns = self.filter_by_entity(entity)
        quarterly_txns = self.filter_by_date_range(entity_txns, start_date, end_date)

        return self._generate_report(quarterly_txns, entity, 'Quarterly', f"{year}-Q{quarter}")

    def get_ytd_report(self, entity, year=None):
        """Get year-to-date report for entity"""
        if year is None:
            year = datetime.now().year

        start_date = datetime(year, 1, 1)
        end_date = datetime.now()

        # Filter transactions
        entity_txns = self.filter_by_entity(entity)
        ytd_txns = self.filter_by_date_range(entity_txns, start_date, end_date)

        return self._generate_report(ytd_txns, entity, 'YTD', str(year))

    def get_custom_range_report(self, entity, start_date_str, end_date_str):
        """Get report for custom date range"""
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d')
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d')

        # Filter transactions
        entity_txns = self.filter_by_entity(entity)
        range_txns = self.filter_by_date_range(entity_txns, start_date, end_date)

        period = f"{start_date_str} to {end_date_str}"
        return self._generate_report(range_txns, entity, 'Custom', period)

    def _generate_report(self, transactions, entity, report_type, period):
        """Generate comprehensive report"""
        # Calculate totals
        total_amount = sum(self.parse_amount(t.get('Amount', '$0')) for t in transactions)
        matched_count = sum(1 for t in transactions if t.get('Match Status') == 'MATCHED')
        unmatched_count = len(transactions) - matched_count

        # Category breakdown
        categories = {}
        for txn in transactions:
            category = txn.get('Category', 'Uncategorized')
            amount = self.parse_amount(txn.get('Amount', '$0'))
            categories[category] = categories.get(category, 0) + amount

        # Merchant breakdown (top 10)
        merchants = {}
        for txn in transactions:
            merchant = txn.get('Description', 'Unknown')
            amount = self.parse_amount(txn.get('Amount', '$0'))
            merchants[merchant] = merchants.get(merchant, 0) + amount

        top_merchants = sorted(merchants.items(), key=lambda x: x[1], reverse=True)[:10]

        # Transaction type breakdown
        transaction_types = {}
        for txn in transactions:
            txn_type = txn.get('Transaction_Type', 'Other')
            amount = self.parse_amount(txn.get('Amount', '$0'))
            transaction_types[txn_type] = transaction_types.get(txn_type, 0) + amount

        report = {
            'entity': BUSINESS_ENTITIES.get(entity, entity),
            'report_type': report_type,
            'period': period,
            'generated_at': datetime.now().isoformat(),
            'summary': {
                'total_transactions': len(transactions),
                'total_amount': f"${total_amount:,.2f}",
                'total_amount_raw': total_amount,
                'matched_transactions': matched_count,
                'unmatched_transactions': unmatched_count,
                'match_rate': f"{(matched_count / len(transactions) * 100) if transactions else 0:.1f}%"
            },
            'breakdown': {
                'by_category': {cat: f"${amt:,.2f}" for cat, amt in sorted(categories.items(), key=lambda x: x[1], reverse=True)},
                'by_merchant': {merch: f"${amt:,.2f}" for merch, amt in top_merchants},
                'by_type': {typ: f"${amt:,.2f}" for typ, amt in sorted(transaction_types.items(), key=lambda x: x[1], reverse=True)}
            },
            'transactions': transactions
        }

        return report

    def export_to_csv(self, report, output_path):
        """Export report to CSV file"""
        try:
            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                # Write header
                f.write(f"# {report['entity']} - {report['report_type']} Report\n")
                f.write(f"# Period: {report['period']}\n")
                f.write(f"# Generated: {report['generated_at']}\n")
                f.write(f"# Total: {report['summary']['total_amount']}\n")
                f.write(f"# Transactions: {report['summary']['total_transactions']}\n")
                f.write(f"# Match Rate: {report['summary']['match_rate']}\n")
                f.write("\n")

                # Write transactions
                if report['transactions']:
                    writer = csv.DictWriter(f, fieldnames=report['transactions'][0].keys())
                    writer.writeheader()
                    writer.writerows(report['transactions'])

            return True
        except Exception as e:
            print(f"Export error: {e}")
            return False

    def get_all_entities_summary(self, year=None, month=None):
        """Get summary for all entities (for dashboard)"""
        if year is None:
            year = datetime.now().year
        if month is None:
            month = datetime.now().month

        summary = {}

        for entity_key, entity_name in BUSINESS_ENTITIES.items():
            report = self.get_monthly_report(entity_key, year, month)
            summary[entity_key] = {
                'name': entity_name,
                'total': report['summary']['total_amount'],
                'total_raw': report['summary']['total_amount_raw'],
                'transactions': report['summary']['total_transactions'],
                'match_rate': report['summary']['match_rate']
            }

        return summary


# Singleton
_expense_report_service = None

def get_expense_report_service(csv_path):
    """Get or create expense report service"""
    global _expense_report_service
    if _expense_report_service is None:
        _expense_report_service = ExpenseReportService(csv_path)
    return _expense_report_service

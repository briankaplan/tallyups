"""
CSV Expense Report Exporter
===========================

Generates CSV exports compatible with:
- QuickBooks Online/Desktop
- Xero
- Generic accounting software
- Business submission format
- Raw data export

Export Formats:
- Standard CSV with all fields
- QuickBooks IIF format
- Xero CSV format
- Business submission format
- Summary CSV with totals
"""

import csv
import io
import logging
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class CSVExporter:
    """
    Generate CSV expense exports for various accounting systems.
    """

    def __init__(self):
        """Initialize CSV exporter."""
        # Category mappings for accounting software
        self.quickbooks_category_map = {
            # Travel
            "Travel - Airfare": "Travel:Airfare",
            "Travel - Hotel": "Travel:Lodging",
            "Travel - Ground Transport": "Travel:Transportation",
            "Travel - Meals": "Travel:Meals",
            "Travel - Vehicle": "Travel:Auto",
            "DH: Travel Costs - Airfare": "Travel:Airfare",
            "DH: Travel Costs - Hotel": "Travel:Lodging",
            "DH: Travel Costs - Cab/Uber/Bus Fare": "Travel:Transportation",
            "DH: Travel costs - Meals": "Travel:Meals",
            "DH: Travel Costs - Gas/Rental Car": "Travel:Auto",

            # Business Development
            "Business Development - Meals": "Meals and Entertainment:Business Meals",
            "DH: BD: Client Business Meals": "Meals and Entertainment:Business Meals",
            "BD: Client Business Meals": "Meals and Entertainment:Business Meals",

            # Software & Subscriptions
            "Software & Subscriptions": "Computer and Internet Expenses:Software Subscriptions",
            "Software subscriptions": "Computer and Internet Expenses:Software Subscriptions",

            # Office
            "Office Supplies": "Office Expenses:Office Supplies",

            # Marketing
            "Marketing & Advertising": "Advertising and Marketing",
            "BD: Advertising & Promotion": "Advertising and Marketing",

            # Meetings
            "Company Meetings": "Meals and Entertainment:Team Meetings",
            "Company Meetings and Meals": "Meals and Entertainment:Team Meetings",

            # Internet
            "Internet & Communications": "Computer and Internet Expenses:Internet",
            "Internet Costs": "Computer and Internet Expenses:Internet",
        }

        self.xero_category_map = {
            # Travel
            "Travel - Airfare": "Travel - International",
            "Travel - Hotel": "Travel - Accommodation",
            "Travel - Ground Transport": "Travel - National",
            "Travel - Meals": "Entertainment",
            "Travel - Vehicle": "Motor Vehicle Expenses",

            # Business Development
            "Business Development - Meals": "Entertainment",

            # Software
            "Software & Subscriptions": "Computer Expenses",

            # Office
            "Office Supplies": "Office Expenses",

            # Marketing
            "Marketing & Advertising": "Advertising",

            # Meetings
            "Company Meetings": "Entertainment",

            # Internet
            "Internet & Communications": "Telephone & Internet",
        }

    def _format_date(self, dt: Optional[datetime], format_str: str = "%m/%d/%Y") -> str:
        """Format date for CSV export."""
        if not dt:
            return ""
        return dt.strftime(format_str)

    def _format_amount(self, amount: Decimal, absolute: bool = True) -> str:
        """Format amount for CSV export."""
        value = abs(amount) if absolute else amount
        return f"{float(value):.2f}"

    def _map_category_quickbooks(self, category: str) -> str:
        """Map category to QuickBooks account."""
        return self.quickbooks_category_map.get(category, "Other Expenses")

    def _map_category_xero(self, category: str) -> str:
        """Map category to Xero account."""
        return self.xero_category_map.get(category, "General Expenses")

    def export_standard_csv(self, report: 'Report') -> bytes:
        """
        Export standard CSV with all transaction fields.

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header row
        headers = [
            "Index",
            "Date",
            "Description",
            "Amount",
            "Category",
            "Business Type",
            "Review Status",
            "Has Receipt",
            "Receipt URL",
            "Notes",
            "AI Confidence",
            "MI Merchant",
            "MI Category",
            "Source",
        ]
        writer.writerow(headers)

        # Data rows
        for txn in report.transactions:
            writer.writerow([
                txn.index,
                self._format_date(txn.date),
                txn.description,
                self._format_amount(txn.amount),
                txn.effective_category,
                txn.business_type,
                txn.review_status or "",
                "Yes" if txn.has_receipt else "No",
                txn.effective_receipt_url,
                txn.notes or txn.ai_note or "",
                f"{txn.ai_confidence:.0f}%" if txn.ai_confidence else "",
                txn.mi_merchant or "",
                txn.mi_category or "",
                txn.source or "",
            ])

        # Return as bytes
        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_quickbooks_csv(self, report: 'Report') -> bytes:
        """
        Export CSV in QuickBooks Online format.

        QuickBooks format:
        Date, Description, Amount, Account, Class, Memo

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # QuickBooks header
        headers = [
            "Date",
            "Description",
            "Amount",
            "Account",
            "Class",
            "Memo",
            "Billable",
            "Receipt",
        ]
        writer.writerow(headers)

        # Data rows
        for txn in report.transactions:
            # Map category to QuickBooks account
            account = self._map_category_quickbooks(txn.effective_category)

            # Class is business type
            qb_class = report.business_type if report.business_type != "All" else txn.business_type

            # Memo from notes
            memo = txn.notes or txn.ai_note or txn.description[:100]

            writer.writerow([
                self._format_date(txn.date),
                txn.description[:100],
                self._format_amount(txn.amount),
                account,
                qb_class,
                memo,
                "",  # Billable
                txn.effective_receipt_url,
            ])

        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_xero_csv(self, report: 'Report') -> bytes:
        """
        Export CSV in Xero bank statement format.

        Xero format:
        *Date, *Amount, Payee, Description, Reference, Account Code

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Xero header
        headers = [
            "*Date",
            "*Amount",
            "Payee",
            "Description",
            "Reference",
            "Account Code",
            "Tax Type",
        ]
        writer.writerow(headers)

        # Data rows
        for txn in report.transactions:
            # Map category to Xero account
            account_code = self._map_category_xero(txn.effective_category)

            # Payee is merchant
            payee = txn.mi_merchant or txn.description[:50]

            # Reference includes report ID
            reference = f"{report.report_id}-{txn.index}"

            writer.writerow([
                self._format_date(txn.date, "%Y-%m-%d"),  # Xero prefers YYYY-MM-DD
                self._format_amount(txn.amount, absolute=False),  # Xero needs signed amounts
                payee,
                txn.notes or txn.ai_note or "",
                reference,
                account_code,
                "No Tax",  # Default tax type
            ])

        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_business_csv(self, report: 'Report') -> bytes:
        """
        Export CSV in Business submission format.

        Format matches existing business export:
        External ID, Line, Category, Amount, Currency, Date, Project,
        Memo, Line of Business, Billable, Receipt URL

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Business header
        headers = [
            "External ID",
            "Line",
            "Category",
            "Amount",
            "Currency",
            "Date",
            "Project",
            "Memo",
            "Line of Business(do not fill)",
            "Billable",
            "Receipt URL",
        ]
        writer.writerow(headers)

        # Data rows
        for line_num, txn in enumerate(report.transactions, start=1):
            # Build memo from description and notes
            memo = txn.description
            if txn.notes and txn.notes != txn.description:
                memo = f"{txn.description} - {txn.notes}"

            writer.writerow([
                f"{report.report_id}-{line_num}",  # External ID
                line_num,  # Line
                txn.effective_category,  # Category
                self._format_amount(txn.amount),  # Amount
                "USD",  # Currency
                self._format_date(txn.date),  # Date
                "",  # Project (leave blank)
                memo,  # Memo
                "",  # Line of Business (do not fill)
                "",  # Billable (leave blank)
                txn.effective_receipt_url,  # Receipt URL
            ])

        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_summary_csv(self, report: 'Report') -> bytes:
        """
        Export summary CSV with statistics and breakdowns.

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Report header
        writer.writerow(["EXPENSE REPORT SUMMARY"])
        writer.writerow([])
        writer.writerow(["Report Name", report.report_name])
        writer.writerow(["Report ID", report.report_id])
        writer.writerow(["Business Type", report.business_type])
        writer.writerow(["Date Range", f"{self._format_date(report.date_range[0])} - {self._format_date(report.date_range[1])}"])
        writer.writerow(["Generated", self._format_date(report.generated_at, "%Y-%m-%d %H:%M:%S")])
        writer.writerow([])

        # Key metrics
        writer.writerow(["KEY METRICS"])
        writer.writerow(["Total Transactions", report.summary.total_transactions])
        writer.writerow(["Total Amount", f"${float(report.summary.total_amount):,.2f}"])
        writer.writerow(["Average Transaction", f"${float(report.summary.average_transaction):,.2f}"])
        writer.writerow(["Match Rate", f"{report.summary.match_rate:.1f}%"])
        writer.writerow(["Receipt Rate", f"{report.summary.receipt_rate:.1f}%"])
        writer.writerow([])

        # Category breakdown
        writer.writerow(["CATEGORY BREAKDOWN"])
        writer.writerow(["Category", "Amount", "Count", "% of Total"])
        for cat in report.summary.by_category:
            writer.writerow([
                cat.category,
                f"${float(cat.total):,.2f}",
                cat.count,
                f"{cat.percentage:.1f}%"
            ])
        writer.writerow([])

        # Top vendors
        writer.writerow(["TOP VENDORS"])
        writer.writerow(["Vendor", "Amount", "Count", "Recurring"])
        for vendor in report.summary.by_vendor[:20]:
            writer.writerow([
                vendor.vendor,
                f"${float(vendor.total):,.2f}",
                vendor.count,
                "Yes" if vendor.is_recurring else "No"
            ])
        writer.writerow([])

        # Monthly trends
        if report.summary.monthly_trends:
            writer.writerow(["MONTHLY TRENDS"])
            writer.writerow(["Month", "Amount", "Count"])
            for trend in report.summary.monthly_trends:
                month_name = datetime(trend.year, trend.month, 1).strftime('%B %Y')
                writer.writerow([
                    month_name,
                    f"${float(trend.total):,.2f}",
                    trend.count
                ])

        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_reconciliation_csv(self, report: 'Report') -> bytes:
        """
        Export reconciliation CSV showing matched/unmatched status.

        Args:
            report: Report object to export

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Header
        headers = [
            "Index",
            "Date",
            "Description",
            "Amount",
            "Category",
            "Match Status",
            "Has Receipt",
            "AI Confidence",
            "Receipt URL",
            "Notes",
        ]
        writer.writerow(headers)

        # Data rows - sorted by match status (unmatched first)
        sorted_txns = sorted(
            report.transactions,
            key=lambda t: (
                0 if t.review_status not in ('MATCHED', 'VERIFIED', 'APPROVED') else 1,
                0 if not t.has_receipt else 1,
                t.date or datetime.min
            )
        )

        for txn in sorted_txns:
            is_matched = txn.review_status in ('MATCHED', 'VERIFIED', 'APPROVED')
            status = "MATCHED" if is_matched else "UNMATCHED"

            writer.writerow([
                txn.index,
                self._format_date(txn.date),
                txn.description,
                self._format_amount(txn.amount),
                txn.effective_category,
                status,
                "Yes" if txn.has_receipt else "MISSING",
                f"{txn.ai_confidence:.0f}%" if txn.ai_confidence else "",
                txn.effective_receipt_url,
                txn.notes or "",
            ])

        output.seek(0)
        return output.getvalue().encode('utf-8')

    def export_multi_business_csv(self, reports: Dict[str, 'Report']) -> bytes:
        """
        Export combined CSV with all business types.

        Args:
            reports: Dict mapping business type to Report

        Returns:
            CSV file as bytes
        """
        output = io.StringIO()
        writer = csv.writer(output)

        # Summary section
        writer.writerow(["MULTI-BUSINESS EXPENSE SUMMARY"])
        writer.writerow([])
        writer.writerow(["Business Type", "Total Amount", "Transactions", "Match Rate", "Receipt Rate"])

        grand_total = Decimal('0')
        grand_count = 0

        for bt, report in reports.items():
            if report.summary.total_transactions > 0:
                writer.writerow([
                    bt,
                    f"${float(report.summary.total_amount):,.2f}",
                    report.summary.total_transactions,
                    f"{report.summary.match_rate:.1f}%",
                    f"{report.summary.receipt_rate:.1f}%",
                ])
                grand_total += report.summary.total_amount
                grand_count += report.summary.total_transactions

        writer.writerow(["GRAND TOTAL", f"${float(grand_total):,.2f}", grand_count, "", ""])
        writer.writerow([])
        writer.writerow([])

        # Detail sections for each business type
        for bt, report in reports.items():
            if report.summary.total_transactions > 0:
                writer.writerow([f"=== {bt} TRANSACTIONS ==="])
                writer.writerow(["Date", "Description", "Amount", "Category", "Status", "Receipt"])

                for txn in report.transactions:
                    writer.writerow([
                        self._format_date(txn.date),
                        txn.description[:50],
                        self._format_amount(txn.amount),
                        txn.effective_category,
                        txn.review_status or "",
                        "Yes" if txn.has_receipt else "No",
                    ])

                writer.writerow([])

        output.seek(0)
        return output.getvalue().encode('utf-8')


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_exporter_instance = None

def get_csv_exporter() -> CSVExporter:
    """Get or create CSV exporter instance."""
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = CSVExporter()
    return _exporter_instance

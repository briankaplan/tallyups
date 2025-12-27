"""
Comprehensive Expense Report Generator
======================================

Generates audit-ready expense reports by business type with multiple export formats.
Integrates with existing transaction data, receipts, and business classification.

Report Types:
- Business Type Summary (Business / MCR / Personal / CEO)
- Expense Detail Report (with receipts for tax documentation)
- Reconciliation Report (matched vs unmatched)
- Vendor Analysis (spend analysis and trends)

Export Formats:
- Excel (.xlsx) - Multi-sheet workbook with charts
- PDF - Professional audit-ready layout
- CSV - Raw data for accounting software
- QuickBooks/Xero compatible formats
"""

import csv
import io
import json
import logging
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from collections import defaultdict
import hashlib

logger = logging.getLogger(__name__)

# =============================================================================
# DATA TYPES
# =============================================================================

class ReportType(Enum):
    """Available report types."""
    BUSINESS_SUMMARY = "business_summary"
    EXPENSE_DETAIL = "expense_detail"
    RECONCILIATION = "reconciliation"
    VENDOR_ANALYSIS = "vendor_analysis"
    TAX_DOCUMENTATION = "tax_documentation"
    MONTHLY_SUMMARY = "monthly_summary"
    QUARTERLY_SUMMARY = "quarterly_summary"
    ANNUAL_SUMMARY = "annual_summary"


class ExportFormat(Enum):
    """Available export formats."""
    EXCEL = "excel"
    PDF = "pdf"
    CSV = "csv"
    QUICKBOOKS = "quickbooks"
    XERO = "xero"
    JSON = "json"


class BusinessType(Enum):
    """Business type categories matching existing system."""
    BUSINESS = "Business"
    SECONDARY = "Secondary"
    PERSONAL = "Personal"
    EM_CO = "EM.co"
    ALL = "All"


# Business type abbreviations for report IDs
BUSINESS_ABBREV = {
    "Business": "DOW",
    "Secondary": "MCR",
    "Personal": "PER",
    "EM.co": "EMC",
    "All": "ALL"
}


@dataclass
class Transaction:
    """Transaction data structure."""
    index: int
    date: datetime
    description: str
    amount: Decimal
    category: str
    chase_category: str
    business_type: str
    receipt_file: Optional[str] = None
    receipt_url: Optional[str] = None
    r2_url: Optional[str] = None
    notes: Optional[str] = None
    ai_note: Optional[str] = None
    ai_confidence: Optional[float] = None
    review_status: Optional[str] = None
    mi_merchant: Optional[str] = None
    mi_category: Optional[str] = None
    report_id: Optional[str] = None
    source: Optional[str] = None
    already_submitted: Optional[str] = None

    @property
    def has_receipt(self) -> bool:
        return bool(self.receipt_file or self.receipt_url or self.r2_url)

    @property
    def effective_category(self) -> str:
        """Get the best available category."""
        return self.mi_category or self.category or self.chase_category or "Uncategorized"

    @property
    def effective_receipt_url(self) -> str:
        """Get the best available receipt URL."""
        if self.r2_url:
            return self.r2_url
        if self.receipt_url:
            return self.receipt_url
        if self.receipt_file:
            r2_url = os.environ.get('R2_PUBLIC_URL', 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev')
            return f"{r2_url}/receipts/{self.receipt_file}"
        return ""


@dataclass
class CategoryBreakdown:
    """Category spending breakdown."""
    category: str
    total: Decimal
    count: int
    percentage: float
    transactions: List[Transaction] = field(default_factory=list)


@dataclass
class VendorBreakdown:
    """Vendor/merchant spending breakdown."""
    vendor: str
    normalized_name: str
    total: Decimal
    count: int
    average: Decimal
    is_recurring: bool
    first_transaction: datetime
    last_transaction: datetime
    categories: List[str] = field(default_factory=list)


@dataclass
class MonthlyTrend:
    """Monthly spending trend data."""
    year: int
    month: int
    total: Decimal
    count: int
    by_category: Dict[str, Decimal] = field(default_factory=dict)


@dataclass
class ReportSummary:
    """Summary statistics for a report."""
    total_transactions: int
    total_amount: Decimal
    matched_count: int
    unmatched_count: int
    match_rate: float
    receipts_attached: int
    receipts_missing: int
    receipt_rate: float
    average_transaction: Decimal
    largest_transaction: Decimal
    smallest_transaction: Decimal
    date_range_start: datetime
    date_range_end: datetime
    by_category: List[CategoryBreakdown] = field(default_factory=list)
    by_vendor: List[VendorBreakdown] = field(default_factory=list)
    monthly_trends: List[MonthlyTrend] = field(default_factory=list)


@dataclass
class Report:
    """Complete report structure."""
    report_id: str
    report_name: str
    report_type: ReportType
    business_type: str
    generated_at: datetime
    date_range: Tuple[datetime, datetime]
    summary: ReportSummary
    transactions: List[Transaction]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert report to dictionary for JSON serialization."""
        return {
            "report_id": self.report_id,
            "report_name": self.report_name,
            "report_type": self.report_type.value,
            "business_type": self.business_type,
            "generated_at": self.generated_at.isoformat(),
            "date_range": {
                "start": self.date_range[0].isoformat(),
                "end": self.date_range[1].isoformat()
            },
            "summary": {
                "total_transactions": self.summary.total_transactions,
                "total_amount": float(self.summary.total_amount),
                "matched_count": self.summary.matched_count,
                "unmatched_count": self.summary.unmatched_count,
                "match_rate": self.summary.match_rate,
                "receipts_attached": self.summary.receipts_attached,
                "receipts_missing": self.summary.receipts_missing,
                "receipt_rate": self.summary.receipt_rate,
                "average_transaction": float(self.summary.average_transaction),
                "by_category": [
                    {
                        "category": c.category,
                        "total": float(c.total),
                        "count": c.count,
                        "percentage": c.percentage
                    }
                    for c in self.summary.by_category
                ],
                "by_vendor": [
                    {
                        "vendor": v.vendor,
                        "total": float(v.total),
                        "count": v.count,
                        "average": float(v.average),
                        "is_recurring": v.is_recurring
                    }
                    for v in self.summary.by_vendor[:20]  # Top 20 vendors
                ]
            },
            "transaction_count": len(self.transactions),
            "metadata": self.metadata
        }


# =============================================================================
# REPORT GENERATOR
# =============================================================================

class ExpenseReportGenerator:
    """
    Comprehensive expense report generator.

    Generates audit-ready reports with multiple formats and business type support.
    """

    def __init__(self, db=None, receipt_dir: Optional[Path] = None):
        """
        Initialize report generator.

        Args:
            db: Database connection (MySQL or SQLite)
            receipt_dir: Directory containing receipt files
        """
        self.db = db
        self.receipt_dir = receipt_dir or Path("receipts")

        # Category mappings for standardization
        self.category_mapping = self._load_category_mapping()

        logger.info("ExpenseReportGenerator initialized")

    def _load_category_mapping(self) -> Dict[str, str]:
        """Load category standardization mapping."""
        return {
            # Travel categories
            "DH: Travel Costs - Airfare": "Travel - Airfare",
            "DH: Travel Costs - Hotel": "Travel - Hotel",
            "DH: Travel Costs - Cab/Uber/Bus Fare": "Travel - Ground Transport",
            "DH: Travel costs - Meals": "Travel - Meals",
            "DH: Travel Costs - Gas/Rental Car": "Travel - Vehicle",
            "Travel Costs - Meals": "Travel - Meals",
            "Travel Costs - Cab/Uber/Bus Fare": "Travel - Ground Transport",

            # Business categories
            "DH: BD: Client Business Meals": "Business Development - Meals",
            "BD: Client Business Meals": "Business Development - Meals",
            "BD: Advertising & Promotion": "Marketing & Advertising",
            "Company Meetings and Meals": "Company Meetings",

            # Software & subscriptions
            "Software subscriptions": "Software & Subscriptions",

            # Office & internet
            "Office Supplies": "Office Supplies",
            "Internet Costs": "Internet & Communications",
        }

    def _normalize_category(self, category: str) -> str:
        """Normalize category name for consistency."""
        if not category:
            return "Uncategorized"
        return self.category_mapping.get(category, category)

    def _normalize_vendor(self, description: str) -> str:
        """Normalize vendor/merchant name."""
        if not description:
            return "Unknown"

        # Remove common prefixes
        prefixes = ['TST*', 'TST ', 'SQ *', 'SQ*', 'DD ', 'DD*', 'PP *', 'PP*',
                   'UBER *', 'UBER*', 'LYFT *', 'LYFT*', 'AMZN*', 'AMAZON*']
        name = description.strip()
        for prefix in prefixes:
            if name.upper().startswith(prefix):
                name = name[len(prefix):].strip()

        # Remove trailing transaction IDs and numbers
        name = re.sub(r'\s*#?\d{4,}.*$', '', name)
        name = re.sub(r'\s*-\s*\d+$', '', name)

        # Clean up special characters
        name = re.sub(r'\s+', ' ', name).strip()

        return name[:50]  # Truncate to reasonable length

    def _parse_date(self, date_val: Any) -> Optional[datetime]:
        """Parse date from various formats."""
        if not date_val:
            return None

        if isinstance(date_val, datetime):
            return date_val

        date_str = str(date_val)

        # Try various formats
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%m/%d/%y',
            '%Y-%m-%d %H:%M:%S',
            '%Y-%m-%dT%H:%M:%S',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt)
            except ValueError:
                continue

        # Try dateutil as fallback
        try:
            from dateutil import parser
            return parser.parse(date_str)
        except:
            return None

    def _parse_amount(self, amount_val: Any) -> Decimal:
        """Parse amount from various formats."""
        if amount_val is None:
            return Decimal('0')

        if isinstance(amount_val, (int, float, Decimal)):
            return Decimal(str(amount_val))

        # Clean string amount
        amount_str = str(amount_val).replace('$', '').replace(',', '').strip()

        try:
            return Decimal(amount_str)
        except:
            return Decimal('0')

    def _row_to_transaction(self, row: Dict) -> Transaction:
        """Convert database row to Transaction object."""
        return Transaction(
            index=int(row.get('_index', 0)),
            date=self._parse_date(row.get('chase_date')),
            description=row.get('chase_description', ''),
            amount=self._parse_amount(row.get('chase_amount', 0)),
            category=row.get('category', ''),
            chase_category=row.get('chase_category', ''),
            business_type=row.get('business_type', ''),
            receipt_file=row.get('receipt_file'),
            receipt_url=row.get('receipt_url'),
            r2_url=row.get('r2_url'),
            notes=row.get('notes'),
            ai_note=row.get('ai_note'),
            ai_confidence=float(row.get('ai_confidence') or 0),
            review_status=row.get('review_status'),
            mi_merchant=row.get('mi_merchant'),
            mi_category=row.get('mi_category'),
            report_id=row.get('report_id'),
            source=row.get('source'),
            already_submitted=row.get('already_submitted'),
        )

    def fetch_transactions(
        self,
        business_type: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        include_submitted: bool = False,
        report_id: Optional[str] = None,
    ) -> List[Transaction]:
        """
        Fetch transactions from database.

        Args:
            business_type: Filter by business type (None for all)
            date_from: Start date (YYYY-MM-DD)
            date_to: End date (YYYY-MM-DD)
            include_submitted: Include already submitted transactions
            report_id: Get transactions for specific report

        Returns:
            List of Transaction objects
        """
        if not self.db:
            logger.error("No database connection")
            return []

        try:
            # Use database methods if available
            if report_id:
                rows = self.db.get_report_expenses(report_id)
            elif hasattr(self.db, 'get_reportable_expenses'):
                rows = self.db.get_reportable_expenses(
                    business_type=business_type,
                    date_from=date_from,
                    date_to=date_to
                )
            else:
                # Fallback to get_all_transactions
                all_txns = self.db.get_all_transactions()
                rows = [dict(row) for _, row in all_txns.iterrows()]

            transactions = []
            for row in rows:
                txn = self._row_to_transaction(row)

                # Apply filters
                if business_type and business_type != "All" and txn.business_type != business_type:
                    continue

                if date_from:
                    start = self._parse_date(date_from)
                    if txn.date and start and txn.date < start:
                        continue

                if date_to:
                    end = self._parse_date(date_to)
                    if txn.date and end and txn.date > end:
                        continue

                if not include_submitted and txn.already_submitted == 'yes':
                    continue

                transactions.append(txn)

            # Sort by date descending
            transactions.sort(key=lambda t: t.date or datetime.min, reverse=True)

            logger.info(f"Fetched {len(transactions)} transactions")
            return transactions

        except Exception as e:
            logger.error(f"Error fetching transactions: {e}")
            return []

    def calculate_statistics(self, transactions: List[Transaction]) -> ReportSummary:
        """
        Calculate comprehensive statistics for transactions.

        Args:
            transactions: List of transactions to analyze

        Returns:
            ReportSummary with all statistics
        """
        if not transactions:
            return ReportSummary(
                total_transactions=0,
                total_amount=Decimal('0'),
                matched_count=0,
                unmatched_count=0,
                match_rate=0.0,
                receipts_attached=0,
                receipts_missing=0,
                receipt_rate=0.0,
                average_transaction=Decimal('0'),
                largest_transaction=Decimal('0'),
                smallest_transaction=Decimal('0'),
                date_range_start=datetime.now(),
                date_range_end=datetime.now(),
            )

        # Basic stats
        amounts = [abs(t.amount) for t in transactions]
        total_amount = sum(amounts)

        matched = [t for t in transactions if t.review_status in ('MATCHED', 'VERIFIED', 'APPROVED')]
        receipts_attached = [t for t in transactions if t.has_receipt]

        dates = [t.date for t in transactions if t.date]

        # Category breakdown
        category_totals = defaultdict(lambda: {'total': Decimal('0'), 'count': 0, 'transactions': []})
        for txn in transactions:
            cat = self._normalize_category(txn.effective_category)
            category_totals[cat]['total'] += abs(txn.amount)
            category_totals[cat]['count'] += 1
            category_totals[cat]['transactions'].append(txn)

        categories = []
        for cat, data in sorted(category_totals.items(), key=lambda x: x[1]['total'], reverse=True):
            categories.append(CategoryBreakdown(
                category=cat,
                total=data['total'],
                count=data['count'],
                percentage=float(data['total'] / total_amount * 100) if total_amount else 0,
                transactions=data['transactions']
            ))

        # Vendor breakdown
        vendor_data = defaultdict(lambda: {
            'total': Decimal('0'),
            'count': 0,
            'dates': [],
            'categories': set()
        })

        for txn in transactions:
            vendor = self._normalize_vendor(txn.description)
            vendor_data[vendor]['total'] += abs(txn.amount)
            vendor_data[vendor]['count'] += 1
            if txn.date:
                vendor_data[vendor]['dates'].append(txn.date)
            vendor_data[vendor]['categories'].add(txn.effective_category)

        vendors = []
        for vendor, data in sorted(vendor_data.items(), key=lambda x: x[1]['total'], reverse=True)[:50]:
            dates_list = data['dates']
            vendors.append(VendorBreakdown(
                vendor=vendor,
                normalized_name=vendor,
                total=data['total'],
                count=data['count'],
                average=data['total'] / data['count'] if data['count'] else Decimal('0'),
                is_recurring=data['count'] >= 3,  # 3+ transactions = recurring
                first_transaction=min(dates_list) if dates_list else datetime.now(),
                last_transaction=max(dates_list) if dates_list else datetime.now(),
                categories=list(data['categories'])
            ))

        # Monthly trends
        monthly_data = defaultdict(lambda: {'total': Decimal('0'), 'count': 0, 'categories': defaultdict(Decimal)})
        for txn in transactions:
            if txn.date:
                key = (txn.date.year, txn.date.month)
                monthly_data[key]['total'] += abs(txn.amount)
                monthly_data[key]['count'] += 1
                monthly_data[key]['categories'][txn.effective_category] += abs(txn.amount)

        trends = []
        for (year, month), data in sorted(monthly_data.items()):
            trends.append(MonthlyTrend(
                year=year,
                month=month,
                total=data['total'],
                count=data['count'],
                by_category=dict(data['categories'])
            ))

        return ReportSummary(
            total_transactions=len(transactions),
            total_amount=total_amount,
            matched_count=len(matched),
            unmatched_count=len(transactions) - len(matched),
            match_rate=len(matched) / len(transactions) * 100 if transactions else 0,
            receipts_attached=len(receipts_attached),
            receipts_missing=len(transactions) - len(receipts_attached),
            receipt_rate=len(receipts_attached) / len(transactions) * 100 if transactions else 0,
            average_transaction=total_amount / len(transactions) if transactions else Decimal('0'),
            largest_transaction=max(amounts) if amounts else Decimal('0'),
            smallest_transaction=min(amounts) if amounts else Decimal('0'),
            date_range_start=min(dates) if dates else datetime.now(),
            date_range_end=max(dates) if dates else datetime.now(),
            by_category=categories,
            by_vendor=vendors,
            monthly_trends=trends,
        )

    def generate_report_id(self, business_type: str, report_type: ReportType) -> str:
        """Generate unique report ID."""
        abbrev = BUSINESS_ABBREV.get(business_type, "GEN")
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        type_code = report_type.value[:3].upper()
        return f"RPT-{abbrev}-{type_code}-{timestamp}"

    def generate_report(
        self,
        date_range: Tuple[str, str],
        business_types: Optional[List[str]] = None,
        report_type: ReportType = ReportType.EXPENSE_DETAIL,
        options: Optional[Dict] = None,
    ) -> Report:
        """
        Generate comprehensive expense report.

        Args:
            date_range: Tuple of (start_date, end_date) in YYYY-MM-DD format
            business_types: List of business types to include (None for all)
            report_type: Type of report to generate
            options: Additional options dict
                - include_receipts: bool - Include receipt URLs
                - include_unmatched: bool - Include unmatched transactions
                - group_by: str - Grouping method (category, vendor, date)
                - include_submitted: bool - Include already submitted

        Returns:
            Report object with all data
        """
        options = options or {}
        start_date, end_date = date_range

        # Determine business type for report
        if not business_types or business_types == ['all']:
            business_type = "All"
        elif len(business_types) == 1:
            business_type = business_types[0]
        else:
            business_type = "Multiple"

        # Fetch transactions
        all_transactions = []
        types_to_fetch = business_types if business_types and business_types != ['all'] else [None]

        for bt in types_to_fetch:
            txns = self.fetch_transactions(
                business_type=bt,
                date_from=start_date,
                date_to=end_date,
                include_submitted=options.get('include_submitted', False)
            )
            all_transactions.extend(txns)

        # Remove duplicates by index
        seen = set()
        transactions = []
        for t in all_transactions:
            if t.index not in seen:
                seen.add(t.index)
                transactions.append(t)

        # Filter unmatched if requested
        if not options.get('include_unmatched', True):
            transactions = [t for t in transactions if t.review_status in ('MATCHED', 'VERIFIED', 'APPROVED')]

        # Calculate statistics
        summary = self.calculate_statistics(transactions)

        # Generate report ID
        report_id = self.generate_report_id(business_type, report_type)

        # Generate report name
        start_dt = self._parse_date(start_date) or datetime.now()
        end_dt = self._parse_date(end_date) or datetime.now()
        report_name = f"{business_type} Expenses - {start_dt.strftime('%b %Y')}"
        if start_dt.month != end_dt.month or start_dt.year != end_dt.year:
            report_name = f"{business_type} Expenses - {start_dt.strftime('%b %d')} to {end_dt.strftime('%b %d, %Y')}"

        return Report(
            report_id=report_id,
            report_name=report_name,
            report_type=report_type,
            business_type=business_type,
            generated_at=datetime.now(),
            date_range=(start_dt, end_dt),
            summary=summary,
            transactions=transactions,
            metadata={
                'options': options,
                'business_types_included': business_types or ['all'],
                'generator_version': '2.0.0',
            }
        )

    def generate_business_summary_report(
        self,
        date_range: Tuple[str, str],
        options: Optional[Dict] = None
    ) -> Dict[str, Report]:
        """
        Generate summary reports for all business types.

        Returns:
            Dict mapping business type to Report
        """
        business_types = ["Business", "Secondary", "Personal", "EM.co"]
        reports = {}

        for bt in business_types:
            report = self.generate_report(
                date_range=date_range,
                business_types=[bt],
                report_type=ReportType.BUSINESS_SUMMARY,
                options=options
            )
            reports[bt] = report

        return reports

    def generate_reconciliation_report(
        self,
        date_range: Tuple[str, str],
        business_type: Optional[str] = None,
    ) -> Report:
        """
        Generate reconciliation report showing matched vs unmatched transactions.
        """
        transactions = self.fetch_transactions(
            business_type=business_type,
            date_from=date_range[0],
            date_to=date_range[1],
            include_submitted=True
        )

        # Group by match status
        matched = [t for t in transactions if t.review_status in ('MATCHED', 'VERIFIED', 'APPROVED')]
        unmatched = [t for t in transactions if t.review_status not in ('MATCHED', 'VERIFIED', 'APPROVED')]
        missing_receipts = [t for t in transactions if not t.has_receipt]

        summary = self.calculate_statistics(transactions)

        report_id = self.generate_report_id(business_type or "All", ReportType.RECONCILIATION)

        return Report(
            report_id=report_id,
            report_name=f"Reconciliation Report - {business_type or 'All Business Types'}",
            report_type=ReportType.RECONCILIATION,
            business_type=business_type or "All",
            generated_at=datetime.now(),
            date_range=(
                self._parse_date(date_range[0]) or datetime.now(),
                self._parse_date(date_range[1]) or datetime.now()
            ),
            summary=summary,
            transactions=transactions,
            metadata={
                'matched_count': len(matched),
                'unmatched_count': len(unmatched),
                'missing_receipts_count': len(missing_receipts),
                'unmatched_indices': [t.index for t in unmatched],
                'missing_receipt_indices': [t.index for t in missing_receipts],
            }
        )

    def generate_vendor_analysis_report(
        self,
        date_range: Tuple[str, str],
        business_type: Optional[str] = None,
        top_n: int = 25,
    ) -> Report:
        """
        Generate vendor analysis report with spending patterns.
        """
        transactions = self.fetch_transactions(
            business_type=business_type,
            date_from=date_range[0],
            date_to=date_range[1],
            include_submitted=True
        )

        summary = self.calculate_statistics(transactions)

        # Enhanced vendor analysis
        vendor_details = {}
        for vendor in summary.by_vendor[:top_n]:
            vendor_txns = [t for t in transactions
                         if self._normalize_vendor(t.description) == vendor.vendor]

            # Calculate trend (comparing first half vs second half)
            if len(vendor_txns) >= 4:
                mid = len(vendor_txns) // 2
                first_half_avg = sum(abs(t.amount) for t in vendor_txns[:mid]) / mid
                second_half_avg = sum(abs(t.amount) for t in vendor_txns[mid:]) / (len(vendor_txns) - mid)
                trend = "increasing" if second_half_avg > first_half_avg * 1.1 else \
                       "decreasing" if second_half_avg < first_half_avg * 0.9 else "stable"
            else:
                trend = "insufficient_data"

            vendor_details[vendor.vendor] = {
                'trend': trend,
                'monthly_average': float(vendor.total / max(1, len(summary.monthly_trends))),
                'transaction_dates': [t.date.isoformat() if t.date else None for t in vendor_txns],
            }

        report_id = self.generate_report_id(business_type or "All", ReportType.VENDOR_ANALYSIS)

        return Report(
            report_id=report_id,
            report_name=f"Vendor Analysis - {business_type or 'All Business Types'}",
            report_type=ReportType.VENDOR_ANALYSIS,
            business_type=business_type or "All",
            generated_at=datetime.now(),
            date_range=(
                self._parse_date(date_range[0]) or datetime.now(),
                self._parse_date(date_range[1]) or datetime.now()
            ),
            summary=summary,
            transactions=transactions,
            metadata={
                'top_vendors': top_n,
                'vendor_details': vendor_details,
                'recurring_vendors': [v.vendor for v in summary.by_vendor if v.is_recurring],
                'one_time_vendors': [v.vendor for v in summary.by_vendor if not v.is_recurring],
            }
        )


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_generator_instance = None

def get_report_generator(db=None, receipt_dir=None) -> ExpenseReportGenerator:
    """Get or create report generator instance."""
    global _generator_instance
    if _generator_instance is None or db is not None:
        _generator_instance = ExpenseReportGenerator(db=db, receipt_dir=receipt_dir)
    return _generator_instance

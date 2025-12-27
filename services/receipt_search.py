#!/usr/bin/env python3
"""
Receipt Search Service
=======================
Advanced search engine for the Receipt Library.

Features:
- Natural language query parsing
- Full-text search with relevance ranking
- Fuzzy merchant matching
- Complex filter combinations
- Search suggestions and autocomplete
- Search history and saved searches

Performance target: <100ms search results
"""

import os
import re
import json
import logging
from datetime import datetime, date, timedelta
from decimal import Decimal
from typing import Optional, List, Dict, Any, Tuple
from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from db_mysql import MySQLReceiptDatabase

logger = logging.getLogger(__name__)


# =============================================================================
# DATA CLASSES
# =============================================================================

@dataclass
class ParsedQuery:
    """Parsed search query with extracted components."""
    raw_query: str = ""
    text_terms: List[str] = field(default_factory=list)
    filters: Dict[str, Any] = field(default_factory=dict)

    # Extracted filters
    merchant: Optional[str] = None
    amount_min: Optional[Decimal] = None
    amount_max: Optional[Decimal] = None
    amount_exact: Optional[Decimal] = None
    date_from: Optional[date] = None
    date_to: Optional[date] = None
    business_type: Optional[str] = None
    status: Optional[str] = None
    source: Optional[str] = None
    tags: List[str] = field(default_factory=list)
    has_receipt: Optional[bool] = None
    needs_review: Optional[bool] = None
    is_favorite: Optional[bool] = None

    def has_filters(self) -> bool:
        """Check if query has any filters."""
        return bool(
            self.merchant or self.amount_min or self.amount_max or self.amount_exact or
            self.date_from or self.date_to or self.business_type or self.status or
            self.source or self.tags or self.has_receipt is not None or
            self.needs_review is not None or self.is_favorite is not None
        )


@dataclass
class SearchResult:
    """A single search result."""
    id: int
    uuid: str
    merchant_name: str
    merchant_normalized: str
    amount: float
    receipt_date: date
    status: str
    business_type: str
    thumbnail_key: str
    storage_key: str
    source: str
    match_confidence: float
    is_favorite: bool
    needs_review: bool
    relevance_score: float = 0.0
    highlight: Dict[str, str] = field(default_factory=dict)


@dataclass
class SearchResults:
    """Container for search results."""
    query: str
    results: List[SearchResult] = field(default_factory=list)
    total_count: int = 0
    page: int = 1
    per_page: int = 50
    took_ms: float = 0.0
    suggestions: List[str] = field(default_factory=list)


@dataclass
class SearchSuggestion:
    """A search suggestion."""
    text: str
    type: str  # 'merchant', 'tag', 'filter', 'recent'
    count: Optional[int] = None


# =============================================================================
# QUERY PARSER
# =============================================================================

class QueryParser:
    """
    Parse natural language search queries into structured filters.

    Supports operators like:
    - merchant:starbucks
    - amount:>100 or amount:<50 or amount:25.99
    - date:today, date:yesterday, date:this-week, date:last-month
    - date:2024-01-15, date:jan-2024
    - type:sec or type:personal
    - status:unmatched or status:ready
    - from:gmail or from:scanner
    - #tag or tag:expense
    - is:favorite, is:starred, is:review
    """

    # Regex patterns for operators
    PATTERNS = {
        'merchant': re.compile(r'merchant:(\S+)', re.IGNORECASE),
        'amount_gt': re.compile(r'amount:>(\d+(?:\.\d{2})?)', re.IGNORECASE),
        'amount_lt': re.compile(r'amount:<(\d+(?:\.\d{2})?)', re.IGNORECASE),
        'amount_exact': re.compile(r'amount:(\d+(?:\.\d{2})?)', re.IGNORECASE),
        'date': re.compile(r'date:([\w-]+)', re.IGNORECASE),
        'type': re.compile(r'type:(\w+)', re.IGNORECASE),
        'status': re.compile(r'status:(\w+)', re.IGNORECASE),
        'from': re.compile(r'from:(\w+)', re.IGNORECASE),
        'tag': re.compile(r'tag:(\S+)', re.IGNORECASE),
        'hashtag': re.compile(r'#(\w+)', re.IGNORECASE),
        'is': re.compile(r'is:(\w+)', re.IGNORECASE),
    }

    # Date shortcuts
    DATE_SHORTCUTS = {
        'today': lambda: (date.today(), date.today()),
        'yesterday': lambda: (date.today() - timedelta(days=1), date.today() - timedelta(days=1)),
        'this-week': lambda: (date.today() - timedelta(days=date.today().weekday()), date.today()),
        'last-week': lambda: (
            date.today() - timedelta(days=date.today().weekday() + 7),
            date.today() - timedelta(days=date.today().weekday() + 1)
        ),
        'this-month': lambda: (date.today().replace(day=1), date.today()),
        'last-month': lambda: (
            (date.today().replace(day=1) - timedelta(days=1)).replace(day=1),
            date.today().replace(day=1) - timedelta(days=1)
        ),
        'this-year': lambda: (date(date.today().year, 1, 1), date.today()),
        'last-year': lambda: (date(date.today().year - 1, 1, 1), date(date.today().year - 1, 12, 31)),
    }

    # Business type aliases
    TYPE_ALIASES = {
        'biz': 'business',
        'business': 'business',
        'business': 'business',
        'sec': 'sec',
        'rodeo': 'sec',
        'personal': 'personal',
        'me': 'personal',
        'ceo': 'ceo',
        'emco': 'em_co',
        'em-co': 'em_co',
    }

    # Status aliases
    STATUS_ALIASES = {
        'new': 'processing',
        'pending': 'processing',
        'ready': 'ready',
        'unmatched': 'ready',
        'matched': 'matched',
        'linked': 'matched',
        'dup': 'duplicate',
        'duplicate': 'duplicate',
        'rejected': 'rejected',
        'archived': 'archived',
    }

    # Source aliases
    SOURCE_ALIASES = {
        'gmail': ['gmail_personal', 'gmail_sec', 'gmail_business'],
        'email': ['gmail_personal', 'gmail_sec', 'gmail_business', 'forwarded_email'],
        'scanner': ['scanner_mobile', 'scanner_web'],
        'scan': ['scanner_mobile', 'scanner_web'],
        'upload': ['manual_upload'],
        'manual': ['manual_upload'],
    }

    def parse(self, query: str) -> ParsedQuery:
        """Parse a query string into structured components."""
        parsed = ParsedQuery(raw_query=query)

        if not query:
            return parsed

        remaining = query

        # Extract merchant filter
        match = self.PATTERNS['merchant'].search(remaining)
        if match:
            parsed.merchant = match.group(1).replace('"', '').replace("'", '')
            remaining = remaining.replace(match.group(0), '')

        # Extract amount filters
        match = self.PATTERNS['amount_gt'].search(remaining)
        if match:
            parsed.amount_min = Decimal(match.group(1))
            remaining = remaining.replace(match.group(0), '')

        match = self.PATTERNS['amount_lt'].search(remaining)
        if match:
            parsed.amount_max = Decimal(match.group(1))
            remaining = remaining.replace(match.group(0), '')

        match = self.PATTERNS['amount_exact'].search(remaining)
        if match and not parsed.amount_min and not parsed.amount_max:
            parsed.amount_exact = Decimal(match.group(1))
            remaining = remaining.replace(match.group(0), '')

        # Extract date filter
        match = self.PATTERNS['date'].search(remaining)
        if match:
            date_value = match.group(1).lower()
            if date_value in self.DATE_SHORTCUTS:
                parsed.date_from, parsed.date_to = self.DATE_SHORTCUTS[date_value]()
            else:
                # Try to parse as date
                parsed_date = self._parse_date_string(date_value)
                if parsed_date:
                    parsed.date_from = parsed_date
                    parsed.date_to = parsed_date
            remaining = remaining.replace(match.group(0), '')

        # Extract business type filter
        match = self.PATTERNS['type'].search(remaining)
        if match:
            type_value = match.group(1).lower()
            parsed.business_type = self.TYPE_ALIASES.get(type_value, type_value)
            remaining = remaining.replace(match.group(0), '')

        # Extract status filter
        match = self.PATTERNS['status'].search(remaining)
        if match:
            status_value = match.group(1).lower()
            parsed.status = self.STATUS_ALIASES.get(status_value, status_value)
            remaining = remaining.replace(match.group(0), '')

        # Extract source filter
        match = self.PATTERNS['from'].search(remaining)
        if match:
            source_value = match.group(1).lower()
            parsed.source = source_value
            remaining = remaining.replace(match.group(0), '')

        # Extract tags
        for match in self.PATTERNS['tag'].finditer(remaining):
            parsed.tags.append(match.group(1))
        remaining = self.PATTERNS['tag'].sub('', remaining)

        for match in self.PATTERNS['hashtag'].finditer(remaining):
            parsed.tags.append(match.group(1))
        remaining = self.PATTERNS['hashtag'].sub('', remaining)

        # Extract is: filters
        for match in self.PATTERNS['is'].finditer(remaining):
            value = match.group(1).lower()
            if value in ('favorite', 'fav', 'starred'):
                parsed.is_favorite = True
            elif value in ('review', 'needs-review'):
                parsed.needs_review = True
            elif value in ('matched', 'linked'):
                parsed.has_receipt = True
            elif value in ('unmatched', 'missing'):
                parsed.has_receipt = False
        remaining = self.PATTERNS['is'].sub('', remaining)

        # Remaining text becomes search terms
        remaining = remaining.strip()
        if remaining:
            # Split into terms, keeping quoted phrases together
            parsed.text_terms = self._tokenize(remaining)

        return parsed

    def _parse_date_string(self, date_str: str) -> Optional[date]:
        """Try to parse various date formats."""
        formats = [
            '%Y-%m-%d',
            '%m/%d/%Y',
            '%m-%d-%Y',
            '%d-%m-%Y',
            '%b-%Y',
            '%B-%Y',
        ]

        for fmt in formats:
            try:
                return datetime.strptime(date_str, fmt).date()
            except ValueError:
                continue

        # Try month-year format
        month_patterns = [
            (r'jan(?:uary)?[-\s]?(\d{4})', 1),
            (r'feb(?:ruary)?[-\s]?(\d{4})', 2),
            (r'mar(?:ch)?[-\s]?(\d{4})', 3),
            (r'apr(?:il)?[-\s]?(\d{4})', 4),
            (r'may[-\s]?(\d{4})', 5),
            (r'jun(?:e)?[-\s]?(\d{4})', 6),
            (r'jul(?:y)?[-\s]?(\d{4})', 7),
            (r'aug(?:ust)?[-\s]?(\d{4})', 8),
            (r'sep(?:tember)?[-\s]?(\d{4})', 9),
            (r'oct(?:ober)?[-\s]?(\d{4})', 10),
            (r'nov(?:ember)?[-\s]?(\d{4})', 11),
            (r'dec(?:ember)?[-\s]?(\d{4})', 12),
        ]

        for pattern, month in month_patterns:
            match = re.match(pattern, date_str, re.IGNORECASE)
            if match:
                year = int(match.group(1))
                return date(year, month, 1)

        return None

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text, keeping quoted phrases together."""
        tokens = []
        current_token = ""
        in_quotes = False

        for char in text:
            if char == '"':
                in_quotes = not in_quotes
            elif char == ' ' and not in_quotes:
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
            else:
                current_token += char

        if current_token:
            tokens.append(current_token)

        return tokens


# =============================================================================
# RECEIPT SEARCH SERVICE
# =============================================================================

class ReceiptSearchService:
    """
    Advanced search service for the Receipt Library.

    Provides:
    - Natural language search parsing
    - Full-text search with MySQL FULLTEXT
    - Fuzzy merchant matching
    - Complex filter combinations
    - Search suggestions
    """

    def __init__(self):
        self.db = MySQLReceiptDatabase()
        self.parser = QueryParser()
        self._suggestion_cache = {}
        self._merchant_cache = None
        self._tag_cache = None

    def search(
        self,
        query: str,
        page: int = 1,
        per_page: int = 50,
        sort_by: str = "relevance",
        sort_order: str = "desc"
    ) -> SearchResults:
        """
        Search receipts with natural language query.

        Examples:
        - "starbucks" - Search for Starbucks receipts
        - "merchant:starbucks amount:>20" - Starbucks over $20
        - "type:sec date:last-month" - MCR receipts from last month
        - "#client-meal is:favorite" - Favorite client meal receipts
        """
        import time
        start_time = time.time()

        results = SearchResults(query=query, page=page, per_page=per_page)

        if not self.db.use_mysql:
            return results

        # Parse query
        parsed = self.parser.parse(query)

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Build WHERE clauses
            where_clauses = ["r.deleted_at IS NULL"]
            params = []

            # Full-text search on text terms
            if parsed.text_terms:
                search_text = ' '.join(parsed.text_terms)
                # Use MATCH AGAINST for full-text search
                where_clauses.append("""
                    (MATCH(r.merchant_name, r.ocr_raw_text, r.ai_description, r.user_notes)
                     AGAINST(%s IN NATURAL LANGUAGE MODE)
                     OR r.merchant_normalized LIKE %s
                     OR r.merchant_name LIKE %s)
                """)
                params.extend([search_text, f"%{search_text.lower()}%", f"%{search_text}%"])

            # Merchant filter
            if parsed.merchant:
                where_clauses.append("r.merchant_normalized LIKE %s")
                params.append(f"%{parsed.merchant.lower()}%")

            # Amount filters
            if parsed.amount_exact:
                where_clauses.append("ABS(r.amount - %s) < 0.01")
                params.append(float(parsed.amount_exact))
            else:
                if parsed.amount_min:
                    where_clauses.append("r.amount >= %s")
                    params.append(float(parsed.amount_min))
                if parsed.amount_max:
                    where_clauses.append("r.amount <= %s")
                    params.append(float(parsed.amount_max))

            # Date filters
            if parsed.date_from:
                where_clauses.append("r.receipt_date >= %s")
                params.append(parsed.date_from)
            if parsed.date_to:
                where_clauses.append("r.receipt_date <= %s")
                params.append(parsed.date_to)

            # Business type filter
            if parsed.business_type:
                where_clauses.append("r.business_type = %s")
                params.append(parsed.business_type)

            # Status filter
            if parsed.status:
                where_clauses.append("r.status = %s")
                params.append(parsed.status)

            # Source filter
            if parsed.source:
                source_values = QueryParser.SOURCE_ALIASES.get(parsed.source, [parsed.source])
                placeholders = ','.join(['%s'] * len(source_values))
                where_clauses.append(f"r.source IN ({placeholders})")
                params.extend(source_values)

            # Tag filters
            for tag in parsed.tags:
                where_clauses.append("JSON_CONTAINS(r.tags, %s)")
                params.append(json.dumps(tag))

            # Boolean filters
            if parsed.has_receipt is not None:
                if parsed.has_receipt:
                    where_clauses.append("r.matched_transaction_id IS NOT NULL")
                else:
                    where_clauses.append("r.matched_transaction_id IS NULL")

            if parsed.needs_review is not None:
                where_clauses.append("r.needs_review = %s")
                params.append(parsed.needs_review)

            if parsed.is_favorite is not None:
                where_clauses.append("r.is_favorite = %s")
                params.append(parsed.is_favorite)

            where_sql = " AND ".join(where_clauses)

            # Get total count
            cursor.execute(f"SELECT COUNT(*) as count FROM receipt_library r WHERE {where_sql}", params)
            results.total_count = cursor.fetchone()['count']

            # Build ORDER BY
            if sort_by == "relevance" and parsed.text_terms:
                search_text = ' '.join(parsed.text_terms)
                order_sql = f"""
                    MATCH(r.merchant_name, r.ocr_raw_text, r.ai_description, r.user_notes)
                    AGAINST(%s IN NATURAL LANGUAGE MODE) DESC
                """
                params.append(search_text)
            else:
                valid_sort = {'created_at', 'receipt_date', 'amount', 'merchant_normalized'}
                sort_field = sort_by if sort_by in valid_sort else 'created_at'
                order_sql = f"r.{sort_field} {'DESC' if sort_order == 'desc' else 'ASC'}"

            # Calculate offset
            offset = (page - 1) * per_page

            # Fetch results
            cursor.execute(f"""
                SELECT
                    r.id, r.uuid, r.merchant_name, r.merchant_normalized,
                    r.amount, r.receipt_date, r.status, r.business_type,
                    r.thumbnail_key, r.storage_key, r.source,
                    r.match_confidence, r.is_favorite, r.needs_review
                FROM receipt_library r
                WHERE {where_sql}
                ORDER BY {order_sql}
                LIMIT %s OFFSET %s
            """, params + [per_page, offset])

            for row in cursor.fetchall():
                result = SearchResult(
                    id=row['id'],
                    uuid=row['uuid'],
                    merchant_name=row['merchant_name'] or '',
                    merchant_normalized=row['merchant_normalized'] or '',
                    amount=float(row['amount']) if row['amount'] else 0,
                    receipt_date=row['receipt_date'],
                    status=row['status'],
                    business_type=row['business_type'],
                    thumbnail_key=row['thumbnail_key'] or '',
                    storage_key=row['storage_key'] or '',
                    source=row['source'],
                    match_confidence=row['match_confidence'] or 0,
                    is_favorite=bool(row['is_favorite']),
                    needs_review=bool(row['needs_review'])
                )
                results.results.append(result)

            # Get suggestions if no results
            if not results.results and query:
                results.suggestions = self.get_suggestions(query)

        results.took_ms = (time.time() - start_time) * 1000
        return results

    def get_suggestions(self, partial: str, limit: int = 10) -> List[str]:
        """Get search suggestions for partial query."""
        if not self.db.use_mysql or not partial:
            return []

        suggestions = []
        partial_lower = partial.lower()

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            # Suggest merchants
            cursor.execute("""
                SELECT DISTINCT merchant_normalized, COUNT(*) as cnt
                FROM receipt_library
                WHERE merchant_normalized LIKE %s
                  AND deleted_at IS NULL
                GROUP BY merchant_normalized
                ORDER BY cnt DESC
                LIMIT %s
            """, (f"%{partial_lower}%", limit))

            for row in cursor.fetchall():
                if row['merchant_normalized']:
                    suggestions.append(row['merchant_normalized'])

            # Suggest filter completions
            if partial.startswith('type:'):
                remaining = partial[5:].lower()
                for alias, value in QueryParser.TYPE_ALIASES.items():
                    if alias.startswith(remaining):
                        suggestions.append(f"type:{alias}")

            elif partial.startswith('status:'):
                remaining = partial[7:].lower()
                for alias in QueryParser.STATUS_ALIASES.keys():
                    if alias.startswith(remaining):
                        suggestions.append(f"status:{alias}")

            elif partial.startswith('date:'):
                remaining = partial[5:].lower()
                for shortcut in QueryParser.DATE_SHORTCUTS.keys():
                    if shortcut.startswith(remaining):
                        suggestions.append(f"date:{shortcut}")

        return suggestions[:limit]

    def get_top_merchants(self, limit: int = 20) -> List[Dict]:
        """Get top merchants for filter dropdown."""
        if not self.db.use_mysql:
            return []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT merchant_normalized, COUNT(*) as count
                FROM receipt_library
                WHERE merchant_normalized IS NOT NULL
                  AND deleted_at IS NULL
                GROUP BY merchant_normalized
                ORDER BY count DESC
                LIMIT %s
            """, (limit,))

            return [{'merchant': row['merchant_normalized'], 'count': row['count']}
                    for row in cursor.fetchall()]

    def get_all_tags(self) -> List[Dict]:
        """Get all tags with counts."""
        if not self.db.use_mysql:
            return []

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT tags FROM receipt_library
                WHERE tags IS NOT NULL AND deleted_at IS NULL
            """)

            tag_counts = defaultdict(int)
            for row in cursor.fetchall():
                if row['tags']:
                    tags = json.loads(row['tags']) if isinstance(row['tags'], str) else row['tags']
                    for tag in tags:
                        tag_counts[tag] += 1

            return [{'tag': tag, 'count': count}
                    for tag, count in sorted(tag_counts.items(), key=lambda x: -x[1])]

    def quick_stats(self) -> Dict:
        """Get quick stats for search UI."""
        if not self.db.use_mysql:
            return {}

        with self.db.pooled_connection() as conn:
            cursor = conn.cursor()

            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) as unmatched,
                    SUM(CASE WHEN needs_review = TRUE THEN 1 ELSE 0 END) as needs_review,
                    SUM(CASE WHEN receipt_date >= DATE_SUB(CURDATE(), INTERVAL 30 DAY) THEN 1 ELSE 0 END) as this_month
                FROM receipt_library
                WHERE deleted_at IS NULL
            """)

            row = cursor.fetchone()
            return {
                'total': row['total'] or 0,
                'unmatched': row['unmatched'] or 0,
                'needs_review': row['needs_review'] or 0,
                'this_month': row['this_month'] or 0
            }


# =============================================================================
# SINGLETON AND CONVENIENCE FUNCTIONS
# =============================================================================

_search_service = None


def get_search_service() -> ReceiptSearchService:
    """Get or create the singleton search service."""
    global _search_service
    if _search_service is None:
        _search_service = ReceiptSearchService()
    return _search_service


def search_receipts(query: str, page: int = 1, per_page: int = 50) -> SearchResults:
    """Search receipts with natural language query."""
    return get_search_service().search(query, page, per_page)


def get_suggestions(partial: str) -> List[str]:
    """Get search suggestions."""
    return get_search_service().get_suggestions(partial)


def parse_query(query: str) -> ParsedQuery:
    """Parse a search query."""
    return QueryParser().parse(query)

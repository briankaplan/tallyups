"""
PDF Expense Report Exporter
===========================

Generates professional audit-ready PDF reports with:
- Cover page with summary statistics
- Detailed transaction listings
- Receipt thumbnails embedded
- Category charts and visualizations
- Professional formatting for auditors
"""

import io
import logging
import base64
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING
import requests

if TYPE_CHECKING:
    from reportlab.graphics.shapes import Drawing

logger = logging.getLogger(__name__)

# Try to import PDF libraries
try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import letter, A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import inch, mm
    from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
        PageBreak, Image as RLImage, KeepTogether
    )
    from reportlab.graphics.shapes import Drawing, Rect
    from reportlab.graphics.charts.piecharts import Pie
    from reportlab.graphics.charts.barcharts import VerticalBarChart
    from reportlab.graphics.charts.legends import Legend
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    logger.warning("reportlab not installed - PDF export will be limited")

try:
    from PIL import Image as PILImage
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# Brand colors - only define if reportlab is available
if HAS_REPORTLAB:
    BRAND_GREEN = colors.HexColor('#00FF88')
    BRAND_GREEN_DARK = colors.HexColor('#00CC6B')
    DARK_BG = colors.HexColor('#0B0D10')
    PANEL_BG = colors.HexColor('#1A1A1A')
    TEXT_COLOR = colors.HexColor('#F0F0F0')
    MUTED_COLOR = colors.HexColor('#888888')
    SUCCESS_COLOR = colors.HexColor('#00FF88')
    WARNING_COLOR = colors.HexColor('#FFD85E')
    ERROR_COLOR = colors.HexColor('#FF4E6A')
else:
    # Stub values when reportlab not available
    BRAND_GREEN = BRAND_GREEN_DARK = DARK_BG = PANEL_BG = None
    TEXT_COLOR = MUTED_COLOR = SUCCESS_COLOR = WARNING_COLOR = ERROR_COLOR = None


class PDFExporter:
    """
    Generate professional PDF expense reports.
    """

    def __init__(self, receipt_dir: Optional[Path] = None):
        """Initialize PDF exporter."""
        self.receipt_dir = receipt_dir or Path("receipts")
        self.styles = None

        if not HAS_REPORTLAB:
            logger.warning("reportlab not available - install with: pip install reportlab")

    def _init_styles(self):
        """Initialize paragraph styles."""
        if self.styles:
            return

        self.styles = getSampleStyleSheet()

        # Title style
        self.styles.add(ParagraphStyle(
            name='ReportTitle',
            parent=self.styles['Heading1'],
            fontSize=24,
            textColor=BRAND_GREEN,
            spaceAfter=20,
            alignment=TA_CENTER,
        ))

        # Subtitle style
        self.styles.add(ParagraphStyle(
            name='ReportSubtitle',
            parent=self.styles['Normal'],
            fontSize=12,
            textColor=MUTED_COLOR,
            spaceAfter=10,
            alignment=TA_CENTER,
        ))

        # Section header
        self.styles.add(ParagraphStyle(
            name='SectionHeader',
            parent=self.styles['Heading2'],
            fontSize=16,
            textColor=BRAND_GREEN,
            spaceBefore=20,
            spaceAfter=12,
            borderWidth=1,
            borderColor=BRAND_GREEN,
            borderPadding=5,
        ))

        # Metric label
        self.styles.add(ParagraphStyle(
            name='MetricLabel',
            parent=self.styles['Normal'],
            fontSize=10,
            textColor=MUTED_COLOR,
        ))

        # Metric value
        self.styles.add(ParagraphStyle(
            name='MetricValue',
            parent=self.styles['Normal'],
            fontSize=14,
            textColor=colors.black,
            fontName='Helvetica-Bold',
        ))

        # Table header
        self.styles.add(ParagraphStyle(
            name='TableHeader',
            parent=self.styles['Normal'],
            fontSize=9,
            textColor=colors.white,
            fontName='Helvetica-Bold',
            alignment=TA_CENTER,
        ))

        # Table cell
        self.styles.add(ParagraphStyle(
            name='TableCell',
            parent=self.styles['Normal'],
            fontSize=8,
            textColor=colors.black,
        ))

    def _format_currency(self, amount: Decimal) -> str:
        """Format amount as currency."""
        return f"${float(amount):,.2f}"

    def _format_percentage(self, value: float) -> str:
        """Format value as percentage."""
        return f"{value:.1f}%"

    def _fetch_receipt_thumbnail(self, url: str, max_size: Tuple[int, int] = (100, 100)) -> Optional[bytes]:
        """Fetch and resize receipt image for embedding."""
        if not HAS_PIL or not url:
            return None

        try:
            # Fetch image
            if url.startswith('http'):
                response = requests.get(url, timeout=10)
                if response.status_code != 200:
                    return None
                img_data = io.BytesIO(response.content)
            else:
                # Local file
                img_path = self.receipt_dir / url
                if not img_path.exists():
                    return None
                img_data = open(img_path, 'rb')

            # Resize with PIL
            img = PILImage.open(img_data)
            img.thumbnail(max_size, PILImage.Resampling.LANCZOS)

            # Convert to bytes
            output = io.BytesIO()
            img.save(output, format='PNG')
            output.seek(0)

            return output.getvalue()

        except Exception as e:
            logger.debug(f"Could not fetch receipt thumbnail: {e}")
            return None

    def _create_pie_chart(self, data: List[Tuple[str, float]], title: str = "") -> 'Drawing':
        """Create a pie chart drawing."""
        drawing = Drawing(300, 200)

        pie = Pie()
        pie.x = 100
        pie.y = 25
        pie.width = 100
        pie.height = 100
        pie.data = [d[1] for d in data[:8]]  # Limit to 8 slices
        pie.labels = [d[0][:15] for d in data[:8]]

        # Colors
        chart_colors = [
            colors.HexColor('#00FF88'),
            colors.HexColor('#00CC6B'),
            colors.HexColor('#FFD85E'),
            colors.HexColor('#FF6B9D'),
            colors.HexColor('#6B8AFF'),
            colors.HexColor('#FF8C42'),
            colors.HexColor('#B19CD9'),
            colors.HexColor('#77DD77'),
        ]

        for i in range(len(data[:8])):
            pie.slices[i].fillColor = chart_colors[i % len(chart_colors)]
            pie.slices[i].strokeWidth = 0.5

        drawing.add(pie)

        # Add legend
        legend = Legend()
        legend.x = 220
        legend.y = 100
        legend.dx = 8
        legend.dy = 8
        legend.fontName = 'Helvetica'
        legend.fontSize = 7
        legend.boxAnchor = 'w'
        legend.columnMaximum = 8
        legend.strokeWidth = 0.5
        legend.strokeColor = colors.black
        legend.deltax = 75
        legend.deltay = 10
        legend.autoXPadding = 5
        legend.yGap = 0
        legend.dxTextSpace = 5
        legend.alignment = 'right'
        legend.dividerLines = 0
        legend.dividerOffsY = 4.5
        legend.subCols.rpad = 30
        legend.colorNamePairs = [(chart_colors[i], data[i][0][:20]) for i in range(len(data[:8]))]

        drawing.add(legend)

        return drawing

    def export_report(self, report: 'Report', include_receipts: bool = False) -> bytes:
        """
        Export report to PDF.

        Args:
            report: Report object to export
            include_receipts: Whether to embed receipt thumbnails

        Returns:
            PDF file as bytes
        """
        if not HAS_REPORTLAB:
            raise ImportError("reportlab required for PDF export. Install with: pip install reportlab")

        self._init_styles()

        # Create PDF buffer
        buffer = io.BytesIO()

        # Create document
        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch,
            title=report.report_name,
            author="Tallyups Expense System",
        )

        # Build story (content)
        story = []

        # Cover page
        story.extend(self._create_cover_page(report))

        # Summary statistics
        story.append(PageBreak())
        story.extend(self._create_summary_section(report))

        # Category breakdown
        story.append(PageBreak())
        story.extend(self._create_category_section(report))

        # Vendor analysis
        story.extend(self._create_vendor_section(report))

        # Transaction detail
        story.append(PageBreak())
        story.extend(self._create_transactions_section(report, include_receipts))

        # Build PDF
        doc.build(story)

        buffer.seek(0)
        return buffer.getvalue()

    def _create_cover_page(self, report: 'Report') -> List:
        """Create cover page elements."""
        elements = []

        # Add spacing at top
        elements.append(Spacer(1, 2*inch))

        # Title
        elements.append(Paragraph(
            report.report_name,
            self.styles['ReportTitle']
        ))

        # Subtitle
        elements.append(Paragraph(
            f"Business Type: {report.business_type}",
            self.styles['ReportSubtitle']
        ))

        elements.append(Spacer(1, 0.3*inch))

        # Date range
        elements.append(Paragraph(
            f"Period: {report.date_range[0].strftime('%B %d, %Y')} - {report.date_range[1].strftime('%B %d, %Y')}",
            self.styles['ReportSubtitle']
        ))

        elements.append(Spacer(1, 1*inch))

        # Key metrics box
        metrics_data = [
            ['TOTAL EXPENSES', 'TRANSACTIONS', 'MATCH RATE', 'RECEIPT RATE'],
            [
                self._format_currency(report.summary.total_amount),
                str(report.summary.total_transactions),
                self._format_percentage(report.summary.match_rate),
                self._format_percentage(report.summary.receipt_rate),
            ]
        ]

        metrics_table = Table(metrics_data, colWidths=[1.5*inch]*4)
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('TEXTCOLOR', (0, 0), (-1, 0), MUTED_COLOR),
            ('FONTNAME', (0, 1), (-1, 1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 1), (-1, 1), 16),
            ('TEXTCOLOR', (0, 1), (0, 1), BRAND_GREEN),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
            ('BOX', (0, 0), (-1, -1), 1, BRAND_GREEN),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#333333')),
        ]))

        elements.append(metrics_table)

        elements.append(Spacer(1, 2*inch))

        # Generated info
        elements.append(Paragraph(
            f"Generated: {report.generated_at.strftime('%B %d, %Y at %I:%M %p')}",
            self.styles['ReportSubtitle']
        ))

        elements.append(Paragraph(
            f"Report ID: {report.report_id}",
            self.styles['ReportSubtitle']
        ))

        return elements

    def _create_summary_section(self, report: 'Report') -> List:
        """Create summary statistics section."""
        elements = []

        elements.append(Paragraph("Summary Statistics", self.styles['SectionHeader']))

        # Two-column layout for metrics
        metrics_left = [
            ("Total Transactions", str(report.summary.total_transactions)),
            ("Total Amount", self._format_currency(report.summary.total_amount)),
            ("Average Transaction", self._format_currency(report.summary.average_transaction)),
            ("Largest Transaction", self._format_currency(report.summary.largest_transaction)),
            ("Smallest Transaction", self._format_currency(report.summary.smallest_transaction)),
        ]

        metrics_right = [
            ("Matched Transactions", str(report.summary.matched_count)),
            ("Unmatched Transactions", str(report.summary.unmatched_count)),
            ("Match Rate", self._format_percentage(report.summary.match_rate)),
            ("Receipts Attached", str(report.summary.receipts_attached)),
            ("Receipts Missing", str(report.summary.receipts_missing)),
        ]

        # Create metrics table
        table_data = []
        for (l_label, l_value), (r_label, r_value) in zip(metrics_left, metrics_right):
            table_data.append([l_label, l_value, r_label, r_value])

        metrics_table = Table(table_data, colWidths=[2*inch, 1.5*inch, 2*inch, 1.5*inch])
        metrics_table.setStyle(TableStyle([
            ('ALIGN', (0, 0), (0, -1), 'LEFT'),
            ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
            ('ALIGN', (2, 0), (2, -1), 'LEFT'),
            ('ALIGN', (3, 0), (3, -1), 'RIGHT'),
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica'),
            ('FONTNAME', (1, 0), (1, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica'),
            ('FONTNAME', (3, 0), (3, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 10),
            ('TEXTCOLOR', (0, 0), (0, -1), MUTED_COLOR),
            ('TEXTCOLOR', (2, 0), (2, -1), MUTED_COLOR),
            ('TOPPADDING', (0, 0), (-1, -1), 8),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
            ('LINEBELOW', (0, 0), (-1, -2), 0.5, colors.HexColor('#DDDDDD')),
        ]))

        elements.append(metrics_table)
        elements.append(Spacer(1, 0.5*inch))

        return elements

    def _create_category_section(self, report: 'Report') -> List:
        """Create category breakdown section."""
        elements = []

        elements.append(Paragraph("Spending by Category", self.styles['SectionHeader']))

        if not report.summary.by_category:
            elements.append(Paragraph("No category data available", self.styles['Normal']))
            return elements

        # Pie chart
        chart_data = [(c.category, float(c.total)) for c in report.summary.by_category[:8]]
        if chart_data:
            pie_chart = self._create_pie_chart(chart_data, "Category Distribution")
            elements.append(pie_chart)
            elements.append(Spacer(1, 0.3*inch))

        # Category table
        table_data = [['Category', 'Amount', 'Count', '% of Total']]
        for cat in report.summary.by_category[:15]:
            table_data.append([
                cat.category[:40],
                self._format_currency(cat.total),
                str(cat.count),
                self._format_percentage(cat.percentage),
            ])

        cat_table = Table(table_data, colWidths=[3*inch, 1.5*inch, 1*inch, 1*inch])
        cat_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN_DARK),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0, 1), (-1, -1), 6),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 6),
        ]))

        elements.append(cat_table)
        elements.append(Spacer(1, 0.5*inch))

        return elements

    def _create_vendor_section(self, report: 'Report') -> List:
        """Create vendor analysis section."""
        elements = []

        elements.append(Paragraph("Top Vendors", self.styles['SectionHeader']))

        if not report.summary.by_vendor:
            elements.append(Paragraph("No vendor data available", self.styles['Normal']))
            return elements

        # Vendor table
        table_data = [['Vendor', 'Total', 'Count', 'Avg', 'Recurring']]
        for vendor in report.summary.by_vendor[:20]:
            table_data.append([
                vendor.vendor[:35],
                self._format_currency(vendor.total),
                str(vendor.count),
                self._format_currency(vendor.average),
                'Yes' if vendor.is_recurring else 'No',
            ])

        vendor_table = Table(table_data, colWidths=[2.5*inch, 1.2*inch, 0.8*inch, 1*inch, 0.8*inch])
        vendor_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN_DARK),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 9),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 8),
            ('TOPPADDING', (0, 0), (-1, 0), 8),
            ('ALIGN', (0, 1), (0, -1), 'LEFT'),
            ('ALIGN', (1, 1), (-1, -1), 'RIGHT'),
            ('ALIGN', (4, 1), (4, -1), 'CENTER'),
            ('FONTSIZE', (0, 1), (-1, -1), 8),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F5F5F5')]),
            ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0, 1), (-1, -1), 5),
            ('BOTTOMPADDING', (0, 1), (-1, -1), 5),
        ]))

        elements.append(vendor_table)

        return elements

    def _create_transactions_section(self, report: 'Report', include_receipts: bool = False) -> List:
        """Create transaction detail section."""
        elements = []

        elements.append(Paragraph("Transaction Details", self.styles['SectionHeader']))
        elements.append(Paragraph(
            f"Total: {len(report.transactions)} transactions",
            self.styles['ReportSubtitle']
        ))
        elements.append(Spacer(1, 0.2*inch))

        if not report.transactions:
            elements.append(Paragraph("No transactions in this report", self.styles['Normal']))
            return elements

        # Transaction table - split into batches for page handling
        batch_size = 30
        for i in range(0, len(report.transactions), batch_size):
            batch = report.transactions[i:i+batch_size]

            table_data = [['Date', 'Description', 'Amount', 'Category', 'Status', 'Receipt']]

            for txn in batch:
                date_str = txn.date.strftime('%m/%d/%y') if txn.date else ''
                desc = txn.description[:40] if txn.description else ''
                status = txn.review_status[:10] if txn.review_status else ''
                receipt = 'Yes' if txn.has_receipt else 'No'

                table_data.append([
                    date_str,
                    desc,
                    self._format_currency(abs(txn.amount)),
                    txn.effective_category[:25],
                    status,
                    receipt,
                ])

            txn_table = Table(table_data, colWidths=[0.7*inch, 2.3*inch, 0.9*inch, 1.5*inch, 0.7*inch, 0.5*inch])
            txn_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN_DARK),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, 0), 8),
                ('FONTSIZE', (0, 1), (-1, -1), 7),
                ('ALIGN', (2, 1), (2, -1), 'RIGHT'),
                ('ALIGN', (4, 1), (5, -1), 'CENTER'),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#F8F8F8')]),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
                ('TOPPADDING', (0, 0), (-1, -1), 4),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
                ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ('RIGHTPADDING', (0, 0), (-1, -1), 4),
            ]))

            # Color code receipt column
            for row_idx, txn in enumerate(batch, 1):
                if txn.has_receipt:
                    txn_table.setStyle(TableStyle([
                        ('BACKGROUND', (5, row_idx), (5, row_idx), SUCCESS_COLOR),
                        ('TEXTCOLOR', (5, row_idx), (5, row_idx), colors.black),
                    ]))
                else:
                    txn_table.setStyle(TableStyle([
                        ('BACKGROUND', (5, row_idx), (5, row_idx), ERROR_COLOR),
                        ('TEXTCOLOR', (5, row_idx), (5, row_idx), colors.white),
                    ]))

            elements.append(KeepTogether([txn_table]))
            elements.append(Spacer(1, 0.2*inch))

        return elements

    def export_reconciliation_report(self, report: 'Report') -> bytes:
        """Export reconciliation-focused PDF report."""
        if not HAS_REPORTLAB:
            raise ImportError("reportlab required for PDF export")

        self._init_styles()

        buffer = io.BytesIO()

        doc = SimpleDocTemplate(
            buffer,
            pagesize=letter,
            rightMargin=0.5*inch,
            leftMargin=0.5*inch,
            topMargin=0.5*inch,
            bottomMargin=0.5*inch,
            title=f"Reconciliation Report - {report.business_type}",
        )

        story = []

        # Title
        story.append(Paragraph(
            f"Reconciliation Report",
            self.styles['ReportTitle']
        ))

        story.append(Paragraph(
            f"{report.business_type} | {report.date_range[0].strftime('%m/%d/%Y')} - {report.date_range[1].strftime('%m/%d/%Y')}",
            self.styles['ReportSubtitle']
        ))

        story.append(Spacer(1, 0.5*inch))

        # Reconciliation summary
        matched = [t for t in report.transactions if t.review_status in ('MATCHED', 'VERIFIED', 'APPROVED')]
        unmatched = [t for t in report.transactions if t.review_status not in ('MATCHED', 'VERIFIED', 'APPROVED')]
        missing_receipts = [t for t in report.transactions if not t.has_receipt]

        summary_data = [
            ['Status', 'Count', 'Amount'],
            ['Matched/Verified', len(matched), self._format_currency(sum(abs(t.amount) for t in matched))],
            ['Unmatched', len(unmatched), self._format_currency(sum(abs(t.amount) for t in unmatched))],
            ['Missing Receipts', len(missing_receipts), self._format_currency(sum(abs(t.amount) for t in missing_receipts))],
            ['Total', len(report.transactions), self._format_currency(report.summary.total_amount)],
        ]

        summary_table = Table(summary_data, colWidths=[2*inch, 1.5*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), BRAND_GREEN_DARK),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#333333')),
            ('TEXTCOLOR', (0, -1), (-1, -1), colors.white),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 1, colors.HexColor('#DDDDDD')),
            ('TOPPADDING', (0, 0), (-1, -1), 10),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 10),
        ]))

        story.append(summary_table)

        # Unmatched transactions section
        if unmatched:
            story.append(PageBreak())
            story.append(Paragraph(
                f"Unmatched Transactions ({len(unmatched)})",
                self.styles['SectionHeader']
            ))

            unmatched_data = [['Date', 'Description', 'Amount', 'Category']]
            for txn in unmatched[:50]:  # Limit to 50
                unmatched_data.append([
                    txn.date.strftime('%m/%d/%y') if txn.date else '',
                    txn.description[:45],
                    self._format_currency(abs(txn.amount)),
                    txn.effective_category[:20],
                ])

            unmatched_table = Table(unmatched_data, colWidths=[0.8*inch, 3*inch, 1*inch, 1.5*inch])
            unmatched_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), ERROR_COLOR),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FFF5F5')]),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))

            story.append(unmatched_table)

        # Missing receipts section
        if missing_receipts:
            story.append(PageBreak())
            story.append(Paragraph(
                f"Missing Receipts ({len(missing_receipts)})",
                self.styles['SectionHeader']
            ))

            missing_data = [['Date', 'Description', 'Amount', 'Status']]
            for txn in missing_receipts[:50]:
                missing_data.append([
                    txn.date.strftime('%m/%d/%y') if txn.date else '',
                    txn.description[:45],
                    self._format_currency(abs(txn.amount)),
                    txn.review_status or 'Unknown',
                ])

            missing_table = Table(missing_data, colWidths=[0.8*inch, 3*inch, 1*inch, 1.5*inch])
            missing_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), WARNING_COLOR),
                ('TEXTCOLOR', (0, 0), (-1, 0), colors.black),
                ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                ('FONTSIZE', (0, 0), (-1, -1), 8),
                ('ALIGN', (2, 0), (2, -1), 'RIGHT'),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#DDDDDD')),
                ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#FFFBF0')]),
                ('TOPPADDING', (0, 0), (-1, -1), 5),
                ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
            ]))

            story.append(missing_table)

        doc.build(story)
        buffer.seek(0)

        return buffer.getvalue()


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_exporter_instance = None

def get_pdf_exporter(receipt_dir: Optional[Path] = None) -> PDFExporter:
    """Get or create PDF exporter instance."""
    global _exporter_instance
    if _exporter_instance is None:
        _exporter_instance = PDFExporter(receipt_dir=receipt_dir)
    return _exporter_instance

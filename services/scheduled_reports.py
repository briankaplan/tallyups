"""
Scheduled Reports Service
=========================

Automated report generation and delivery system.
Supports:
- Weekly/monthly/quarterly schedules
- Email delivery
- Multiple recipients
- Custom templates
"""

import json
import logging
import smtplib
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import os

logger = logging.getLogger(__name__)


class ScheduleFrequency(Enum):
    """Report schedule frequencies."""
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"


class ReportDeliveryMethod(Enum):
    """How to deliver the report."""
    EMAIL = "email"
    SAVE_TO_DISK = "save_to_disk"
    WEBHOOK = "webhook"


@dataclass
class ScheduledReport:
    """Configuration for a scheduled report."""
    id: str
    name: str
    frequency: ScheduleFrequency
    business_types: List[str]
    report_type: str  # expense_detail, reconciliation, vendor_analysis
    export_format: str  # excel, pdf, csv
    delivery_method: ReportDeliveryMethod
    recipients: List[str] = field(default_factory=list)  # Email addresses
    webhook_url: Optional[str] = None
    save_path: Optional[str] = None
    enabled: bool = True
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    day_of_week: int = 0  # 0=Monday for weekly
    day_of_month: int = 1  # For monthly
    time_of_day: str = "09:00"  # HH:MM
    options: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            'id': self.id,
            'name': self.name,
            'frequency': self.frequency.value,
            'business_types': self.business_types,
            'report_type': self.report_type,
            'export_format': self.export_format,
            'delivery_method': self.delivery_method.value,
            'recipients': self.recipients,
            'webhook_url': self.webhook_url,
            'save_path': self.save_path,
            'enabled': self.enabled,
            'last_run': self.last_run.isoformat() if self.last_run else None,
            'next_run': self.next_run.isoformat() if self.next_run else None,
            'day_of_week': self.day_of_week,
            'day_of_month': self.day_of_month,
            'time_of_day': self.time_of_day,
            'options': self.options,
        }

    @classmethod
    def from_dict(cls, data: Dict) -> 'ScheduledReport':
        """Create from dictionary."""
        return cls(
            id=data['id'],
            name=data['name'],
            frequency=ScheduleFrequency(data['frequency']),
            business_types=data.get('business_types', ['all']),
            report_type=data.get('report_type', 'expense_detail'),
            export_format=data.get('export_format', 'excel'),
            delivery_method=ReportDeliveryMethod(data.get('delivery_method', 'email')),
            recipients=data.get('recipients', []),
            webhook_url=data.get('webhook_url'),
            save_path=data.get('save_path'),
            enabled=data.get('enabled', True),
            last_run=datetime.fromisoformat(data['last_run']) if data.get('last_run') else None,
            next_run=datetime.fromisoformat(data['next_run']) if data.get('next_run') else None,
            day_of_week=data.get('day_of_week', 0),
            day_of_month=data.get('day_of_month', 1),
            time_of_day=data.get('time_of_day', '09:00'),
            options=data.get('options', {}),
        )


class ScheduledReportService:
    """
    Service for managing and executing scheduled reports.
    """

    def __init__(
        self,
        db=None,
        config_path: Optional[Path] = None,
        smtp_config: Optional[Dict] = None,
    ):
        """
        Initialize scheduled report service.

        Args:
            db: Database connection
            config_path: Path to store schedule configurations
            smtp_config: SMTP configuration for email delivery
        """
        self.db = db
        self.config_path = config_path or Path("data/scheduled_reports.json")
        self.config_path.parent.mkdir(parents=True, exist_ok=True)

        self.smtp_config = smtp_config or {
            'host': os.environ.get('SMTP_HOST', 'smtp.gmail.com'),
            'port': int(os.environ.get('SMTP_PORT', '587')),
            'user': os.environ.get('SMTP_USER', ''),
            'password': os.environ.get('SMTP_PASSWORD', ''),
            'from_email': os.environ.get('SMTP_FROM', 'reports@tallyups.com'),
            'from_name': os.environ.get('SMTP_FROM_NAME', 'Tallyups Reports'),
        }

        self.schedules: Dict[str, ScheduledReport] = {}
        self._load_schedules()

        self._running = False
        self._thread: Optional[threading.Thread] = None

        logger.info(f"ScheduledReportService initialized with {len(self.schedules)} schedules")

    def _load_schedules(self):
        """Load schedules from config file."""
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r') as f:
                    data = json.load(f)

                for schedule_data in data.get('schedules', []):
                    schedule = ScheduledReport.from_dict(schedule_data)
                    self.schedules[schedule.id] = schedule

                logger.info(f"Loaded {len(self.schedules)} scheduled reports")

            except Exception as e:
                logger.error(f"Error loading schedules: {e}")

    def _save_schedules(self):
        """Save schedules to config file."""
        try:
            data = {
                'schedules': [s.to_dict() for s in self.schedules.values()],
                'updated_at': datetime.now().isoformat(),
            }

            with open(self.config_path, 'w') as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            logger.error(f"Error saving schedules: {e}")

    def create_schedule(self, schedule: ScheduledReport) -> str:
        """
        Create a new scheduled report.

        Args:
            schedule: ScheduledReport configuration

        Returns:
            Schedule ID
        """
        # Calculate next run time
        schedule.next_run = self._calculate_next_run(schedule)

        self.schedules[schedule.id] = schedule
        self._save_schedules()

        logger.info(f"Created scheduled report: {schedule.name} (next run: {schedule.next_run})")

        return schedule.id

    def update_schedule(self, schedule_id: str, updates: Dict) -> bool:
        """Update an existing schedule."""
        if schedule_id not in self.schedules:
            return False

        schedule = self.schedules[schedule_id]

        # Update fields
        for key, value in updates.items():
            if hasattr(schedule, key):
                if key == 'frequency':
                    value = ScheduleFrequency(value)
                elif key == 'delivery_method':
                    value = ReportDeliveryMethod(value)
                setattr(schedule, key, value)

        # Recalculate next run
        schedule.next_run = self._calculate_next_run(schedule)

        self._save_schedules()
        return True

    def delete_schedule(self, schedule_id: str) -> bool:
        """Delete a scheduled report."""
        if schedule_id in self.schedules:
            del self.schedules[schedule_id]
            self._save_schedules()
            return True
        return False

    def get_schedule(self, schedule_id: str) -> Optional[ScheduledReport]:
        """Get a schedule by ID."""
        return self.schedules.get(schedule_id)

    def list_schedules(self) -> List[ScheduledReport]:
        """List all schedules."""
        return list(self.schedules.values())

    def _calculate_next_run(self, schedule: ScheduledReport) -> datetime:
        """Calculate the next run time for a schedule."""
        now = datetime.now()
        time_parts = schedule.time_of_day.split(':')
        run_hour = int(time_parts[0])
        run_minute = int(time_parts[1]) if len(time_parts) > 1 else 0

        if schedule.frequency == ScheduleFrequency.DAILY:
            # Next day at specified time
            next_run = now.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)
            if next_run <= now:
                next_run += timedelta(days=1)

        elif schedule.frequency == ScheduleFrequency.WEEKLY:
            # Next week on specified day
            days_ahead = schedule.day_of_week - now.weekday()
            if days_ahead <= 0:  # Target day already happened this week
                days_ahead += 7
            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)

        elif schedule.frequency == ScheduleFrequency.BIWEEKLY:
            # Every two weeks on specified day
            days_ahead = schedule.day_of_week - now.weekday()
            if days_ahead <= 0:
                days_ahead += 14
            next_run = now + timedelta(days=days_ahead)
            next_run = next_run.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)

        elif schedule.frequency == ScheduleFrequency.MONTHLY:
            # Next month on specified day
            if now.day >= schedule.day_of_month:
                # Next month
                if now.month == 12:
                    next_run = now.replace(year=now.year + 1, month=1, day=schedule.day_of_month)
                else:
                    next_run = now.replace(month=now.month + 1, day=schedule.day_of_month)
            else:
                next_run = now.replace(day=schedule.day_of_month)
            next_run = next_run.replace(hour=run_hour, minute=run_minute, second=0, microsecond=0)

        elif schedule.frequency == ScheduleFrequency.QUARTERLY:
            # First of next quarter
            quarter = (now.month - 1) // 3
            next_quarter_month = (quarter + 1) * 3 + 1
            if next_quarter_month > 12:
                next_quarter_month = 1
                year = now.year + 1
            else:
                year = now.year
            next_run = datetime(year, next_quarter_month, schedule.day_of_month, run_hour, run_minute)

        else:
            next_run = now + timedelta(days=1)

        return next_run

    def _get_date_range(self, schedule: ScheduledReport) -> tuple:
        """Get date range for report based on frequency."""
        now = datetime.now()

        if schedule.frequency == ScheduleFrequency.DAILY:
            # Yesterday
            end = now - timedelta(days=1)
            start = end
        elif schedule.frequency == ScheduleFrequency.WEEKLY:
            # Last 7 days
            end = now - timedelta(days=1)
            start = end - timedelta(days=6)
        elif schedule.frequency == ScheduleFrequency.BIWEEKLY:
            # Last 14 days
            end = now - timedelta(days=1)
            start = end - timedelta(days=13)
        elif schedule.frequency == ScheduleFrequency.MONTHLY:
            # Last month
            if now.month == 1:
                start = datetime(now.year - 1, 12, 1)
                end = datetime(now.year - 1, 12, 31)
            else:
                start = datetime(now.year, now.month - 1, 1)
                from calendar import monthrange
                last_day = monthrange(now.year, now.month - 1)[1]
                end = datetime(now.year, now.month - 1, last_day)
        elif schedule.frequency == ScheduleFrequency.QUARTERLY:
            # Last quarter
            quarter = (now.month - 1) // 3
            if quarter == 0:
                start = datetime(now.year - 1, 10, 1)
                end = datetime(now.year - 1, 12, 31)
            else:
                quarter_start_month = (quarter - 1) * 3 + 1
                start = datetime(now.year, quarter_start_month, 1)
                quarter_end_month = quarter * 3
                from calendar import monthrange
                last_day = monthrange(now.year, quarter_end_month)[1]
                end = datetime(now.year, quarter_end_month, last_day)
        else:
            end = now - timedelta(days=1)
            start = end - timedelta(days=30)

        return (start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d'))

    def run_schedule(self, schedule_id: str) -> bool:
        """
        Manually trigger a scheduled report.

        Args:
            schedule_id: ID of schedule to run

        Returns:
            True if successful
        """
        schedule = self.schedules.get(schedule_id)
        if not schedule:
            logger.error(f"Schedule not found: {schedule_id}")
            return False

        return self._execute_schedule(schedule)

    def _execute_schedule(self, schedule: ScheduledReport) -> bool:
        """Execute a scheduled report."""
        logger.info(f"Executing scheduled report: {schedule.name}")

        try:
            # Import report generator
            from services.report_generator import get_report_generator, ReportType

            generator = get_report_generator(db=self.db)

            # Get date range
            date_from, date_to = self._get_date_range(schedule)

            # Map report type
            type_map = {
                "expense_detail": ReportType.EXPENSE_DETAIL,
                "business_summary": ReportType.BUSINESS_SUMMARY,
                "reconciliation": ReportType.RECONCILIATION,
                "vendor_analysis": ReportType.VENDOR_ANALYSIS,
            }
            rpt_type = type_map.get(schedule.report_type, ReportType.EXPENSE_DETAIL)

            # Generate report
            if schedule.report_type == "reconciliation":
                report = generator.generate_reconciliation_report(
                    date_range=(date_from, date_to),
                    business_type=schedule.business_types[0] if len(schedule.business_types) == 1 else None
                )
            elif schedule.report_type == "vendor_analysis":
                report = generator.generate_vendor_analysis_report(
                    date_range=(date_from, date_to),
                    business_type=schedule.business_types[0] if len(schedule.business_types) == 1 else None
                )
            else:
                report = generator.generate_report(
                    date_range=(date_from, date_to),
                    business_types=schedule.business_types if schedule.business_types != ['all'] else None,
                    report_type=rpt_type,
                    options=schedule.options
                )

            # Export in requested format
            if schedule.export_format == "excel":
                from services.excel_exporter import get_excel_exporter
                exporter = get_excel_exporter()
                content = exporter.export_report(report)
                filename = f"{report.report_id}.xlsx"
                content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

            elif schedule.export_format == "pdf":
                from services.pdf_exporter import get_pdf_exporter
                exporter = get_pdf_exporter()
                content = exporter.export_report(report)
                filename = f"{report.report_id}.pdf"
                content_type = "application/pdf"

            elif schedule.export_format == "csv":
                from services.csv_exporter import get_csv_exporter
                exporter = get_csv_exporter()
                content = exporter.export_standard_csv(report)
                filename = f"{report.report_id}.csv"
                content_type = "text/csv"

            else:
                logger.error(f"Unsupported export format: {schedule.export_format}")
                return False

            # Deliver report
            if schedule.delivery_method == ReportDeliveryMethod.EMAIL:
                self._send_email(schedule, content, filename, content_type, report)

            elif schedule.delivery_method == ReportDeliveryMethod.SAVE_TO_DISK:
                self._save_to_disk(schedule, content, filename)

            elif schedule.delivery_method == ReportDeliveryMethod.WEBHOOK:
                self._send_webhook(schedule, content, filename, report)

            # Update schedule
            schedule.last_run = datetime.now()
            schedule.next_run = self._calculate_next_run(schedule)
            self._save_schedules()

            logger.info(f"Successfully executed scheduled report: {schedule.name}")
            return True

        except Exception as e:
            logger.error(f"Error executing scheduled report {schedule.name}: {e}")
            import traceback
            traceback.print_exc()
            return False

    def _send_email(
        self,
        schedule: ScheduledReport,
        content: bytes,
        filename: str,
        content_type: str,
        report: Any
    ):
        """Send report via email."""
        if not schedule.recipients:
            logger.warning(f"No recipients for email delivery: {schedule.name}")
            return

        if not self.smtp_config.get('user'):
            logger.warning("SMTP not configured - skipping email delivery")
            return

        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.smtp_config['from_name']} <{self.smtp_config['from_email']}>"
            msg['To'] = ', '.join(schedule.recipients)
            msg['Subject'] = f"Expense Report: {schedule.name} - {datetime.now().strftime('%B %d, %Y')}"

            # Email body
            body = f"""
Hello,

Your scheduled expense report "{schedule.name}" is ready.

Report Summary:
- Total Transactions: {report.summary.total_transactions}
- Total Amount: ${float(report.summary.total_amount):,.2f}
- Match Rate: {report.summary.match_rate:.1f}%
- Receipt Rate: {report.summary.receipt_rate:.1f}%
- Date Range: {report.date_range[0].strftime('%m/%d/%Y')} - {report.date_range[1].strftime('%m/%d/%Y')}

The detailed report is attached.

Best regards,
Tallyups Expense System
"""
            msg.attach(MIMEText(body, 'plain'))

            # Attach report
            attachment = MIMEApplication(content)
            attachment.add_header('Content-Disposition', 'attachment', filename=filename)
            attachment.add_header('Content-Type', content_type)
            msg.attach(attachment)

            # Send email
            with smtplib.SMTP(self.smtp_config['host'], self.smtp_config['port']) as server:
                server.starttls()
                server.login(self.smtp_config['user'], self.smtp_config['password'])
                server.send_message(msg)

            logger.info(f"Email sent to {len(schedule.recipients)} recipients")

        except Exception as e:
            logger.error(f"Error sending email: {e}")

    def _save_to_disk(self, schedule: ScheduledReport, content: bytes, filename: str):
        """Save report to disk."""
        save_dir = Path(schedule.save_path or "reports/scheduled")
        save_dir.mkdir(parents=True, exist_ok=True)

        # Add timestamp to filename
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        name, ext = filename.rsplit('.', 1)
        final_filename = f"{name}_{timestamp}.{ext}"

        save_path = save_dir / final_filename

        with open(save_path, 'wb') as f:
            f.write(content)

        logger.info(f"Report saved to: {save_path}")

    def _send_webhook(self, schedule: ScheduledReport, content: bytes, filename: str, report: Any):
        """Send report via webhook."""
        if not schedule.webhook_url:
            logger.warning("No webhook URL configured")
            return

        try:
            import requests
            import base64

            payload = {
                'schedule_id': schedule.id,
                'schedule_name': schedule.name,
                'report_id': report.report_id,
                'filename': filename,
                'summary': report.to_dict()['summary'],
                'content_base64': base64.b64encode(content).decode('utf-8'),
                'generated_at': datetime.now().isoformat(),
            }

            response = requests.post(
                schedule.webhook_url,
                json=payload,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            if response.status_code == 200:
                logger.info(f"Webhook delivered successfully")
            else:
                logger.warning(f"Webhook returned status {response.status_code}")

        except Exception as e:
            logger.error(f"Error sending webhook: {e}")

    def start_scheduler(self, check_interval: int = 60):
        """
        Start the background scheduler.

        Args:
            check_interval: Seconds between schedule checks
        """
        if self._running:
            logger.warning("Scheduler already running")
            return

        self._running = True
        self._thread = threading.Thread(target=self._scheduler_loop, args=(check_interval,), daemon=True)
        self._thread.start()

        logger.info("Scheduled report service started")

    def stop_scheduler(self):
        """Stop the background scheduler."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
        logger.info("Scheduled report service stopped")

    def _scheduler_loop(self, check_interval: int):
        """Main scheduler loop."""
        while self._running:
            try:
                now = datetime.now()

                for schedule in self.schedules.values():
                    if not schedule.enabled:
                        continue

                    if schedule.next_run and schedule.next_run <= now:
                        logger.info(f"Running scheduled report: {schedule.name}")
                        self._execute_schedule(schedule)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")

            time.sleep(check_interval)


# =============================================================================
# SINGLETON ACCESS
# =============================================================================

_service_instance = None

def get_scheduled_report_service(db=None, **kwargs) -> ScheduledReportService:
    """Get or create scheduled report service instance."""
    global _service_instance
    if _service_instance is None or db is not None:
        _service_instance = ScheduledReportService(db=db, **kwargs)
    return _service_instance


# =============================================================================
# DEFAULT SCHEDULES
# =============================================================================

def create_default_schedules(service: ScheduledReportService):
    """Create default scheduled reports."""

    # Weekly Business Summary (Monday 9 AM)
    if 'weekly_business' not in service.schedules:
        service.create_schedule(ScheduledReport(
            id='weekly_business',
            name='Weekly Business Summary',
            frequency=ScheduleFrequency.WEEKLY,
            business_types=['Business'],
            report_type='expense_detail',
            export_format='excel',
            delivery_method=ReportDeliveryMethod.SAVE_TO_DISK,
            day_of_week=0,  # Monday
            time_of_day='09:00',
        ))

    # Monthly All Business Summary (1st of month)
    if 'monthly_all' not in service.schedules:
        service.create_schedule(ScheduledReport(
            id='monthly_all',
            name='Monthly All Business Summary',
            frequency=ScheduleFrequency.MONTHLY,
            business_types=['all'],
            report_type='business_summary',
            export_format='excel',
            delivery_method=ReportDeliveryMethod.SAVE_TO_DISK,
            day_of_month=1,
            time_of_day='08:00',
        ))

    # Quarterly Reconciliation (1st of quarter)
    if 'quarterly_reconciliation' not in service.schedules:
        service.create_schedule(ScheduledReport(
            id='quarterly_reconciliation',
            name='Quarterly Reconciliation Report',
            frequency=ScheduleFrequency.QUARTERLY,
            business_types=['all'],
            report_type='reconciliation',
            export_format='pdf',
            delivery_method=ReportDeliveryMethod.SAVE_TO_DISK,
            day_of_month=1,
            time_of_day='08:00',
        ))

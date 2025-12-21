"""
ReceiptAI Routes Package
========================
Flask blueprints for modular route organization.

Blueprints:
- notes_bp:    /api/notes/*    - AI note generation (5 routes)
- incoming_bp: /api/incoming/* - Gmail inbox system (8 routes)
- reports_bp:  /api/reports/*  - Expense reports (9 routes)
- library_bp:  /api/library/*  - Receipt library (8 routes)
- calendar_bp: /api/calendar/* - Google Calendar integration (10 routes)
- gmail_bp:    /api/gmail/*    - Gmail receipt processing (10 routes)
- contacts_bp: /api/contacts/* - Contact management & ATLAS (12 routes)

Total: 60+ routes
"""

from flask import Blueprint

# Import all blueprints
from .notes import notes_bp
from .incoming import incoming_bp
from .reports import reports_bp
from .library import library_bp
from .calendar import calendar_bp
from .gmail import gmail_bp
from .contacts import contacts_bp

# Export for easy registration
__all__ = [
    'notes_bp',
    'incoming_bp',
    'reports_bp',
    'library_bp',
    'calendar_bp',
    'gmail_bp',
    'contacts_bp',
]

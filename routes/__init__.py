"""
ReceiptAI Routes Package
========================
Flask blueprints for modular route organization.

Blueprints:
- notes_bp:        /api/notes/*        - AI note generation (5 routes)
- incoming_bp:     /api/incoming/*     - Gmail inbox system (8 routes)
- reports_bp:      /api/reports/*      - Expense reports (9 routes)
- library_bp:      /api/library/*      - Receipt library (8 routes)
- calendar_bp:     /api/calendar/*     - Google Calendar integration (10 routes)
- gmail_bp:        /api/gmail/*        - Gmail receipt processing (10 routes)
- contacts_bp:     /api/contacts/*     - Contact management (12 routes)
- atlas_bp:        /api/atlas/*        - ATLAS Relationship Intelligence (67 routes)
- transactions_bp: /api/transactions/* - Transaction CRUD & linking (15 routes)
- ocr_bp:          /api/ocr/*          - OCR processing & verification (10 routes)
- ai_bp:           /api/ai/*           - Gemini AI categorization & Apple splits (11 routes)
- contact_hub_bp:  /api/contact-hub/*  - ATLAS Contact Hub CRM integration (31 routes)

Total: 190+ routes
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
from .atlas import atlas_bp
from .transactions import transactions_bp
from .ocr import ocr_bp
from .ai import ai_bp
from .contact_hub import contact_hub_bp

# Export for easy registration
__all__ = [
    'notes_bp',
    'incoming_bp',
    'reports_bp',
    'library_bp',
    'calendar_bp',
    'gmail_bp',
    'contacts_bp',
    'atlas_bp',
    'transactions_bp',
    'ocr_bp',
    'ai_bp',
    'contact_hub_bp',
]

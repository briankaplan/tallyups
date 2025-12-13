"""
ReceiptAI Routes Package
========================
Flask blueprints for modular route organization.

Blueprints:
- notes_bp:    /api/notes/*    - AI note generation (5 routes)
- incoming_bp: /api/incoming/* - Gmail inbox system (8 routes)
- reports_bp:  /api/reports/*  - Expense reports (9 routes)
- library_bp:  /api/library/*  - Receipt library (8 routes)

Total: 30 routes extracted from viewer_server.py
"""

from flask import Blueprint

# Import all blueprints
from .notes import notes_bp
from .incoming import incoming_bp
from .reports import reports_bp
from .library import library_bp

# Export for easy registration
__all__ = [
    'notes_bp',
    'incoming_bp',
    'reports_bp',
    'library_bp',
]

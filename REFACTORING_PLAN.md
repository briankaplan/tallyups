# Tallyups Refactoring Plan

## Overview

The codebase has grown organically and needs restructuring to improve maintainability. This document outlines the refactoring priorities.

## Critical Issues

### 1. Monolithic `viewer_server.py` (30,084 lines)

**Current State:**
- 357 routes defined in main file
- 101 routes already extracted to `routes/` modules
- Contains utility functions, database helpers, and business logic mixed together

**Recommended Structure:**

```
viewer_server.py (< 500 lines)
├── App initialization
├── Blueprint registration
├── Error handlers
└── Security middleware

routes/
├── atlas.py         # 55 routes - relationship intelligence
├── transactions.py  # 14 routes - transaction CRUD
├── ocr.py          # 12 routes - OCR processing
├── ai.py           # 11 routes - AI features
├── contact_hub.py  # 30 routes - contact management
├── auth.py         # Authentication (existing)
├── library.py      # Receipt library (existing)
├── incoming.py     # Incoming receipts (existing)
├── reports.py      # Reports (existing)
├── gmail.py        # Gmail integration (existing)
├── contacts.py     # Contacts (existing)
└── admin.py        # Admin (existing)

utils/
├── db.py           # Database helpers
├── cache.py        # Caching utilities
├── vision.py       # Vision/OCR utilities
├── matching.py     # Receipt matching logic
└── security.py     # Security helpers
```

### 2. Other Large Files

| File | Lines | Recommended Action |
|------|-------|-------------------|
| `incoming_receipts_service.py` | 4,355 | Split into receipt parsing, matching, storage |
| `db_mysql.py` | 3,998 | Keep as-is (database abstraction layer) |
| `services/plaid_service.py` | 2,216 | Keep as-is (Plaid integration) |
| `business_classifier.py` | 1,592 | Keep as-is (classification logic) |

## File Organization

### Root Directory (Current: 84 files)

**Keep in Root:**
- `viewer_server.py` - Main Flask app
- `auth.py` - Authentication page
- `requirements.txt` - Dependencies
- `Procfile`, `railway.toml` - Deployment config
- `pytest.ini` - Test config
- Configuration files

**Move to `templates/`:**
- `bank_accounts.html`
- `contacts.html`
- `dashboard_*.html`
- `incoming.html`
- `review.html`
- `settings.html`
- Other UI HTML files

**Note:** Moving HTML files requires updating Flask routes that use `send_from_directory(BASE_DIR, ...)`.

### Recommended New Structure

```
tallyups/
├── app/
│   ├── __init__.py      # App factory
│   ├── routes/          # All blueprints
│   ├── services/        # Business logic
│   ├── models/          # Data models
│   └── utils/           # Utilities
├── templates/           # All HTML templates
├── static/              # CSS, JS, images
├── tests/               # Test suite
├── migrations/          # DB migrations
├── config/              # Configuration
└── ios/                 # iOS app
```

## Migration Steps

### Phase 1: Safe Cleanup (Done)
- [x] Remove data files from git
- [x] Remove duplicate files
- [x] Update .gitignore
- [x] Fix test failures

### Phase 2: Route Extraction (In Progress)
1. [x] Extract atlas routes to `routes/atlas.py` (22 routes - status, imessage, relationship, gmail, people)
   - Blueprint created and registered
   - Original routes remain in viewer_server.py (lines 8195-8856) - marked for removal
   - Remaining atlas routes (contacts, sync, ai, bulk) still need extraction
2. [x] Extract transaction routes to `routes/transactions.py` (15 routes - CRUD, linking, status)
   - Blueprint created and registered
   - Original routes remain in viewer_server.py (lines 5663-6232) - marked for removal
   - Bulk operations (/api/bulk/*) remain in viewer_server.py (pandas dependencies)
3. [x] Extract OCR routes to `routes/ocr.py` (10 routes - OCR, verify, cache)
   - Blueprint created and registered
   - Original routes remain in viewer_server.py (lines 4494-5270) - marked for removal
   - Complex library routes remain in viewer_server.py for now
4. [x] Extract AI routes to `routes/ai.py` (11 routes - Gemini categorization, Apple splits)
   - Blueprint created and registered
   - Original routes remain in viewer_server.py (lines 7066-7880) - marked for removal
   - Routes: categorize, note, auto-process, batch-categorize, regenerate-notes,
     find-problematic-notes, regenerate-birthday-notes, apple-split-*
5. [x] Extract contact-hub routes to `routes/contact_hub.py` (31 routes - ATLAS CRM)
   - Blueprint created and registered
   - Original routes remain in viewer_server.py (lines 26004-26632) - marked for removal
   - Routes: contact CRUD, interactions, expense linking, reminders, calendar sync,
     relationship intelligence endpoints
6. [ ] Test each extraction before proceeding

### Phase 3: Utility Extraction (Pending)
1. Move database helpers to `utils/db.py`
2. Move cache utilities to `utils/cache.py`
3. Move vision utilities to `utils/vision.py`
4. Update imports across codebase

### Phase 4: Template Reorganization (Future)
1. Create template routing system
2. Move HTML files to `templates/`
3. Update all `send_from_directory` calls
4. Test all UI pages

## Testing Strategy

Before each refactoring step:
1. Run full test suite: `pytest tests/`
2. Check app imports: `python -c "from viewer_server import app"`
3. Verify production health: `curl https://tallyups.com/api/health`

## Risk Assessment

| Change | Risk | Mitigation |
|--------|------|------------|
| Extract routes | Medium | Test each blueprint individually |
| Move utilities | Low | Update imports, run tests |
| Move templates | High | Extensive UI testing required |
| Refactor large services | High | Do incrementally with tests |

## Timeline Recommendation

- **Week 1:** Phase 2 - Route extraction
- **Week 2:** Phase 3 - Utility extraction
- **Week 3:** Phase 4 - Template reorganization
- **Ongoing:** Improve test coverage

---

*Generated: December 27, 2025*

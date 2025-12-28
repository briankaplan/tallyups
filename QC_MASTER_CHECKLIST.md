# TallyUps/ReceiptAI - Master QC Checklist

**Last Updated:** 2025-12-27
**Status:** IN PROGRESS - CRITICAL ISSUES FOUND

## CRITICAL ACTION ITEMS (Fix Immediately)

### Security - CRITICAL
1. [x] **viewer_server.py**: Add `@login_required` to `/settings/gmail/status`, `/settings/calendar/status`, `/settings/calendar/preferences` GET ✅ FIXED 2025-12-27
2. [x] **viewer_server.py**: Add user ownership validation to `/api/gmail/authorize/<email>`, `/api/gmail/disconnect/<email>` ✅ FIXED 2025-12-27
3. [x] **plaid_service.py**: Add user_id validation to `_get_item()` method (line 1098) ✅ FIXED 2025-12-27
4. [x] **auth_routes.py**: Fix SQL injection risk at line 521 (dynamic f-string) ✅ FIXED 2025-12-27
5. [ ] **auth_routes.py**: Add rate limiting to login endpoints (Flask-Limiter) - PENDING
6. [x] **db_user_scope.py**: User scoping now ENABLED by default in production ✅ FIXED 2025-12-27

### Security - HIGH
7. [ ] **auth_routes.py**: Implement refresh token rotation revocation - PENDING
8. [ ] **viewer_server.py**: Move calendar preferences from file to database (user-scoped) - PENDING
9. [x] **user_credentials_service.py**: Fail if `CREDENTIALS_ENCRYPTION_KEY` not set in production ✅ FIXED 2025-12-27
10. [x] **taskade_integration_service.py**: Clarified per-user vs admin credential paths ✅ FIXED 2025-12-27

---

## Overview

This document tracks the comprehensive Quality Control audit of the entire TallyUps application. Every file, endpoint, connection, and feature must be verified.

---

## 1. SECURITY - Data Isolation (Multi-User)

### Completed Fixes
| File | Issue | Status | Commit |
|------|-------|--------|--------|
| `routes/transactions.py` | Missing user_id filtering | ✅ FIXED | 4e9dddc |
| `routes/contacts.py` | Missing user_id filtering | ✅ FIXED | 4e9dddc |
| `routes/reports.py` | 4 endpoints unprotected | ✅ FIXED | 92eb938 |
| `routes/ocr.py` | Missing user_id filtering | ✅ FIXED | 4e9dddc |
| `routes/library.py` | Tags/collections unscoped | ✅ FIXED | d1ba553 |
| `routes/contact_hub.py` | Suggest endpoint unscoped | ✅ FIXED | d1ba553 |
| `routes/incoming.py` | Stats unscoped | ✅ FIXED | d1ba553 |
| `routes/ai.py` | Timing attack vulnerability | ✅ FIXED | d1ba553 |

### Pending Audit
| File | Status | Notes |
|------|--------|-------|
| `routes/auth_routes.py` | ✅ AUDITED | SQL injection fixed, rate limiting pending |
| `routes/business_types.py` | ⏳ PENDING | Business type management |
| `routes/credentials_routes.py` | ⏳ PENDING | API credentials storage |
| `services/plaid_service.py` | ✅ AUDITED | _get_item() user validation added |
| `services/gmail_receipt_service.py` | ✅ AUDITED | Proper user scoping verified |
| `services/taskade_integration_service.py` | ✅ AUDITED | Per-user credentials enforced |
| `services/user_credentials_service.py` | ✅ AUDITED | Encryption required in production |
| `viewer_server.py` | ✅ AUDITED | Status endpoints protected, Gmail ownership validated |
| `db_user_scope.py` | ✅ AUDITED | User scoping enabled by default in production |

---

## 2. AUTHENTICATION & ONBOARDING

### User Registration
| Feature | Status | Notes |
|---------|--------|-------|
| Email/password signup | ⏳ PENDING | |
| Apple Sign-In | ⏳ PENDING | iOS app |
| Email verification | ⏳ PENDING | |
| Password requirements | ⏳ PENDING | |
| Demo account | ⏳ PENDING | |

### User Login
| Feature | Status | Notes |
|---------|--------|-------|
| Email/password login | ⏳ PENDING | |
| Session management | ⏳ PENDING | |
| Remember me | ⏳ PENDING | |
| Password reset | ⏳ PENDING | |
| Logout | ⏳ PENDING | |

### First-Time Tutorial
| Feature | Status | Notes |
|---------|--------|-------|
| Welcome modal | ⏳ PENDING | |
| Feature walkthrough | ⏳ PENDING | |
| Connection prompts | ⏳ PENDING | |
| Skip option | ⏳ PENDING | |

---

## 3. SETTINGS & CONNECTIONS

### Gmail Integration
| Feature | Status | Notes |
|---------|--------|-------|
| OAuth connection | ⏳ PENDING | |
| Multi-account support | ⏳ PENDING | |
| Email receipt scanning | ⏳ PENDING | |
| Label management | ⏳ PENDING | |
| Disconnect account | ⏳ PENDING | |

### Calendar Integration
| Feature | Status | Notes |
|---------|--------|-------|
| Google Calendar OAuth | ⏳ PENDING | |
| Event sync | ⏳ PENDING | |
| Receipt-to-event matching | ⏳ PENDING | |

### Bank Connections (Plaid)
| Feature | Status | Notes |
|---------|--------|-------|
| Plaid Link integration | ⏳ PENDING | |
| Multi-account support | ⏳ PENDING | |
| Transaction sync | ⏳ PENDING | |
| User-scoped tokens | ⏳ PENDING | |

### API Credentials
| Feature | Status | Notes |
|---------|--------|-------|
| Per-user API key storage | ⏳ PENDING | |
| Anthropic/OpenAI keys | ⏳ PENDING | |
| Encryption at rest | ⏳ PENDING | |

---

## 4. CORE FEATURES

### Receipt Management
| Feature | Status | Notes |
|---------|--------|-------|
| Upload receipt | ⏳ PENDING | |
| Camera scan | ⏳ PENDING | |
| OCR extraction | ⏳ PENDING | |
| AI categorization | ⏳ PENDING | |
| Receipt-to-transaction matching | ⏳ PENDING | |
| Receipt library | ⏳ PENDING | |
| Search receipts | ⏳ PENDING | |

### Transaction Management
| Feature | Status | Notes |
|---------|--------|-------|
| View transactions | ⏳ PENDING | |
| Filter/sort | ⏳ PENDING | |
| Edit transaction | ⏳ PENDING | |
| Assign business type | ⏳ PENDING | |
| Link receipt | ⏳ PENDING | |
| Bulk operations | ⏳ PENDING | |

### Expense Reports
| Feature | Status | Notes |
|---------|--------|-------|
| Create report | ⏳ PENDING | |
| Add transactions | ⏳ PENDING | |
| Generate AI notes | ⏳ PENDING | |
| Export (PDF/Excel/CSV) | ⏳ PENDING | |
| Submit report | ⏳ PENDING | |

### Dashboard
| Feature | Status | Notes |
|---------|--------|-------|
| Stats display | ⏳ PENDING | |
| Charts | ⏳ PENDING | |
| Recent activity | ⏳ PENDING | |
| Quick actions | ⏳ PENDING | |

---

## 5. STYLING & UI CONSISTENCY

### Completed Fixes
| File | Issue | Status | Commit |
|------|-------|--------|--------|
| `dashboard_v2.html` | Hardcoded colors | ✅ FIXED | 8ef87b5 |
| `tallyups-clean.css` | Hardcoded hover color | ✅ FIXED | 8ef87b5 |
| `receipt_reconciler_viewer.html` | Hardcoded colors | ✅ FIXED | 3443521 |
| `report_builder.html` | Hardcoded colors | ✅ FIXED | 3443521 |
| `contacts.html` | Hardcoded colors | ✅ FIXED | 3443521 |

### Pending Audit
| File | Status | Notes |
|------|--------|-------|
| `templates/settings.html` | ⏳ PENDING | |
| `templates/login.html` | ⏳ PENDING | |
| `templates/transactions.html` | ⏳ PENDING | |
| All other HTML files | ⏳ PENDING | |

---

## 6. iOS APP

### Authentication
| Feature | Status | Notes |
|---------|--------|-------|
| Login view | ⏳ PENDING | |
| Apple Sign-In | ⏳ PENDING | |
| Session persistence | ⏳ PENDING | |
| Biometric auth | ⏳ PENDING | |

### Core Features
| Feature | Status | Notes |
|---------|--------|-------|
| Scanner view | ⏳ PENDING | |
| Transactions view | ⏳ PENDING | |
| Receipt detail | ⏳ PENDING | |
| Settings | ⏳ PENDING | |

---

## 7. DATABASE SCHEMA

| Table | user_id Column | Index | Notes |
|-------|---------------|-------|-------|
| `transactions` | ⏳ CHECK | ⏳ CHECK | |
| `receipts` | ⏳ CHECK | ⏳ CHECK | |
| `reports` | ⏳ CHECK | ⏳ CHECK | |
| `contacts` | ⏳ CHECK | ⏳ CHECK | |
| `receipt_tags` | ⏳ CHECK | ⏳ CHECK | |
| `collections` | ⏳ CHECK | ⏳ CHECK | |
| `incoming_receipts` | ⏳ CHECK | ⏳ CHECK | |
| `users` | N/A | N/A | User table itself |
| `user_sessions` | ⏳ CHECK | ⏳ CHECK | |
| `user_credentials` | ⏳ CHECK | ⏳ CHECK | |

---

## 8. API ENDPOINTS AUDIT

### Authentication (`/api/auth/*`)
| Endpoint | Method | Auth | User Scoped | Status |
|----------|--------|------|-------------|--------|
| `/api/auth/register` | POST | No | N/A | ⏳ PENDING |
| `/api/auth/login` | POST | No | N/A | ⏳ PENDING |
| `/api/auth/logout` | POST | Yes | N/A | ⏳ PENDING |
| `/api/auth/me` | GET | Yes | Yes | ⏳ PENDING |

### Transactions (`/api/transactions/*`)
| Endpoint | Method | Auth | User Scoped | Status |
|----------|--------|------|-------------|--------|
| `/api/transactions` | GET | Yes | Yes | ✅ FIXED |
| `/api/transactions/<id>` | GET | Yes | Yes | ✅ FIXED |
| `/api/transactions/<id>` | PATCH | Yes | Yes | ✅ FIXED |

### Reports (`/api/reports/*`)
| Endpoint | Method | Auth | User Scoped | Status |
|----------|--------|------|-------------|--------|
| `/api/reports` | GET | Yes | Yes | ⏳ CHECK |
| `/api/reports` | POST | Yes | Yes | ⏳ CHECK |
| `/api/reports/<id>/items` | GET | Yes | Yes | ✅ FIXED |
| `/api/reports/stats` | GET | Yes | Yes | ✅ FIXED |
| `/api/reports/dashboard` | GET | Yes | Yes | ✅ FIXED |
| `/api/reports/business-summary` | GET | Yes | Yes | ✅ FIXED |

### Contacts (`/api/contacts/*`)
| Endpoint | Method | Auth | User Scoped | Status |
|----------|--------|------|-------------|--------|
| All endpoints | * | Yes | Yes | ✅ FIXED |

---

## Progress Summary

| Category | Completed | Pending | Total |
|----------|-----------|---------|-------|
| Security Fixes | 8 | ~20 | ~28 |
| Styling Fixes | 5 | ~15 | ~20 |
| Feature Audit | 0 | ~50 | ~50 |
| iOS App | 0 | ~15 | ~15 |

**Overall Progress:** ~15%

---

## Next Actions (Priority Order)

1. [ ] Audit `auth_routes.py` - registration/login flow
2. [ ] Audit `viewer_server.py` - main app routes
3. [ ] Audit `credentials_routes.py` - API key storage
4. [ ] Audit `plaid_service.py` - bank connections
5. [ ] Audit `gmail_receipt_service.py` - email integration
6. [ ] Verify database schema has user_id on all tables
7. [ ] Audit iOS app authentication flow
8. [ ] Verify first-time tutorial/onboarding exists

---

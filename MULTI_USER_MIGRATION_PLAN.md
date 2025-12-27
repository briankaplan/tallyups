# TallyUps Multi-User Migration Plan

> **Status**: PLANNING ONLY - Do not execute without explicit approval
> **Created**: December 15, 2024
> **Risk Level**: HIGH

---

## Executive Summary

This document outlines the complete plan to convert TallyUps from a single-user application to a multi-user SaaS platform with full data isolation between users.

**Estimated Effort**: 3-4 weeks
**Risk**: High - touches every part of the system

---

## Table of Contents

1. [Current State Analysis](#1-current-state-analysis)
2. [Target Architecture](#2-target-architecture)
3. [Database Migration Plan](#3-database-migration-plan)
4. [Authentication System](#4-authentication-system)
5. [Code Changes Required](#5-code-changes-required)
6. [New Features to Build](#6-new-features-to-build)
7. [Migration Strategy](#7-migration-strategy)
8. [Risk Mitigation](#8-risk-mitigation)
9. [Testing Plan](#9-testing-plan)
10. [Rollback Plan](#10-rollback-plan)
11. [Timeline & Phases](#11-timeline--phases)

---

## 1. Current State Analysis

### Current Authentication
- Single password stored in `AUTH_PASSWORD` environment variable
- Optional PIN for mobile (`AUTH_PIN`)
- WebAuthn/biometric as secondary factor
- No user accounts - just "logged in" or "not logged in"

### Current Data Model
```
transactions     - No user association
receipts         - No user association
reports          - No user association
report_items     - No user association
atlas_contacts   - No user association
gmail_tokens     - Stored by email, not user
calendar_tokens  - Stored by email, not user
```

### Current Queries (Example)
```sql
-- Every query is global - no user filtering
SELECT * FROM transactions WHERE business_type = 'Personal';
SELECT * FROM reports WHERE status = 'draft';
```

---

## 2. Target Architecture

### User Model
```
┌─────────────────────────────────────────────────────────┐
│                        USERS                            │
├─────────────────────────────────────────────────────────┤
│ id visors(PK)                                                │
│ email (unique)                                          │
│ password_hash                                           │
│ name                                                    │
│ created_at                                              │
│ last_login                                              │
│ email_verified (boolean)                                │
│ is_active (boolean)                                     │
│ settings (JSON)                                         │
└─────────────────────────────────────────────────────────┘
           │
           │ user_id (FK)
           ▼
┌──────────────────┬──────────────────┬──────────────────┐
│   transactions   │     reports      │  atlas_contacts  │
│   (user_id)      │    (user_id)     │    (user_id)     │
└──────────────────┴──────────────────┴──────────────────┘
```

### Data Isolation
- Every data table gets `user_id` foreign key
- Every query filtered by `user_id` from session
- Users can ONLY see their own data
- Admin can see all (optional)

---

## 3. Database Migration Plan

### Phase 3.1: Create Users Table

```sql
-- New users table
CREATE TABLE users (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    password_hash VARCHAR(255) NOT NULL,
    name VARCHAR(255),
    pin_hash VARCHAR(255),

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    email_verified BOOLEAN DEFAULT FALSE,
    email_verification_token VARCHAR(255),

    -- Password reset
    password_reset_token VARCHAR(255),
    password_reset_expires DATETIME,

    -- Timestamps
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login DATETIME,

    -- Preferences (JSON blob)
    settings JSON,

    -- Indexes
    INDEX idx_email (email),
    INDEX idx_active (is_active)
);
```

### Phase 3.2: Create User Sessions Table

```sql
CREATE TABLE user_sessions (
    id VARCHAR(255) PRIMARY KEY,
    user_id INT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    INDEX idx_expires (expires_at)
);
```

### Phase 3.3: Add user_id to Existing Tables

```sql
-- Transactions
ALTER TABLE transactions
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id),
ADD FOREIGN KEY (user_id) REFERENCES users(id);

-- Reports
ALTER TABLE reports
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id),
ADD FOREIGN KEY (user_id) REFERENCES users(id);

-- Report Items
ALTER TABLE report_items
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id),
ADD FOREIGN KEY (user_id) REFERENCES users(id);

-- Atlas Contacts
ALTER TABLE atlas_contacts
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id),
ADD FOREIGN KEY (user_id) REFERENCES users(id);

-- Contact sub-tables
ALTER TABLE contact_emails ADD COLUMN user_id INT;
ALTER TABLE contact_phones ADD COLUMN user_id INT;
ALTER TABLE contact_addresses ADD COLUMN user_id INT;
ALTER TABLE interactions ADD COLUMN user_id INT;

-- Gmail Tokens (new structure)
ALTER TABLE gmail_tokens
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id),
ADD FOREIGN KEY (user_id) REFERENCES users(id);

-- Calendar Tokens
ALTER TABLE calendar_tokens
ADD COLUMN user_id INT,
ADD INDEX idx_user_id (user_id);
```

### Phase 3.4: Create User Businesses Table

```sql
-- Businesses become a proper entity, not just a text field
CREATE TABLE user_businesses (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id INT NOT NULL,
    name VARCHAR(255) NOT NULL,
    type VARCHAR(50), -- 'personal', 'business', 'rental', etc.
    is_default BOOLEAN DEFAULT FALSE,

    -- Optional details
    address TEXT,
    tax_id VARCHAR(50),
    logo_url VARCHAR(500),

    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    INDEX idx_user_id (user_id),
    UNIQUE KEY unique_user_business (user_id, name)
);
```

### Phase 3.5: Data Migration Script

```sql
-- Step 1: Create the first user (you)
INSERT INTO users (email, password_hash, name, is_active, email_verified)
VALUES ('brian@example.com', '$2b$12$...existing_hash...', 'Brian Kaplan', TRUE, TRUE);

-- Get the new user ID
SET @brian_user_id = LAST_INSERT_ID();

-- Step 2: Assign ALL existing data to this user
UPDATE transactions SET user_id = @brian_user_id WHERE user_id IS NULL;
UPDATE reports SET user_id = @brian_user_id WHERE user_id IS NULL;
UPDATE report_items SET user_id = @brian_user_id WHERE user_id IS NULL;
UPDATE atlas_contacts SET user_id = @brian_user_id WHERE user_id IS NULL;
UPDATE gmail_tokens SET user_id = @brian_user_id WHERE user_id IS NULL;

-- Step 3: Create businesses from existing business_type values
INSERT INTO user_businesses (user_id, name, is_default)
SELECT DISTINCT @brian_user_id, business_type, FALSE
FROM transactions
WHERE business_type IS NOT NULL AND business_type != '';

-- Set Personal as default
UPDATE user_businesses
SET is_default = TRUE
WHERE user_id = @brian_user_id AND name = 'Personal';

-- Step 4: Make user_id NOT NULL after migration
ALTER TABLE transactions MODIFY user_id INT NOT NULL;
ALTER TABLE reports MODIFY user_id INT NOT NULL;
-- ... etc for all tables
```

---

## 4. Authentication System

### 4.1 New Auth Flow

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   SIGNUP    │────▶│   VERIFY    │────▶│   LOGIN     │
│  /register  │     │   EMAIL     │     │   /login    │
└─────────────┘     └─────────────┘     └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │   SESSION   │
                                        │  Created    │
                                        └─────────────┘
                                               │
                                               ▼
                                        ┌─────────────┐
                                        │  All APIs   │
                                        │ user_id set │
                                        └─────────────┘
```

### 4.2 New Auth Endpoints

```python
# Registration
@app.route("/register", methods=["GET", "POST"])
# - Collect email, password, name
# - Hash password with bcrypt
# - Send verification email
# - Create inactive user

# Email Verification
@app.route("/verify/<token>")
# - Validate token
# - Activate user account
# - Redirect to login

# Login
@app.route("/login", methods=["GET", "POST"])
# - Validate email/password
# - Create session in user_sessions table
# - Set session cookie
# - Redirect to dashboard

# Logout
@app.route("/logout")
# - Delete session from database
# - Clear session cookie

# Password Reset Request
@app.route("/forgot-password", methods=["GET", "POST"])
# - Generate reset token
# - Send reset email

# Password Reset
@app.route("/reset-password/<token>", methods=["GET", "POST"])
# - Validate token and expiry
# - Update password hash
# - Invalidate all sessions
```

### 4.3 Session Management

```python
# Helper to get current user
def get_current_user():
    session_id = request.cookies.get('session_id')
    if not session_id:
        return None

    session = db.query("""
        SELECT u.* FROM users u
        JOIN user_sessions s ON u.id = s.user_id
        WHERE s.id = ? AND s.expires_at > NOW() AND u.is_active = TRUE
    """, [session_id])

    return session[0] if session else None

# Decorator for protected routes
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        user = get_current_user()
        if not user:
            return redirect('/login')
        g.user = user  # Make user available in request context
        return f(*args, **kwargs)
    return decorated
```

---

## 5. Code Changes Required

### 5.1 Files That Need Modification

| File | Changes Needed | Complexity |
|------|----------------|------------|
| `auth.py` | Complete rewrite for multi-user | High |
| `viewer_server.py` | Add user_id to ALL queries | High |
| `routes/reports.py` | Add user_id filtering | Medium |
| `routes/contacts.py` | Add user_id filtering | Medium |
| `routes/gmail.py` | Per-user token storage | High |
| `routes/calendar.py` | Per-user token storage | Medium |
| All HTML templates | Update for user context | Low |
| All JS files | Handle auth errors | Low |

### 5.2 Query Modification Pattern

**Before (Current):**
```python
@app.route("/api/transactions")
def get_transactions():
    cursor.execute("SELECT * FROM transactions")
    return jsonify(cursor.fetchall())
```

**After (Multi-User):**
```python
@app.route("/api/transactions")
@login_required
def get_transactions():
    cursor.execute(
        "SELECT * FROM transactions WHERE user_id = %s",
        [g.user['id']]
    )
    return jsonify(cursor.fetchall())
```

### 5.3 Queries to Update (Comprehensive List)

```
viewer_server.py:
- /api/dashboard/stats
- /api/transactions
- /api/receipts
- /api/receipts/recent
- /api/library/receipts
- /api/viewer/transactions
- /api/incoming
- /api/incoming/count
- /upload_receipt
- /mobile-upload
- /add_manual_expense
- /api/bulk_import
- /api/match
- /api/unmatch
- ... (50+ more endpoints)

routes/reports.py:
- /api/reports
- /api/reports/<id>
- /api/reports/stats
- /api/reports/create
- /api/reports/<id>/add
- ... (15+ more)

routes/contacts.py:
- /api/atlas/contacts
- /api/atlas/contacts/<id>
- /api/atlas/sync/*
- ... (20+ more)
```

### 5.4 Gmail OAuth Changes

```python
# Current: Tokens stored by email only
def get_gmail_token(email):
    return db.query("SELECT * FROM gmail_tokens WHERE email = ?", [email])

# New: Tokens stored by user_id + email
def get_gmail_token(user_id, email):
    return db.query("""
        SELECT * FROM gmail_tokens
        WHERE user_id = ? AND email = ?
    """, [user_id, email])

# OAuth callback must associate token with logged-in user
@app.route("/auth/google/callback")
@login_required
def google_callback():
    # ... OAuth exchange ...
    save_token(user_id=g.user['id'], email=email, token=token)
```

---

## 6. New Features to Build

### 6.1 Registration Page (`/register`)

```html
- Email input (validated)
- Password input (strength meter)
- Confirm password
- Name input
- Terms of service checkbox
- Submit button
- "Already have account? Login" link
```

### 6.2 Email Verification Flow

```
1. User registers
2. System sends email with verification link
3. User clicks link
4. Account activated
5. Redirect to login
```

### 6.3 Password Reset Flow

```
1. User clicks "Forgot Password"
2. Enters email
3. System sends reset link (expires in 1 hour)
4. User clicks link
5. Enters new password
6. All sessions invalidated
7. Redirect to login
```

### 6.4 User Profile Page (`/profile`)

```
- View/edit name
- Change email (requires verification)
- Change password
- View connected Gmail accounts
- View connected businesses
- Delete account option
```

### 6.5 User Settings Page (`/settings`)

```
- Notification preferences
- Default business selection
- Timezone setting
- Date format preference
- Currency preference
- Export all data
- Delete account
```

### 6.6 Business Management UI (`/businesses`)

```
- List all businesses
- Add new business
- Edit business details
- Set default business
- Delete business (with confirmation)
```

---

## 7. Migration Strategy

### 7.1 Pre-Migration Checklist

- [ ] Full database backup
- [ ] Full R2/storage backup
- [ ] Test migration on staging
- [ ] Document rollback procedure
- [ ] Schedule maintenance window
- [ ] Notify users (if any)

### 7.2 Migration Steps

```
1. BACKUP
   - mysqldump full database
   - Copy R2 bucket
   - Save all env vars

2. SCHEMA CHANGES
   - Create users table
   - Create user_sessions table
   - Create user_businesses table
   - Add user_id columns (nullable first)

3. DATA MIGRATION
   - Create admin user (you)
   - Assign all data to admin user
   - Create businesses from business_type
   - Migrate gmail tokens

4. CODE DEPLOYMENT
   - Deploy new auth system
   - Deploy modified endpoints
   - Deploy new UI pages

5. SCHEMA FINALIZATION
   - Make user_id NOT NULL
   - Add foreign key constraints
   - Add indexes

6. VERIFICATION
   - Test all endpoints
   - Verify data integrity
   - Check Gmail OAuth still works
```

### 7.3 Zero-Downtime Strategy

```
Phase A: Backward Compatible
- Add user_id columns (nullable)
- Deploy code that writes user_id but doesn't require it
- Run data migration in background

Phase B: Switchover
- Short maintenance window (5-10 min)
- Make user_id required
- Switch auth system
- Deploy final code

Phase C: Cleanup
- Remove old auth code
- Remove migration scaffolding
```

---

## 8. Risk Mitigation

### 8.1 Risk Matrix

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Data loss | Low | Critical | Multiple backups, test on staging |
| Auth lockout | Medium | High | Keep env var auth as fallback |
| Query errors | High | Medium | Comprehensive testing |
| Gmail OAuth break | Medium | High | Test OAuth flow separately |
| Performance issues | Low | Medium | Add proper indexes |
| Session issues | Medium | Medium | Implement session cleanup |

### 8.2 Fallback Auth

Keep environment variable auth as emergency backdoor:

```python
# Emergency admin access (only if normal auth fails)
if request.headers.get('X-Admin-Key') == os.environ.get('EMERGENCY_ADMIN_KEY'):
    g.user = get_admin_user()
    return f(*args, **kwargs)
```

### 8.3 Data Integrity Checks

```sql
-- Run after migration to verify no orphaned data
SELECT COUNT(*) FROM transactions WHERE user_id IS NULL;
SELECT COUNT(*) FROM reports WHERE user_id IS NULL;
SELECT COUNT(*) FROM atlas_contacts WHERE user_id IS NULL;

-- All should return 0
```

---

## 9. Testing Plan

### 9.1 Unit Tests

```python
# Test user creation
def test_create_user():
    user = create_user("test@example.com", "password123", "Test User")
    assert user.id is not None
    assert user.email == "test@example.com"
    assert user.password_hash != "password123"  # Should be hashed

# Test data isolation
def test_user_data_isolation():
    user1 = create_user("user1@test.com", "pass", "User 1")
    user2 = create_user("user2@test.com", "pass", "User 2")

    create_transaction(user_id=user1.id, amount=100)
    create_transaction(user_id=user2.id, amount=200)

    # User 1 should only see their transaction
    with login_as(user1):
        transactions = get_transactions()
        assert len(transactions) == 1
        assert transactions[0].amount == 100
```

### 9.2 Integration Tests

```
- [ ] Register new user
- [ ] Verify email
- [ ] Login
- [ ] Create transaction
- [ ] Verify transaction only visible to creator
- [ ] Connect Gmail
- [ ] Verify Gmail token associated with user
- [ ] Create report
- [ ] Logout
- [ ] Login as different user
- [ ] Verify can't see first user's data
```

### 9.3 Load Testing

```
- Simulate 100 concurrent users
- Each user has 1000 transactions
- Verify query performance with user_id filtering
- Check index effectiveness
```

---

## 10. Rollback Plan

### If Migration Fails

```bash
# 1. Stop the application
railway down

# 2. Restore database from backup
mysql -h $DB_HOST -u $DB_USER -p $DB_NAME < backup_pre_migration.sql

# 3. Restore old code
git checkout pre-migration-tag
git push -f origin main

# 4. Restart application
railway up

# 5. Verify functionality
curl https://tallyups.com/api/health
```

### Partial Rollback

If only some features are broken:

```python
# Feature flag to disable multi-user
MULTI_USER_ENABLED = os.environ.get('MULTI_USER_ENABLED', 'false') == 'true'

if MULTI_USER_ENABLED:
    # New multi-user code
else:
    # Old single-user code
```

---

## 11. Timeline & Phases

### Phase 1: Foundation (Week 1)
- [ ] Create users table
- [ ] Create user_sessions table
- [ ] Build registration page
- [ ] Build login page
- [ ] Build basic auth system
- [ ] Test auth flow

### Phase 2: Data Migration (Week 2)
- [ ] Add user_id to all tables (nullable)
- [ ] Write migration scripts
- [ ] Test on staging database
- [ ] Run production migration
- [ ] Verify data integrity

### Phase 3: Code Updates (Week 2-3)
- [ ] Update all queries in viewer_server.py
- [ ] Update routes/reports.py
- [ ] Update routes/contacts.py
- [ ] Update Gmail OAuth flow
- [ ] Update all templates

### Phase 4: New Features (Week 3)
- [ ] Email verification
- [ ] Password reset
- [ ] User profile page
- [ ] Business management UI
- [ ] Settings page updates

### Phase 5: Testing & Launch (Week 4)
- [ ] Full integration testing
- [ ] Security audit
- [ ] Performance testing
- [ ] Documentation
- [ ] Production deployment
- [ ] Monitor for issues

---

## Appendix A: Environment Variables (New)

```bash
# Email (for verification/reset)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=noreply@tallyups.com
SMTP_PASSWORD=xxx
FROM_EMAIL=noreply@tallyups.com

# Session
SESSION_SECRET_KEY=xxx  # For signing session cookies
SESSION_TIMEOUT_DAYS=7

# Emergency access
EMERGENCY_ADMIN_KEY=xxx  # Backdoor if auth breaks

# Feature flags
MULTI_USER_ENABLED=true
REGISTRATION_ENABLED=true
EMAIL_VERIFICATION_REQUIRED=true
```

---

## Appendix B: New Database Schema (Complete)

```sql
-- See section 3 for all CREATE TABLE and ALTER TABLE statements
```

---

## Appendix C: API Endpoint Changes

| Endpoint | Auth Change | Query Change |
|----------|-------------|--------------|
| `GET /api/transactions` | Add @login_required | Add WHERE user_id = ? |
| `POST /api/transactions` | Add @login_required | Add user_id to INSERT |
| `GET /api/reports` | Add @login_required | Add WHERE user_id = ? |
| ... | ... | ... |

*Full list: ~100+ endpoints*

---

## Decision Required

Before proceeding, confirm:

1. **Go/No-Go**: Should we proceed with multi-user migration?
2. **Timeline**: When should we start?
3. **Staging**: Do you have a staging environment to test first?
4. **Backup**: Is current backup strategy sufficient?
5. **Downtime**: Is a maintenance window acceptable?

---

**Document Status**: PLANNING COMPLETE - AWAITING APPROVAL

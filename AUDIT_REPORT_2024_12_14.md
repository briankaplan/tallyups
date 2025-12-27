# ReceiptAI (Tallyups) Comprehensive Audit Report
**Generated:** 2024-12-14
**Auditor:** Senior FinTech Engineer

---

## Executive Summary

| Severity | Count |
|----------|-------|
| Critical | 3 |
| High | 5 |
| Medium | 8 |
| Low | 7 |
| **Total** | **23** |

**Estimated Remediation Effort:** 40-60 hours

The ReceiptAI system is a well-architected expense reconciliation platform with solid foundations in connection pooling, OCR fallback chains, and smart matching algorithms. However, several security vulnerabilities and code quality issues were identified that should be addressed before production hardening.

---

## Critical Issues

### 1. Hardcoded MySQL Credentials in receipt_intelligence.py

**File:** `receipt_intelligence.py:36-44`
**Severity:** Critical
**Impact:** Exposure of database credentials in source code. If this file is committed to a public repo or the environment variables aren't set, the hardcoded defaults could be used.

**Current Code:**
```python
MYSQL_CONFIG = {
    'host': os.getenv('MYSQL_HOST', 'metro.proxy.rlwy.net'),  # Hardcoded!
    'port': int(os.getenv('MYSQL_PORT', 19800)),              # Hardcoded!
    'user': os.getenv('MYSQL_USER', 'root'),                  # Hardcoded!
    'password': os.getenv('MYSQL_PASSWORD', ''),
    'database': os.getenv('MYSQL_DATABASE', 'railway'),
    ...
}
```

**Recommended Fix:**
```python
from db_config import get_db_config

MYSQL_CONFIG = get_db_config()
if not MYSQL_CONFIG:
    raise RuntimeError("MySQL not configured - set MYSQL_URL or MYSQL* environment variables")
```

**Effort:** 1 hour

---

### 2. Weak Password Hashing in auth.py

**File:** `auth.py:26-28`
**Severity:** Critical
**Impact:** SHA256 is not suitable for password hashing - no salt, fast to brute force. If password hashes are leaked, they can be cracked quickly.

**Current Code:**
```python
def hash_password(password: str) -> str:
    """Simple SHA256 hash for password comparison"""
    return hashlib.sha256(password.encode()).hexdigest()
```

**Recommended Fix:**
```python
import bcrypt

def hash_password(password: str) -> bytes:
    """Secure password hashing with bcrypt"""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt())

def verify_password(password: str) -> bool:
    if AUTH_PASSWORD_HASH:
        try:
            return bcrypt.checkpw(password.encode(), AUTH_PASSWORD_HASH.encode())
        except ValueError:
            return False
    # ... rest of logic
```

**Effort:** 2 hours

---

### 3. Insecure Default Authentication Bypass

**File:** `auth.py:37-39`
**Severity:** Critical
**Impact:** If no password is configured, the application allows unauthenticated access. This could expose sensitive financial data if deployed without proper configuration.

**Current Code:**
```python
def verify_password(password: str) -> bool:
    # ...
    else:
        # No password set - allow access (for local development)
        return True
```

**Recommended Fix:**
```python
def verify_password(password: str) -> bool:
    if AUTH_PASSWORD_HASH:
        return bcrypt.checkpw(password.encode(), AUTH_PASSWORD_HASH.encode())
    elif AUTH_PASSWORD:
        # For development - but log warning
        logger.warning("Using plaintext password comparison - not recommended for production")
        return secrets.compare_digest(password, AUTH_PASSWORD)
    else:
        # NEVER allow unauthenticated access in production
        if os.environ.get('RAILWAY_ENVIRONMENT'):
            raise RuntimeError("AUTH_PASSWORD or AUTH_PASSWORD_HASH must be set in production")
        logger.warning("No password configured - allowing access (development mode)")
        return True
```

**Effort:** 2 hours

---

## High Priority Issues

### 4. Dynamic SQL Column Names Without Validation

**File:** `viewer_server.py:4347-4349`
**Severity:** High
**Impact:** While the values use parameterized queries, the column names are dynamically interpolated. An attacker could potentially inject malicious column names.

**Current Code:**
```python
cursor.execute(f"UPDATE transactions SET {db_field} = %s WHERE `Index` = %s", (value, index))
```

**Recommended Fix:**
```python
ALLOWED_FIELDS = {'notes', 'category', 'business_type', 'receipt_url', 'review_status', ...}

def safe_update_field(cursor, table, field, value, where_col, where_val):
    if field not in ALLOWED_FIELDS:
        raise ValueError(f"Invalid field: {field}")
    cursor.execute(f"UPDATE {table} SET {field} = %s WHERE {where_col} = %s", (value, where_val))
```

**Effort:** 4 hours (needs to audit all dynamic SQL)

---

### 5. Timing Attack Vulnerability in PIN Verification

**File:** `auth.py:42-46`
**Severity:** High
**Impact:** Direct string comparison allows timing attacks to guess PIN digits one at a time.

**Current Code:**
```python
def verify_pin(pin: str) -> bool:
    if AUTH_PIN:
        return pin == AUTH_PIN  # Timing attack vulnerable!
    return False
```

**Recommended Fix:**
```python
import secrets

def verify_pin(pin: str) -> bool:
    if AUTH_PIN:
        return secrets.compare_digest(pin, AUTH_PIN)  # Constant-time comparison
    return False
```

**Effort:** 0.5 hours

---

### 6. Missing Rate Limiting on Authentication Endpoints

**File:** `viewer_server.py:2010-2048`
**Severity:** High
**Impact:** No rate limiting on /login and /login/pin endpoints allows brute force attacks.

**Recommended Fix:**
```python
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(app, key_func=get_remote_address)

@app.route("/login", methods=["GET", "POST"])
@limiter.limit("5 per minute")  # 5 attempts per minute
def login():
    ...

@app.route("/login/pin", methods=["GET", "POST"])
@limiter.limit("10 per minute")  # 10 PIN attempts per minute
def login_pin():
    ...
```

**Effort:** 2 hours

---

### 7. Connection Pool Leak via Legacy Property

**File:** `db_mysql.py:544-557`
**Severity:** High
**Impact:** The `conn` property gets a connection from the pool but provides no mechanism to return it, causing pool exhaustion.

**Current Code:**
```python
@property
def conn(self):
    """
    Legacy compatibility property that returns a pooled connection.
    WARNING: This is for backwards compatibility...
    """
    if not self._pool:
        return None
    return self._pool.get_connection()  # Never returned to pool!
```

**Recommended Fix:**
```python
# Remove the property entirely and update all callers to use:
with db.pooled_connection() as conn:
    # use conn
```

**Effort:** 8 hours (need to find and update all callers)

---

### 8. Duplicate Database Configuration Functions

**Files:** `db_mysql.py:383-422`, `incoming_receipts_service.py:447-473`
**Severity:** High
**Impact:** Different behavior between the two implementations could lead to connection failures or inconsistent configuration.

**Current State:**
- `db_mysql.py` uses centralized `db_config.py`
- `incoming_receipts_service.py` has its own inline implementation

**Recommended Fix:**
Update `incoming_receipts_service.py` to use centralized config:
```python
from db_config import get_db_config

def _get_mysql_config():
    config = get_db_config()
    if config:
        config['cursorclass'] = pymysql.cursors.DictCursor
    return config
```

**Effort:** 1 hour

---

## Medium Priority Issues

### 9. Hardcoded VIP People List

**File:** `contacts_engine.py:8-66`
**Severity:** Medium
**Impact:** Hardcoded names require code changes to update. Should be in database for flexibility.

**Recommended Fix:** Move to database table `expense_attendees` or `vip_contacts` with admin UI.

**Effort:** 6 hours

---

### 10. Large Monolithic Server File

**File:** `viewer_server.py` (~970KB, 25000+ lines)
**Severity:** Medium
**Impact:** Difficult to maintain, test, and review. High cognitive load for developers.

**Recommended Fix:** Split into blueprints:
- `routes/transactions.py`
- `routes/receipts.py`
- `routes/contacts.py`
- `routes/reports.py`
- `routes/admin.py`

**Effort:** 20 hours

---

### 11. Inconsistent Error Handling in OCR Pipeline

**File:** `receipt_ocr_service.py:401-417`
**Severity:** Medium
**Impact:** Broad exception catches may hide specific errors, making debugging difficult.

**Current Code:**
```python
except Exception as e:
    print(f"... OpenAI extraction error: {e}")
```

**Recommended Fix:**
```python
except openai.RateLimitError as e:
    logger.warning(f"OpenAI rate limited: {e}")
    return None  # Try fallback
except openai.APIConnectionError as e:
    logger.error(f"OpenAI connection error: {e}")
    return None
except Exception as e:
    logger.exception(f"Unexpected OpenAI error")
    return None
```

**Effort:** 4 hours

---

### 12. Missing Database Index on chase_date

**File:** `db_mysql.py` (migrations section)
**Severity:** Medium
**Impact:** Slow queries when filtering by date range (common operation).

**Current State:** Index exists but may not be optimal for compound queries.

**Recommended Fix:**
```sql
CREATE INDEX idx_transactions_date_business
ON transactions(chase_date, business_type, deleted);

CREATE INDEX idx_transactions_date_receipt
ON transactions(chase_date, r2_url(100));
```

**Effort:** 1 hour

---

### 13. N+1 Query Pattern in Matching Algorithm

**File:** `smart_auto_matcher.py:470-477`
**Severity:** Medium
**Impact:** When processing multiple receipts, each iteration may query the database separately.

**Recommended Fix:** Batch load all transactions upfront, then iterate in memory.

**Effort:** 3 hours

---

### 14. Unbounded Email Scanning in Scheduler

**File:** `viewer_server.py:493-506`
**Severity:** Medium
**Impact:** Scanning all 3 email accounts every 4 hours could be slow and rate-limited.

**Recommended Fix:** Add incremental sync using Gmail historyId instead of full scan.

**Effort:** 6 hours

---

### 15. Missing HTTPS Enforcement in Development

**File:** `viewer_server.py:557`
**Severity:** Medium
**Impact:** Cookies are only secure in production; development could leak session tokens.

**Recommended Fix:** Add warning when running without HTTPS in development.

**Effort:** 0.5 hours

---

### 16. Calendar Token Files in Repository

**File:** Multiple `token_*.pickle` files in config/
**Severity:** Medium
**Impact:** OAuth tokens in git could be leaked if repository is public.

**Recommended Fix:** Add to .gitignore and store in environment variables or secure vault.

**Effort:** 1 hour

---

## Low Priority Issues

### 17. Inconsistent Logging (print vs logger)

**Multiple Files**
**Severity:** Low
**Impact:** Mixed use of `print()` and `logger.info()` makes log aggregation difficult.

**Effort:** 3 hours

---

### 18. Missing Type Hints in Many Functions

**Multiple Files**
**Severity:** Low
**Impact:** Harder to catch type errors, less IDE support.

**Effort:** 8 hours

---

### 19. Unused Imports and Dead Code

**Multiple Files** (e.g., `imgkit` import that's never used)
**Severity:** Low
**Impact:** Code bloat, confusion.

**Effort:** 2 hours

---

### 20. Magic Numbers in Matching Algorithm

**File:** `smart_auto_matcher.py:36-48`
**Severity:** Low
**Impact:** Hard to tune thresholds without code changes.

**Recommended Fix:** Move to config file or environment variables.

**Effort:** 2 hours

---

### 21. Missing Unit Tests for Core Matching Logic

**File:** `smart_auto_matcher.py`
**Severity:** Low
**Impact:** Changes to matching algorithm could introduce regressions undetected.

**Effort:** 8 hours

---

### 22. Emoji in Log Messages

**Multiple Files**
**Severity:** Low
**Impact:** May not render correctly in all log aggregators.

**Effort:** 2 hours

---

### 23. Potential Memory Leak in Vision Cache

**File:** `smart_auto_matcher.py:109`
**Severity:** Low
**Impact:** `hash_cache` dict grows unbounded in memory.

**Recommended Fix:** Add LRU eviction or periodic cleanup.

**Effort:** 2 hours

---

## Architecture Recommendations

### 1. Split viewer_server.py into Modules

The 970KB monolith should be split into:
```
routes/
  __init__.py
  transactions.py      # CRUD for transactions
  receipts.py          # Receipt matching and OCR
  incoming.py          # Gmail receipt ingestion (exists)
  reports.py           # Expense reports (exists)
  contacts.py          # Contact management
  admin.py             # Pool status, diagnostics
  auth.py              # Login/logout routes
services/
  matching_service.py  # Smart auto-matcher
  ocr_service.py       # OCR pipeline
  storage_service.py   # R2 operations
```

### 2. Implement Database Migrations Framework

Current state: Ad-hoc migrations in `_run_migrations()` method.

Recommended: Use Alembic for proper version-controlled migrations.

### 3. Add Comprehensive API Documentation

Current state: No API docs.

Recommended: Add OpenAPI/Swagger specs using Flask-RESTx or flasgger.

### 4. Implement Structured Logging Throughout

Current state: Mixed print/logger usage.

Recommended: Use structured JSON logging with correlation IDs for request tracing.

### 5. Add Health Check Endpoint for Load Balancer

Current state: `/api/health/pool-status` exists but requires auth.

Recommended: Add unauthenticated `/health` endpoint for Railway health checks.

---

## Quick Wins (< 1 hour each)

| Priority | Fix | Effort |
|----------|-----|--------|
| 1 | Add `secrets.compare_digest()` for PIN verification | 15 min |
| 2 | Remove hardcoded MySQL defaults in receipt_intelligence.py | 30 min |
| 3 | Add rate limiter to login endpoints | 45 min |
| 4 | Add .gitignore entries for token files | 10 min |
| 5 | Add HTTPS warning for development | 15 min |
| 6 | Use centralized db_config in incoming_receipts_service.py | 30 min |

---

## Database Schema Observations

### Positive Findings
- Good use of indexes on frequently queried columns
- Proper foreign key relationships with CASCADE deletes
- utf8mb4 charset for full Unicode support
- Appropriate DECIMAL precision for currency

### Areas for Improvement
- Consider partitioning `transactions` table by date for large datasets
- Add covering indexes for common query patterns
- Consider adding `deleted_at` timestamp instead of boolean `deleted` for audit trail

---

## Matching Algorithm Assessment

### Current Weights
```python
if amount_score >= 0.90:
    weights = {'amount': 0.60, 'merchant': 0.30, 'date': 0.10}
elif merchant_score >= 0.80:
    weights = {'amount': 0.45, 'merchant': 0.40, 'date': 0.15}
else:
    weights = {'amount': 0.50, 'merchant': 0.35, 'date': 0.15}
```

### Assessment
- **Amount matching:** Well-implemented with tip variance handling
- **Merchant matching:** Good normalization, but could benefit from ML-based entity resolution
- **Date matching:** Appropriate tolerances for different transaction types

### Recommended Improvements
1. Add machine learning feedback loop from user corrections
2. Implement fuzzy amount matching for split transactions
3. Add receipt-to-receipt duplicate detection before matching

---

## Conclusion

The ReceiptAI system has a solid foundation with well-designed components for connection pooling, OCR fallbacks, and smart matching. The critical security issues (hardcoded credentials, weak password hashing, authentication bypass) should be addressed immediately. The high-priority items around SQL injection prevention and rate limiting should follow.

The codebase would benefit from modularization of the large server file and implementation of proper database migrations. Overall, with the recommended fixes applied, this system would be production-ready for enterprise use.

---

*End of Audit Report*

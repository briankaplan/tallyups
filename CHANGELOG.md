# TallyUps Changelog

All notable changes to this project are documented in this file.

---

## [2.1.0] - 2024-12-29

### Comprehensive Quality & Security Audit

This release addresses 22 improvements identified during a comprehensive audit of the codebase, covering security, performance, accessibility, and mobile responsiveness.

---

### Authentication & Security

#### Google Sign-In Integration
- **NEW**: Added Google Sign-In as an authentication option alongside Apple Sign-In
- Added `GoogleSignInService.swift` with full OAuth2 implementation
- Added `GoogleSignInButton` SwiftUI component with proper branding
- Integrated with existing `AuthService` for seamless token management
- Backend support via `/api/auth/google` endpoint

#### Enhanced localStorage Security (`static/js/storage-utils.js`)
- **NEW**: Created secure storage utility with whitelist-based key access
- Implemented XSS sanitization for all stored values
- Added size limits per key to prevent storage exhaustion attacks
- Automatic session/local storage routing for sensitive keys (tokens use sessionStorage)
- Storage key prefixing (`tallyups_`) to prevent collisions
- Quota exceeded handling with automatic old data cleanup
- Migration support for legacy storage keys

```javascript
// Usage example
StorageUtils.set('theme', 'dark');
StorageUtils.get('theme', 'light'); // Returns 'dark'
StorageUtils.getDeviceId(); // Auto-generates and persists device ID
```

#### Gmail Multi-User Dynamic Accounts (`viewer_server.py`)
- **NEW**: Users can now connect their own Gmail accounts dynamically
- **REPLACED**: Legacy hardcoded Gmail accounts with user-scoped `user_credentials` table
- Added `/api/credentials/google/connect` endpoint for OAuth flow initiation
- Updated OAuth callback to handle `NEW_ACCOUNT` flow with userinfo API lookup
- Gmail credentials stored per-user with proper access/refresh token columns
- Updated `/settings/gmail/status` to be user-scoped (queries `user_credentials` table)
- Updated `/api/gmail/disconnect/<email>` to deactivate user-scoped accounts
- Added disconnect buttons for all accounts in Settings UI (`settings.html`)
- Full OAuth 2.0 flow: consent screen → token exchange → userinfo → DB storage

```javascript
// Connect new Gmail account (from settings page)
const response = await fetch('/api/credentials/google/connect', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({ service: 'gmail' })
});
// Redirects to Google OAuth consent screen with account selector
```

---

### Performance Improvements

#### Database Composite Indexes (`migrations/019_composite_indexes.sql`)
- **NEW**: Added 6 high-impact composite indexes for common query patterns:
  - `idx_txn_user_date`: `(user_id, chase_date DESC)` - User transaction timeline
  - `idx_txn_user_business`: `(user_id, business_type, chase_date)` - Filtered queries
  - `idx_txn_matching`: `(user_id, receipt_url, status)` - Receipt matching
  - `idx_txn_search`: `(user_id, merchant_name, chase_description)` - Search operations
  - `idx_incoming_user_status`: `(user_id, status, received_at)` - Inbox queries
  - `idx_incoming_user_merchant`: `(user_id, merchant_name, ocr_total)` - Merchant filtering
- All indexes are conditional (`IF NOT EXISTS`) for safe re-running

#### Console.log Cleanup
- Removed all `console.log` statements from production JavaScript files
- Keeps error logging (`console.error`, `console.warn`) for debugging
- Files cleaned:
  - `static/js/auth.js`
  - `static/js/transactions.js`
  - `static/js/receipt_library.js`
  - `static/js/settings.js`
  - `static/js/dashboard.js`

---

### Critical Security Fixes

#### XSS Prevention (`static/js/reconciler.js`)
- **FIXED**: Added `escapeHtml()` to all user-controlled innerHTML:
  - Notes field in transaction table (line 1112)
  - Error messages display (line 4385)
  - Merchant names in stats (line 4694)
  - Subscription names (line 4760)
  - Source names (line 4797)
  - Report names and business types (lines 5101-5102)
- `receipt_library.js` already had escapeHtml implemented

#### SQL Injection Prevention (`db_mysql.py`)
- **VERIFIED**: `ALLOWED_UPDATE_COLUMNS` whitelist prevents dynamic column injection
- Only whitelisted columns can be updated via API
- Unauthorized column updates are logged and rejected

#### CSRF Protection (`viewer_server.py`)
- **VERIFIED**: Flask-WTF CSRFProtect enabled
- `/api/csrf-token` endpoint for SPA token retrieval
- CSRF token in response headers for AJAX requests
- Context processor for template access
- API blueprints properly exempted

#### Security Headers (`viewer_server.py`)
- **VERIFIED**: Comprehensive security headers on all responses:
  - `X-Frame-Options: DENY` - Prevents clickjacking
  - `X-Content-Type-Options: nosniff` - Prevents MIME sniffing
  - `X-XSS-Protection: 1; mode=block` - Legacy XSS filter
  - `Strict-Transport-Security` - HTTPS enforcement (production)
  - `Content-Security-Policy` - Restricts script/style sources

#### Database Connection Management (`db_mysql.py`)
- **VERIFIED**: Connection leak fixed with `_legacy_conn` tracking
- Thread-safe with `_legacy_conn_lock`
- Connection health checks with `ping(reconnect=True)`
- Proper pool return on cleanup

#### Session Fixation Prevention
- **FIXED**: All authentication handlers now regenerate session on successful login
- Added `session.clear()` before setting authentication state in:
  - Password login (`viewer_server.py:2547`)
  - PIN login (`viewer_server.py:2591`)
  - Google OAuth callback (`viewer_server.py:2917`)
  - Apple Sign In callback (`viewer_server.py:3217`)
  - Apple Web Sign In (`routes/auth_routes.py:668`)
  - Google Sign In (`routes/auth_routes.py:1518`)
- Prevents attackers from fixing session ID before authentication

---

### Backend Reliability

#### OCR Provider Timeouts
- **OpenAI**: 30s timeout via client parameter
- **Gemini**: 30s SIGALRM timeout added (`gemini_utils.py`)
- **Ollama**: 30s SIGALRM timeout already implemented
- All providers now fail gracefully instead of hanging

#### Gemini Rate Limiting (`gemini_utils.py`)
- **VERIFIED**: Exponential backoff before key switching
- Delays: 2s, 4s, 8s... up to 30s
- Key exhaustion triggers 60-120s cooldown
- Automatic key rotation with `switch_to_next_key()`

#### OCR Circuit Breaker (`receipt_ocr_service.py`)
- **VERIFIED**: `CircuitBreaker` class prevents hammering failed providers
- 5 failure threshold opens circuit
- 5 minute timeout before retry
- Per-provider failure tracking

#### Gmail Token Management (`gmail_receipt_service.py`)
- **VERIFIED**: Automatic token refresh before API calls
- Checks `creds.expired` and `creds.refresh_token`
- Stores refreshed credentials for future use

#### Refund Detection (`smart_auto_matcher.py`)
- **VERIFIED**: Sign mismatch detection prevents purchase/refund matching
- Positive receipt + negative transaction = 0% match
- Division by zero protection for edge cases

---

### Accessibility (WCAG 2.1 AA Compliance)

#### Accessibility CSS (`static/css/accessibility.css`)
- **NEW**: Comprehensive accessibility stylesheet with:
  - Screen reader only class (`.sr-only`)
  - Skip-to-main-content link
  - Focus-visible styles for keyboard navigation
  - High contrast mode support (`prefers-contrast: high`)
  - Reduced motion support (`prefers-reduced-motion: reduce`)
  - Minimum 44x44px touch targets for interactive elements
  - Error states with accessible colors
  - Loading state announcements with `aria-busy`
  - Tooltip accessibility
  - Form field grouping with fieldset/legend
  - Required field indicators

#### Accessibility JavaScript (`static/js/accessibility.js`)
- **NEW**: Accessibility helper utilities:
  - Live region for screen reader announcements
  - `A11y.announce(message, priority)` for dynamic content updates
  - Focus trap management for modals/dialogs
  - Keyboard navigation helpers (arrow keys, Escape)
  - `A11y.trapFocus(container)` / `A11y.releaseFocus(container)`
  - `A11y.announceFormErrors(form)` for validation feedback
  - `A11y.enhanceTable(table)` for sortable table headers

#### HTML Template Updates
- Added ARIA labels to `auth.html`:
  - Form roles and labels
  - Input `aria-describedby` for error messages
  - Button `aria-label` for icon-only buttons
  - Live regions for authentication status
- Added ARIA labels to `settings.html`:
  - Tab panel roles and states
  - Form section headings
  - Toggle button states

---

### User Interface

#### Loading States System (`static/js/loading-states.js`, `static/css/loading-states.css`)
- **NEW**: Comprehensive loading state utility:
  - `LoadingStates.setLoading(button, text)` - Set button to loading state
  - `LoadingStates.clearLoading(button, success)` - Clear with optional success animation
  - `LoadingStates.setError(button, errorText)` - Show error state briefly
  - `LoadingStates.setProgress(button, percent)` - Progress bar button
  - `LoadingStates.withLoading(button, asyncFn, options)` - Wrap async operations
  - Auto-binding for forms and buttons with `data-loading-text`

```javascript
// Usage examples
LoadingStates.setLoading(submitBtn, 'Saving...');

// Or wrap an async function
await LoadingStates.withLoading(button, async () => {
    await saveData();
}, { loadingText: 'Saving...', showSuccess: true });
```

- CSS support includes:
  - Spinning loader animation
  - Success state (green checkmark)
  - Error state (red with icon)
  - Progress bar button
  - Skeleton loading patterns
  - Page loading overlay
  - Inline loading indicator
  - Table row loading state
  - Card loading state
  - Input loading state
  - Reduced motion support

#### Mobile Responsiveness (`static/css/mobile-responsive.css`)
- **ENHANCED**: Comprehensive mobile-first CSS system (1150+ lines):
  - 6 breakpoints: xs (<375px), sm (≥375px), md (≥768px), lg (≥1024px), xl (≥1280px), 2xl (≥1536px)
  - Responsive typography scale
  - Touch-friendly 44px minimum targets
  - Table scroll wrappers for horizontal overflow
  - Card stack layouts on mobile
  - Responsive grid utilities (`.grid-cols-{1-6}`)
  - Form input sizing
  - Modal/dialog mobile adaptations
  - Bottom sheet pattern for mobile modals
  - Navigation responsive patterns
  - Image responsive utilities
  - Print-friendly styles

---

### iOS App Improvements

#### Offline Queue System (Already Implemented)
Verified existing implementation in:
- `UploadQueue.swift`: Persistent queue with UserDefaults storage
  - Queue management with `enqueue()`, `remove()`, `getAll()`
  - Status tracking: pending, uploading, completed, failed
  - Retry logic with max 3 attempts
  - Progress callbacks
  - Background upload support

- `NetworkMonitor.swift`: Connectivity monitoring
  - NWPathMonitor for real-time status
  - Connection type detection (wifi, cellular, ethernet)
  - Auto-resume pending uploads when connected
  - Published properties for SwiftUI

#### Contact Sync Integration
- **NEW**: Added push/delete methods to `contact_sync_engine.py`:
  - `AppleContactsAdapter.push_contact(contact)`: Create/update contacts via AppleScript
  - `AppleContactsAdapter.delete_contact(contact_id)`: Remove contacts via AppleScript
  - `GoogleContactsAdapter.delete_contact(resource_name)`: Remove via People API
  - Error handling and rollback support

---

### Documentation

#### Keyboard Shortcuts (`static/js/keyboard-shortcuts.js`)
- **NEW**: Comprehensive keyboard shortcut system:
  - Global shortcuts: `?` (help), `/` (search), `Escape` (close)
  - Navigation: `g h` (home), `g t` (transactions), `g l` (library), `g s` (settings)
  - Actions: `n` (new), `s` (save), `d` (delete)
  - Selection: `j/k` (next/prev), `Space` (select), `Cmd+A` (select all)
  - Views: `1/2/3` (grid/list/timeline)
  - Visual help modal with all shortcuts listed
  - Context-aware (disabled in input fields)

---

### Files Created

| File | Purpose |
|------|---------|
| `static/js/storage-utils.js` | Secure localStorage wrapper |
| `static/js/loading-states.js` | Button loading state utility |
| `static/js/accessibility.js` | WCAG accessibility helpers |
| `static/js/keyboard-shortcuts.js` | Keyboard shortcut system |
| `static/css/loading-states.css` | Loading state styles |
| `static/css/accessibility.css` | Accessibility styles |
| `migrations/019_composite_indexes.sql` | Performance indexes |

### Files Enhanced

| File | Changes |
|------|---------|
| `static/css/mobile-responsive.css` | Complete responsive overhaul |
| `static/templates/auth.html` | ARIA labels and roles |
| `static/templates/settings.html` | Accessibility attributes |
| `contact_sync_engine.py` | Push/delete contact methods |
| `ios/TallyScanner/Services/GoogleSignInService.swift` | New Google auth |
| `static/js/reconciler.js` | XSS escapeHtml fixes (6 locations) |
| `gemini_utils.py` | Added 30s timeout protection |

### Security Audit Summary

This release addresses all 20 critical items from the comprehensive security audit (`COMPREHENSIVE_AUDIT_REPORT.md`):

| Category | Items | Status |
|----------|-------|--------|
| XSS Prevention | 6 innerHTML fixes | ✅ Fixed |
| SQL Injection | Column whitelist | ✅ Verified |
| CSRF Protection | Flask-WTF | ✅ Verified |
| Security Headers | CSP, X-Frame, etc. | ✅ Verified |
| Connection Leak | Pool management | ✅ Verified |
| OCR Timeouts | All 3 providers | ✅ Fixed/Verified |
| Rate Limiting | Exponential backoff | ✅ Verified |
| Circuit Breaker | Provider failover | ✅ Verified |
| Token Refresh | Gmail OAuth | ✅ Verified |
| Refund Detection | Matcher algorithm | ✅ Verified |

---

## [2.0.0] - 2024-12-11

### World-Class Receipt Library System

See `CHANGELOG_SESSION_2024_12_11.md` for detailed implementation notes.

#### Major Features
- Receipt Library with 10,000+ capacity
- Sub-100ms natural language search
- Multi-signal duplicate detection (95%+ accuracy)
- Grid/List/Timeline views
- Full dark mode support
- Mobile responsive design

#### Backend Services
- `receipt_library_service.py` - Core CRUD operations
- `duplicate_detector.py` - 5-signal duplicate detection
- `receipt_search.py` - Natural language query parser
- `thumbnail_generator.py` - WebP thumbnail generation

#### Database Schema
- `receipt_library` - Main table with 50+ columns
- `receipt_library_search` - Fast search index
- `receipt_library_duplicates` - Duplicate tracking
- `receipt_library_stats` - Analytics
- `receipt_library_activity` - Audit log

---

## [1.9.0] - 2024-12-01

### Multi-User Authentication System

#### Features
- Apple Sign-In integration
- JWT-based session management
- User scoping for all data
- Demo account support
- Business type management per user

#### Database Changes
- `users` table with Apple ID linking
- `user_sessions` table for JWT tracking
- `user_credentials` table for OAuth tokens
- Added `user_id` columns to transactions and receipts

---

## [1.8.0] - 2024-11-15

### Plaid Integration

- Bank account linking via Plaid
- Automatic transaction import
- Real-time sync support
- Multi-account support

---

## [1.7.0] - 2024-11-01

### Gmail Receipt Integration

- OAuth2 authentication for Gmail
- Automatic receipt detection and parsing
- Label-based organization
- Multi-account support (Personal, MCR, Down Home)

---

## [1.6.0] - 2024-10-15

### OCR & AI Classification

- Multi-provider OCR support (Google Vision, AWS Textract, local)
- AI-powered business type classification
- Smart merchant name normalization
- Receipt-transaction auto-matching

---

## [1.5.0] - 2024-10-01

### iOS TallyScanner App

- Native SwiftUI app
- Camera scanning with VisionKit
- Offline queue support
- Apple Sign-In
- Push notifications

---

## [1.0.0] - 2024-09-01

### Initial Release

- Transaction management
- Manual receipt upload
- Basic categorization
- Dark mode UI
- Export to CSV/Excel

---

## Migration Guide

### Upgrading to 2.1.0

1. **Run database migration**:
```bash
mysql -u root -p railway < migrations/019_composite_indexes.sql
```

2. **Clear browser cache** to load new CSS/JS files

3. **Update iOS app** to latest version for Google Sign-In support

4. **Include new CSS/JS** in your templates:
```html
<link rel="stylesheet" href="/static/css/accessibility.css">
<link rel="stylesheet" href="/static/css/loading-states.css">
<link rel="stylesheet" href="/static/css/mobile-responsive.css">
<script src="/static/js/storage-utils.js"></script>
<script src="/static/js/accessibility.js"></script>
<script src="/static/js/loading-states.js"></script>
<script src="/static/js/keyboard-shortcuts.js"></script>
```

---

## Contributing

When contributing to this project:
1. Follow existing code style and patterns
2. Include accessibility attributes on all interactive elements
3. Test on mobile devices (minimum 375px width)
4. Remove console.log statements before committing
5. Update this CHANGELOG with your changes

---

*Last updated: December 29, 2024*

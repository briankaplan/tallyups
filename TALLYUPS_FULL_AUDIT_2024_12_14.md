# Tallyups (ReceiptAI) Comprehensive Audit Report
**Date:** December 14, 2024
**Auditor:** Principal Full-Stack Engineer
**System Version:** 2025.12.04.v4

---

## Executive Summary

Tallyups is a well-architected expense reconciliation system with strong foundations but significant opportunities for improvement in UX speed, automation, and security hardening. The codebase shows evidence of rapid iteration with some technical debt accumulation.

**Total Issues Found:** 47
**Estimated Total Fix Time:** 96-128 hours
**Critical:** 5 | **High:** 14 | **Medium:** 18 | **Low:** 10

---

## System Inventory

### Route Map (`viewer_server.py` - 26,000+ lines)

| Category | Endpoint Pattern | Count | Auth Required |
|----------|-----------------|-------|---------------|
| Health | `/api/health/*` | 4 | Partial |
| Auth | `/login`, `/logout`, `/auth/*` | 6 | Public |
| Dashboard | `/dashboard/*` | 3 | Session |
| Transactions | `/api/transactions/*` | 5 | Session/API Key |
| OCR | `/api/ocr/*` | 12 | Mixed |
| AI | `/api/ai/*` | 10 | Session |
| Contacts | `/api/contacts/*` | 8 | Session |
| Atlas | `/api/atlas/*` | 20+ | Session |
| Reports | `/api/reports/*` | 10+ | Session |
| Incoming | `/api/incoming/*` | 6 | Session |
| Library | `/api/library/*` | 8 | Session |

### HTML Pages

| File | Purpose | JS Dependencies |
|------|---------|-----------------|
| `receipt_reconciler_viewer.html` | Main transactions UI | `reconciler.js`, `panzoom` |
| `incoming.html` | Gmail inbox queue | Inline JS |
| `receipt_library.html` | Receipt archive | `receipt_library.js` |
| `report_builder.html` | Expense reports | Inline JS |
| `contacts.html` | CRM contacts | Inline JS |
| `mobile_scanner.html` | Mobile capture | Camera API |
| `dashboard_v2.html` | Analytics | Chart.js |
| `settings.html` | User settings | Inline JS |

### App Flow Map

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            RECEIPT INGESTION                                 │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  Gmail Scan ──► Email Filter ──► Attachment Extract ──► Convert to Image   │
│  (3 accounts)    (80+ spam       (PDF/HTML/IMG)         (PyMuPDF/Playwright)│
│                   domains)                                                   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         R2 UPLOAD                                    │   │
│  │  • Upload to Cloudflare R2                                          │   │
│  │  • Generate thumbnail                                                │   │
│  │  • Store in incoming_receipts table                                  │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                         OCR PIPELINE                                 │   │
│  │  1. OpenAI GPT-4o-mini (Primary)                                    │   │
│  │  2. Gemini 2.0 Flash (Fallback)                                     │   │
│  │  3. Ollama Llama 3.2 Vision (Local)                                 │   │
│  │  • Cached by SHA256 hash in MySQL ocr_cache table                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      SMART MATCHING                                  │   │
│  │  • Amount Score: 50% weight                                         │   │
│  │  • Merchant Score: 35% weight                                       │   │
│  │  • Date Score: 15% weight                                           │   │
│  │  • Auto-match threshold: 75%+                                       │   │
│  │  • Duplicate detection: 95% perceptual hash similarity              │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      USER REVIEW                                     │   │
│  │  • Inbox (incoming.html) - Accept/Reject queue                      │   │
│  │  • Reconciler (receipt_reconciler_viewer.html) - Main review        │   │
│  │  • Quick Viewer - Fast keyboard-driven navigation                   │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      CATEGORIZATION                                  │   │
│  │  • MI (Machine Intelligence) auto-classification                    │   │
│  │  • Business Type assignment (Down Home / MCR / Personal)            │   │
│  │  • AI note generation with Claude                                    │   │
│  │  • Calendar/Contact context injection                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                       │                                                      │
│                       ▼                                                      │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                      REPORTING                                       │   │
│  │  • Create expense reports                                           │   │
│  │  • Add verified transactions                                        │   │
│  │  • Export to CSV/Expensify                                          │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## CRITICAL ISSUES (5)

### C-1: R2 URLs Are Permanently Public (SECURITY)
**File:** `r2_service.py:20,75,92`
**Severity:** Critical
**User Impact:** Any receipt URL can be accessed by anyone who has or guesses the URL

**Root Cause:**
```python
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL', 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev')
# ...
public_url = f"{R2_PUBLIC_URL}/{key}"
return f"{R2_PUBLIC_URL}/{key}"
```

All receipt URLs are permanent public URLs without expiration or access control.

**Fix:**
```python
import boto3
from botocore.config import Config

def get_signed_url(key: str, expires_in: int = 3600) -> str:
    """Generate a time-limited signed URL for private R2 access."""
    s3_client = boto3.client(
        's3',
        endpoint_url=f'https://{R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        config=Config(signature_version='s3v4')
    )

    return s3_client.generate_presigned_url(
        'get_object',
        Params={'Bucket': R2_BUCKET_NAME, 'Key': key},
        ExpiresIn=expires_in
    )
```

**Verification:**
1. Change bucket to private in Cloudflare R2 dashboard
2. Test that direct URLs return 403
3. Test that signed URLs work

**Effort:** 4 hours

---

### C-2: CSRF Protection Fallback to Disabled
**File:** `viewer_server.py:44-50,674`
**Severity:** Critical
**User Impact:** If Flask-WTF not installed, all POST endpoints are vulnerable to CSRF attacks

**Root Cause:**
```python
try:
    from flask_wtf.csrf import CSRFProtect, generate_csrf
    CSRF_AVAILABLE = True
except ImportError:
    CSRF_AVAILABLE = False  # Silent fallback!
    print("⚠️ Flask-WTF not installed. CSRF protection disabled.")
```

**Fix:** Make Flask-WTF a hard requirement:
```python
# requirements.txt - make mandatory
Flask-WTF>=1.2.0

# viewer_server.py - fail loud
from flask_wtf.csrf import CSRFProtect, generate_csrf
csrf = CSRFProtect(app)
# Remove try/except fallback
```

**Verification:** Remove Flask-WTF temporarily, verify app fails to start

**Effort:** 1 hour

---

### C-3: Missing Auth on Write Endpoints
**File:** `viewer_server.py:4692-4875`
**Severity:** Critical
**User Impact:** `/update_row` and `/ai_match` endpoints lack consistent auth checks

**Root Cause:**
```python
@app.route("/update_row", methods=["POST"])
def update_row():  # NO @login_required decorator!
    # ... updates database directly
```

**Fix:**
```python
@app.route("/update_row", methods=["POST"])
@login_required
def update_row():
    # Also add API key fallback for mobile app
    admin_key = request.headers.get('X-Admin-Key')
    if not is_authenticated() and admin_key != os.getenv('ADMIN_API_KEY'):
        return jsonify({'error': 'Authentication required'}), 401
```

**Verification:** Test without auth - should return 401

**Effort:** 2 hours

---

### C-4: SQL String Formatting in Query Building
**File:** `viewer_server.py:4558,4566-4572`
**Severity:** Critical
**User Impact:** Potential SQL injection if where_clauses are manipulated

**Root Cause:**
```python
where_sql = f"WHERE {' AND '.join(where_clauses)}" if where_clauses else ""
query = f'''SELECT * FROM transactions {where_sql} ORDER BY...'''
if not return_all:
    query += f' LIMIT {int(per_page)} OFFSET {int(offset)}'  # int() casting is good
```

While `per_page` and `offset` are properly cast to int, `where_clauses` could theoretically contain user input.

**Fix:** Use parameterized queries consistently:
```python
def build_transactions_query(filters: dict) -> Tuple[str, List]:
    """Build parameterized query with proper escaping."""
    where_parts = []
    params = []

    if not filters.get('show_in_report'):
        where_parts.append("(report_id IS NULL OR report_id = '')")

    if filters.get('business_type'):
        where_parts.append("business_type = %s")
        params.append(filters['business_type'])

    where_sql = f"WHERE {' AND '.join(where_parts)}" if where_parts else ""
    return where_sql, params
```

**Effort:** 3 hours

---

### C-5: Logging May Contain PII
**File:** Multiple files
**Severity:** Critical
**User Impact:** Sensitive receipt data/email content may appear in logs

**Root Cause:** Print statements include receipt text:
```python
print(f"      📧 Processing email: {subject}")  # Subject may contain PII
print(f"      OCR extracted: {extracted_text}")  # Full receipt text
```

**Fix:** Create structured logging that redacts PII:
```python
def sanitize_for_log(text: str, max_len: int = 50) -> str:
    """Redact PII from log output."""
    if not text:
        return "[empty]"
    # Remove email addresses
    text = re.sub(r'[\w.-]+@[\w.-]+', '[EMAIL]', text)
    # Remove phone numbers
    text = re.sub(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b', '[PHONE]', text)
    # Remove credit card numbers
    text = re.sub(r'\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b', '[CARD]', text)
    return text[:max_len] + '...' if len(text) > max_len else text
```

**Effort:** 4 hours

---

## HIGH PRIORITY ISSUES (14)

### H-1: Panzoom Zoom/Pan Doesn't Work Correctly
**File:** `static/js/reconciler.js:2000-2007`
**Severity:** High
**User Impact:** Users can't properly zoom and pan receipts - image escapes viewport

**Root Cause:**
```javascript
panzoomInstance = Panzoom(img, {
    maxScale: 5,
    minScale: 0.5,
    startScale: 1.2,
    contain: 'outside'  // BUG: 'outside' lets image escape container!
});

wrap.addEventListener('wheel', panzoomInstance.zoomWithWheel);  // BUG: Event on wrong element
```

**Problems:**
1. `contain: 'outside'` allows image to move entirely outside container
2. Wheel listener attached to wrapper, not image
3. No touch gesture support for mobile

**Fix:**
```javascript
// After image loads
if (panzoomInstance) panzoomInstance.destroy();

panzoomInstance = Panzoom(img, {
    maxScale: 8,
    minScale: 0.3,
    startScale: 1.0,
    contain: 'inside',  // FIXED: Keep image within container bounds
    cursor: 'grab',
    touchAction: 'none'  // Enable touch gestures
});

// FIXED: Attach wheel to image element, prevent default scroll
img.addEventListener('wheel', (e) => {
    e.preventDefault();
    panzoomInstance.zoomWithWheel(e);
}, { passive: false });

// Add touch support
img.addEventListener('touchstart', () => {
    img.style.cursor = 'grabbing';
});
img.addEventListener('touchend', () => {
    img.style.cursor = 'grab';
});
```

**Verification:**
1. Load receipt image
2. Zoom in with scroll wheel - image should stay within container
3. Pan with mouse drag - image should not leave visible area
4. Test on mobile with pinch-to-zoom

**Effort:** 2 hours

---

### H-2: Quick Viewer Has Same Panzoom Issues
**File:** `static/js/reconciler.js:2348-2365`
**Severity:** High
**User Impact:** Quick Viewer modal has identical zoom/pan bugs

**Root Cause:** Same Panzoom configuration as main viewer

**Fix:** Apply same fix as H-1 to Quick Viewer initialization at line 2351

**Effort:** 1 hour

---

### H-3: Keyboard Shortcuts Not Connected to Main App
**File:** `static/js/keyboard.js` + `reconciler.js`
**Severity:** High
**User Impact:** Keyboard.js class exists but isn't initialized anywhere

**Root Cause:**
```javascript
// keyboard.js defines KeyboardHandler class
class KeyboardHandler {
    constructor(reviewInterface) {
        this.ui = reviewInterface;  // Expects a UI interface
    }
    // ...
}

// But reconciler.js never instantiates it!
// The keyboard handling in reconciler.js is separate/duplicated
```

**Fix:**
```javascript
// At end of reconciler.js, after DOMContentLoaded
document.addEventListener('DOMContentLoaded', async () => {
    // ... existing init code ...

    // Initialize keyboard handler with UI bridge
    window.keyboardHandler = new KeyboardHandler({
        navigate: (delta) => navigateRow(delta),
        togglePreview: () => openQuickViewer(),
        closeAll: () => { closeQuickViewer(); closeMobileReceiptViewer(); },
        setReviewStatus: (status) => markStatus(status),
        setBusinessType: (type) => updateBusinessType(type),
        aiMatch: () => aiMatch(),
        generateAINote: () => aiNote(),
        showToast: showToast,
        refresh: () => loadCSV(),
        // ... map all actions
    });
});
```

**Effort:** 3 hours

---

### H-4: Bulk Actions UI Not Visible in Main App
**File:** `static/js/bulk-actions.js`
**Severity:** High
**User Impact:** Full bulk operations system exists but isn't wired to the UI

**Root Cause:** BulkActions class is defined but never instantiated or accessible from the main app

**Fix:** Add bulk selection mode to reconciler:
```javascript
// In reconciler.js
let bulkActions = null;

document.addEventListener('DOMContentLoaded', () => {
    // ... existing init ...

    bulkActions = new BulkActions({
        getFilteredTransactions: () => filteredData,
        getAllTransactions: () => csvData,
        showToast: showToast,
        refresh: () => loadCSV()
    });
});

// Add multi-select with Shift+Click
function handleRowClick(e, row) {
    if (e.shiftKey && bulkActions) {
        bulkActions.toggle(row._index);
        return;
    }
    // ... normal selection
}

// Add bulk action button to toolbar
<button onclick="bulkActions.open()" id="bulk-action-btn" style="display:none">
    📦 Bulk (<span id="bulk-count">0</span>)
</button>
```

**Effort:** 4 hours

---

### H-5: Virtual Scrolling Threshold Too High
**File:** `static/js/reconciler.js:1217-1223`
**Severity:** High
**User Impact:** Large datasets (500+) are slow because virtual scrolling only kicks in at 200

**Root Cause:**
```javascript
const VIRTUAL_SCROLL_CONFIG = {
    rowHeight: 48,        // Hardcoded - rows may vary
    bufferSize: 20,
    enabled: true,
    threshold: 200        // Too high - should be 50
};
```

**Fix:**
```javascript
const VIRTUAL_SCROLL_CONFIG = {
    rowHeight: 52,        // Measured actual row height
    bufferSize: 15,       // Smaller buffer = faster
    enabled: true,
    threshold: 50,        // Enable earlier
    measureRows: true     // Dynamic row height measurement
};

// Add row height measurement
function measureRowHeight() {
    const row = document.querySelector('tbody tr');
    if (row) {
        VIRTUAL_SCROLL_CONFIG.rowHeight = row.offsetHeight || 52;
    }
}
```

**Effort:** 2 hours

---

### H-6: N+1 Query Pattern in Transactions Endpoint
**File:** `viewer_server.py:4576-4582`
**Severity:** High
**User Impact:** Extra query for rejected_receipts on every page load

**Root Cause:**
```python
# Main query
cursor.execute(query)
rows = cursor.fetchall()

# SEPARATE query for rejected - N+1!
cursor.execute('SELECT receipt_path FROM rejected_receipts')
rejected_paths = {r['receipt_path'] for r in cursor.fetchall()}
```

**Fix:** Use JOIN or fetch once and cache:
```python
# Option 1: JOIN
query = '''
    SELECT t.*,
           CASE WHEN r.receipt_path IS NOT NULL THEN 1 ELSE 0 END as is_rejected
    FROM transactions t
    LEFT JOIN rejected_receipts r ON t.receipt_file = r.receipt_path
    {where_sql}
    ORDER BY t.chase_date DESC
'''

# Option 2: Cache rejected paths (better for large tables)
@functools.lru_cache(maxsize=1)
def get_rejected_paths(cache_key: str) -> Set[str]:
    """Cache rejected paths for 60 seconds."""
    cursor.execute('SELECT receipt_path FROM rejected_receipts')
    return {r['receipt_path'] for r in cursor.fetchall()}

# Use with time-based cache key
cache_key = f"rejected_{int(time.time() // 60)}"
rejected_paths = get_rejected_paths(cache_key)
```

**Effort:** 2 hours

---

### H-7: Missing Index on Common Filter Columns
**File:** `db_mysql.py:736-742`
**Severity:** High
**User Impact:** Slow queries when filtering by date range + business type

**Root Cause:** No composite index for common filter patterns

**Fix:** Add composite indexes:
```sql
-- Add to migrations
CREATE INDEX idx_tx_date_business ON transactions(chase_date DESC, business_type);
CREATE INDEX idx_tx_business_status ON transactions(business_type, review_status);
CREATE INDEX idx_tx_amount_date ON transactions(chase_amount, chase_date DESC);

-- For incoming_receipts
CREATE INDEX idx_inc_status_date ON incoming_receipts(status, received_date DESC);
CREATE INDEX idx_inc_source_status ON incoming_receipts(source, status);
```

**Effort:** 1 hour

---

### H-8: No Receipt Image Prefetching
**File:** `static/js/reconciler.js`
**Severity:** High
**User Impact:** Waiting for each receipt image to load when navigating

**Root Cause:** Images only load when user navigates to a row

**Fix:** Add prefetching:
```javascript
// Prefetch next/prev images when selecting a row
function selectRow(row) {
    // ... existing selection code ...

    // Prefetch adjacent receipts
    const currentIdx = filteredData.findIndex(r => r._index === row._index);
    prefetchAdjacentReceipts(currentIdx);
}

function prefetchAdjacentReceipts(currentIdx) {
    const indices = [currentIdx - 1, currentIdx + 1, currentIdx + 2];

    indices.forEach(idx => {
        if (idx >= 0 && idx < filteredData.length) {
            const row = filteredData[idx];
            const url = row.r2_url || row.receipt_url || row['Receipt File'];
            if (url) {
                const img = new Image();
                img.src = url.startsWith('http') ? url : `/receipts/${url}`;
            }
        }
    });
}
```

**Effort:** 1 hour

---

### H-9: HTML Email Screenshots Not Cached
**File:** `incoming_receipts_service.py:95-174`
**Severity:** High
**User Impact:** Playwright browser launches for every HTML email, slow processing

**Root Cause:** No caching of HTML to image conversion

**Fix:**
```python
import hashlib

HTML_SCREENSHOT_CACHE = {}

def convert_html_to_image_cached(html_content: str) -> bytes:
    """Cache HTML screenshots by content hash."""
    content_hash = hashlib.md5(html_content.encode()).hexdigest()[:16]

    if content_hash in HTML_SCREENSHOT_CACHE:
        return HTML_SCREENSHOT_CACHE[content_hash]

    result = convert_html_to_image(html_content)
    if result:
        HTML_SCREENSHOT_CACHE[content_hash] = result
        # Limit cache size
        if len(HTML_SCREENSHOT_CACHE) > 100:
            HTML_SCREENSHOT_CACHE.pop(next(iter(HTML_SCREENSHOT_CACHE)))

    return result
```

**Effort:** 1 hour

---

### H-10: Reports Page Too Manual
**File:** `report_builder.html`
**Severity:** High
**User Impact:** Creating expense reports requires many clicks, no auto-grouping

**Root Cause:** Basic add/remove interface without smart suggestions

**Fix - Add smart report creation:**
```javascript
async function createSmartReport(options) {
    // Auto-group by date range and business type
    const response = await fetch('/api/reports/smart-create', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            business_type: options.businessType,
            date_start: options.startDate,
            date_end: options.endDate,
            auto_include_verified: true,
            auto_group_by_category: true
        })
    });

    const report = await response.json();
    showToast(`Created report with ${report.item_count} transactions`, '📊');
}

// One-click report creation buttons
<button onclick="createSmartReport({
    businessType: 'Down Home',
    startDate: getLastMonthStart(),
    endDate: getLastMonthEnd()
})">
    📊 Create Down Home Report (Last Month)
</button>
```

**Effort:** 6 hours

---

### H-11: Mobile Receipt Viewer Panzoom Issues
**File:** `static/js/reconciler.js:5273-5285`
**Severity:** High
**User Impact:** Same panzoom issues on mobile viewer

**Root Cause:** Same configuration issues as H-1

**Fix:** Apply consistent panzoom configuration across all viewers

**Effort:** 1 hour

---

### H-12: No Batch OCR from UI
**File:** Multiple
**Severity:** High
**User Impact:** Can't trigger OCR re-extraction for multiple receipts at once

**Fix:** Add batch OCR endpoint and UI:
```python
@app.route("/api/ocr/batch-extract", methods=["POST"])
@login_required
def batch_ocr_extract():
    """Run OCR on multiple receipts."""
    data = request.get_json()
    receipt_ids = data.get('receipt_ids', [])

    results = []
    for rid in receipt_ids[:50]:  # Limit to 50
        result = extract_ocr_for_receipt(rid)
        results.append({'id': rid, 'success': result.get('ok', False)})

    return jsonify({'processed': len(results), 'results': results})
```

**Effort:** 3 hours

---

### H-13: Description Engine Lacks Confidence Scores
**File:** `merchant_intelligence.py`
**Severity:** High
**User Impact:** AI-generated descriptions have no visible confidence, users can't trust them

**Root Cause:** MerchantIntelligence returns normalized names but no confidence metadata

**Fix:**
```python
class MerchantIntelligence:
    def normalize(self, merchant: str) -> Dict[str, Any]:
        """Return normalized name with confidence."""
        result = {
            'original': merchant,
            'normalized': '',
            'confidence': 0.0,
            'method': 'unknown',
            'chain_match': None
        }

        # Exact chain match = 100% confidence
        m_lower = merchant.lower().strip()
        if m_lower in self.chain_lookup:
            result['normalized'] = self.chain_lookup[m_lower]
            result['confidence'] = 1.0
            result['method'] = 'chain_exact'
            result['chain_match'] = True
            return result

        # Fuzzy match = lower confidence
        best_match = self._fuzzy_match(m_lower)
        if best_match:
            result['normalized'] = best_match['name']
            result['confidence'] = best_match['score']
            result['method'] = 'fuzzy'
            return result

        # Cleaned but unmatched
        result['normalized'] = self._clean_merchant(merchant)
        result['confidence'] = 0.5
        result['method'] = 'cleaned'
        return result
```

**Effort:** 3 hours

---

### H-14: Calendar Context Not Used in Notes
**File:** `services/smart_notes_service.py` (referenced in ARCHITECTURE.md)
**Severity:** High
**User Impact:** AI notes don't mention meetings/appointments on same day

**Fix:** Inject calendar context into note generation:
```python
async def generate_smart_note(transaction: dict) -> dict:
    """Generate note with calendar context."""
    tx_date = parse_date(transaction.get('chase_date'))

    # Get calendar events for that day
    calendar_events = await get_calendar_events(
        tx_date - timedelta(hours=12),
        tx_date + timedelta(hours=12)
    )

    # Get contacts who might be attendees
    merchant = transaction.get('chase_description', '')
    nearby_contacts = search_contacts_by_company(merchant)

    # Build context for AI
    context = {
        'transaction': transaction,
        'calendar_events': calendar_events,
        'potential_attendees': nearby_contacts,
        'merchant_category': get_merchant_category(merchant)
    }

    note = await generate_with_claude(context)

    return {
        'note': note.text,
        'confidence': note.confidence,
        'suggested_attendees': note.attendees,
        'calendar_matches': [e.title for e in calendar_events],
        'explanation': note.reasoning
    }
```

**Effort:** 8 hours

---

## MEDIUM PRIORITY ISSUES (18)

### M-1: Receipt Viewer Fragmentation
**Files:** Multiple implementations across `reconciler.js`
**Impact:** Inconsistent UX, code duplication
**Fix:** Create unified `ReceiptViewer` class
**Effort:** 6 hours

### M-2: No Rate Limiting on Most Endpoints
**File:** `viewer_server.py`
**Impact:** DoS vulnerability
**Fix:** Add Flask-Limiter
**Effort:** 3 hours

### M-3: Connection Pool Status Not Exposed in UI
**File:** `/api/health/pool-status`
**Impact:** DevOps can't monitor pool health easily
**Fix:** Add pool status to admin dashboard
**Effort:** 2 hours

### M-4: UTC Timestamp Inconsistency
**Files:** Multiple
**Impact:** Date mismatches across timezones
**Fix:** Enforce UTC throughout, convert on display
**Effort:** 4 hours

### M-5: No Image Optimization
**File:** R2 upload flow
**Impact:** Large images slow loading
**Fix:** Add WebP conversion and size limits
**Effort:** 4 hours

### M-6: Missing Error Boundaries in JS
**File:** `reconciler.js`
**Impact:** Single error crashes whole UI
**Fix:** Add try/catch wrappers
**Effort:** 2 hours

### M-7: No Loading Skeletons for Lists
**File:** `incoming.html`, `reconciler.js`
**Impact:** Poor perceived performance
**Fix:** Add skeleton components
**Effort:** 2 hours

### M-8: Search Not Debounced
**File:** `reconciler.js:applyFilters`
**Impact:** Excessive re-renders while typing
**Fix:** Add debounce(300ms)
**Effort:** 1 hour

### M-9: No Undo After Batch Operations
**File:** `bulk-actions.js`
**Impact:** No recovery from bulk mistakes
**Fix:** Store undo state before batch
**Effort:** 3 hours

### M-10: API Responses Not Compressed
**File:** `viewer_server.py`
**Impact:** Slow on slow networks
**Fix:** Add Flask-Compress
**Effort:** 1 hour

### M-11: No Service Worker Caching Strategy
**File:** `sw.js` (referenced in manifest)
**Impact:** No offline support
**Fix:** Implement workbox strategies
**Effort:** 4 hours

### M-12: Gmail Token Refresh Could Fail Silently
**File:** `gmail_search.py`
**Impact:** Expired tokens cause silent failures
**Fix:** Add token refresh monitoring
**Effort:** 2 hours

### M-13: No Duplicate Detection UI
**File:** `smart_auto_matcher.py` has logic, no UI
**Impact:** Duplicates require manual review
**Fix:** Add duplicate review queue
**Effort:** 4 hours

### M-14: OpenAI API Key Not Rotated
**File:** Multiple OCR files
**Impact:** Single point of failure
**Fix:** Add key rotation support
**Effort:** 2 hours

### M-15: No Export Progress Indicator
**File:** `bulk-actions.js:exportCSV`
**Impact:** Large exports appear frozen
**Fix:** Stream export with progress
**Effort:** 2 hours

### M-16: Business Type Quick Buttons Not Prominent
**File:** `receipt_reconciler_viewer.html`
**Impact:** Extra clicks to set common types
**Fix:** Add floating action buttons
**Effort:** 2 hours

### M-17: No Dark/Light Mode Toggle Persistence
**File:** `reconciler.js:loadTheme`
**Impact:** Theme resets on reload
**Fix:** Store in localStorage
**Effort:** 0.5 hours

### M-18: Mobile Cards Don't Virtual Scroll
**File:** `reconciler.js:renderMobileCards`
**Impact:** Mobile slow with many transactions
**Fix:** Add intersection observer
**Effort:** 3 hours

---

## LOW PRIORITY ISSUES (10)

| ID | Issue | File | Effort |
|----|-------|------|--------|
| L-1 | No keyboard shortcut cheatsheet print view | keyboard.js | 1h |
| L-2 | Toast notifications stack incorrectly | reconciler.js | 1h |
| L-3 | No favicon for PWA home screen | manifest.json | 0.5h |
| L-4 | Missing aria-labels for accessibility | All HTML | 4h |
| L-5 | No haptic feedback on mobile actions | reconciler.js | 1h |
| L-6 | Console.log statements in production | Multiple | 2h |
| L-7 | No analytics/telemetry for UX optimization | viewer_server.py | 4h |
| L-8 | Search highlight doesn't work in table | reconciler.js | 2h |
| L-9 | No email notification for new receipts | incoming_receipts_service.py | 3h |
| L-10 | Reports don't have PDF export | report_builder.html | 4h |

---

## PERSONA FINDINGS

### Power User (Speed + Automation)

**Pain Points:**
1. Keyboard shortcuts exist but aren't connected (H-3)
2. Bulk actions hidden in separate file (H-4)
3. No quick filters for common patterns (e.g., "all unmatched from last week")
4. Receipt zoom/pan frustrating (H-1)

**Wants:**
- Process 50+ transactions per minute
- Never touch the mouse
- Auto-categorize with learning

**Recommendations:**
1. Wire up keyboard.js properly
2. Add "Speed Mode" with minimal UI
3. Show keyboard hints inline
4. Add vim-style command palette (`/` to search, `:` for commands)

### CFO/Ops (Throughput)

**Pain Points:**
1. Can't see processing pipeline status
2. Reports too manual (H-10)
3. No monthly summaries auto-generated
4. No compliance audit trail

**Wants:**
- Dashboard showing pending/completed/issues
- One-click monthly report generation
- Export that matches accountant's format

**Recommendations:**
1. Add ops dashboard with pipeline metrics
2. Create report templates
3. Add approval workflow
4. Generate compliance logs

### Auditor (Defensibility)

**Pain Points:**
1. No audit trail for who changed what
2. AI decisions not explained
3. Original receipt vs. modified not tracked
4. Confidence scores hidden

**Wants:**
- Full change history
- AI reasoning visible
- Original artifacts preserved
- Match confidence visible

**Recommendations:**
1. Add audit_log table with all changes
2. Show AI confidence in UI (H-13)
3. Keep immutable original receipt copies
4. Add "Why this match?" tooltip

### Security Engineer (Attack Surface)

**Pain Points:**
1. R2 URLs permanently public (C-1)
2. CSRF optional (C-2)
3. Some endpoints unprotected (C-3)
4. PII in logs (C-5)

**Wants:**
- All URLs signed and expiring
- All endpoints authenticated
- No PII in logs
- Rate limiting everywhere

**Recommendations:**
1. Fix critical security issues first
2. Add security headers
3. Implement WAF rules
4. Add anomaly detection

### Performance Engineer (P95 Latency)

**Pain Points:**
1. Virtual scroll threshold too high (H-5)
2. N+1 queries (H-6)
3. No image prefetch (H-8)
4. No response compression (M-10)

**Metrics Needed:**
- `/api/transactions` p95 < 200ms
- Image load p95 < 500ms
- OCR extraction p95 < 5s
- Full page TTI < 2s

**Recommendations:**
1. Add DataDog/New Relic APM
2. Implement Redis cache layer
3. Add CDN for R2 assets
4. Profile and fix slow queries

---

## UI/UX UPGRADE SPEC

### Component Library

Create these reusable components:

```javascript
// components/ReceiptViewer.js
class ReceiptViewer {
    constructor(container, options = {}) {
        this.container = container;
        this.options = {
            maxScale: 8,
            minScale: 0.3,
            enableTouch: true,
            contain: 'inside',
            ...options
        };
        this.init();
    }

    init() { /* Unified panzoom setup */ }
    load(url) { /* Load image with prefetch */ }
    zoom(delta) { /* Zoom in/out */ }
    reset() { /* Reset to fit */ }
    rotate(degrees) { /* Rotate image */ }
}

// components/TransactionTable.js
class TransactionTable {
    constructor(container, options = {}) {
        this.virtualScroll = new VirtualScroller(this);
        this.bulkActions = new BulkActions(this);
        this.keyboard = new KeyboardHandler(this);
    }
}

// components/BatchProcessor.js
class BatchProcessor {
    async process(items, processor, options) {
        // Unified batch processing with progress
    }
}
```

### Keyboard Shortcut Reference

| Category | Key | Action |
|----------|-----|--------|
| **Navigation** | | |
| | ↑ / k | Previous row |
| | ↓ / j | Next row |
| | Enter | Open quick viewer |
| | q | Toggle quick viewer |
| | Escape | Close all modals |
| **Quick Actions** | | |
| | g | Mark as Good |
| | b | Mark as Bad |
| | d | Set Down Home |
| | m | Set MCR |
| | p | Set Personal |
| **Bulk** | | |
| | Shift+Click | Multi-select |
| | Ctrl+A | Select all visible |
| | Ctrl+Shift+A | Open bulk actions |
| **AI** | | |
| | Shift+A | AI Match |
| | Shift+J | Generate AI Note |
| **Image** | | |
| | + / = | Zoom in |
| | - | Zoom out |
| | 0 | Reset zoom |
| | Shift+R | Rotate 90° |
| **Search** | | |
| | / | Focus search |
| | 1-4 | Quick business filter |
| | u | Show unmatched only |

### Performance Targets

| Metric | Target | Current Est. |
|--------|--------|--------------|
| Transactions API p95 | < 200ms | ~400ms |
| Image load p95 | < 500ms | ~1500ms |
| OCR extraction p95 | < 5s | ~8s |
| Full page TTI | < 2s | ~3.5s |
| Virtual scroll FPS | 60fps | ~45fps |
| Memory usage (1000 rows) | < 50MB | ~120MB |

---

## QUICK WINS (< 1 hour each)

| # | Fix | File | Time |
|---|-----|------|------|
| 1 | Change `contain: 'outside'` to `'inside'` | reconciler.js:2004 | 5m |
| 2 | Lower virtual scroll threshold to 50 | reconciler.js:1222 | 5m |
| 3 | Add `e.preventDefault()` to wheel zoom | reconciler.js:2007 | 5m |
| 4 | Add debounce to search input | reconciler.js | 15m |
| 5 | Store theme preference in localStorage | reconciler.js | 15m |
| 6 | Add composite index on transactions | db_mysql.py | 20m |
| 7 | Enable Flask-Compress | viewer_server.py | 15m |
| 8 | Add prefetch for adjacent receipts | reconciler.js | 30m |
| 9 | Fix bulk actions initialization | reconciler.js | 30m |
| 10 | Add @login_required to update_row | viewer_server.py | 10m |

---

## 2-WEEK "MAKE IT SLAY" EXECUTION PLAN

### Week 1: Security + Core UX

**Day 1-2: Critical Security**
- [ ] C-1: Implement R2 signed URLs (4h)
- [ ] C-2: Make Flask-WTF mandatory (1h)
- [ ] C-3: Add auth to all write endpoints (2h)

**Day 3-4: Receipt Viewer Overhaul**
- [ ] H-1, H-2, H-11: Fix all panzoom issues (4h)
- [ ] Create unified ReceiptViewer component (6h)
- [ ] Add image prefetching (1h)

**Day 5: Keyboard + Bulk Actions**
- [ ] H-3: Wire up keyboard.js (3h)
- [ ] H-4: Connect bulk actions to UI (4h)

### Week 2: Speed + Automation

**Day 6-7: Performance**
- [ ] H-5: Lower virtual scroll threshold (1h)
- [ ] H-6: Fix N+1 query pattern (2h)
- [ ] H-7: Add missing indexes (1h)
- [ ] M-10: Add response compression (1h)
- [ ] Add loading skeletons (2h)

**Day 8-9: Smart Features**
- [ ] H-13: Add confidence scores to UI (3h)
- [ ] H-14: Inject calendar context (8h)
- [ ] H-10: Smart report creation (6h)

**Day 10: Polish + Testing**
- [ ] Fix remaining medium priority items
- [ ] Full regression test
- [ ] Performance benchmarking
- [ ] Deploy to staging

---

## Summary Metrics

| Category | Count | Est. Hours |
|----------|-------|------------|
| Critical | 5 | 14h |
| High | 14 | 38h |
| Medium | 18 | 48h |
| Low | 10 | 22h |
| **Total** | **47** | **122h** |

**Recommended Phase 1 (Week 1):** 34h - Security + Core UX
**Recommended Phase 2 (Week 2):** 24h - Speed + Automation
**Remaining (Backlog):** 64h - Polish + Advanced Features

---

*Report generated by Principal Full-Stack Engineer audit*
*December 14, 2024*

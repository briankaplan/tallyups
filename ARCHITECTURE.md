# ReceiptAI/TallyUps Architecture Documentation

## Overview

ReceiptAI is an AI-powered expense management system that automatically captures receipts from Gmail, matches them to bank transactions, and generates intelligent expense reports.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Frontend (HTML/JS)                          │
├─────────────────────────────────────────────────────────────────────┤
│  receipt_reconciler_viewer.html  │  incoming.html  │  library.html  │
│  mobile_scanner.html             │  reports.html   │  contacts.html │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────┐
│                     Flask Application (viewer_server.py)            │
├─────────────────────────────────────────────────────────────────────┤
│  Blueprints:                                                        │
│  ├── routes/notes.py      → /api/notes/*     (AI note generation)  │
│  ├── routes/incoming.py   → /api/incoming/*  (Gmail inbox)         │
│  ├── routes/reports.py    → /api/reports/*   (Expense reports)     │
│  └── routes/library.py    → /api/library/*   (Receipt library)     │
│                                                                     │
│  Core Routes (still in viewer_server.py):                          │
│  ├── /api/transactions/*  (CRUD for expenses)                      │
│  ├── /api/contacts/*      (Contact management)                     │
│  ├── /api/admin/*         (Admin operations)                       │
│  └── /mobile-upload       (Mobile receipt capture)                 │
└─────────────────────────────────────────────────────────────────────┘
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
┌─────────────────────┐ ┌─────────────────┐ ┌─────────────────┐
│   MySQL Database    │ │ Cloudflare R2   │ │   Gmail API     │
│   (Railway)         │ │ (Receipt Store) │ │ (3 accounts)    │
└─────────────────────┘ └─────────────────┘ └─────────────────┘
```

## Directory Structure

```
ReceiptAI-MASTER-LIBRARY/
├── viewer_server.py          # Main Flask application (25K+ lines)
├── db_mysql.py               # MySQL database layer with connection pooling
├── db_config.py              # Centralized database configuration
│
├── routes/                   # Flask blueprints (modular routes)
│   ├── __init__.py
│   ├── notes.py              # /api/notes/* - AI note generation
│   ├── incoming.py           # /api/incoming/* - Gmail inbox system
│   ├── reports.py            # /api/reports/* - Expense reports
│   └── library.py            # /api/library/* - Receipt library
│
├── services/                 # Business logic services
│   ├── smart_notes_service.py    # Claude-powered note generation
│   ├── expense_report_service.py # Report generation
│   ├── receipt_classifier.py     # Receipt categorization
│   └── receipt_deduplicator.py   # Duplicate detection
│
├── incoming_receipts_service.py  # Gmail scanning & filtering
├── receipt_ocr_service.py        # OCR extraction (OpenAI/Gemini/Ollama)
├── smart_auto_matcher.py         # Receipt-to-transaction matching
├── merchant_intelligence.py      # Merchant normalization & learning
├── r2_service.py                 # Cloudflare R2 storage
│
├── static/                   # Static assets
│   ├── css/
│   └── js/
│
├── templates/                # Jinja2 templates
│
└── scripts/                  # Utility scripts
    ├── search/               # Receipt search utilities
    ├── ocr/                  # OCR processing scripts
    ├── db/                   # Database migrations
    └── gmail/                # Gmail authentication
```

## Core Components

### 1. Database Layer (`db_mysql.py`)

**Connection Pooling:**
```python
pool_size = 20        # Base connections
max_overflow = 30     # Peak capacity (50 total)
pool_timeout = 60     # Wait time for connection
pool_recycle = 300    # Connection lifetime (5 min)
```

**Key Tables:**
| Table | Purpose |
|-------|---------|
| `transactions` | Core expense data from bank statements |
| `incoming_receipts` | Gmail inbox receipts pending review |
| `receipt_metadata` | OCR extraction results |
| `reports` | Expense report definitions |
| `merchants` | Learned merchant patterns |
| `ocr_cache` | Cached OCR results (SHA256 hashed) |
| `contacts` | CRM contacts for attendee matching |

### 2. OCR Pipeline (`receipt_ocr_service.py`)

**Fallback Chain:**
1. **OpenAI gpt-4o-mini** (Primary) - Best accuracy
2. **Gemini 2.0 Flash** (Fallback) - Free tier
3. **Ollama Llama 3.2 Vision** (Local) - Offline capable

**Caching:**
- SHA256 hash of image → MySQL `ocr_cache` table
- Cache hit = instant response (no API call)
- Confidence threshold: 0.3 minimum to cache

### 3. Matching Algorithm (`smart_auto_matcher.py`)

**Weighted Scoring:**
```
Amount Score:  50% weight
Merchant Score: 35% weight
Date Score:    15% weight
```

**Thresholds:**
- Auto-match: 75%+ confidence
- Review needed: 50-75%
- Duplicate detection: 95% similar (perceptual hash)

**Date Tolerance:**
- Retail: ±3 days
- Subscriptions: ±7 days
- Delivery: ±14 days

### 4. Gmail Integration (`incoming_receipts_service.py`)

**Accounts Monitored:**
- kaplan.brian@gmail.com
- brian@business.com
- brian@secondary.com

**Spam Filtering:**
- 80+ blocked domains (mailchimp, sendgrid, etc.)
- Subject pattern matching
- Sender analysis
- Database-backed subscription learning

**Receipt Processing:**
1. Scan Gmail for new emails
2. Filter marketing/spam
3. Extract attachments (PDF, images)
4. Convert HTML emails to screenshots (Playwright)
5. Upload to R2 storage
6. Run OCR extraction
7. Attempt auto-match to transactions

### 5. Smart Notes Service (`services/smart_notes_service.py`)

**Data Sources Combined:**
- Transaction details (merchant, amount, date)
- Receipt OCR data (line items, totals)
- Calendar events (meetings, appointments)
- Contact database (attendee matching)

**Output:**
- AI-generated expense note
- Suggested attendees
- Business purpose
- Tax category
- Confidence score

## API Endpoints

### Notes API (`/api/notes/*`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/generate` | Generate AI note for transaction |
| POST | `/batch` | Batch generate notes |
| PUT | `/<tx_id>` | Update/edit note |
| POST | `/regenerate` | Regenerate with new context |
| GET | `/status` | Service status |

### Incoming API (`/api/incoming/*`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/receipts` | List inbox receipts |
| POST | `/accept` | Accept as transaction |
| POST | `/reject` | Reject receipt |
| POST | `/scan` | Trigger Gmail scan |
| GET | `/stats` | Inbox statistics |
| POST | `/cleanup` | Clean old rejected |

### Reports API (`/api/reports/*`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/` | List all reports |
| POST | `/` | Create new report |
| PATCH | `/<id>` | Update report |
| POST | `/<id>/add` | Add transaction |
| POST | `/<id>/remove` | Remove transaction |
| GET | `/<id>/items` | Get report items |
| GET | `/dashboard` | Dashboard data |
| GET | `/stats` | Report statistics |

### Library API (`/api/library/*`)
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/receipts` | List receipts |
| GET | `/search` | Search receipts |
| GET | `/counts` | Receipt counts |
| GET | `/stats` | Library statistics |
| GET | `/tags` | List tags |
| POST | `/tags` | Create tag |
| GET | `/collections` | List collections |
| POST | `/collections` | Create collection |

## Environment Variables

### Required
```bash
# MySQL Database
MYSQL_URL=mysql://user:pass@host:port/database
# OR individual vars:
MYSQLHOST=
MYSQLUSER=
MYSQLPASSWORD=
MYSQLDATABASE=

# API Keys
OPENAI_API_KEY=sk-...
GEMINI_API_KEY=...
ADMIN_API_KEY=...        # For API authentication

# R2 Storage
R2_ACCOUNT_ID=
R2_ACCESS_KEY_ID=
R2_SECRET_ACCESS_KEY=
R2_BUCKET_NAME=
R2_PUBLIC_URL=
```

### Optional
```bash
RAILWAY_ENVIRONMENT=production  # Enables scheduled tasks
DB_READ_ONLY=false              # Read-only mode
FLASK_SECRET_KEY=               # Session encryption
```

## Deployment

### Railway Configuration
- **Build**: Nixpacks (auto-detected Python)
- **Start Command**: `gunicorn viewer_server:app`
- **Health Check**: `/api/health/pool-status`

### Required Services
1. **MySQL Database** (Railway addon)
2. **Cloudflare R2** (receipt storage)
3. **Gmail API** (OAuth tokens in `gmail_tokens/`)

## Security Considerations

### Authentication
- Session-based login (`@login_required`)
- API key authentication (`X-Admin-Key` header)
- Google OAuth for Gmail access

### Data Protection
- All SQL uses parameterized queries (%s placeholders)
- File uploads validated by extension + magic bytes
- No hardcoded credentials (environment variables only)

### Rate Limiting
- OCR endpoints: cached to reduce API calls
- Gmail scanning: 4-hour intervals in production

## Maintenance

### Database
```bash
# Check connection pool status
curl /api/health/pool-status

# Reset connection pool
curl -X POST /api/health/pool-reset

# Keep-alive ping
curl -X POST /api/health/pool-keepalive
```

### Logs
- Structured logging via `logging_config.py`
- Request timing with `@log_timing` decorator
- Railway logs: `railway logs`

## Future Improvements

1. **Complete Blueprint Migration**: Move remaining routes from viewer_server.py
2. **Redis Caching**: Add Redis for session and data caching
3. **Background Workers**: Move OCR and Gmail scanning to Celery
4. **API Rate Limiting**: Add proper rate limiting middleware
5. **Unit Tests**: Expand test coverage

---

*Last Updated: December 2024*
*Version: 2025.12.04.v4*

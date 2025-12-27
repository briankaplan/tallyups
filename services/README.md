# Life OS Backend Services

Complete backend services for the Life OS receipt management system.

## Overview

This directory contains three critical backend services that power the Life OS receipt management system:

1. **R2 Storage Service** - Cloudflare R2 file storage
2. **Gmail Receipt Service** - Multi-account Gmail receipt extraction
3. **Receipt Matcher Service** - Intelligent fuzzy matching

## Services

### 1. R2 Storage Service (`r2_storage_service.py`)

Complete R2 storage service for receipt files using S3-compatible API.

**Features:**
- Upload receipts to R2 bucket
- Download/serve receipts by path
- List receipts with filtering
- Delete receipts
- Generate public URLs
- Handle deduplication via file hashing

**Requirements:**
```bash
pip install boto3 python-dotenv
```

**Environment Variables:**
```bash
CLOUDFLARE_ACCOUNT_ID=your_account_id
R2_ACCESS_KEY_ID=your_access_key
R2_SECRET_ACCESS_KEY=your_secret_key
R2_BUCKET_NAME=second-brain-receipts
R2_PUBLIC_URL=https://pub-....r2.dev
R2_CUSTOM_DOMAIN=  # Optional
```

**Usage:**
```python
from services.r2_storage_service import R2StorageService

# Initialize service
r2 = R2StorageService()

# Upload file
result = r2.upload_file(
    file_path='receipt.jpg',
    metadata={'merchant': 'Starbucks', 'amount': '5.00'}
)

# Download file
data = r2.download_file('receipts/2025-01-01_receipt.jpg')

# List files
files = r2.list_files(prefix='receipts/2025-01')

# Delete file
r2.delete_file('receipts/2025-01-01_receipt.jpg')

# Get public URL
url = r2.get_public_url('receipts/2025-01-01_receipt.jpg')
```

**Test:**
```bash
python services/r2_storage_service.py
```

---

### 2. Gmail Receipt Service (`gmail_receipt_service.py`)

Multi-account Gmail receipt extraction service with automatic data extraction.

**Features:**
- Connect to 3 Gmail accounts simultaneously
- Search for receipt emails using smart filters
- Extract merchant, amount, date, order number
- Save to SQLite database
- Download attachments
- Return structured receipt data

**Requirements:**
```bash
pip install google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client python-dotenv
```

**Gmail Accounts:**
- `brian@business.com` (Business business)
- `kaplan.brian@gmail.com` (Personal)
- `brian@secondary.com` (Secondary business)

**Setup:**

1. Create OAuth2 credentials in Google Cloud Console
2. Download credentials JSON for each account
3. Place credentials in `credentials/` directory:
   - `credentials/business_gmail.json`
   - `credentials/personal_gmail.json`
   - `credentials/sec_gmail.json`

4. First run will open browser for OAuth consent
5. Tokens will be saved in `credentials/token_*.json`

**Environment Variables:**
```bash
GMAIL_CREDENTIALS_BUSINESS=credentials/business_gmail.json
GMAIL_TOKEN_BUSINESS=credentials/token_business.json
GMAIL_CREDENTIALS_PERSONAL=credentials/personal_gmail.json
GMAIL_TOKEN_PERSONAL=credentials/token_personal.json
GMAIL_CREDENTIALS_MCR=credentials/sec_gmail.json
GMAIL_TOKEN_MCR=credentials/token_sec.json
```

**Usage:**
```python
from services.gmail_receipt_service import GmailReceiptService

# Initialize service
gmail = GmailReceiptService(db_path='receipts.db')

# Authenticate account
gmail.authenticate_account('brian@business.com')

# Search for receipts (last 30 days)
receipts = gmail.search_receipts(
    account_email='brian@business.com',
    days_back=30,
    max_results=100
)

# Save receipts to database
for receipt in receipts:
    receipt_id = gmail.save_receipt(receipt)

# Search all accounts and save
stats = gmail.search_and_save_receipts(
    account_email=None,  # All accounts
    days_back=30
)
```

**Database Schema:**
```sql
CREATE TABLE receipts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_account TEXT NOT NULL,
    gmail_message_id TEXT UNIQUE,
    email_subject TEXT,
    email_date TEXT,
    source TEXT DEFAULT 'gmail',
    merchant TEXT,
    amount REAL,
    transaction_date TEXT,
    order_number TEXT,
    business_type TEXT,
    r2_url TEXT,
    r2_key TEXT,
    file_hash TEXT,
    file_size INTEGER,
    total_pages INTEGER DEFAULT 1,
    processing_status TEXT DEFAULT 'pending',
    confidence_score REAL,
    extraction_metadata TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    processed_at TEXT
);
```

**Test:**
```bash
python services/gmail_receipt_service.py receipts.db
```

---

### 3. Receipt Matcher Service (`receipt_matcher_service.py`)

Intelligent fuzzy matching service for transactions and receipts.

**Features:**
- Load transactions from CSV
- Load receipts from SQLite/R2
- Fuzzy match by:
  - Merchant name (fuzz ratio > 80%)
  - Amount (+/- $1 tolerance)
  - Date (+/- 3 days)
- Calculate confidence score (0-100%)
- Auto-approve if confidence > 90%
- Return match suggestions for manual review
- Export results to CSV

**Requirements:**
```bash
pip install fuzzywuzzy python-Levenshtein pandas
```

**Matching Algorithm:**

1. **Merchant Matching (40% weight)**
   - Uses fuzzy token set ratio
   - Cleans merchant names (removes TST*, SQ*, etc.)
   - Threshold: 80% similarity minimum
   - Scores:
     - 100% match = 40 points
     - 95% match = 38 points
     - 90% match = 36 points
     - 80% match = 32 points

2. **Amount Matching (40% weight)**
   - Tolerance: +/- $1.00
   - Scores:
     - Exact match = 40 points
     - Within $0.01 = 38 points
     - Within $0.50 = 35 points
     - Proportional for larger differences

3. **Date Matching (20% weight)**
   - Tolerance: +/- 3 days
   - Scores:
     - Same day = 20 points
     - 1 day difference = 18 points
     - 2-3 days = 15 points
     - Proportional for larger differences

4. **Confidence Score:**
   - Total = Merchant + Amount + Date
   - Auto-approve if confidence >= 90%
   - Manual review if confidence < 90%

**Usage:**
```python
from services.receipt_matcher_service import ReceiptMatcherService

# Initialize service
matcher = ReceiptMatcherService(
    db_path='receipts.db',
    csv_path='transactions.csv',
    merchant_threshold=80.0,
    amount_tolerance=1.0,
    date_tolerance_days=3,
    auto_approve_threshold=90.0
)

# Load data
matcher.load_transactions_from_csv()
matcher.load_receipts_from_db()

# Match all transactions
results = matcher.match_all_transactions()

# Export matches
matcher.export_matches_to_csv(
    results['matches'],
    'matches_report.csv'
)

# Update original CSV with matches
matcher.update_csv_with_matches(
    results['matches'],
    'transactions_MATCHED.csv'
)

# Print statistics
matcher.print_statistics()
```

**Output:**
```
MATCHING STATISTICS
================================================================================
Total transactions: 250
Total receipts: 180
Total matches: 165
Auto-approved: 142
Manual review: 23
No match: 85
================================================================================
```

**Test:**
```bash
python services/receipt_matcher_service.py transactions.csv receipts.db
```

---

## Integration Example

Complete workflow using all three services:

```python
from services.r2_storage_service import R2StorageService
from services.gmail_receipt_service import GmailReceiptService
from services.receipt_matcher_service import ReceiptMatcherService

# 1. Initialize services
r2 = R2StorageService()
gmail = GmailReceiptService(db_path='receipts.db')
matcher = ReceiptMatcherService(
    db_path='receipts.db',
    csv_path='Chase_Activity.csv'
)

# 2. Extract receipts from Gmail
print("Extracting receipts from Gmail...")
stats = gmail.search_and_save_receipts(days_back=30)
print(f"Found {stats['total_saved']} new receipts")

# 3. Upload receipt attachments to R2
# (This would be integrated with receipt_processor_service.py)

# 4. Match transactions to receipts
print("\nMatching transactions to receipts...")
matcher.load_transactions_from_csv()
matcher.load_receipts_from_db()
results = matcher.match_all_transactions()

# 5. Export results
matcher.export_matches_to_csv(
    results['matches'],
    'match_report.csv'
)
matcher.update_csv_with_matches(
    results['matches'],
    'Chase_Activity_MATCHED.csv'
)

# 6. Print statistics
matcher.print_statistics()
```

---

## Installation

### Quick Install

```bash
# Install all required packages
pip install boto3 python-dotenv google-auth google-auth-oauthlib google-auth-httplib2 google-api-python-client fuzzywuzzy python-Levenshtein pandas

# Or use requirements.txt
pip install -r requirements.txt
```

### requirements.txt

```
boto3>=1.28.0
python-dotenv>=1.0.0
google-auth>=2.23.0
google-auth-oauthlib>=1.1.0
google-auth-httplib2>=0.1.1
google-api-python-client>=2.100.0
fuzzywuzzy>=0.18.0
python-Levenshtein>=0.21.0
pandas>=2.0.0
```

---

## Configuration

### Environment Variables

Create a `.env` file in the project root:

```bash
# Cloudflare R2 Configuration
CLOUDFLARE_ACCOUNT_ID=33950783df90825d4b885322a8ea2f2f
R2_ACCESS_KEY_ID=38c091312371e3c552fdf21b31096fc3
R2_SECRET_ACCESS_KEY=bdd5443df55080d8f173d89071c3c7397b27dde92a8cf0095ff6808b9d347bb1
R2_BUCKET_NAME=second-brain-receipts
R2_PUBLIC_URL=https://pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev
R2_CUSTOM_DOMAIN=

# Gmail OAuth Credentials
GMAIL_CREDENTIALS_BUSINESS=credentials/business_gmail.json
GMAIL_TOKEN_BUSINESS=credentials/token_business.json
GMAIL_CREDENTIALS_PERSONAL=credentials/personal_gmail.json
GMAIL_TOKEN_PERSONAL=credentials/token_personal.json
GMAIL_CREDENTIALS_MCR=credentials/sec_gmail.json
GMAIL_TOKEN_MCR=credentials/token_sec.json
```

### Directory Structure

```
/Users/briankaplan/Desktop/Task/
├── services/
│   ├── r2_storage_service.py
│   ├── gmail_receipt_service.py
│   ├── receipt_matcher_service.py
│   ├── receipt_processor_service.py
│   └── ... (other services)
├── credentials/
│   ├── business_gmail.json
│   ├── token_business.json
│   ├── personal_gmail.json
│   ├── token_personal.json
│   ├── sec_gmail.json
│   └── token_sec.json
├── receipt-system/
│   └── data/
│       └── Chase_Activity_MATCHED.csv
├── receipts.db
└── .env
```

---

## Troubleshooting

### R2 Storage Issues

**Error: "Failed to initialize R2 client"**
- Check environment variables are set correctly
- Verify R2 credentials are valid
- Test connectivity to R2 endpoint

**Error: "R2 upload error"**
- Check bucket name is correct
- Verify file permissions
- Check file size limits

### Gmail Issues

**Error: "Gmail API not available"**
```bash
pip install google-auth google-auth-oauthlib google-api-python-client
```

**Error: "Credentials file not found"**
- Download OAuth2 credentials from Google Cloud Console
- Place in `credentials/` directory
- Check file paths in `.env`

**Error: "OAuth flow failed"**
- Enable Gmail API in Google Cloud Console
- Add test users if app is in testing mode
- Check OAuth consent screen configuration

### Matching Issues

**Error: "fuzzywuzzy not available"**
```bash
pip install fuzzywuzzy python-Levenshtein
```

**Low match rates:**
- Adjust `merchant_threshold` (default: 80.0)
- Increase `amount_tolerance` (default: 1.0)
- Increase `date_tolerance_days` (default: 3)

**Too many auto-approvals:**
- Increase `auto_approve_threshold` (default: 90.0)

---

## API Reference

### R2StorageService

```python
class R2StorageService:
    def __init__(self, account_id=None, access_key_id=None, secret_access_key=None, bucket_name=None, public_url=None)
    def upload_file(self, file_path, r2_key=None, metadata=None, public=True) -> Dict
    def download_file(self, r2_key, local_path=None) -> bytes
    def delete_file(self, r2_key) -> bool
    def list_files(self, prefix='', max_files=1000) -> List[Dict]
    def get_file_metadata(self, r2_key) -> Dict
    def file_exists(self, r2_key) -> bool
    def get_public_url(self, r2_key, use_custom_domain=True) -> str
```

### GmailReceiptService

```python
class GmailReceiptService:
    def __init__(self, db_path='receipts.db')
    def authenticate_account(self, account_email) -> object
    def search_receipts(self, account_email, days_back=30, max_results=100) -> List[Dict]
    def save_receipt(self, receipt) -> int
    def download_attachment(self, account, message_id, attachment_id, filename) -> bytes
    def search_and_save_receipts(self, account_email=None, days_back=30, max_results=100) -> Dict
```

### ReceiptMatcherService

```python
class ReceiptMatcherService:
    def __init__(self, db_path='receipts.db', csv_path=None, merchant_threshold=80.0, amount_tolerance=1.0, date_tolerance_days=3, auto_approve_threshold=90.0)
    def load_transactions_from_csv(self, csv_path=None) -> List[Transaction]
    def load_receipts_from_db(self) -> List[Receipt]
    def match_transaction_to_receipts(self, transaction) -> List[Match]
    def match_all_transactions(self) -> Dict
    def export_matches_to_csv(self, matches, output_path) -> bool
    def update_csv_with_matches(self, matches, output_path=None) -> bool
    def print_statistics(self)
```

---

## Testing

Run tests for each service:

```bash
# Test R2 Storage
python services/r2_storage_service.py

# Test Gmail Receipt Service
python services/gmail_receipt_service.py receipts.db

# Test Receipt Matcher
python services/receipt_matcher_service.py Chase_Activity.csv receipts.db
```

---

## Production Deployment

### Environment Setup

1. Set environment variables on Railway/production server
2. Upload Gmail OAuth credentials to secure storage
3. Initialize database with schema
4. Test R2 connectivity
5. Run initial Gmail sync
6. Schedule periodic syncs (cron/scheduler)

### Monitoring

- Monitor R2 storage usage
- Track Gmail API quota usage
- Log matching statistics
- Alert on low confidence matches
- Track processing errors

---

## License

MIT License

---

## Support

For issues or questions:
- Email: brian@business.com
- Database: receipts.db
- Logs: Check service output for errors

---

## Version History

- **v1.0.0** (2025-11-02)
  - Initial release
  - R2 Storage Service
  - Gmail Receipt Service
  - Receipt Matcher Service
  - Complete documentation

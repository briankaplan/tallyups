# Life OS Backend Services - Deployment Guide

Complete deployment guide for production use.

## Quick Start

### 1. Installation

```bash
cd /Users/briankaplan/Desktop/Task/services

# Install all dependencies
pip install -r requirements.txt

# Or install individually
pip install boto3 python-dotenv google-auth google-auth-oauthlib google-api-python-client fuzzywuzzy python-Levenshtein pandas
```

### 2. Environment Configuration

Create `.env` file in `/Users/briankaplan/Desktop/Task/`:

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

### 3. Verify Installation

```bash
# Run test suite
python services/test_services.py

# Expected output:
# ✅ All services imported successfully!
# ✅ All basic functionality tests passed!
```

### 4. Run Integration Example

```bash
python services/integration_example.py
```

---

## Gmail OAuth Setup

### Step 1: Google Cloud Console Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com)
2. Create a new project (or use existing)
3. Enable Gmail API:
   - APIs & Services > Library
   - Search for "Gmail API"
   - Click "Enable"

### Step 2: Create OAuth Credentials

1. APIs & Services > Credentials
2. Click "Create Credentials" > "OAuth client ID"
3. Application type: "Desktop app"
4. Name: "Life OS Receipt Service"
5. Download JSON credentials

### Step 3: Configure Credentials

For each Gmail account (3 total):

```bash
# Create credentials directory
mkdir -p credentials

# Copy downloaded credentials
cp ~/Downloads/client_secret_*.json credentials/business_gmail.json
cp ~/Downloads/client_secret_*.json credentials/personal_gmail.json
cp ~/Downloads/client_secret_*.json credentials/sec_gmail.json
```

### Step 4: Authenticate Accounts

```bash
# Authenticate each account (one at a time)
python services/gmail_receipt_service.py receipts.db

# Follow prompts to:
# 1. Select account
# 2. Browser will open for OAuth consent
# 3. Grant access to Gmail
# 4. Token will be saved automatically
```

**Important:** You must authenticate ALL 3 accounts:
- brian@business.com
- kaplan.brian@gmail.com
- brian@secondary.com

---

## Production Workflow

### Daily/Weekly Receipt Processing

```python
#!/usr/bin/env python3
"""
Automated receipt processing workflow
Run daily or weekly to process new receipts
"""

from services.gmail_receipt_service import GmailReceiptService
from services.receipt_matcher_service import ReceiptMatcherService

# 1. Extract receipts from Gmail
gmail = GmailReceiptService(db_path='receipts.db')

# Search last 7 days
stats = gmail.search_and_save_receipts(
    account_email=None,  # All accounts
    days_back=7,
    max_results=100
)

print(f"Found {stats['total_saved']} new receipts")

# 2. Match transactions
matcher = ReceiptMatcherService(
    db_path='receipts.db',
    csv_path='transactions.csv'
)

matcher.load_transactions_from_csv()
matcher.load_receipts_from_db()
results = matcher.match_all_transactions()

# 3. Export matches
matcher.export_matches_to_csv(
    results['matches'],
    'weekly_matches.csv'
)

matcher.update_csv_with_matches(
    results['matches'],
    'transactions_MATCHED.csv'
)

print(f"Matched {len(results['matches'])} transactions")
print(f"Auto-approved: {len(results['auto_approved'])}")
print(f"Manual review: {len(results['manual_review'])}")
```

### Schedule with Cron (macOS/Linux)

```bash
# Edit crontab
crontab -e

# Run daily at 9 AM
0 9 * * * cd /Users/briankaplan/Desktop/Task && python3 services/automated_workflow.py >> logs/receipts.log 2>&1

# Run weekly on Monday at 8 AM
0 8 * * 1 cd /Users/briankaplan/Desktop/Task && python3 services/weekly_report.py >> logs/weekly.log 2>&1
```

---

## Troubleshooting

### R2 Storage Issues

**Error: "Failed to initialize R2 client"**

```bash
# Check environment variables
python3 -c "import os; from dotenv import load_dotenv; load_dotenv(); print('Account ID:', os.getenv('CLOUDFLARE_ACCOUNT_ID'))"

# Test R2 connection
python3 services/r2_storage_service.py
```

**Error: "R2 upload error: SignatureDoesNotMatch"**

- Verify R2 access key and secret are correct
- Check that credentials haven't expired
- Regenerate R2 credentials if needed

### Gmail Issues

**Error: "Gmail API not available"**

```bash
# Install Google API libraries
pip install google-auth google-auth-oauthlib google-api-python-client
```

**Error: "Credentials file not found"**

```bash
# Check credentials exist
ls -la credentials/
# Should show:
# business_gmail.json
# personal_gmail.json
# sec_gmail.json
```

**Error: "OAuth flow failed"**

1. Check Gmail API is enabled in Google Cloud Console
2. Verify OAuth consent screen is configured
3. Add your email to test users if app is in testing mode
4. Try deleting token file and re-authenticating:

```bash
rm credentials/token_business.json
python services/gmail_receipt_service.py receipts.db
```

**Error: "Daily limit exceeded"**

- Gmail API has quota limits
- Default: 1 billion quota units/day
- Reading emails: ~5-10 units each
- Reduce `max_results` or `days_back` if hitting limits

### Matching Issues

**Low match rates (< 50%)**

```python
# Adjust matching thresholds
matcher = ReceiptMatcherService(
    merchant_threshold=70.0,  # Lower from 80
    amount_tolerance=2.0,     # Increase from 1.0
    date_tolerance_days=7     # Increase from 3
)
```

**Too many false positives**

```python
# Increase thresholds
matcher = ReceiptMatcherService(
    merchant_threshold=90.0,      # Higher merchant similarity
    auto_approve_threshold=95.0   # Stricter auto-approval
)
```

**Missing matches**

1. Check merchant name cleaning:
```python
matcher = ReceiptMatcherService(db_path='receipts.db')
cleaned = matcher._clean_merchant_name('TST*STARBUCKS #12345')
print(cleaned)  # Should be: STARBUCKS 12345
```

2. Verify date formats in CSV:
```python
transactions = matcher.load_transactions_from_csv('transactions.csv')
print(transactions[0].date)  # Should be MM/DD/YYYY or YYYY-MM-DD
```

---

## Performance Optimization

### Database Indexing

The Gmail service automatically creates indices, but you can add more:

```sql
-- Add custom indices for faster queries
CREATE INDEX IF NOT EXISTS idx_receipts_amount ON receipts(amount);
CREATE INDEX IF NOT EXISTS idx_receipts_business ON receipts(business_type);
CREATE INDEX IF NOT EXISTS idx_receipts_status ON receipts(processing_status);
```

### Batch Processing

For large datasets (1000+ transactions):

```python
# Process in batches
matcher = ReceiptMatcherService(db_path='receipts.db')

# Load all data once
matcher.load_transactions_from_csv()
matcher.load_receipts_from_db()

# Process in chunks
chunk_size = 100
for i in range(0, len(matcher.transactions), chunk_size):
    chunk = matcher.transactions[i:i + chunk_size]
    # Process chunk...
```

### Caching

```python
# Cache fuzzy match results
from functools import lru_cache

@lru_cache(maxsize=1000)
def cached_fuzzy_match(str1, str2):
    return fuzz.token_set_ratio(str1, str2)
```

---

## Monitoring & Logging

### Setup Logging

```python
import logging

# Configure logging
logging.basicConfig(
    filename='logs/receipts.log',
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

logger = logging.getLogger(__name__)

# Log to file and console
console_handler = logging.StreamHandler()
logger.addHandler(console_handler)
```

### Monitor Service Health

```bash
# Create monitoring script
cat > monitor_services.sh << 'EOF'
#!/bin/bash

echo "=== Life OS Services Health Check ==="
echo ""

# Test R2 connection
echo "Testing R2 Storage..."
python3 -c "from services.r2_storage_service import R2StorageService; r2 = R2StorageService(); files = r2.list_files(max_files=1); print('✅ R2 OK')"

# Test database
echo "Testing Database..."
python3 -c "import sqlite3; conn = sqlite3.connect('receipts.db'); cur = conn.cursor(); cur.execute('SELECT COUNT(*) FROM receipts'); print(f'✅ Database OK ({cur.fetchone()[0]} receipts)')"

# Test Gmail (if authenticated)
echo "Testing Gmail..."
python3 -c "from services.gmail_receipt_service import GmailReceiptService; gmail = GmailReceiptService('receipts.db'); print('✅ Gmail OK')"

echo ""
echo "=== Health Check Complete ==="
EOF

chmod +x monitor_services.sh
```

### Dashboard Metrics

Track these metrics:
- Total receipts in database
- Total matched transactions
- Auto-approval rate (%)
- Average confidence score
- Unmatched transactions count
- R2 storage usage (GB)
- Gmail API quota usage

---

## Security Best Practices

### 1. Protect Credentials

```bash
# Never commit credentials to git
echo "credentials/" >> .gitignore
echo ".env" >> .gitignore
echo "*.db" >> .gitignore

# Set proper permissions
chmod 600 credentials/*.json
chmod 600 .env
```

### 2. Rotate R2 Keys

```bash
# Generate new R2 access keys quarterly
# Update .env file
# Test before revoking old keys
```

### 3. Monitor OAuth Tokens

```bash
# Check token expiration
python3 -c "
from google.oauth2.credentials import Credentials
import json

with open('credentials/token_business.json') as f:
    token_data = json.load(f)
    creds = Credentials.from_authorized_user_info(token_data)
    print(f'Valid: {creds.valid}')
    print(f'Expired: {creds.expired}')
    print(f'Has refresh: {bool(creds.refresh_token)}')
"
```

### 4. Backup Database

```bash
# Daily backup
cp receipts.db backups/receipts_$(date +%Y%m%d).db

# Cleanup old backups (keep last 30 days)
find backups/ -name "receipts_*.db" -mtime +30 -delete
```

---

## API Integration (Railway/Production)

### Environment Variables on Railway

```bash
# Set in Railway dashboard or CLI
railway variables set CLOUDFLARE_ACCOUNT_ID=33950783df90825d4b885322a8ea2f2f
railway variables set R2_ACCESS_KEY_ID=38c091312371e3c552fdf21b31096fc3
railway variables set R2_SECRET_ACCESS_KEY=bdd5443df55080d8f173d89071c3c7397b27dde92a8cf0095ff6808b9d347bb1
railway variables set R2_BUCKET_NAME=second-brain-receipts
railway variables set R2_PUBLIC_URL=https://pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev
```

### Flask/FastAPI Integration

```python
from flask import Flask, jsonify
from services.r2_storage_service import R2StorageService
from services.gmail_receipt_service import GmailReceiptService
from services.receipt_matcher_service import ReceiptMatcherService

app = Flask(__name__)

# Initialize services
r2 = R2StorageService()
gmail = GmailReceiptService('receipts.db')
matcher = ReceiptMatcherService('receipts.db')

@app.route('/api/receipts/list')
def list_receipts():
    """List all receipts"""
    files = r2.list_files(prefix='receipts/', max_files=100)
    return jsonify({
        'success': True,
        'count': len(files),
        'receipts': files
    })

@app.route('/api/receipts/extract')
def extract_receipts():
    """Extract receipts from Gmail"""
    stats = gmail.search_and_save_receipts(days_back=7)
    return jsonify({
        'success': True,
        'stats': stats
    })

@app.route('/api/receipts/match')
def match_receipts():
    """Match transactions to receipts"""
    matcher.load_transactions_from_csv('transactions.csv')
    matcher.load_receipts_from_db()
    results = matcher.match_all_transactions()

    return jsonify({
        'success': True,
        'total_matches': len(results['matches']),
        'auto_approved': len(results['auto_approved']),
        'manual_review': len(results['manual_review']),
        'no_match': len(results['no_match'])
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)
```

---

## Support & Maintenance

### Regular Maintenance Tasks

**Daily:**
- Monitor service health
- Check error logs
- Review unmatched transactions

**Weekly:**
- Run Gmail extraction
- Match new transactions
- Export weekly reports
- Review manual matches

**Monthly:**
- Backup database
- Review matching accuracy
- Update merchant name mappings
- Clean up old receipts

**Quarterly:**
- Rotate R2 access keys
- Review Gmail OAuth tokens
- Update dependencies
- Optimize database

### Getting Help

**Service Issues:**
1. Check logs: `tail -f logs/receipts.log`
2. Run test suite: `python services/test_services.py`
3. Check environment: `python -c "from dotenv import load_dotenv; load_dotenv(); import os; print(os.environ)"`

**Data Issues:**
1. Verify database: `sqlite3 receipts.db ".schema"`
2. Check receipts: `sqlite3 receipts.db "SELECT COUNT(*) FROM receipts"`
3. Inspect sample: `sqlite3 receipts.db "SELECT * FROM receipts LIMIT 5"`

**Matching Issues:**
1. Review thresholds in code
2. Check merchant name cleaning
3. Verify date/amount formats
4. Test with single transaction

---

## Next Steps

1. ✅ Install dependencies
2. ✅ Configure environment variables
3. ✅ Run test suite
4. ⏳ Setup Gmail OAuth
5. ⏳ Extract receipts from Gmail
6. ⏳ Upload receipt attachments to R2
7. ⏳ Match transactions to receipts
8. ⏳ Generate expense reports

---

## Resources

- **Documentation:** `services/README.md`
- **Test Suite:** `services/test_services.py`
- **Integration Example:** `services/integration_example.py`
- **Cloudflare R2 Docs:** https://developers.cloudflare.com/r2/
- **Gmail API Docs:** https://developers.google.com/gmail/api
- **FuzzyWuzzy Docs:** https://github.com/seatgeek/fuzzywuzzy

---

Last Updated: 2025-11-02
Version: 1.0.0

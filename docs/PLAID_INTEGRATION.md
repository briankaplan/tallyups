# Plaid Bank Integration Guide

## Overview

Tallyups integrates with Plaid to provide automatic bank account and credit card transaction syncing. This allows you to:

- **Connect multiple bank accounts and credit cards** from any supported institution
- **Automatically sync transactions** every hour (or manually)
- **Assign accounts to business types** (Personal, Down Home, Music City Rodeo, Em.Co)
- **Same card can belong to multiple businesses** - just select all that apply
- **Never lose data** - transactions are synced incrementally, never deleted

## Quick Start

### 1. Set Up Your Environment Variables

Add to your `.env` file (Railway automatically uses these):

```bash
# Your Plaid credentials (from dashboard.plaid.com)
PLAID_CLIENT_ID=672f9218fda72b001a353656
PLAID_SECRET=877c90bec851a46153fe477977de48    # Production secret
PLAID_ENV=production

# Optional: For real-time webhooks
PLAID_WEBHOOK_URL=https://your-app.railway.app/api/plaid/webhook
```

### 2. Run the Database Migration

```bash
# Using the MySQL client
mysql -h your-host -u root -p your_database < migrations/003_plaid_integration.sql

# Or connect to Railway MySQL and run the migration
railway run python -c "
from db_mysql import get_mysql_db
db = get_mysql_db()
with open('migrations/003_plaid_integration.sql') as f:
    conn = db.get_connection()
    cursor = conn.cursor()
    for statement in f.read().split(';'):
        if statement.strip():
            cursor.execute(statement)
    conn.commit()
    db.return_connection(conn)
print('Migration complete!')
"
```

### 3. Install the Plaid Python SDK

```bash
pip install plaid-python
```

### 4. Connect Your Bank Accounts

1. Go to **Settings** > **Bank Accounts** in Tallyups
2. Click **Connect Bank Account**
3. Select your bank and log in securely through Plaid
4. Choose which accounts to sync
5. Assign each account to business types (you can select multiple!)

---

## Architecture

### Database Schema

The integration creates these tables:

| Table | Purpose |
|-------|---------|
| `plaid_items` | Stores bank connections (access tokens, institution info) |
| `plaid_accounts` | Individual accounts within each connection |
| `plaid_transactions` | Synced transactions (staging table) |
| `plaid_webhooks` | Audit log of webhook events |
| `plaid_sync_history` | Sync operation history and statistics |
| `plaid_link_tokens` | Temporary tokens for the Link flow |

### Files Created

```
services/
  plaid_service.py      # Core Plaid service (all API operations)
  plaid_routes.py       # REST API endpoints
  plaid_sync_worker.py  # Background sync worker

static/js/
  plaid-link.js         # Frontend Plaid Link integration

migrations/
  003_plaid_integration.sql  # Database schema

bank_accounts.html      # Settings page for managing accounts
```

---

## API Endpoints

All endpoints require authentication (except webhook).

### Link Token Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plaid/link-token` | POST | Create a Plaid Link token |
| `/api/plaid/exchange-token` | POST | Exchange public token for access |

### Account Management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plaid/items` | GET | List all linked Items |
| `/api/plaid/items/<id>` | GET | Get Item details |
| `/api/plaid/items/<id>` | DELETE | Remove (disconnect) Item |
| `/api/plaid/accounts` | GET | List all accounts |
| `/api/plaid/accounts/<id>` | PUT | Update account settings |

### Transactions

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plaid/transactions` | GET | List transactions |
| `/api/plaid/transactions/summary` | GET | Get transaction statistics |
| `/api/plaid/sync` | POST | Trigger manual sync |
| `/api/plaid/sync/status` | GET | Get sync status |

### System

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/plaid/status` | GET | Check Plaid configuration status |
| `/api/plaid/webhook` | POST | Receive Plaid webhooks |

---

## Usage Examples

### Python - Sync Transactions

```python
from services.plaid_service import get_plaid_service

plaid = get_plaid_service()

# Sync all Items
for item in plaid.get_items():
    result = plaid.sync_transactions(item.item_id)
    print(f"Synced {item.institution_name}: +{result.added} transactions")
```

### Python - Get Accounts

```python
from services.plaid_service import get_plaid_service

plaid = get_plaid_service()

for account in plaid.get_accounts():
    print(f"{account.name} (****{account.mask}): ${account.balance_current}")
```

### JavaScript - Connect Bank

```javascript
// In browser
PlaidLink.connect();

// Listen for success
window.addEventListener('plaid:connected', (e) => {
    console.log('Connected:', e.detail.item.institution_name);
    console.log('Accounts:', e.detail.accounts);
});
```

### JavaScript - Sync Transactions

```javascript
// Sync all accounts
await PlaidLink.sync();

// Sync specific Item
await PlaidLink.sync('item-xxx');
```

---

## Background Sync Worker

The sync worker runs automatically to keep transactions up to date.

### Run Manually (Once)

```bash
python services/plaid_sync_worker.py --once
```

### Run Continuously

```bash
python services/plaid_sync_worker.py
```

### Run as Daemon

```bash
python services/plaid_sync_worker.py --daemon
```

### Configuration

| Environment Variable | Default | Description |
|---------------------|---------|-------------|
| `PLAID_SYNC_INTERVAL` | 3600 | Sync interval in seconds (1 hour) |
| `PLAID_SYNC_CONCURRENT` | 3 | Max concurrent syncs |
| `PLAID_SYNC_ENABLED` | true | Enable/disable automatic sync |
| `PLAID_MIN_SYNC_GAP` | 300 | Minimum time between syncs (5 min) |

---

## Multi-Business Support

### How It Works

Each account can be assigned to multiple business types:

- **Personal** - Personal expenses
- **Down Home** - Down Home Productions
- **MCR** - Music City Rodeo
- **Em.Co** - Em.Co expenses

### Setting Business Types

1. Go to Settings > Bank Accounts
2. For each account, click the business type tags to toggle them
3. Selected business types are highlighted
4. Same card can have multiple business types selected

### How Transactions Use Business Types

When transactions sync, they inherit the default business type from their account. You can later re-classify individual transactions in the main reconciliation view.

---

## Webhooks (Optional)

Plaid can send real-time updates when new transactions are available.

### Setup

1. Set your webhook URL in environment:
   ```bash
   PLAID_WEBHOOK_URL=https://your-app.railway.app/api/plaid/webhook
   ```

2. Configure webhook secret (optional, for security):
   ```bash
   PLAID_WEBHOOK_SECRET=your_secret_key
   ```

### Supported Webhooks

| Type | Code | Action |
|------|------|--------|
| TRANSACTIONS | SYNC_UPDATES_AVAILABLE | Triggers sync |
| TRANSACTIONS | DEFAULT_UPDATE | Triggers sync |
| ITEM | ERROR | Marks Item as needing re-auth |
| ITEM | PENDING_EXPIRATION | Logs warning |

---

## Security Notes

1. **Access tokens are NEVER exposed to clients** - Only stored server-side
2. **All API calls use HTTPS** - Plaid requires secure connections
3. **Webhook signatures are verified** - Prevents spoofing
4. **Sessions are required** - All endpoints (except webhook) need authentication

---

## Troubleshooting

### "Plaid not configured"

Check that these environment variables are set:
- `PLAID_CLIENT_ID`
- `PLAID_SECRET`

### "ITEM_LOGIN_REQUIRED"

The user needs to re-authenticate with their bank:
1. Go to Settings > Bank Accounts
2. Click "Re-authenticate" on the affected account
3. Complete the Plaid Link flow

### "Sync failed"

Check the sync history:
```python
from db_mysql import get_mysql_db
db = get_mysql_db()
conn = db.get_connection()
cursor = conn.cursor()
cursor.execute("""
    SELECT * FROM plaid_sync_history
    WHERE status = 'failed'
    ORDER BY started_at DESC
    LIMIT 10
""")
for row in cursor.fetchall():
    print(row)
```

### Missing Transactions

Plaid's cursor-based sync ensures you never miss transactions. If transactions seem missing:

1. Trigger a manual sync
2. Check if the account has `sync_enabled = true`
3. Check if the transaction is marked `pending = true`

---

## Your Credentials

You have been approved for Plaid Production access:

```
Client ID:          672f9218fda72b001a353656
Production Secret:  877c90bec851a46153fe477977de48
Sandbox Secret:     9cddcd15c6725cdfe1a10abbb65665
```

Use **Production** credentials for real bank data.
Use **Sandbox** credentials for testing with fake data.

---

## Support

If you encounter issues:

1. Check the logs: `railway logs`
2. Review sync history in the database
3. Ensure Plaid SDK is installed: `pip install plaid-python`
4. Verify environment variables are set correctly

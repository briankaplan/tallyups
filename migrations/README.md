# ReceiptAI Database Migrations

This directory contains SQL migration files for the MySQL database schema.

## Migration Files

| File | Description |
|------|-------------|
| `001_initial_schema.sql` | Initial database schema with all tables |
| `002_add_indexes.sql` | Performance indexes for common queries |

## Running Migrations

### Via Railway
```bash
# Connect to MySQL
railway connect mysql

# Run migration
source /path/to/migrations/001_initial_schema.sql
```

### Via MySQL CLI
```bash
# Get connection string from Railway
export MYSQL_URL=$(railway variables --json | jq -r '.MYSQL_URL')

# Parse and connect
mysql -h $DB_HOST -P $DB_PORT -u $DB_USER -p$DB_PASS $DB_NAME < migrations/001_initial_schema.sql
```

### Via Python Script
```bash
python scripts/db/run_migration.py migrations/001_initial_schema.sql
```

## Migration Best Practices

1. **Always backup first**
   ```bash
   ./scripts/backup-database.sh pre-migration
   ```

2. **Test on development first**
   - Apply migration to development environment
   - Verify application still works
   - Then apply to production

3. **Use IF NOT EXISTS**
   - All CREATE statements should use `IF NOT EXISTS`
   - This makes migrations idempotent

4. **Never modify existing migrations**
   - Create a new migration file for changes
   - Keep migration history intact

5. **Include rollback comments**
   - Document how to undo each change
   - Example: `-- ROLLBACK: DROP INDEX idx_name`

## Table Overview

### Core Tables
- **transactions** - Financial transactions from Chase exports
- **incoming_receipts** - Receipts from Gmail, scans, etc.
- **merchants** - Merchant information for categorization
- **contacts** - People/business associations

### Supporting Tables
- **expense_reports** - Generated expense reports
- **ocr_cache** - Cached OCR results
- **audit_log** - Change tracking for compliance

## Schema Diagram

```
transactions (1) <----> (N) incoming_receipts
     |
     v
merchants (N) <----> (1) transactions (via merchant name)
     |
     v
contacts (N) <----> (N) merchants (via business association)
```

## Common Queries

### Check table sizes
```sql
SELECT
    table_name,
    table_rows,
    ROUND(data_length / 1024 / 1024, 2) AS data_mb,
    ROUND(index_length / 1024 / 1024, 2) AS index_mb
FROM information_schema.tables
WHERE table_schema = DATABASE()
ORDER BY data_length DESC;
```

### Check index usage
```sql
SELECT
    table_name,
    index_name,
    seq_in_index,
    column_name
FROM information_schema.statistics
WHERE table_schema = DATABASE()
ORDER BY table_name, index_name, seq_in_index;
```

### Find missing indexes
```sql
-- Queries without proper indexes will show up here
EXPLAIN SELECT * FROM transactions WHERE chase_date = '2025-01-15';
```

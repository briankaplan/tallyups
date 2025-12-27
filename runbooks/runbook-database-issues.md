# Runbook: Database Issues

## High Connection Pool Usage

### Symptoms
- `Pool exhausted` errors in logs
- Slow query responses (>5s)
- Health check shows high `checkedout` count
- 500 errors on API endpoints

### Investigation

1. **Check pool status:**
   ```bash
   curl -s https://tallyups.com/api/health/pool-status | jq
   ```

   Expected healthy state:
   ```json
   {
     "pool_size": 20,
     "available": 15,
     "in_use": 5,
     "overflow_count": 0,
     "utilization_percent": 25.0
   }
   ```

2. **Check for long-running queries:**
   ```sql
   -- Connect via Railway
   railway connect mysql

   -- Find long queries
   SHOW PROCESSLIST;

   -- Find queries over 30 seconds
   SELECT * FROM information_schema.processlist
   WHERE time > 30 AND command != 'Sleep';
   ```

3. **Check recent deployments:**
   ```bash
   git log --oneline -10
   railway logs -e production --limit 100 | grep -i "error\|exception"
   ```

### Resolution

**If temporary spike:**
1. Wait 2-3 minutes for connections to return
2. Monitor pool status until utilization < 50%

**If sustained high usage:**
1. Increase pool size (temporary):
   ```bash
   railway variables set DB_POOL_SIZE=30 -e production
   ```

2. Identify and fix inefficient code:
   - Look for missing `with` context managers
   - Check for loops that open connections

**If connection leak:**
1. Reset the pool:
   ```bash
   curl -X POST https://tallyups.com/api/health/pool-reset
   ```

2. If persists, restart the service:
   ```bash
   railway redeploy -e production
   ```

### Prevention

- Always use context managers for connections:
  ```python
  with get_pooled_connection() as conn:
      cursor = conn.cursor()
      # ... use cursor
  # Connection automatically returned
  ```

- Set query timeouts
- Add connection monitoring alerts

---

## Database Connection Failures

### Symptoms
- `Can't connect to MySQL server` errors
- Health check shows `database: unhealthy`
- All API endpoints returning 500

### Investigation

1. **Check database is running:**
   ```bash
   # Via Railway dashboard - check MySQL service status
   # Or via API:
   curl -s https://tallyups.com/health | jq '.services.database'
   ```

2. **Test direct connection:**
   ```bash
   railway connect mysql
   # If this fails, database is down
   ```

3. **Check Railway MySQL service:**
   - Go to Railway dashboard
   - Check MySQL service logs
   - Check if service is in "Crashed" state

### Resolution

**If Railway MySQL is down:**
1. Check Railway status page: https://status.railway.app
2. Wait for Railway to restore service
3. If prolonged, contact Railway support

**If network issue:**
1. Check if web service can reach MySQL:
   ```bash
   railway logs -e production | grep -i "mysql\|database"
   ```

2. Verify MYSQL_URL is correct:
   ```bash
   railway variables -e production | grep MYSQL_URL
   ```

**If credentials changed:**
1. Get new credentials from Railway MySQL service
2. Update MYSQL_URL variable
3. Redeploy

### Recovery Verification

```bash
# Check health
curl -s https://tallyups.com/health | jq

# Verify API works
curl -s https://tallyups.com/api/transactions?limit=1
```

---

## Slow Query Performance

### Symptoms
- Dashboard load time > 3 seconds
- Specific endpoints timing out
- High CPU on MySQL service

### Investigation

1. **Identify slow endpoints:**
   ```bash
   railway logs -e production | grep "duration_ms" | sort -t: -k2 -rn | head -20
   ```

2. **Find slow queries in MySQL:**
   ```sql
   -- Enable slow query log temporarily
   SET GLOBAL slow_query_log = 'ON';
   SET GLOBAL long_query_time = 1;

   -- Check slow query log
   SHOW VARIABLES LIKE 'slow_query%';
   ```

3. **Check missing indexes:**
   ```sql
   -- For transactions table
   EXPLAIN SELECT * FROM transactions WHERE chase_date = '2025-01-15';
   EXPLAIN SELECT * FROM transactions WHERE business_type = 'business';
   ```

### Resolution

**Add missing indexes:**
```sql
-- Common indexes that help
CREATE INDEX idx_transactions_date ON transactions(chase_date);
CREATE INDEX idx_transactions_business_type ON transactions(business_type);
CREATE INDEX idx_transactions_review_status ON transactions(review_status);
```

**Optimize queries:**
- Add LIMIT clauses
- Use specific column selection instead of SELECT *
- Add pagination for large result sets

**If query can't be optimized:**
- Consider caching results (Redis)
- Run expensive queries async
- Pre-compute aggregations

---

## Data Integrity Issues

### Symptoms
- Duplicate transactions appearing
- Missing receipt associations
- Incorrect business_type values

### Investigation

1. **Check for duplicates:**
   ```sql
   SELECT chase_date, chase_description, chase_amount, COUNT(*) as cnt
   FROM transactions
   GROUP BY chase_date, chase_description, chase_amount
   HAVING cnt > 1;
   ```

2. **Check orphaned receipts:**
   ```sql
   SELECT COUNT(*) FROM incoming_receipts
   WHERE matched_transaction_id IS NOT NULL
   AND matched_transaction_id NOT IN (SELECT _index FROM transactions);
   ```

### Resolution

**Remove duplicates:**
```sql
-- Keep lowest _index, delete others
DELETE t1 FROM transactions t1
INNER JOIN transactions t2
WHERE t1._index > t2._index
AND t1.chase_date = t2.chase_date
AND t1.chase_description = t2.chase_description
AND t1.chase_amount = t2.chase_amount;
```

**Fix orphaned references:**
```sql
UPDATE incoming_receipts
SET matched_transaction_id = NULL, status = 'pending'
WHERE matched_transaction_id NOT IN (SELECT _index FROM transactions);
```

### Prevention

- Add unique constraints where appropriate
- Use transactions for multi-table updates
- Regular data quality checks (see test_data_quality.py)

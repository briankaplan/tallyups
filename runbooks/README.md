# ReceiptAI Operational Runbooks

Quick reference guides for common operational tasks and incident response.

## Table of Contents

1. [Deployment](#deployment)
2. [Database Operations](#database-operations)
3. [Incident Response](#incident-response)
4. [Monitoring & Alerts](#monitoring--alerts)
5. [Backup & Recovery](#backup--recovery)

---

## Quick Reference

| Task | Command |
|------|---------|
| Check status | `./scripts/railway-status.sh` |
| Deploy to dev | `git push origin dev` |
| Deploy to prod | `git push origin main` |
| Promote dev→prod | `./scripts/railway-promote.sh` |
| Run smoke tests | `./scripts/run_tests.sh smoke` |
| View logs | `railway logs -e production` |
| Check health | `curl https://tallyups.com/health` |

---

## Deployment

### Deploy to Development
```bash
git checkout dev
git merge feature-branch
git push origin dev
# Auto-deploys to https://web-development-c29a.up.railway.app
```

### Deploy to Production
```bash
git checkout main
git merge dev
git push origin main
# Auto-deploys to https://tallyups.com
```

### Manual Deploy (Emergency)
```bash
railway link --environment production
railway up --detach
```

### Rollback Production
```bash
# Via Railway Dashboard:
# 1. Go to Deployments
# 2. Find last good deployment
# 3. Click "..." → "Redeploy"

# Via CLI:
railway rollback
```

---

## Database Operations

### Connection Pool Status
```bash
curl https://tallyups.com/api/health/pool-status
```

### Reset Connection Pool
```bash
curl -X POST https://tallyups.com/api/health/pool-reset
```

### Run Query (Railway)
```bash
railway connect mysql
# Then run SQL
```

### Check Slow Queries
```sql
SHOW PROCESSLIST;
SELECT * FROM information_schema.processlist WHERE time > 30;
```

---

## Incident Response

See individual runbook files:
- `runbook-database-issues.md`
- `runbook-high-error-rate.md`
- `runbook-slow-performance.md`
- `runbook-gmail-failures.md`

---

## Monitoring & Alerts

### Health Check Endpoints
| Endpoint | Purpose |
|----------|---------|
| `/health` | Overall system health |
| `/api/health/pool-status` | Database pool metrics |

### Key Metrics to Monitor
- Response time (p99 < 1s)
- Error rate (< 1%)
- Database pool utilization (< 80%)
- Memory usage (< 80%)

---

## Backup & Recovery

### Automated Backups
- Database: Daily at 2 AM UTC
- Receipts: Stored in R2 (auto-replicated)

### Manual Backup
```bash
./scripts/backup-database.sh
```

### Restore Database
```bash
./scripts/restore-database.sh backups/backup_20250101_020000.sql.gz
```

---

## Contacts

| Role | Contact |
|------|---------|
| On-call | Check PagerDuty |
| Database | Brian Kaplan |
| Infrastructure | Railway Support |

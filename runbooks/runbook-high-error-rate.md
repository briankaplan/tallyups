# Runbook: High Error Rate

## Overview

This runbook covers investigation and resolution when the application experiences elevated error rates (>1% of requests).

---

## Symptoms

- Health check shows `status: degraded`
- Alert: "High error rate: X errors in last minute"
- Users reporting 500 errors
- Dashboard showing errors

---

## Quick Triage (First 5 Minutes)

### 1. Check overall health
```bash
curl -s https://tallyups.com/health | jq
```

### 2. Check recent logs for errors
```bash
railway logs -e production --limit 200 | grep -i "error\|exception\|traceback"
```

### 3. Identify error patterns
```bash
# Count errors by type
railway logs -e production --limit 500 | grep "ERROR" | cut -d: -f4 | sort | uniq -c | sort -rn
```

### 4. Check if specific endpoint
```bash
railway logs -e production | grep "500" | grep -oP 'path[=:]["]\K[^"]+' | sort | uniq -c
```

---

## Common Error Patterns

### Pattern 1: Database Connection Errors

**Signs:**
- Errors contain `MySQL`, `connection`, `pool`
- Multiple endpoints affected
- Health shows database unhealthy

**Action:** See `runbook-database-issues.md`

---

### Pattern 2: External API Failures

**Signs:**
- Errors contain `OpenAI`, `Gemini`, `Gmail`
- AI features not working
- Specific endpoints affected

**Investigation:**
```bash
# Check API status pages
# OpenAI: https://status.openai.com
# Google: https://status.cloud.google.com
```

**Resolution:**
```python
# Verify API keys are valid
curl -s "https://api.openai.com/v1/models" \
  -H "Authorization: Bearer $OPENAI_API_KEY" | jq '.error // "OK"'
```

If API is down:
1. Errors will auto-recover when API returns
2. Consider disabling AI features temporarily:
   ```bash
   railway variables set ENABLE_SMART_NOTES=false -e production
   ```

If API key expired:
1. Generate new key from provider
2. Update in Railway:
   ```bash
   railway variables set OPENAI_API_KEY=sk-new-key -e production
   ```

---

### Pattern 3: Memory/Resource Exhaustion

**Signs:**
- OOM (Out of Memory) errors
- Service restarts frequently
- Slow responses before crash

**Investigation:**
```bash
# Check Railway metrics in dashboard
# Look for memory spikes
```

**Resolution:**
1. Increase memory limit in Railway
2. Identify memory leaks:
   - Large file uploads not cleaned up
   - Image processing without cleanup
   - Growing caches

3. Add memory limits to image processing:
   ```python
   # Limit image size before processing
   MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10MB
   ```

---

### Pattern 4: Code Bug (Recent Deploy)

**Signs:**
- Errors started after recent deployment
- Specific error message in stack trace
- Only certain operations affected

**Investigation:**
```bash
# Check what changed
git log --oneline -5 main

# Check specific file changes
git diff HEAD~1 HEAD -- viewer_server.py
```

**Resolution:**

**Option 1: Quick fix**
```bash
# Fix the bug
git checkout main
# ... make fix ...
git commit -am "fix: resolve error in endpoint"
git push origin main
```

**Option 2: Rollback**
```bash
# Via Railway dashboard:
# Deployments → Find last good → Redeploy

# Or revert commit:
git revert HEAD
git push origin main
```

---

### Pattern 5: Rate Limiting

**Signs:**
- 429 errors in logs
- External API rate limit messages
- Periodic error spikes

**Resolution:**
1. Implement exponential backoff:
   ```python
   @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
   def call_api():
       ...
   ```

2. Add request caching
3. Spread out batch operations

---

## Escalation

### When to Escalate

- Error rate > 10% for > 5 minutes
- Database is completely down
- Multiple services affected
- User data at risk

### Escalation Path

1. **Level 1**: On-call engineer
   - Can restart services
   - Can rollback deployments

2. **Level 2**: Platform owner
   - Can modify infrastructure
   - Can contact Railway support

3. **Level 3**: Railway Support
   - For platform-level issues
   - support@railway.app

---

## Post-Incident

### Required Actions

1. **Update status page** (if exists)
2. **Document timeline** of incident
3. **Identify root cause**
4. **Create follow-up issues** for prevention

### Post-Incident Template

```markdown
## Incident Report: [Title]

**Date:** YYYY-MM-DD
**Duration:** X hours Y minutes
**Severity:** P1/P2/P3

### Summary
Brief description of what happened.

### Timeline
- HH:MM - Alert triggered
- HH:MM - Investigation started
- HH:MM - Root cause identified
- HH:MM - Fix deployed
- HH:MM - Verified resolved

### Root Cause
What caused the incident.

### Resolution
What was done to fix it.

### Prevention
What will prevent this in the future.

### Action Items
- [ ] Add monitoring for X
- [ ] Improve error handling for Y
- [ ] Add test for Z
```

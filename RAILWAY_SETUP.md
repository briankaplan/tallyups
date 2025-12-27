# Railway Configuration - Complete Setup

## Environment Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        tallyups Project                         │
├─────────────────────────────┬───────────────────────────────────┤
│      DEVELOPMENT            │         PRODUCTION                │
│  (branch: dev)              │      (branch: main)               │
├─────────────────────────────┼───────────────────────────────────┤
│  web                        │  web                              │
│  └─ web-development-c29a    │  └─ web-production-309e           │
│                             │                                   │
│  MySQL-Dev                  │  MySQL                            │
│  └─ railway_dev database    │  └─ railway database              │
└─────────────────────────────┴───────────────────────────────────┘
```

## URLs

| Environment | Web URL | Database |
|-------------|---------|----------|
| **Production** | https://web-production-309e.up.railway.app | MySQL (shared) |
| **Development** | https://web-development-c29a.up.railway.app | MySQL-Dev (isolated) |

## Auto-Deploy Triggers

| Branch | Deploys To |
|--------|------------|
| `main` | Production |
| `dev` | Development |

## Services

### Production Environment
- **web** - Main Flask application
- **MySQL** - Production database

### Development Environment  
- **web** - Development Flask application
- **MySQL-Dev** - Isolated dev database (won't affect production data)

## Project IDs (for API access)

```bash
PROJECT_ID="f6f866e5-94f7-4ced-9bc7-a33197ca8411"
PROD_ENV_ID="9d801aac-3f55-4ee0-a012-e2d8a9a58e55"
DEV_ENV_ID="7542556b-c121-4ed5-bfee-ca4f83d24039"
WEB_SERVICE_ID="c359b956-80d3-4223-ba6d-456e6ab1824b"
MYSQL_SERVICE_ID="b88afa88-ffa5-4768-8e53-5df2faa1caa1"
MYSQL_DEV_SERVICE_ID="4b41d25e-7ea5-438e-8399-cb23161e61d9"
RAILWAY_API_TOKEN="e82a0806-6042-4101-bbce-34945c3212cb"
```

## Health Checks (Configured)

Both environments have:
- **Health check path:** `/health`
- **Timeout:** 30 seconds
- **Restart policy:** On failure (max 3 retries)

## Environment-Specific Variables

### Development (auto-set)
```
MYSQL_URL=mysql://root:devpassword123@MySQL-Dev.railway.internal:3306/railway_dev
RAILWAY_ENVIRONMENT=development
LOG_LEVEL=DEBUG
```

### Production (unchanged)
```
MYSQL_URL=mysql://root:xxx@metro.proxy.rlwy.net:19800/railway
RAILWAY_ENVIRONMENT=production
LOG_LEVEL=INFO
```

---

## Workflow

### Daily Development
```bash
# 1. Make sure you're on dev branch
git checkout dev

# 2. Make changes, test locally
# ... code ...

# 3. Commit and push (auto-deploys to development)
git add .
git commit -m "feat: new feature"
git push

# 4. Test at development URL
open https://web-development-c29a.up.railway.app
```

### Promoting to Production
```bash
# Option 1: Merge dev → main (recommended)
git checkout main
git merge dev
git push  # Auto-deploys to production

# Option 2: Use promotion script
./scripts/railway-promote.sh
```

### Checking Status
```bash
./scripts/railway-status.sh
```

---

## Scripts Available

| Script | Description |
|--------|-------------|
| `./scripts/railway-status.sh` | Check health of both environments |
| `./scripts/railway-dev-deploy.sh` | Manual deploy to development |
| `./scripts/railway-promote.sh` | Promote dev to production |

---

## API Examples

### Check deployment status
```bash
curl -s -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST https://backboard.railway.app/graphql/v2 \
  -d '{"query": "query { project(id: \"f6f866e5-94f7-4ced-9bc7-a33197ca8411\") { environments { edges { node { name deployments(first: 1) { edges { node { status } } } } } } } }"}'
```

### Trigger redeploy
```bash
# Development
curl -s -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST https://backboard.railway.app/graphql/v2 \
  -d '{"query": "mutation { serviceInstanceRedeploy(serviceId: \"c359b956-80d3-4223-ba6d-456e6ab1824b\", environmentId: \"7542556b-c121-4ed5-bfee-ca4f83d24039\") }"}'

# Production
curl -s -H "Authorization: Bearer $RAILWAY_API_TOKEN" \
  -H "Content-Type: application/json" \
  -X POST https://backboard.railway.app/graphql/v2 \
  -d '{"query": "mutation { serviceInstanceRedeploy(serviceId: \"c359b956-80d3-4223-ba6d-456e6ab1824b\", environmentId: \"9d801aac-3f55-4ee0-a012-e2d8a9a58e55\") }"}'
```

---

## Backup Location

Full backup saved to: `~/Desktop/ReceiptAI-Backup-20251210/`
- Git bundle (all branches)
- Railway environment variables
- Recent commit history

---

## Quick Reference

```bash
# Switch branches
git checkout dev      # Work on features
git checkout main     # Prepare for production

# Check status
./scripts/railway-status.sh

# View logs
railway logs -e development
railway logs -e production
```

---

## Custom Domain

| Domain | Environment | Status |
|--------|-------------|--------|
| **tallyups.com** | Production | ✅ Configured |
| web-production-309e.up.railway.app | Production | Active |
| web-development-c29a.up.railway.app | Development | Active |

### DNS Configuration (Cloudflare)

```
Type    Name    Target                      Proxy
CNAME   @       7j6thkww.up.railway.app     Proxied (orange)
CNAME   www     tallyups.com                Proxied (orange)
```

**SSL/TLS:** Set to "Full" mode in Cloudflare

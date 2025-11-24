# Railway Deployment Guide

## Prerequisites
- Railway account (https://railway.app)
- Railway CLI installed
- Git repository

## Step 1: Install Railway CLI

```bash
# macOS/Linux
curl -fsSL https://railway.app/install.sh | sh

# Or via npm
npm i -g @railway/cli
```

## Step 2: Login to Railway

```bash
railway login
```

## Step 3: Initialize Project

```bash
# In your project directory
railway init
```

## Step 4: Set Environment Variables

### Via CLI:
```bash
railway variables set AUTH_PASSWORD="YourSecurePassword"
railway variables set OPENAI_API_KEY="your-openai-key"
railway variables set GEMINI_API_KEY="your-gemini-key"
railway variables set R2_ACCOUNT_ID="your-r2-account-id"
railway variables set R2_BUCKET_NAME="your-bucket-name"
railway variables set R2_ACCESS_KEY_ID="your-access-key"
railway variables set R2_SECRET_ACCESS_KEY="your-secret-key"
railway variables set R2_PUBLIC_URL="https://your-r2-url"
railway variables set R2_ENDPOINT="https://your-r2-endpoint"
```

### Or via Railway Dashboard:
1. Go to your project
2. Click "Variables"  
3. Add each variable from your `.env` file

## Step 5: Link GitHub Repository (Recommended)

1. Push code to GitHub
2. In Railway dashboard, click "Deploy from GitHub"
3. Select your repository
4. Railway will auto-deploy on push

## Step 6: Deploy

```bash
# Deploy current directory
railway up

# Or if linked to GitHub, just push:
git push origin main
```

## Step 7: Get Your URL

```bash
railway domain
```

Or check the Railway dashboard for your app URL.

## Important Notes

### Database Persistence
- **WARNING**: Railway has ephemeral filesystem
- Your SQLite database (`receipt-system/receipts.db`) will be LOST on redeploy
- **Solution**: Use Railway Volumes for persistence

### Add Volume for Database:
1. Railway Dashboard → Your Service → Settings
2. Scroll to "Volumes"
3. Click "New Volume"
4. Mount path: `/app/receipt-system`
5. This persists your `receipts.db` and `gmail_tokens/`

### Gmail Tokens
- Gmail OAuth tokens in `receipt-system/gmail_tokens/` need persistence
- Same solution: use Railway Volume

## Post-Deployment

### Test Your App:
```bash
curl https://your-app.railway.app/api/health
```

### View Logs:
```bash
railway logs
```

### Check Status:
```bash
railway status
```

## Troubleshooting

### Build Fails:
- Check Railway build logs: `railway logs --build`
- Ensure `requirements.txt` is up to date

### App Crashes:
- Check runtime logs: `railway logs`
- Verify all environment variables are set
- Check PORT binding (Railway provides $PORT automatically)

### Database Lost After Redeploy:
- Add a Volume (see Database Persistence section)
- Volume path must match your app's database location

## Files Created for Railway

- `Procfile` - Tells Railway how to start your app
- `railway.json` - Railway configuration
- `runtime.txt` - Python version specification
- `requirements.txt` - Python dependencies

## Useful Commands

```bash
# Open Railway dashboard
railway open

# Run command in Railway environment  
railway run python script.py

# SSH into your deployment
railway shell

# Delete deployment
railway down
```

## Cost

- Railway offers $5/month free credit
- After that, pay-as-you-go pricing
- Monitor usage in dashboard

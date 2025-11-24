#!/bin/bash
# Railway Environment Variables Setup Script
# Run this after: railway login && railway init

echo "🚂 Setting Railway Environment Variables..."
echo ""

# Load variables from .env
source .env

# Set all environment variables
echo "Setting OPENAI_API_KEY..."
railway variables set OPENAI_API_KEY="$OPENAI_API_KEY"

echo "Setting GEMINI_API_KEY..."
railway variables set GEMINI_API_KEY="$GEMINI_API_KEY"

echo "Setting GEMINI_API_KEY_2..."
railway variables set GEMINI_API_KEY_2="$GEMINI_API_KEY_2"

echo "Setting GEMINI_API_KEY_3..."
railway variables set GEMINI_API_KEY_3="$GEMINI_API_KEY_3"

echo "Setting R2 credentials..."
railway variables set R2_ACCOUNT_ID="$R2_ACCOUNT_ID"
railway variables set R2_BUCKET_NAME="$R2_BUCKET_NAME"
railway variables set R2_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID"
railway variables set R2_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY"
railway variables set R2_TOKEN="$R2_TOKEN"
railway variables set R2_PUBLIC_URL="$R2_PUBLIC_URL"
railway variables set R2_ENDPOINT="$R2_ENDPOINT"

echo "Setting AUTH_PASSWORD..."
railway variables set AUTH_PASSWORD="$AUTH_PASSWORD"

echo "Setting application config..."
railway variables set PORT="$PORT"
railway variables set AI_MODEL="$AI_MODEL"
railway variables set AI_CONFIDENCE_THRESHOLD="$AI_CONFIDENCE_THRESHOLD"
railway variables set LOG_DIR="$LOG_DIR"
railway variables set LOG_LEVEL="$LOG_LEVEL"
railway variables set OCR_ENGINE="$OCR_ENGINE"
railway variables set OCR_LANG="$OCR_LANG"
railway variables set AUTO_BACKUP="$AUTO_BACKUP"
railway variables set BACKUP_DIR="$BACKUP_DIR"
railway variables set ENABLE_AI_BUSINESS_INFERENCE="$ENABLE_AI_BUSINESS_INFERENCE"
railway variables set ENABLE_TIP_DETECTION="$ENABLE_TIP_DETECTION"
railway variables set ENABLE_SMART_NOTES="$ENABLE_SMART_NOTES"

echo "Setting CSV config..."
railway variables set RR_CSV="$RR_CSV"
railway variables set RR_RECEIPTS="$RR_RECEIPTS"
railway variables set RR_HTML="$RR_HTML"

echo ""
echo "✅ All environment variables set!"
echo ""
echo "Next steps:"
echo "1. Add a Railway Volume at: /app/receipt-system"
echo "2. Deploy with: railway up"
echo "3. Get your URL with: railway domain"

#!/bin/bash
# ReceiptAI Database Backup Script
# =================================
# Creates a compressed backup of the MySQL database and uploads to R2
#
# Usage:
#   ./scripts/backup-database.sh              # Backup with timestamp
#   ./scripts/backup-database.sh manual       # Backup with "manual" prefix
#   ./scripts/backup-database.sh pre-deploy   # Backup before deployment

set -e

# Configuration
BACKUP_PREFIX="${1:-backup}"
TIMESTAMP=$(date -u +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_PREFIX}_${TIMESTAMP}.sql.gz"
TEMP_DIR="/tmp/receiptai_backups"
R2_BACKUP_PATH="database/${BACKUP_FILE}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}📦 ReceiptAI Database Backup${NC}"
echo "=============================="
echo "Timestamp: ${TIMESTAMP}"
echo "Backup file: ${BACKUP_FILE}"
echo ""

# Create temp directory
mkdir -p "$TEMP_DIR"

# Parse MySQL URL
# Format: mysql://user:password@host:port/database
if [ -z "$MYSQL_URL" ]; then
    # Try to get from Railway
    if command -v railway &> /dev/null; then
        echo "Getting MySQL URL from Railway..."
        MYSQL_URL=$(railway variables --json 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('MYSQL_URL',''))" 2>/dev/null || echo "")
    fi
fi

if [ -z "$MYSQL_URL" ]; then
    echo -e "${RED}Error: MYSQL_URL not set${NC}"
    echo "Set MYSQL_URL environment variable or run from Railway context"
    exit 1
fi

# Parse URL components
DB_USER=$(echo "$MYSQL_URL" | sed -n 's|mysql://\([^:]*\):.*|\1|p')
DB_PASS=$(echo "$MYSQL_URL" | sed -n 's|mysql://[^:]*:\([^@]*\)@.*|\1|p')
DB_HOST=$(echo "$MYSQL_URL" | sed -n 's|mysql://[^@]*@\([^:]*\):.*|\1|p')
DB_PORT=$(echo "$MYSQL_URL" | sed -n 's|mysql://[^@]*@[^:]*:\([^/]*\)/.*|\1|p')
DB_NAME=$(echo "$MYSQL_URL" | sed -n 's|mysql://[^/]*/\(.*\)|\1|p')

echo "Database: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
echo ""

# Step 1: Dump database
echo -e "${YELLOW}Step 1: Dumping database...${NC}"
mysqldump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --password="$DB_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    --set-gtid-purged=OFF \
    "$DB_NAME" | gzip > "${TEMP_DIR}/${BACKUP_FILE}"

BACKUP_SIZE=$(du -h "${TEMP_DIR}/${BACKUP_FILE}" | cut -f1)
echo -e "${GREEN}✓ Database dumped (${BACKUP_SIZE})${NC}"
echo ""

# Step 2: Upload to R2 (if configured)
if [ -n "$R2_ACCESS_KEY_ID" ] && [ -n "$R2_SECRET_ACCESS_KEY" ] && [ -n "$R2_ENDPOINT" ]; then
    echo -e "${YELLOW}Step 2: Uploading to R2...${NC}"

    # Use AWS CLI with R2 endpoint
    AWS_ACCESS_KEY_ID="$R2_ACCESS_KEY_ID" \
    AWS_SECRET_ACCESS_KEY="$R2_SECRET_ACCESS_KEY" \
    aws s3 cp \
        "${TEMP_DIR}/${BACKUP_FILE}" \
        "s3://${R2_BACKUP_BUCKET:-bkreceipts-backups}/${R2_BACKUP_PATH}" \
        --endpoint-url "$R2_ENDPOINT" \
        --quiet

    echo -e "${GREEN}✓ Uploaded to R2: ${R2_BACKUP_PATH}${NC}"
else
    echo -e "${YELLOW}⚠ R2 not configured, keeping local backup only${NC}"
fi
echo ""

# Step 3: Cleanup old local backups (keep last 5)
echo -e "${YELLOW}Step 3: Cleaning up old backups...${NC}"
ls -t "${TEMP_DIR}"/backup_*.sql.gz 2>/dev/null | tail -n +6 | xargs -r rm -f
echo -e "${GREEN}✓ Cleanup complete${NC}"
echo ""

# Step 4: Verify backup
echo -e "${YELLOW}Step 4: Verifying backup...${NC}"
if gzip -t "${TEMP_DIR}/${BACKUP_FILE}" 2>/dev/null; then
    echo -e "${GREEN}✓ Backup verified (gzip integrity OK)${NC}"
else
    echo -e "${RED}✗ Backup verification failed!${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}✅ Backup complete!${NC}"
echo ""
echo "Local path: ${TEMP_DIR}/${BACKUP_FILE}"
if [ -n "$R2_ACCESS_KEY_ID" ]; then
    echo "R2 path: s3://${R2_BACKUP_BUCKET:-bkreceipts-backups}/${R2_BACKUP_PATH}"
fi
echo ""

# Output for scripts
echo "${TEMP_DIR}/${BACKUP_FILE}"

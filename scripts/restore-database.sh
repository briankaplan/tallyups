#!/bin/bash
# ReceiptAI Database Restore Script
# ==================================
# Restores a MySQL database from a backup file
#
# Usage:
#   ./scripts/restore-database.sh backup_file.sql.gz
#   ./scripts/restore-database.sh /tmp/receiptai_backups/backup_20250101_020000.sql.gz
#
# WARNING: This will REPLACE all data in the target database!

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

# Check arguments
if [ -z "$1" ]; then
    echo -e "${RED}Error: No backup file specified${NC}"
    echo ""
    echo "Usage: ./scripts/restore-database.sh <backup_file.sql.gz>"
    echo ""
    echo "Examples:"
    echo "  ./scripts/restore-database.sh backup_20250101_020000.sql.gz"
    echo "  ./scripts/restore-database.sh /tmp/receiptai_backups/backup_20250101_020000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"

# Check if file exists
if [ ! -f "$BACKUP_FILE" ]; then
    # Try in default backup directory
    if [ -f "/tmp/receiptai_backups/$BACKUP_FILE" ]; then
        BACKUP_FILE="/tmp/receiptai_backups/$BACKUP_FILE"
    else
        echo -e "${RED}Error: Backup file not found: $BACKUP_FILE${NC}"
        exit 1
    fi
fi

echo -e "${GREEN}📦 ReceiptAI Database Restore${NC}"
echo "==============================="
echo "Backup file: ${BACKUP_FILE}"
echo ""

# Parse MySQL URL
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

echo "Target Database: ${DB_NAME}@${DB_HOST}:${DB_PORT}"
echo ""

# Safety confirmation
echo -e "${YELLOW}⚠️  WARNING: This will REPLACE ALL DATA in the database!${NC}"
echo ""
read -p "Are you sure you want to restore? (yes/no): " CONFIRM

if [ "$CONFIRM" != "yes" ]; then
    echo "Restore cancelled."
    exit 0
fi

echo ""

# Step 1: Verify backup file
echo -e "${YELLOW}Step 1: Verifying backup file...${NC}"
if ! gzip -t "$BACKUP_FILE" 2>/dev/null; then
    echo -e "${RED}Error: Backup file is corrupted or invalid${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Backup file verified${NC}"
echo ""

# Step 2: Create pre-restore backup
echo -e "${YELLOW}Step 2: Creating pre-restore backup...${NC}"
PRE_RESTORE_BACKUP="/tmp/receiptai_backups/pre_restore_$(date -u +%Y%m%d_%H%M%S).sql.gz"
mkdir -p /tmp/receiptai_backups

mysqldump \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --password="$DB_PASS" \
    --single-transaction \
    --routines \
    --triggers \
    --set-gtid-purged=OFF \
    "$DB_NAME" 2>/dev/null | gzip > "$PRE_RESTORE_BACKUP"

echo -e "${GREEN}✓ Pre-restore backup saved: $PRE_RESTORE_BACKUP${NC}"
echo ""

# Step 3: Restore database
echo -e "${YELLOW}Step 3: Restoring database...${NC}"

# Decompress and restore
gunzip -c "$BACKUP_FILE" | mysql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --password="$DB_PASS" \
    "$DB_NAME"

echo -e "${GREEN}✓ Database restored${NC}"
echo ""

# Step 4: Verify restore
echo -e "${YELLOW}Step 4: Verifying restore...${NC}"

# Count rows in main table
ROW_COUNT=$(mysql \
    --host="$DB_HOST" \
    --port="$DB_PORT" \
    --user="$DB_USER" \
    --password="$DB_PASS" \
    --skip-column-names \
    -e "SELECT COUNT(*) FROM transactions" \
    "$DB_NAME" 2>/dev/null)

echo "Transactions table: ${ROW_COUNT} rows"
echo -e "${GREEN}✓ Restore verified${NC}"
echo ""

echo -e "${GREEN}✅ Restore complete!${NC}"
echo ""
echo "If something went wrong, restore from pre-restore backup:"
echo "  ./scripts/restore-database.sh $PRE_RESTORE_BACKUP"
echo ""

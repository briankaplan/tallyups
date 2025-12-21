-- Migration 004: Drop deprecated receipt_url column
-- The r2_url column is now the canonical source for receipt URLs
--
-- Before running this migration:
-- 1. Verify r2_url is populated where needed: SELECT COUNT(*) FROM transactions WHERE r2_url IS NOT NULL
-- 2. Backup the database
--
-- Date: 2024-12-21

-- First, copy any receipt_url data to r2_url where r2_url is empty (just in case)
UPDATE transactions
SET r2_url = receipt_url
WHERE (r2_url IS NULL OR r2_url = '')
  AND receipt_url IS NOT NULL
  AND receipt_url != '';

-- Drop the index on receipt_url if it exists
DROP INDEX IF EXISTS idx_receipt_url ON transactions;

-- Drop the composite index that includes receipt_url
DROP INDEX IF EXISTS idx_has_receipt ON transactions;

-- Drop the receipt_url column
ALTER TABLE transactions DROP COLUMN IF EXISTS receipt_url;

-- Recreate the has_receipt index using only r2_url and receipt_file
CREATE INDEX idx_has_receipt ON transactions(r2_url(50), receipt_file(50));

-- Verify the column was dropped
-- SELECT column_name FROM information_schema.columns
-- WHERE table_name = 'transactions' AND column_name = 'receipt_url';

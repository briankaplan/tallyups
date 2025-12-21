-- Migration 006: Decimal Precision Standardization
-- Standardizes all financial amounts to DECIMAL(15,2) to prevent data loss
--
-- Current state:
--   - Most tables use DECIMAL(10,2) - max 99,999,999.99
--   - plaid_accounts/plaid_transactions use DECIMAL(15,2) - max 9,999,999,999,999.99
--
-- This migration upgrades all to DECIMAL(15,2) for consistency
--
-- IMPORTANT: This is a safe upgrade (widening precision never loses data)
--
-- Date: 2024-12-21

-- ============================================================================
-- SECTION 1: TRANSACTIONS TABLE
-- ============================================================================

-- Upgrade chase_amount from DECIMAL(10,2) to DECIMAL(15,2)
ALTER TABLE transactions
MODIFY COLUMN chase_amount DECIMAL(15,2);

-- ============================================================================
-- SECTION 2: INCOMING_RECEIPTS TABLE
-- ============================================================================

-- Upgrade extracted_amount
ALTER TABLE incoming_receipts
MODIFY COLUMN extracted_amount DECIMAL(15,2);

-- ============================================================================
-- SECTION 3: EXPENSE_REPORTS TABLE
-- ============================================================================

-- Upgrade total_amount if it exists
ALTER TABLE expense_reports
MODIFY COLUMN total_amount DECIMAL(15,2);

-- ============================================================================
-- SECTION 4: OCR_CACHE TABLE
-- ============================================================================

-- If amount is stored in ocr_cache, upgrade it
-- ALTER TABLE ocr_cache
-- MODIFY COLUMN amount DECIMAL(15,2);

-- ============================================================================
-- SECTION 5: VERIFICATION
-- ============================================================================

-- Verify column types after migration:
-- SELECT TABLE_NAME, COLUMN_NAME, COLUMN_TYPE
-- FROM information_schema.COLUMNS
-- WHERE TABLE_SCHEMA = DATABASE()
--   AND COLUMN_NAME LIKE '%amount%'
--   AND DATA_TYPE = 'decimal';

-- Expected output: All should show decimal(15,2)

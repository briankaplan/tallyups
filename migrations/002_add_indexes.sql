-- Migration: 002_add_indexes
-- Description: Add performance indexes for common query patterns
-- Created: 2025-11-24

-- ============================================================================
-- COMPOSITE INDEXES FOR DASHBOARD QUERIES
-- ============================================================================

-- Dashboard: Filter by business type and date range
CREATE INDEX IF NOT EXISTS idx_transactions_business_date
ON transactions(business_type, chase_date);

-- Dashboard: Filter by review status and business type
CREATE INDEX IF NOT EXISTS idx_transactions_review_business
ON transactions(review_status, business_type);

-- Dashboard: Filter by verification status and business type
CREATE INDEX IF NOT EXISTS idx_transactions_verification_business
ON transactions(verification_status, business_type);

-- ============================================================================
-- COMPOSITE INDEXES FOR MATCHING QUERIES
-- ============================================================================

-- Matching: Find transactions by amount and date for receipt matching
CREATE INDEX IF NOT EXISTS idx_transactions_amount_date
ON transactions(chase_amount, chase_date);

-- Matching: Find unmatched transactions
CREATE INDEX IF NOT EXISTS idx_transactions_no_receipt
ON transactions(receipt_file(1), chase_date)
WHERE receipt_file IS NULL OR receipt_file = '';

-- ============================================================================
-- FULLTEXT INDEXES FOR SEARCH
-- ============================================================================

-- Search: Full-text search on transaction descriptions
ALTER TABLE transactions
ADD FULLTEXT INDEX ft_chase_description (chase_description);

-- Search: Full-text search on notes
ALTER TABLE transactions
ADD FULLTEXT INDEX ft_notes (notes);

-- Search: Full-text search on incoming receipts OCR text
ALTER TABLE incoming_receipts
ADD FULLTEXT INDEX ft_ocr_text (ocr_raw_text);

-- ============================================================================
-- INDEXES FOR REPORTING QUERIES
-- ============================================================================

-- Reports: Monthly summaries by business type
CREATE INDEX IF NOT EXISTS idx_transactions_month_business
ON transactions(business_type, chase_date);

-- Reports: Expense totals by category
CREATE INDEX IF NOT EXISTS idx_transactions_category_amount
ON transactions(chase_category, chase_amount);

-- ============================================================================
-- INDEXES FOR INCOMING RECEIPTS PROCESSING
-- ============================================================================

-- Processing: Find unprocessed receipts
CREATE INDEX IF NOT EXISTS idx_incoming_unprocessed
ON incoming_receipts(processed, created_at);

-- Processing: Find pending matches
CREATE INDEX IF NOT EXISTS idx_incoming_pending_match
ON incoming_receipts(status, ocr_date, ocr_total);

-- Processing: Gmail deduplication
CREATE INDEX IF NOT EXISTS idx_incoming_gmail_dedup
ON incoming_receipts(gmail_account, source_id);

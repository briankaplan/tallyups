-- Migration: 008_plaid_source_tracking
-- Add structured source account tracking for Plaid transactions
-- Created: 2025-12-23
-- Description: Enable better receipt matching by tracking source bank/card info

-- ============================================================================
-- ADD SOURCE TRACKING COLUMNS TO TRANSACTIONS
-- ============================================================================

-- Plaid transaction ID for deduplication and linking back to plaid_transactions
ALTER TABLE transactions
ADD COLUMN plaid_transaction_id VARCHAR(100) NULL AFTER receipt_source,
ADD COLUMN plaid_account_id VARCHAR(100) NULL AFTER plaid_transaction_id;

-- Structured source info for filtering and display
ALTER TABLE transactions
ADD COLUMN source_institution VARCHAR(100) NULL AFTER plaid_account_id,
ADD COLUMN source_account_name VARCHAR(100) NULL AFTER source_institution,
ADD COLUMN source_account_mask VARCHAR(10) NULL AFTER source_account_name;

-- ============================================================================
-- INDEXES FOR EFFICIENT QUERIES
-- ============================================================================

-- Unique index on plaid_transaction_id to prevent duplicate imports
CREATE UNIQUE INDEX idx_plaid_transaction_id
ON transactions(plaid_transaction_id);

-- Index for filtering by source
CREATE INDEX idx_source_institution
ON transactions(source_institution);

CREATE INDEX idx_source_account_mask
ON transactions(source_account_mask);

-- Composite index for "show all transactions from this card"
CREATE INDEX idx_source_account
ON transactions(source_institution, source_account_name, source_account_mask);

-- ============================================================================
-- FOREIGN KEY (optional - for referential integrity)
-- ============================================================================

-- Note: We don't enforce FK to plaid_accounts because:
-- 1. Some transactions may come from CSV imports (non-Plaid)
-- 2. Accounts might be disconnected but we keep transaction history
-- The plaid_account_id is for reference/joining only

-- ============================================================================
-- VIEW: Transactions with full source details
-- ============================================================================

CREATE OR REPLACE VIEW v_transactions_with_source AS
SELECT
    t.*,
    CASE
        WHEN t.source_institution IS NOT NULL THEN
            CONCAT(
                t.source_institution,
                ' - ',
                COALESCE(t.source_account_name, 'Account'),
                CASE WHEN t.source_account_mask IS NOT NULL
                     THEN CONCAT(' (...', t.source_account_mask, ')')
                     ELSE ''
                END
            )
        ELSE NULL
    END AS source_display,
    pa.type AS account_type,
    pa.subtype AS account_subtype,
    pa.balance_current,
    pa.default_business_type AS account_business_type
FROM transactions t
LEFT JOIN plaid_accounts pa ON t.plaid_account_id = pa.account_id;

-- ============================================================================
-- VIEW: Transaction counts by source account
-- ============================================================================

CREATE OR REPLACE VIEW v_transactions_by_source AS
SELECT
    source_institution,
    source_account_name,
    source_account_mask,
    COUNT(*) AS transaction_count,
    SUM(chase_amount) AS total_amount,
    MIN(chase_date) AS earliest_date,
    MAX(chase_date) AS latest_date,
    SUM(CASE WHEN r2_url IS NOT NULL AND r2_url != '' THEN 1 ELSE 0 END) AS with_receipt,
    SUM(CASE WHEN r2_url IS NULL OR r2_url = '' THEN 1 ELSE 0 END) AS without_receipt
FROM transactions
WHERE source_institution IS NOT NULL
GROUP BY source_institution, source_account_name, source_account_mask
ORDER BY transaction_count DESC;

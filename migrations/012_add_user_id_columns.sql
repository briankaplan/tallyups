-- Migration: 012_add_user_id_columns
-- Add user_id columns to all data tables for multi-tenancy
-- Created: 2025-12-26
-- Description: Add user_id to transactions, incoming_receipts, merchants, contacts, expense_reports

-- ============================================================================
-- TRANSACTIONS TABLE
-- ============================================================================
ALTER TABLE transactions
ADD COLUMN user_id CHAR(36) NULL AFTER _index,
ADD COLUMN deleted BOOLEAN DEFAULT FALSE AFTER updated_at;

CREATE INDEX idx_transactions_user_id ON transactions(user_id);
CREATE INDEX idx_transactions_deleted ON transactions(deleted);
CREATE INDEX idx_transactions_user_date ON transactions(user_id, chase_date);
CREATE INDEX idx_transactions_user_business ON transactions(user_id, business_type);

-- ============================================================================
-- INCOMING RECEIPTS TABLE
-- ============================================================================
ALTER TABLE incoming_receipts
ADD COLUMN user_id CHAR(36) NULL AFTER id,
ADD COLUMN deleted BOOLEAN DEFAULT FALSE AFTER updated_at;

CREATE INDEX idx_incoming_user_id ON incoming_receipts(user_id);
CREATE INDEX idx_incoming_deleted ON incoming_receipts(deleted);
CREATE INDEX idx_incoming_user_status ON incoming_receipts(user_id, status);

-- ============================================================================
-- MERCHANTS TABLE
-- ============================================================================
ALTER TABLE merchants
ADD COLUMN user_id CHAR(36) NULL AFTER id;

-- Merchants can be shared (user_id NULL) or user-specific
CREATE INDEX idx_merchants_user_id ON merchants(user_id);

-- ============================================================================
-- CONTACTS TABLE
-- ============================================================================
ALTER TABLE contacts
ADD COLUMN user_id CHAR(36) NULL AFTER id,
ADD COLUMN deleted BOOLEAN DEFAULT FALSE AFTER updated_at;

CREATE INDEX idx_contacts_user_id ON contacts(user_id);
CREATE INDEX idx_contacts_deleted ON contacts(deleted);

-- ============================================================================
-- EXPENSE REPORTS TABLE
-- ============================================================================
ALTER TABLE expense_reports
ADD COLUMN user_id CHAR(36) NULL AFTER id,
ADD COLUMN deleted BOOLEAN DEFAULT FALSE AFTER updated_at;

CREATE INDEX idx_expense_reports_user_id ON expense_reports(user_id);
CREATE INDEX idx_expense_reports_deleted ON expense_reports(deleted);

-- ============================================================================
-- OCR CACHE TABLE
-- ============================================================================
-- OCR cache can be shared across users (same receipt content = same hash)
-- No user_id needed here

-- ============================================================================
-- AUDIT LOG TABLE
-- ============================================================================
-- audit_log already has user_id column, just add index if missing
CREATE INDEX IF NOT EXISTS idx_audit_user_id ON audit_log(user_id);

-- ============================================================================
-- UPDATE PLAID ACCOUNTS TABLE (if exists)
-- ============================================================================
-- Check if plaid_accounts exists and add user_id
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'plaid_accounts'
);

-- Add user_id to plaid_accounts if it exists
-- This needs to be done via prepared statement for conditional execution
SET @sql = IF(@table_exists > 0,
    'ALTER TABLE plaid_accounts ADD COLUMN user_id CHAR(36) NULL AFTER id, ADD INDEX idx_plaid_accounts_user_id (user_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Same for plaid_institutions
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'plaid_institutions'
);

SET @sql = IF(@table_exists > 0,
    'ALTER TABLE plaid_institutions ADD COLUMN user_id CHAR(36) NULL AFTER id, ADD INDEX idx_plaid_institutions_user_id (user_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

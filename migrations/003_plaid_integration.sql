-- ============================================================================
-- Migration 003: Plaid Integration Schema
-- ============================================================================
-- Author: Claude Code
-- Created: 2025-12-20
-- Description: Complete schema for Plaid bank account linking and transaction sync
--
-- This migration adds support for:
--   - Multiple linked bank accounts per user
--   - Secure access token storage
--   - Transaction synchronization with cursor-based sync
--   - Webhook event tracking
--   - Account balance tracking
--   - Sync history and error logging
-- ============================================================================

-- ============================================================================
-- TABLE: plaid_items
-- ============================================================================
-- A Plaid Item represents a user's connection to a single financial institution.
-- Each Item can contain multiple accounts (checking, savings, credit cards, etc.)
--
-- SECURITY: access_token is encrypted and should NEVER be exposed to clients.
-- The item_id is the public-facing identifier.
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_items (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Plaid identifiers
    item_id VARCHAR(255) NOT NULL UNIQUE,           -- Plaid's unique identifier for this connection
    access_token VARCHAR(500) NOT NULL,              -- Encrypted access token (NEVER expose to client)

    -- Institution information
    institution_id VARCHAR(50),                      -- Plaid institution ID (e.g., 'ins_3')
    institution_name VARCHAR(255),                   -- Human-readable name (e.g., 'Chase')
    institution_logo TEXT,                           -- Base64 encoded logo (optional)
    institution_color VARCHAR(10),                   -- Primary brand color (e.g., '#0A4A82')

    -- Transaction sync cursor (for incremental sync)
    -- This cursor tracks where we left off in transaction sync.
    -- Plaid's cursor-based sync ensures we never miss or duplicate transactions.
    transactions_cursor TEXT,                        -- Opaque cursor for Plaid's transactions/sync endpoint

    -- Webhook configuration
    webhook_url VARCHAR(500),                        -- URL to receive Plaid webhooks

    -- Connection status
    status ENUM(
        'active',           -- Normal operation, syncing transactions
        'needs_reauth',     -- User needs to re-authenticate (e.g., password changed)
        'suspended',        -- Temporarily paused by user
        'revoked',          -- User revoked access
        'error'             -- Persistent error state
    ) DEFAULT 'active',

    -- Error tracking
    error_code VARCHAR(100),                         -- Last error code from Plaid
    error_message TEXT,                              -- Last error message
    error_timestamp DATETIME,                        -- When the error occurred

    -- Sync statistics
    last_successful_sync DATETIME,                   -- Last successful transaction sync
    last_sync_attempt DATETIME,                      -- Last sync attempt (success or failure)
    total_transactions_synced INT DEFAULT 0,         -- Cumulative count of synced transactions

    -- Multi-user support (future-proofing)
    user_id VARCHAR(100) DEFAULT 'default',          -- User identifier for multi-user support

    -- Consent tracking (for compliance)
    consent_given_at DATETIME,                       -- When user gave consent
    consent_expires_at DATETIME,                     -- When consent expires (if applicable)

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes for common queries
    INDEX idx_plaid_items_status (status),
    INDEX idx_plaid_items_user (user_id),
    INDEX idx_plaid_items_institution (institution_id),
    INDEX idx_plaid_items_last_sync (last_successful_sync)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- TABLE: plaid_accounts
-- ============================================================================
-- Individual accounts within a Plaid Item.
-- One Item (bank connection) can have multiple accounts:
--   - Checking accounts
--   - Savings accounts
--   - Credit cards
--   - Investment accounts
--   - Loan accounts
--
-- Each account is tracked separately for balance monitoring and can be
-- individually enabled/disabled for transaction sync.
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_accounts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Foreign key to plaid_items
    item_id VARCHAR(255) NOT NULL,

    -- Plaid identifiers
    account_id VARCHAR(255) NOT NULL UNIQUE,         -- Plaid's unique account identifier
    persistent_account_id VARCHAR(255),              -- Stable ID that persists across Item re-links

    -- Account information (from Plaid)
    name VARCHAR(255),                               -- Account name (e.g., 'Plaid Checking')
    official_name VARCHAR(255),                      -- Official account name from institution
    mask VARCHAR(10),                                -- Last 4 digits of account number

    -- Account classification
    type ENUM(
        'depository',       -- Checking, savings
        'credit',           -- Credit cards
        'loan',             -- Mortgages, student loans, auto loans
        'investment',       -- Brokerage, 401k, IRA
        'other'             -- Catch-all
    ) NOT NULL,

    subtype VARCHAR(50),                             -- More specific type (e.g., 'checking', 'credit card')

    -- Balance information (updated on each sync)
    balance_available DECIMAL(15, 2),                -- Available balance (checking/savings)
    balance_current DECIMAL(15, 2),                  -- Current balance
    balance_limit DECIMAL(15, 2),                    -- Credit limit (for credit accounts)
    balance_currency VARCHAR(3) DEFAULT 'USD',       -- ISO 4217 currency code
    balance_updated_at DATETIME,                     -- When balance was last updated

    -- Sync settings
    sync_enabled BOOLEAN DEFAULT TRUE,               -- Whether to sync transactions for this account

    -- Display settings
    display_name VARCHAR(255),                       -- User-customizable display name
    display_order INT DEFAULT 0,                     -- Order in UI
    is_hidden BOOLEAN DEFAULT FALSE,                 -- Hidden from main views

    -- Business classification (integrates with existing system)
    default_business_type VARCHAR(50),               -- Default business type for transactions

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Foreign key constraint
    CONSTRAINT fk_plaid_accounts_item
        FOREIGN KEY (item_id) REFERENCES plaid_items(item_id)
        ON DELETE CASCADE ON UPDATE CASCADE,

    -- Indexes
    INDEX idx_plaid_accounts_item (item_id),
    INDEX idx_plaid_accounts_type (type),
    INDEX idx_plaid_accounts_sync (sync_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- TABLE: plaid_transactions
-- ============================================================================
-- Transactions synced from Plaid.
--
-- IMPORTANT: This is a STAGING table. Transactions flow:
--   1. Synced from Plaid into this table
--   2. Processed and matched with receipts
--   3. Optionally merged into main 'transactions' table
--
-- This separation allows:
--   - Clean import/export without affecting existing data
--   - Easy reconciliation between Plaid and manual imports
--   - Rollback capability if sync goes wrong
--   - Duplicate detection across sources
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_transactions (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Plaid identifiers
    transaction_id VARCHAR(255) NOT NULL UNIQUE,     -- Plaid's unique transaction ID
    account_id VARCHAR(255) NOT NULL,                -- Which account this belongs to

    -- Foreign key to main transactions table (if linked)
    linked_transaction_id INT,                       -- Link to main transactions table

    -- Transaction details
    amount DECIMAL(15, 2) NOT NULL,                  -- Amount (positive = debit, negative = credit for Plaid)
    iso_currency_code VARCHAR(3) DEFAULT 'USD',      -- Currency

    -- Date information
    date DATE NOT NULL,                              -- Posted date
    datetime DATETIME,                               -- Exact datetime if available
    authorized_date DATE,                            -- When transaction was authorized
    authorized_datetime DATETIME,                    -- Exact authorization datetime

    -- Merchant/payee information
    merchant_name VARCHAR(255),                      -- Clean merchant name from Plaid
    name VARCHAR(500),                               -- Raw transaction name/description

    -- Location (if available)
    location_address VARCHAR(255),
    location_city VARCHAR(100),
    location_region VARCHAR(50),                     -- State/province
    location_postal_code VARCHAR(20),
    location_country VARCHAR(10),
    location_lat DECIMAL(10, 7),
    location_lon DECIMAL(10, 7),

    -- Categorization (Plaid's categories)
    category_id VARCHAR(50),                         -- Plaid category ID
    category_primary VARCHAR(100),                   -- Primary category
    category_detailed VARCHAR(100),                  -- Detailed category
    category_confidence_level ENUM(
        'VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'
    ) DEFAULT 'UNKNOWN',

    -- Personal finance category (newer Plaid categorization)
    personal_finance_category_primary VARCHAR(100),
    personal_finance_category_detailed VARCHAR(100),
    personal_finance_category_confidence ENUM(
        'VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW', 'UNKNOWN'
    ) DEFAULT 'UNKNOWN',

    -- Payment metadata
    payment_channel ENUM(
        'online',           -- Web/app purchase
        'in store',         -- Physical POS transaction
        'other'             -- Other methods
    ) DEFAULT 'other',

    -- Check information (if applicable)
    check_number VARCHAR(50),

    -- Transaction status
    pending BOOLEAN DEFAULT FALSE,                   -- Whether transaction is pending
    pending_transaction_id VARCHAR(255),             -- ID of pending transaction (before it posts)

    -- Business classification (matching existing system)
    business_type VARCHAR(50),                       -- 'Down_Home', 'MCR', 'Personal', etc.

    -- Receipt matching
    receipt_matched BOOLEAN DEFAULT FALSE,           -- Whether a receipt has been matched
    receipt_file VARCHAR(500),                       -- Path/URL to matched receipt
    r2_url VARCHAR(1000),                            -- R2 storage URL

    -- AI matching results
    ai_note TEXT,                                    -- AI-generated matching note
    ai_confidence FLOAT,                             -- Match confidence 0-100

    -- Processing status
    processing_status ENUM(
        'new',              -- Just synced, not processed
        'processing',       -- Being processed for receipt matching
        'matched',          -- Receipt matched
        'unmatched',        -- No receipt found
        'excluded',         -- Explicitly excluded from processing
        'duplicate'         -- Duplicate of existing transaction
    ) DEFAULT 'new',

    -- Sync metadata
    sync_batch_id VARCHAR(100),                      -- Which sync batch imported this
    synced_at DATETIME DEFAULT CURRENT_TIMESTAMP,    -- When we synced this transaction

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Foreign key to plaid_accounts
    CONSTRAINT fk_plaid_transactions_account
        FOREIGN KEY (account_id) REFERENCES plaid_accounts(account_id)
        ON DELETE CASCADE ON UPDATE CASCADE,

    -- Link to main transactions table (optional)
    CONSTRAINT fk_plaid_transactions_linked
        FOREIGN KEY (linked_transaction_id) REFERENCES transactions(id)
        ON DELETE SET NULL ON UPDATE CASCADE,

    -- Indexes for common queries
    INDEX idx_plaid_tx_account (account_id),
    INDEX idx_plaid_tx_date (date),
    INDEX idx_plaid_tx_merchant (merchant_name),
    INDEX idx_plaid_tx_amount (amount),
    INDEX idx_plaid_tx_pending (pending),
    INDEX idx_plaid_tx_processing (processing_status),
    INDEX idx_plaid_tx_business (business_type),
    INDEX idx_plaid_tx_synced (synced_at),

    -- Composite indexes for receipt matching queries
    INDEX idx_plaid_tx_match (date, amount, merchant_name),
    INDEX idx_plaid_tx_receipt (receipt_matched, processing_status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- TABLE: plaid_webhooks
-- ============================================================================
-- Audit log for all Plaid webhook events received.
-- This provides:
--   - Complete audit trail for compliance
--   - Debugging capability for sync issues
--   - Webhook replay capability
--   - Deduplication of webhook events
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_webhooks (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Webhook identification
    webhook_type VARCHAR(100) NOT NULL,              -- e.g., 'TRANSACTIONS', 'ITEM', 'AUTH'
    webhook_code VARCHAR(100) NOT NULL,              -- e.g., 'SYNC_UPDATES_AVAILABLE', 'ERROR'

    -- Associated Item (if applicable)
    item_id VARCHAR(255),

    -- Webhook payload
    payload JSON,                                    -- Full webhook payload (for replay)

    -- Processing status
    status ENUM(
        'received',         -- Just received, not processed
        'processing',       -- Currently being processed
        'processed',        -- Successfully processed
        'failed',           -- Processing failed
        'ignored'           -- Intentionally ignored
    ) DEFAULT 'received',

    -- Processing details
    processed_at DATETIME,
    error_message TEXT,
    retry_count INT DEFAULT 0,

    -- Deduplication
    webhook_id VARCHAR(255) UNIQUE,                  -- Plaid webhook ID for deduplication

    -- Metadata
    received_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_plaid_webhooks_type (webhook_type, webhook_code),
    INDEX idx_plaid_webhooks_item (item_id),
    INDEX idx_plaid_webhooks_status (status),
    INDEX idx_plaid_webhooks_received (received_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- TABLE: plaid_sync_history
-- ============================================================================
-- Detailed log of all sync operations.
-- Tracks every sync attempt with full statistics.
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_sync_history (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Which Item was synced
    item_id VARCHAR(255) NOT NULL,

    -- Sync batch identifier
    batch_id VARCHAR(100) NOT NULL UNIQUE,

    -- Sync type
    sync_type ENUM(
        'initial',          -- First sync after linking
        'incremental',      -- Normal incremental sync
        'historical',       -- Historical transaction fetch
        'manual',           -- User-triggered manual sync
        'webhook'           -- Triggered by webhook
    ) NOT NULL,

    -- Timing
    started_at DATETIME NOT NULL,
    completed_at DATETIME,
    duration_ms INT,                                 -- Duration in milliseconds

    -- Results
    status ENUM(
        'running',
        'success',
        'partial',          -- Some accounts failed
        'failed'
    ) DEFAULT 'running',

    -- Transaction counts
    transactions_added INT DEFAULT 0,
    transactions_modified INT DEFAULT 0,
    transactions_removed INT DEFAULT 0,

    -- Cursor information
    cursor_before TEXT,                              -- Cursor before sync
    cursor_after TEXT,                               -- Cursor after sync
    has_more BOOLEAN DEFAULT FALSE,                  -- More transactions available

    -- Error information
    error_code VARCHAR(100),
    error_message TEXT,

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Foreign key
    CONSTRAINT fk_plaid_sync_history_item
        FOREIGN KEY (item_id) REFERENCES plaid_items(item_id)
        ON DELETE CASCADE ON UPDATE CASCADE,

    -- Indexes
    INDEX idx_plaid_sync_item (item_id),
    INDEX idx_plaid_sync_status (status),
    INDEX idx_plaid_sync_started (started_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- TABLE: plaid_link_tokens
-- ============================================================================
-- Temporary storage for Plaid Link tokens.
-- These are short-lived tokens used during the account linking flow.
-- Tokens expire after 4 hours (Plaid's limit).
-- ============================================================================
CREATE TABLE IF NOT EXISTS plaid_link_tokens (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Token
    link_token VARCHAR(500) NOT NULL UNIQUE,

    -- Token metadata
    user_id VARCHAR(100) DEFAULT 'default',

    -- What this token is for
    purpose ENUM(
        'link',             -- New account linking
        'update'            -- Update existing Item (re-auth)
    ) NOT NULL DEFAULT 'link',

    -- For update mode, which Item
    update_item_id VARCHAR(255),

    -- Expiration
    expires_at DATETIME NOT NULL,

    -- Status
    status ENUM(
        'active',           -- Ready to use
        'used',             -- Already used
        'expired'           -- Expired
    ) DEFAULT 'active',

    -- Metadata
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_plaid_link_tokens_user (user_id),
    INDEX idx_plaid_link_tokens_status (status),
    INDEX idx_plaid_link_tokens_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;


-- ============================================================================
-- STORED PROCEDURES
-- ============================================================================

-- Procedure to clean up expired link tokens
DELIMITER //
CREATE PROCEDURE IF NOT EXISTS cleanup_expired_link_tokens()
BEGIN
    UPDATE plaid_link_tokens
    SET status = 'expired'
    WHERE expires_at < NOW() AND status = 'active';

    -- Delete tokens older than 7 days
    DELETE FROM plaid_link_tokens
    WHERE created_at < DATE_SUB(NOW(), INTERVAL 7 DAY);
END //
DELIMITER ;

-- Procedure to get sync statistics for an Item
DELIMITER //
CREATE PROCEDURE IF NOT EXISTS get_item_sync_stats(IN p_item_id VARCHAR(255))
BEGIN
    SELECT
        COUNT(*) as total_syncs,
        SUM(CASE WHEN status = 'success' THEN 1 ELSE 0 END) as successful_syncs,
        SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_syncs,
        SUM(transactions_added) as total_transactions_added,
        MAX(completed_at) as last_sync,
        AVG(duration_ms) as avg_sync_duration_ms
    FROM plaid_sync_history
    WHERE item_id = p_item_id;
END //
DELIMITER ;


-- ============================================================================
-- VIEWS
-- ============================================================================

-- View: Active accounts with balance and status
CREATE OR REPLACE VIEW v_plaid_accounts_summary AS
SELECT
    pa.id,
    pa.account_id,
    pa.name,
    pa.official_name,
    pa.mask,
    pa.type,
    pa.subtype,
    pa.balance_current,
    pa.balance_available,
    pa.balance_limit,
    pa.balance_currency,
    pa.balance_updated_at,
    pa.sync_enabled,
    pa.default_business_type,
    pi.institution_name,
    pi.institution_logo,
    pi.status as item_status,
    pi.last_successful_sync,
    (SELECT COUNT(*) FROM plaid_transactions pt WHERE pt.account_id = pa.account_id) as transaction_count
FROM plaid_accounts pa
JOIN plaid_items pi ON pa.item_id = pi.item_id
WHERE pi.status != 'revoked';


-- View: Recent Plaid transactions with matching status
CREATE OR REPLACE VIEW v_plaid_recent_transactions AS
SELECT
    pt.id,
    pt.transaction_id,
    pt.account_id,
    pa.name as account_name,
    pa.mask as account_mask,
    pi.institution_name,
    pt.date,
    pt.merchant_name,
    pt.name as description,
    pt.amount,
    pt.iso_currency_code,
    pt.pending,
    pt.business_type,
    pt.processing_status,
    pt.receipt_matched,
    pt.r2_url as receipt_url,
    pt.ai_confidence,
    pt.category_primary,
    pt.category_detailed,
    pt.payment_channel,
    pt.synced_at
FROM plaid_transactions pt
JOIN plaid_accounts pa ON pt.account_id = pa.account_id
JOIN plaid_items pi ON pa.item_id = pi.item_id
ORDER BY pt.date DESC, pt.synced_at DESC;


-- View: Unmatched transactions needing receipts
CREATE OR REPLACE VIEW v_plaid_needs_receipts AS
SELECT
    pt.id,
    pt.transaction_id,
    pt.date,
    pt.merchant_name,
    pt.name as description,
    pt.amount,
    pa.name as account_name,
    pi.institution_name,
    pt.business_type,
    pt.category_primary
FROM plaid_transactions pt
JOIN plaid_accounts pa ON pt.account_id = pa.account_id
JOIN plaid_items pi ON pa.item_id = pi.item_id
WHERE pt.processing_status IN ('new', 'unmatched')
    AND pt.pending = FALSE
    AND pt.amount < 0  -- Expenses only
    AND pt.business_type IN ('Down_Home', 'MCR')  -- Business expenses
ORDER BY pt.date DESC;


-- ============================================================================
-- Add migration record (create table if needed)
-- ============================================================================
CREATE TABLE IF NOT EXISTS migrations (
    id INT AUTO_INCREMENT PRIMARY KEY,
    version INT NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    applied_at DATETIME DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO migrations (version, name, applied_at)
VALUES (3, 'plaid_integration', NOW())
ON DUPLICATE KEY UPDATE applied_at = NOW();

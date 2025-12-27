-- Migration 004: Card Number Tracking
-- Adds card number fields for multi-account sorting and receipt matching

-- Add card tracking to transactions table
ALTER TABLE transactions
ADD COLUMN card_last4 VARCHAR(4) NULL COMMENT 'Last 4 digits of card used',
ADD COLUMN card_network VARCHAR(50) NULL COMMENT 'Visa, Mastercard, Amex, etc.',
ADD COLUMN card_type VARCHAR(50) NULL COMMENT 'credit, debit, etc.',
ADD COLUMN plaid_account_id VARCHAR(255) NULL COMMENT 'Link to plaid_accounts.account_id',
ADD COLUMN plaid_transaction_id VARCHAR(255) NULL COMMENT 'Link to plaid_transactions.transaction_id',
ADD COLUMN bank_name VARCHAR(255) NULL COMMENT 'Bank/institution name',
ADD COLUMN ocr_card_last4 VARCHAR(4) NULL COMMENT 'Card last 4 extracted from receipt OCR',
ADD COLUMN ocr_card_network VARCHAR(50) NULL COMMENT 'Card network from receipt (Visa, MC, etc.)';

-- Add indexes for card-based queries
CREATE INDEX idx_transactions_card_last4 ON transactions(card_last4);
CREATE INDEX idx_transactions_plaid_account ON transactions(plaid_account_id);
CREATE INDEX idx_transactions_plaid_tx ON transactions(plaid_transaction_id);

-- Add card info to plaid_transactions for matching
ALTER TABLE plaid_transactions
ADD COLUMN card_last4 VARCHAR(4) NULL COMMENT 'Last 4 from account mask',
ADD COLUMN card_network VARCHAR(50) NULL COMMENT 'Visa, Mastercard, etc. if available',
ADD COLUMN card_type VARCHAR(50) NULL COMMENT 'credit, debit, etc. from account type';

CREATE INDEX idx_plaid_tx_card ON plaid_transactions(card_last4);

-- Add display name for accounts
ALTER TABLE plaid_accounts
ADD COLUMN card_network VARCHAR(50) NULL COMMENT 'Visa, Mastercard, Amex, etc.',
ADD COLUMN nickname VARCHAR(100) NULL COMMENT 'User-defined friendly name';

-- Add migration tracking
INSERT INTO migrations (name, executed_at)
VALUES ('004_card_number_tracking', NOW())
ON DUPLICATE KEY UPDATE executed_at = NOW();

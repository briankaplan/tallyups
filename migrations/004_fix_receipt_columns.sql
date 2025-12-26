-- Migration: 004_fix_receipt_columns
-- Fix receipt image column standardization
-- Created: 2025-12-26
-- Description: Ensures receipt_image_url column exists and is properly populated

-- ============================================================================
-- ADD MISSING COLUMNS TO INCOMING_RECEIPTS
-- ============================================================================

-- Add receipt_image_url if it doesn't exist (used by incoming_receipts_service.py)
ALTER TABLE incoming_receipts
    ADD COLUMN IF NOT EXISTS receipt_image_url VARCHAR(1000) AFTER r2_url;

-- Add thumbnail_url if it doesn't exist
ALTER TABLE incoming_receipts
    ADD COLUMN IF NOT EXISTS thumbnail_url VARCHAR(1000) AFTER receipt_image_url;

-- ============================================================================
-- SYNC r2_url AND receipt_image_url
-- ============================================================================

-- If receipt_image_url is null but r2_url has value, copy it
UPDATE incoming_receipts
SET receipt_image_url = r2_url
WHERE receipt_image_url IS NULL AND r2_url IS NOT NULL AND r2_url != '';

-- If r2_url is null but receipt_image_url has value, copy it back
UPDATE incoming_receipts
SET r2_url = receipt_image_url
WHERE r2_url IS NULL AND receipt_image_url IS NOT NULL AND receipt_image_url != '';

-- ============================================================================
-- FIX TRANSACTIONS TABLE
-- ============================================================================

-- Ensure r2_url column exists on transactions
ALTER TABLE transactions
    ADD COLUMN IF NOT EXISTS r2_url VARCHAR(1000) AFTER receipt_file;

-- Copy receipt_file to r2_url if r2_url is empty but receipt_file looks like a URL
UPDATE transactions
SET r2_url = receipt_file
WHERE (r2_url IS NULL OR r2_url = '')
  AND receipt_file LIKE 'http%';

-- ============================================================================
-- ADD INDEXES FOR FASTER LOOKUPS
-- ============================================================================

CREATE INDEX IF NOT EXISTS idx_incoming_receipt_image ON incoming_receipts(receipt_image_url(100));
CREATE INDEX IF NOT EXISTS idx_transactions_r2_url ON transactions(r2_url(100));

-- ============================================================================
-- RECEIPT FAVORITES TABLE (for favorite counts)
-- Matches existing endpoint schema: receipt_type + receipt_id
-- ============================================================================

CREATE TABLE IF NOT EXISTS receipt_favorites (
    id INT AUTO_INCREMENT PRIMARY KEY,
    receipt_type VARCHAR(20) NOT NULL,       -- 'transaction', 'incoming', 'metadata'
    receipt_id INT NOT NULL,
    priority INT DEFAULT 0,
    note TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_receipt (receipt_type, receipt_id),
    INDEX idx_receipt_id (receipt_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- RECEIPT TAG ASSIGNMENTS TABLE (for tag counts)
-- ============================================================================

CREATE TABLE IF NOT EXISTS receipt_tag_assignments (
    id INT AUTO_INCREMENT PRIMARY KEY,
    receipt_type VARCHAR(20) NOT NULL,       -- 'transaction', 'incoming'
    receipt_id INT NOT NULL,
    tag_id INT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    UNIQUE KEY uk_receipt_tag (receipt_type, receipt_id, tag_id),
    INDEX idx_receipt (receipt_type, receipt_id),
    INDEX idx_tag (tag_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- RECEIPT DUPLICATES TABLE (for duplicate detection)
-- ============================================================================

CREATE TABLE IF NOT EXISTS receipt_duplicates (
    id INT AUTO_INCREMENT PRIMARY KEY,
    original_transaction_id INT NOT NULL,
    duplicate_transaction_id INT NOT NULL,
    similarity_score DECIMAL(5,4) DEFAULT 0,
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved BOOLEAN DEFAULT FALSE,
    resolution VARCHAR(50),  -- 'keep_original', 'keep_duplicate', 'merge', 'both_valid'
    resolved_at TIMESTAMP,

    UNIQUE KEY uk_duplicate_pair (original_transaction_id, duplicate_transaction_id),
    INDEX idx_original (original_transaction_id),
    INDEX idx_duplicate (duplicate_transaction_id),
    INDEX idx_resolved (resolved)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

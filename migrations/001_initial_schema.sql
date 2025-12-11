-- Migration: 001_initial_schema
-- ReceiptAI MySQL Database Schema
-- Created: 2025-11-24
-- Description: Initial database schema for ReceiptAI production deployment

-- ============================================================================
-- TRANSACTIONS TABLE
-- Main table storing all financial transactions from Chase exports
-- ============================================================================
CREATE TABLE IF NOT EXISTS transactions (
    _index INT PRIMARY KEY,  -- Original CSV row index, used as unique identifier

    -- Chase/Bank Data (imported from CSV)
    chase_date DATE,
    chase_description VARCHAR(500),
    chase_amount DECIMAL(10,2),
    chase_category VARCHAR(100),
    chase_type VARCHAR(50),

    -- Receipt Association
    receipt_file VARCHAR(500),           -- Path/URL to receipt file
    receipt_source VARCHAR(50),          -- Source: 'gmail', 'scan', 'manual', 'imessage'

    -- Business Classification
    business_type VARCHAR(50),           -- 'down_home', 'mcr', 'personal'
    notes TEXT,                          -- User notes

    -- AI Matching Results
    ai_note TEXT,                        -- AI-generated note about the match
    ai_confidence INT,                   -- Match confidence 0-100
    ai_receipt_merchant VARCHAR(255),    -- AI-extracted merchant from receipt
    ai_receipt_date VARCHAR(50),         -- AI-extracted date from receipt
    ai_receipt_total VARCHAR(50),        -- AI-extracted total from receipt

    -- Verification Status
    verification_status VARCHAR(20) DEFAULT 'pending',  -- 'pending', 'verified', 'mismatch', 'needs_review'
    verified_by VARCHAR(50),             -- 'gemini', 'llama', 'llava', 'manual'
    verification_date TIMESTAMP,

    -- Review Status
    review_status VARCHAR(50),           -- 'needs_review', 'approved', 'rejected', 'pending'

    -- Smart Notes
    smart_note TEXT,                     -- AI-generated contextual note
    smart_note_updated TIMESTAMP,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes defined below
    INDEX idx_chase_date (chase_date),
    INDEX idx_chase_description (chase_description(100)),
    INDEX idx_chase_amount (chase_amount),
    INDEX idx_business_type (business_type),
    INDEX idx_review_status (review_status),
    INDEX idx_verification_status (verification_status),
    INDEX idx_receipt_file (receipt_file(100))
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- INCOMING RECEIPTS TABLE
-- Stores receipts from Gmail, scans, and other sources before matching
-- ============================================================================
CREATE TABLE IF NOT EXISTS incoming_receipts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Receipt Source Information
    source VARCHAR(50) NOT NULL,         -- 'gmail', 'scan', 'manual', 'imessage'
    source_id VARCHAR(255),              -- Gmail message ID, scan UUID, etc.
    gmail_account VARCHAR(100),          -- Gmail account that received the email

    -- Receipt File
    original_filename VARCHAR(500),
    r2_key VARCHAR(500),                 -- Cloudflare R2 storage key
    r2_url VARCHAR(1000),                -- Public URL to receipt
    file_type VARCHAR(20),               -- 'image/jpeg', 'image/png', 'application/pdf'
    file_size INT,

    -- OCR/AI Extracted Data
    ocr_merchant VARCHAR(255),
    ocr_date DATE,
    ocr_total DECIMAL(10,2),
    ocr_raw_text TEXT,
    ocr_confidence INT,
    ocr_provider VARCHAR(50),            -- 'gemini', 'openai', 'tesseract'

    -- Email Metadata (for Gmail receipts)
    email_subject VARCHAR(500),
    email_from VARCHAR(255),
    email_date TIMESTAMP,

    -- Matching Status
    status VARCHAR(50) DEFAULT 'pending',  -- 'pending', 'matched', 'no_match', 'duplicate', 'ignored'
    matched_transaction_id INT,          -- FK to transactions._index
    match_confidence INT,
    match_method VARCHAR(50),            -- 'exact', 'fuzzy', 'manual', 'ai'

    -- Processing Status
    processed BOOLEAN DEFAULT FALSE,
    processed_at TIMESTAMP,
    error_message TEXT,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_source (source),
    INDEX idx_gmail_account (gmail_account),
    INDEX idx_status (status),
    INDEX idx_ocr_merchant (ocr_merchant),
    INDEX idx_ocr_date (ocr_date),
    INDEX idx_ocr_total (ocr_total),
    INDEX idx_matched_transaction (matched_transaction_id),
    INDEX idx_processed (processed),
    INDEX idx_email_date (email_date),

    -- Foreign key (soft - transactions may not exist yet)
    -- FOREIGN KEY (matched_transaction_id) REFERENCES transactions(_index) ON DELETE SET NULL

    UNIQUE KEY uk_source_id (source, source_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- MERCHANTS TABLE
-- Stores merchant information for consistent categorization
-- ============================================================================
CREATE TABLE IF NOT EXISTS merchants (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Merchant Identity
    name VARCHAR(255) NOT NULL,
    canonical_name VARCHAR(255),         -- Standardized name
    aliases JSON,                        -- Array of alternative names

    -- Business Classification
    default_business_type VARCHAR(50),   -- Default classification for this merchant
    category VARCHAR(100),               -- Merchant category

    -- Contact Information
    email_domains JSON,                  -- Array of email domains for this merchant

    -- Metadata
    transaction_count INT DEFAULT 0,
    total_amount DECIMAL(12,2) DEFAULT 0,
    last_transaction_date DATE,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_name (name),
    INDEX idx_canonical_name (canonical_name),
    INDEX idx_default_business_type (default_business_type),

    UNIQUE KEY uk_canonical_name (canonical_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CONTACTS TABLE
-- Stores contacts for person/business association
-- ============================================================================
CREATE TABLE IF NOT EXISTS contacts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Contact Identity
    name VARCHAR(255) NOT NULL,
    email VARCHAR(255),
    phone VARCHAR(50),

    -- Business Association
    business_type VARCHAR(50),           -- 'down_home', 'mcr', 'personal'
    company VARCHAR(255),
    role VARCHAR(100),

    -- Source
    source VARCHAR(50),                  -- 'google', 'manual', 'imessage'
    source_id VARCHAR(255),

    -- Metadata
    notes TEXT,
    tags JSON,

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_name (name),
    INDEX idx_email (email),
    INDEX idx_business_type (business_type),

    UNIQUE KEY uk_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- EXPENSE REPORTS TABLE
-- Stores generated expense reports
-- ============================================================================
CREATE TABLE IF NOT EXISTS expense_reports (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Report Identity
    name VARCHAR(255) NOT NULL,
    business_type VARCHAR(50) NOT NULL,

    -- Date Range
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,

    -- Report Data
    transaction_ids JSON,                -- Array of transaction _index values
    total_amount DECIMAL(12,2),
    transaction_count INT,

    -- Export Information
    export_format VARCHAR(20),           -- 'pdf', 'csv', 'xlsx'
    export_url VARCHAR(1000),

    -- Status
    status VARCHAR(50) DEFAULT 'draft',  -- 'draft', 'final', 'submitted', 'approved'
    submitted_at TIMESTAMP,
    approved_at TIMESTAMP,
    approved_by VARCHAR(100),

    -- Metadata
    notes TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_business_type (business_type),
    INDEX idx_date_range (start_date, end_date),
    INDEX idx_status (status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- OCR CACHE TABLE
-- Caches OCR results to avoid re-processing
-- ============================================================================
CREATE TABLE IF NOT EXISTS ocr_cache (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- File Identity
    file_hash VARCHAR(64) NOT NULL,      -- SHA-256 of file content
    file_path VARCHAR(500),
    r2_key VARCHAR(500),

    -- OCR Results
    provider VARCHAR(50) NOT NULL,       -- 'gemini', 'openai', 'tesseract'
    merchant VARCHAR(255),
    receipt_date DATE,
    total DECIMAL(10,2),
    raw_text TEXT,
    confidence INT,

    -- Metadata
    processing_time_ms INT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_file_hash (file_hash),
    INDEX idx_provider (provider),

    UNIQUE KEY uk_file_hash_provider (file_hash, provider)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- AUDIT LOG TABLE
-- Tracks all changes for compliance and debugging
-- ============================================================================
CREATE TABLE IF NOT EXISTS audit_log (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    -- Event Information
    event_type VARCHAR(50) NOT NULL,     -- 'create', 'update', 'delete', 'match', 'verify'
    table_name VARCHAR(50) NOT NULL,
    record_id VARCHAR(50) NOT NULL,

    -- Change Details
    old_values JSON,
    new_values JSON,

    -- Context
    user_id VARCHAR(100),
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_event_type (event_type),
    INDEX idx_table_name (table_name),
    INDEX idx_record_id (record_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

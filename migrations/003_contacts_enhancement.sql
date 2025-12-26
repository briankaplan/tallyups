-- Migration: 003_contacts_enhancement
-- Enhanced Contacts Schema with Gmail Integration
-- Created: 2025-12-26
-- Description: Adds relationship tracking, Gmail integration, sync conflict management

-- ============================================================================
-- ENHANCE CONTACTS TABLE
-- Add relationship intelligence and enrichment fields
-- ============================================================================
ALTER TABLE contacts
    ADD COLUMN IF NOT EXISTS title VARCHAR(100) AFTER role,
    ADD COLUMN IF NOT EXISTS linkedin_url VARCHAR(500) AFTER source_id,
    ADD COLUMN IF NOT EXISTS avatar_url VARCHAR(500) AFTER linkedin_url,
    ADD COLUMN IF NOT EXISTS relationship_score INT DEFAULT 50 AFTER avatar_url,
    ADD COLUMN IF NOT EXISTS last_interaction TIMESTAMP AFTER relationship_score,
    ADD COLUMN IF NOT EXISTS interaction_count INT DEFAULT 0 AFTER last_interaction,
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) DEFAULT 'medium' AFTER interaction_count,
    ADD COLUMN IF NOT EXISTS category VARCHAR(100) AFTER priority,
    ADD COLUMN IF NOT EXISTS gmail_thread_count INT DEFAULT 0 AFTER category,
    ADD COLUMN IF NOT EXISTS last_email_date TIMESTAMP AFTER gmail_thread_count;

-- Add indexes for new columns
CREATE INDEX IF NOT EXISTS idx_relationship_score ON contacts(relationship_score);
CREATE INDEX IF NOT EXISTS idx_last_interaction ON contacts(last_interaction);
CREATE INDEX IF NOT EXISTS idx_priority ON contacts(priority);

-- ============================================================================
-- GMAIL RECEIPTS TABLE
-- Tracks receipts extracted from Gmail before matching
-- ============================================================================
CREATE TABLE IF NOT EXISTS gmail_receipts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Gmail Identity
    gmail_id VARCHAR(255) NOT NULL,           -- Gmail message ID
    account_email VARCHAR(255) NOT NULL,      -- Which Gmail account
    thread_id VARCHAR(255),                   -- Gmail thread ID

    -- Email Details
    subject VARCHAR(500),
    sender_email VARCHAR(255),
    sender_name VARCHAR(255),
    received_date TIMESTAMP,
    body_preview TEXT,

    -- Attachment Info
    has_attachment BOOLEAN DEFAULT FALSE,
    attachment_filename VARCHAR(255),
    attachment_url VARCHAR(1000),
    attachment_type VARCHAR(50),

    -- OCR/Extraction Results
    extracted_merchant VARCHAR(255),
    extracted_amount DECIMAL(10,2),
    extracted_date DATE,
    extraction_confidence INT,
    ocr_processed BOOLEAN DEFAULT FALSE,
    ocr_raw_text TEXT,

    -- Matching Status
    status VARCHAR(50) DEFAULT 'pending',     -- 'pending', 'matched', 'rejected', 'duplicate'
    matched_transaction_id INT,
    matched_at TIMESTAMP,

    -- Contact Association
    contact_id INT,                           -- FK to contacts.id

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_gmail_id (gmail_id),
    INDEX idx_account_email (account_email),
    INDEX idx_sender_email (sender_email),
    INDEX idx_status (status),
    INDEX idx_received_date (received_date),
    INDEX idx_contact_id (contact_id),

    UNIQUE KEY uk_gmail_id (gmail_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CONTACT INTERACTIONS TABLE
-- Track all interactions with contacts (emails, calls, meetings, expenses)
-- ============================================================================
CREATE TABLE IF NOT EXISTS contact_interactions (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Contact Reference
    contact_id INT NOT NULL,

    -- Interaction Details
    interaction_type VARCHAR(50) NOT NULL,    -- 'email', 'call', 'meeting', 'expense', 'text'
    interaction_date TIMESTAMP NOT NULL,
    subject VARCHAR(500),
    notes TEXT,

    -- Source Reference
    source_type VARCHAR(50),                  -- 'gmail', 'calendar', 'transaction', 'manual'
    source_id VARCHAR(255),                   -- Gmail ID, Calendar Event ID, Transaction ID

    -- Sentiment/Quality
    sentiment VARCHAR(20),                    -- 'positive', 'neutral', 'negative'
    importance VARCHAR(20) DEFAULT 'normal',  -- 'high', 'normal', 'low'

    -- Financial (for expense-type interactions)
    amount DECIMAL(10,2),
    transaction_id INT,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_contact_id (contact_id),
    INDEX idx_interaction_type (interaction_type),
    INDEX idx_interaction_date (interaction_date),
    INDEX idx_source (source_type, source_id),

    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CONTACT SYNC CONFLICTS TABLE
-- Manages conflicts when syncing from multiple sources
-- ============================================================================
CREATE TABLE IF NOT EXISTS contact_conflicts (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Contact Reference
    contact_id INT NOT NULL,

    -- Conflict Details
    source VARCHAR(50) NOT NULL,              -- 'google', 'apple', 'linkedin'
    field_name VARCHAR(50) NOT NULL,          -- 'email', 'phone', 'company', etc.
    local_value TEXT,
    remote_value TEXT,

    -- Resolution
    resolved BOOLEAN DEFAULT FALSE,
    resolution VARCHAR(20),                   -- 'local', 'remote', 'manual', 'merged'
    resolved_value TEXT,
    resolved_at TIMESTAMP,
    resolved_by VARCHAR(100),

    -- Metadata
    detected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_contact_id (contact_id),
    INDEX idx_resolved (resolved),
    INDEX idx_source (source),

    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CONTACT MERGE LOG TABLE
-- Audit trail for merged contacts
-- ============================================================================
CREATE TABLE IF NOT EXISTS contact_merge_log (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- Merge Details
    primary_contact_id INT NOT NULL,
    merged_contact_ids JSON NOT NULL,         -- Array of IDs that were merged
    merge_strategy VARCHAR(50) NOT NULL,      -- 'keep_primary', 'combine', 'manual'

    -- Before/After Data
    merged_data JSON,                         -- Snapshot of merged contact data

    -- Metadata
    merged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    merged_by VARCHAR(100),

    -- Indexes
    INDEX idx_primary_contact (primary_contact_id),
    INDEX idx_merged_at (merged_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CONTACT EMAIL THREADS TABLE
-- Links contacts to their email threads for quick lookup
-- ============================================================================
CREATE TABLE IF NOT EXISTS contact_email_threads (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- References
    contact_id INT NOT NULL,
    gmail_account VARCHAR(255) NOT NULL,
    thread_id VARCHAR(255) NOT NULL,

    -- Thread Summary
    subject VARCHAR(500),
    message_count INT DEFAULT 1,
    last_message_date TIMESTAMP,
    has_receipt BOOLEAN DEFAULT FALSE,

    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_contact_id (contact_id),
    INDEX idx_thread_id (thread_id),
    INDEX idx_last_message (last_message_date),

    UNIQUE KEY uk_contact_thread (contact_id, thread_id),
    FOREIGN KEY (contact_id) REFERENCES contacts(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

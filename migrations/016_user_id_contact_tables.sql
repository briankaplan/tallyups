-- Migration 016: Add user_id to contact-related tables
-- These tables were missing user_id for proper multi-tenant isolation

-- ============================================================================
-- GMAIL RECEIPTS TABLE
-- ============================================================================
ALTER TABLE gmail_receipts
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_gmail_receipts_user_id ON gmail_receipts(user_id);

-- Migrate existing data to admin user
UPDATE gmail_receipts
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- CONTACT INTERACTIONS TABLE
-- ============================================================================
ALTER TABLE contact_interactions
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_contact_interactions_user_id ON contact_interactions(user_id);

-- Migrate existing data to admin user
UPDATE contact_interactions
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- CONTACT CONFLICTS TABLE
-- ============================================================================
ALTER TABLE contact_conflicts
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_contact_conflicts_user_id ON contact_conflicts(user_id);

-- Migrate existing data to admin user
UPDATE contact_conflicts
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- CONTACT MERGE LOG TABLE
-- ============================================================================
ALTER TABLE contact_merge_log
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_contact_merge_log_user_id ON contact_merge_log(user_id);

-- Migrate existing data to admin user
UPDATE contact_merge_log
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- CONTACT EMAIL THREADS TABLE
-- ============================================================================
ALTER TABLE contact_email_threads
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_contact_email_threads_user_id ON contact_email_threads(user_id);

-- Migrate existing data to admin user
UPDATE contact_email_threads
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- CALENDAR PREFERENCES TABLE (new - replaces file-based storage)
-- ============================================================================
CREATE TABLE IF NOT EXISTS calendar_preferences (
    user_id CHAR(36) PRIMARY KEY,
    enabled_calendars JSON DEFAULT NULL,
    default_calendar VARCHAR(255) DEFAULT NULL,
    sync_frequency_minutes INT DEFAULT 30,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    CONSTRAINT fk_calendar_preferences_user
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- Create index for quick lookups
CREATE INDEX idx_calendar_preferences_updated ON calendar_preferences(updated_at);

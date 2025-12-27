-- Migration: 013_migrate_to_admin
-- Migrate all existing data to admin user account
-- Created: 2025-12-26
-- Description: Create admin user and assign all existing data to admin

-- ============================================================================
-- CREATE ADMIN USER
-- ============================================================================
INSERT INTO users (
    id,
    email,
    name,
    role,
    is_active,
    default_business_type,
    onboarding_completed,
    created_at
) VALUES (
    'admin-00000000-0000-0000-0000-000000000000',
    'admin@tallyups.com',
    'Admin',
    'admin',
    TRUE,
    'Personal',
    TRUE,
    NOW()
) ON DUPLICATE KEY UPDATE
    role = 'admin',
    is_active = TRUE;

-- ============================================================================
-- MIGRATE EXISTING DATA TO ADMIN USER
-- ============================================================================

-- Update transactions
UPDATE transactions
SET user_id = 'admin-00000000-0000-0000-0000-000000000000'
WHERE user_id IS NULL;

-- Update incoming_receipts
UPDATE incoming_receipts
SET user_id = 'admin-00000000-0000-0000-0000-000000000000'
WHERE user_id IS NULL;

-- Update merchants (make admin's merchants shared by keeping user_id NULL for canonical ones)
-- User-specific merchant overrides will have user_id set

-- Update contacts
UPDATE contacts
SET user_id = 'admin-00000000-0000-0000-0000-000000000000'
WHERE user_id IS NULL;

-- Update expense_reports
UPDATE expense_reports
SET user_id = 'admin-00000000-0000-0000-0000-000000000000'
WHERE user_id IS NULL;

-- Update plaid_items if exists (CRITICAL - this holds your bank connections)
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'plaid_items'
);

SET @sql = IF(@table_exists > 0,
    'UPDATE plaid_items SET user_id = ''admin-00000000-0000-0000-0000-000000000000'' WHERE user_id IS NULL OR user_id = ''default''',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Update plaid_accounts if exists
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'plaid_accounts'
);

SET @sql = IF(@table_exists > 0,
    'UPDATE plaid_accounts SET user_id = ''admin-00000000-0000-0000-0000-000000000000'' WHERE user_id IS NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Update plaid_institutions if exists
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'plaid_institutions'
);

SET @sql = IF(@table_exists > 0,
    'UPDATE plaid_institutions SET user_id = ''admin-00000000-0000-0000-0000-000000000000'' WHERE user_id IS NULL',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================================================
-- ADD FOREIGN KEY CONSTRAINTS
-- ============================================================================
-- Now that all data has user_id set, we can add foreign keys
-- Note: These are optional - removing them allows for easier data management

-- For transactions - using soft constraint (no actual FK to avoid issues with imports)
-- ALTER TABLE transactions
-- ADD CONSTRAINT fk_transactions_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- For incoming_receipts
-- ALTER TABLE incoming_receipts
-- ADD CONSTRAINT fk_incoming_user FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE;

-- ============================================================================
-- MAKE USER_ID NOT NULL (optional - after verification)
-- ============================================================================
-- Uncomment these after verifying all data has been migrated:
-- ALTER TABLE transactions MODIFY COLUMN user_id CHAR(36) NOT NULL;
-- ALTER TABLE incoming_receipts MODIFY COLUMN user_id CHAR(36) NOT NULL;
-- ALTER TABLE contacts MODIFY COLUMN user_id CHAR(36) NOT NULL;
-- ALTER TABLE expense_reports MODIFY COLUMN user_id CHAR(36) NOT NULL;

-- ============================================================================
-- VERIFICATION QUERIES (run manually to verify migration)
-- ============================================================================
-- SELECT 'transactions' as tbl, COUNT(*) as total, SUM(user_id IS NULL) as null_count FROM transactions
-- UNION ALL
-- SELECT 'incoming_receipts', COUNT(*), SUM(user_id IS NULL) FROM incoming_receipts
-- UNION ALL
-- SELECT 'contacts', COUNT(*), SUM(user_id IS NULL) FROM contacts
-- UNION ALL
-- SELECT 'expense_reports', COUNT(*), SUM(user_id IS NULL) FROM expense_reports;

-- ============================================================================
-- CREATE DEFAULT USER SETTINGS TABLE
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_settings (
    id INT AUTO_INCREMENT PRIMARY KEY,

    user_id CHAR(36) NOT NULL,

    -- Display Preferences
    theme ENUM('dark', 'light', 'system') DEFAULT 'dark',
    date_format VARCHAR(20) DEFAULT 'YYYY-MM-DD',
    currency VARCHAR(3) DEFAULT 'USD',

    -- Notification Preferences
    notifications_enabled BOOLEAN DEFAULT TRUE,
    email_notifications BOOLEAN DEFAULT TRUE,
    push_notifications BOOLEAN DEFAULT TRUE,
    weekly_summary_enabled BOOLEAN DEFAULT TRUE,

    -- Scanner Preferences
    auto_upload BOOLEAN DEFAULT TRUE,
    save_to_photos BOOLEAN DEFAULT FALSE,
    high_quality_mode BOOLEAN DEFAULT TRUE,

    -- Privacy
    analytics_enabled BOOLEAN DEFAULT TRUE,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    UNIQUE KEY uk_user_settings (user_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create settings for admin user
INSERT INTO user_settings (user_id)
VALUES ('admin-00000000-0000-0000-0000-000000000000')
ON DUPLICATE KEY UPDATE updated_at = NOW();

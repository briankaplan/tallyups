-- Migration: 015_add_user_id_to_reports
-- Add user_id column to reports table for multi-tenancy
-- Created: 2025-12-27
-- Description: The reports table was missed in migration 012 which only added user_id to expense_reports

-- ============================================================================
-- REPORTS TABLE - Add user_id if not exists
-- ============================================================================

-- Check if reports table exists and add user_id
SET @table_exists = (
    SELECT COUNT(*)
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
    AND table_name = 'reports'
);

SET @column_exists = (
    SELECT COUNT(*)
    FROM information_schema.columns
    WHERE table_schema = DATABASE()
    AND table_name = 'reports'
    AND column_name = 'user_id'
);

-- Only add column if table exists and column doesn't
SET @sql = IF(@table_exists > 0 AND @column_exists = 0,
    'ALTER TABLE reports ADD COLUMN user_id CHAR(36) NULL AFTER report_id',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add index for user_id queries
SET @index_exists = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
    AND table_name = 'reports'
    AND index_name = 'idx_reports_user_id'
);

SET @sql = IF(@table_exists > 0 AND @index_exists = 0,
    'CREATE INDEX idx_reports_user_id ON reports(user_id)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add compound index for user + status queries
SET @index_exists2 = (
    SELECT COUNT(*)
    FROM information_schema.statistics
    WHERE table_schema = DATABASE()
    AND table_name = 'reports'
    AND index_name = 'idx_reports_user_status'
);

SET @sql = IF(@table_exists > 0 AND @index_exists2 = 0,
    'CREATE INDEX idx_reports_user_status ON reports(user_id, status)',
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================================================
-- MIGRATE EXISTING DATA
-- ============================================================================
-- Set existing reports to admin user if we have one
SET @admin_id = (
    SELECT id FROM users WHERE role = 'admin' LIMIT 1
);

SET @sql = IF(@table_exists > 0 AND @admin_id IS NOT NULL,
    CONCAT('UPDATE reports SET user_id = ''', @admin_id, ''' WHERE user_id IS NULL'),
    'SELECT 1'
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

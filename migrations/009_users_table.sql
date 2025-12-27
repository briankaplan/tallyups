-- Migration: 009_users_table
-- Create users table for multi-tenant support
-- Created: 2025-12-26
-- Description: Core users table with Sign in with Apple support

-- ============================================================================
-- USERS TABLE
-- Core user account information
-- ============================================================================
CREATE TABLE IF NOT EXISTS users (
    id CHAR(36) PRIMARY KEY,                 -- UUID format

    -- Apple Sign In
    apple_user_id VARCHAR(255) UNIQUE,       -- Apple's unique user identifier
    apple_email VARCHAR(255),                -- Email from Apple (may be private relay)

    -- User Profile
    email VARCHAR(255),                      -- User's actual email (may differ from Apple)
    name VARCHAR(255),                       -- Display name

    -- Access Control
    role ENUM('user', 'admin') DEFAULT 'user',
    is_active BOOLEAN DEFAULT TRUE,

    -- Preferences
    default_business_type VARCHAR(50) DEFAULT 'Personal',
    timezone VARCHAR(50) DEFAULT 'America/Chicago',

    -- Onboarding
    onboarding_completed BOOLEAN DEFAULT FALSE,
    onboarding_step INT DEFAULT 0,

    -- Storage Quota (for future use)
    storage_used_bytes BIGINT DEFAULT 0,
    storage_limit_bytes BIGINT DEFAULT 10737418240,  -- 10GB default

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    last_login_at TIMESTAMP,
    deleted_at TIMESTAMP NULL,               -- Soft delete for GDPR

    -- Indexes
    INDEX idx_apple_user_id (apple_user_id),
    INDEX idx_email (email),
    INDEX idx_role (role),
    INDEX idx_is_active (is_active),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- ADMIN USER PLACEHOLDER
-- Will be populated in migration 013
-- ============================================================================
-- The admin user ID will be: 'admin-00000000-0000-0000-0000-000000000000'
-- This ensures existing data can be migrated without foreign key violations

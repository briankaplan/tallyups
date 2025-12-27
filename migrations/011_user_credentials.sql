-- Migration: 011_user_credentials
-- Create user credentials table for third-party integrations
-- Created: 2025-12-26
-- Description: Store encrypted OAuth tokens and API keys per user

-- ============================================================================
-- USER CREDENTIALS TABLE
-- Stores encrypted credentials for third-party services
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_credentials (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- User Association
    user_id CHAR(36) NOT NULL,

    -- Service Identity
    service_type ENUM(
        'gmail',
        'google_calendar',
        'taskade',
        'openai',
        'gemini',
        'anthropic',
        'plaid'
    ) NOT NULL,

    -- Account Identity (for services that support multiple accounts)
    account_email VARCHAR(255),              -- Gmail account, etc.
    account_name VARCHAR(255),               -- Display name

    -- OAuth Tokens (encrypted at rest)
    access_token TEXT,                       -- Encrypted
    refresh_token TEXT,                      -- Encrypted
    token_type VARCHAR(50) DEFAULT 'Bearer',
    token_expires_at DATETIME,

    -- API Keys (encrypted at rest)
    api_key VARCHAR(500),                    -- Encrypted

    -- Service-Specific Config
    workspace_id VARCHAR(255),               -- Taskade workspace
    project_id VARCHAR(255),                 -- Taskade project
    folder_id VARCHAR(255),                  -- Taskade folder
    scopes JSON,                             -- OAuth scopes granted
    metadata JSON,                           -- Additional service-specific data

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP,
    last_error TEXT,
    error_count INT DEFAULT 0,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    -- Foreign Key
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- Indexes
    INDEX idx_user_id (user_id),
    INDEX idx_service_type (service_type),
    INDEX idx_account_email (account_email),
    INDEX idx_is_active (is_active),

    -- One credential per service+account per user
    UNIQUE KEY uk_user_service_account (user_id, service_type, account_email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- OAUTH STATES TABLE
-- Temporary storage for OAuth flow state parameters
-- ============================================================================
CREATE TABLE IF NOT EXISTS oauth_states (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- User Association
    user_id CHAR(36) NOT NULL,

    -- OAuth State
    state VARCHAR(64) NOT NULL UNIQUE,       -- Random state parameter
    service_type ENUM(
        'gmail',
        'google_calendar',
        'taskade'
    ) NOT NULL,

    -- Redirect Info
    redirect_uri VARCHAR(500),

    -- Expiration
    expires_at TIMESTAMP NOT NULL,
    used BOOLEAN DEFAULT FALSE,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Foreign Key
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- Indexes
    INDEX idx_state (state),
    INDEX idx_user_id (user_id),
    INDEX idx_expires_at (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- CLEANUP EVENT
-- Auto-delete expired OAuth states
-- ============================================================================
CREATE EVENT IF NOT EXISTS cleanup_oauth_states
ON SCHEDULE EVERY 1 HOUR
DO DELETE FROM oauth_states WHERE expires_at < NOW();

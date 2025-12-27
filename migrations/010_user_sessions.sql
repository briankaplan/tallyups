-- Migration: 010_user_sessions
-- Create user sessions table for JWT refresh token management
-- Created: 2025-12-26
-- Description: Track active sessions and refresh tokens per device

-- ============================================================================
-- USER SESSIONS TABLE
-- Stores refresh tokens and device information
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_sessions (
    id INT AUTO_INCREMENT PRIMARY KEY,

    -- User Association
    user_id CHAR(36) NOT NULL,

    -- Session Identity
    device_id VARCHAR(255) NOT NULL,         -- Unique device identifier
    device_name VARCHAR(255),                -- Human-readable device name
    device_type ENUM('ios', 'android', 'web') DEFAULT 'ios',

    -- Tokens
    refresh_token_hash VARCHAR(64) NOT NULL, -- SHA-256 hash of refresh token

    -- Security
    ip_address VARCHAR(45),                  -- IPv4 or IPv6
    user_agent VARCHAR(500),

    -- Push Notifications
    push_token VARCHAR(255),                 -- APNs or FCM token
    push_enabled BOOLEAN DEFAULT TRUE,

    -- Status
    is_active BOOLEAN DEFAULT TRUE,
    last_used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    revoked_at TIMESTAMP NULL,

    -- Foreign Key
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,

    -- Indexes
    INDEX idx_user_id (user_id),
    INDEX idx_device_id (device_id),
    INDEX idx_refresh_token_hash (refresh_token_hash),
    INDEX idx_is_active (is_active),
    INDEX idx_expires_at (expires_at),

    -- Unique constraint: one active session per device per user
    UNIQUE KEY uk_user_device (user_id, device_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- SESSION AUDIT LOG
-- Track login/logout events for security
-- ============================================================================
CREATE TABLE IF NOT EXISTS session_events (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,

    user_id CHAR(36) NOT NULL,
    session_id INT,

    event_type ENUM(
        'login',
        'logout',
        'token_refresh',
        'token_revoked',
        'password_change',
        'account_deleted'
    ) NOT NULL,

    -- Context
    ip_address VARCHAR(45),
    user_agent VARCHAR(500),
    device_id VARCHAR(255),

    -- Additional Data
    metadata JSON,

    -- Timestamp
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,

    -- Indexes
    INDEX idx_user_id (user_id),
    INDEX idx_event_type (event_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

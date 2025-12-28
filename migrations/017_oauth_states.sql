-- Migration: 017_oauth_states.sql
-- Create oauth_states table for Google OAuth flow

CREATE TABLE IF NOT EXISTS oauth_states (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    state VARCHAR(255) NOT NULL UNIQUE,
    service_type VARCHAR(50) NOT NULL,
    redirect_uri VARCHAR(500),
    expires_at DATETIME NOT NULL,
    used BOOLEAN DEFAULT FALSE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_state (state),
    INDEX idx_user (user_id),
    INDEX idx_expires (expires_at)
);

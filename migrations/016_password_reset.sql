-- Migration: 016_password_reset.sql
-- Add password reset functionality

-- Add reset token columns to users table
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token VARCHAR(255) DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_token_expires DATETIME DEFAULT NULL;
ALTER TABLE users ADD COLUMN IF NOT EXISTS reset_attempts INT DEFAULT 0;
ALTER TABLE users ADD COLUMN IF NOT EXISTS last_reset_request DATETIME DEFAULT NULL;

-- Index for quick token lookup
CREATE INDEX IF NOT EXISTS idx_users_reset_token ON users(reset_token);

-- Create password reset log for security auditing
CREATE TABLE IF NOT EXISTS password_reset_log (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id VARCHAR(36) NOT NULL,
    email VARCHAR(255) NOT NULL,
    token_hash VARCHAR(255) NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    status ENUM('requested', 'completed', 'expired', 'invalid') DEFAULT 'requested',
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME DEFAULT NULL,
    INDEX idx_prl_user (user_id),
    INDEX idx_prl_email (email),
    INDEX idx_prl_created (created_at)
);

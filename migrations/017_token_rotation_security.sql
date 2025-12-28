-- Migration 017: Add previous_token_hash for refresh token rotation security
-- This enables detection of token reuse attacks (potential theft)

-- Add column to track the previous refresh token hash
-- When a token is rotated, we store the old hash here
-- If someone tries to use the old token again, we detect it as a reuse attack
ALTER TABLE user_sessions
ADD COLUMN previous_token_hash VARCHAR(64) NULL AFTER refresh_token_hash;

-- Add index for quick lookups during reuse detection
CREATE INDEX idx_user_sessions_previous_token ON user_sessions(previous_token_hash);

-- Add event_data column to session_events for storing additional context
ALTER TABLE session_events
ADD COLUMN event_data JSON NULL AFTER ip_address;

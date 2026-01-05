-- Migration: Add google_user_id column to users table
-- This enables Google Sign In functionality

-- Add google_user_id column (MySQL syntax)
-- Run this only if column doesn't exist:
-- Check: SHOW COLUMNS FROM users LIKE 'google_user_id';
ALTER TABLE users ADD COLUMN google_user_id VARCHAR(255) NULL;

-- Create index for Google user ID lookups
CREATE INDEX idx_users_google_user_id ON users(google_user_id);

-- Migration: 015_demo_account
-- Create demo account for Apple App Store review
-- Created: 2025-12-28
-- Description: Adds password support and creates demo user with sample data

-- ============================================================================
-- ADD PASSWORD HASH COLUMN TO USERS TABLE
-- ============================================================================
-- Note: Run these separately if column already exists (will error but that's OK)

-- Add password_hash column if it doesn't exist
SET @exist := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'password_hash');
SET @sql := IF(@exist = 0, 'ALTER TABLE users ADD COLUMN password_hash VARCHAR(255) NULL AFTER email', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- Add is_demo_account column if it doesn't exist
SET @exist := (SELECT COUNT(*) FROM INFORMATION_SCHEMA.COLUMNS
               WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'users' AND COLUMN_NAME = 'is_demo_account');
SET @sql := IF(@exist = 0, 'ALTER TABLE users ADD COLUMN is_demo_account BOOLEAN DEFAULT FALSE AFTER role', 'SELECT 1');
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- ============================================================================
-- CREATE DEMO USER
-- Email: demo@tallyups.com
-- Password: TallyDemo2025!
-- Password hash (bcrypt): $2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.dLLqEu0RvTLjGy
-- ============================================================================
INSERT INTO users (
    id,
    email,
    name,
    password_hash,
    role,
    is_demo_account,
    is_active,
    default_business_type,
    timezone,
    onboarding_completed,
    created_at
) VALUES (
    'demo-0000-0000-0000-000000000001',
    'demo@tallyups.com',
    'Demo User',
    '$2b$12$LQv3c1yqBWVHxkd0LHAkCOYz6TtxMQJqhN8/X4.dLLqEu0RvTLjGy',
    'user',
    TRUE,
    TRUE,
    'Personal',
    'America/New_York',
    TRUE,
    NOW()
) ON DUPLICATE KEY UPDATE
    password_hash = VALUES(password_hash),
    is_demo_account = TRUE,
    is_active = TRUE;

-- ============================================================================
-- CREATE DEMO TRANSACTIONS
-- Realistic sample data for App Store reviewers to test
-- ============================================================================

-- Clear existing demo transactions first
DELETE FROM transactions WHERE user_id = 'demo-0000-0000-0000-000000000001';

-- Insert demo transactions (last 30 days of realistic expenses)
INSERT INTO transactions (
    _index, user_id, chase_date, chase_description, chase_amount,
    mi_merchant, mi_category, business_type, review_status, notes
) VALUES
-- Week 1: Recent transactions
(90001, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 1 DAY),
 'STARBUCKS STORE 12345', -5.75, 'Starbucks', 'Food & Dining', 'Personal', 'good', 'Morning coffee'),

(90002, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 2 DAY),
 'UBER TRIP ABCD1234', -24.50, 'Uber', 'Transportation', 'Business', 'good', 'Client meeting downtown'),

(90003, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 3 DAY),
 'AMAZON.COM*AB12CD34E', -89.99, 'Amazon', 'Shopping', 'Personal', 'pending', 'Office supplies'),

(90004, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 4 DAY),
 'CHIPOTLE ONLINE', -12.85, 'Chipotle', 'Food & Dining', 'Personal', 'good', 'Lunch'),

(90005, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 5 DAY),
 'SHELL OIL 57442234501', -48.32, 'Shell', 'Gas & Fuel', 'Personal', 'good', 'Gas fill-up'),

-- Week 2
(90006, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 7 DAY),
 'COSTCO WHSE #1234', -156.78, 'Costco', 'Shopping', 'Personal', 'pending', 'Groceries and household'),

(90007, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 8 DAY),
 'NETFLIX.COM', -15.99, 'Netflix', 'Entertainment', 'Personal', 'good', 'Monthly subscription'),

(90008, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 9 DAY),
 'DOORDASH*MCDONALDS', -18.45, 'DoorDash', 'Food & Dining', 'Personal', 'good', 'Dinner delivery'),

(90009, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 10 DAY),
 'ZOOM.US', -14.99, 'Zoom', 'Business Services', 'Business', 'good', 'Video conferencing'),

(90010, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 11 DAY),
 'TARGET 00012345', -67.23, 'Target', 'Shopping', 'Personal', 'pending', NULL),

-- Week 3
(90011, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 14 DAY),
 'WHOLE FOODS MKT', -92.15, 'Whole Foods', 'Groceries', 'Personal', 'good', 'Weekly groceries'),

(90012, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 15 DAY),
 'LYFT *RIDE', -32.00, 'Lyft', 'Transportation', 'Business', 'good', 'Airport pickup'),

(90013, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 16 DAY),
 'APPLE.COM/BILL', -9.99, 'Apple', 'Entertainment', 'Personal', 'good', 'iCloud storage'),

(90014, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 18 DAY),
 'CVS/PHARMACY #1234', -28.45, 'CVS', 'Health', 'Personal', 'good', 'Vitamins'),

(90015, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 20 DAY),
 'SPOTIFY USA', -9.99, 'Spotify', 'Entertainment', 'Personal', 'good', 'Monthly subscription'),

-- Week 4
(90016, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 21 DAY),
 'DELTA AIR LINES', -385.00, 'Delta Airlines', 'Travel', 'Business', 'pending', 'Conference flight'),

(90017, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 22 DAY),
 'MARRIOTT HOTELS', -189.00, 'Marriott', 'Travel', 'Business', 'pending', 'Conference hotel'),

(90018, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 25 DAY),
 'WALGREENS #12345', -15.67, 'Walgreens', 'Health', 'Personal', 'good', NULL),

(90019, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 27 DAY),
 'PANERA BREAD #1234', -14.25, 'Panera Bread', 'Food & Dining', 'Personal', 'good', 'Lunch meeting'),

(90020, 'demo-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 30 DAY),
 'ADOBE *CREATIVE CLD', -54.99, 'Adobe', 'Business Services', 'Business', 'good', 'Creative Cloud subscription');

-- ============================================================================
-- CREATE DEMO RECEIPTS (linked to some transactions)
-- ============================================================================

-- Note: In production, these would have actual r2_url values pointing to sample receipt images
-- For demo, we'll use placeholder URLs that the app can display

UPDATE transactions
SET r2_url = CONCAT('https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev/demo/receipt_', _index, '.jpg'),
    receipt_file = CONCAT('demo_receipt_', _index, '.jpg')
WHERE user_id = 'demo-0000-0000-0000-000000000001'
AND review_status = 'good';

-- ============================================================================
-- CREATE DEMO INCOMING RECEIPTS (pending inbox items)
-- ============================================================================

DELETE FROM incoming_receipts WHERE user_id = 'demo-0000-0000-0000-000000000001';

INSERT INTO incoming_receipts (
    user_id, email_id, gmail_account, subject, from_email,
    merchant, amount, transaction_date,
    status, created_at
) VALUES
('demo-0000-0000-0000-000000000001', 'demo_amazon_001', 'demo@tallyups.com',
 'Your Amazon.com order has shipped', 'receipts@amazon.com',
 'Amazon', 45.99, DATE_SUB(CURDATE(), INTERVAL 1 DAY),
 'pending', NOW()),

('demo-0000-0000-0000-000000000001', 'demo_uber_001', 'demo@tallyups.com',
 'Your trip receipt from Uber', 'no-reply@uber.com',
 'Uber', 18.50, DATE_SUB(CURDATE(), INTERVAL 2 DAY),
 'pending', NOW()),

('demo-0000-0000-0000-000000000001', 'demo_bestbuy_001', 'demo@tallyups.com',
 'Your Best Buy receipt', 'receipts@bestbuy.com',
 'Best Buy', 299.99, DATE_SUB(CURDATE(), INTERVAL 3 DAY),
 'pending', NOW());

-- ============================================================================
-- SUMMARY
-- ============================================================================
-- Demo Account Created:
--   Email: demo@tallyups.com
--   Password: TallyDemo2025!
--
-- Demo Data:
--   - 20 transactions spanning 30 days
--   - Mix of Personal and Business expenses
--   - Various categories (Food, Travel, Shopping, etc.)
--   - Some with receipts attached, some pending
--   - 3 items in receipt inbox

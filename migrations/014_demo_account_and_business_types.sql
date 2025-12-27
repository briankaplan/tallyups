-- Migration: 014_demo_account_and_business_types
-- Create demo account for App Store review and per-user business types
-- Created: 2025-12-26

-- ============================================================================
-- USER BUSINESS TYPES TABLE (Per-User Custom Categories)
-- ============================================================================
CREATE TABLE IF NOT EXISTS user_business_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user_id CHAR(36) NOT NULL,
    name VARCHAR(100) NOT NULL,
    display_name VARCHAR(100) NOT NULL,
    color VARCHAR(7) DEFAULT '#00FF88',  -- Hex color for UI
    icon VARCHAR(50) DEFAULT 'briefcase',  -- SF Symbol name
    is_default BOOLEAN DEFAULT FALSE,
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    UNIQUE KEY uk_user_business_type (user_id, name),
    INDEX idx_user_active (user_id, is_active),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ============================================================================
-- ADMIN USER BUSINESS TYPES (Your specific categories)
-- ============================================================================
INSERT INTO user_business_types (user_id, name, display_name, color, icon, is_default, sort_order)
VALUES
    ('admin-00000000-0000-0000-0000-000000000000', 'Personal', 'Personal', '#00FF88', 'person.fill', TRUE, 1),
    ('admin-00000000-0000-0000-0000-000000000000', 'Down_Home', 'Down Home', '#FF6B6B', 'house.fill', FALSE, 2),
    ('admin-00000000-0000-0000-0000-000000000000', 'Music_City_Rodeo', 'Music City Rodeo', '#4ECDC4', 'music.note', FALSE, 3)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    color = VALUES(color),
    icon = VALUES(icon);

-- ============================================================================
-- DEMO ACCOUNT FOR APP STORE REVIEW
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
    'demo-00000000-0000-0000-0000-000000000001',
    'demo@tallyups.com',
    'App Store Demo',
    'user',
    TRUE,
    'Personal',
    TRUE,
    NOW()
) ON DUPLICATE KEY UPDATE
    name = 'App Store Demo',
    is_active = TRUE;

-- Demo user business types (generic for demo)
INSERT INTO user_business_types (user_id, name, display_name, color, icon, is_default, sort_order)
VALUES
    ('demo-00000000-0000-0000-0000-000000000001', 'Personal', 'Personal', '#00FF88', 'person.fill', TRUE, 1),
    ('demo-00000000-0000-0000-0000-000000000001', 'Business', 'Business', '#4A90D9', 'briefcase.fill', FALSE, 2),
    ('demo-00000000-0000-0000-0000-000000000001', 'Travel', 'Travel', '#F5A623', 'airplane', FALSE, 3)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name);

-- Demo user settings
INSERT INTO user_settings (user_id, theme, notifications_enabled)
VALUES ('demo-00000000-0000-0000-0000-000000000001', 'dark', TRUE)
ON DUPLICATE KEY UPDATE updated_at = NOW();

-- ============================================================================
-- SAMPLE TRANSACTIONS FOR DEMO ACCOUNT
-- ============================================================================
INSERT INTO transactions (
    user_id,
    chase_date,
    chase_description,
    chase_amount,
    business_type,
    category,
    verification_status,
    source,
    created_at
) VALUES
    -- Recent transactions for demo
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 1 DAY), 'STARBUCKS STORE 12345', -5.75, 'Personal', 'Food & Dining', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 2 DAY), 'AMAZON.COM*AMZN.COM/BILL', -47.99, 'Personal', 'Shopping', 'pending', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 3 DAY), 'UBER TRIP NASHVILLE', -24.50, 'Business', 'Transportation', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 4 DAY), 'WHOLE FOODS MARKET', -89.32, 'Personal', 'Groceries', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 5 DAY), 'DELTA AIR LINES', -342.00, 'Travel', 'Travel', 'pending', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 6 DAY), 'MARRIOTT NASHVILLE DT', -189.00, 'Travel', 'Lodging', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 7 DAY), 'OFFICE DEPOT #1234', -156.78, 'Business', 'Office Supplies', 'pending', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 8 DAY), 'NETFLIX.COM', -15.99, 'Personal', 'Entertainment', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 10 DAY), 'CHIPOTLE ONLINE', -12.45, 'Personal', 'Food & Dining', 'verified', 'demo', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', DATE_SUB(CURDATE(), INTERVAL 14 DAY), 'ZOOM.US', -149.90, 'Business', 'Software', 'verified', 'demo', NOW())
ON DUPLICATE KEY UPDATE updated_at = NOW();

-- ============================================================================
-- SAMPLE CONTACTS FOR DEMO ACCOUNT
-- ============================================================================
INSERT INTO contacts (
    user_id,
    name,
    email,
    company,
    business_type,
    category,
    created_at
) VALUES
    ('demo-00000000-0000-0000-0000-000000000001', 'John Smith', 'john.smith@example.com', 'Acme Corp', 'Business', 'client', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', 'Sarah Johnson', 'sarah.j@example.com', 'Tech Solutions', 'Business', 'vendor', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', 'Mike Williams', 'mike.w@example.com', 'Creative Agency', 'Business', 'partner', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', 'Emily Davis', 'emily.d@example.com', NULL, 'Personal', 'friend', NOW()),
    ('demo-00000000-0000-0000-0000-000000000001', 'David Brown', 'david.b@example.com', 'Brown & Associates', 'Business', 'client', NOW())
ON DUPLICATE KEY UPDATE updated_at = NOW();

-- ============================================================================
-- DEFAULT BUSINESS TYPES FOR NEW USERS (Template)
-- ============================================================================
-- This stored procedure creates default business types for new users
DELIMITER //

CREATE PROCEDURE IF NOT EXISTS create_default_business_types(IN p_user_id CHAR(36))
BEGIN
    INSERT INTO user_business_types (user_id, name, display_name, color, icon, is_default, sort_order)
    VALUES
        (p_user_id, 'Personal', 'Personal', '#00FF88', 'person.fill', TRUE, 1),
        (p_user_id, 'Business', 'Business', '#4A90D9', 'briefcase.fill', FALSE, 2)
    ON DUPLICATE KEY UPDATE updated_at = NOW();
END //

DELIMITER ;

-- ============================================================================
-- API ENDPOINT: Get User Business Types
-- ============================================================================
-- Backend route: GET /api/business-types
-- Returns: user's custom business types with colors and icons
--
-- Example response:
-- {
--   "business_types": [
--     {"name": "Personal", "display_name": "Personal", "color": "#00FF88", "icon": "person.fill", "is_default": true},
--     {"name": "Business", "display_name": "Business", "color": "#4A90D9", "icon": "briefcase.fill", "is_default": false}
--   ]
-- }

-- ============================================================================
-- DOCUMENTATION: Demo Account Credentials for App Store Review
-- ============================================================================
--
-- Email: demo@tallyups.com
-- Password: TallyDemo2025!
--
-- Or use Sign in with Apple with demo Apple ID:
-- Apple ID: (create a demo Apple ID for testing)
--
-- The demo account has:
-- - 10 sample transactions across different categories
-- - 5 sample contacts
-- - 3 business types (Personal, Business, Travel)
-- - Pre-configured settings
--
-- This account is read-only for demo purposes.
-- ============================================================================

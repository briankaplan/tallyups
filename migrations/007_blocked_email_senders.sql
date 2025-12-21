-- Migration 007: Blocked Email Senders Table
-- Stores email patterns that users have rejected to auto-block future emails
--
-- When a user rejects an email receipt, the sender is added here.
-- Future emails from this sender will be auto-rejected before reaching the inbox.
--
-- Date: 2024-12-21

-- ============================================================================
-- SECTION 1: BLOCKED SENDERS TABLE
-- ============================================================================

CREATE TABLE IF NOT EXISTS blocked_email_senders (
    id INT AUTO_INCREMENT PRIMARY KEY,
    email_pattern VARCHAR(255) NOT NULL UNIQUE COMMENT 'Email address or pattern to block',
    domain_pattern VARCHAR(255) COMMENT 'Domain extracted for faster matching',
    reason VARCHAR(255) COMMENT 'Why this sender was blocked',
    rejection_count INT DEFAULT 1 COMMENT 'Number of times this pattern was rejected',
    is_active BOOLEAN DEFAULT TRUE COMMENT 'Can be disabled without deleting',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,

    INDEX idx_email_pattern (email_pattern),
    INDEX idx_domain_pattern (domain_pattern),
    INDEX idx_active (is_active)
);

-- ============================================================================
-- SECTION 2: TRIGGER TO EXTRACT DOMAIN ON INSERT
-- ============================================================================

DELIMITER //

DROP TRIGGER IF EXISTS trg_extract_domain_on_insert //

CREATE TRIGGER trg_extract_domain_on_insert
BEFORE INSERT ON blocked_email_senders
FOR EACH ROW
BEGIN
    -- Extract domain from email pattern (everything after @)
    IF NEW.email_pattern LIKE '%@%' THEN
        SET NEW.domain_pattern = LOWER(SUBSTRING_INDEX(NEW.email_pattern, '@', -1));
    END IF;
END //

DROP TRIGGER IF EXISTS trg_extract_domain_on_update //

CREATE TRIGGER trg_extract_domain_on_update
BEFORE UPDATE ON blocked_email_senders
FOR EACH ROW
BEGIN
    -- Update domain if email pattern changed
    IF NEW.email_pattern != OLD.email_pattern AND NEW.email_pattern LIKE '%@%' THEN
        SET NEW.domain_pattern = LOWER(SUBSTRING_INDEX(NEW.email_pattern, '@', -1));
    END IF;
END //

DELIMITER ;

-- ============================================================================
-- SECTION 3: INSERT DEFAULT SPAM DOMAINS
-- ============================================================================

INSERT IGNORE INTO blocked_email_senders (email_pattern, domain_pattern, reason) VALUES
-- Marketing platforms
('noreply@mailchimp.com', 'mailchimp.com', 'Marketing platform'),
('noreply@sendgrid.net', 'sendgrid.net', 'Marketing platform'),
('noreply@constantcontact.com', 'constantcontact.com', 'Marketing platform'),

-- Social media notifications
('notification@linkedin.com', 'linkedin.com', 'Social media notification'),
('notification@facebook.com', 'facebook.com', 'Social media notification'),

-- Common newsletter patterns
('newsletter@%', NULL, 'Newsletter pattern'),
('promo@%', NULL, 'Promotional pattern'),
('marketing@%', NULL, 'Marketing pattern'),
('offers@%', NULL, 'Promotional pattern'),
('deals@%', NULL, 'Promotional pattern');

-- ============================================================================
-- VERIFICATION
-- ============================================================================

-- Verify table was created
-- SELECT * FROM blocked_email_senders;

-- Check blocked count by domain
-- SELECT domain_pattern, COUNT(*) as blocked_count
-- FROM blocked_email_senders
-- WHERE is_active = TRUE
-- GROUP BY domain_pattern;

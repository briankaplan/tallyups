-- Migration 005: Schema Integrity Fixes
-- Addresses critical issues found in database architecture review
--
-- CRITICAL: Run in order, with backups between major sections
--
-- Date: 2024-12-21

-- ============================================================================
-- SECTION 1: SOFT-DELETE PERFORMANCE INDEXES (P1)
-- Without these, queries on large datasets are 10-100x slower
-- ============================================================================

-- Index for filtering active (non-deleted) transactions
-- Most queries should use this to avoid scanning deleted records
CREATE INDEX IF NOT EXISTS idx_transactions_active
ON transactions(deleted, chase_date, business_type);

-- Index for soft-deleted record cleanup/archival
CREATE INDEX IF NOT EXISTS idx_transactions_deleted_created
ON transactions(deleted, created_at);

-- Index for verified transactions by business type (common report query)
CREATE INDEX IF NOT EXISTS idx_transactions_verified_business
ON transactions(verification_status, business_type, chase_date);

-- ============================================================================
-- SECTION 2: FOREIGN KEY ENFORCEMENT (P0)
-- Enable referential integrity for incoming_receipts -> transactions
-- ============================================================================

-- First, clean up any orphaned records that would violate the FK
-- This identifies incoming_receipts pointing to non-existent transactions
-- SELECT id, matched_transaction_id FROM incoming_receipts
-- WHERE matched_transaction_id IS NOT NULL
--   AND matched_transaction_id NOT IN (SELECT id FROM transactions);

-- Set orphaned references to NULL (safe cleanup)
UPDATE incoming_receipts
SET matched_transaction_id = NULL
WHERE matched_transaction_id IS NOT NULL
  AND matched_transaction_id NOT IN (SELECT id FROM transactions);

-- Now add the foreign key constraint
-- Using SET NULL on delete so receipts aren't lost when transactions are removed
ALTER TABLE incoming_receipts
ADD CONSTRAINT fk_incoming_receipts_transaction
FOREIGN KEY (matched_transaction_id) REFERENCES transactions(id)
ON DELETE SET NULL;

-- ============================================================================
-- SECTION 3: BUSINESS TYPES LOOKUP TABLE (P2)
-- Creates master list for validation and reporting
-- ============================================================================

CREATE TABLE IF NOT EXISTS business_types (
    id INT AUTO_INCREMENT PRIMARY KEY,
    code VARCHAR(50) NOT NULL UNIQUE,
    name VARCHAR(255) NOT NULL,
    description TEXT,
    color VARCHAR(7) DEFAULT '#666666' COMMENT 'Hex color for UI display',
    is_active BOOLEAN DEFAULT TRUE,
    sort_order INT DEFAULT 0,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
);

-- Insert standard business types
INSERT IGNORE INTO business_types (code, name, color, sort_order) VALUES
('down_home', 'Down Home', '#10B981', 1),
('mcr', 'Music City Rodeo', '#6366F1', 2),
('personal', 'Personal', '#8B5CF6', 3),
('emco', 'EMCO', '#3B82F6', 4),
('ceo', 'CEO', '#F59E0B', 5);

-- ============================================================================
-- SECTION 4: CONTACT TABLE CLEANUP (P2)
-- Merge atlas_contacts into contacts if both exist
-- ============================================================================

-- Check if atlas_contacts has data not in contacts
-- SELECT ac.* FROM atlas_contacts ac
-- LEFT JOIN contacts c ON ac.email = c.email
-- WHERE c.id IS NULL;

-- If atlas_contacts exists and has unique data, migrate it
-- This is a safe merge that preserves all unique records
INSERT IGNORE INTO contacts (
    first_name, last_name, email, phone, company,
    source, created_at
)
SELECT
    first_name, last_name, email, phone, company,
    'atlas_migration', created_at
FROM atlas_contacts ac
WHERE NOT EXISTS (
    SELECT 1 FROM contacts c WHERE c.email = ac.email
);

-- After verifying migration, atlas_contacts can be dropped
-- DROP TABLE IF EXISTS atlas_contacts;

-- ============================================================================
-- SECTION 5: AUDIT TRIGGER FOR TRANSACTIONS (P2)
-- Automatically log changes to critical transaction fields
-- ============================================================================

DELIMITER //

-- Drop existing trigger if present (for idempotency)
DROP TRIGGER IF EXISTS trg_audit_transactions_update //

CREATE TRIGGER trg_audit_transactions_update
AFTER UPDATE ON transactions
FOR EACH ROW
BEGIN
    -- Only log if critical fields changed
    IF OLD.chase_amount != NEW.chase_amount
       OR OLD.verification_status != NEW.verification_status
       OR OLD.business_type != NEW.business_type
       OR OLD.review_status != NEW.review_status
       OR OLD.deleted != NEW.deleted
    THEN
        INSERT INTO audit_log (
            event_type,
            table_name,
            record_id,
            old_values,
            new_values,
            user_id,
            created_at
        ) VALUES (
            'update',
            'transactions',
            NEW.id,
            JSON_OBJECT(
                'amount', OLD.chase_amount,
                'verification_status', OLD.verification_status,
                'business_type', OLD.business_type,
                'review_status', OLD.review_status,
                'deleted', OLD.deleted
            ),
            JSON_OBJECT(
                'amount', NEW.chase_amount,
                'verification_status', NEW.verification_status,
                'business_type', NEW.business_type,
                'review_status', NEW.review_status,
                'deleted', NEW.deleted
            ),
            COALESCE(@current_user_id, 'system'),
            NOW()
        );
    END IF;
END //

-- Trigger for transaction deletion
DROP TRIGGER IF EXISTS trg_audit_transactions_delete //

CREATE TRIGGER trg_audit_transactions_delete
BEFORE DELETE ON transactions
FOR EACH ROW
BEGIN
    INSERT INTO audit_log (
        event_type,
        table_name,
        record_id,
        old_values,
        user_id,
        created_at
    ) VALUES (
        'delete',
        'transactions',
        OLD.id,
        JSON_OBJECT(
            'amount', OLD.chase_amount,
            'description', OLD.chase_description,
            'date', OLD.chase_date,
            'business_type', OLD.business_type
        ),
        COALESCE(@current_user_id, 'system'),
        NOW()
    );
END //

DELIMITER ;

-- ============================================================================
-- SECTION 6: ADDITIONAL USEFUL INDEXES
-- Based on common query patterns in the codebase
-- ============================================================================

-- For expense report generation (date range + business type)
CREATE INDEX IF NOT EXISTS idx_transactions_report_query
ON transactions(business_type, chase_date, deleted);

-- For receipt matching queries
CREATE INDEX IF NOT EXISTS idx_incoming_receipts_matching
ON incoming_receipts(status, extracted_amount, extracted_date);

-- For contact-expense linking
CREATE INDEX IF NOT EXISTS idx_contact_expense_link_contact
ON contact_expense_links(contact_id, created_at);

-- For plaid transaction matching
CREATE INDEX IF NOT EXISTS idx_plaid_transactions_match
ON plaid_transactions(amount, date, processing_status);

-- ============================================================================
-- VERIFICATION QUERIES (Run after migration)
-- ============================================================================

-- Verify indexes were created
-- SHOW INDEX FROM transactions WHERE Key_name LIKE 'idx_transactions%';

-- Verify FK constraint
-- SELECT CONSTRAINT_NAME FROM information_schema.TABLE_CONSTRAINTS
-- WHERE TABLE_NAME = 'incoming_receipts' AND CONSTRAINT_TYPE = 'FOREIGN KEY';

-- Verify business_types populated
-- SELECT * FROM business_types;

-- Verify audit trigger exists
-- SHOW TRIGGERS LIKE 'transactions';

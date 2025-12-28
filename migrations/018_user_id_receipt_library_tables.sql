-- Migration 018: Add user_id to receipt library tables
-- These tables were missing user_id for proper multi-tenant isolation
-- Tables: receipt_tags, receipt_tag_assignments, receipt_favorites,
--         receipt_annotations, receipt_attendees, receipt_collections, receipt_collection_items

-- ============================================================================
-- RECEIPT TAGS TABLE
-- ============================================================================
ALTER TABLE receipt_tags
ADD COLUMN user_id CHAR(36) NULL AFTER id;

-- Need to drop the unique constraint first, then recreate with user_id
ALTER TABLE receipt_tags DROP INDEX unique_tag_name;
ALTER TABLE receipt_tags ADD UNIQUE KEY unique_user_tag_name (user_id, name);

CREATE INDEX idx_receipt_tags_user_id ON receipt_tags(user_id);

-- Migrate existing data to admin user
UPDATE receipt_tags
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT TAG ASSIGNMENTS TABLE
-- ============================================================================
ALTER TABLE receipt_tag_assignments
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_receipt_tag_assignments_user_id ON receipt_tag_assignments(user_id);

-- Migrate existing data to admin user
UPDATE receipt_tag_assignments
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT FAVORITES TABLE
-- ============================================================================
ALTER TABLE receipt_favorites
ADD COLUMN user_id CHAR(36) NULL AFTER id;

-- Update unique constraint to include user_id
ALTER TABLE receipt_favorites DROP INDEX unique_favorite;
ALTER TABLE receipt_favorites ADD UNIQUE KEY unique_user_favorite (user_id, receipt_type, receipt_id);

CREATE INDEX idx_receipt_favorites_user_id ON receipt_favorites(user_id);

-- Migrate existing data to admin user
UPDATE receipt_favorites
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT ANNOTATIONS TABLE
-- ============================================================================
ALTER TABLE receipt_annotations
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_receipt_annotations_user_id ON receipt_annotations(user_id);

-- Migrate existing data to admin user
UPDATE receipt_annotations
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT ATTENDEES TABLE
-- ============================================================================
ALTER TABLE receipt_attendees
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_receipt_attendees_user_id ON receipt_attendees(user_id);

-- Migrate existing data to admin user
UPDATE receipt_attendees
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT COLLECTIONS TABLE
-- ============================================================================
ALTER TABLE receipt_collections
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_receipt_collections_user_id ON receipt_collections(user_id);

-- Migrate existing data to admin user
UPDATE receipt_collections
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

-- ============================================================================
-- RECEIPT COLLECTION ITEMS TABLE
-- ============================================================================
ALTER TABLE receipt_collection_items
ADD COLUMN user_id CHAR(36) NULL AFTER id;

CREATE INDEX idx_receipt_collection_items_user_id ON receipt_collection_items(user_id);

-- Migrate existing data to admin user
UPDATE receipt_collection_items
SET user_id = '00000000-0000-0000-0000-000000000001'
WHERE user_id IS NULL;

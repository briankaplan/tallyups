-- Migration 019: Add composite indexes for multi-user performance
-- Created: 2025-12-28
-- Purpose: Optimize common queries with user_id filtering

-- Transactions table composite indexes
CREATE INDEX idx_user_date_status ON transactions(user_id, chase_date, review_status);
CREATE INDEX idx_user_business_date ON transactions(user_id, business_type, chase_date);
CREATE INDEX idx_user_deleted ON transactions(user_id, deleted);

-- Incoming receipts table composite indexes
CREATE INDEX idx_inc_user_status ON incoming_receipts(user_id, status);
CREATE INDEX idx_inc_user_date ON incoming_receipts(user_id, created_at);
CREATE INDEX idx_inc_user_merchant ON incoming_receipts(user_id, merchant(50));

-- These indexes optimize queries like:
-- SELECT * FROM transactions WHERE user_id = ? AND chase_date BETWEEN ? AND ? AND review_status = ?
-- SELECT * FROM transactions WHERE user_id = ? AND business_type = ? ORDER BY chase_date DESC
-- SELECT * FROM incoming_receipts WHERE user_id = ? AND status = ?

-- ReceiptAI SQLite Database Schema
-- Created: 2025-11-13

-- Main transactions table
CREATE TABLE IF NOT EXISTS transactions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    _index INTEGER UNIQUE NOT NULL,  -- Original CSV row index

    -- Chase/Bank Data
    chase_date TEXT,
    chase_description TEXT,
    chase_amount REAL,
    chase_category TEXT,
    chase_type TEXT,

    -- Receipt Data
    receipt_file TEXT,

    -- Business Classification
    business_type TEXT,
    notes TEXT,

    -- AI Matching Results
    ai_note TEXT,
    ai_confidence INTEGER,
    ai_receipt_merchant TEXT,
    ai_receipt_date TEXT,
    ai_receipt_total TEXT,

    -- Review Status
    review_status TEXT,

    -- Metadata
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for fast lookups
CREATE INDEX IF NOT EXISTS idx_chase_date ON transactions(chase_date);
CREATE INDEX IF NOT EXISTS idx_chase_description ON transactions(chase_description);
CREATE INDEX IF NOT EXISTS idx_receipt_file ON transactions(receipt_file);
CREATE INDEX IF NOT EXISTS idx_business_type ON transactions(business_type);
CREATE INDEX IF NOT EXISTS idx_review_status ON transactions(review_status);
CREATE INDEX IF NOT EXISTS idx_index ON transactions(_index);

-- Trigger to update timestamp on changes
CREATE TRIGGER IF NOT EXISTS update_timestamp
AFTER UPDATE ON transactions
BEGIN
    UPDATE transactions SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Receipt metadata cache (for fast matching)
-- Will migrate this later, keeping CSV for now
CREATE TABLE IF NOT EXISTS receipt_metadata (
    filename TEXT PRIMARY KEY,
    merchant TEXT,
    date TEXT,
    amount REAL,
    raw_text TEXT,
    cached_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_receipt_merchant ON receipt_metadata(merchant);
CREATE INDEX IF NOT EXISTS idx_receipt_date ON receipt_metadata(date);
CREATE INDEX IF NOT EXISTS idx_receipt_amount ON receipt_metadata(amount);

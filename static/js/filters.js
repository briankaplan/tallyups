/**
 * Transaction Filter System
 * =========================
 * High-performance filtering with instant response.
 * Supports complex filter combinations with presets.
 */

class TransactionFilter {
    constructor() {
        this.filters = {
            dateRange: null,           // { start: Date, end: Date }
            merchants: [],             // Array of merchant names
            amountRange: null,         // { min: number, max: number }
            businessTypes: [],         // ['Down Home', 'MCR', 'Personal', 'EM.co', 'Unassigned']
            categories: [],            // Category names
            matchStatus: null,         // 'matched', 'unmatched', 'review'
            reviewStatus: null,        // 'good', 'bad', 'needs_review', 'approved', 'flagged'
            validationStatus: null,    // 'verified', 'mismatch', 'error'
            hasReceipt: null,          // true, false, null
            hasNote: null,             // true, false, null
            searchQuery: '',
            confidence: null,          // { min: number, max: number }
        };

        this.presets = {
            'needs-work': {
                name: 'Needs Work',
                icon: '🔧',
                filters: {
                    reviewStatus: 'needs_review'
                }
            },
            'unmatched': {
                name: 'Unmatched',
                icon: '❓',
                filters: {
                    hasReceipt: false
                }
            },
            'needs-review': {
                name: 'Needs Review',
                icon: '👀',
                filters: {
                    validationStatus: 'mismatch'
                }
            },
            'down-home': {
                name: 'Down Home',
                icon: '🏠',
                filters: {
                    businessTypes: ['Down Home']
                }
            },
            'mcr': {
                name: 'Music City Rodeo',
                icon: '🤠',
                filters: {
                    businessTypes: ['Music City Rodeo']
                }
            },
            'personal': {
                name: 'Personal',
                icon: '👤',
                filters: {
                    businessTypes: ['Personal']
                }
            },
            'high-value': {
                name: 'High Value (>$500)',
                icon: '💰',
                filters: {
                    amountRange: { min: 500, max: null }
                }
            },
            'this-month': {
                name: 'This Month',
                icon: '📅',
                filters: {
                    dateRange: { start: this.startOfMonth(), end: this.today() }
                }
            },
            'last-month': {
                name: 'Last Month',
                icon: '📆',
                filters: {
                    dateRange: { start: this.startOfLastMonth(), end: this.endOfLastMonth() }
                }
            },
            'verified': {
                name: 'Verified',
                icon: '✅',
                filters: {
                    validationStatus: 'verified'
                }
            },
            'with-receipts': {
                name: 'With Receipts',
                icon: '🧾',
                filters: {
                    hasReceipt: true
                }
            },
            'no-note': {
                name: 'Missing Notes',
                icon: '📝',
                filters: {
                    hasNote: false,
                    hasReceipt: true
                }
            },
            'low-confidence': {
                name: 'Low Confidence',
                icon: '⚠️',
                filters: {
                    confidence: { min: 0, max: 70 }
                }
            },
            'refunds': {
                name: 'Refunds',
                icon: '💸',
                filters: {
                    amountRange: { min: null, max: 0 }
                }
            },
            'all': {
                name: 'All Transactions',
                icon: '📊',
                filters: {}
            }
        };

        this.activePreset = null;
        this.listeners = new Set();
    }

    // Date helpers
    today() {
        return new Date();
    }

    startOfMonth() {
        const d = new Date();
        d.setDate(1);
        d.setHours(0, 0, 0, 0);
        return d;
    }

    startOfLastMonth() {
        const d = new Date();
        d.setMonth(d.getMonth() - 1);
        d.setDate(1);
        d.setHours(0, 0, 0, 0);
        return d;
    }

    endOfLastMonth() {
        const d = new Date();
        d.setDate(0);  // Last day of previous month
        d.setHours(23, 59, 59, 999);
        return d;
    }

    // Filter methods
    setFilter(key, value) {
        if (this.filters.hasOwnProperty(key)) {
            this.filters[key] = value;
            this.activePreset = null;
            this.notifyListeners();
        }
    }

    setFilters(filterObj) {
        for (const [key, value] of Object.entries(filterObj)) {
            if (this.filters.hasOwnProperty(key)) {
                this.filters[key] = value;
            }
        }
        this.activePreset = null;
        this.notifyListeners();
    }

    clearFilter(key) {
        if (this.filters.hasOwnProperty(key)) {
            if (Array.isArray(this.filters[key])) {
                this.filters[key] = [];
            } else {
                this.filters[key] = null;
            }
            this.notifyListeners();
        }
    }

    clearAll() {
        this.filters = {
            dateRange: null,
            merchants: [],
            amountRange: null,
            businessTypes: [],
            categories: [],
            matchStatus: null,
            reviewStatus: null,
            validationStatus: null,
            hasReceipt: null,
            hasNote: null,
            searchQuery: '',
            confidence: null,
        };
        this.activePreset = null;
        this.notifyListeners();
    }

    applyPreset(presetKey) {
        const preset = this.presets[presetKey];
        if (!preset) return false;

        this.clearAll();
        this.setFilters(preset.filters);
        this.activePreset = presetKey;
        this.notifyListeners();
        return true;
    }

    // Main filter function - optimized for speed
    apply(transactions) {
        if (!transactions || !transactions.length) return [];

        const startTime = performance.now();
        const { filters } = this;

        // Pre-compute filter checks
        const hasDateFilter = filters.dateRange?.start || filters.dateRange?.end;
        const hasMerchantFilter = filters.merchants.length > 0;
        const hasAmountFilter = filters.amountRange?.min != null || filters.amountRange?.max != null;
        const hasBusinessFilter = filters.businessTypes.length > 0;
        const hasCategoryFilter = filters.categories.length > 0;
        const hasConfidenceFilter = filters.confidence?.min != null || filters.confidence?.max != null;
        const searchLower = filters.searchQuery?.toLowerCase();
        const hasSearch = searchLower && searchLower.length > 0;

        // Filter in single pass
        const results = transactions.filter(tx => {
            // Date filter
            if (hasDateFilter) {
                const txDate = this.parseDate(tx['Chase Date'] || tx.transaction_date);
                if (txDate) {
                    if (filters.dateRange.start && txDate < filters.dateRange.start) return false;
                    if (filters.dateRange.end && txDate > filters.dateRange.end) return false;
                }
            }

            // Merchant filter
            if (hasMerchantFilter) {
                const merchant = (tx['Chase Description'] || tx.merchant || '').toLowerCase();
                if (!filters.merchants.some(m => merchant.includes(m.toLowerCase()))) {
                    return false;
                }
            }

            // Amount filter
            if (hasAmountFilter) {
                const amount = this.parseAmount(tx['Chase Amount'] || tx.amount);
                if (filters.amountRange.min != null && amount < filters.amountRange.min) return false;
                if (filters.amountRange.max != null && amount > filters.amountRange.max) return false;
            }

            // Business type filter
            if (hasBusinessFilter) {
                const bizType = tx['Business Type'] || 'Unassigned';
                if (!filters.businessTypes.includes(bizType) &&
                    !(filters.businessTypes.includes('Unassigned') && !bizType)) {
                    return false;
                }
            }

            // Category filter
            if (hasCategoryFilter) {
                const category = tx['mi_category'] || tx['Chase Category'] || tx.category || '';
                if (!filters.categories.includes(category)) {
                    return false;
                }
            }

            // Match status filter
            if (filters.matchStatus) {
                const hasReceipt = !!(tx['Receipt File'] || tx.r2_url || tx.receipt_url);
                switch (filters.matchStatus) {
                    case 'matched':
                        if (!hasReceipt) return false;
                        break;
                    case 'unmatched':
                        if (hasReceipt) return false;
                        break;
                    case 'review':
                        if (!hasReceipt || tx.receipt_validation_status !== 'mismatch') return false;
                        break;
                }
            }

            // Review status filter
            if (filters.reviewStatus) {
                const status = (tx['Review Status'] || '').toLowerCase();
                if (filters.reviewStatus === 'needs_review') {
                    if (status === 'good' || status === 'approved' || status === 'not needed') return false;
                } else if (status !== filters.reviewStatus) {
                    return false;
                }
            }

            // Validation status filter
            if (filters.validationStatus) {
                const valStatus = tx.receipt_validation_status || '';
                if (valStatus !== filters.validationStatus) return false;
            }

            // Has receipt filter
            if (filters.hasReceipt !== null) {
                const hasReceipt = !!(tx['Receipt File'] || tx.r2_url || tx.receipt_url);
                if (hasReceipt !== filters.hasReceipt) return false;
            }

            // Has note filter
            if (filters.hasNote !== null) {
                const hasNote = !!(tx['AI Note'] || tx.Notes || tx.notes);
                if (hasNote !== filters.hasNote) return false;
            }

            // Confidence filter
            if (hasConfidenceFilter) {
                const confidence = parseFloat(tx['AI Confidence'] || tx.ai_confidence || 0);
                if (filters.confidence.min != null && confidence < filters.confidence.min) return false;
                if (filters.confidence.max != null && confidence > filters.confidence.max) return false;
            }

            // Search query (last for performance - most expensive)
            if (hasSearch) {
                const searchFields = [
                    tx['Chase Description'],
                    tx.merchant,
                    tx['mi_merchant'],
                    tx['AI Note'],
                    tx.Notes,
                    tx['mi_category'],
                    tx['Chase Category'],
                ].filter(Boolean).join(' ').toLowerCase();

                if (!searchFields.includes(searchLower)) {
                    // Try amount search
                    const amountStr = String(this.parseAmount(tx['Chase Amount'] || tx.amount));
                    if (!amountStr.includes(searchLower)) {
                        return false;
                    }
                }
            }

            return true;
        });

        const elapsed = performance.now() - startTime;
        if (elapsed > 50) {
            console.log(`Filter took ${elapsed.toFixed(1)}ms for ${transactions.length} -> ${results.length} transactions`);
        }

        return results;
    }

    // Parsing helpers
    parseDate(dateStr) {
        if (!dateStr) return null;
        if (dateStr instanceof Date) return dateStr;

        // Try common formats
        const formats = [
            /^(\d{4})-(\d{2})-(\d{2})/,  // YYYY-MM-DD
            /^(\d{2})\/(\d{2})\/(\d{4})/,  // MM/DD/YYYY
        ];

        for (const fmt of formats) {
            const match = dateStr.match(fmt);
            if (match) {
                if (fmt === formats[0]) {
                    return new Date(match[1], match[2] - 1, match[3]);
                } else {
                    return new Date(match[3], match[1] - 1, match[2]);
                }
            }
        }

        return new Date(dateStr);
    }

    parseAmount(amountStr) {
        if (typeof amountStr === 'number') return amountStr;
        if (!amountStr) return 0;

        // Remove currency symbols and commas
        const cleaned = String(amountStr).replace(/[$,]/g, '');
        return parseFloat(cleaned) || 0;
    }

    // Listener system
    addListener(callback) {
        this.listeners.add(callback);
    }

    removeListener(callback) {
        this.listeners.delete(callback);
    }

    notifyListeners() {
        for (const listener of this.listeners) {
            try {
                listener(this.filters, this.activePreset);
            } catch (e) {
                console.error('Filter listener error:', e);
            }
        }
    }

    // State getters
    getActiveFilters() {
        const active = {};
        for (const [key, value] of Object.entries(this.filters)) {
            if (value !== null && value !== '' &&
                (!Array.isArray(value) || value.length > 0)) {
                active[key] = value;
            }
        }
        return active;
    }

    getFilterCount() {
        return Object.keys(this.getActiveFilters()).length;
    }

    isFiltered() {
        return this.getFilterCount() > 0;
    }

    // Serialize for URL params
    toQueryString() {
        const active = this.getActiveFilters();
        if (Object.keys(active).length === 0) return '';

        return new URLSearchParams({
            filters: JSON.stringify(active)
        }).toString();
    }

    fromQueryString(queryString) {
        try {
            const params = new URLSearchParams(queryString);
            const filtersJson = params.get('filters');
            if (filtersJson) {
                const parsed = JSON.parse(filtersJson);
                this.setFilters(parsed);
            }
        } catch (e) {
            console.error('Failed to parse filter query string:', e);
        }
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TransactionFilter;
}

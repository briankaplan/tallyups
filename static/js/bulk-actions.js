/**
 * Bulk Operations System
 * ======================
 * High-performance batch operations for processing many transactions at once.
 */

class BulkActions {
    constructor(reviewInterface) {
        this.ui = reviewInterface;
        this.selectedIds = new Set();
        this.modalEl = null;
        this.progressEl = null;
        this.isProcessing = false;

        this.init();
    }

    init() {
        this.createModal();
        this.createProgressOverlay();
    }

    createModal() {
        const modal = document.createElement('div');
        modal.id = 'bulk-action-modal';
        modal.className = 'bulk-modal';
        modal.innerHTML = `
            <div class="bulk-backdrop"></div>
            <div class="bulk-content">
                <div class="bulk-header">
                    <h2>📦 Bulk Actions</h2>
                    <span class="bulk-count">0 selected</span>
                    <button class="bulk-close">×</button>
                </div>
                <div class="bulk-body">
                    <!-- Business Type Section -->
                    <div class="bulk-section">
                        <h3>🏢 Set Business Type</h3>
                        <div class="bulk-buttons">
                            <button class="bulk-btn" data-action="business" data-value="Business">
                                <span class="btn-icon">🏠</span>
                                <span class="btn-text">Business</span>
                            </button>
                            <button class="bulk-btn" data-action="business" data-value="Secondary">
                                <span class="btn-icon">🤠</span>
                                <span class="btn-text">MCR</span>
                            </button>
                            <button class="bulk-btn" data-action="business" data-value="Personal">
                                <span class="btn-icon">👤</span>
                                <span class="btn-text">Personal</span>
                            </button>
                            <button class="bulk-btn" data-action="business" data-value="EM.co">
                                <span class="btn-icon">🏢</span>
                                <span class="btn-text">EM.co</span>
                            </button>
                        </div>
                    </div>

                    <!-- Review Status Section -->
                    <div class="bulk-section">
                        <h3>✓ Set Review Status</h3>
                        <div class="bulk-buttons">
                            <button class="bulk-btn success" data-action="status" data-value="good">
                                <span class="btn-icon">✓</span>
                                <span class="btn-text">Mark Good</span>
                            </button>
                            <button class="bulk-btn danger" data-action="status" data-value="bad">
                                <span class="btn-icon">✗</span>
                                <span class="btn-text">Mark Bad</span>
                            </button>
                            <button class="bulk-btn" data-action="status" data-value="not needed">
                                <span class="btn-icon">—</span>
                                <span class="btn-text">Not Needed</span>
                            </button>
                            <button class="bulk-btn" data-action="status" data-value="">
                                <span class="btn-icon">↩</span>
                                <span class="btn-text">Clear Status</span>
                            </button>
                        </div>
                    </div>

                    <!-- AI Section -->
                    <div class="bulk-section">
                        <h3>🤖 AI Operations</h3>
                        <div class="bulk-buttons">
                            <button class="bulk-btn primary" data-action="ai-notes">
                                <span class="btn-icon">📝</span>
                                <span class="btn-text">Generate AI Notes</span>
                            </button>
                            <button class="bulk-btn primary" data-action="ai-categorize">
                                <span class="btn-icon">🏷️</span>
                                <span class="btn-text">AI Categorize</span>
                            </button>
                            <button class="bulk-btn" data-action="ai-match">
                                <span class="btn-icon">🔍</span>
                                <span class="btn-text">AI Match Receipts</span>
                            </button>
                        </div>
                    </div>

                    <!-- Category Section -->
                    <div class="bulk-section">
                        <h3>🏷️ Set Category</h3>
                        <div class="bulk-category-select">
                            <select id="bulk-category">
                                <option value="">Select category...</option>
                                <option value="Meals & Entertainment">Meals & Entertainment</option>
                                <option value="Travel">Travel</option>
                                <option value="Software & Subscriptions">Software & Subscriptions</option>
                                <option value="Office Supplies">Office Supplies</option>
                                <option value="Professional Services">Professional Services</option>
                                <option value="Marketing">Marketing</option>
                                <option value="Equipment">Equipment</option>
                                <option value="Utilities">Utilities</option>
                                <option value="Other">Other</option>
                            </select>
                            <button class="bulk-btn" data-action="category">Apply Category</button>
                        </div>
                    </div>

                    <!-- Export Section -->
                    <div class="bulk-section">
                        <h3>📊 Export</h3>
                        <div class="bulk-buttons">
                            <button class="bulk-btn" data-action="export-csv">
                                <span class="btn-icon">📄</span>
                                <span class="btn-text">Export CSV</span>
                            </button>
                            <button class="bulk-btn" data-action="export-expensify">
                                <span class="btn-icon">💰</span>
                                <span class="btn-text">Export Expensify</span>
                            </button>
                        </div>
                    </div>

                    <!-- Danger Zone -->
                    <div class="bulk-section danger-zone">
                        <h3>⚠️ Danger Zone</h3>
                        <div class="bulk-buttons">
                            <button class="bulk-btn danger" data-action="detach-receipts">
                                <span class="btn-icon">🗑️</span>
                                <span class="btn-text">Detach Receipts</span>
                            </button>
                        </div>
                    </div>
                </div>
                <div class="bulk-footer">
                    <button class="bulk-cancel">Cancel</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        this.modalEl = modal;
        this.bindModalEvents();
    }

    createProgressOverlay() {
        const overlay = document.createElement('div');
        overlay.id = 'bulk-progress';
        overlay.className = 'bulk-progress';
        overlay.innerHTML = `
            <div class="progress-content">
                <div class="progress-header">
                    <span class="progress-title">Processing...</span>
                    <span class="progress-count">0 / 0</span>
                </div>
                <div class="progress-bar">
                    <div class="progress-fill"></div>
                </div>
                <div class="progress-status"></div>
                <button class="progress-cancel">Cancel</button>
            </div>
        `;

        document.body.appendChild(overlay);
        this.progressEl = overlay;
        this.bindProgressEvents();
    }

    bindModalEvents() {
        // Close buttons
        this.modalEl.querySelector('.bulk-backdrop').addEventListener('click', () => this.close());
        this.modalEl.querySelector('.bulk-close').addEventListener('click', () => this.close());
        this.modalEl.querySelector('.bulk-cancel').addEventListener('click', () => this.close());

        // Action buttons
        this.modalEl.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.currentTarget.dataset.action;
                const value = e.currentTarget.dataset.value;
                this.executeAction(action, value);
            });
        });

        // Category select
        this.modalEl.querySelector('[data-action="category"]')?.addEventListener('click', () => {
            const select = this.modalEl.querySelector('#bulk-category');
            if (select.value) {
                this.executeAction('category', select.value);
            }
        });
    }

    bindProgressEvents() {
        this.progressEl.querySelector('.progress-cancel')?.addEventListener('click', () => {
            this.cancelProcessing();
        });
    }

    // Selection management
    select(id) {
        this.selectedIds.add(id);
        this.updateUI();
    }

    deselect(id) {
        this.selectedIds.delete(id);
        this.updateUI();
    }

    toggle(id) {
        if (this.selectedIds.has(id)) {
            this.selectedIds.delete(id);
        } else {
            this.selectedIds.add(id);
        }
        this.updateUI();
    }

    selectAll(ids) {
        ids.forEach(id => this.selectedIds.add(id));
        this.updateUI();
    }

    selectRange(fromId, toId) {
        // Get indices from UI
        const transactions = this.ui?.getFilteredTransactions() || [];
        const fromIndex = transactions.findIndex(t => t._index === fromId);
        const toIndex = transactions.findIndex(t => t._index === toId);

        if (fromIndex === -1 || toIndex === -1) return;

        const start = Math.min(fromIndex, toIndex);
        const end = Math.max(fromIndex, toIndex);

        for (let i = start; i <= end; i++) {
            this.selectedIds.add(transactions[i]._index);
        }

        this.updateUI();
    }

    clearSelection() {
        this.selectedIds.clear();
        this.updateUI();
    }

    getSelectedTransactions() {
        const all = this.ui?.getAllTransactions() || [];
        return all.filter(t => this.selectedIds.has(t._index));
    }

    updateUI() {
        const count = this.selectedIds.size;

        // Update count in modal
        const countEl = this.modalEl?.querySelector('.bulk-count');
        if (countEl) {
            countEl.textContent = `${count} selected`;
        }

        // Emit event for UI to update row highlighting
        document.dispatchEvent(new CustomEvent('bulkSelectionChanged', {
            detail: { selectedIds: Array.from(this.selectedIds), count }
        }));
    }

    // Modal control
    open() {
        if (this.selectedIds.size === 0) {
            this.ui?.showToast('No transactions selected', '⚠️');
            return;
        }

        this.updateUI();
        this.modalEl?.classList.add('visible');
    }

    close() {
        this.modalEl?.classList.remove('visible');
    }

    // Action execution
    async executeAction(action, value) {
        if (this.isProcessing) return;

        const selected = this.getSelectedTransactions();
        if (selected.length === 0) {
            this.ui?.showToast('No transactions selected', '⚠️');
            return;
        }

        this.close();

        switch (action) {
            case 'business':
                await this.bulkSetBusinessType(selected, value);
                break;
            case 'status':
                await this.bulkSetReviewStatus(selected, value);
                break;
            case 'category':
                await this.bulkSetCategory(selected, value);
                break;
            case 'ai-notes':
                await this.bulkGenerateNotes(selected);
                break;
            case 'ai-categorize':
                await this.bulkCategorize(selected);
                break;
            case 'ai-match':
                await this.bulkAIMatch(selected);
                break;
            case 'export-csv':
                await this.exportCSV(selected);
                break;
            case 'export-expensify':
                await this.exportExpensify(selected);
                break;
            case 'detach-receipts':
                await this.bulkDetachReceipts(selected);
                break;
        }
    }

    // Bulk operations with progress
    async bulkSetBusinessType(transactions, type) {
        await this.processWithProgress(
            transactions,
            'Setting Business Type',
            async (tx) => {
                await this.updateTransaction(tx._index, { 'Business Type': type });
                tx['Business Type'] = type;
            }
        );
    }

    async bulkSetReviewStatus(transactions, status) {
        await this.processWithProgress(
            transactions,
            'Setting Review Status',
            async (tx) => {
                await this.updateTransaction(tx._index, { 'Review Status': status });
                tx['Review Status'] = status;
            }
        );
    }

    async bulkSetCategory(transactions, category) {
        await this.processWithProgress(
            transactions,
            'Setting Category',
            async (tx) => {
                await this.updateTransaction(tx._index, { 'mi_category': category });
                tx['mi_category'] = category;
            }
        );
    }

    async bulkGenerateNotes(transactions) {
        await this.processWithProgress(
            transactions,
            'Generating AI Notes',
            async (tx) => {
                try {
                    const res = await fetch('/api/notes/generate', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ _index: tx._index })
                    });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const data = await res.json();
                    if (data.ok && data.note) {
                        tx['AI Note'] = data.note;
                    }
                } catch (e) {
                    console.error('Note generation failed for', tx._index, e);
                }
            },
            { concurrent: 3, delay: 500 }  // Rate limit
        );
    }

    async bulkCategorize(transactions) {
        await this.processWithProgress(
            transactions,
            'AI Categorizing',
            async (tx) => {
                try {
                    const res = await fetch('/api/ai/categorize', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ _index: tx._index })
                    });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const data = await res.json();
                    if (data.ok) {
                        if (data.category) tx['mi_category'] = data.category;
                        if (data.business_type) tx['Business Type'] = data.business_type;
                    }
                } catch (e) {
                    console.error('Categorization failed for', tx._index, e);
                }
            },
            { concurrent: 3, delay: 300 }
        );
    }

    async bulkAIMatch(transactions) {
        await this.processWithProgress(
            transactions,
            'AI Matching Receipts',
            async (tx) => {
                try {
                    const res = await fetch('/ai_match', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ _index: tx._index })
                    });
                    if (!res.ok) throw new Error(`HTTP ${res.status}`);
                    const data = await res.json();
                    if (data.ok && data.result) {
                        Object.assign(tx, data.result);
                    }
                } catch (e) {
                    console.error('AI Match failed for', tx._index, e);
                }
            },
            { concurrent: 2, delay: 1000 }  // Slower - more API calls
        );
    }

    async bulkDetachReceipts(transactions) {
        const doDetach = async () => {
            await this.processWithProgress(
                transactions,
                'Detaching Receipts',
                async (tx) => {
                    await this.updateTransaction(tx._index, {
                        'Receipt File': '',
                        'r2_url': '',
                        'Review Status': ''
                    });
                    tx['Receipt File'] = '';
                    tx['r2_url'] = '';
                    tx['Review Status'] = '';
                }
            );
        };

        // Use ErrorHandler confirmation if available
        if (typeof ErrorHandler !== 'undefined') {
            ErrorHandler.confirm(
                `Are you sure you want to detach receipts from ${transactions.length} transactions? This cannot be undone.`,
                doDetach,
                { title: 'Bulk Detach Receipts', confirmText: 'Detach All', danger: true }
            );
        } else {
            // Fallback to native confirm
            if (window.confirm(`Detach receipts from ${transactions.length} transactions?`)) {
                await doDetach();
            }
        }
    }

    // Progress system
    async processWithProgress(items, title, processor, options = {}) {
        const { concurrent = 5, delay = 50 } = options;

        this.isProcessing = true;
        this.cancelRequested = false;
        this.showProgress(title, items.length);

        let processed = 0;
        let errors = 0;

        try {
            // Process in batches
            for (let i = 0; i < items.length; i += concurrent) {
                if (this.cancelRequested) break;

                const batch = items.slice(i, i + concurrent);
                const results = await Promise.allSettled(
                    batch.map(item => processor(item))
                );

                // Count errors
                results.forEach(r => {
                    if (r.status === 'rejected') errors++;
                });

                processed += batch.length;
                this.updateProgress(processed, items.length, errors);

                // Delay between batches
                if (delay > 0 && i + concurrent < items.length) {
                    await this.sleep(delay);
                }
            }

            // Complete
            if (this.cancelRequested) {
                this.ui?.showToast(`Cancelled at ${processed}/${items.length}`, '⚠️');
            } else {
                this.ui?.showToast(
                    `Completed ${processed} transactions` + (errors ? ` (${errors} errors)` : ''),
                    errors ? '⚠️' : '✅'
                );
            }

        } catch (e) {
            console.error('Bulk operation failed:', e);
            this.ui?.showToast('Operation failed: ' + e.message, '❌');
        } finally {
            this.isProcessing = false;
            this.hideProgress();
            this.clearSelection();
            this.ui?.refresh();
        }
    }

    showProgress(title, total) {
        const titleEl = this.progressEl?.querySelector('.progress-title');
        const countEl = this.progressEl?.querySelector('.progress-count');
        const fillEl = this.progressEl?.querySelector('.progress-fill');
        const statusEl = this.progressEl?.querySelector('.progress-status');

        if (titleEl) titleEl.textContent = title;
        if (countEl) countEl.textContent = `0 / ${total}`;
        if (fillEl) fillEl.style.width = '0%';
        if (statusEl) statusEl.textContent = '';

        this.progressEl?.classList.add('visible');
    }

    updateProgress(current, total, errors = 0) {
        const percent = Math.round((current / total) * 100);

        const countEl = this.progressEl?.querySelector('.progress-count');
        const fillEl = this.progressEl?.querySelector('.progress-fill');
        const statusEl = this.progressEl?.querySelector('.progress-status');

        if (countEl) countEl.textContent = `${current} / ${total}`;
        if (fillEl) fillEl.style.width = `${percent}%`;
        if (statusEl && errors > 0) statusEl.textContent = `${errors} errors`;
    }

    hideProgress() {
        this.progressEl?.classList.remove('visible');
    }

    cancelProcessing() {
        this.cancelRequested = true;
    }

    // Export functions
    async exportCSV(transactions) {
        const headers = [
            'Date', 'Merchant', 'Amount', 'Category', 'Business Type',
            'Review Status', 'AI Note', 'Receipt File'
        ];

        const rows = transactions.map(tx => [
            tx['Chase Date'] || tx.transaction_date || '',
            tx['Chase Description'] || tx.merchant || '',
            tx['Chase Amount'] || tx.amount || '',
            tx['mi_category'] || tx['Chase Category'] || '',
            tx['Business Type'] || '',
            tx['Review Status'] || '',
            (tx['AI Note'] || tx.Notes || '').replace(/"/g, '""'),
            tx['Receipt File'] || ''
        ]);

        const csv = [
            headers.join(','),
            ...rows.map(r => r.map(c => `"${c}"`).join(','))
        ].join('\n');

        this.downloadFile(csv, 'transactions-export.csv', 'text/csv');
        this.ui?.showToast(`Exported ${transactions.length} transactions`, '📄');
    }

    async exportExpensify(transactions) {
        // Expensify CSV format
        const headers = [
            'Timestamp', 'Merchant', 'Amount', 'MCC', 'Category',
            'Tag', 'Comment', 'Reimbursable', 'Billable', 'Receipt URL'
        ];

        const rows = transactions.map(tx => {
            const date = new Date(tx['Chase Date'] || tx.transaction_date);
            const timestamp = date.toISOString().replace('T', ' ').substring(0, 19);

            return [
                timestamp,
                tx['Chase Description'] || tx.merchant || '',
                Math.abs(parseFloat(tx['Chase Amount'] || tx.amount || 0)).toFixed(2),
                '',  // MCC
                tx['mi_category'] || tx['Chase Category'] || 'Other',
                tx['Business Type'] || '',
                (tx['AI Note'] || tx.Notes || '').replace(/"/g, '""'),
                '1',  // Reimbursable
                '0',  // Billable
                tx.r2_url || tx.receipt_url || ''
            ];
        });

        const csv = [
            headers.join(','),
            ...rows.map(r => r.map(c => `"${c}"`).join(','))
        ].join('\n');

        this.downloadFile(csv, 'expensify-export.csv', 'text/csv');
        this.ui?.showToast(`Exported ${transactions.length} for Expensify`, '💰');
    }

    // Utilities
    async updateTransaction(index, updates) {
        const res = await fetch('/update_row', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                _index: index,
                patch: updates
            })
        });

        if (!res.ok) throw new Error('Update failed');
        return res.json();
    }

    downloadFile(content, filename, mimeType) {
        const blob = new Blob([content], { type: mimeType });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();
        URL.revokeObjectURL(url);
    }

    sleep(ms) {
        return new Promise(resolve => setTimeout(resolve, ms));
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = BulkActions;
}

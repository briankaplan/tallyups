/**
 * Transaction Review Interface
 * ============================
 * Ultimate keyboard-driven review interface for processing hundreds of transactions.
 * Optimized for speed: < 1 second page load, < 100ms action response.
 */

class TransactionReviewInterface {
    constructor(options = {}) {
        this.options = {
            tableContainer: '#transaction-table',
            previewContainer: '#receipt-preview',
            filterContainer: '#filter-panel',
            rowHeight: 48,
            pageSize: 50,
            ...options
        };

        // State
        this.transactions = [];
        this.filteredTransactions = [];
        this.currentIndex = -1;
        this.selectedTransaction = null;
        this.scrollTop = 0;

        // Undo system
        this.undoStack = [];
        this.maxUndoStack = 50;

        // Components
        this.filter = new TransactionFilter();
        this.bulk = new BulkActions(this);
        this.preview = null;
        this.keyboard = null;

        // Virtual scroll state
        this.virtualScroll = {
            startIndex: 0,
            endIndex: 0,
            visibleCount: 20,
            buffer: 5,
        };

        // Sorting state
        this.sortColumn = 'chase_date';
        this.sortDirection = 'desc';

        // Performance tracking
        this.metrics = {
            lastRenderTime: 0,
            lastFilterTime: 0,
        };

        this.init();
    }

    async init() {
        this.bindElements();
        this.initComponents();
        this.bindEvents();
        await this.loadTransactions();

        // Show ready toast
        this.showToast('Review interface ready! Press ? for shortcuts', '⚡');
    }

    bindElements() {
        this.tableContainer = document.querySelector(this.options.tableContainer);
        this.previewContainer = document.querySelector(this.options.previewContainer);
        this.filterContainer = document.querySelector(this.options.filterContainer);
        this.tableBody = this.tableContainer?.querySelector('tbody');
        this.searchInput = document.querySelector('#search-input');
        this.filterBadge = document.querySelector('#filter-badge');
    }

    initComponents() {
        // Initialize preview panel
        if (this.previewContainer) {
            this.preview = new ReceiptPreview(this.previewContainer);
            this.preview.on('approved', () => this.onTransactionApproved());
            this.preview.on('businessTypeChanged', (e) => this.onFieldChanged(e));
            this.preview.on('reviewStatusChanged', (e) => this.onFieldChanged(e));
            this.preview.on('closed', () => this.focusTable());
        }

        // Initialize keyboard handler
        this.keyboard = new KeyboardHandler(this);
        window.keyboardHandler = this.keyboard;  // For help modal

        // Initialize filter listener
        this.filter.addListener(() => this.onFilterChanged());
    }

    bindEvents() {
        // Table click handling
        this.tableBody?.addEventListener('click', (e) => {
            const row = e.target.closest('tr');
            if (row) {
                const index = parseInt(row.dataset.index, 10);
                this.selectByIndex(index);
            }
        });

        // Table double-click for preview
        this.tableBody?.addEventListener('dblclick', (e) => {
            this.togglePreview(true);
        });

        // Search input
        this.searchInput?.addEventListener('input', (e) => {
            this.debounce('search', () => {
                this.filter.setFilter('searchQuery', e.target.value);
            }, 150);
        });

        // Virtual scroll
        this.tableContainer?.addEventListener('scroll', () => {
            this.onScroll();
        });

        // Bulk selection events
        document.addEventListener('bulkSelectionChanged', (e) => {
            this.highlightSelectedRows(e.detail.selectedIds);
        });

        // Window resize
        window.addEventListener('resize', () => {
            this.debounce('resize', () => this.recalculateVirtualScroll(), 100);
        });

        // Table header sorting
        document.querySelectorAll('th[data-sort]').forEach(th => {
            th.addEventListener('click', () => {
                this.sortBy(th.dataset.sort);
            });
            th.style.cursor = 'pointer';
        });
    }

    // Data loading
    async loadTransactions() {
        const startTime = performance.now();

        try {
            const res = await fetch('/api/transactions');
            if (!res.ok) throw new Error('Failed to fetch');

            this.transactions = await res.json() || [];
            this.applyFilters();

            const elapsed = performance.now() - startTime;
            console.log(`Loaded ${this.transactions.length} transactions in ${elapsed.toFixed(0)}ms`);

            // Warn if slow
            if (elapsed > 1000) {
                console.warn('Page load exceeded 1 second target');
            }

        } catch (e) {
            this.showToast('Failed to load transactions: ' + e.message, '❌');
        }
    }

    // Filtering
    applyFilters() {
        const startTime = performance.now();

        this.filteredTransactions = this.filter.apply(this.transactions);
        // Apply sorting after filtering
        this.filteredTransactions = this.sortTransactions(this.filteredTransactions);
        this.renderTable();
        this.updateStats();

        this.metrics.lastFilterTime = performance.now() - startTime;

        // Update filter badge
        const count = this.filter.getFilterCount();
        if (this.filterBadge) {
            this.filterBadge.textContent = count || '';
            this.filterBadge.classList.toggle('visible', count > 0);
        }
    }

    onFilterChanged() {
        this.applyFilters();
    }

    // Sorting
    sortBy(column) {
        // Toggle direction if same column, else default to desc for dates/amounts, asc for text
        if (this.sortColumn === column) {
            this.sortDirection = this.sortDirection === 'asc' ? 'desc' : 'asc';
        } else {
            this.sortColumn = column;
            // Default direction based on column type
            this.sortDirection = ['chase_date', 'chase_amount', 'ai_confidence'].includes(column) ? 'desc' : 'asc';
        }

        // Update header indicators
        this.updateSortIndicators();

        // Re-apply filters (which includes sorting)
        this.applyFilters();

        this.showToast(`Sorted by ${this.getColumnLabel(column)} (${this.sortDirection})`, '↕️');
    }

    updateSortIndicators() {
        document.querySelectorAll('th[data-sort]').forEach(th => {
            th.classList.remove('sort-asc', 'sort-desc');
            if (th.dataset.sort === this.sortColumn) {
                th.classList.add(`sort-${this.sortDirection}`);
            }
        });
    }

    getColumnLabel(column) {
        const labels = {
            'chase_date': 'Date',
            'chase_description': 'Merchant',
            'chase_amount': 'Amount',
            'business_type': 'Business',
            'review_status': 'Status',
            'ai_confidence': 'Confidence'
        };
        return labels[column] || column;
    }

    sortTransactions(transactions) {
        const col = this.sortColumn;
        const dir = this.sortDirection === 'asc' ? 1 : -1;

        return [...transactions].sort((a, b) => {
            let valA, valB;

            // Map column names to actual field names
            switch (col) {
                case 'chase_date':
                    valA = new Date(a['Chase Date'] || a.transaction_date || 0);
                    valB = new Date(b['Chase Date'] || b.transaction_date || 0);
                    break;
                case 'chase_description':
                    valA = (a['mi_merchant'] || a['Chase Description'] || '').toLowerCase();
                    valB = (b['mi_merchant'] || b['Chase Description'] || '').toLowerCase();
                    break;
                case 'chase_amount':
                    valA = parseFloat(a['Chase Amount'] || a.amount || 0);
                    valB = parseFloat(b['Chase Amount'] || b.amount || 0);
                    break;
                case 'business_type':
                    valA = (a['Business Type'] || '').toLowerCase();
                    valB = (b['Business Type'] || '').toLowerCase();
                    break;
                case 'review_status':
                    valA = (a['Review Status'] || '').toLowerCase();
                    valB = (b['Review Status'] || '').toLowerCase();
                    break;
                case 'ai_confidence':
                    valA = parseFloat(a['AI Confidence'] || a.ai_confidence || 0);
                    valB = parseFloat(b['AI Confidence'] || b.ai_confidence || 0);
                    break;
                default:
                    valA = a[col] || '';
                    valB = b[col] || '';
            }

            if (valA < valB) return -1 * dir;
            if (valA > valB) return 1 * dir;
            return 0;
        });
    }

    // Rendering with virtual scroll
    renderTable() {
        const startTime = performance.now();

        if (!this.tableBody) return;

        // Calculate virtual scroll bounds
        this.recalculateVirtualScroll();

        const { startIndex, endIndex } = this.virtualScroll;
        const fragment = document.createDocumentFragment();

        // Add spacer for items above viewport
        if (startIndex > 0) {
            const spacer = document.createElement('tr');
            spacer.className = 'virtual-spacer';
            spacer.innerHTML = `<td colspan="9" style="height: ${startIndex * this.options.rowHeight}px"></td>`;
            fragment.appendChild(spacer);
        }

        // Render visible rows
        for (let i = startIndex; i < endIndex && i < this.filteredTransactions.length; i++) {
            const tx = this.filteredTransactions[i];
            const row = this.createRow(tx, i);
            fragment.appendChild(row);
        }

        // Add spacer for items below viewport
        const belowCount = this.filteredTransactions.length - endIndex;
        if (belowCount > 0) {
            const spacer = document.createElement('tr');
            spacer.className = 'virtual-spacer';
            spacer.innerHTML = `<td colspan="9" style="height: ${belowCount * this.options.rowHeight}px"></td>`;
            fragment.appendChild(spacer);
        }

        // Replace table contents
        this.tableBody.innerHTML = '';
        this.tableBody.appendChild(fragment);

        this.metrics.lastRenderTime = performance.now() - startTime;

        // Warn if slow
        if (this.metrics.lastRenderTime > 100) {
            console.warn(`Slow render: ${this.metrics.lastRenderTime.toFixed(0)}ms`);
        }
    }

    createRow(tx, index) {
        const row = document.createElement('tr');
        row.dataset.index = tx._index;
        row.dataset.visibleIndex = index;

        // Add classes
        const classes = [];
        if (tx._index === this.selectedTransaction?._index) classes.push('selected');
        if (this.bulk.selectedIds.has(tx._index)) classes.push('bulk-selected');
        if (parseFloat(tx['Chase Amount']) < 0) classes.push('refund-row'); // Chase: negative = refund
        if (tx.newly_matched) classes.push('newly-matched');

        row.className = classes.join(' ');

        // Build row content
        row.innerHTML = `
            <td class="col-select">
                <input type="checkbox" ${this.bulk.selectedIds.has(tx._index) ? 'checked' : ''} />
            </td>
            <td class="col-date">${this.formatDate(tx['Chase Date'] || tx.transaction_date)}</td>
            <td class="col-merchant">
                <div class="merchant-cell">
                    ${this.escapeHtml(tx['mi_merchant'] || tx['Chase Description'] || '—')}
                    ${tx.mi_is_subscription ? '<span class="sub-badge">SUB</span>' : ''}
                </div>
            </td>
            <td class="col-amount ${parseFloat(tx['Chase Amount']) > 0 ? 'positive' : 'negative'}">
                ${this.formatAmount(tx['Chase Amount'] || tx.amount)}
            </td>
            <td class="col-receipt">${this.getReceiptIndicator(tx)}</td>
            <td class="col-confidence">${this.getConfidenceBadge(tx)}</td>
            <td class="col-business">${this.getBusinessBadge(tx['Business Type'])}</td>
            <td class="col-status">${this.getStatusBadge(tx['Review Status'])}</td>
            <td class="col-actions">
                <button class="row-action" data-action="preview" title="Preview">👁️</button>
            </td>
        `;

        // Checkbox click handler
        const checkbox = row.querySelector('input[type="checkbox"]');
        checkbox?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.bulk.toggle(tx._index);
        });

        // Action button handler
        const actionBtn = row.querySelector('[data-action="preview"]');
        actionBtn?.addEventListener('click', (e) => {
            e.stopPropagation();
            this.selectTransaction(tx);
            this.togglePreview(true);
        });

        return row;
    }

    recalculateVirtualScroll() {
        const container = this.tableContainer;
        if (!container) return;

        const scrollTop = container.scrollTop;
        const viewportHeight = container.clientHeight;
        const { rowHeight, buffer } = { rowHeight: this.options.rowHeight, buffer: this.virtualScroll.buffer };

        const startIndex = Math.max(0, Math.floor(scrollTop / rowHeight) - buffer);
        const visibleCount = Math.ceil(viewportHeight / rowHeight) + (buffer * 2);
        const endIndex = Math.min(this.filteredTransactions.length, startIndex + visibleCount);

        // Only re-render if bounds changed significantly
        if (startIndex !== this.virtualScroll.startIndex || endIndex !== this.virtualScroll.endIndex) {
            this.virtualScroll = { ...this.virtualScroll, startIndex, endIndex, visibleCount };
        }
    }

    onScroll() {
        const oldStart = this.virtualScroll.startIndex;
        const oldEnd = this.virtualScroll.endIndex;

        this.recalculateVirtualScroll();

        // Re-render if needed
        if (this.virtualScroll.startIndex !== oldStart || this.virtualScroll.endIndex !== oldEnd) {
            this.renderTable();
        }
    }

    // Navigation
    navigate(delta) {
        const newIndex = Math.max(0, Math.min(
            this.filteredTransactions.length - 1,
            this.currentIndex + delta
        ));

        if (newIndex !== this.currentIndex) {
            this.selectByVisibleIndex(newIndex);
        }
    }

    navigateToIndex(index) {
        if (index === -1) {
            index = this.filteredTransactions.length - 1;
        }
        this.selectByVisibleIndex(index);
    }

    selectByVisibleIndex(index) {
        if (index < 0 || index >= this.filteredTransactions.length) return;

        this.currentIndex = index;
        this.selectedTransaction = this.filteredTransactions[index];

        // Update row highlighting
        this.updateSelectedRow();

        // Scroll into view
        this.scrollToIndex(index);

        // Update preview if open
        if (this.previewContainer?.classList.contains('active')) {
            this.preview?.load(this.selectedTransaction);
        }
    }

    selectByIndex(txIndex) {
        const visibleIndex = this.filteredTransactions.findIndex(t => t._index === txIndex);
        if (visibleIndex !== -1) {
            this.selectByVisibleIndex(visibleIndex);
        }
    }

    selectTransaction(tx) {
        const visibleIndex = this.filteredTransactions.indexOf(tx);
        if (visibleIndex !== -1) {
            this.selectByVisibleIndex(visibleIndex);
        }
    }

    updateSelectedRow() {
        // Remove old selection
        this.tableBody?.querySelectorAll('.selected').forEach(r => r.classList.remove('selected'));

        // Add new selection
        const row = this.tableBody?.querySelector(`tr[data-index="${this.selectedTransaction?._index}"]`);
        row?.classList.add('selected');
    }

    scrollToIndex(index) {
        const container = this.tableContainer;
        if (!container) return;

        const rowTop = index * this.options.rowHeight;
        const rowBottom = rowTop + this.options.rowHeight;
        const viewportTop = container.scrollTop;
        const viewportBottom = viewportTop + container.clientHeight;

        if (rowTop < viewportTop) {
            container.scrollTop = rowTop;
        } else if (rowBottom > viewportBottom) {
            container.scrollTop = rowBottom - container.clientHeight;
        }
    }

    highlightSelectedRows(selectedIds) {
        this.tableBody?.querySelectorAll('tr').forEach(row => {
            const index = parseInt(row.dataset.index, 10);
            const checkbox = row.querySelector('input[type="checkbox"]');

            row.classList.toggle('bulk-selected', selectedIds.includes(index));
            if (checkbox) checkbox.checked = selectedIds.includes(index);
        });
    }

    // Selection extension (shift+arrow)
    extendSelection(delta) {
        if (!this.selectedTransaction) {
            this.navigate(delta > 0 ? 1 : -1);
            return;
        }

        const newIndex = this.currentIndex + delta;
        if (newIndex < 0 || newIndex >= this.filteredTransactions.length) return;

        const targetTx = this.filteredTransactions[newIndex];
        this.bulk.toggle(targetTx._index);
        this.navigate(delta);
    }

    // Quick actions
    setReviewStatus(status) {
        if (!this.selectedTransaction) return;
        this.updateField('Review Status', status);
        this.preview?.updateStatusButtons(status);
    }

    setBusinessType(type) {
        if (!this.selectedTransaction) return;
        this.updateField('Business Type', type);
        this.preview?.updateBusinessButtons(type);
    }

    setValidationStatus(status) {
        if (!this.selectedTransaction) return;
        this.updateField('receipt_validation_status', status);
    }

    setPersonal() {
        this.setBusinessType('Personal');
    }

    async updateField(field, value) {
        if (!this.selectedTransaction) return;

        // Save undo state
        this.saveUndoState(field, this.selectedTransaction._index, {
            [field]: this.selectedTransaction[field]
        });

        // Update locally
        this.selectedTransaction[field] = value;

        // Update UI immediately (optimistic)
        this.updateRowInPlace(this.selectedTransaction);

        // Sync to server
        try {
            await fetch('/update_row', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    _index: this.selectedTransaction._index,
                    patch: { [field]: value }
                })
            });
        } catch (e) {
            console.error('Update failed:', e);
            this.showToast('Update failed', '❌');
        }
    }

    updateRowInPlace(tx) {
        const row = this.tableBody?.querySelector(`tr[data-index="${tx._index}"]`);
        if (!row) return;

        // Update specific cells
        row.querySelector('.col-business')?.replaceWith(
            this.createCell('business', this.getBusinessBadge(tx['Business Type']))
        );
        row.querySelector('.col-status')?.replaceWith(
            this.createCell('status', this.getStatusBadge(tx['Review Status']))
        );
        row.querySelector('.col-receipt')?.replaceWith(
            this.createCell('receipt', this.getReceiptIndicator(tx))
        );
    }

    createCell(type, content) {
        const td = document.createElement('td');
        td.className = `col-${type}`;
        td.innerHTML = content;
        return td;
    }

    // AI operation state tracking
    aiOperationInProgress = false;

    setAILoading(loading, operation = '') {
        this.aiOperationInProgress = loading;
        document.body.classList.toggle('ai-loading', loading);

        // Disable/enable AI action buttons
        document.querySelectorAll('[data-ai-action]').forEach(btn => {
            btn.disabled = loading;
            if (loading) {
                btn.dataset.originalText = btn.textContent;
                if (btn.dataset.aiAction === operation) {
                    btn.innerHTML = '<span class="spinner-inline"></span> Working...';
                }
            } else if (btn.dataset.originalText) {
                btn.textContent = btn.dataset.originalText;
            }
        });
    }

    // AI actions
    async aiMatch() {
        if (!this.selectedTransaction) {
            this.showToast('Select a transaction first', '⚠️');
            return;
        }

        if (this.aiOperationInProgress) {
            this.showToast('AI operation in progress...', '⏳');
            return;
        }

        this.setAILoading(true, 'match');
        this.showToast('Finding receipt...', '🔍', 10000);

        try {
            const res = await fetch('/ai_match', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ _index: this.selectedTransaction._index })
            });

            const data = await res.json();
            if (data.ok && data.result) {
                Object.assign(this.selectedTransaction, data.result);
                this.updateRowInPlace(this.selectedTransaction);
                this.preview?.load(this.selectedTransaction);
                this.showToast('Receipt matched!', '✅');
            } else {
                this.showToast(data.message || 'No receipt found', '❌');
            }
        } catch (e) {
            this.showToast('AI Match failed: ' + e.message, '❌');
        } finally {
            this.setAILoading(false);
        }
    }

    async generateAINote() {
        if (!this.selectedTransaction) {
            this.showToast('Select a transaction first', '⚠️');
            return;
        }

        if (this.aiOperationInProgress) {
            this.showToast('AI operation in progress...', '⏳');
            return;
        }

        this.setAILoading(true, 'note');
        this.showToast('Generating note...', '✍️', 10000);

        try {
            const res = await fetch('/api/notes/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ _index: this.selectedTransaction._index })
            });

            const data = await res.json();
            if (data.ok && data.note) {
                this.selectedTransaction['AI Note'] = data.note;
                this.preview?.updateNote(this.selectedTransaction);
                this.showToast('Note generated', '✅');
            } else {
                this.showToast(data.error || 'Generation failed', '❌');
            }
        } catch (e) {
            this.showToast('Note generation failed: ' + e.message, '❌');
        } finally {
            this.setAILoading(false);
        }
    }

    async aiCategorize() {
        if (!this.selectedTransaction) {
            this.showToast('Select a transaction first', '⚠️');
            return;
        }

        if (this.aiOperationInProgress) {
            this.showToast('AI operation in progress...', '⏳');
            return;
        }

        this.setAILoading(true, 'categorize');
        this.showToast('Categorizing...', '🏷️', 10000);

        try {
            const res = await fetch('/api/ai/categorize', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ _index: this.selectedTransaction._index })
            });

            const data = await res.json();
            if (data.ok) {
                if (data.category) this.selectedTransaction['mi_category'] = data.category;
                if (data.business_type) this.selectedTransaction['Business Type'] = data.business_type;
                this.updateRowInPlace(this.selectedTransaction);
                this.showToast('Categorized', '✅');
            } else {
                this.showToast(data.error || 'Categorization failed', '❌');
            }
        } catch (e) {
            this.showToast('Categorization failed: ' + e.message, '❌');
        } finally {
            this.setAILoading(false);
        }
    }

    detachReceipt() {
        if (!this.selectedTransaction) return;

        // Use ErrorHandler confirmation if available
        if (typeof ErrorHandler !== 'undefined') {
            ErrorHandler.confirm(
                'Are you sure you want to detach this receipt? This cannot be undone.',
                () => this._doDetachReceipt(),
                { title: 'Detach Receipt', confirmText: 'Detach', danger: true }
            );
        } else {
            // Fallback to native confirm
            if (confirm('Are you sure you want to detach this receipt?')) {
                this._doDetachReceipt();
            }
        }
    }

    _doDetachReceipt() {
        this.updateField('Receipt File', '');
        this.updateField('r2_url', '');
        this.updateField('Review Status', '');
        this.preview?.showEmpty();
        this.showToast('Receipt detached', '🗑️');
    }

    // Preview controls
    togglePreview(show) {
        if (show && this.selectedTransaction) {
            this.preview?.load(this.selectedTransaction);
            this.previewContainer?.classList.add('active');
        } else {
            this.previewContainer?.classList.remove('active');
        }
    }

    closeAll() {
        this.previewContainer?.classList.remove('active');
        this.keyboard?.hideHelpModal();
        this.bulk?.close();
    }

    // Image controls (delegated to preview)
    rotateImage() { this.preview?.rotate(); }
    zoomIn() { this.preview?.zoomIn(); }
    zoomOut() { this.preview?.zoomOut(); }
    resetZoom() { this.preview?.resetZoom(); }

    // Filter controls
    focusSearch() {
        this.searchInput?.focus();
    }

    toggleFilterPanel() {
        this.filterContainer?.classList.toggle('active');
    }

    quickFilter(type, value) {
        switch (type) {
            case 'business':
                this.filter.setFilter('businessTypes', value === 'Unassigned' ? ['Unassigned', ''] : [value]);
                break;
            case 'receipt':
                if (value === 'unmatched') {
                    this.filter.setFilter('hasReceipt', false);
                }
                break;
            case 'status':
                if (value === 'needs-review') {
                    this.filter.setFilter('reviewStatus', 'needs_review');
                }
                break;
        }
    }

    // Bulk operations
    selectAll() {
        const ids = this.filteredTransactions.map(t => t._index);
        this.bulk.selectAll(ids);
    }

    selectSameMerchant() {
        if (!this.selectedTransaction) return;

        const merchant = (this.selectedTransaction['Chase Description'] || '').toLowerCase();
        const ids = this.filteredTransactions
            .filter(t => (t['Chase Description'] || '').toLowerCase() === merchant)
            .map(t => t._index);

        this.bulk.selectAll(ids);
        this.showToast(`Selected ${ids.length} transactions`, '✅');
    }

    openBulkActions() {
        this.bulk.open();
    }

    // Undo system
    saveUndoState(action, txIndex, oldData) {
        this.undoStack.push({
            action,
            txIndex,
            oldData,
            timestamp: Date.now()
        });

        if (this.undoStack.length > this.maxUndoStack) {
            this.undoStack.shift();
        }
    }

    async undo() {
        const entry = this.undoStack.pop();
        if (!entry) {
            this.showToast('Nothing to undo', '⚠️');
            return;
        }

        const tx = this.transactions.find(t => t._index === entry.txIndex);
        if (!tx) return;

        // Restore old data
        Object.assign(tx, entry.oldData);

        // Sync to server
        try {
            await fetch('/update_row', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    _index: entry.txIndex,
                    patch: entry.oldData
                })
            });

            this.renderTable();
            this.showToast(`Undid: ${entry.action}`, '↩️');
        } catch (e) {
            console.error('Undo failed:', e);
        }
    }

    save() {
        this.showToast('Changes auto-saved', '✅');
    }

    // Export
    exportSelected() {
        const selected = this.bulk.getSelectedTransactions();
        if (selected.length > 0) {
            this.bulk.exportCSV(selected);
        } else {
            this.showToast('No transactions selected', '⚠️');
        }
    }

    // Quick viewer (popup)
    openQuickViewer() {
        if (!this.selectedTransaction) {
            this.showToast('Select a transaction first', '⚠️');
            return;
        }
        this.togglePreview(true);
    }

    // Event callbacks
    onTransactionApproved() {
        this.navigate(1);  // Move to next transaction
    }

    onFieldChanged(e) {
        // Sync changes back to main data
        const { transaction, type, status } = e;
        if (transaction) {
            this.updateRowInPlace(transaction);
        }
    }

    focusTable() {
        this.tableContainer?.focus();
    }

    // Stats update
    updateStats() {
        const stats = {
            total: this.transactions.length,
            filtered: this.filteredTransactions.length,
            withReceipts: this.filteredTransactions.filter(t => t['Receipt File'] || t.r2_url).length,
            needsReview: this.filteredTransactions.filter(t =>
                !t['Review Status'] || t['Review Status'] === 'needs_review'
            ).length,
        };

        // Emit stats event
        document.dispatchEvent(new CustomEvent('statsUpdated', { detail: stats }));
    }

    // Refresh
    refresh() {
        this.applyFilters();
    }

    // Utilities
    formatDate(dateStr) {
        if (!dateStr) return '—';
        try {
            const d = new Date(dateStr);
            return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
        } catch {
            return dateStr;
        }
    }

    formatAmount(amount) {
        if (!amount) return '$0.00';
        const num = parseFloat(amount);
        const formatted = Math.abs(num).toLocaleString('en-US', {
            style: 'currency',
            currency: 'USD'
        });
        return num < 0 ? `-${formatted}` : formatted;
    }

    getReceiptIndicator(tx) {
        const hasReceipt = !!(tx['Receipt File'] || tx.r2_url || tx.receipt_url);
        const validation = tx.receipt_validation_status;

        if (!hasReceipt) {
            if (tx['Review Status'] === 'not needed') {
                return '<span class="receipt-badge not-needed">—</span>';
            }
            return '<span class="receipt-badge missing">✗</span>';
        }

        if (validation === 'verified') {
            return '<span class="receipt-badge verified">✓</span>';
        }
        if (validation === 'mismatch') {
            return '<span class="receipt-badge mismatch">⚠</span>';
        }

        return '<span class="receipt-badge has-receipt">🧾</span>';
    }

    getConfidenceBadge(tx) {
        const confidence = Math.round(parseFloat(tx['AI Confidence'] || tx.ai_confidence || 0));
        if (!confidence) return '<span class="confidence-badge none">—</span>';

        let cls = 'low';
        if (confidence >= 90) cls = 'high';
        else if (confidence >= 70) cls = 'medium';

        return `<span class="confidence-badge ${cls}">${confidence}%</span>`;
    }

    getBusinessBadge(type) {
        const badges = {
            'Down Home': '<span class="biz-badge down-home">🏠 DH</span>',
            'Music City Rodeo': '<span class="biz-badge mcr">🤠 MCR</span>',
            'Personal': '<span class="biz-badge personal">👤 Personal</span>',
            'EM.co': '<span class="biz-badge emco">🏢 EM.co</span>',
        };
        return badges[type] || '<span class="biz-badge unassigned">—</span>';
    }

    getStatusBadge(status) {
        const badges = {
            'good': '<span class="status-badge good">✓ Good</span>',
            'approved': '<span class="status-badge good">✓ Approved</span>',
            'bad': '<span class="status-badge bad">✗ Bad</span>',
            'flagged': '<span class="status-badge bad">🚩 Flagged</span>',
            'not needed': '<span class="status-badge not-needed">— Not Needed</span>',
        };
        return badges[status] || '<span class="status-badge pending">⏳ Pending</span>';
    }

    escapeHtml(str) {
        if (!str) return '';
        return str.replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }

    showToast(message, icon = 'ℹ️', duration = 3000) {
        // Find or create toast container
        let container = document.querySelector('.toast-container');
        if (!container) {
            container = document.createElement('div');
            container.className = 'toast-container';
            document.body.appendChild(container);
        }

        const toast = document.createElement('div');
        toast.className = 'toast';
        // SECURITY: Escape message to prevent XSS
        toast.innerHTML = `<span class="toast-icon">${icon}</span><span class="toast-message">${this.escapeHtml(message)}</span>`;

        container.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => toast.classList.add('show'));

        // Remove after duration
        setTimeout(() => {
            toast.classList.remove('show');
            setTimeout(() => toast.remove(), 300);
        }, duration);
    }

    // Debounce utility
    debounce(key, fn, delay) {
        this._debounceTimers = this._debounceTimers || {};

        if (this._debounceTimers[key]) {
            clearTimeout(this._debounceTimers[key]);
        }

        this._debounceTimers[key] = setTimeout(fn, delay);
    }

    // Public getters
    getAllTransactions() {
        return this.transactions;
    }

    getFilteredTransactions() {
        return this.filteredTransactions;
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TransactionReviewInterface;
}

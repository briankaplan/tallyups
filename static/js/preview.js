/**
 * Receipt Preview Panel
 * =====================
 * Fast, feature-rich receipt preview with zoom/pan, OCR data, and AI notes.
 * Uses ImageUtils for unified image handling and fallbacks.
 */

class ReceiptPreview {
    constructor(container) {
        this.container = container;
        this.currentTransaction = null;
        this.panzoomInstance = null;
        this.rotation = 0;
        this.isLoading = false;
        this.imageLoaded = false;

        // Preload Panzoom library if available
        this.panzoomReady = typeof Panzoom !== 'undefined';

        this.init();
    }

    init() {
        if (!this.container) return;

        this.container.innerHTML = this.getTemplate();
        this.bindElements();
        this.bindEvents();
    }

    getTemplate() {
        return `
            <div class="preview-panel">
                <!-- Header -->
                <div class="preview-header">
                    <div class="preview-title">
                        <span class="preview-icon">🧾</span>
                        <span class="preview-merchant">No Transaction Selected</span>
                    </div>
                    <div class="preview-actions">
                        <button class="preview-btn" data-action="rotate" title="Rotate (Shift+R)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M23 4v6h-6M1 20v-6h6"/>
                                <path d="M3.51 9a9 9 0 0114.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0020.49 15"/>
                            </svg>
                        </button>
                        <button class="preview-btn" data-action="zoom-in" title="Zoom In (+)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M11 8v6M8 11h6"/>
                            </svg>
                        </button>
                        <button class="preview-btn" data-action="zoom-out" title="Zoom Out (-)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35M8 11h6"/>
                            </svg>
                        </button>
                        <button class="preview-btn" data-action="reset" title="Reset (0)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M3 12a9 9 0 109-9 9.75 9.75 0 00-6.74 2.74L3 8"/>
                                <path d="M3 3v5h5"/>
                            </svg>
                        </button>
                        <button class="preview-btn close" data-action="close" title="Close (Esc)">
                            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M18 6L6 18M6 6l12 12"/>
                            </svg>
                        </button>
                    </div>
                </div>

                <!-- Receipt Image -->
                <div class="preview-image-container">
                    <div class="preview-loading">
                        <div class="spinner"></div>
                        <span>Loading receipt...</span>
                    </div>
                    <div class="preview-empty">
                        <div class="empty-icon">📭</div>
                        <span>No receipt attached</span>
                        <button class="attach-btn" data-action="attach">Attach Receipt</button>
                    </div>
                    <div class="preview-image-wrapper">
                        <img class="preview-image" alt="Receipt" />
                    </div>
                </div>

                <!-- Transaction Data -->
                <div class="preview-data">
                    <!-- Match Confidence -->
                    <div class="match-section">
                        <div class="match-header">
                            <span class="match-label">Match Confidence</span>
                            <span class="match-value">—</span>
                        </div>
                        <div class="confidence-bar">
                            <div class="confidence-fill" style="--confidence: 0%"></div>
                        </div>
                        <div class="match-reasons"></div>
                    </div>

                    <!-- OCR Data -->
                    <div class="ocr-section">
                        <h4>📋 Extracted Data</h4>
                        <div class="ocr-grid">
                            <div class="ocr-row">
                                <label>Merchant:</label>
                                <span class="ocr-value" data-field="merchant">—</span>
                            </div>
                            <div class="ocr-row">
                                <label>Amount:</label>
                                <span class="ocr-value" data-field="amount">—</span>
                            </div>
                            <div class="ocr-row">
                                <label>Date:</label>
                                <span class="ocr-value" data-field="date">—</span>
                            </div>
                            <div class="ocr-row">
                                <label>Category:</label>
                                <span class="ocr-value" data-field="category">—</span>
                            </div>
                        </div>
                    </div>

                    <!-- Business Type -->
                    <div class="business-section">
                        <h4>🏢 Business Type</h4>
                        <div class="business-buttons">
                            <button class="biz-btn" data-business="Down Home">
                                <span class="biz-icon">🏠</span> Down Home
                            </button>
                            <button class="biz-btn" data-business="Music City Rodeo">
                                <span class="biz-icon">🤠</span> MCR
                            </button>
                            <button class="biz-btn" data-business="Personal">
                                <span class="biz-icon">👤</span> Personal
                            </button>
                            <button class="biz-btn" data-business="EM.co">
                                <span class="biz-icon">🏢</span> EM.co
                            </button>
                        </div>
                    </div>

                    <!-- Review Status -->
                    <div class="status-section">
                        <h4>✓ Review Status</h4>
                        <div class="status-buttons">
                            <button class="status-btn good" data-status="good" title="Mark Good (g)">
                                ✓ Good
                            </button>
                            <button class="status-btn bad" data-status="bad" title="Mark Bad (b)">
                                ✗ Bad
                            </button>
                            <button class="status-btn not-needed" data-status="not needed" title="Not Needed">
                                — Not Needed
                            </button>
                        </div>
                    </div>

                    <!-- AI Note -->
                    <div class="note-section">
                        <div class="note-header">
                            <h4>📝 AI Note</h4>
                            <button class="regenerate-btn" data-action="regenerate" title="Regenerate (Shift+J)">
                                🔄 Regenerate
                            </button>
                        </div>
                        <textarea class="note-input" placeholder="Enter expense description..."></textarea>
                        <div class="note-meta">
                            <span class="note-confidence"></span>
                            <span class="note-sources"></span>
                        </div>
                    </div>

                    <!-- Quick Actions -->
                    <div class="quick-actions">
                        <button class="action-btn primary" data-action="approve">
                            ✓ Approve
                        </button>
                        <button class="action-btn danger" data-action="detach">
                            ✗ Detach Receipt
                        </button>
                    </div>
                </div>
            </div>
        `;
    }

    bindElements() {
        this.panel = this.container.querySelector('.preview-panel');
        this.header = this.container.querySelector('.preview-header');
        this.merchantEl = this.container.querySelector('.preview-merchant');
        this.imageContainer = this.container.querySelector('.preview-image-container');
        this.imageWrapper = this.container.querySelector('.preview-image-wrapper');
        this.image = this.container.querySelector('.preview-image');
        this.loadingEl = this.container.querySelector('.preview-loading');
        this.emptyEl = this.container.querySelector('.preview-empty');
        this.dataEl = this.container.querySelector('.preview-data');
        this.noteInput = this.container.querySelector('.note-input');
        this.confidenceBar = this.container.querySelector('.confidence-fill');
        this.matchValue = this.container.querySelector('.match-value');
        this.matchReasons = this.container.querySelector('.match-reasons');
    }

    bindEvents() {
        // Action buttons
        this.container.querySelectorAll('[data-action]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const action = e.currentTarget.dataset.action;
                this.handleAction(action);
            });
        });

        // Business type buttons
        this.container.querySelectorAll('[data-business]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const businessType = e.currentTarget.dataset.business;
                this.setBusinessType(businessType);
            });
        });

        // Status buttons
        this.container.querySelectorAll('[data-status]').forEach(btn => {
            btn.addEventListener('click', (e) => {
                const status = e.currentTarget.dataset.status;
                this.setReviewStatus(status);
            });
        });

        // Note input - debounced save
        let noteTimeout;
        this.noteInput?.addEventListener('input', (e) => {
            clearTimeout(noteTimeout);
            noteTimeout = setTimeout(() => {
                this.saveNote(e.target.value);
            }, 500);
        });

        // Image load events
        this.image?.addEventListener('load', () => this.onImageLoad());
        this.image?.addEventListener('error', () => this.onImageError());

        // Keyboard events within preview
        this.container.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') {
                this.close();
            }
        });
    }

    handleAction(action) {
        switch (action) {
            case 'rotate':
                this.rotate();
                break;
            case 'zoom-in':
                this.zoomIn();
                break;
            case 'zoom-out':
                this.zoomOut();
                break;
            case 'reset':
                this.resetZoom();
                break;
            case 'close':
                this.close();
                break;
            case 'attach':
                this.attachReceipt();
                break;
            case 'regenerate':
                this.regenerateNote();
                break;
            case 'approve':
                this.approve();
                break;
            case 'detach':
                this.detachReceipt();
                break;
        }
    }

    // Load transaction into preview
    async load(transaction) {
        if (!transaction) {
            this.clear();
            return;
        }

        this.currentTransaction = transaction;
        this.rotation = 0;

        // Update header
        const merchant = transaction['mi_merchant'] || transaction['Chase Description'] || 'Unknown Merchant';
        this.merchantEl.textContent = merchant;

        // Update OCR data
        this.updateOCRData(transaction);

        // Update business type buttons
        this.updateBusinessButtons(transaction['Business Type']);

        // Update status buttons
        this.updateStatusButtons(transaction['Review Status']);

        // Update confidence
        this.updateConfidence(transaction);

        // Update note
        this.updateNote(transaction);

        // Load receipt image
        this.loadReceiptImage(transaction);

        // Show panel
        this.container.classList.add('active');
    }

    loadReceiptImage(transaction) {
        // Get receipt URL
        const receiptUrl = this.getReceiptUrl(transaction);

        if (!receiptUrl) {
            this.showEmpty();
            return;
        }

        this.showLoading();

        // Set image source
        this.image.src = receiptUrl;
    }

    getReceiptUrl(transaction) {
        // Use unified ImageUtils if available, otherwise fallback to inline logic
        if (typeof ImageUtils !== 'undefined') {
            return ImageUtils.getReceiptUrl(transaction);
        }

        // Fallback: Priority: r2_url > R2 URL > receipt_url > Receipt File
        if (transaction.r2_url) {
            return transaction.r2_url;
        }
        if (transaction['R2 URL']) {
            return transaction['R2 URL'];
        }
        if (transaction.receipt_url) {
            return transaction.receipt_url;
        }
        if (transaction['Receipt File']) {
            return `/receipts/${transaction['Receipt File']}`;
        }
        return null;
    }

    onImageLoad() {
        this.isLoading = false;
        this.imageLoaded = true;

        this.hideLoading();
        this.hideEmpty();
        this.showImage();

        // Initialize panzoom
        this.initPanzoom();

        // Auto-rotate landscape images
        if (this.image.naturalWidth > this.image.naturalHeight * 1.3) {
            this.rotation = 90;
            this.applyRotation();
        }
    }

    onImageError() {
        this.isLoading = false;
        this.imageLoaded = false;

        // Use ImageUtils fallback chain if available
        if (typeof ImageUtils !== 'undefined' && this.currentTransaction) {
            const fallbacks = ImageUtils.buildFallbackChain(this.currentTransaction);
            const currentUrl = this.image.src;
            const currentIndex = fallbacks.findIndex(url => currentUrl.includes(url) || url.includes(new URL(currentUrl).pathname));

            if (currentIndex !== -1 && currentIndex < fallbacks.length - 1) {
                console.warn(`Image load failed: ${currentUrl}, trying fallback...`);
                this.image.src = fallbacks[currentIndex + 1];
                return;
            }
        }

        // Legacy fallback: try local file
        if (this.currentTransaction?.['Receipt File'] && this.image.src.includes('r2')) {
            this.image.src = `/receipts/${this.currentTransaction['Receipt File']}`;
            return;
        }

        this.hideLoading();
        this.showEmpty();
    }

    initPanzoom() {
        if (!this.panzoomReady || !this.image) return;

        // Destroy existing instance
        if (this.panzoomInstance) {
            this.panzoomInstance.destroy();
        }

        try {
            this.panzoomInstance = Panzoom(this.image, {
                maxScale: 5,
                minScale: 0.5,
                contain: 'outside',
                canvas: true,
            });

            // Enable wheel zoom
            this.imageWrapper?.addEventListener('wheel', this.panzoomInstance.zoomWithWheel);
        } catch (e) {
            console.warn('Panzoom initialization failed:', e);
        }
    }

    // Update UI sections
    updateOCRData(tx) {
        const fields = {
            merchant: tx['mi_merchant'] || tx['ai_receipt_merchant'] || '—',
            amount: this.formatAmount(tx['ai_receipt_total'] || tx['Chase Amount']),
            date: tx['ai_receipt_date'] || tx['Chase Date'] || '—',
            category: tx['mi_category'] || tx['Chase Category'] || '—',
        };

        for (const [field, value] of Object.entries(fields)) {
            const el = this.container.querySelector(`[data-field="${field}"]`);
            if (el) el.textContent = value;
        }
    }

    updateBusinessButtons(currentType) {
        this.container.querySelectorAll('[data-business]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.business === currentType);
        });
    }

    updateStatusButtons(currentStatus) {
        this.container.querySelectorAll('[data-status]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.status === currentStatus);
        });
    }

    updateConfidence(tx) {
        const confidence = parseFloat(tx['AI Confidence'] || tx.ai_confidence || 0);
        const percent = Math.min(100, Math.round(confidence));

        this.confidenceBar.style.setProperty('--confidence', `${percent}%`);
        this.matchValue.textContent = `${percent}%`;

        // Update color based on confidence
        let color = 'var(--ok)';
        if (percent < 50) color = 'var(--bad)';
        else if (percent < 80) color = 'var(--warn)';
        this.confidenceBar.style.background = color;

        // Update match reasons
        this.updateMatchReasons(tx, percent);
    }

    updateMatchReasons(tx, confidence) {
        const reasons = [];

        // Merchant match
        if (tx['mi_merchant'] && tx['Chase Description']) {
            const match = tx['mi_merchant'].toLowerCase().includes(tx['Chase Description'].toLowerCase().substring(0, 5));
            reasons.push({
                text: 'Merchant',
                status: match ? 'good' : 'warn',
                icon: match ? '✓' : '⚠'
            });
        }

        // Amount match
        const txAmount = Math.abs(parseFloat(tx['Chase Amount']) || 0);
        const receiptAmount = Math.abs(parseFloat(tx['ai_receipt_total']) || 0);
        if (receiptAmount > 0) {
            const amountMatch = Math.abs(txAmount - receiptAmount) < 1;
            reasons.push({
                text: 'Amount',
                status: amountMatch ? 'good' : 'bad',
                icon: amountMatch ? '✓' : '✗'
            });
        }

        // Date match
        if (tx['ai_receipt_date'] && tx['Chase Date']) {
            const receiptDate = new Date(tx['ai_receipt_date']);
            const txDate = new Date(tx['Chase Date']);
            const daysDiff = Math.abs((receiptDate - txDate) / (1000 * 60 * 60 * 24));

            let status = 'good', icon = '✓';
            if (daysDiff > 7) { status = 'bad'; icon = '✗'; }
            else if (daysDiff > 2) { status = 'warn'; icon = '⚠'; }

            reasons.push({
                text: `Date ${daysDiff > 0 ? `+${Math.round(daysDiff)}d` : ''}`,
                status,
                icon
            });
        }

        this.matchReasons.innerHTML = reasons.map(r => `
            <span class="reason ${r.status}">${r.icon} ${r.text}</span>
        `).join('');
    }

    updateNote(tx) {
        const note = tx['AI Note'] || tx.Notes || '';
        this.noteInput.value = note;

        // Update meta
        const confidence = tx.note_confidence || '';
        const sources = tx.note_data_sources || [];

        const confidenceEl = this.container.querySelector('.note-confidence');
        const sourcesEl = this.container.querySelector('.note-sources');

        if (confidenceEl && confidence) {
            confidenceEl.textContent = `Confidence: ${Math.round(confidence * 100)}%`;
        }
        if (sourcesEl && sources.length) {
            sourcesEl.textContent = `Sources: ${sources.join(', ')}`;
        }
    }

    // Actions
    async setBusinessType(type) {
        if (!this.currentTransaction) return;

        this.updateBusinessButtons(type);

        try {
            await this.updateField('Business Type', type);
            this.emit('businessTypeChanged', { transaction: this.currentTransaction, type });
        } catch (e) {
            console.error('Failed to update business type:', e);
        }
    }

    async setReviewStatus(status) {
        if (!this.currentTransaction) return;

        this.updateStatusButtons(status);

        try {
            await this.updateField('Review Status', status);
            this.emit('reviewStatusChanged', { transaction: this.currentTransaction, status });
        } catch (e) {
            console.error('Failed to update review status:', e);
        }
    }

    async saveNote(note) {
        if (!this.currentTransaction) return;

        try {
            await this.updateField('AI Note', note);
            this.emit('noteChanged', { transaction: this.currentTransaction, note });
        } catch (e) {
            console.error('Failed to save note:', e);
        }
    }

    async updateField(field, value) {
        const idx = this.currentTransaction._index;

        const res = await fetch('/update_row', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                _index: idx,
                patch: { [field]: value }
            })
        });

        if (!res.ok) throw new Error('Update failed');

        // Update local transaction
        this.currentTransaction[field] = value;
    }

    async regenerateNote() {
        if (!this.currentTransaction) return;

        this.noteInput.placeholder = 'Generating AI note...';
        this.noteInput.disabled = true;

        try {
            const res = await fetch('/api/notes/generate', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ _index: this.currentTransaction._index })
            });

            const data = await res.json();
            if (data.ok && data.note) {
                this.noteInput.value = data.note;
                this.currentTransaction['AI Note'] = data.note;
                this.emit('noteRegenerated', { transaction: this.currentTransaction, result: data });
            }
        } catch (e) {
            console.error('Failed to regenerate note:', e);
        } finally {
            this.noteInput.placeholder = 'Enter expense description...';
            this.noteInput.disabled = false;
        }
    }

    async approve() {
        await this.setReviewStatus('good');
        this.emit('approved', { transaction: this.currentTransaction });
    }

    async detachReceipt() {
        if (!this.currentTransaction) return;

        try {
            await this.updateField('Receipt File', '');
            await this.updateField('r2_url', '');
            await this.updateField('Review Status', '');

            this.showEmpty();
            this.emit('receiptDetached', { transaction: this.currentTransaction });
        } catch (e) {
            console.error('Failed to detach receipt:', e);
        }
    }

    attachReceipt() {
        this.emit('attachRequested', { transaction: this.currentTransaction });
    }

    // Zoom/Pan controls
    rotate() {
        this.rotation = (this.rotation + 90) % 360;
        this.applyRotation();
    }

    applyRotation() {
        if (this.image) {
            this.image.style.transform = `rotate(${this.rotation}deg)`;
        }
    }

    zoomIn() {
        this.panzoomInstance?.zoomIn();
    }

    zoomOut() {
        this.panzoomInstance?.zoomOut();
    }

    resetZoom() {
        this.panzoomInstance?.reset();
        this.rotation = 0;
        this.applyRotation();
    }

    // State management
    showLoading() {
        this.loadingEl?.classList.add('visible');
        this.emptyEl?.classList.remove('visible');
        this.imageWrapper?.classList.remove('visible');
    }

    hideLoading() {
        this.loadingEl?.classList.remove('visible');
    }

    showEmpty() {
        this.emptyEl?.classList.add('visible');
        this.imageWrapper?.classList.remove('visible');
    }

    hideEmpty() {
        this.emptyEl?.classList.remove('visible');
    }

    showImage() {
        this.imageWrapper?.classList.add('visible');
    }

    clear() {
        this.currentTransaction = null;
        this.merchantEl.textContent = 'No Transaction Selected';
        this.showEmpty();
        this.container.classList.remove('active');
    }

    close() {
        this.container.classList.remove('active');
        this.emit('closed');
    }

    // Utilities
    formatAmount(amount) {
        if (!amount) return '—';
        const num = parseFloat(amount);
        if (isNaN(num)) return amount;
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(Math.abs(num));
    }

    // Event emitter
    emit(event, data) {
        this.container.dispatchEvent(new CustomEvent(event, { detail: data, bubbles: true }));
    }

    on(event, callback) {
        this.container.addEventListener(event, (e) => callback(e.detail));
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ReceiptPreview;
}

/**
 * Receipt Library - World-Class Receipt Management
 * =================================================
 * High-performance receipt library with virtual scrolling,
 * natural language search, and keyboard navigation.
 */

(function() {
  'use strict';

  // ============================================
  // State Management
  // ============================================

  // Cache buster for thumbnail URLs - ensures fresh load on session/page load
  const cacheBuster = `cb=${Date.now()}`;

  // Helper to add cache buster to thumbnail URLs for fresh loading
  function getThumbnailUrl(url) {
    if (!url) return '';
    // Use ImageUtils if available for URL fixing
    if (typeof ImageUtils !== 'undefined') {
      url = ImageUtils.fixUrl(url);
    }
    // Add cache buster to force reload (fixes cached login thumbnail issue)
    const separator = url.includes('?') ? '&' : '?';
    return `${url}${separator}${cacheBuster}`;
  }

  // Helper to get receipt URL from receipt object using ImageUtils (prioritizes r2_url)
  function getReceiptImageUrl(receipt) {
    if (typeof ImageUtils !== 'undefined') {
      return ImageUtils.getReceiptUrl(receipt);
    }
    // Fallback - prioritize r2_url over receipt_url
    return receipt.r2_url || receipt.thumbnail_url || receipt.receipt_url || receipt.receipt_image_url || '';
  }

  const state = {
    receipts: [],
    filteredReceipts: [],
    selectedReceipts: new Set(),
    currentReceipt: null,
    currentIndex: -1,

    // View state
    viewMode: 'grid', // grid, list, timeline
    sortBy: 'date_desc',

    // Filters
    filters: {
      search: '',
      source: 'all',
      status: 'all',
      business: 'all',
      dateFrom: null,
      dateTo: null,
      amountMin: null,
      amountMax: null
    },

    // Pagination for virtual scrolling
    page: 1,
    pageSize: 200,  // Increased from 50 for faster loading
    hasMore: true,
    isLoading: false,

    // Counts
    counts: {
      all: 0,
      favorites: 0,
      recent: 0,
      review: 0,
      duplicates: 0,
      verified: 0,
      matched: 0,
      processing: 0,
      gmail: 0,
      scanner: 0,
      upload: 0,
      downHome: 0,
      mcr: 0,
      personal: 0,
      ceo: 0
    }
  };

  // ============================================
  // DOM Elements
  // ============================================

  const $ = (id) => document.getElementById(id);
  const $$ = (selector) => document.querySelectorAll(selector);

  const elements = {
    // Main containers
    sidebar: $('sidebar'),
    receiptsContainer: $('receipts-container'),
    receiptGrid: $('receipt-grid'),
    receiptList: $('receipt-list'),
    timelineView: $('timeline-view'),
    loading: $('loading'),
    emptyState: $('empty-state'),

    // Header
    menuBtn: $('menu-btn'),
    searchInput: $('search-input'),
    searchClear: $('search-clear'),
    searchShortcut: $('search-shortcut'),

    // Toolbar
    resultsCount: $('results-count'),
    totalAmount: $('total-amount'),

    // Modals
    detailModal: $('detail-modal'),
    filterModal: $('filter-modal'),
    sortModal: $('sort-modal'),
    uploadModal: $('upload-modal'),
    shortcutsModal: $('shortcuts-modal'),

    // Detail modal elements
    detailClose: $('detail-close'),
    detailImage: $('detail-image'),
    detailImg: $('detail-img'),
    detailMerchant: $('detail-merchant'),
    detailSource: $('detail-source'),
    detailAmount: $('detail-amount'),
    detailDate: $('detail-date'),
    detailBusiness: $('detail-business'),
    detailStatus: $('detail-status'),
    detailNotes: $('detail-notes'),
    detailNotesText: $('detail-notes-text'),
    detailTags: $('detail-tags'),

    // Filter modal elements
    filterDateFrom: $('filter-date-from'),
    filterDateTo: $('filter-date-to'),
    filterAmountMin: $('filter-amount-min'),
    filterAmountMax: $('filter-amount-max'),

    // Upload
    uploadDropzone: $('upload-dropzone'),
    fileInput: $('file-input'),

    // Toast
    toastContainer: $('toast-container')
  };

  // ============================================
  // API Functions
  // ============================================

  const API = {
    baseUrl: '/api/library',

    async fetchReceipts(params = {}) {
      const queryParams = new URLSearchParams();

      if (state.filters.search) queryParams.append('q', state.filters.search);
      if (state.filters.source !== 'all') queryParams.append('source', state.filters.source);
      if (state.filters.status !== 'all') queryParams.append('status', state.filters.status);
      if (state.filters.business !== 'all') queryParams.append('business_type', state.filters.business);
      if (state.filters.dateFrom) queryParams.append('date_from', state.filters.dateFrom);
      if (state.filters.dateTo) queryParams.append('date_to', state.filters.dateTo);
      if (state.filters.amountMin) queryParams.append('amount_min', state.filters.amountMin);
      if (state.filters.amountMax) queryParams.append('amount_max', state.filters.amountMax);

      queryParams.append('sort', state.sortBy);
      queryParams.append('page', params.page || state.page);
      queryParams.append('limit', state.pageSize);

      try {
        const response = await fetch(`${this.baseUrl}/receipts?${queryParams}`, {
          credentials: 'include'
        });

        if (response.status === 401) {
          window.location.href = '/login?next=/library';
          return null;
        }

        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        showToast('Failed to load receipts', 'error');
        return null;
      }
    },

    async getReceipt(uuid) {
      try {
        const response = await fetch(`${this.baseUrl}/receipts/${uuid}`, {
          credentials: 'include'
        });
        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        return null;
      }
    },

    async updateReceipt(uuid, data) {
      try {
        const response = await fetch(`${this.baseUrl}/receipts/${uuid}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(data),
          credentials: 'include'
        });
        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        return null;
      }
    },

    async deleteReceipt(uuid) {
      try {
        const response = await fetch(`${this.baseUrl}/receipts/${uuid}`, {
          method: 'DELETE',
          credentials: 'include'
        });
        return response.ok;
      } catch (error) {
        console.error('API Error:', error);
        return false;
      }
    },

    async uploadReceipts(files, businessType = 'auto') {
      const formData = new FormData();
      files.forEach(file => formData.append('files', file));
      formData.append('business_type', businessType);

      try {
        const response = await fetch(`${this.baseUrl}/upload`, {
          method: 'POST',
          body: formData,
          credentials: 'include'
        });
        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        return null;
      }
    },

    async getStats() {
      try {
        const response = await fetch(`${this.baseUrl}/stats`, {
          credentials: 'include'
        });
        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        return null;
      }
    },

    async search(query) {
      try {
        const response = await fetch(`${this.baseUrl}/search?q=${encodeURIComponent(query)}`, {
          credentials: 'include'
        });
        return await response.json();
      } catch (error) {
        console.error('API Error:', error);
        return null;
      }
    }
  };

  // ============================================
  // Rendering Functions
  // ============================================

  function renderReceipts() {
    const receipts = state.filteredReceipts;

    if (receipts.length === 0) {
      showEmptyState();
      return;
    }

    hideEmptyState();

    switch (state.viewMode) {
      case 'grid':
        renderGridView(receipts);
        break;
      case 'list':
        renderListView(receipts);
        break;
      case 'timeline':
        renderTimelineView(receipts);
        break;
    }

    updateViewVisibility();
    updateStats();
  }

  function renderGridView(receipts) {
    elements.receiptGrid.innerHTML = receipts.map((receipt, index) => `
      <div class="receipt-card ${state.selectedReceipts.has(receipt.uuid) ? 'selected' : ''}"
           data-uuid="${receipt.uuid}"
           data-index="${index}"
           onclick="handleReceiptClick(event, ${index})"
           tabindex="0">
        <div class="receipt-thumb ${getReceiptImageUrl(receipt) ? '' : 'no-image'}">
          ${getReceiptImageUrl(receipt) ?
            `<img src="${getThumbnailUrl(getReceiptImageUrl(receipt))}"
                  alt="${escapeHtml(receipt.merchant_name || 'Receipt')}"
                  loading="lazy"
                  onload="this.classList.add('loaded')"
                  onerror="this.parentElement.classList.add('no-image'); this.remove();">` :
            `<svg class="placeholder" width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path>
              <rect x="9" y="3" width="6" height="4" rx="1"></rect>
            </svg>`
          }
          <div class="receipt-badges">
            ${getStatusBadge(receipt)}
            ${getSourceBadge(receipt)}
          </div>
          <div class="receipt-checkbox">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3">
              <polyline points="20 6 9 17 4 12"></polyline>
            </svg>
          </div>
        </div>
        <div class="receipt-info">
          <div class="receipt-merchant">${escapeHtml(receipt.merchant_name || 'Unknown')}</div>
          <div class="receipt-meta">
            <span class="receipt-amount ${receipt.amount < 0 ? 'refund' : ''}">${formatCurrency(receipt.amount)}</span>
            <span class="receipt-date">${formatDate(receipt.receipt_date)}</span>
          </div>
          ${receipt.business_type && receipt.business_type !== 'unknown' ? `
            <div class="receipt-business">
              <span class="business-dot ${receipt.business_type.replace('_', '-')}"></span>
              ${formatBusinessType(receipt.business_type)}
            </div>
          ` : ''}
        </div>
      </div>
    `).join('');
  }

  function renderListView(receipts) {
    elements.receiptList.innerHTML = receipts.map((receipt, index) => `
      <div class="list-item ${state.selectedReceipts.has(receipt.uuid) ? 'selected' : ''}"
           data-uuid="${receipt.uuid}"
           data-index="${index}"
           onclick="handleReceiptClick(event, ${index})"
           tabindex="0">
        <div class="list-thumb">
          ${getReceiptImageUrl(receipt) ?
            `<img src="${getThumbnailUrl(getReceiptImageUrl(receipt))}"
                  alt="${escapeHtml(receipt.merchant_name || 'Receipt')}"
                  loading="lazy"
                  onload="this.classList.add('loaded')">` :
            `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
              <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path>
              <rect x="9" y="3" width="6" height="4" rx="1"></rect>
            </svg>`
          }
        </div>
        <div class="list-info">
          <div class="list-merchant">${escapeHtml(receipt.merchant_name || 'Unknown')}</div>
          <div class="list-meta">
            <span>${formatDate(receipt.receipt_date)}</span>
            <span>${formatSource(receipt.source)}</span>
            ${receipt.business_type && receipt.business_type !== 'unknown' ?
              `<span>${formatBusinessType(receipt.business_type)}</span>` : ''}
          </div>
        </div>
        <div class="list-amount ${receipt.amount < 0 ? 'refund' : ''}">${formatCurrency(receipt.amount)}</div>
      </div>
    `).join('');
  }

  function renderTimelineView(receipts) {
    // Group receipts by date
    const grouped = {};
    receipts.forEach(receipt => {
      const date = receipt.receipt_date || 'Unknown Date';
      if (!grouped[date]) grouped[date] = [];
      grouped[date].push(receipt);
    });

    elements.timelineView.innerHTML = Object.entries(grouped).map(([date, items]) => `
      <div class="timeline-group">
        <div class="timeline-date">${formatFullDate(date)}</div>
        <div class="timeline-items">
          ${items.map((receipt, i) => `
            <div class="list-item"
                 data-uuid="${receipt.uuid}"
                 onclick="handleReceiptClick(event, ${receipts.indexOf(receipt)})"
                 tabindex="0">
              <div class="list-thumb">
                ${getReceiptImageUrl(receipt) ?
                  `<img src="${getThumbnailUrl(getReceiptImageUrl(receipt))}" alt="" loading="lazy" onload="this.classList.add('loaded')">` :
                  `<svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                    <path d="M9 5H7a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-2"></path>
                    <rect x="9" y="3" width="6" height="4" rx="1"></rect>
                  </svg>`
                }
              </div>
              <div class="list-info">
                <div class="list-merchant">${escapeHtml(receipt.merchant_name || 'Unknown')}</div>
                <div class="list-meta">
                  <span>${formatSource(receipt.source)}</span>
                </div>
              </div>
              <div class="list-amount">${formatCurrency(receipt.amount)}</div>
            </div>
          `).join('')}
        </div>
      </div>
    `).join('');
  }

  function updateViewVisibility() {
    elements.receiptGrid.classList.toggle('hidden', state.viewMode !== 'grid');
    elements.receiptList.classList.toggle('active', state.viewMode === 'list');
    elements.timelineView.classList.toggle('active', state.viewMode === 'timeline');
  }

  function updateStats() {
    const count = state.filteredReceipts.length;
    elements.resultsCount.textContent = `${count.toLocaleString()} receipt${count !== 1 ? 's' : ''}`;

    const total = state.filteredReceipts.reduce((sum, r) => sum + (parseFloat(r.amount) || 0), 0);
    elements.totalAmount.textContent = formatCurrency(total);
  }

  function updateCounts(data) {
    if (!data || !data.counts) return;

    const counts = data.counts;
    const setCount = (id, value) => {
      const el = $(id);
      if (el) el.textContent = value || 0;
    };

    setCount('count-all', counts.total);
    setCount('count-favorites', counts.favorites);
    setCount('count-recent', counts.recent);
    setCount('count-review', counts.needs_review);
    setCount('count-duplicates', counts.duplicates);
    setCount('count-verified', counts.verified);
    setCount('count-matched', counts.matched);
    setCount('count-processing', counts.processing);
    setCount('count-gmail', counts.gmail);
    setCount('count-scanner', counts.scanner);
    setCount('count-upload', counts.upload);
    setCount('count-down-home', counts.down_home);
    setCount('count-mcr', counts.mcr);
    setCount('count-personal', counts.personal);
    setCount('count-ceo', counts.ceo);
  }

  // ============================================
  // Badge Helpers
  // ============================================

  function getStatusBadge(receipt) {
    const status = receipt.status || receipt.verification_status;
    if (!status || status === 'processing') return '';

    const badges = {
      'verified': '<span class="badge status verified">Verified</span>',
      'mismatch': '<span class="badge status mismatch">Mismatch</span>',
      'needs_review': '<span class="badge status needs-review">Review</span>',
      'matched': '<span class="badge status verified">Matched</span>'
    };

    return badges[status] || '';
  }

  function getSourceBadge(receipt) {
    const source = receipt.source || 'unknown';
    const labels = {
      'gmail_personal': 'Gmail',
      'gmail_mcr': 'Gmail',
      'gmail_down_home': 'Gmail',
      'scanner_mobile': 'Scan',
      'scanner_web': 'Scan',
      'manual_upload': 'Upload',
      'gmail': 'Gmail',
      'scanner': 'Scan'
    };

    const label = labels[source] || source;
    const sourceClass = source.includes('gmail') ? 'gmail' : (source.includes('scanner') ? 'scanner' : 'manual');

    return `<span class="badge source ${sourceClass}">${label}</span>`;
  }

  // ============================================
  // Detail Modal
  // ============================================

  function openDetailModal(receipt, index) {
    state.currentReceipt = receipt;
    state.currentIndex = index;

    // Update modal content
    elements.detailMerchant.textContent = receipt.merchant_name || 'Unknown';
    elements.detailSource.innerHTML = `
      <svg width="12" height="12" viewBox="0 0 24 24" fill="currentColor">
        <circle cx="12" cy="12" r="5"/>
      </svg>
      ${formatSource(receipt.source)} Receipt
    `;

    elements.detailAmount.textContent = formatCurrency(receipt.amount);
    elements.detailAmount.classList.toggle('refund', receipt.amount < 0);

    elements.detailDate.textContent = formatFullDate(receipt.receipt_date);
    elements.detailBusiness.textContent = formatBusinessType(receipt.business_type);
    elements.detailStatus.textContent = formatStatus(receipt.status);

    // Handle image - prioritize r2_url
    const imageUrl = getReceiptImageUrl(receipt);
    if (imageUrl) {
      elements.detailImage.classList.remove('no-image');
      elements.detailImg.src = imageUrl;
      elements.detailImg.style.display = 'block';
    } else {
      elements.detailImage.classList.add('no-image');
      elements.detailImg.style.display = 'none';
    }

    // AI Notes
    if (receipt.ai_description || receipt.ai_notes) {
      elements.detailNotes.style.display = 'block';
      elements.detailNotesText.textContent = receipt.ai_description || receipt.ai_notes;
    } else {
      elements.detailNotes.style.display = 'none';
    }

    // Linked Transaction
    const linkedField = document.getElementById('field-linked');
    const linkedValue = document.getElementById('detail-linked');
    if (receipt.transaction_id || receipt._index || receipt.matched_transaction_id) {
      const txId = receipt.transaction_id || receipt._index || receipt.matched_transaction_id;
      linkedField.style.display = 'flex';
      linkedValue.innerHTML = `Transaction #${txId} <a href="/reconcile?tx=${txId}" style="margin-left:8px;color:var(--accent);">View →</a>`;
    } else if (receipt.type === 'incoming' && receipt.status === 'accepted') {
      linkedField.style.display = 'flex';
      linkedValue.textContent = 'Accepted (pending match)';
    } else {
      linkedField.style.display = 'none';
    }

    // OCR Data
    const ocrField = document.getElementById('field-ocr');
    const ocrValue = document.getElementById('detail-ocr');
    if (receipt.ocr_merchant || receipt.ocr_amount || receipt.ocr_confidence) {
      ocrField.style.display = 'flex';
      const parts = [];
      if (receipt.ocr_merchant) parts.push(`Merchant: ${receipt.ocr_merchant}`);
      if (receipt.ocr_amount) parts.push(`Amount: $${receipt.ocr_amount}`);
      if (receipt.ocr_confidence) parts.push(`Confidence: ${Math.round(receipt.ocr_confidence * 100)}%`);
      ocrValue.textContent = parts.join(' | ');
    } else {
      ocrField.style.display = 'none';
    }

    // Tags
    const tagsHtml = (receipt.tags || []).map(tag =>
      `<span class="tag">${escapeHtml(tag)}</span>`
    ).join('');
    elements.detailTags.innerHTML = tagsHtml + '<span class="tag add-tag">+ Add tag</span>';

    // Show modal and backdrop
    elements.detailModal.classList.add('visible');
    const backdrop = document.getElementById('detail-backdrop');
    if (backdrop) backdrop.classList.add('visible');
    document.body.style.overflow = 'hidden';

    // Update URL without reload
    history.pushState({ receipt: receipt.uuid }, '', `/library?receipt=${receipt.uuid}`);
  }

  function closeDetailModal() {
    elements.detailModal.classList.remove('visible');
    const backdrop = document.getElementById('detail-backdrop');
    if (backdrop) backdrop.classList.remove('visible');
    document.body.style.overflow = '';
    state.currentReceipt = null;
    state.currentIndex = -1;

    // Update URL
    history.pushState({}, '', '/library');
  }

  // Expose as global function for onclick handlers
  window.closeDetailPanel = closeDetailModal;

  function navigateReceipt(direction) {
    const newIndex = state.currentIndex + direction;
    if (newIndex >= 0 && newIndex < state.filteredReceipts.length) {
      openDetailModal(state.filteredReceipts[newIndex], newIndex);
    }
  }

  // ============================================
  // Event Handlers
  // ============================================

  window.handleReceiptClick = function(event, index) {
    const receipt = state.filteredReceipts[index];
    if (!receipt) return;

    // Check if clicking checkbox area
    if (event.target.closest('.receipt-checkbox')) {
      toggleSelection(receipt.uuid);
      return;
    }

    // Shift+click for range selection
    if (event.shiftKey && state.currentIndex >= 0) {
      const start = Math.min(state.currentIndex, index);
      const end = Math.max(state.currentIndex, index);
      for (let i = start; i <= end; i++) {
        state.selectedReceipts.add(state.filteredReceipts[i].uuid);
      }
      renderReceipts();
      return;
    }

    // Ctrl/Cmd+click for multi-selection
    if (event.ctrlKey || event.metaKey) {
      toggleSelection(receipt.uuid);
      return;
    }

    // Normal click opens detail
    openDetailModal(receipt, index);
  };

  function toggleSelection(uuid) {
    if (state.selectedReceipts.has(uuid)) {
      state.selectedReceipts.delete(uuid);
    } else {
      state.selectedReceipts.add(uuid);
    }
    renderReceipts();
    updateSelectionUI();
  }

  function updateSelectionUI() {
    const count = state.selectedReceipts.size;
    // Update bulk action buttons visibility etc.
  }

  // ============================================
  // Search
  // ============================================

  let searchTimeout;

  function handleSearch(query) {
    clearTimeout(searchTimeout);

    // Update UI
    elements.searchClear.classList.toggle('visible', query.length > 0);
    elements.searchShortcut.style.display = query.length > 0 ? 'none' : 'block';

    // Debounce search
    searchTimeout = setTimeout(() => {
      state.filters.search = query;
      state.page = 1;
      loadReceipts();
    }, 300);
  }

  function clearSearch() {
    elements.searchInput.value = '';
    state.filters.search = '';
    elements.searchClear.classList.remove('visible');
    elements.searchShortcut.style.display = 'block';
    state.page = 1;
    loadReceipts();
  }

  // ============================================
  // Filters
  // ============================================

  function setFilter(type, value) {
    state.filters[type] = value;
    state.page = 1;
    loadReceipts();
    updateActiveFilters();
  }

  function updateActiveFilters() {
    // Update sidebar active states
    $$('.nav-item').forEach(item => {
      const filter = item.dataset.filter;
      if (!filter) return;

      let isActive = false;
      if (filter === 'all' && state.filters.source === 'all' && state.filters.status === 'all' && state.filters.business === 'all') {
        isActive = true;
      } else if (filter.startsWith('business:') && state.filters.business === filter.split(':')[1]) {
        isActive = true;
      } else if (filter.startsWith('status:') && state.filters.status === filter.split(':')[1]) {
        isActive = true;
      } else if (filter.startsWith('source:') && state.filters.source === filter.split(':')[1]) {
        isActive = true;
      }

      item.classList.toggle('active', isActive);
    });

    // Update filter chips
    $$('.filter-chip').forEach(chip => {
      const preset = chip.dataset.preset;
      const status = chip.dataset.status;
      const filter = chip.dataset.filter;

      let isActive = false;
      if (filter === 'all' && !state.filters.dateFrom && !state.filters.dateTo && state.filters.status === 'all') {
        isActive = true;
      } else if (status && state.filters.status === status) {
        isActive = true;
      }

      chip.classList.toggle('active', isActive);
    });
  }

  function applyDatePreset(preset) {
    const today = new Date();
    let from = null;
    let to = today.toISOString().split('T')[0];

    switch (preset) {
      case 'today':
        from = to;
        break;
      case 'week':
        const weekAgo = new Date(today);
        weekAgo.setDate(weekAgo.getDate() - 7);
        from = weekAgo.toISOString().split('T')[0];
        break;
      case 'month':
        const monthAgo = new Date(today);
        monthAgo.setMonth(monthAgo.getMonth() - 1);
        from = monthAgo.toISOString().split('T')[0];
        break;
      case 'quarter':
        const quarterAgo = new Date(today);
        quarterAgo.setDate(quarterAgo.getDate() - 90);
        from = quarterAgo.toISOString().split('T')[0];
        break;
      case 'year':
        from = `${today.getFullYear()}-01-01`;
        break;
      case 'all':
        from = null;
        to = null;
        break;
    }

    state.filters.dateFrom = from;
    state.filters.dateTo = to;
    state.page = 1;
    loadReceipts();
    updateActiveFilters();
  }

  // ============================================
  // Sorting
  // ============================================

  function setSort(sortBy) {
    state.sortBy = sortBy;
    state.page = 1;

    // Update UI
    $$('[data-sort]').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.sort === sortBy);
    });

    loadReceipts();
    closeModal(elements.sortModal);
  }

  // ============================================
  // View Toggle
  // ============================================

  function setViewMode(mode) {
    state.viewMode = mode;

    // Update buttons
    $$('.view-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.view === mode);
    });

    renderReceipts();
  }

  // ============================================
  // Upload
  // ============================================

  function handleFileUpload(files) {
    if (!files || files.length === 0) return;

    const validFiles = Array.from(files).filter(file => {
      const validTypes = ['image/jpeg', 'image/png', 'image/webp', 'image/heic', 'application/pdf'];
      return validTypes.includes(file.type) || file.name.match(/\.(jpg|jpeg|png|webp|heic|pdf)$/i);
    });

    if (validFiles.length === 0) {
      showToast('No valid files selected', 'error');
      return;
    }

    showToast(`Uploading ${validFiles.length} file${validFiles.length > 1 ? 's' : ''}...`, 'info');

    API.uploadReceipts(validFiles).then(result => {
      if (result && result.ok) {
        showToast(`Uploaded ${result.count} receipt${result.count > 1 ? 's' : ''}`, 'success');
        loadReceipts();
      } else {
        showToast('Upload failed', 'error');
      }
    });

    closeModal(elements.uploadModal);
  }

  // ============================================
  // Modals
  // ============================================

  function openModal(modal) {
    modal.classList.add('visible');
  }

  function closeModal(modal) {
    modal.classList.remove('visible');
  }

  // ============================================
  // Loading States
  // ============================================

  function showLoading() {
    elements.loading.style.display = 'flex';
    elements.receiptGrid.innerHTML = '';
    elements.receiptList.innerHTML = '';
    elements.timelineView.innerHTML = '';
    hideEmptyState();
  }

  function hideLoading() {
    elements.loading.style.display = 'none';
  }

  function showEmptyState(title = 'No receipts found', message = 'Try adjusting your filters or upload some receipts') {
    $('empty-title').textContent = title;
    $('empty-message').textContent = message;
    elements.emptyState.classList.remove('hidden');
  }

  function hideEmptyState() {
    elements.emptyState.classList.add('hidden');
  }

  // ============================================
  // Toast Notifications
  // ============================================

  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        ${type === 'success' ? '<polyline points="20 6 9 17 4 12"></polyline>' :
          type === 'error' ? '<circle cx="12" cy="12" r="10"></circle><line x1="15" y1="9" x2="9" y2="15"></line><line x1="9" y1="9" x2="15" y2="15"></line>' :
          '<circle cx="12" cy="12" r="10"></circle><line x1="12" y1="16" x2="12" y2="12"></line><line x1="12" y1="8" x2="12.01" y2="8"></line>'}
      </svg>
      <span>${escapeHtml(message)}</span>
    `;

    elements.toastContainer.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 300);
    }, 3000);
  }

  // ============================================
  // Utility Functions
  // ============================================

  function escapeHtml(str) {
    if (!str) return '';
    return String(str).replace(/[&<>"']/g, char => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    }[char]));
  }

  function formatCurrency(amount) {
    const num = parseFloat(amount) || 0;
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(Math.abs(num));
  }

  function formatDate(dateStr) {
    if (!dateStr) return 'No date';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
  }

  function formatFullDate(dateStr) {
    if (!dateStr) return 'No date';
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      weekday: 'long',
      month: 'long',
      day: 'numeric',
      year: 'numeric'
    });
  }

  function formatSource(source) {
    const sources = {
      'gmail_personal': 'Gmail',
      'gmail_mcr': 'Gmail MCR',
      'gmail_down_home': 'Gmail DH',
      'scanner_mobile': 'Mobile Scan',
      'scanner_web': 'Web Scan',
      'manual_upload': 'Upload',
      'gmail': 'Gmail',
      'scanner': 'Scanner',
      'import': 'Import'
    };
    return sources[source] || source || 'Unknown';
  }

  function formatBusinessType(type) {
    const types = {
      'down_home': 'Down Home',
      'mcr': 'Music City Rodeo',
      'personal': 'Personal',
      'ceo': 'CEO',
      'unknown': 'Unknown'
    };
    return types[type] || type || 'Unknown';
  }

  function formatStatus(status) {
    const statuses = {
      'processing': 'Processing',
      'ready': 'Ready',
      'matched': 'Matched',
      'verified': 'Verified',
      'duplicate': 'Duplicate',
      'rejected': 'Rejected',
      'archived': 'Archived'
    };
    return statuses[status] || status || 'Unknown';
  }

  // ============================================
  // Data Loading
  // ============================================

  async function loadReceipts() {
    if (state.isLoading) return;

    state.isLoading = true;
    showLoading();

    const data = await API.fetchReceipts();

    if (data && data.ok !== false) {
      state.receipts = data.receipts || data.results || [];
      state.filteredReceipts = state.receipts;
      state.hasMore = data.has_more || false;

      updateCounts(data);
    } else if (!data) {
      // Handle auth redirect
      return;
    }

    hideLoading();
    renderReceipts();
    state.isLoading = false;
  }

  async function loadMore() {
    if (state.isLoading || !state.hasMore) return;

    state.page++;
    state.isLoading = true;

    const data = await API.fetchReceipts({ page: state.page });

    if (data && data.receipts) {
      state.receipts = [...state.receipts, ...data.receipts];
      state.filteredReceipts = state.receipts;
      state.hasMore = data.has_more || false;
    }

    renderReceipts();
    state.isLoading = false;
  }

  // ============================================
  // Keyboard Navigation
  // ============================================

  function handleKeydown(event) {
    // Don't handle if typing in input
    if (event.target.tagName === 'INPUT' || event.target.tagName === 'TEXTAREA') {
      if (event.key === 'Escape') {
        event.target.blur();
      }
      return;
    }

    switch (event.key) {
      case '/':
        event.preventDefault();
        elements.searchInput.focus();
        break;

      case 'Escape':
        if (elements.detailModal.classList.contains('visible')) {
          closeDetailModal();
        } else if (elements.filterModal.classList.contains('visible')) {
          closeModal(elements.filterModal);
        } else if (elements.sortModal.classList.contains('visible')) {
          closeModal(elements.sortModal);
        } else if (elements.uploadModal.classList.contains('visible')) {
          closeModal(elements.uploadModal);
        } else if (elements.shortcutsModal.classList.contains('visible')) {
          closeModal(elements.shortcutsModal);
        } else if (elements.sidebar.classList.contains('visible')) {
          elements.sidebar.classList.remove('visible');
        }
        break;

      case 'j':
      case 'ArrowDown':
        if (elements.detailModal.classList.contains('visible')) {
          event.preventDefault();
          navigateReceipt(1);
        }
        break;

      case 'k':
      case 'ArrowUp':
        if (elements.detailModal.classList.contains('visible')) {
          event.preventDefault();
          navigateReceipt(-1);
        }
        break;

      case 'Enter':
        if (state.currentIndex >= 0 && !elements.detailModal.classList.contains('visible')) {
          openDetailModal(state.filteredReceipts[state.currentIndex], state.currentIndex);
        }
        break;

      case '1':
        setViewMode('grid');
        break;

      case '2':
        setViewMode('list');
        break;

      case '3':
        setViewMode('timeline');
        break;

      case 'f':
        if (state.currentReceipt) {
          // Toggle favorite
          API.updateReceipt(state.currentReceipt.uuid, {
            is_favorite: !state.currentReceipt.is_favorite
          }).then(() => {
            showToast(state.currentReceipt.is_favorite ? 'Removed from favorites' : 'Added to favorites', 'success');
          });
        }
        break;

      case 'd':
        if (state.currentReceipt) {
          const url = getReceiptImageUrl(state.currentReceipt);
          if (url) window.open(url, '_blank');
        }
        break;

      case '?':
        openModal(elements.shortcutsModal);
        break;
    }
  }

  // ============================================
  // Infinite Scroll
  // ============================================

  function setupInfiniteScroll() {
    const observer = new IntersectionObserver((entries) => {
      if (entries[0].isIntersecting && state.hasMore && !state.isLoading) {
        loadMore();
      }
    }, { threshold: 0.1 });

    // Create sentinel element
    const sentinel = document.createElement('div');
    sentinel.className = 'scroll-sentinel';
    sentinel.style.height = '1px';
    elements.receiptsContainer.appendChild(sentinel);
    observer.observe(sentinel);
  }

  // ============================================
  // Theme Toggle
  // ============================================

  function toggleTheme() {
    const isDark = document.body.classList.contains('dark-mode');
    document.body.classList.toggle('dark-mode', !isDark);
    document.body.classList.toggle('light-mode', isDark);
    localStorage.setItem('theme', isDark ? 'light' : 'dark');
  }

  function loadTheme() {
    const saved = localStorage.getItem('theme');
    if (saved === 'light') {
      document.body.classList.remove('dark-mode');
      document.body.classList.add('light-mode');
    }
  }

  // ============================================
  // Event Listeners Setup
  // ============================================

  function setupEventListeners() {
    // Menu toggle
    elements.menuBtn?.addEventListener('click', () => {
      elements.sidebar.classList.toggle('visible');
    });

    // Search
    elements.searchInput?.addEventListener('input', (e) => handleSearch(e.target.value));
    elements.searchClear?.addEventListener('click', clearSearch);

    // View toggles
    $$('.view-btn').forEach(btn => {
      btn.addEventListener('click', () => setViewMode(btn.dataset.view));
    });

    // Header buttons
    $('filter-btn')?.addEventListener('click', () => openModal(elements.filterModal));
    $('sort-btn')?.addEventListener('click', () => openModal(elements.sortModal));
    $('upload-btn')?.addEventListener('click', () => openModal(elements.uploadModal));
    $('empty-upload-btn')?.addEventListener('click', () => openModal(elements.uploadModal));
    $('theme-btn')?.addEventListener('click', toggleTheme);

    // Detail modal
    elements.detailClose?.addEventListener('click', closeDetailModal);
    $('detail-favorite')?.addEventListener('click', () => {
      if (state.currentReceipt) {
        API.updateReceipt(state.currentReceipt.uuid, {
          is_favorite: !state.currentReceipt.is_favorite
        });
      }
    });
    $('detail-download')?.addEventListener('click', () => {
      if (state.currentReceipt) {
        const url = getReceiptImageUrl(state.currentReceipt);
        if (url) window.open(url, '_blank');
      }
    });
    $('detail-share')?.addEventListener('click', () => {
      if (navigator.share && state.currentReceipt) {
        navigator.share({
          title: `Receipt - ${state.currentReceipt.merchant_name}`,
          text: `${state.currentReceipt.merchant_name}: ${formatCurrency(state.currentReceipt.amount)}`,
          url: getReceiptImageUrl(state.currentReceipt) || window.location.href
        }).catch(() => {});
      }
    });
    $('detail-delete')?.addEventListener('click', async () => {
      if (state.currentReceipt && confirm('Delete this receipt?')) {
        const success = await API.deleteReceipt(state.currentReceipt.uuid);
        if (success) {
          showToast('Receipt deleted', 'success');
          closeDetailModal();
          loadReceipts();
        }
      }
    });

    // Filter modal
    $('filter-modal-close')?.addEventListener('click', () => closeModal(elements.filterModal));
    $('filter-apply')?.addEventListener('click', () => {
      state.filters.dateFrom = elements.filterDateFrom.value || null;
      state.filters.dateTo = elements.filterDateTo.value || null;
      state.filters.amountMin = elements.filterAmountMin.value || null;
      state.filters.amountMax = elements.filterAmountMax.value || null;
      state.page = 1;
      loadReceipts();
      closeModal(elements.filterModal);
    });

    // Filter presets
    $$('[data-preset]').forEach(btn => {
      btn.addEventListener('click', () => applyDatePreset(btn.dataset.preset));
    });

    $$('[data-amount]').forEach(btn => {
      btn.addEventListener('click', () => {
        const range = btn.dataset.amount.split('-');
        elements.filterAmountMin.value = range[0];
        elements.filterAmountMax.value = range[1] === '+' ? '' : range[1];
      });
    });

    // Sort modal
    $('sort-modal-close')?.addEventListener('click', () => closeModal(elements.sortModal));
    $$('[data-sort]').forEach(btn => {
      btn.addEventListener('click', () => setSort(btn.dataset.sort));
    });

    // Upload
    elements.uploadDropzone?.addEventListener('click', () => elements.fileInput.click());
    elements.fileInput?.addEventListener('change', (e) => handleFileUpload(e.target.files));
    elements.uploadDropzone?.addEventListener('dragover', (e) => {
      e.preventDefault();
      elements.uploadDropzone.classList.add('dragover');
    });
    elements.uploadDropzone?.addEventListener('dragleave', () => {
      elements.uploadDropzone.classList.remove('dragover');
    });
    elements.uploadDropzone?.addEventListener('drop', (e) => {
      e.preventDefault();
      elements.uploadDropzone.classList.remove('dragover');
      handleFileUpload(e.dataTransfer.files);
    });

    // Close modals on backdrop click
    [elements.filterModal, elements.sortModal, elements.uploadModal, elements.shortcutsModal].forEach(modal => {
      modal?.addEventListener('click', (e) => {
        if (e.target === modal) closeModal(modal);
      });
    });

    // Sidebar navigation
    $$('.nav-item').forEach(item => {
      item.addEventListener('click', (e) => {
        e.preventDefault();
        const filter = item.dataset.filter;
        if (!filter) return;

        if (filter === 'all') {
          state.filters.source = 'all';
          state.filters.status = 'all';
          state.filters.business = 'all';
        } else if (filter === 'favorites') {
          state.filters.source = 'all';
          state.filters.status = 'all';
          state.filters.business = 'all';
          // TODO: Add favorites filter
        } else if (filter.startsWith('business:')) {
          state.filters.business = filter.split(':')[1];
        } else if (filter.startsWith('status:')) {
          state.filters.status = filter.split(':')[1];
        } else if (filter.startsWith('source:')) {
          state.filters.source = filter.split(':')[1];
        }

        state.page = 1;
        loadReceipts();
        updateActiveFilters();

        // Close sidebar on mobile
        if (window.innerWidth < 1024) {
          elements.sidebar.classList.remove('visible');
        }
      });
    });

    // Filter chips
    $$('.filter-chip').forEach(chip => {
      chip.addEventListener('click', () => {
        const filter = chip.dataset.filter;
        const preset = chip.dataset.preset;
        const status = chip.dataset.status;

        if (filter === 'all') {
          state.filters.status = 'all';
          state.filters.dateFrom = null;
          state.filters.dateTo = null;
        } else if (preset) {
          applyDatePreset(preset);
          return;
        } else if (status) {
          state.filters.status = state.filters.status === status ? 'all' : status;
        }

        state.page = 1;
        loadReceipts();
        updateActiveFilters();
      });
    });

    // Keyboard
    document.addEventListener('keydown', handleKeydown);

    // Back button
    window.addEventListener('popstate', () => {
      if (elements.detailModal.classList.contains('visible')) {
        closeDetailModal();
      }
    });

    // Click outside sidebar to close
    document.addEventListener('click', (e) => {
      if (elements.sidebar.classList.contains('visible') &&
          !elements.sidebar.contains(e.target) &&
          !elements.menuBtn.contains(e.target)) {
        elements.sidebar.classList.remove('visible');
      }
    });
  }

  // ============================================
  // Initialize
  // ============================================

  function init() {
    loadTheme();
    setupEventListeners();
    setupInfiniteScroll();
    loadReceipts();

    // Load stats
    API.getStats().then(data => {
      if (data) updateCounts(data);
    });

    // Check for receipt in URL
    const params = new URLSearchParams(window.location.search);
    const receiptId = params.get('receipt');
    if (receiptId) {
      API.getReceipt(receiptId).then(receipt => {
        if (receipt) openDetailModal(receipt, -1);
      });
    }
  }

  // Start when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

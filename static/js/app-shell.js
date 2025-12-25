/**
 * TallyUps App Shell
 * Provides consistent header, navigation, and app structure across all pages
 */

(function() {
  'use strict';

  // Navigation items configuration - matches unified-header.js
  const NAV_ITEMS = [
    { id: 'home', label: 'Home', icon: '🏠', href: '/', paths: ['/', '/dashboard'] },
    { id: 'reconcile', label: 'Reconcile', icon: '🔄', href: '/viewer', paths: ['/viewer', '/reconcile'] },
    { id: 'library', label: 'Library', icon: '📚', href: '/library', paths: ['/library'] },
    { id: 'scan', label: 'Scan', icon: '📸', href: '/scanner', paths: ['/scanner', '/mobile_scanner'] },
    { id: 'inbox', label: 'Inbox', icon: '📥', href: '/incoming', paths: ['/incoming', '/inbox'], badge: 'inboxCount' },
    { id: 'reports', label: 'Reports', icon: '📊', href: '/reports', paths: ['/reports', '/report'] },
    { id: 'gmail', label: 'Gmail', icon: '📧', href: '/gmail', paths: ['/gmail'] },
    { id: 'contacts', label: 'Contacts', icon: '👥', href: '/contacts', paths: ['/contacts'] }
  ];

  // App state
  const state = {
    inboxCount: 0,
    currentPath: window.location.pathname,
    isMobile: window.innerWidth <= 768,
    reportTrayOpen: false,
    selectedItems: []
  };

  /**
   * Initialize the app shell
   */
  function init() {
    // Load ImageUtils config for proper R2 URL handling
    if (typeof ImageUtils !== 'undefined' && ImageUtils.loadConfig) {
      ImageUtils.loadConfig();
    }

    // Inject design system CSS if not already present
    injectDesignSystem();

    // Header is now handled by unified-header.js - don't create duplicate
    // createHeader();

    // Bottom nav disabled - using header nav only
    // createBottomNav();

    // Report tray disabled - was causing UI issues
    // createReportTray();

    // Create toast container
    createToastContainer();

    // Set up event listeners
    setupEventListeners();

    // Fetch initial data
    fetchInboxCount();

    // Add page wrapper class to body content
    wrapPageContent();
  }

  /**
   * Inject design system CSS with critical inline styles to prevent FOUC
   */
  function injectDesignSystem() {
    // Add critical inline styles IMMEDIATELY to prevent Flash of Unstyled Content
    if (!document.querySelector('#app-shell-critical-css')) {
      const criticalStyle = document.createElement('style');
      criticalStyle.id = 'app-shell-critical-css';
      criticalStyle.textContent = `
        /* Critical CSS - minimal styles matching unified-header.css to prevent FOUC */
        .app-header { position: fixed; top: 0; left: 0; right: 0; height: 64px; background: #0b0d10; border-bottom: 1px solid rgba(255,255,255,0.08); z-index: 1000; display: flex; align-items: center; justify-content: space-between; padding: 0 24px; }
        .app-header__logo { display: flex; align-items: center; gap: 12px; text-decoration: none; }
        .app-header__logo-icon { width: 32px; height: 32px; background: #00ff88; border-radius: 12px; display: flex; align-items: center; justify-content: center; }
        .app-header__logo-icon svg { width: 20px; height: 20px; color: #000; }
        .app-header__logo-text { font-size: 18px; font-weight: 700; color: #ffffff; }
        .app-header__nav { display: flex; align-items: center; gap: 4px; }
        .app-header__nav-link { display: flex; align-items: center; gap: 8px; padding: 8px 12px; color: #9ca3af; text-decoration: none; border-radius: 12px; font-size: 14px; }
        .app-header__nav-link:hover { color: #fff; background: rgba(255,255,255,0.06); }
        .app-header__nav-link.active { color: #00ffa3; background: rgba(0,255,163,0.1); }
        .app-header__controls { display: flex; align-items: center; gap: 8px; }
        body.has-app-header { padding-top: 64px; }
        @media (max-width: 768px) {
          .app-header { height: 56px; padding: 0 16px; }
          .app-header__nav { display: none; }
          body.has-app-header { padding-top: 56px; }
        }
      `;
      document.head.insertBefore(criticalStyle, document.head.firstChild);
    }

    // Then load full design system CSS
    if (document.querySelector('link[href*="design-system.css"]')) return;

    const link = document.createElement('link');
    link.rel = 'stylesheet';
    link.href = '/static/css/design-system.css';
    document.head.insertBefore(link, document.head.firstChild);
  }

  /**
   * Create the app header
   * IMPORTANT: If unified-header.js has already created a header, skip this
   */
  function createHeader() {
    // Check if header already exists (from unified-header.js)
    if (document.querySelector('.app-header')) {
      // Header already exists, just ensure body has the class
      document.body.classList.add('has-app-header');
      return;
    }

    // Remove legacy inline headers (not .app-header from unified-header.js)
    const legacyHeaderSelectors = [
      'header.header',
      'header.site-header',
      'header.swipe-header',
      '.header-content',
      '.site-header-content',
      'body > header:not(.app-header)'  // Legacy headers only
    ];

    document.querySelectorAll(legacyHeaderSelectors.join(', ')).forEach(el => {
      // Don't remove if it's inside main content areas
      if (!el.closest('main, .main-content, .content, .page-content, .dashboard-content')) {
        el.remove();
      }
    });

    // Only create header if none exists
    const header = document.createElement('header');
    header.className = 'app-header';
    header.innerHTML = `
      <a href="/" class="app-header__logo">
        <span class="app-header__logo-icon">T</span>
        <span class="hide-mobile">TallyUps</span>
      </a>

      <nav class="app-header__nav">
        ${NAV_ITEMS.map(item => createNavLink(item, 'header')).join('')}
      </nav>

      <div class="app-header__actions">
        <button class="btn btn--icon btn--ghost" onclick="TallyUps.showSearch()" title="Search">
          🔍
        </button>
        <a href="/settings" class="btn btn--icon btn--ghost" title="Settings">
          ⚙️
        </a>
      </div>
    `;

    document.body.insertBefore(header, document.body.firstChild);
    document.body.classList.add('has-app-header');
  }

  /**
   * Create bottom navigation for mobile
   */
  function createBottomNav() {
    // Remove any existing bottom nav
    const existingNav = document.querySelector('.bottom-nav');
    if (existingNav) existingNav.remove();

    const nav = document.createElement('nav');
    nav.className = 'bottom-nav';
    nav.innerHTML = NAV_ITEMS.map(item => createNavLink(item, 'bottom')).join('');

    document.body.appendChild(nav);
  }

  /**
   * Create a navigation link
   */
  function createNavLink(item, type) {
    const isActive = item.paths.some(path => {
      if (path === '/') return state.currentPath === '/';
      return state.currentPath.startsWith(path);
    });

    const badgeHtml = item.badge && state[item.badge] > 0
      ? `<span class="${type === 'bottom' ? 'bottom-nav__badge' : 'badge badge--error'}">${state[item.badge]}</span>`
      : '';

    if (type === 'header') {
      return `
        <a href="${item.href}" class="app-header__nav-link ${isActive ? 'active' : ''}" data-nav-id="${item.id}">
          <span class="icon">${item.icon}</span>
          <span>${item.label}</span>
          ${badgeHtml}
        </a>
      `;
    }

    return `
      <a href="${item.href}" class="bottom-nav__link ${isActive ? 'active' : ''}" data-nav-id="${item.id}">
        <span class="icon">${item.icon}</span>
        <span>${item.label}</span>
        ${badgeHtml}
      </a>
    `;
  }

  /**
   * Create report tray for adding items to reports
   */
  function createReportTray() {
    const existingTray = document.querySelector('.report-tray');
    if (existingTray) existingTray.remove();
    const existingBackdrop = document.querySelector('.report-tray-backdrop');
    if (existingBackdrop) existingBackdrop.remove();

    // Create backdrop for closing by clicking outside
    const backdrop = document.createElement('div');
    backdrop.className = 'report-tray-backdrop';
    backdrop.id = 'report-tray-backdrop';
    backdrop.onclick = () => TallyUps.closeReportTray();
    document.body.appendChild(backdrop);

    const tray = document.createElement('div');
    tray.className = 'report-tray';
    tray.id = 'report-tray';
    tray.innerHTML = `
      <div class="report-tray__handle" onclick="TallyUps.toggleReportTray()"></div>
      <div class="report-tray__header">
        <h3 class="report-tray__title">Add to Report</h3>
        <button class="btn btn--ghost btn--sm" onclick="TallyUps.closeReportTray()">✕</button>
      </div>
      <div class="report-tray__content" id="report-tray-content">
        <div class="empty-state">
          <div class="spinner"></div>
          <p>Loading reports...</p>
        </div>
      </div>
      <div class="report-tray__actions">
        <button class="btn btn--secondary" style="flex:1" onclick="TallyUps.createNewReport()">
          + New Report
        </button>
        <button class="btn btn--primary" style="flex:1" onclick="TallyUps.addToSelectedReport()" id="add-to-report-btn" disabled>
          Add Selected
        </button>
      </div>
    `;

    document.body.appendChild(tray);

    // Create floating action button for adding to reports
    const fab = document.createElement('button');
    fab.className = 'add-to-report-fab';
    fab.id = 'add-to-report-fab';
    fab.style.display = 'none';
    fab.innerHTML = '📋';
    fab.onclick = () => TallyUps.openReportTray();
    document.body.appendChild(fab);
  }

  /**
   * Create toast notification container
   */
  function createToastContainer() {
    if (document.querySelector('.toast-container')) return;

    const container = document.createElement('div');
    container.className = 'toast-container';
    container.id = 'toast-container';
    document.body.appendChild(container);
  }

  /**
   * Wrap existing page content with proper spacing
   */
  function wrapPageContent() {
    // Add page-wrapper class to body if not present
    if (!document.body.classList.contains('page-wrapper')) {
      // Find the main content area or create wrapper
      const existingContent = document.querySelector('main, .main-content, .page-content');
      if (existingContent && !existingContent.classList.contains('page-wrapper')) {
        existingContent.style.paddingTop = 'var(--header-height)';
        existingContent.style.paddingBottom = 'calc(var(--bottom-nav-height) + var(--space-4))';
      }
    }
  }

  /**
   * Setup event listeners
   */
  function setupEventListeners() {
    // Handle window resize
    window.addEventListener('resize', debounce(() => {
      state.isMobile = window.innerWidth <= 768;
    }, 250));

    // Handle keyboard shortcuts
    document.addEventListener('keydown', (e) => {
      // Cmd/Ctrl + K for search
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        TallyUps.showSearch();
      }

      // Escape to close modals/trays
      if (e.key === 'Escape') {
        TallyUps.closeReportTray();
        TallyUps.closeModal();
      }
    });

    // Listen for selection changes
    document.addEventListener('selectionChange', (e) => {
      state.selectedItems = e.detail.items || [];
      updateFabVisibility();
    });
  }

  /**
   * Fetch inbox count from API
   */
  async function fetchInboxCount() {
    try {
      const response = await fetch('/api/incoming/count');
      if (response.ok) {
        const data = await response.json();
        state.inboxCount = data.count || 0;
        updateNavBadges();
      }
    } catch (error) {
      console.warn('Failed to fetch inbox count:', error);
    }
  }

  /**
   * Update navigation badges
   */
  function updateNavBadges() {
    document.querySelectorAll('[data-nav-id="inbox"]').forEach(link => {
      let badge = link.querySelector('.bottom-nav__badge, .badge');
      if (state.inboxCount > 0) {
        if (!badge) {
          badge = document.createElement('span');
          badge.className = link.classList.contains('bottom-nav__link') ? 'bottom-nav__badge' : 'badge badge--error';
          link.appendChild(badge);
        }
        badge.textContent = state.inboxCount > 99 ? '99+' : state.inboxCount;
      } else if (badge) {
        badge.remove();
      }
    });
  }

  /**
   * Update FAB visibility based on selection
   */
  function updateFabVisibility() {
    const fab = document.getElementById('add-to-report-fab');
    if (!fab) return;

    if (state.selectedItems.length > 0) {
      fab.style.display = 'flex';
      const badge = fab.querySelector('.badge') || document.createElement('span');
      badge.className = 'badge';
      badge.textContent = state.selectedItems.length;
      if (!fab.querySelector('.badge')) fab.appendChild(badge);
    } else {
      fab.style.display = 'none';
    }
  }

  /**
   * Open report tray
   */
  async function openReportTray() {
    const tray = document.getElementById('report-tray');
    const backdrop = document.getElementById('report-tray-backdrop');
    if (!tray) return;

    tray.classList.add('open');
    if (backdrop) backdrop.classList.add('open');
    state.reportTrayOpen = true;

    // Load reports
    await loadReportsForTray();
  }

  /**
   * Close report tray
   */
  function closeReportTray() {
    const tray = document.getElementById('report-tray');
    const backdrop = document.getElementById('report-tray-backdrop');
    if (!tray) return;

    tray.classList.remove('open');
    if (backdrop) backdrop.classList.remove('open');
    state.reportTrayOpen = false;
  }

  /**
   * Toggle report tray
   */
  function toggleReportTray() {
    if (state.reportTrayOpen) {
      closeReportTray();
    } else {
      openReportTray();
    }
  }

  /**
   * Load reports for the tray
   */
  async function loadReportsForTray() {
    const content = document.getElementById('report-tray-content');
    if (!content) return;

    try {
      const response = await fetch('/api/reports?status=draft');
      if (!response.ok) throw new Error('Failed to load reports');

      const data = await response.json();
      const reports = data.reports || [];

      if (reports.length === 0) {
        content.innerHTML = `
          <div class="empty-state" style="padding: var(--space-6)">
            <div class="empty-state__icon">📋</div>
            <p class="empty-state__title">No Draft Reports</p>
            <p class="empty-state__description">Create a new report to start adding expenses.</p>
          </div>
        `;
      } else {
        content.innerHTML = reports.map(report => `
          <div class="report-tray__item" data-report-id="${report.report_id || report.id}" onclick="TallyUps.selectReport('${report.report_id || report.id}')">
            <div class="report-tray__item-info">
              <div class="report-tray__item-name">${report.report_name || report.name}</div>
              <div class="report-tray__item-meta">
                ${report.count || 0} items · $${(report.total || 0).toFixed(2)}
              </div>
            </div>
            <span class="badge badge--${report.status === 'draft' ? 'warning' : 'success'}">${report.status}</span>
          </div>
        `).join('');
      }
    } catch (error) {
      console.error('Error loading reports:', error);
      content.innerHTML = `
        <div class="empty-state" style="padding: var(--space-6)">
          <div class="empty-state__icon">⚠️</div>
          <p class="empty-state__title">Error Loading Reports</p>
          <p class="empty-state__description">Please try again.</p>
        </div>
      `;
    }
  }

  /**
   * Select a report in the tray
   */
  function selectReport(reportId) {
    document.querySelectorAll('.report-tray__item').forEach(item => {
      item.classList.toggle('selected', item.dataset.reportId === reportId);
    });

    state.selectedReportId = reportId;

    const addBtn = document.getElementById('add-to-report-btn');
    if (addBtn) addBtn.disabled = false;
  }

  /**
   * Add selected items to the selected report
   */
  async function addToSelectedReport() {
    if (!state.selectedReportId || state.selectedItems.length === 0) {
      showToast('Please select a report and items', 'warning');
      return;
    }

    try {
      const response = await fetch(`/api/reports/${state.selectedReportId}/add`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ transaction_ids: state.selectedItems })
      });

      if (!response.ok) throw new Error('Failed to add items');

      const data = await response.json();
      showToast(`Added ${state.selectedItems.length} items to report`, 'success');

      // Clear selection and close tray
      state.selectedItems = [];
      updateFabVisibility();
      closeReportTray();

      // Dispatch event for other components to update
      document.dispatchEvent(new CustomEvent('reportUpdated', { detail: { reportId: state.selectedReportId } }));

    } catch (error) {
      console.error('Error adding to report:', error);
      showToast('Failed to add items to report', 'error');
    }
  }

  /**
   * Create a new report
   */
  async function createNewReport() {
    const name = prompt('Enter report name:');
    if (!name) return;

    try {
      const response = await fetch('/api/reports', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, status: 'draft' })
      });

      if (!response.ok) throw new Error('Failed to create report');

      const data = await response.json();
      showToast('Report created successfully', 'success');

      // Reload reports and select the new one
      await loadReportsForTray();
      selectReport(data.report_id || data.id);

    } catch (error) {
      console.error('Error creating report:', error);
      showToast('Failed to create report', 'error');
    }
  }

  /**
   * Show search modal
   */
  function showSearch() {
    // Dispatch event for page-specific search handling
    document.dispatchEvent(new CustomEvent('showSearch'));
  }

  /**
   * Show a toast notification
   */
  function showToast(message, type = 'info', duration = 4000) {
    const container = document.getElementById('toast-container');
    if (!container) return;

    const icons = {
      success: '✓',
      error: '✕',
      warning: '⚠',
      info: 'ℹ'
    };

    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.innerHTML = `
      <span class="toast__icon">${icons[type]}</span>
      <div class="toast__content">
        <div class="toast__message">${message}</div>
      </div>
      <button class="btn btn--ghost btn--sm" onclick="this.parentElement.remove()">✕</button>
    `;

    container.appendChild(toast);

    // Auto-remove after duration
    setTimeout(() => {
      toast.style.animation = 'fadeOut 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, duration);
  }

  /**
   * Close any open modal
   */
  function closeModal() {
    document.querySelectorAll('.modal.open, .modal-backdrop.open').forEach(el => {
      el.classList.remove('open');
    });
  }

  /**
   * Debounce helper
   */
  function debounce(fn, delay) {
    let timeoutId;
    return (...args) => {
      clearTimeout(timeoutId);
      timeoutId = setTimeout(() => fn.apply(this, args), delay);
    };
  }

  /**
   * Format currency
   */
  function formatCurrency(amount) {
    return new Intl.NumberFormat('en-US', {
      style: 'currency',
      currency: 'USD'
    }).format(amount);
  }

  /**
   * Format date
   */
  function formatDate(dateStr) {
    const date = new Date(dateStr);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      year: 'numeric'
    });
  }

  // Expose public API
  window.TallyUps = {
    init,
    state,
    showToast,
    showSearch,
    openReportTray,
    closeReportTray,
    toggleReportTray,
    selectReport,
    addToSelectedReport,
    createNewReport,
    closeModal,
    formatCurrency,
    formatDate,
    updateNavBadges,

    // Allow external components to update selection
    setSelectedItems: (items) => {
      state.selectedItems = items;
      updateFabVisibility();
    }
  };

  // Auto-initialize when DOM is ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }

})();

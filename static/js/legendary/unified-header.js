/**
 * TALLYUPS UNIFIED HEADER
 * Inject consistent header across all pages
 */

(function() {
  'use strict';

  // Navigation items
  const NAV_ITEMS = [
    { href: '/viewer', label: 'Dashboard', icon: 'dashboard' },
    { href: '/library', label: 'Library', icon: 'library' },
    { href: '/scanner', label: 'Scanner', icon: 'scanner' },
    { href: '/incoming', label: 'Incoming', icon: 'incoming' },
    { href: '/reports', label: 'Reports', icon: 'reports' },
    { href: '/contacts', label: 'Contacts', icon: 'contacts' },
  ];

  // SVG Icons
  const ICONS = {
    dashboard: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>`,
    library: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>`,
    scanner: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"/><circle cx="12" cy="13" r="4"/></svg>`,
    incoming: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>`,
    reports: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>`,
    contacts: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    search: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>`,
    sun: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>`,
    moon: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>`,
    settings: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    menu: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/></svg>`,
    close: `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>`,
    logo: `<svg viewBox="0 0 32 32" fill="none"><rect width="32" height="32" rx="8" fill="url(#logo-gradient)"/><path d="M8 16h16M16 8v16" stroke="white" stroke-width="2.5" stroke-linecap="round"/><defs><linearGradient id="logo-gradient" x1="0" y1="0" x2="32" y2="32"><stop stop-color="#00FFA3"/><stop offset="1" stop-color="#5B7FFF"/></linearGradient></defs></svg>`
  };

  // Get current page
  function getCurrentPage() {
    const path = window.location.pathname;
    for (const item of NAV_ITEMS) {
      if (path === item.href || path.startsWith(item.href + '/')) {
        return item.href;
      }
    }
    // Default to dashboard for root
    if (path === '/' || path === '/viewer' || path === '') {
      return '/viewer';
    }
    return null;
  }

  // Create header HTML
  function createHeaderHTML() {
    const currentPage = getCurrentPage();

    const navLinks = NAV_ITEMS.map(item => `
      <a href="${item.href}" class="nav-link ${currentPage === item.href ? 'active' : ''}">
        ${ICONS[item.icon]}
        <span>${item.label}</span>
      </a>
    `).join('');

    const mobileNavLinks = NAV_ITEMS.map(item => `
      <a href="${item.href}" class="mobile-nav-link ${currentPage === item.href ? 'active' : ''}">
        ${ICONS[item.icon]}
        <span>${item.label}</span>
      </a>
    `).join('');

    return `
      <header class="unified-header">
        <div class="unified-header-inner">
          <!-- Brand -->
          <a href="/viewer" class="header-brand">
            ${ICONS.logo}
            <span class="header-logo-text">TallyUps</span>
          </a>

          <!-- Navigation -->
          <nav class="header-nav">
            ${navLinks}
          </nav>

          <!-- Search -->
          <div class="header-search">
            <span class="header-search-icon">${ICONS.search}</span>
            <input
              type="text"
              class="header-search-input"
              placeholder="Search expenses..."
              id="global-search"
            >
            <span class="header-search-kbd">
              <kbd>⌘</kbd><kbd>K</kbd>
            </span>
          </div>

          <!-- Actions -->
          <div class="header-actions">
            <button class="header-action-btn theme-toggle" id="theme-toggle" title="Toggle theme">
              <span class="sun-icon">${ICONS.sun}</span>
              <span class="moon-icon">${ICONS.moon}</span>
            </button>
            <a href="/settings" class="header-action-btn" title="Settings">
              ${ICONS.settings}
            </a>
            <button class="header-action-btn mobile-menu-btn" id="mobile-menu-btn">
              ${ICONS.menu}
            </button>
          </div>
        </div>
      </header>

      <!-- Mobile Drawer -->
      <div class="mobile-drawer" id="mobile-drawer">
        <div class="mobile-drawer-overlay" id="mobile-drawer-overlay"></div>
        <div class="mobile-drawer-content">
          <div class="mobile-drawer-header">
            <a href="/viewer" class="header-brand">
              ${ICONS.logo}
              <span class="header-logo-text">TallyUps</span>
            </a>
            <button class="mobile-drawer-close" id="mobile-drawer-close">
              ${ICONS.close}
            </button>
          </div>
          <nav class="mobile-nav">
            ${mobileNavLinks}
            <a href="/settings" class="mobile-nav-link">
              ${ICONS.settings}
              <span>Settings</span>
            </a>
          </nav>
        </div>
      </div>
    `;
  }

  // Initialize header
  function initHeader() {
    // Don't initialize if already exists
    if (document.querySelector('.unified-header')) {
      return;
    }

    // Find the target - either body start or after existing outdated headers
    const existingHeader = document.querySelector('header, .app-header, #header, .main-header');

    // Create header container
    const headerContainer = document.createElement('div');
    headerContainer.innerHTML = createHeaderHTML();

    if (existingHeader) {
      // Replace existing header
      existingHeader.replaceWith(headerContainer.firstElementChild);
      // Also insert mobile drawer
      document.body.appendChild(headerContainer.lastElementChild);
    } else {
      // Insert at the very beginning of body
      document.body.insertBefore(headerContainer.firstElementChild, document.body.firstChild);
      document.body.appendChild(headerContainer.lastElementChild);
    }

    // Setup event listeners
    setupEventListeners();
  }

  // Setup event listeners
  function setupEventListeners() {
    // Theme toggle
    const themeToggle = document.getElementById('theme-toggle');
    if (themeToggle) {
      themeToggle.addEventListener('click', toggleTheme);
    }

    // Mobile menu
    const mobileMenuBtn = document.getElementById('mobile-menu-btn');
    const mobileDrawer = document.getElementById('mobile-drawer');
    const mobileDrawerOverlay = document.getElementById('mobile-drawer-overlay');
    const mobileDrawerClose = document.getElementById('mobile-drawer-close');

    if (mobileMenuBtn) {
      mobileMenuBtn.addEventListener('click', () => {
        mobileDrawer.classList.add('open');
      });
    }

    if (mobileDrawerOverlay) {
      mobileDrawerOverlay.addEventListener('click', () => {
        mobileDrawer.classList.remove('open');
      });
    }

    if (mobileDrawerClose) {
      mobileDrawerClose.addEventListener('click', () => {
        mobileDrawer.classList.remove('open');
      });
    }

    // Global search - CMD+K
    document.addEventListener('keydown', (e) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault();
        const searchInput = document.getElementById('global-search');
        if (searchInput) {
          searchInput.focus();
        }
      }
      // Escape to close mobile drawer
      if (e.key === 'Escape' && mobileDrawer) {
        mobileDrawer.classList.remove('open');
      }
    });
  }

  // Toggle theme
  function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('tallyups-theme', newTheme);
  }

  // Initialize theme from localStorage
  function initTheme() {
    const savedTheme = localStorage.getItem('tallyups-theme') || 'dark';
    document.documentElement.setAttribute('data-theme', savedTheme);
  }

  // Wait for DOM and initialize
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initTheme();
      initHeader();
    });
  } else {
    initTheme();
    initHeader();
  }

  // Export for manual initialization if needed
  window.TallyUpsHeader = {
    init: initHeader,
    toggleTheme: toggleTheme
  };

})();

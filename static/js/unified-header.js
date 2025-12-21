/**
 * Unified Header System for Tallyups
 * Injects consistent header/navigation across all pages
 */

(function() {
  'use strict';

  // Navigation items configuration
  const NAV_ITEMS = [
    { href: '/', label: 'Home', icon: 'home' },
    { href: '/viewer', label: 'Reconcile', icon: 'check' },
    { href: '/library', label: 'Library', icon: 'grid' },
    { href: '/scanner', label: 'Scan', icon: 'camera' },
    { href: '/incoming', label: 'Inbox', icon: 'inbox' },
    { href: '/reports', label: 'Reports', icon: 'file' },
    { href: '/gmail', label: 'Gmail', icon: 'mail' },
    { href: '/contacts', label: 'Contacts', icon: 'users' }
  ];

  // SVG Icons
  const ICONS = {
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path><polyline points="9 22 9 12 15 12 15 22"></polyline>',
    check: '<path d="M9 11l3 3L22 4"></path><path d="M21 12v7a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h11"></path>',
    grid: '<rect x="3" y="3" width="7" height="7"></rect><rect x="14" y="3" width="7" height="7"></rect><rect x="14" y="14" width="7" height="7"></rect><rect x="3" y="14" width="7" height="7"></rect>',
    camera: '<path d="M23 19a2 2 0 0 1-2 2H3a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h4l2-3h6l2 3h4a2 2 0 0 1 2 2z"></path><circle cx="12" cy="13" r="4"></circle>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"></polyline><path d="M5.45 5.11L2 12v6a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2v-6l-3.45-6.89A2 2 0 0 0 16.76 4H7.24a2 2 0 0 0-1.79 1.11z"></path>',
    file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path><polyline points="14 2 14 8 20 8"></polyline><line x1="16" y1="13" x2="8" y2="13"></line><line x1="16" y1="17" x2="8" y2="17"></line>',
    mail: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"></path><polyline points="22,6 12,13 2,6"></polyline>',
    users: '<path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"></path><circle cx="9" cy="7" r="4"></circle><path d="M23 21v-2a4 4 0 0 0-3-3.87"></path><path d="M16 3.13a4 4 0 0 1 0 7.75"></path>',
    search: '<circle cx="11" cy="11" r="8"></circle><line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
    sun: '<circle cx="12" cy="12" r="5"></circle><line x1="12" y1="1" x2="12" y2="3"></line><line x1="12" y1="21" x2="12" y2="23"></line><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"></line><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"></line><line x1="1" y1="12" x2="3" y2="12"></line><line x1="21" y1="12" x2="23" y2="12"></line><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"></line><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"></line>',
    moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"></path>',
    settings: '<circle cx="12" cy="12" r="3"></circle><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06a1.65 1.65 0 0 0 1.82.33H9a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"></path>',
    menu: '<line x1="3" y1="12" x2="21" y2="12"></line><line x1="3" y1="6" x2="21" y2="6"></line><line x1="3" y1="18" x2="21" y2="18"></line>',
    x: '<line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line>',
    logo: '<rect x="3" y="4" width="18" height="16" rx="2"/><line x1="7" y1="9" x2="17" y2="9"/><line x1="7" y1="13" x2="13" y2="13"/><line x1="7" y1="17" x2="10" y2="17"/>'
  };

  function createSvg(iconName) {
    return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[iconName] || ''}</svg>`;
  }

  function getCurrentPath() {
    return window.location.pathname;
  }

  function isActive(href) {
    const path = getCurrentPath();
    if (href === '/') return path === '/' || path === '/dashboard';
    return path.startsWith(href);
  }

  function createHeader() {
    const currentPath = getCurrentPath();

    // Build nav links
    const navLinks = NAV_ITEMS.map(item => `
      <a href="${item.href}" class="app-header__nav-link${isActive(item.href) ? ' active' : ''}">
        ${createSvg(item.icon)}
        <span>${item.label}</span>
      </a>
    `).join('');

    // Build mobile menu links
    const mobileLinks = NAV_ITEMS.map(item => `
      <a href="${item.href}" class="mobile-menu__link${isActive(item.href) ? ' active' : ''}">
        ${createSvg(item.icon)}
        <span>${item.label}</span>
      </a>
    `).join('');

    const headerHTML = `
      <header class="app-header">
        <a href="/" class="app-header__logo">
          <div class="app-header__logo-icon">
            ${createSvg('logo')}
          </div>
          <span class="app-header__logo-text">Tallyups</span>
        </a>

        <nav class="app-header__nav">
          ${navLinks}
        </nav>

        <div class="app-header__controls">
          <div class="app-header__search">
            ${createSvg('search')}
            <input type="text" placeholder="Search..." id="global-search">
          </div>
          <button class="app-header__btn" onclick="TallyupsHeader.toggleTheme()" title="Toggle theme">
            ${createSvg('sun')}
          </button>
          <a href="/settings" class="app-header__btn" title="Settings">
            ${createSvg('settings')}
          </a>
          <button class="app-header__hamburger" onclick="TallyupsHeader.toggleMobileMenu()">
            ${createSvg('menu')}
          </button>
        </div>
      </header>

      <div class="mobile-menu" id="mobile-menu">
        <nav class="mobile-menu__nav">
          ${mobileLinks}
          <div class="mobile-menu__divider"></div>
          <a href="/settings" class="mobile-menu__link${currentPath === '/settings' ? ' active' : ''}">
            ${createSvg('settings')}
            <span>Settings</span>
          </a>
        </nav>
      </div>
    `;

    return headerHTML;
  }

  function injectHeader() {
    // Check if header already exists
    if (document.querySelector('.app-header')) return;

    // Remove any existing headers
    const existingHeaders = document.querySelectorAll('header:not(.app-header)');
    existingHeaders.forEach(h => h.remove());

    // Remove bottom navigation if exists
    const bottomNav = document.querySelector('.bottom-nav, .mobile-nav, [class*="bottom-nav"]');
    if (bottomNav) bottomNav.remove();

    // Inject new header at the start of body
    document.body.insertAdjacentHTML('afterbegin', createHeader());

    // Add body class for padding
    document.body.classList.add('has-app-header');

    // Initialize theme icon
    updateThemeIcon();
  }

  function toggleMobileMenu() {
    const menu = document.getElementById('mobile-menu');
    const hamburger = document.querySelector('.app-header__hamburger');

    if (menu.classList.contains('open')) {
      menu.classList.remove('open');
      hamburger.innerHTML = createSvg('menu');
    } else {
      menu.classList.add('open');
      hamburger.innerHTML = createSvg('x');
    }
  }

  function toggleTheme() {
    const html = document.documentElement;
    const currentTheme = html.getAttribute('data-theme') || 'dark';
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';

    html.setAttribute('data-theme', newTheme);
    localStorage.setItem('tallyups-theme', newTheme);

    updateThemeIcon();
  }

  function updateThemeIcon() {
    const btn = document.querySelector('.app-header__controls .app-header__btn');
    if (!btn) return;

    const currentTheme = document.documentElement.getAttribute('data-theme') || 'dark';
    btn.innerHTML = createSvg(currentTheme === 'dark' ? 'sun' : 'moon');
  }

  function loadTheme() {
    const saved = localStorage.getItem('tallyups-theme');
    if (saved) {
      document.documentElement.setAttribute('data-theme', saved);
    }
  }

  // Global search handler
  function initSearch() {
    const searchInput = document.getElementById('global-search');
    if (!searchInput) return;

    searchInput.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        const query = searchInput.value.trim();
        if (query) {
          // Navigate to viewer with search
          window.location.href = `/viewer?search=${encodeURIComponent(query)}`;
        }
      }
    });
  }

  // Initialize
  function init() {
    loadTheme();

    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', () => {
        injectHeader();
        initSearch();
      });
    } else {
      injectHeader();
      initSearch();
    }
  }

  // Expose to global scope
  window.TallyupsHeader = {
    toggleMobileMenu,
    toggleTheme,
    refresh: injectHeader
  };

  init();
})();

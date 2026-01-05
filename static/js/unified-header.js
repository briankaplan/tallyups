/**
 * TallyUps Unified Header & Navigation
 * Clean Sentinel-inspired design with consistent navigation
 */

(function() {
  'use strict';

  // Navigation configuration
  const NAV_ITEMS = [
    { href: '/', label: 'Home', icon: 'home' },
    { href: '/viewer', label: 'Match', icon: 'link' },
    { href: '/incoming', label: 'Inbox', icon: 'inbox' },
    { href: '/library', label: 'Library', icon: 'book' },
    { href: '/reports', label: 'Reports', icon: 'file-text' },
    { href: '/gmail', label: 'Gmail', icon: 'mail' },
    { href: '/contacts', label: 'Contacts', icon: 'users' },
    { href: '/bank-accounts', label: 'Banks', icon: 'credit-card' }
  ];

  const MOBILE_NAV_ITEMS = [
    { href: '/', label: 'Home', icon: 'home' },
    { href: '/viewer', label: 'Match', icon: 'link' },
    { href: '/scanner', label: 'Scan', icon: 'camera' },
    { href: '/incoming', label: 'Inbox', icon: 'inbox' },
    { href: '/library', label: 'Library', icon: 'book' }
  ];

  // SVG Icons (Feather-style)
  const ICONS = {
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    link: '<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>',
    camera: '<path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/>',
    'file-text': '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',
    clipboard: '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12l2 2 4-4"/>',
    menu: '<line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="18" x2="21" y2="18"/>',
    x: '<line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/>',
    mail: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
    'credit-card': '<rect x="1" y="4" width="22" height="16" rx="2" ry="2"/><line x1="1" y1="10" x2="23" y2="10"/>'
  };

  function getIcon(name, size = 20) {
    const path = ICONS[name] || ICONS.home;
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  }

  function getCurrentPath() {
    return window.location.pathname;
  }

  function isActive(href) {
    const path = getCurrentPath();
    if (href === '/') return path === '/' || path === '/dashboard';
    return path.startsWith(href);
  }

  // Page hierarchy for breadcrumbs
  const PAGE_HIERARCHY = {
    '/': { title: 'Dashboard', parent: null },
    '/viewer': { title: 'Match Receipts', parent: null },
    '/incoming': { title: 'Inbox', parent: null },
    '/library': { title: 'Library', parent: null },
    '/scanner': { title: 'Scan', parent: null },
    '/reports': { title: 'Reports', parent: null },
    '/gmail': { title: 'Gmail', parent: null },
    '/contacts': { title: 'Contacts', parent: null },
    '/settings': { title: 'Settings', parent: '/' },
    '/bank-accounts': { title: 'Bank Accounts', parent: '/settings' },
    '/profile': { title: 'Profile', parent: '/settings' },
    '/receipt': { title: 'Receipt Details', parent: '/library' },
    '/report': { title: 'Report Details', parent: '/reports' }
  };

  function getPageTitle() {
    const path = getCurrentPath();
    const pageInfo = PAGE_HIERARCHY[path];
    return pageInfo ? pageInfo.title : 'TallyUps';
  }

  function getBreadcrumbs() {
    const path = getCurrentPath();
    const crumbs = [];
    let currentPath = path;

    // Build breadcrumb chain from current page to root
    while (currentPath) {
      const pageInfo = PAGE_HIERARCHY[currentPath];
      if (pageInfo) {
        crumbs.unshift({ path: currentPath, title: pageInfo.title });
        currentPath = pageInfo.parent;
      } else {
        break;
      }
    }

    return crumbs;
  }

  function needsBreadcrumbs() {
    const path = getCurrentPath();
    const pageInfo = PAGE_HIERARCHY[path];
    return pageInfo && pageInfo.parent !== null;
  }

  function createBreadcrumbBar() {
    if (!needsBreadcrumbs()) return '';

    const crumbs = getBreadcrumbs();
    const breadcrumbItems = crumbs.map((crumb, index) => {
      const isLast = index === crumbs.length - 1;
      if (isLast) {
        return `<span class="tu-breadcrumb__current">${crumb.title}</span>`;
      }
      return `
        <a href="${crumb.path}" class="tu-breadcrumb__link">${crumb.title}</a>
        <span class="tu-breadcrumb__separator">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <polyline points="9 18 15 12 9 6"></polyline>
          </svg>
        </span>
      `;
    }).join('');

    return `
      <div class="tu-breadcrumb">
        <div class="tu-breadcrumb__inner">
          ${breadcrumbItems}
        </div>
      </div>
    `;
  }

  function createHeader() {
    const currentPath = getCurrentPath();
    const pageTitle = getPageTitle();

    // Desktop nav links
    const navLinks = NAV_ITEMS.map(item => `
      <a href="${item.href}" class="tu-header__nav-item ${isActive(item.href) ? 'active' : ''}">
        ${getIcon(item.icon, 18)}
        <span>${item.label}</span>
      </a>
    `).join('');

    // Breadcrumb bar for sub-pages
    const breadcrumbBar = createBreadcrumbBar();

    return `
      <header class="tu-header ${needsBreadcrumbs() ? 'has-breadcrumbs' : ''}">
        <div class="tu-header__left">
          <a href="/" class="tu-header__brand">
            <div class="tu-header__logo">
              ${getIcon('clipboard', 24)}
            </div>
            <div class="tu-header__text">
              <div class="tu-header__title">TALLYUPS</div>
              <div class="tu-header__subtitle">${pageTitle}</div>
            </div>
          </a>
        </div>
        <nav class="tu-header__nav">
          ${navLinks}
        </nav>
        <div class="tu-header__actions">
          <div class="tu-header__status">
            <span class="tu-header__status-dot"></span>
            <span>Synced</span>
          </div>
          <a href="/settings" class="tu-header__settings" title="Settings">
            ${getIcon('settings', 18)}
          </a>
          <button class="tu-header__hamburger" onclick="TallyupsHeader.toggleMobileMenu()">
            ${getIcon('menu', 20)}
          </button>
        </div>
      </header>
      ${breadcrumbBar}
    `;
  }

  function createBottomNav() {
    const navItems = MOBILE_NAV_ITEMS.map(item => `
      <a href="${item.href}" class="tu-bottom-nav__item ${isActive(item.href) ? 'active' : ''}">
        ${getIcon(item.icon, 22)}
        <span>${item.label}</span>
      </a>
    `).join('');

    return `
      <nav class="tu-bottom-nav">
        ${navItems}
      </nav>
    `;
  }

  function createMobileMenu() {
    const allItems = [
      ...NAV_ITEMS,
      { href: '/scanner', label: 'Scan', icon: 'camera' },
      { href: '/settings', label: 'Settings', icon: 'settings' }
    ];

    const menuLinks = allItems.map(item => `
      <a href="${item.href}" class="tu-mobile-menu__item ${isActive(item.href) ? 'active' : ''}">
        ${getIcon(item.icon, 20)}
        <span>${item.label}</span>
      </a>
    `).join('');

    return `
      <div class="tu-mobile-menu" id="tu-mobile-menu">
        <div class="tu-mobile-menu__overlay" onclick="TallyupsHeader.toggleMobileMenu()"></div>
        <div class="tu-mobile-menu__content">
          <div class="tu-mobile-menu__header">
            <span>Menu</span>
            <button onclick="TallyupsHeader.toggleMobileMenu()">${getIcon('x', 20)}</button>
          </div>
          <nav class="tu-mobile-menu__nav">
            ${menuLinks}
          </nav>
        </div>
      </div>
    `;
  }

  function injectStyles() {
    if (document.getElementById('tu-header-styles')) return;

    const styles = document.createElement('style');
    styles.id = 'tu-header-styles';
    styles.textContent = `
      /* TallyUps Header - Sentinel-inspired clean design */
      .tu-header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 12px 24px;
        background: #0a0f14;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        position: sticky;
        top: 0;
        z-index: 1000;
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', 'Segoe UI', Roboto, sans-serif;
      }

      .tu-header__left {
        display: flex;
        align-items: center;
      }

      .tu-header__brand {
        display: flex;
        align-items: center;
        gap: 12px;
        text-decoration: none;
        color: inherit;
      }

      .tu-header__logo {
        width: 40px;
        height: 40px;
        background: linear-gradient(135deg, #a855f7, #3b82f6);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
      }

      .tu-header__title {
        font-size: 18px;
        font-weight: 700;
        color: #fff;
        letter-spacing: -0.02em;
      }

      .tu-header__subtitle {
        font-size: 12px;
        color: #5a6577;
      }

      .tu-header__nav {
        display: flex;
        align-items: center;
        gap: 4px;
      }

      .tu-header__nav-item {
        display: flex;
        align-items: center;
        gap: 6px;
        padding: 8px 12px;
        border-radius: 8px;
        text-decoration: none;
        color: #8b95a5;
        font-size: 13px;
        font-weight: 500;
        transition: all 0.15s ease;
      }

      .tu-header__nav-item:hover {
        background: rgba(255,255,255,0.05);
        color: #fff;
      }

      .tu-header__nav-item.active {
        background: rgba(0,255,136,0.1);
        color: #00ff88;
      }

      .tu-header__nav-item svg {
        flex-shrink: 0;
      }

      .tu-header__actions {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .tu-header__status {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 6px 14px;
        background: #111820;
        border: 1px solid rgba(255,255,255,0.06);
        border-radius: 20px;
        font-size: 13px;
        color: #8b95a5;
      }

      .tu-header__status-dot {
        width: 8px;
        height: 8px;
        background: #22c55e;
        border-radius: 50%;
        animation: tu-pulse 2s ease-in-out infinite;
      }

      @keyframes tu-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }

      .tu-header__settings {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 36px;
        height: 36px;
        background: #111820;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        color: #8b95a5;
        transition: all 0.15s ease;
      }

      .tu-header__settings:hover {
        border-color: rgba(255,255,255,0.15);
        background: #1a2230;
        color: #fff;
      }

      .tu-header__hamburger {
        display: none;
        align-items: center;
        justify-content: center;
        width: 40px;
        height: 40px;
        background: transparent;
        border: none;
        color: #fff;
        cursor: pointer;
      }

      /* Bottom Navigation (Mobile) */
      .tu-bottom-nav {
        display: none;
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        background: #0a0f14;
        border-top: 1px solid rgba(255,255,255,0.06);
        padding: 8px 0;
        padding-bottom: max(8px, env(safe-area-inset-bottom));
        z-index: 999;
      }

      .tu-bottom-nav__item {
        flex: 1;
        display: flex;
        flex-direction: column;
        align-items: center;
        gap: 4px;
        padding: 8px 4px;
        text-decoration: none;
        color: #5a6577;
        font-size: 10px;
        font-weight: 500;
        transition: color 0.15s ease;
      }

      .tu-bottom-nav__item:hover,
      .tu-bottom-nav__item.active {
        color: #00ff88;
      }

      .tu-bottom-nav__item svg {
        transition: transform 0.15s ease;
      }

      .tu-bottom-nav__item.active svg {
        transform: scale(1.1);
      }

      /* Mobile Menu */
      .tu-mobile-menu {
        display: none;
        position: fixed;
        inset: 0;
        z-index: 9999;
      }

      .tu-mobile-menu.open {
        display: block;
      }

      .tu-mobile-menu__overlay {
        position: absolute;
        inset: 0;
        background: rgba(0,0,0,0.6);
        backdrop-filter: blur(4px);
      }

      .tu-mobile-menu__content {
        position: absolute;
        top: 0;
        right: 0;
        bottom: 0;
        width: 280px;
        background: #111820;
        box-shadow: -4px 0 24px rgba(0,0,0,0.3);
        overflow-y: auto;
      }

      .tu-mobile-menu__header {
        display: flex;
        align-items: center;
        justify-content: space-between;
        padding: 16px 20px;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        font-weight: 600;
        color: #fff;
      }

      .tu-mobile-menu__header button {
        display: flex;
        align-items: center;
        justify-content: center;
        width: 32px;
        height: 32px;
        background: transparent;
        border: none;
        color: #8b95a5;
        cursor: pointer;
      }

      .tu-mobile-menu__nav {
        padding: 12px;
      }

      .tu-mobile-menu__item {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 12px 16px;
        border-radius: 8px;
        text-decoration: none;
        color: #8b95a5;
        font-size: 15px;
        font-weight: 500;
        transition: all 0.15s ease;
      }

      .tu-mobile-menu__item:hover {
        background: rgba(255,255,255,0.05);
        color: #fff;
      }

      .tu-mobile-menu__item.active {
        background: rgba(0,255,136,0.1);
        color: #00ff88;
      }

      /* Responsive */
      @media (max-width: 900px) {
        .tu-header__nav-item span { display: none; }
        .tu-header__nav-item { padding: 8px; }
        .tu-header__status span { display: none; }
        .tu-header__text { display: none; }
      }

      @media (max-width: 768px) {
        .tu-header { padding: 10px 16px; }
        .tu-header__nav { display: none; }
        .tu-header__status { display: none; }
        .tu-header__settings { display: none; }
        .tu-header__hamburger { display: flex !important; }
      }

      /* Bottom nav - show on mobile for easy navigation */
      @media (max-width: 768px) {
        .tu-bottom-nav {
          display: flex !important;
        }
        body.has-tu-header {
          padding-bottom: 70px;
        }
      }

      /* Body adjustments */
      body.has-tu-header {
        padding-top: 0;
        margin: 0;
        background: #0a0f14;
        color: #fff;
      }

      /* Breadcrumb Bar */
      .tu-breadcrumb {
        background: #0d1117;
        border-bottom: 1px solid rgba(255,255,255,0.06);
        padding: 10px 24px;
        position: sticky;
        top: 56px;
        z-index: 999;
      }

      .tu-breadcrumb__inner {
        display: flex;
        align-items: center;
        gap: 4px;
        max-width: 1200px;
        margin: 0 auto;
      }

      .tu-breadcrumb__link {
        color: #5a6577;
        text-decoration: none;
        font-size: 13px;
        font-weight: 500;
        padding: 4px 8px;
        border-radius: 6px;
        transition: all 0.15s ease;
      }

      .tu-breadcrumb__link:hover {
        color: #00ff88;
        background: rgba(0,255,136,0.1);
      }

      .tu-breadcrumb__separator {
        color: #3a4557;
        display: flex;
        align-items: center;
      }

      .tu-breadcrumb__current {
        color: #fff;
        font-size: 13px;
        font-weight: 600;
        padding: 4px 8px;
      }

      @media (max-width: 768px) {
        .tu-breadcrumb {
          padding: 8px 16px;
          top: 48px;
        }
        .tu-breadcrumb__link,
        .tu-breadcrumb__current {
          font-size: 12px;
        }
      }

      /* Adjust body padding when breadcrumbs present */
      body.has-tu-header.has-breadcrumbs {
        padding-top: 96px; /* header + breadcrumb */
      }
    `;
    document.head.appendChild(styles);
  }

  function toggleMobileMenu() {
    const menu = document.getElementById('tu-mobile-menu');
    if (menu) {
      menu.classList.toggle('open');
    }
  }

  function injectHeader() {
    // Check if already injected
    if (document.querySelector('.tu-header')) return;

    // Remove old headers/navs
    const oldHeaders = document.querySelectorAll('.app-header, header:not(.tu-header)');
    oldHeaders.forEach(h => h.remove());

    const oldBottomNav = document.querySelectorAll('.bottom-nav, .mobile-nav');
    oldBottomNav.forEach(n => n.remove());

    // Inject styles first
    injectStyles();

    // Inject header (includes breadcrumbs if needed)
    document.body.insertAdjacentHTML('afterbegin', createHeader());

    // Inject bottom nav for mobile
    document.body.insertAdjacentHTML('beforeend', createBottomNav());

    // Inject mobile menu (hamburger slide-out)
    document.body.insertAdjacentHTML('beforeend', createMobileMenu());

    // Add body classes
    document.body.classList.add('has-tu-header');
    if (needsBreadcrumbs()) {
      document.body.classList.add('has-breadcrumbs');
    }
  }

  function init() {
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', injectHeader);
    } else {
      injectHeader();
    }
  }

  // Expose globally
  window.TallyupsHeader = {
    toggleMobileMenu,
    refresh: injectHeader
  };

  init();
})();

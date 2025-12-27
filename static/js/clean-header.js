/**
 * TallyUps Clean Header
 * Injects consistent header across all pages
 */

(function() {
  'use strict';

  // Page configuration
  const PAGES = {
    '/': { title: 'Dashboard', icon: 'home' },
    '/viewer': { title: 'Match', icon: 'link' },
    '/incoming': { title: 'Inbox', icon: 'inbox' },
    '/library': { title: 'Library', icon: 'book' },
    '/scanner': { title: 'Scan', icon: 'camera' },
    '/reports': { title: 'Reports', icon: 'file-text' },
    '/settings': { title: 'Settings', icon: 'settings' },
    '/gmail': { title: 'Gmail', icon: 'mail' },
    '/contacts': { title: 'Contacts', icon: 'users' }
  };

  // SVG Icons
  const ICONS = {
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    link: '<path d="M10 13a5 5 0 007.54.54l3-3a5 5 0 00-7.07-7.07l-1.72 1.71"/><path d="M14 11a5 5 0 00-7.54-.54l-3 3a5 5 0 007.07 7.07l1.71-1.71"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>',
    book: '<path d="M4 19.5A2.5 2.5 0 016.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 014 19.5v-15A2.5 2.5 0 016.5 2z"/>',
    camera: '<path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/>',
    'file-text': '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>',
    mail: '<path d="M4 4h16c1.1 0 2 .9 2 2v12c0 1.1-.9 2-2 2H4c-1.1 0-2-.9-2-2V6c0-1.1.9-2 2-2z"/><polyline points="22,6 12,13 2,6"/>',
    users: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
    search: '<circle cx="11" cy="11" r="8"/><path d="m21 21-4.35-4.35"/>',
    clipboard: '<path d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2"/><rect x="9" y="3" width="6" height="4" rx="1"/><path d="M9 12l2 2 4-4"/>'
  };

  function getIcon(name, size = 20) {
    const path = ICONS[name] || ICONS.home;
    return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${path}</svg>`;
  }

  function getCurrentPage() {
    const path = window.location.pathname;
    return PAGES[path] || { title: 'TallyUps', icon: 'clipboard' };
  }

  function createHeader() {
    const currentPage = getCurrentPage();
    const currentPath = window.location.pathname;

    const header = document.createElement('header');
    header.className = 'clean-header';
    header.innerHTML = `
      <div class="clean-header__left">
        <a href="/" class="clean-header__brand">
          <div class="clean-header__logo">
            ${getIcon('clipboard', 24)}
          </div>
          <div class="clean-header__text">
            <div class="clean-header__title">TALLYUPS</div>
            <div class="clean-header__subtitle">${currentPage.title}</div>
          </div>
        </a>
      </div>
      <nav class="clean-header__nav">
        <a href="/" class="clean-header__nav-item ${currentPath === '/' ? 'active' : ''}">${getIcon('home', 18)}<span>Home</span></a>
        <a href="/viewer" class="clean-header__nav-item ${currentPath === '/viewer' ? 'active' : ''}">${getIcon('link', 18)}<span>Match</span></a>
        <a href="/incoming" class="clean-header__nav-item ${currentPath === '/incoming' ? 'active' : ''}">${getIcon('inbox', 18)}<span>Inbox</span></a>
        <a href="/library" class="clean-header__nav-item ${currentPath === '/library' ? 'active' : ''}">${getIcon('book', 18)}<span>Library</span></a>
        <a href="/reports" class="clean-header__nav-item ${currentPath === '/reports' ? 'active' : ''}">${getIcon('file-text', 18)}<span>Reports</span></a>
      </nav>
      <div class="clean-header__actions">
        <div class="clean-header__status">
          <span class="clean-header__status-dot"></span>
          <span>Synced</span>
        </div>
        <button class="clean-header__search" onclick="window.location='/library'">
          ${getIcon('search', 16)}
          <span>Search</span>
          <kbd>⌘K</kbd>
        </button>
      </div>
    `;

    return header;
  }

  function injectStyles() {
    if (document.getElementById('clean-header-styles')) return;

    const styles = document.createElement('style');
    styles.id = 'clean-header-styles';
    styles.textContent = `
      .clean-header {
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

      .clean-header__left {
        display: flex;
        align-items: center;
      }

      .clean-header__brand {
        display: flex;
        align-items: center;
        gap: 12px;
        text-decoration: none;
        color: inherit;
      }

      .clean-header__logo {
        width: 40px;
        height: 40px;
        background: linear-gradient(135deg, #a855f7, #3b82f6);
        border-radius: 10px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
      }

      .clean-header__title {
        font-size: 18px;
        font-weight: 700;
        color: #fff;
        letter-spacing: -0.02em;
      }

      .clean-header__subtitle {
        font-size: 12px;
        color: #5a6577;
      }

      .clean-header__nav {
        display: flex;
        align-items: center;
        gap: 4px;
      }

      .clean-header__nav-item {
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

      .clean-header__nav-item:hover {
        background: rgba(255,255,255,0.05);
        color: #fff;
      }

      .clean-header__nav-item.active {
        background: rgba(0,255,136,0.1);
        color: #00ff88;
      }

      .clean-header__nav-item svg {
        flex-shrink: 0;
      }

      .clean-header__actions {
        display: flex;
        align-items: center;
        gap: 12px;
      }

      .clean-header__status {
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

      .clean-header__status-dot {
        width: 8px;
        height: 8px;
        background: #22c55e;
        border-radius: 50%;
        animation: pulse 2s ease-in-out infinite;
      }

      @keyframes pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.5; }
      }

      .clean-header__search {
        display: flex;
        align-items: center;
        gap: 8px;
        padding: 8px 14px;
        background: #111820;
        border: 1px solid rgba(255,255,255,0.1);
        border-radius: 8px;
        color: #fff;
        font-size: 13px;
        cursor: pointer;
        transition: all 0.15s ease;
      }

      .clean-header__search:hover {
        border-color: rgba(255,255,255,0.15);
        background: #1a2230;
      }

      .clean-header__search svg {
        color: #8b95a5;
      }

      .clean-header__search kbd {
        background: #1e2836;
        padding: 2px 6px;
        border-radius: 4px;
        font-size: 11px;
        font-family: inherit;
        color: #5a6577;
      }

      @media (max-width: 900px) {
        .clean-header__nav-item span { display: none; }
        .clean-header__nav-item { padding: 8px; }
        .clean-header__search span { display: none; }
        .clean-header__search kbd { display: none; }
        .clean-header__status span { display: none; }
      }

      @media (max-width: 600px) {
        .clean-header { padding: 10px 16px; }
        .clean-header__text { display: none; }
        .clean-header__nav { display: none; }
      }

      /* Body padding for header */
      body {
        padding-top: 0 !important;
        margin: 0;
        background: #0a0f14;
        color: #fff;
      }
    `;
    document.head.appendChild(styles);
  }

  function init() {
    // Don't inject on pages that have their own clean header
    if (document.querySelector('.clean-header')) return;
    if (window.location.pathname === '/') return; // Dashboard has its own

    injectStyles();
    const header = createHeader();
    document.body.insertBefore(header, document.body.firstChild);
  }

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

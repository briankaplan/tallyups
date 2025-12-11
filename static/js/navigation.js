/**
 * Tallyups Universal Navigation Component
 * Injects consistent navigation across all pages
 */

(function() {
  'use strict';

  // Navigation items configuration
  const NAV_ITEMS = [
    { href: '/', icon: 'home', label: 'Home', id: 'nav-home' },
    { href: '/viewer', icon: 'reconcile', label: 'Reconcile', id: 'nav-reconcile' },
    { href: '/library', icon: 'library', label: 'Library', id: 'nav-library' },
    { href: '/scanner', icon: 'scan', label: 'Scan', id: 'nav-scan' },
    { href: '/incoming', icon: 'inbox', label: 'Inbox', id: 'nav-inbox', badge: 'inbox-badge' },
    { href: '/reports', icon: 'reports', label: 'Reports', id: 'nav-reports' },
    { href: '/contacts', icon: 'contacts', label: 'Contacts', id: 'nav-contacts' }
  ];

  // SVG icons
  const ICONS = {
    home: '<path d="M3 9l9-7 9 7v11a2 2 0 01-2 2H5a2 2 0 01-2-2z"/><polyline points="9 22 9 12 15 12 15 22"/>',
    reconcile: '<path d="M9 11l3 3L22 4"/><path d="M21 12v7a2 2 0 01-2 2H5a2 2 0 01-2-2V5a2 2 0 012-2h11"/>',
    library: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
    scan: '<path d="M23 19a2 2 0 01-2 2H3a2 2 0 01-2-2V8a2 2 0 012-2h4l2-3h6l2 3h4a2 2 0 012 2z"/><circle cx="12" cy="13" r="4"/>',
    inbox: '<polyline points="22 12 16 12 14 15 10 15 8 12 2 12"/><path d="M5.45 5.11L2 12v6a2 2 0 002 2h16a2 2 0 002-2v-6l-3.45-6.89A2 2 0 0016.76 4H7.24a2 2 0 00-1.79 1.11z"/>',
    reports: '<path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/>',
    contacts: '<path d="M17 21v-2a4 4 0 00-4-4H5a4 4 0 00-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 00-3-3.87"/><path d="M16 3.13a4 4 0 010 7.75"/>',
    settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z"/>'
  };

  // Inject CSS styles
  function injectStyles() {
    if (document.getElementById('tallyups-nav-styles')) return;

    const styles = document.createElement('style');
    styles.id = 'tallyups-nav-styles';
    styles.textContent = `
      /* Tallyups Navigation Variables */
      :root {
        --nav-bg: rgba(0, 0, 0, 0.95);
        --nav-border: #222;
        --nav-text: #888;
        --nav-text-active: #00ff88;
        --nav-height: 64px;
        --safe-bottom: env(safe-area-inset-bottom, 0px);
        --safe-top: env(safe-area-inset-top, 0px);
      }

      /* Body padding for fixed nav */
      body {
        padding-bottom: calc(var(--nav-height) + var(--safe-bottom)) !important;
      }

      /* Main Navigation Bar */
      .tallyups-nav {
        position: fixed;
        bottom: 0;
        left: 0;
        right: 0;
        height: calc(var(--nav-height) + var(--safe-bottom));
        background: var(--nav-bg);
        backdrop-filter: blur(20px);
        -webkit-backdrop-filter: blur(20px);
        border-top: 1px solid var(--nav-border);
        display: flex;
        justify-content: space-around;
        align-items: flex-start;
        padding-top: 8px;
        padding-bottom: var(--safe-bottom);
        z-index: 9999;
        box-sizing: border-box;
      }

      /* Navigation Item */
      .tallyups-nav-item {
        display: flex;
        flex-direction: column;
        align-items: center;
        justify-content: center;
        gap: 4px;
        padding: 6px 12px;
        color: var(--nav-text);
        text-decoration: none;
        font-size: 10px;
        font-weight: 500;
        font-family: -apple-system, BlinkMacSystemFont, 'SF Pro Display', system-ui, sans-serif;
        transition: all 0.2s ease;
        position: relative;
        -webkit-tap-highlight-color: transparent;
        min-width: 48px;
      }

      .tallyups-nav-item svg {
        width: 22px;
        height: 22px;
        stroke-width: 1.75;
        transition: all 0.2s ease;
      }

      .tallyups-nav-item:hover {
        color: #ccc;
      }

      .tallyups-nav-item.active {
        color: var(--nav-text-active);
      }

      .tallyups-nav-item.active svg {
        stroke: var(--nav-text-active);
        filter: drop-shadow(0 0 6px rgba(0, 255, 136, 0.4));
      }

      /* Active indicator dot */
      .tallyups-nav-item.active::after {
        content: '';
        position: absolute;
        bottom: 0;
        left: 50%;
        transform: translateX(-50%);
        width: 4px;
        height: 4px;
        background: var(--nav-text-active);
        border-radius: 50%;
      }

      /* Badge for notifications */
      .tallyups-nav-badge {
        position: absolute;
        top: 2px;
        right: 2px;
        min-width: 16px;
        height: 16px;
        background: #ff4757;
        color: white;
        font-size: 10px;
        font-weight: 700;
        border-radius: 8px;
        display: none;
        align-items: center;
        justify-content: center;
        padding: 0 4px;
        box-sizing: border-box;
      }

      .tallyups-nav-badge.visible {
        display: flex;
      }

      /* Desktop: Show labels inline, larger touch targets */
      @media (min-width: 768px) {
        .tallyups-nav {
          --nav-height: 56px;
        }

        .tallyups-nav-item {
          flex-direction: row;
          gap: 8px;
          font-size: 13px;
          padding: 8px 16px;
          border-radius: 8px;
        }

        .tallyups-nav-item:hover {
          background: rgba(255, 255, 255, 0.05);
        }

        .tallyups-nav-item.active {
          background: rgba(0, 255, 136, 0.1);
        }

        .tallyups-nav-item.active::after {
          display: none;
        }

        .tallyups-nav-item svg {
          width: 20px;
          height: 20px;
        }
      }

      /* Large desktop: Limit nav width */
      @media (min-width: 1200px) {
        .tallyups-nav {
          left: 50%;
          transform: translateX(-50%);
          max-width: 800px;
          border-radius: 16px 16px 0 0;
          border-left: 1px solid var(--nav-border);
          border-right: 1px solid var(--nav-border);
        }
      }

      /* Reduce motion for accessibility */
      @media (prefers-reduced-motion: reduce) {
        .tallyups-nav-item,
        .tallyups-nav-item svg {
          transition: none;
        }
      }
    `;
    document.head.appendChild(styles);
  }

  // Get current page to mark active
  function getCurrentPage() {
    const path = window.location.pathname;
    if (path === '/' || path === '/dashboard') return '/';
    if (path.includes('/viewer') || path.includes('/reconcile')) return '/viewer';
    if (path.includes('/library')) return '/library';
    if (path.includes('/scanner') || path.includes('/scan')) return '/scanner';
    if (path.includes('/incoming') || path.includes('/inbox')) return '/incoming';
    if (path.includes('/report')) return '/reports';
    if (path.includes('/contact')) return '/contacts';
    if (path.includes('/setting')) return '/settings';
    return path;
  }

  // Create navigation HTML
  function createNavigation() {
    const nav = document.createElement('nav');
    nav.className = 'tallyups-nav';
    nav.id = 'tallyups-nav';
    nav.setAttribute('role', 'navigation');
    nav.setAttribute('aria-label', 'Main navigation');

    const currentPage = getCurrentPage();

    NAV_ITEMS.forEach(item => {
      const link = document.createElement('a');
      link.href = item.href;
      link.className = 'tallyups-nav-item';
      link.id = item.id;

      if (item.href === currentPage) {
        link.classList.add('active');
        link.setAttribute('aria-current', 'page');
      }

      // SVG icon
      const svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
      svg.setAttribute('viewBox', '0 0 24 24');
      svg.setAttribute('fill', 'none');
      svg.setAttribute('stroke', 'currentColor');
      svg.innerHTML = ICONS[item.icon];

      // Label
      const label = document.createElement('span');
      label.textContent = item.label;

      link.appendChild(svg);
      link.appendChild(label);

      // Badge (for inbox notifications)
      if (item.badge) {
        const badge = document.createElement('span');
        badge.className = 'tallyups-nav-badge';
        badge.id = item.badge;
        badge.textContent = '0';
        link.appendChild(badge);
      }

      nav.appendChild(link);
    });

    return nav;
  }

  // Remove existing navigation
  function removeExistingNav() {
    // Remove old bottom-nav elements
    document.querySelectorAll('.bottom-nav, nav.bottom-nav').forEach(el => el.remove());
  }

  // Initialize navigation
  function init() {
    // Don't run if already initialized
    if (document.getElementById('tallyups-nav')) return;

    injectStyles();
    removeExistingNav();

    const nav = createNavigation();
    document.body.appendChild(nav);
  }

  // Update badge count
  window.TallyupsNav = {
    setBadge: function(id, count) {
      const badge = document.getElementById(id);
      if (badge) {
        badge.textContent = count;
        badge.classList.toggle('visible', count > 0);
      }
    },
    setActive: function(href) {
      document.querySelectorAll('.tallyups-nav-item').forEach(item => {
        item.classList.toggle('active', item.getAttribute('href') === href);
      });
    }
  };

  // Run on DOM ready
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();

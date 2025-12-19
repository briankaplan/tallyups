/**
 * Tallyups Design System JavaScript
 * Theme management, toast notifications, and shared utilities
 */

// THEME MANAGEMENT
const ThemeManager = {
  STORAGE_KEY: 'tallyups-theme',
  currentTheme: 'dark',
  
  init() {
    const stored = localStorage.getItem(this.STORAGE_KEY);
    if (stored) {
      this.setTheme(stored);
    } else if (window.matchMedia('(prefers-color-scheme: light)').matches) {
      this.setTheme('light');
    } else {
      this.setTheme('dark');
    }
    
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      if (!localStorage.getItem(this.STORAGE_KEY)) {
        this.setTheme(e.matches ? 'dark' : 'light');
      }
    });
  },
  
  setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem(this.STORAGE_KEY, theme);
    this.currentTheme = theme;
    window.dispatchEvent(new CustomEvent('themechange', { detail: { theme } }));
  },
  
  toggle() {
    this.setTheme(this.currentTheme === 'dark' ? 'light' : 'dark');
  },
  
  get isDark() {
    return this.currentTheme === 'dark';
  }
};

// TOAST NOTIFICATIONS
const Toast = {
  container: null,
  
  init() {
    if (this.container) return;
    this.container = document.createElement('div');
    this.container.className = 'toast-container';
    this.container.id = 'toast-container';
    this.container.setAttribute('aria-live', 'polite');
    document.body.appendChild(this.container);
  },
  
  show(message, type, duration) {
    type = type || 'info';
    duration = duration || 3000;
    this.init();
    
    var icon = '?';
    if (type === 'success') icon = '?';
    else if (type === 'error') icon = '?';
    else if (type === 'warning') icon = '?';
    else icon = '?';
    
    var toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    toast.setAttribute('role', 'alert');
    toast.innerHTML = '<span class="toast-icon">' + icon + '</span><span class="toast-message">' + message + '</span>';
    
    this.container.appendChild(toast);
    
    if (duration > 0) {
      var self = this;
      setTimeout(function() { self.dismiss(toast); }, duration);
    }
    
    return toast;
  },
  
  dismiss(toast) {
    if (!toast || !toast.parentNode) return;
    toast.classList.add('toast-out');
    toast.addEventListener('animationend', function() { toast.remove(); });
  },
  
  success(msg, dur) { return this.show(msg, 'success', dur || 3000); },
  error(msg, dur) { return this.show(msg, 'error', dur || 5000); },
  warning(msg, dur) { return this.show(msg, 'warning', dur || 4000); },
  info(msg, dur) { return this.show(msg, 'info', dur || 3000); }
};

// Legacy showToast compatibility
function showToast(message, icon, duration) {
  icon = icon || '?';
  duration = duration || 3000;
  var type = 'info';
  if (icon === '?' || icon === '?' || icon === '?') type = 'success';
  else if (icon === '?' || icon === '?' || icon === '?') type = 'error';
  else if (icon === '?' || icon === '??') type = 'warning';
  Toast.show(message, type, duration);
}

// LOADING STATES
const Loading = {
  show(element, size) {
    size = size || 'md';
    if (typeof element === 'string') element = document.getElementById(element);
    if (!element) return;
    element.dataset.originalContent = element.innerHTML;
    element.disabled = true;
    element.setAttribute('aria-busy', 'true');
    element.innerHTML = '<span class="spinner spinner-' + size + '"></span>';
  },
  
  hide(element) {
    if (typeof element === 'string') element = document.getElementById(element);
    if (!element) return;
    element.disabled = false;
    element.removeAttribute('aria-busy');
    if (element.dataset.originalContent) {
      element.innerHTML = element.dataset.originalContent;
      delete element.dataset.originalContent;
    }
  },
  
  button(btn, loading) {
    if (typeof btn === 'string') btn = document.getElementById(btn);
    if (!btn) return;
    if (loading) {
      btn.dataset.originalText = btn.textContent;
      btn.disabled = true;
      btn.innerHTML = '<span class="spinner spinner-sm"></span> Loading...';
    } else {
      btn.disabled = false;
      btn.textContent = btn.dataset.originalText || 'Submit';
    }
  }
};

// CONFIRM DIALOG (Replace browser alerts)
const Confirm = {
  show(message, options) {
    options = options || {};
    return new Promise(function(resolve) {
      var title = options.title || 'Confirm';
      var confirmText = options.confirmText || 'Confirm';
      var cancelText = options.cancelText || 'Cancel';
      var type = options.type || 'warning';
      
      var backdrop = document.createElement('div');
      backdrop.className = 'modal-backdrop active';
      backdrop.id = 'confirm-backdrop';
      
      var modal = document.createElement('div');
      modal.className = 'modal active';
      modal.id = 'confirm-modal';
      modal.style.width = '400px';
      modal.innerHTML = '<div class="modal-header"><h3 class="modal-title">' + title + '</h3></div>' +
        '<div class="modal-body"><p style="margin:0;color:var(--text-secondary);">' + message + '</p></div>' +
        '<div class="modal-footer">' +
        '<button class="btn btn-secondary" id="confirm-cancel">' + cancelText + '</button>' +
        '<button class="btn btn-' + (type === 'danger' ? 'danger' : 'primary') + '" id="confirm-ok">' + confirmText + '</button>' +
        '</div>';
      
      document.body.appendChild(backdrop);
      document.body.appendChild(modal);
      document.body.style.overflow = 'hidden';
      
      function cleanup() {
        backdrop.remove();
        modal.remove();
        document.body.style.overflow = '';
      }
      
      modal.querySelector('#confirm-ok').addEventListener('click', function() {
        cleanup();
        resolve(true);
      });
      
      modal.querySelector('#confirm-cancel').addEventListener('click', function() {
        cleanup();
        resolve(false);
      });
      
      backdrop.addEventListener('click', function() {
        cleanup();
        resolve(false);
      });
      
      modal.querySelector('#confirm-ok').focus();
    });
  }
};

// Global theme toggle function for onclick handlers
function toggleTheme() {
  ThemeManager.toggle();
  var icon = ThemeManager.isDark ? '🌙' : '☀️';
  Toast.show('Theme: ' + (ThemeManager.isDark ? 'Dark' : 'Light'), 'info', 1500);
}

// Accessibility: Add skip link functionality
function setupAccessibility() {
  // Add skip to main content link if not present
  if (!document.querySelector('.skip-link')) {
    var skip = document.createElement('a');
    skip.href = '#main-content';
    skip.className = 'skip-link sr-only';
    skip.textContent = 'Skip to main content';
    skip.style.cssText = 'position:absolute;top:-40px;left:0;background:var(--brand-primary);color:#000;padding:8px;z-index:9999;transition:top 0.3s;';
    skip.addEventListener('focus', function() { this.style.top = '0'; });
    skip.addEventListener('blur', function() { this.style.top = '-40px'; });
    document.body.insertBefore(skip, document.body.firstChild);
  }

  // Add aria-labels to icon-only buttons
  document.querySelectorAll('button').forEach(function(btn) {
    if (!btn.getAttribute('aria-label') && btn.title) {
      btn.setAttribute('aria-label', btn.title);
    }
  });
}

// INIT ON DOM READY
document.addEventListener('DOMContentLoaded', function() {
  ThemeManager.init();
  Toast.init();
  setupAccessibility();

  // Add keyboard shortcut for theme toggle (Ctrl/Cmd + Shift + T)
  document.addEventListener('keydown', function(e) {
    if ((e.ctrlKey || e.metaKey) && e.shiftKey && e.key === 'T') {
      e.preventDefault();
      toggleTheme();
    }
  });
});

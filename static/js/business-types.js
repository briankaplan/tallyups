/**
 * Business Types Utility
 * Centralized management of dynamic business types across the app
 */

const BusinessTypes = {
  _cache: null,
  _cacheTime: null,
  _cacheDuration: 5 * 60 * 1000, // 5 minutes

  /**
   * Escape HTML to prevent XSS
   */
  _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
  },

  // Default fallback types
  defaults: [
    { name: 'Personal', color: '#4a9eff' },
    { name: 'Business', color: '#00ff88' },
    { name: 'Secondary', color: '#ff66aa' },
    { name: 'EM.co', color: '#00d4ff' }
  ],

  /**
   * Fetch business types from API with caching
   */
  async getAll() {
    // Return cache if valid
    if (this._cache && this._cacheTime && (Date.now() - this._cacheTime < this._cacheDuration)) {
      return this._cache;
    }

    try {
      const response = await fetch('/api/settings/business-types', { credentials: 'include' });
      if (response.ok) {
        const data = await response.json();
        if (data.types && data.types.length > 0) {
          this._cache = data.types;
          this._cacheTime = Date.now();
          return data.types;
        }
      }
    } catch (error) {
      console.warn('Failed to fetch business types, using defaults:', error);
    }

    // Fallback to defaults
    return this.defaults;
  },

  /**
   * Get color for a business type
   */
  async getColor(typeName) {
    const types = await this.getAll();
    const found = types.find(t => t.name.toLowerCase() === typeName.toLowerCase());
    return found ? found.color : '#888888';
  },

  /**
   * Get color synchronously (from cache or default)
   */
  getColorSync(typeName) {
    if (this._cache) {
      const found = this._cache.find(t => t.name.toLowerCase() === typeName.toLowerCase());
      if (found) return found.color;
    }
    // Check defaults
    const defaultType = this.defaults.find(t => t.name.toLowerCase() === typeName.toLowerCase());
    return defaultType ? defaultType.color : '#888888';
  },

  /**
   * Build color map object { 'Personal': '#4a9eff', ... }
   */
  async getColorMap() {
    const types = await this.getAll();
    const map = {};
    types.forEach(t => { map[t.name] = t.color; });
    return map;
  },

  /**
   * Get names only as array
   */
  async getNames() {
    const types = await this.getAll();
    return types.map(t => t.name);
  },

  /**
   * Populate a <select> element with business type options
   * @param {HTMLSelectElement} selectElement - The select to populate
   * @param {Object} options - { includeAll: boolean, includeEmpty: boolean, selected: string }
   */
  async populateSelect(selectElement, options = {}) {
    const { includeAll = false, includeEmpty = false, selected = null, emptyLabel = 'Select...' } = options;
    const types = await this.getAll();

    // Clear existing options
    selectElement.innerHTML = '';

    // Add "All" option if requested
    if (includeAll) {
      const allOpt = document.createElement('option');
      allOpt.value = '';
      allOpt.textContent = 'All';
      selectElement.appendChild(allOpt);
    }

    // Add empty/placeholder option if requested
    if (includeEmpty && !includeAll) {
      const emptyOpt = document.createElement('option');
      emptyOpt.value = '';
      emptyOpt.textContent = emptyLabel;
      selectElement.appendChild(emptyOpt);
    }

    // Add business type options
    types.forEach(t => {
      const opt = document.createElement('option');
      opt.value = t.name;
      opt.textContent = t.name;
      if (selected && t.name === selected) {
        opt.selected = true;
      }
      selectElement.appendChild(opt);
    });

    return types;
  },

  /**
   * Create filter chips/buttons for business types
   * @param {HTMLElement} container - Container to append chips to
   * @param {Function} onSelect - Callback when chip is selected (receives type name)
   */
  async createFilterChips(container, onSelect, options = {}) {
    const { includeAll = true, showCounts = false, activeType = null } = options;
    const types = await this.getAll();

    container.innerHTML = '';

    // "All" chip
    if (includeAll) {
      const allChip = document.createElement('div');
      allChip.className = 'chip' + (activeType === null ? ' active' : '');
      allChip.dataset.biz = '';
      allChip.textContent = 'All';
      allChip.onclick = () => {
        container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        allChip.classList.add('active');
        onSelect(null);
      };
      container.appendChild(allChip);
    }

    // Type chips
    types.forEach(t => {
      const chip = document.createElement('div');
      chip.className = 'chip chip-with-badge' + (activeType === t.name ? ' active' : '');
      chip.dataset.biz = t.name;
      chip.style.setProperty('--chip-color', t.color);

      if (showCounts) {
        const safeName = this._escapeHtml(t.name);
        const safeId = t.name.toLowerCase().replace(/\s+/g, '-').replace(/[^a-z0-9-]/g, '');
        chip.innerHTML = `${safeName} <span class="notification-badge" id="${safeId}-count">0</span>`;
      } else {
        chip.textContent = t.name;
      }

      chip.onclick = () => {
        container.querySelectorAll('.chip').forEach(c => c.classList.remove('active'));
        chip.classList.add('active');
        onSelect(t.name);
      };
      container.appendChild(chip);
    });

    return types;
  },

  /**
   * Create quick action buttons for business type assignment
   * @param {HTMLElement} container - Container to append buttons to
   * @param {Function} onAssign - Callback when button clicked (receives type name)
   */
  async createQuickButtons(container, onAssign) {
    const types = await this.getAll();
    container.innerHTML = '';

    types.forEach(t => {
      const btn = document.createElement('button');
      btn.className = 'action-btn business-type-btn';
      btn.style.borderColor = t.color;
      const span = document.createElement('span');
      span.style.color = t.color;
      span.textContent = t.name;
      btn.appendChild(span);
      btn.onclick = () => onAssign(t.name);
      container.appendChild(btn);
    });

    return types;
  },

  /**
   * Get gradient style for a business type (for cards/badges)
   */
  getGradient(typeName) {
    const color = this.getColorSync(typeName);
    // Create a gradient from the color
    const darkerColor = this._darkenColor(color, 20);
    return `linear-gradient(135deg, ${color}, ${darkerColor})`;
  },

  /**
   * Helper to darken a hex color
   */
  _darkenColor(hex, percent) {
    const num = parseInt(hex.replace('#', ''), 16);
    const amt = Math.round(2.55 * percent);
    const R = Math.max(0, (num >> 16) - amt);
    const G = Math.max(0, ((num >> 8) & 0x00FF) - amt);
    const B = Math.max(0, (num & 0x0000FF) - amt);
    return '#' + (0x1000000 + R * 0x10000 + G * 0x100 + B).toString(16).slice(1);
  },

  /**
   * Clear cache (call after adding/removing types)
   */
  clearCache() {
    this._cache = null;
    this._cacheTime = null;
  },

  /**
   * Force refresh from server
   */
  async refresh() {
    this.clearCache();
    return await this.getAll();
  }
};

// Make available globally
window.BusinessTypes = BusinessTypes;

// Pre-fetch on load
document.addEventListener('DOMContentLoaded', () => {
  BusinessTypes.getAll().catch(() => {});
});

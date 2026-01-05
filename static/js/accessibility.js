/**
 * Accessibility Utilities for TallyUps
 * Provides helpers for WCAG 2.1 AA compliance
 */

(function(window) {
    'use strict';

    const A11y = {
        // Live region for screen reader announcements
        _liveRegion: null,

        /**
         * Initialize accessibility features
         */
        init() {
            this._createLiveRegion();
            this._setupSkipLink();
            this._enhanceFocusManagement();
            this._setupKeyboardNavigation();
        },

        /**
         * Create a live region for dynamic announcements
         */
        _createLiveRegion() {
            if (this._liveRegion) return;

            this._liveRegion = document.createElement('div');
            this._liveRegion.setAttribute('role', 'status');
            this._liveRegion.setAttribute('aria-live', 'polite');
            this._liveRegion.setAttribute('aria-atomic', 'true');
            this._liveRegion.className = 'live-region sr-only';
            this._liveRegion.id = 'a11y-announcer';
            document.body.appendChild(this._liveRegion);
        },

        /**
         * Announce a message to screen readers
         * @param {string} message - The message to announce
         * @param {string} priority - 'polite' or 'assertive'
         */
        announce(message, priority = 'polite') {
            if (!this._liveRegion) this._createLiveRegion();

            this._liveRegion.setAttribute('aria-live', priority);

            // Clear and set to trigger announcement
            this._liveRegion.textContent = '';
            setTimeout(() => {
                this._liveRegion.textContent = message;
            }, 100);
        },

        /**
         * Setup skip to main content link
         */
        _setupSkipLink() {
            const main = document.querySelector('main, [role="main"], #main-content');
            if (!main) return;

            // Ensure main has an ID
            if (!main.id) main.id = 'main-content';

            // Check if skip link already exists
            if (document.querySelector('.skip-link')) return;

            const skipLink = document.createElement('a');
            skipLink.href = '#' + main.id;
            skipLink.className = 'skip-link';
            skipLink.textContent = 'Skip to main content';
            document.body.insertBefore(skipLink, document.body.firstChild);
        },

        /**
         * Enhanced focus management for modals and dialogs
         */
        _enhanceFocusManagement() {
            // Track last focused element before modal opens
            document.addEventListener('click', (e) => {
                const trigger = e.target.closest('[data-modal-target], [data-opens-dialog]');
                if (trigger) {
                    window._lastFocusedElement = trigger;
                }
            });
        },

        /**
         * Trap focus within a container (for modals)
         * @param {HTMLElement} container - The container to trap focus in
         */
        trapFocus(container) {
            const focusable = container.querySelectorAll(
                'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])'
            );

            if (focusable.length === 0) return;

            const firstFocusable = focusable[0];
            const lastFocusable = focusable[focusable.length - 1];

            container._focusTrapHandler = (e) => {
                if (e.key !== 'Tab') return;

                if (e.shiftKey) {
                    if (document.activeElement === firstFocusable) {
                        lastFocusable.focus();
                        e.preventDefault();
                    }
                } else {
                    if (document.activeElement === lastFocusable) {
                        firstFocusable.focus();
                        e.preventDefault();
                    }
                }
            };

            container.addEventListener('keydown', container._focusTrapHandler);
            firstFocusable.focus();
        },

        /**
         * Release focus trap
         * @param {HTMLElement} container - The container to release
         */
        releaseFocus(container) {
            if (container._focusTrapHandler) {
                container.removeEventListener('keydown', container._focusTrapHandler);
                delete container._focusTrapHandler;
            }

            // Return focus to trigger element
            if (window._lastFocusedElement) {
                window._lastFocusedElement.focus();
                window._lastFocusedElement = null;
            }
        },

        /**
         * Setup keyboard navigation helpers
         */
        _setupKeyboardNavigation() {
            // Arrow key navigation for lists and grids
            document.addEventListener('keydown', (e) => {
                const target = e.target;

                // Handle Escape to close modals/dropdowns
                if (e.key === 'Escape') {
                    const modal = document.querySelector('[role="dialog"]:not([aria-hidden="true"])');
                    if (modal) {
                        const closeBtn = modal.querySelector('[data-dismiss], .close-btn, [aria-label*="close" i]');
                        if (closeBtn) closeBtn.click();
                    }
                }

                // Arrow navigation in lists
                if (['ArrowUp', 'ArrowDown'].includes(e.key)) {
                    const list = target.closest('[role="listbox"], [role="menu"]');
                    if (list) {
                        const items = list.querySelectorAll('[role="option"], [role="menuitem"]');
                        const currentIndex = Array.from(items).indexOf(target);

                        let nextIndex;
                        if (e.key === 'ArrowDown') {
                            nextIndex = currentIndex < items.length - 1 ? currentIndex + 1 : 0;
                        } else {
                            nextIndex = currentIndex > 0 ? currentIndex - 1 : items.length - 1;
                        }

                        items[nextIndex].focus();
                        e.preventDefault();
                    }
                }
            });
        },

        /**
         * Add loading state to a button
         * @param {HTMLElement} button - The button element
         * @param {boolean} loading - Whether to show loading state
         * @param {string} loadingText - Text to show while loading
         */
        setButtonLoading(button, loading, loadingText = 'Loading...') {
            if (loading) {
                button._originalText = button.textContent;
                button._originalDisabled = button.disabled;
                button.disabled = true;
                button.setAttribute('aria-busy', 'true');
                button.innerHTML = `<span class="sr-only">${loadingText}</span><span aria-hidden="true">${loadingText}</span>`;
            } else {
                button.disabled = button._originalDisabled || false;
                button.removeAttribute('aria-busy');
                if (button._originalText) {
                    button.textContent = button._originalText;
                }
            }
        },

        /**
         * Announce form validation errors
         * @param {HTMLFormElement} form - The form element
         */
        announceFormErrors(form) {
            const errors = form.querySelectorAll('.error-message, .form-error, [role="alert"]');
            if (errors.length === 0) return;

            const messages = Array.from(errors).map(e => e.textContent).join('. ');
            this.announce(`Form has ${errors.length} error${errors.length > 1 ? 's' : ''}: ${messages}`, 'assertive');
        },

        /**
         * Set up accessible table with sortable headers
         * @param {HTMLTableElement} table - The table element
         */
        enhanceTable(table) {
            const headers = table.querySelectorAll('th[data-sortable]');

            headers.forEach(th => {
                th.setAttribute('role', 'columnheader');
                th.setAttribute('aria-sort', 'none');
                th.setAttribute('tabindex', '0');

                // Add sort button wrapper
                const text = th.textContent;
                th.innerHTML = `<button type="button" class="sort-btn">${text}<span class="sr-only">, sortable</span></button>`;
            });
        }
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => A11y.init());
    } else {
        A11y.init();
    }

    // Export
    window.A11y = A11y;

})(window);

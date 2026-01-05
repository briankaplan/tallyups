/**
 * Loading States Utility for TallyUps
 * Provides consistent loading states for buttons and forms
 */

(function(window) {
    'use strict';

    const LoadingStates = {
        // Default spinner HTML
        _spinnerSVG: `<svg class="loading-spinner" width="16" height="16" viewBox="0 0 16 16" fill="none" xmlns="http://www.w3.org/2000/svg">
            <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-dasharray="28.3" stroke-dashoffset="10">
                <animateTransform attributeName="transform" type="rotate" from="0 8 8" to="360 8 8" dur="0.8s" repeatCount="indefinite"/>
            </circle>
        </svg>`,

        // Store original button states
        _originalStates: new WeakMap(),

        /**
         * Set a button to loading state
         * @param {HTMLElement} button - The button element
         * @param {string} [loadingText] - Optional text to show while loading
         * @returns {Function} - Function to call to restore the button
         */
        setLoading(button, loadingText = null) {
            if (!button || button.hasAttribute('data-loading')) {
                return () => {};
            }

            // Store original state
            this._originalStates.set(button, {
                innerHTML: button.innerHTML,
                disabled: button.disabled,
                ariaDisabled: button.getAttribute('aria-disabled'),
                width: button.style.width
            });

            // Preserve button width to prevent layout shift
            const rect = button.getBoundingClientRect();
            button.style.minWidth = `${rect.width}px`;

            // Set loading state
            button.setAttribute('data-loading', 'true');
            button.setAttribute('aria-busy', 'true');
            button.disabled = true;

            // Build loading content
            const text = loadingText || button.getAttribute('data-loading-text') || 'Loading...';
            button.innerHTML = `
                <span class="btn-loading-content">
                    ${this._spinnerSVG}
                    <span class="btn-loading-text">${text}</span>
                </span>
            `;

            // Return restore function
            return () => this.clearLoading(button);
        },

        /**
         * Clear loading state from a button
         * @param {HTMLElement} button - The button element
         * @param {boolean} [success] - Show success state briefly
         */
        clearLoading(button, success = false) {
            if (!button || !button.hasAttribute('data-loading')) {
                return;
            }

            const original = this._originalStates.get(button);
            if (!original) {
                return;
            }

            button.removeAttribute('data-loading');
            button.removeAttribute('aria-busy');

            if (success) {
                // Show success checkmark briefly
                button.innerHTML = `
                    <span class="btn-success-content">
                        <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                            <path d="M3 8L6.5 11.5L13 4" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                        </svg>
                        <span>Done</span>
                    </span>
                `;
                button.classList.add('btn-success');

                setTimeout(() => {
                    this._restoreButton(button, original);
                }, 1500);
            } else {
                this._restoreButton(button, original);
            }
        },

        /**
         * Restore button to original state
         */
        _restoreButton(button, original) {
            button.innerHTML = original.innerHTML;
            button.disabled = original.disabled;
            button.style.minWidth = '';
            button.classList.remove('btn-success');

            if (original.ariaDisabled !== null) {
                button.setAttribute('aria-disabled', original.ariaDisabled);
            } else {
                button.removeAttribute('aria-disabled');
            }

            this._originalStates.delete(button);
        },

        /**
         * Set error state on a button briefly
         * @param {HTMLElement} button - The button element
         * @param {string} [errorText] - Error message to show
         */
        setError(button, errorText = 'Error') {
            this.clearLoading(button);

            const original = this._originalStates.get(button) || {
                innerHTML: button.innerHTML,
                disabled: button.disabled
            };

            this._originalStates.set(button, original);

            button.innerHTML = `
                <span class="btn-error-content">
                    <svg width="16" height="16" viewBox="0 0 16 16" fill="none">
                        <circle cx="8" cy="8" r="6" stroke="currentColor" stroke-width="2"/>
                        <path d="M8 5V9M8 11V11.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/>
                    </svg>
                    <span>${errorText}</span>
                </span>
            `;
            button.classList.add('btn-error');

            setTimeout(() => {
                button.classList.remove('btn-error');
                this._restoreButton(button, original);
            }, 2500);
        },

        /**
         * Auto-bind loading states to forms
         * @param {HTMLFormElement} form - The form element
         */
        bindForm(form) {
            if (!form || form.hasAttribute('data-loading-bound')) {
                return;
            }

            form.setAttribute('data-loading-bound', 'true');

            form.addEventListener('submit', (e) => {
                const submitBtn = form.querySelector('button[type="submit"], input[type="submit"]');
                if (submitBtn && !submitBtn.hasAttribute('data-no-loading')) {
                    this.setLoading(submitBtn);
                }
            });
        },

        /**
         * Auto-bind loading to all buttons with data-loading-text
         */
        bindAll() {
            // Bind buttons with data-loading-text attribute
            document.querySelectorAll('button[data-loading-text]').forEach(button => {
                if (button.hasAttribute('data-loading-bound')) return;
                button.setAttribute('data-loading-bound', 'true');

                button.addEventListener('click', () => {
                    // Only auto-set if not in a form (forms handle their own loading)
                    if (!button.closest('form')) {
                        this.setLoading(button);
                    }
                });
            });

            // Bind all forms
            document.querySelectorAll('form:not([data-no-loading])').forEach(form => {
                this.bindForm(form);
            });
        },

        /**
         * Wrap an async function with loading state
         * @param {HTMLElement} button - The button element
         * @param {Function} asyncFn - Async function to execute
         * @param {Object} options - Options
         * @returns {Promise} - Result of asyncFn
         */
        async withLoading(button, asyncFn, options = {}) {
            const { loadingText, showSuccess = true } = options;
            const restore = this.setLoading(button, loadingText);

            try {
                const result = await asyncFn();
                this.clearLoading(button, showSuccess);
                return result;
            } catch (error) {
                if (options.errorText) {
                    this.setError(button, options.errorText);
                } else {
                    this.clearLoading(button);
                }
                throw error;
            }
        },

        /**
         * Create a progress button that shows completion percentage
         * @param {HTMLElement} button - The button element
         * @param {number} progress - Progress 0-100
         */
        setProgress(button, progress) {
            if (!button.hasAttribute('data-progress')) {
                // First time - store original and setup
                this._originalStates.set(button, {
                    innerHTML: button.innerHTML,
                    disabled: button.disabled
                });
                button.setAttribute('data-progress', '0');
                button.disabled = true;
            }

            const clampedProgress = Math.min(100, Math.max(0, progress));
            button.setAttribute('data-progress', clampedProgress.toString());
            button.innerHTML = `
                <span class="btn-progress-content">
                    <span class="btn-progress-bar" style="width: ${clampedProgress}%"></span>
                    <span class="btn-progress-text">${Math.round(clampedProgress)}%</span>
                </span>
            `;

            if (clampedProgress >= 100) {
                setTimeout(() => this.clearProgress(button), 500);
            }
        },

        /**
         * Clear progress state from button
         * @param {HTMLElement} button - The button element
         */
        clearProgress(button) {
            const original = this._originalStates.get(button);
            if (original) {
                button.removeAttribute('data-progress');
                this._restoreButton(button, original);
            }
        }
    };

    // Auto-initialize on DOM ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', () => LoadingStates.bindAll());
    } else {
        LoadingStates.bindAll();
    }

    // Export
    window.LoadingStates = LoadingStates;

})(window);

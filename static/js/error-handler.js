/**
 * Error Handler - Unified Error Handling
 * ======================================
 * Provides consistent error handling, display, and recovery across all pages.
 *
 * Usage:
 *   ErrorHandler.show('Failed to load data', 'error');
 *   ErrorHandler.showApiError(response);
 *   ErrorHandler.wrap(async () => { ... });
 */

const ErrorHandler = {
    // Toast container reference
    toastContainer: null,

    // Error log for debugging
    errorLog: [],
    maxLogSize: 50,

    /**
     * Initialize error handler (call on DOMContentLoaded)
     */
    init() {
        // Create toast container if needed
        if (!this.toastContainer) {
            this.toastContainer = document.querySelector('.toast-container');
            if (!this.toastContainer) {
                this.toastContainer = document.createElement('div');
                this.toastContainer.className = 'toast-container';
                document.body.appendChild(this.toastContainer);
            }
        }

        // Global error handler
        window.addEventListener('error', (e) => {
            this.logError('Uncaught Error', e.error || e.message);
        });

        // Unhandled promise rejection handler
        window.addEventListener('unhandledrejection', (e) => {
            this.logError('Unhandled Promise Rejection', e.reason);
        });
    },

    /**
     * Show an error/success/info message to the user.
     * @param {string} message - Message to display
     * @param {string} type - 'error', 'success', 'warning', 'info'
     * @param {number} duration - Time in ms to show (0 for persistent)
     */
    show(message, type = 'error', duration = 5000) {
        if (!this.toastContainer) this.init();

        const icons = {
            error: '❌',
            success: '✅',
            warning: '⚠️',
            info: 'ℹ️'
        };

        const toast = document.createElement('div');
        toast.className = `toast toast-${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${this.escapeHtml(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">×</button>
        `;

        this.toastContainer.appendChild(toast);

        // Animate in
        requestAnimationFrame(() => toast.classList.add('show'));

        // Auto-remove
        if (duration > 0) {
            setTimeout(() => {
                toast.classList.remove('show');
                setTimeout(() => toast.remove(), 300);
            }, duration);
        }

        // Log errors
        if (type === 'error') {
            this.logError('User Error', message);
        }
    },

    /**
     * Show error from an API response.
     * @param {Response} response - Fetch response object
     * @param {string} fallbackMessage - Default message if none in response
     */
    async showApiError(response, fallbackMessage = 'Request failed') {
        let message = fallbackMessage;

        try {
            const data = await response.json();
            if (data.error) message = data.error;
            else if (data.message) message = data.message;
        } catch {
            // Response wasn't JSON, use status text
            message = `${fallbackMessage}: ${response.statusText || response.status}`;
        }

        // Handle specific status codes
        if (response.status === 401) {
            message = 'Please log in to continue';
            // Optionally redirect to login
            setTimeout(() => {
                if (window.location.pathname !== '/login') {
                    window.location.href = '/login?redirect=' + encodeURIComponent(window.location.pathname);
                }
            }, 2000);
        } else if (response.status === 403) {
            message = 'You do not have permission to perform this action';
        } else if (response.status === 404) {
            message = 'Resource not found';
        } else if (response.status >= 500) {
            message = 'Server error. Please try again later.';
        }

        this.show(message, 'error');
    },

    /**
     * Wrap an async function with error handling.
     * @param {Function} fn - Async function to execute
     * @param {Object} options - {onError, showToast, rethrow}
     */
    async wrap(fn, options = {}) {
        const { onError, showToast = true, rethrow = false, fallbackMessage = 'An error occurred' } = options;

        try {
            return await fn();
        } catch (error) {
            this.logError('Wrapped Function Error', error);

            if (showToast) {
                this.show(error.message || fallbackMessage, 'error');
            }

            if (onError) {
                onError(error);
            }

            if (rethrow) {
                throw error;
            }

            return null;
        }
    },

    /**
     * Create a retry wrapper for flaky operations.
     * @param {Function} fn - Async function to retry
     * @param {number} maxRetries - Max number of retries
     * @param {number} delay - Delay between retries in ms
     */
    async retry(fn, maxRetries = 3, delay = 1000) {
        let lastError;

        for (let attempt = 1; attempt <= maxRetries; attempt++) {
            try {
                return await fn();
            } catch (error) {
                lastError = error;
                this.logError(`Retry Attempt ${attempt}/${maxRetries}`, error);

                if (attempt < maxRetries) {
                    await new Promise(resolve => setTimeout(resolve, delay * attempt));
                }
            }
        }

        this.show(`Operation failed after ${maxRetries} attempts`, 'error');
        throw lastError;
    },

    /**
     * Show a loading state with error recovery.
     * @param {HTMLElement} container - Container to show loading in
     * @param {Function} loadFn - Async function to load data
     * @param {Function} renderFn - Function to render loaded data
     */
    async loadWithRetry(container, loadFn, renderFn) {
        // Show loading state
        const originalContent = container.innerHTML;
        container.innerHTML = `
            <div class="loading-state">
                <div class="loading-spinner"></div>
                <p>Loading...</p>
            </div>
        `;

        try {
            const data = await this.retry(loadFn);
            container.innerHTML = '';
            renderFn(data, container);
        } catch (error) {
            container.innerHTML = `
                <div class="error-state">
                    <div class="error-icon">❌</div>
                    <p class="error-message">Failed to load data</p>
                    <button class="retry-btn" onclick="location.reload()">Retry</button>
                </div>
            `;
        }
    },

    /**
     * Show confirmation dialog before destructive action.
     * @param {string} message - Confirmation message
     * @param {Function} onConfirm - Function to call if confirmed
     * @param {Object} options - {title, confirmText, cancelText, danger}
     */
    confirm(message, onConfirm, options = {}) {
        const {
            title = 'Confirm Action',
            confirmText = 'Confirm',
            cancelText = 'Cancel',
            danger = false
        } = options;

        // Create modal backdrop
        const modal = document.createElement('div');
        modal.className = 'confirm-modal';
        modal.innerHTML = `
            <div class="confirm-backdrop"></div>
            <div class="confirm-content">
                <h3 class="confirm-title">${this.escapeHtml(title)}</h3>
                <p class="confirm-message">${this.escapeHtml(message)}</p>
                <div class="confirm-buttons">
                    <button class="confirm-cancel">${this.escapeHtml(cancelText)}</button>
                    <button class="confirm-ok ${danger ? 'danger' : ''}">${this.escapeHtml(confirmText)}</button>
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('show'));

        const cleanup = () => {
            modal.classList.remove('show');
            setTimeout(() => modal.remove(), 300);
        };

        modal.querySelector('.confirm-backdrop').onclick = cleanup;
        modal.querySelector('.confirm-cancel').onclick = cleanup;
        modal.querySelector('.confirm-ok').onclick = () => {
            cleanup();
            onConfirm();
        };

        // Focus confirm button
        modal.querySelector('.confirm-ok').focus();
    },

    /**
     * Log an error for debugging.
     */
    logError(context, error) {
        const entry = {
            timestamp: new Date().toISOString(),
            context,
            message: error?.message || String(error),
            stack: error?.stack,
            url: window.location.href
        };

        this.errorLog.push(entry);
        if (this.errorLog.length > this.maxLogSize) {
            this.errorLog.shift();
        }

        console.error(`[ErrorHandler] ${context}:`, error);
    },

    /**
     * Get error log for debugging.
     */
    getLog() {
        return [...this.errorLog];
    },

    /**
     * Clear error log.
     */
    clearLog() {
        this.errorLog = [];
    },

    /**
     * Escape HTML to prevent XSS.
     */
    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/[&<>"']/g, c => ({
            '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
        }[c]));
    }
};

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => ErrorHandler.init());
} else {
    ErrorHandler.init();
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ErrorHandler;
}

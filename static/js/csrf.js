/**
 * CSRF Protection for AJAX Requests
 *
 * This module provides utilities to handle CSRF tokens in fetch requests.
 * Include this script in any page that makes POST/PUT/DELETE requests.
 *
 * Usage:
 *   // Either use csrfFetch as a drop-in replacement for fetch:
 *   csrfFetch('/api/endpoint', { method: 'POST', body: JSON.stringify(data) });
 *
 *   // Or get the token and add it manually:
 *   const token = getCsrfToken();
 *   fetch('/api/endpoint', {
 *     method: 'POST',
 *     headers: { 'X-CSRFToken': token }
 *   });
 */

(function(window) {
    'use strict';

    // Cache the CSRF token
    let _csrfToken = null;

    /**
     * Get the CSRF token from page meta tag or response header
     * @returns {string|null} The CSRF token or null if not found
     */
    function getCsrfToken() {
        // Return cached token if available
        if (_csrfToken) {
            return _csrfToken;
        }

        // Try to get from meta tag first (fastest)
        const metaTag = document.querySelector('meta[name="csrf-token"]');
        if (metaTag) {
            _csrfToken = metaTag.getAttribute('content');
            return _csrfToken;
        }

        // Try to get from hidden input (for forms)
        const inputField = document.querySelector('input[name="csrf_token"]');
        if (inputField) {
            _csrfToken = inputField.value;
            return _csrfToken;
        }

        return null;
    }

    /**
     * Refresh the CSRF token by fetching from server
     * @returns {Promise<string>} Promise resolving to new CSRF token
     */
    async function refreshCsrfToken() {
        try {
            const response = await fetch('/api/csrf-token', {
                method: 'GET',
                credentials: 'include'
            });

            if (response.ok) {
                const data = await response.json();
                _csrfToken = data.csrf_token;

                // Update meta tag if it exists
                const metaTag = document.querySelector('meta[name="csrf-token"]');
                if (metaTag) {
                    metaTag.setAttribute('content', _csrfToken);
                }

                return _csrfToken;
            }
        } catch (e) {
            console.warn('Failed to refresh CSRF token:', e);
        }
        return null;
    }

    /**
     * Wrapper around fetch that automatically includes CSRF token
     * @param {string} url - The URL to fetch
     * @param {Object} options - Fetch options
     * @returns {Promise<Response>} Fetch response
     */
    async function csrfFetch(url, options = {}) {
        const method = (options.method || 'GET').toUpperCase();

        // Only add CSRF token for state-changing methods
        if (['POST', 'PUT', 'DELETE', 'PATCH'].includes(method)) {
            let token = getCsrfToken();

            // Try to get token if not cached
            if (!token) {
                token = await refreshCsrfToken();
            }

            // Add token to headers if we have one
            if (token) {
                options.headers = options.headers || {};
                // Use X-CSRFToken for Flask-WTF
                options.headers['X-CSRFToken'] = token;
            }
        }

        // Always include credentials for session cookies
        options.credentials = options.credentials || 'include';

        const response = await fetch(url, options);

        // If we get a 400 error that might be CSRF related, try refreshing token
        if (response.status === 400) {
            const clone = response.clone();
            try {
                const data = await clone.json();
                if (data.error && data.error.toLowerCase().includes('csrf')) {
                    // Token expired, refresh and retry
                    console.log('CSRF token expired, refreshing...');
                    const newToken = await refreshCsrfToken();
                    if (newToken) {
                        options.headers['X-CSRFToken'] = newToken;
                        return fetch(url, options);
                    }
                }
            } catch (e) {
                // Response wasn't JSON, return original
            }
        }

        return response;
    }

    /**
     * Add CSRF token to a form element
     * @param {HTMLFormElement} form - The form to add token to
     */
    function addCsrfToForm(form) {
        const token = getCsrfToken();
        if (!token) {
            console.warn('No CSRF token available for form');
            return;
        }

        let input = form.querySelector('input[name="csrf_token"]');
        if (!input) {
            input = document.createElement('input');
            input.type = 'hidden';
            input.name = 'csrf_token';
            form.appendChild(input);
        }
        input.value = token;
    }

    /**
     * Initialize CSRF protection on page load
     * - Auto-adds token to all forms with method="post"
     * - Sets up token refresh on visibility change
     */
    function initCsrf() {
        // Add token to all POST forms
        document.querySelectorAll('form[method="post"], form[method="POST"]').forEach(form => {
            addCsrfToForm(form);
        });

        // Refresh token when page becomes visible (handles tab switching)
        document.addEventListener('visibilitychange', () => {
            if (document.visibilityState === 'visible') {
                // Token might have expired while tab was inactive
                refreshCsrfToken();
            }
        });

        // Initial token fetch if not in page
        if (!getCsrfToken()) {
            refreshCsrfToken();
        }
    }

    // Auto-initialize when DOM is ready
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initCsrf);
    } else {
        initCsrf();
    }

    // Export functions globally
    window.getCsrfToken = getCsrfToken;
    window.refreshCsrfToken = refreshCsrfToken;
    window.csrfFetch = csrfFetch;
    window.addCsrfToForm = addCsrfToForm;

})(window);

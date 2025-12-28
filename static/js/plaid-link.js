/**
 * ============================================================================
 * Plaid Link Integration Module
 * ============================================================================
 * Author: Claude Code
 * Created: 2025-12-20
 *
 * Handles Plaid Link flow for connecting bank accounts.
 *
 * USAGE:
 * ------
 *   <script src="https://cdn.plaid.com/link/v2/stable/link-initialize.js"></script>
 *   <script src="/static/js/plaid-link.js"></script>
 *
 *   // Connect a new account
 *   PlaidLink.connect();
 *
 *   // Update existing connection (re-auth)
 *   PlaidLink.update('item-xxx');
 *
 * EVENTS:
 * -------
 *   plaid:connected     - New account connected successfully
 *   plaid:updated       - Existing account re-authenticated
 *   plaid:error         - Error occurred during linking
 *   plaid:exit          - User closed Plaid Link
 *
 * ============================================================================
 */

(function(window) {
    'use strict';

    // =========================================================================
    // CONFIGURATION
    // =========================================================================

    const CONFIG = {
        // API endpoints
        endpoints: {
            linkToken: '/api/plaid/link-token',
            exchangeToken: '/api/plaid/exchange-token',
            items: '/api/plaid/items',
            accounts: '/api/plaid/accounts',
            sync: '/api/plaid/sync',
            status: '/api/plaid/status'
        },

        // Plaid Link config
        linkOptions: {
            env: 'production',  // Will be set based on server config
            product: ['transactions'],
            countryCodes: ['US'],
            language: 'en'
        }
    };

    // =========================================================================
    // STATE
    // =========================================================================

    let plaidHandler = null;
    let isInitialized = false;
    let currentItemId = null;

    // =========================================================================
    // UTILITY FUNCTIONS
    // =========================================================================

    /**
     * Make an authenticated API request.
     */
    async function apiRequest(endpoint, options = {}) {
        const defaults = {
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin'
        };

        // Get CSRF token if available
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        if (csrfToken) {
            defaults.headers['X-CSRFToken'] = csrfToken;
        }

        const response = await fetch(endpoint, { ...defaults, ...options });

        // Check response.ok BEFORE parsing JSON to handle non-JSON error responses
        if (!response.ok) {
            let errorMessage = `HTTP ${response.status}`;
            try {
                const data = await response.json();
                errorMessage = data.error || errorMessage;
            } catch (e) {
                // Response wasn't JSON, use status message
            }
            throw new Error(errorMessage);
        }

        return await response.json();
    }

    /**
     * Dispatch a custom event.
     */
    function dispatchEvent(name, detail = {}) {
        window.dispatchEvent(new CustomEvent(name, { detail }));
    }

    /**
     * Show a toast notification.
     */
    function showToast(message, type = 'info') {
        // Use existing toast system if available
        if (window.showToast) {
            window.showToast(message, type);
            return;
        }

        // Fallback: create simple toast
        const toast = document.createElement('div');
        toast.className = `plaid-toast plaid-toast-${type}`;
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            bottom: 100px;
            left: 50%;
            transform: translateX(-50%);
            background: ${type === 'error' ? '#ff4444' : type === 'success' ? '#00ff88' : '#4488ff'};
            color: ${type === 'success' ? '#000' : '#fff'};
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 500;
            z-index: 10000;
            animation: fadeInUp 0.3s ease;
        `;

        document.body.appendChild(toast);
        setTimeout(() => toast.remove(), 3000);
    }

    // =========================================================================
    // PLAID LINK FUNCTIONS
    // =========================================================================

    /**
     * Initialize Plaid Link with a link token.
     */
    async function initializeLink(linkToken, options = {}) {
        return new Promise((resolve, reject) => {
            if (!window.Plaid) {
                reject(new Error('Plaid SDK not loaded. Include link-initialize.js'));
                return;
            }

            const config = {
                token: linkToken,

                onSuccess: async (publicToken, metadata) => {
                    console.log('Plaid Link success:', metadata);

                    try {
                        // Exchange public token for access token
                        const result = await apiRequest(CONFIG.endpoints.exchangeToken, {
                            method: 'POST',
                            body: JSON.stringify({ public_token: publicToken })
                        });

                        if (result.success) {
                            showToast(`Connected ${result.item.institution_name}!`, 'success');
                            dispatchEvent('plaid:connected', {
                                item: result.item,
                                accounts: result.accounts
                            });
                            resolve(result);
                        } else {
                            throw new Error(result.error || 'Token exchange failed');
                        }
                    } catch (error) {
                        console.error('Token exchange error:', error);
                        showToast('Failed to complete connection', 'error');
                        dispatchEvent('plaid:error', { error });
                        reject(error);
                    }
                },

                onExit: (error, metadata) => {
                    console.log('Plaid Link exit:', error, metadata);

                    if (error) {
                        dispatchEvent('plaid:error', { error, metadata });
                    } else {
                        dispatchEvent('plaid:exit', { metadata });
                    }

                    // Don't reject on normal exit
                    if (error) {
                        reject(error);
                    }
                },

                onEvent: (eventName, metadata) => {
                    console.log('Plaid Link event:', eventName, metadata);
                },

                ...options
            };

            plaidHandler = window.Plaid.create(config);
            isInitialized = true;
            resolve(plaidHandler);
        });
    }

    /**
     * Connect a new bank account.
     */
    async function connect(options = {}) {
        try {
            showToast('Preparing secure connection...', 'info');

            // Get link token from server
            const tokenResult = await apiRequest(CONFIG.endpoints.linkToken, {
                method: 'POST',
                body: JSON.stringify(options)
            });

            if (!tokenResult.success) {
                throw new Error(tokenResult.error || 'Failed to get link token');
            }

            // Initialize and open Plaid Link
            await initializeLink(tokenResult.link_token, options);
            plaidHandler.open();

        } catch (error) {
            console.error('Plaid connect error:', error);
            showToast(error.message || 'Failed to start bank connection', 'error');
            dispatchEvent('plaid:error', { error });
            throw error;
        }
    }

    /**
     * Update an existing connection (re-authentication).
     */
    async function update(itemId, options = {}) {
        try {
            currentItemId = itemId;
            showToast('Preparing secure re-authentication...', 'info');

            // Get update link token
            const tokenResult = await apiRequest(CONFIG.endpoints.linkToken, {
                method: 'POST',
                body: JSON.stringify({ update_item_id: itemId, ...options })
            });

            if (!tokenResult.success) {
                throw new Error(tokenResult.error || 'Failed to get update token');
            }

            // Initialize and open Plaid Link in update mode
            await initializeLink(tokenResult.link_token, {
                ...options,
                onSuccess: async (publicToken, metadata) => {
                    // For update mode, we don't exchange the token
                    showToast('Account re-authenticated!', 'success');
                    dispatchEvent('plaid:updated', { itemId, metadata });
                }
            });
            plaidHandler.open();

        } catch (error) {
            console.error('Plaid update error:', error);
            showToast(error.message || 'Failed to start re-authentication', 'error');
            dispatchEvent('plaid:error', { error });
            throw error;
        }
    }

    /**
     * Get all linked Items (bank connections).
     */
    async function getItems() {
        try {
            const result = await apiRequest(CONFIG.endpoints.items);
            return result.items || [];
        } catch (error) {
            console.error('Failed to get items:', error);
            throw error;
        }
    }

    /**
     * Get all accounts.
     */
    async function getAccounts(itemId = null) {
        try {
            const url = itemId
                ? `${CONFIG.endpoints.accounts}?item_id=${itemId}`
                : CONFIG.endpoints.accounts;
            const result = await apiRequest(url);
            return result.accounts || [];
        } catch (error) {
            console.error('Failed to get accounts:', error);
            throw error;
        }
    }

    /**
     * Remove an Item (disconnect bank).
     */
    async function removeItem(itemId) {
        try {
            const result = await apiRequest(`${CONFIG.endpoints.items}/${itemId}`, {
                method: 'DELETE'
            });

            if (result.success) {
                showToast('Bank disconnected', 'success');
                dispatchEvent('plaid:removed', { itemId });
            }

            return result;
        } catch (error) {
            console.error('Failed to remove item:', error);
            showToast('Failed to disconnect bank', 'error');
            throw error;
        }
    }

    /**
     * Trigger a manual sync.
     */
    async function sync(itemId = null) {
        try {
            showToast('Syncing transactions...', 'info');

            const result = await apiRequest(CONFIG.endpoints.sync, {
                method: 'POST',
                body: JSON.stringify({ item_id: itemId })
            });

            if (result.success) {
                const total = result.results.reduce((sum, r) => sum + (r.added || 0), 0);
                showToast(`Synced ${total} new transactions`, 'success');
                dispatchEvent('plaid:synced', { results: result.results });
            }

            return result;
        } catch (error) {
            console.error('Sync failed:', error);
            showToast('Sync failed', 'error');
            throw error;
        }
    }

    /**
     * Get Plaid integration status.
     */
    async function getStatus() {
        try {
            const result = await apiRequest(CONFIG.endpoints.status);
            return result;
        } catch (error) {
            console.error('Failed to get status:', error);
            throw error;
        }
    }

    /**
     * Update account settings.
     */
    async function updateAccount(accountId, settings) {
        try {
            const result = await apiRequest(`${CONFIG.endpoints.accounts}/${accountId}`, {
                method: 'PUT',
                body: JSON.stringify(settings)
            });

            if (result.success) {
                showToast('Account updated', 'success');
            }

            return result;
        } catch (error) {
            console.error('Failed to update account:', error);
            showToast('Failed to update account', 'error');
            throw error;
        }
    }

    // =========================================================================
    // UI HELPERS
    // =========================================================================

    /**
     * Render the connected accounts list.
     */
    async function renderAccountsList(container) {
        const wrapper = typeof container === 'string'
            ? document.querySelector(container)
            : container;

        if (!wrapper) {
            console.error('Container not found');
            return;
        }

        try {
            const items = await getItems();

            if (items.length === 0) {
                wrapper.innerHTML = `
                    <div class="plaid-empty-state">
                        <div class="plaid-empty-icon">
                            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5">
                                <path d="M3 10h18M3 14h18M3 18h18M3 6h18"/>
                                <rect x="1" y="4" width="22" height="16" rx="2"/>
                            </svg>
                        </div>
                        <h3>No Bank Accounts Connected</h3>
                        <p>Connect your bank accounts to automatically sync transactions.</p>
                        <button class="plaid-connect-btn" onclick="PlaidLink.connect()">
                            <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                <path d="M12 5v14M5 12h14"/>
                            </svg>
                            Connect Bank Account
                        </button>
                    </div>
                `;
                return;
            }

            // Render items with their accounts
            let html = '<div class="plaid-items-list">';

            for (const item of items) {
                const accounts = await getAccounts(item.item_id);
                const statusClass = item.status === 'active' ? 'success' :
                                   item.status === 'needs_reauth' ? 'warning' : 'error';

                html += `
                    <div class="plaid-item-card" data-item-id="${item.item_id}">
                        <div class="plaid-item-header">
                            <div class="plaid-item-info">
                                <h3 class="plaid-item-name">${item.institution_name || 'Bank Account'}</h3>
                                <span class="plaid-item-status ${statusClass}">
                                    ${item.status === 'active' ? 'Connected' :
                                      item.status === 'needs_reauth' ? 'Needs Re-auth' : item.status}
                                </span>
                            </div>
                            <div class="plaid-item-actions">
                                ${item.status === 'needs_reauth' ? `
                                    <button class="plaid-btn plaid-btn-warning" onclick="PlaidLink.update('${item.item_id}')">
                                        Re-authenticate
                                    </button>
                                ` : ''}
                                <button class="plaid-btn plaid-btn-sync" onclick="PlaidLink.sync('${item.item_id}')">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M21 12a9 9 0 11-18 0 9 9 0 0118 0z"/>
                                        <path d="M9 12l2 2 4-4"/>
                                    </svg>
                                    Sync
                                </button>
                                <button class="plaid-btn plaid-btn-remove" onclick="PlaidLink.removeItem('${item.item_id}')">
                                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                                        <path d="M18 6L6 18M6 6l12 12"/>
                                    </svg>
                                </button>
                            </div>
                        </div>
                        <div class="plaid-accounts-list">
                            ${accounts.map(acct => `
                                <div class="plaid-account-row" data-account-id="${acct.account_id}">
                                    <div class="plaid-account-info">
                                        <span class="plaid-account-name">${acct.name}</span>
                                        <span class="plaid-account-mask">****${acct.mask || '----'}</span>
                                        <span class="plaid-account-type">${acct.type}${acct.subtype ? ` - ${acct.subtype}` : ''}</span>
                                    </div>
                                    <div class="plaid-account-balance">
                                        ${acct.balance_current !== null ?
                                            `$${Math.abs(acct.balance_current).toLocaleString('en-US', { minimumFractionDigits: 2 })}` :
                                            '--'}
                                    </div>
                                    <div class="plaid-account-toggle">
                                        <label class="plaid-toggle">
                                            <input type="checkbox" ${acct.sync_enabled ? 'checked' : ''}
                                                   onchange="PlaidLink.updateAccount('${acct.account_id}', { sync_enabled: this.checked })">
                                            <span class="plaid-toggle-slider"></span>
                                        </label>
                                    </div>
                                </div>
                            `).join('')}
                        </div>
                        <div class="plaid-item-footer">
                            <span class="plaid-item-sync-time">
                                Last synced: ${item.last_successful_sync ?
                                    new Date(item.last_successful_sync).toLocaleString() :
                                    'Never'}
                            </span>
                        </div>
                    </div>
                `;
            }

            html += `
                <button class="plaid-add-btn" onclick="PlaidLink.connect()">
                    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                        <path d="M12 5v14M5 12h14"/>
                    </svg>
                    Add Another Bank Account
                </button>
            </div>`;

            wrapper.innerHTML = html;

        } catch (error) {
            wrapper.innerHTML = `
                <div class="plaid-error-state">
                    <p>Failed to load bank accounts</p>
                    <button class="plaid-btn" onclick="PlaidLink.renderAccountsList('${container}')">
                        Retry
                    </button>
                </div>
            `;
        }
    }

    // =========================================================================
    // EXPORT
    // =========================================================================

    window.PlaidLink = {
        connect,
        update,
        getItems,
        getAccounts,
        removeItem,
        sync,
        getStatus,
        updateAccount,
        renderAccountsList,

        // For debugging
        _config: CONFIG,
        _isInitialized: () => isInitialized
    };

})(window);


// =========================================================================
// CSS STYLES (injected)
// =========================================================================

(function() {
    const styles = `
        /* Plaid Link Component Styles */
        .plaid-empty-state {
            text-align: center;
            padding: 40px 20px;
            color: var(--text-secondary, #999);
        }

        .plaid-empty-icon {
            color: var(--accent, #00ff88);
            margin-bottom: 16px;
            opacity: 0.5;
        }

        .plaid-empty-state h3 {
            color: var(--text, #fff);
            margin-bottom: 8px;
            font-size: 18px;
        }

        .plaid-empty-state p {
            margin-bottom: 24px;
            font-size: 14px;
        }

        .plaid-connect-btn {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            background: var(--accent, #00ff88);
            color: #000;
            border: none;
            padding: 12px 24px;
            border-radius: 8px;
            font-weight: 600;
            font-size: 14px;
            cursor: pointer;
            transition: all 0.2s;
        }

        .plaid-connect-btn:hover {
            transform: translateY(-2px);
            box-shadow: 0 4px 12px rgba(0, 255, 136, 0.3);
        }

        .plaid-items-list {
            display: flex;
            flex-direction: column;
            gap: 16px;
        }

        .plaid-item-card {
            background: var(--bg-card, #0e141a);
            border: 1px solid var(--border, #1b2a3a);
            border-radius: 12px;
            overflow: hidden;
        }

        .plaid-item-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 16px;
            border-bottom: 1px solid var(--border, #1b2a3a);
        }

        .plaid-item-info {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .plaid-item-name {
            font-size: 16px;
            font-weight: 600;
            margin: 0;
            color: var(--text, #fff);
        }

        .plaid-item-status {
            font-size: 12px;
            padding: 4px 8px;
            border-radius: 4px;
            font-weight: 500;
        }

        .plaid-item-status.success {
            background: rgba(0, 255, 136, 0.15);
            color: var(--success, #00ff88);
        }

        .plaid-item-status.warning {
            background: rgba(255, 170, 0, 0.15);
            color: var(--warning, #ffaa00);
        }

        .plaid-item-status.error {
            background: rgba(255, 68, 68, 0.15);
            color: var(--error, #ff4444);
        }

        .plaid-item-actions {
            display: flex;
            gap: 8px;
        }

        .plaid-btn {
            display: inline-flex;
            align-items: center;
            gap: 6px;
            padding: 8px 12px;
            border-radius: 6px;
            font-size: 13px;
            font-weight: 500;
            border: 1px solid var(--border, #1b2a3a);
            background: transparent;
            color: var(--text, #fff);
            cursor: pointer;
            transition: all 0.2s;
        }

        .plaid-btn:hover {
            background: var(--bg-elevated, #121a25);
            border-color: var(--accent, #00ff88);
        }

        .plaid-btn-warning {
            background: rgba(255, 170, 0, 0.15);
            border-color: var(--warning, #ffaa00);
            color: var(--warning, #ffaa00);
        }

        .plaid-btn-sync {
            background: rgba(0, 255, 136, 0.1);
            border-color: rgba(0, 255, 136, 0.3);
            color: var(--accent, #00ff88);
        }

        .plaid-btn-remove {
            color: var(--error, #ff4444);
        }

        .plaid-btn-remove:hover {
            background: rgba(255, 68, 68, 0.15);
            border-color: var(--error, #ff4444);
        }

        .plaid-accounts-list {
            padding: 8px 0;
        }

        .plaid-account-row {
            display: flex;
            align-items: center;
            padding: 12px 16px;
            border-bottom: 1px solid var(--border, #1b2a3a);
        }

        .plaid-account-row:last-child {
            border-bottom: none;
        }

        .plaid-account-info {
            flex: 1;
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .plaid-account-name {
            font-weight: 500;
            color: var(--text, #fff);
        }

        .plaid-account-mask {
            color: var(--text-dim, #666);
            font-size: 13px;
        }

        .plaid-account-type {
            color: var(--text-secondary, #999);
            font-size: 12px;
            text-transform: capitalize;
        }

        .plaid-account-balance {
            font-weight: 600;
            color: var(--text, #fff);
            margin-right: 16px;
        }

        /* Toggle Switch */
        .plaid-toggle {
            position: relative;
            display: inline-block;
            width: 44px;
            height: 24px;
        }

        .plaid-toggle input {
            opacity: 0;
            width: 0;
            height: 0;
        }

        .plaid-toggle-slider {
            position: absolute;
            cursor: pointer;
            top: 0;
            left: 0;
            right: 0;
            bottom: 0;
            background: var(--bg-elevated, #121a25);
            border: 1px solid var(--border, #1b2a3a);
            border-radius: 24px;
            transition: 0.3s;
        }

        .plaid-toggle-slider:before {
            position: absolute;
            content: "";
            height: 18px;
            width: 18px;
            left: 2px;
            bottom: 2px;
            background-color: white;
            border-radius: 50%;
            transition: 0.3s;
        }

        .plaid-toggle input:checked + .plaid-toggle-slider {
            background: var(--accent, #00ff88);
            border-color: var(--accent, #00ff88);
        }

        .plaid-toggle input:checked + .plaid-toggle-slider:before {
            transform: translateX(20px);
        }

        .plaid-item-footer {
            padding: 12px 16px;
            background: rgba(0, 0, 0, 0.2);
            font-size: 12px;
            color: var(--text-dim, #666);
        }

        .plaid-add-btn {
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
            width: 100%;
            padding: 16px;
            border: 2px dashed var(--border, #1b2a3a);
            border-radius: 12px;
            background: transparent;
            color: var(--text-secondary, #999);
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s;
        }

        .plaid-add-btn:hover {
            border-color: var(--accent, #00ff88);
            color: var(--accent, #00ff88);
            background: rgba(0, 255, 136, 0.05);
        }

        .plaid-error-state {
            text-align: center;
            padding: 20px;
            color: var(--error, #ff4444);
        }

        .plaid-toast {
            animation: fadeInUp 0.3s ease;
        }

        @keyframes fadeInUp {
            from {
                opacity: 0;
                transform: translate(-50%, 20px);
            }
            to {
                opacity: 1;
                transform: translate(-50%, 0);
            }
        }
    `;

    const styleSheet = document.createElement('style');
    styleSheet.textContent = styles;
    document.head.appendChild(styleSheet);
})();

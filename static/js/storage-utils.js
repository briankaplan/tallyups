/**
 * Secure Storage Utilities for TallyUps
 * Provides validated, sanitized localStorage/sessionStorage access
 */

(function(window) {
    'use strict';

    const StorageUtils = {
        // Keys that are allowed to be stored (whitelist approach)
        ALLOWED_KEYS: [
            'theme',
            'device_id',
            'access_token',
            'refresh_token',
            'lastWeeklySummary',
            'categoryRules',
            'filterPreferences',
            'viewMode',
            'sortPreference',
            'sidebarCollapsed',
            'onboardingComplete'
        ],

        // Keys that should use sessionStorage instead of localStorage
        SESSION_ONLY_KEYS: [
            'access_token',
            'refresh_token',
            'csrf_token'
        ],

        // Maximum storage sizes (prevent storage exhaustion)
        MAX_SIZES: {
            theme: 20,
            device_id: 100,
            access_token: 2000,
            refresh_token: 2000,
            lastWeeklySummary: 10000,
            categoryRules: 50000,
            filterPreferences: 5000,
            viewMode: 20,
            sortPreference: 50,
            sidebarCollapsed: 10,
            onboardingComplete: 10
        },

        /**
         * Sanitize a string value to prevent XSS
         * @param {string} value - Value to sanitize
         * @returns {string} Sanitized value
         */
        sanitize(value) {
            if (typeof value !== 'string') {
                return String(value);
            }
            // Remove any potential script tags or event handlers
            return value
                .replace(/<script\b[^<]*(?:(?!<\/script>)<[^<]*)*<\/script>/gi, '')
                .replace(/on\w+\s*=/gi, '')
                .replace(/javascript:/gi, '')
                .replace(/data:/gi, 'data-blocked:');
        },

        /**
         * Validate a key is allowed
         * @param {string} key - Storage key
         * @returns {boolean} Whether key is allowed
         */
        isAllowedKey(key) {
            return this.ALLOWED_KEYS.includes(key);
        },

        /**
         * Get the appropriate storage for a key
         * @param {string} key - Storage key
         * @returns {Storage} localStorage or sessionStorage
         */
        getStorage(key) {
            return this.SESSION_ONLY_KEYS.includes(key) ? sessionStorage : localStorage;
        },

        /**
         * Safely get an item from storage
         * @param {string} key - Storage key
         * @param {*} defaultValue - Default value if not found
         * @returns {*} The stored value or default
         */
        get(key, defaultValue = null) {
            if (!this.isAllowedKey(key)) {
                console.warn(`[StorageUtils] Blocked access to non-whitelisted key: ${key}`);
                return defaultValue;
            }

            try {
                const storage = this.getStorage(key);
                const value = storage.getItem(`tallyups_${key}`);

                if (value === null) {
                    return defaultValue;
                }

                // Try to parse as JSON
                try {
                    return JSON.parse(value);
                } catch {
                    // Return as string if not valid JSON
                    return this.sanitize(value);
                }
            } catch (e) {
                console.warn(`[StorageUtils] Error reading ${key}:`, e);
                return defaultValue;
            }
        },

        /**
         * Safely set an item in storage
         * @param {string} key - Storage key
         * @param {*} value - Value to store
         * @returns {boolean} Whether the operation succeeded
         */
        set(key, value) {
            if (!this.isAllowedKey(key)) {
                console.warn(`[StorageUtils] Blocked write to non-whitelisted key: ${key}`);
                return false;
            }

            try {
                const storage = this.getStorage(key);
                let stringValue;

                if (typeof value === 'object') {
                    stringValue = JSON.stringify(value);
                } else {
                    stringValue = this.sanitize(String(value));
                }

                // Check size limit
                const maxSize = this.MAX_SIZES[key] || 1000;
                if (stringValue.length > maxSize) {
                    console.warn(`[StorageUtils] Value for ${key} exceeds max size (${stringValue.length} > ${maxSize})`);
                    return false;
                }

                storage.setItem(`tallyups_${key}`, stringValue);
                return true;
            } catch (e) {
                // Handle quota exceeded
                if (e.name === 'QuotaExceededError') {
                    console.warn('[StorageUtils] Storage quota exceeded, clearing old data');
                    this.clearOldData();
                    // Retry once
                    try {
                        const storage = this.getStorage(key);
                        storage.setItem(`tallyups_${key}`, typeof value === 'object' ? JSON.stringify(value) : String(value));
                        return true;
                    } catch {
                        return false;
                    }
                }
                console.warn(`[StorageUtils] Error writing ${key}:`, e);
                return false;
            }
        },

        /**
         * Remove an item from storage
         * @param {string} key - Storage key
         * @returns {boolean} Whether the operation succeeded
         */
        remove(key) {
            if (!this.isAllowedKey(key)) {
                return false;
            }

            try {
                const storage = this.getStorage(key);
                storage.removeItem(`tallyups_${key}`);
                return true;
            } catch (e) {
                console.warn(`[StorageUtils] Error removing ${key}:`, e);
                return false;
            }
        },

        /**
         * Clear all TallyUps storage data
         */
        clearAll() {
            try {
                // Clear from both storages
                [localStorage, sessionStorage].forEach(storage => {
                    const keysToRemove = [];
                    for (let i = 0; i < storage.length; i++) {
                        const key = storage.key(i);
                        if (key && key.startsWith('tallyups_')) {
                            keysToRemove.push(key);
                        }
                    }
                    keysToRemove.forEach(key => storage.removeItem(key));
                });
            } catch (e) {
                console.warn('[StorageUtils] Error clearing storage:', e);
            }
        },

        /**
         * Clear old/unnecessary data to free up space
         */
        clearOldData() {
            // Clear non-essential cached data
            const nonEssential = ['lastWeeklySummary', 'categoryRules'];
            nonEssential.forEach(key => this.remove(key));
        },

        /**
         * Get theme preference
         * @returns {string} 'dark' or 'light'
         */
        getTheme() {
            const stored = this.get('theme');
            if (stored === 'dark' || stored === 'light') {
                return stored;
            }
            // Default to system preference
            return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
        },

        /**
         * Set theme preference
         * @param {string} theme - 'dark' or 'light'
         */
        setTheme(theme) {
            if (theme !== 'dark' && theme !== 'light') {
                return false;
            }
            return this.set('theme', theme);
        },

        /**
         * Get or create device ID
         * @returns {string} Device ID
         */
        getDeviceId() {
            let deviceId = this.get('device_id');
            if (!deviceId) {
                deviceId = 'web-' + crypto.randomUUID();
                this.set('device_id', deviceId);
            }
            return deviceId;
        },

        /**
         * Migrate old storage keys to new format
         */
        migrateOldKeys() {
            const oldKeys = ['theme', 'device_id', 'access_token', 'refresh_token'];
            oldKeys.forEach(key => {
                try {
                    const oldValue = localStorage.getItem(key);
                    if (oldValue && !localStorage.getItem(`tallyups_${key}`)) {
                        this.set(key, oldValue);
                        localStorage.removeItem(key);
                    }
                } catch (e) {
                    // Ignore migration errors
                }
            });
        }
    };

    // Auto-migrate on load
    StorageUtils.migrateOldKeys();

    // Export
    window.StorageUtils = StorageUtils;

})(window);

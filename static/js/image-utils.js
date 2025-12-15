/**
 * Image Utilities - Unified Receipt Image Handling
 * =================================================
 * Single source of truth for all receipt image URL resolution and fallback handling.
 *
 * Usage:
 *   const url = ImageUtils.getReceiptUrl(transaction);
 *   const thumbUrl = ImageUtils.getThumbnailUrl(transaction);
 *   ImageUtils.loadWithFallback(imgElement, transaction);
 */

const ImageUtils = {
    // R2 public URL - must match r2_config.py
    R2_PUBLIC_URL: 'https://pub-35015e19c4b442b9af31f1dfd941f47f.r2.dev',

    // Known wrong bucket URLs to fix
    WRONG_BUCKETS: {
        'pub-946b7d51aa2c4a0fb92c1ba15bf5c520.r2.dev': 'second-brain-receipts',
        'pub-f0fa143240d4452e836320be0bac6138.r2.dev': 'tallyups-receipts',
    },

    /**
     * Get the best available receipt URL from a transaction/receipt object.
     * Handles all field name variations and URL fixing.
     * @param {Object} item - Transaction or receipt object
     * @returns {string|null} - Receipt URL or null if none found
     */
    getReceiptUrl(item) {
        if (!item) return null;

        // Priority order for receipt URLs
        const urls = [
            item.r2_url,
            item['R2 URL'],
            item.receipt_url,
            item.receipt_image_url,
            item['Receipt URL'],
        ].filter(Boolean);

        // Return first valid URL (after fixing if needed)
        for (const url of urls) {
            if (url && url.trim()) {
                return this.fixUrl(url);
            }
        }

        // Fall back to local file path
        const receiptFile = item['Receipt File'] || item.receipt_file || item.original_filename;
        if (receiptFile) {
            return `/receipts/${receiptFile}`;
        }

        return null;
    },

    /**
     * Get thumbnail URL (prefer thumbnail, fall back to full image).
     * @param {Object} item - Transaction or receipt object
     * @returns {string|null} - Thumbnail URL or full image URL
     */
    getThumbnailUrl(item) {
        if (!item) return null;

        // Prefer explicit thumbnail
        if (item.thumbnail_url) {
            return this.fixUrl(item.thumbnail_url);
        }

        // Fall back to main receipt URL
        return this.getReceiptUrl(item);
    },

    /**
     * Fix URLs that point to wrong R2 buckets.
     * @param {string} url - URL to fix
     * @returns {string} - Fixed URL
     */
    fixUrl(url) {
        if (!url) return url;

        for (const [wrongPublic, wrongBucket] of Object.entries(this.WRONG_BUCKETS)) {
            if (url.includes(wrongPublic)) {
                const key = url.split(wrongPublic)[1];
                return `${this.R2_PUBLIC_URL}${key}`;
            }
        }

        return url;
    },

    /**
     * Check if an item has a receipt attached.
     * @param {Object} item - Transaction or receipt object
     * @returns {boolean}
     */
    hasReceipt(item) {
        return !!(
            item?.r2_url ||
            item?.['R2 URL'] ||
            item?.receipt_url ||
            item?.receipt_image_url ||
            item?.['Receipt URL'] ||
            item?.['Receipt File'] ||
            item?.receipt_file ||
            item?.original_filename
        );
    },

    /**
     * Load image with automatic fallback handling.
     * @param {HTMLImageElement} img - Image element to load
     * @param {Object} item - Transaction or receipt object
     * @param {Object} options - Options {onLoad, onError, onFallback}
     */
    loadWithFallback(img, item, options = {}) {
        const { onLoad, onError, onFallback } = options;

        // Build fallback chain
        const fallbacks = this.buildFallbackChain(item);
        let currentIndex = 0;

        const tryNextFallback = () => {
            if (currentIndex >= fallbacks.length) {
                // No more fallbacks
                if (onError) onError();
                return;
            }

            const url = fallbacks[currentIndex];
            currentIndex++;

            if (currentIndex > 1 && onFallback) {
                onFallback(url);
            }

            img.src = url;
        };

        const handleLoad = () => {
            img.classList.add('loaded');
            if (onLoad) onLoad();
        };

        const handleError = () => {
            console.warn(`Image load failed: ${img.src}, trying fallback...`);
            tryNextFallback();
        };

        // Remove old listeners
        img.removeEventListener('load', handleLoad);
        img.removeEventListener('error', handleError);

        // Add new listeners
        img.addEventListener('load', handleLoad, { once: true });
        img.addEventListener('error', handleError, { once: true });

        // Start loading
        tryNextFallback();
    },

    /**
     * Build a chain of fallback URLs to try.
     * @param {Object} item - Transaction or receipt object
     * @returns {string[]} - Array of URLs to try in order
     */
    buildFallbackChain(item) {
        if (!item) return [];

        const urls = new Set();

        // Add all possible URLs in priority order
        const candidates = [
            item.r2_url,
            item['R2 URL'],
            item.receipt_url,
            item.receipt_image_url,
            item['Receipt URL'],
        ];

        for (const url of candidates) {
            if (url && url.trim()) {
                // Add fixed URL
                const fixed = this.fixUrl(url);
                urls.add(fixed);

                // If URL was from wrong bucket, also try original as fallback
                if (fixed !== url) {
                    urls.add(url);
                }
            }
        }

        // Add local file fallback
        const receiptFile = item['Receipt File'] || item.receipt_file || item.original_filename;
        if (receiptFile) {
            urls.add(`/receipts/${receiptFile}`);
        }

        // Add proxy fallback for R2 URLs
        for (const url of [...urls]) {
            if (url.includes('r2.dev')) {
                const key = url.split('.r2.dev/')[1];
                if (key) {
                    urls.add(`/api/receipt-proxy/${key}`);
                }
            }
        }

        return [...urls];
    },

    /**
     * Create an image element with built-in fallback handling.
     * @param {Object} item - Transaction or receipt object
     * @param {Object} options - Options {className, alt, lazy}
     * @returns {HTMLImageElement}
     */
    createImage(item, options = {}) {
        const { className = '', alt = 'Receipt', lazy = true } = options;

        const img = document.createElement('img');
        img.alt = alt;
        if (className) img.className = className;
        if (lazy) img.loading = 'lazy';

        this.loadWithFallback(img, item);

        return img;
    },

    /**
     * Get placeholder image for missing receipts.
     * @returns {string} - Data URL for placeholder
     */
    getPlaceholder() {
        return 'data:image/svg+xml;base64,PHN2ZyB4bWxucz0iaHR0cDovL3d3dy53My5vcmcvMjAwMC9zdmciIHdpZHRoPSIyMDAiIGhlaWdodD0iMjAwIiB2aWV3Qm94PSIwIDAgMjAwIDIwMCI+PHJlY3Qgd2lkdGg9IjIwMCIgaGVpZ2h0PSIyMDAiIGZpbGw9IiMyMjIiLz48dGV4dCB4PSIxMDAiIHk9IjEwNSIgZm9udC1mYW1pbHk9InNhbnMtc2VyaWYiIGZvbnQtc2l6ZT0iNDAiIGZpbGw9IiM1NTUiIHRleHQtYW5jaG9yPSJtaWRkbGUiPvCfjqY8L3RleHQ+PC9zdmc+';
    },

    /**
     * Preload an image URL.
     * @param {string} url - URL to preload
     * @returns {Promise<void>}
     */
    preload(url) {
        return new Promise((resolve, reject) => {
            const img = new Image();
            img.onload = resolve;
            img.onerror = reject;
            img.src = url;
        });
    },

    /**
     * Batch preload images for a list of items.
     * @param {Object[]} items - Array of transaction/receipt objects
     * @param {number} limit - Max number to preload (default 10)
     */
    async preloadBatch(items, limit = 10) {
        const urls = items
            .slice(0, limit)
            .map(item => this.getReceiptUrl(item))
            .filter(Boolean);

        await Promise.allSettled(urls.map(url => this.preload(url)));
    }
};

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = ImageUtils;
}

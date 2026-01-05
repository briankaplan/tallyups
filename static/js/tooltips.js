/**
 * TallyUps Help Tooltips
 * ======================
 * Accessible, mobile-friendly help tooltips for users who need guidance.
 * Designed with simple language for non-tech-savvy users.
 *
 * Usage:
 *   1. Add data-tooltip="your help text" to any element
 *   2. Optionally add data-tooltip-position="top|bottom|left|right"
 *   3. Call TallyTooltips.init() on page load
 *
 * Or use the helper icon:
 *   <span class="help-tooltip" data-tooltip="Your explanation here">?</span>
 */

const TallyTooltips = (function() {
    'use strict';

    // Configuration
    const CONFIG = {
        showDelay: 200,          // Delay before showing (ms)
        hideDelay: 100,          // Delay before hiding (ms)
        touchDuration: 3000,     // How long tooltip stays visible on touch (ms)
        maxWidth: 280,           // Maximum tooltip width (px)
        offset: 10,              // Distance from trigger element (px)
        mobileBreakpoint: 768    // Screen width below which we use mobile behavior
    };

    // State
    let activeTooltip = null;
    let showTimeout = null;
    let hideTimeout = null;
    let touchTimeout = null;

    // Predefined help content for common features
    const HELP_CONTENT = {
        // Login/Auth
        'google-signin': 'Sign in using your Google account (like Gmail). This is quick and secure - you don\'t need to create a new password.',
        'apple-signin': 'Sign in with your Apple ID. Great if you use an iPhone or Mac.',
        'password-requirements': 'Your password should be at least 8 characters long and include a number. This keeps your account safe.',
        'email-signin': 'Enter the email address you used when creating your account.',

        // Dashboard
        'matched-receipts': 'These are receipts that have been linked to your bank transactions. The amounts match up correctly.',
        'unmatched-receipts': 'These are bank transactions that don\'t have a receipt attached yet. You may need to find or scan the missing receipt.',
        'needs-review': 'These items need your attention. The receipt and transaction might not match perfectly.',
        'verified': 'These have been checked and everything looks correct. No action needed.',
        'mismatch': 'The receipt amount doesn\'t match the bank transaction. This might be a tip, tax difference, or wrong receipt.',
        'business-expenses': 'Money spent for your business. These can often be deducted from your taxes.',
        'personal-expenses': 'Personal spending that is not for business purposes.',
        'secondary-expenses': 'Expenses for a secondary business or project you\'re tracking separately.',

        // Filters
        'filter-all': 'Show all your transactions, including those with and without receipts.',
        'filter-needs-review': 'Show only items that need your attention or have issues.',
        'filter-verified': 'Show only items that have been reviewed and confirmed as correct.',
        'filter-mismatch': 'Show items where the receipt amount doesn\'t match what your bank shows.',
        'filter-date': 'Filter by when the transaction happened. Useful for finding specific purchases.',
        'filter-amount': 'Filter by how much was spent. Great for finding large purchases.',
        'filter-merchant': 'Filter by store or company name. Type part of the name to search.',
        'filter-business-type': 'Filter by expense category: Business, Personal, or Secondary.',

        // Settings
        'setting-notifications': 'Get alerts when new receipts arrive or when something needs your attention.',
        'setting-auto-match': 'Automatically link receipts to bank transactions when the amounts match.',
        'setting-dark-mode': 'Use a darker color scheme. Easier on the eyes in low light.',
        'setting-currency': 'Choose how money amounts are displayed (e.g., $, or other currencies).',
        'setting-timezone': 'Set your local time zone so dates appear correctly.',
        'setting-export': 'Download your expense data as a file you can use in spreadsheets or accounting software.',
        'setting-connect-bank': 'Link your bank account to automatically import transactions. This is secure and read-only.',
        'setting-email-import': 'Automatically find receipts from your email and add them here.',

        // Actions
        'action-scan': 'Take a photo of a receipt to add it to your records.',
        'action-upload': 'Choose a picture or PDF of a receipt from your device.',
        'action-delete': 'Remove this item permanently. This cannot be undone.',
        'action-edit': 'Make changes to this item\'s details.',
        'action-approve': 'Mark this item as reviewed and correct.',
        'action-reject': 'Mark this item as having a problem that needs fixing.',

        // Status indicators
        'status-pending': 'This item is waiting to be reviewed.',
        'status-processing': 'We\'re working on this. It should be ready soon.',
        'status-error': 'Something went wrong. Try again or contact support if it keeps happening.'
    };

    /**
     * Create the tooltip container element
     */
    function createTooltipElement() {
        const tooltip = document.createElement('div');
        tooltip.className = 'tallyups-tooltip';
        tooltip.setAttribute('role', 'tooltip');
        tooltip.setAttribute('aria-hidden', 'true');
        tooltip.innerHTML = `
            <div class="tallyups-tooltip__content"></div>
            <button class="tallyups-tooltip__close" aria-label="Close help tip">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                    <line x1="18" y1="6" x2="6" y2="18"></line>
                    <line x1="6" y1="6" x2="18" y2="18"></line>
                </svg>
            </button>
        `;
        document.body.appendChild(tooltip);

        // Close button handler
        tooltip.querySelector('.tallyups-tooltip__close').addEventListener('click', (e) => {
            e.stopPropagation();
            hideTooltip();
        });

        return tooltip;
    }

    /**
     * Get or create the tooltip element
     */
    function getTooltipElement() {
        let tooltip = document.querySelector('.tallyups-tooltip');
        if (!tooltip) {
            tooltip = createTooltipElement();
        }
        return tooltip;
    }

    /**
     * Get the tooltip content for an element
     */
    function getTooltipContent(element) {
        // First check for data-tooltip attribute
        let content = element.getAttribute('data-tooltip');

        // If not found, check for data-help-key to use predefined content
        if (!content) {
            const helpKey = element.getAttribute('data-help-key');
            if (helpKey && HELP_CONTENT[helpKey]) {
                content = HELP_CONTENT[helpKey];
            }
        }

        return content;
    }

    /**
     * Position the tooltip relative to the trigger element
     */
    function positionTooltip(tooltip, trigger) {
        const position = trigger.getAttribute('data-tooltip-position') || 'top';
        const triggerRect = trigger.getBoundingClientRect();
        const tooltipRect = tooltip.getBoundingClientRect();
        const scrollTop = window.pageYOffset || document.documentElement.scrollTop;
        const scrollLeft = window.pageXOffset || document.documentElement.scrollLeft;

        let top, left;
        const offset = CONFIG.offset;

        // Calculate position based on preferred direction
        switch (position) {
            case 'bottom':
                top = triggerRect.bottom + scrollTop + offset;
                left = triggerRect.left + scrollLeft + (triggerRect.width / 2) - (tooltipRect.width / 2);
                break;
            case 'left':
                top = triggerRect.top + scrollTop + (triggerRect.height / 2) - (tooltipRect.height / 2);
                left = triggerRect.left + scrollLeft - tooltipRect.width - offset;
                break;
            case 'right':
                top = triggerRect.top + scrollTop + (triggerRect.height / 2) - (tooltipRect.height / 2);
                left = triggerRect.right + scrollLeft + offset;
                break;
            case 'top':
            default:
                top = triggerRect.top + scrollTop - tooltipRect.height - offset;
                left = triggerRect.left + scrollLeft + (triggerRect.width / 2) - (tooltipRect.width / 2);
                break;
        }

        // Keep tooltip within viewport
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Horizontal bounds
        if (left < 10) {
            left = 10;
        } else if (left + tooltipRect.width > viewportWidth - 10) {
            left = viewportWidth - tooltipRect.width - 10;
        }

        // Vertical bounds - flip if needed
        if (top < scrollTop + 10) {
            // Flip to bottom
            top = triggerRect.bottom + scrollTop + offset;
            tooltip.setAttribute('data-actual-position', 'bottom');
        } else if (top + tooltipRect.height > scrollTop + viewportHeight - 10) {
            // Flip to top
            top = triggerRect.top + scrollTop - tooltipRect.height - offset;
            tooltip.setAttribute('data-actual-position', 'top');
        } else {
            tooltip.setAttribute('data-actual-position', position);
        }

        tooltip.style.top = `${top}px`;
        tooltip.style.left = `${left}px`;
    }

    /**
     * Show tooltip for a trigger element
     */
    function showTooltip(trigger) {
        clearTimeout(hideTimeout);

        const content = getTooltipContent(trigger);
        if (!content) return;

        const tooltip = getTooltipElement();
        const contentEl = tooltip.querySelector('.tallyups-tooltip__content');

        contentEl.textContent = content;
        tooltip.classList.add('tallyups-tooltip--visible');
        tooltip.setAttribute('aria-hidden', 'false');

        // Set ARIA relationship
        const tooltipId = 'tallyups-tooltip-' + Date.now();
        tooltip.id = tooltipId;
        trigger.setAttribute('aria-describedby', tooltipId);

        // Position after making visible (so we can measure)
        requestAnimationFrame(() => {
            positionTooltip(tooltip, trigger);
        });

        activeTooltip = { tooltip, trigger };
    }

    /**
     * Hide the currently visible tooltip
     */
    function hideTooltip() {
        clearTimeout(showTimeout);
        clearTimeout(touchTimeout);

        const tooltip = document.querySelector('.tallyups-tooltip');
        if (tooltip) {
            tooltip.classList.remove('tallyups-tooltip--visible');
            tooltip.setAttribute('aria-hidden', 'true');
        }

        if (activeTooltip && activeTooltip.trigger) {
            activeTooltip.trigger.removeAttribute('aria-describedby');
        }

        activeTooltip = null;
    }

    /**
     * Handle mouse enter on trigger elements
     */
    function handleMouseEnter(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');
        if (!trigger) return;

        // Don't use hover on mobile
        if (window.innerWidth < CONFIG.mobileBreakpoint) return;

        clearTimeout(hideTimeout);
        showTimeout = setTimeout(() => {
            showTooltip(trigger);
        }, CONFIG.showDelay);
    }

    /**
     * Handle mouse leave on trigger elements
     */
    function handleMouseLeave(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');
        if (!trigger) return;

        clearTimeout(showTimeout);
        hideTimeout = setTimeout(() => {
            hideTooltip();
        }, CONFIG.hideDelay);
    }

    /**
     * Handle touch/click on trigger elements (mobile behavior)
     */
    function handleTouch(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');

        // If clicking on the tooltip close button, let it handle it
        if (e.target.closest('.tallyups-tooltip__close')) {
            return;
        }

        // If clicking outside tooltip and trigger, hide it
        if (!trigger && !e.target.closest('.tallyups-tooltip')) {
            hideTooltip();
            return;
        }

        if (!trigger) return;

        // Prevent link navigation for help icons
        if (trigger.classList.contains('help-tooltip')) {
            e.preventDefault();
            e.stopPropagation();
        }

        // Toggle tooltip on mobile
        if (activeTooltip && activeTooltip.trigger === trigger) {
            hideTooltip();
        } else {
            hideTooltip();
            showTooltip(trigger);

            // Auto-hide after duration on touch
            touchTimeout = setTimeout(() => {
                hideTooltip();
            }, CONFIG.touchDuration);
        }
    }

    /**
     * Handle keyboard navigation
     */
    function handleKeyDown(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');

        if (trigger) {
            // Show on Enter or Space
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                if (activeTooltip && activeTooltip.trigger === trigger) {
                    hideTooltip();
                } else {
                    showTooltip(trigger);
                }
            }
        }

        // Hide on Escape
        if (e.key === 'Escape' && activeTooltip) {
            hideTooltip();
            if (activeTooltip && activeTooltip.trigger) {
                activeTooltip.trigger.focus();
            }
        }
    }

    /**
     * Handle focus events for keyboard users
     */
    function handleFocus(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');
        if (trigger) {
            showTooltip(trigger);
        }
    }

    function handleBlur(e) {
        const trigger = e.target.closest('[data-tooltip], [data-help-key], .help-tooltip');
        if (trigger) {
            // Delay to allow click on tooltip close button
            setTimeout(() => {
                if (!document.activeElement?.closest('.tallyups-tooltip')) {
                    hideTooltip();
                }
            }, 100);
        }
    }

    /**
     * Create a help icon element
     * @param {string} helpText - The help text to display
     * @param {string} position - Tooltip position (top, bottom, left, right)
     * @returns {HTMLElement} The help icon element
     */
    function createHelpIcon(helpText, position = 'top') {
        const icon = document.createElement('button');
        icon.type = 'button';
        icon.className = 'help-tooltip';
        icon.setAttribute('data-tooltip', helpText);
        icon.setAttribute('data-tooltip-position', position);
        icon.setAttribute('aria-label', 'Help: ' + helpText.substring(0, 50) + '...');
        icon.setAttribute('tabindex', '0');
        icon.innerHTML = '?';
        return icon;
    }

    /**
     * Add help icon next to an element
     * @param {string|Element} target - Selector or element to add help icon to
     * @param {string} helpKeyOrText - Either a key from HELP_CONTENT or custom text
     * @param {Object} options - Additional options
     */
    function addHelpTo(target, helpKeyOrText, options = {}) {
        const element = typeof target === 'string' ? document.querySelector(target) : target;
        if (!element) return null;

        const helpText = HELP_CONTENT[helpKeyOrText] || helpKeyOrText;
        const position = options.position || 'top';

        const icon = createHelpIcon(helpText, position);

        if (options.inline) {
            element.appendChild(icon);
        } else {
            element.parentNode.insertBefore(icon, element.nextSibling);
        }

        return icon;
    }

    /**
     * Initialize the tooltip system
     */
    function init() {
        // Create tooltip container
        getTooltipElement();

        // Add event listeners using delegation for better performance
        document.addEventListener('mouseenter', handleMouseEnter, true);
        document.addEventListener('mouseleave', handleMouseLeave, true);
        document.addEventListener('click', handleTouch);
        document.addEventListener('touchstart', handleTouch, { passive: true });
        document.addEventListener('keydown', handleKeyDown);
        document.addEventListener('focusin', handleFocus);
        document.addEventListener('focusout', handleBlur);

        // Handle window resize - reposition if visible
        window.addEventListener('resize', () => {
            if (activeTooltip) {
                positionTooltip(activeTooltip.tooltip, activeTooltip.trigger);
            }
        });

        // Handle scroll - reposition if visible
        window.addEventListener('scroll', () => {
            if (activeTooltip) {
                positionTooltip(activeTooltip.tooltip, activeTooltip.trigger);
            }
        }, { passive: true });

        console.log('TallyUps Tooltips initialized');
    }

    /**
     * Add tooltips to common page elements
     * Call this after DOM is ready for a specific page type
     */
    function enhancePage(pageType) {
        switch (pageType) {
            case 'login':
                enhanceLoginPage();
                break;
            case 'dashboard':
                enhanceDashboardPage();
                break;
            case 'settings':
                enhanceSettingsPage();
                break;
            case 'library':
                enhanceLibraryPage();
                break;
        }
    }

    function enhanceLoginPage() {
        // Add help to social auth buttons
        const googleBtn = document.querySelector('.btn-google');
        const appleBtn = document.querySelector('.btn-apple');

        if (googleBtn && !googleBtn.hasAttribute('data-tooltip')) {
            googleBtn.setAttribute('data-tooltip', HELP_CONTENT['google-signin']);
            googleBtn.setAttribute('data-tooltip-position', 'bottom');
        }

        if (appleBtn && !appleBtn.hasAttribute('data-tooltip')) {
            appleBtn.setAttribute('data-tooltip', HELP_CONTENT['apple-signin']);
            appleBtn.setAttribute('data-tooltip-position', 'bottom');
        }

        // Add help to password field
        const passwordLabel = document.querySelector('label[for="signup-password"]');
        if (passwordLabel && !passwordLabel.querySelector('.help-tooltip')) {
            addHelpTo(passwordLabel, 'password-requirements', { inline: true });
        }
    }

    function enhanceDashboardPage() {
        // Add help to stat cards
        const statCards = document.querySelectorAll('.stat-card');
        statCards.forEach(card => {
            if (card.classList.contains('business') && !card.hasAttribute('data-tooltip')) {
                card.setAttribute('data-tooltip', HELP_CONTENT['business-expenses']);
            } else if (card.classList.contains('personal') && !card.hasAttribute('data-tooltip')) {
                card.setAttribute('data-tooltip', HELP_CONTENT['personal-expenses']);
            } else if (card.classList.contains('sec') && !card.hasAttribute('data-tooltip')) {
                card.setAttribute('data-tooltip', HELP_CONTENT['secondary-expenses']);
            }
        });

        // Add help to filter chips
        const filterChips = document.querySelectorAll('.filter-chip');
        filterChips.forEach(chip => {
            const filter = chip.getAttribute('data-filter');
            const helpKey = 'filter-' + filter;
            if (HELP_CONTENT[helpKey] && !chip.hasAttribute('data-tooltip')) {
                chip.setAttribute('data-tooltip', HELP_CONTENT[helpKey]);
            }
        });

        // Add help to status badges
        document.querySelectorAll('.receipt-status-badge').forEach(badge => {
            if (badge.classList.contains('verified') && !badge.hasAttribute('data-tooltip')) {
                badge.setAttribute('data-tooltip', HELP_CONTENT['verified']);
            } else if (badge.classList.contains('pending') && !badge.hasAttribute('data-tooltip')) {
                badge.setAttribute('data-tooltip', HELP_CONTENT['status-pending']);
            } else if (badge.classList.contains('mismatch') && !badge.hasAttribute('data-tooltip')) {
                badge.setAttribute('data-tooltip', HELP_CONTENT['mismatch']);
            }
        });
    }

    function enhanceSettingsPage() {
        // Add help to common settings elements
        const settingLabels = {
            'notifications': 'setting-notifications',
            'auto-match': 'setting-auto-match',
            'dark-mode': 'setting-dark-mode',
            'currency': 'setting-currency',
            'timezone': 'setting-timezone',
            'export': 'setting-export',
            'bank': 'setting-connect-bank',
            'email': 'setting-email-import'
        };

        Object.entries(settingLabels).forEach(([selector, helpKey]) => {
            const element = document.querySelector(`[data-setting="${selector}"], #setting-${selector}, .setting-${selector}`);
            if (element && HELP_CONTENT[helpKey]) {
                const label = element.querySelector('label') || element;
                if (!label.querySelector('.help-tooltip')) {
                    addHelpTo(label, helpKey, { inline: true });
                }
            }
        });
    }

    function enhanceLibraryPage() {
        // Add help to filter elements
        const filterBar = document.querySelector('.filters-bar, .filter-container');
        if (filterBar) {
            const filterChips = filterBar.querySelectorAll('.filter-chip, .filter-button');
            filterChips.forEach(chip => {
                const filter = chip.getAttribute('data-filter') || chip.textContent.toLowerCase().trim();
                const helpKey = 'filter-' + filter.replace(/\s+/g, '-');
                if (HELP_CONTENT[helpKey] && !chip.hasAttribute('data-tooltip')) {
                    chip.setAttribute('data-tooltip', HELP_CONTENT[helpKey]);
                }
            });
        }
    }

    // Public API
    return {
        init,
        show: showTooltip,
        hide: hideTooltip,
        addHelpTo,
        createHelpIcon,
        enhancePage,
        HELP_CONTENT,
        config: CONFIG
    };
})();

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', TallyTooltips.init);
} else {
    TallyTooltips.init();
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = TallyTooltips;
}

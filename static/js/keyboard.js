/**
 * Keyboard Shortcut Handler
 * =========================
 * Ultra-fast, keyboard-first transaction review interface.
 * All actions available without touching the mouse.
 */

class KeyboardHandler {
    constructor(reviewInterface) {
        this.ui = reviewInterface;
        this.enabled = true;
        this.modalOpen = false;
        this.searchFocused = false;
        this.helpVisible = false;

        // Shortcut definitions with categories
        this.shortcuts = {
            navigation: {
                'ArrowUp': { action: 'navigateUp', desc: 'Previous transaction', key: '↑' },
                'ArrowDown': { action: 'navigateDown', desc: 'Next transaction', key: '↓' },
                'k': { action: 'navigateUp', desc: 'Previous transaction (vim)', key: 'k' },
                'j': { action: 'navigateDown', desc: 'Next transaction (vim)', key: 'j' },
                'Enter': { action: 'openPreview', desc: 'Open receipt preview', key: '↵' },
                'Escape': { action: 'closeAll', desc: 'Close preview/Clear selection', key: 'Esc' },
                'Home': { action: 'goToFirst', desc: 'Go to first transaction', key: 'Home' },
                'End': { action: 'goToLast', desc: 'Go to last transaction', key: 'End' },
                'PageUp': { action: 'pageUp', desc: 'Page up (10 rows)', key: 'PgUp' },
                'PageDown': { action: 'pageDown', desc: 'Page down (10 rows)', key: 'PgDn' },
            },
            quickActions: {
                'a': { action: 'approve', desc: 'Approve (mark as reviewed)', key: 'a' },
                'r': { action: 'reject', desc: 'Reject / Flag for review', key: 'r' },
                'g': { action: 'markGood', desc: 'Mark as Good', key: 'g' },
                'b': { action: 'markBad', desc: 'Mark as Bad', key: 'b' },
                'x': { action: 'detachReceipt', desc: 'Detach receipt', key: 'x' },
                'v': { action: 'markVerified', desc: 'Mark verified', key: 'v' },
            },
            businessType: {
                'd': { action: 'setBusiness', desc: 'Mark as Business', key: 'd' },
                'm': { action: 'setMCR', desc: 'Mark as Secondary', key: 'm' },
                'p': { action: 'setPersonal', desc: 'Mark as Personal', key: 'p' },
                'e': { action: 'setEMco', desc: 'Mark as EM.co', key: 'e' },
            },
            ai: {
                'A': { action: 'aiMatch', desc: 'AI Match receipt', key: 'Shift+A', shift: true },
                'J': { action: 'aiNote', desc: 'Generate AI note', key: 'Shift+J', shift: true },
                'I': { action: 'aiCategorize', desc: 'AI Categorize', key: 'Shift+I', shift: true },
            },
            bulk: {
                'Shift+ArrowUp': { action: 'extendSelectionUp', desc: 'Extend selection up', key: 'Shift+↑', shift: true },
                'Shift+ArrowDown': { action: 'extendSelectionDown', desc: 'Extend selection down', key: 'Shift+↓', shift: true },
            },
            search: {
                '/': { action: 'focusSearch', desc: 'Focus search', key: '/' },
                'f': { action: 'openFilter', desc: 'Open filter panel', key: 'f' },
                '1': { action: 'filterBusiness', desc: 'Filter: Business', key: '1' },
                '2': { action: 'filterMCR', desc: 'Filter: MCR', key: '2' },
                '3': { action: 'filterPersonal', desc: 'Filter: Personal', key: '3' },
                '4': { action: 'filterUnassigned', desc: 'Filter: Unassigned', key: '4' },
                'u': { action: 'filterUnmatched', desc: 'Show unmatched only', key: 'u' },
                'n': { action: 'filterNeedsReview', desc: 'Show needs-review only', key: 'n' },
            },
            image: {
                'R': { action: 'rotateImage', desc: 'Rotate image', key: 'Shift+R', shift: true },
                '=': { action: 'zoomIn', desc: 'Zoom in', key: '+' },
                '-': { action: 'zoomOut', desc: 'Zoom out', key: '-' },
                '0': { action: 'resetZoom', desc: 'Reset zoom', key: '0' },
            },
            system: {
                '?': { action: 'showHelp', desc: 'Show keyboard shortcuts', key: '?' },
                'q': { action: 'quickView', desc: 'Open quick viewer', key: 'q' },
            }
        };

        // Ctrl/Cmd shortcuts
        this.ctrlShortcuts = {
            'a': { action: 'selectAll', desc: 'Select all visible', key: 'Ctrl+A' },
            'd': { action: 'selectSameMerchant', desc: 'Select same merchant', key: 'Ctrl+D' },
            'z': { action: 'undo', desc: 'Undo last change', key: 'Ctrl+Z' },
            's': { action: 'save', desc: 'Save (auto-saves)', key: 'Ctrl+S' },
            'e': { action: 'export', desc: 'Export selected', key: 'Ctrl+E' },
        };

        // Ctrl+Shift shortcuts
        this.ctrlShiftShortcuts = {
            'a': { action: 'applyToAll', desc: 'Apply action to all selected', key: 'Ctrl+Shift+A' },
        };

        this.init();
    }

    init() {
        document.addEventListener('keydown', this.handleKeyDown.bind(this));
        document.addEventListener('keyup', this.handleKeyUp.bind(this));

        // Track focus state
        document.addEventListener('focusin', (e) => {
            this.searchFocused = e.target.matches('input[type="text"], input[type="search"], textarea');
        });
        document.addEventListener('focusout', () => {
            this.searchFocused = false;
        });
    }

    handleKeyDown(e) {
        // Skip if disabled or in input field (except for specific shortcuts)
        if (!this.enabled) return;

        const key = e.key;
        const ctrl = e.ctrlKey || e.metaKey;
        const shift = e.shiftKey;
        const alt = e.altKey;

        // Allow Escape everywhere
        if (key === 'Escape') {
            e.preventDefault();
            this.execute('closeAll');
            return;
        }

        // Allow / to focus search from anywhere
        if (key === '/' && !this.searchFocused && !ctrl) {
            e.preventDefault();
            this.execute('focusSearch');
            return;
        }

        // Skip other shortcuts if focused on input
        if (this.searchFocused) {
            // Allow Enter to submit search
            if (key === 'Enter') {
                e.target.blur();
            }
            return;
        }

        // Ctrl+Shift shortcuts
        if (ctrl && shift) {
            const shortcut = this.ctrlShiftShortcuts[key.toLowerCase()];
            if (shortcut) {
                e.preventDefault();
                this.execute(shortcut.action);
                return;
            }
        }

        // Ctrl shortcuts
        if (ctrl && !shift) {
            const shortcut = this.ctrlShortcuts[key.toLowerCase()];
            if (shortcut) {
                e.preventDefault();
                this.execute(shortcut.action);
                return;
            }
        }

        // Shift+Arrow for selection
        if (shift && (key === 'ArrowUp' || key === 'ArrowDown')) {
            e.preventDefault();
            this.execute(key === 'ArrowUp' ? 'extendSelectionUp' : 'extendSelectionDown');
            return;
        }

        // Regular shortcuts
        if (!ctrl && !alt) {
            // Check all categories for matching shortcut
            for (const category of Object.values(this.shortcuts)) {
                const shortcut = category[key];
                if (shortcut) {
                    // Check shift requirement
                    if (shortcut.shift && !shift) continue;
                    if (!shortcut.shift && shift) continue;

                    e.preventDefault();
                    this.execute(shortcut.action);
                    return;
                }
            }
        }
    }

    handleKeyUp(e) {
        // Could be used for hold-to-preview type features
    }

    execute(action) {
        if (!this.ui) return;

        const startTime = performance.now();

        // Map actions to UI methods
        const actions = {
            // Navigation
            navigateUp: () => this.ui.navigate(-1),
            navigateDown: () => this.ui.navigate(1),
            goToFirst: () => this.ui.navigateToIndex(0),
            goToLast: () => this.ui.navigateToIndex(-1),
            pageUp: () => this.ui.navigate(-10),
            pageDown: () => this.ui.navigate(10),
            openPreview: () => this.ui.togglePreview(true),
            closeAll: () => this.ui.closeAll(),

            // Quick actions
            approve: () => this.ui.setReviewStatus('approved'),
            reject: () => this.ui.setReviewStatus('flagged'),
            markGood: () => this.ui.setReviewStatus('good'),
            markBad: () => this.ui.setReviewStatus('bad'),
            markVerified: () => this.ui.setValidationStatus('verified'),
            detachReceipt: () => this.ui.detachReceipt(),

            // Business type
            setBusiness: () => this.ui.setBusinessType('Business'),
            setMCR: () => this.ui.setBusinessType('Secondary'),
            setPersonal: () => this.ui.setPersonal(),
            setEMco: () => this.ui.setBusinessType('EM.co'),

            // AI
            aiMatch: () => this.ui.aiMatch(),
            aiNote: () => this.ui.generateAINote(),
            aiCategorize: () => this.ui.aiCategorize(),

            // Bulk
            extendSelectionUp: () => this.ui.extendSelection(-1),
            extendSelectionDown: () => this.ui.extendSelection(1),
            selectAll: () => this.ui.selectAll(),
            selectSameMerchant: () => this.ui.selectSameMerchant(),
            applyToAll: () => this.ui.openBulkActions(),

            // Search & Filter
            focusSearch: () => this.ui.focusSearch(),
            openFilter: () => this.ui.toggleFilterPanel(),
            filterBusiness: () => this.ui.quickFilter('business', 'Business'),
            filterMCR: () => this.ui.quickFilter('business', 'Secondary'),
            filterPersonal: () => this.ui.quickFilter('business', 'Personal'),
            filterUnassigned: () => this.ui.quickFilter('business', 'Unassigned'),
            filterUnmatched: () => this.ui.quickFilter('receipt', 'unmatched'),
            filterNeedsReview: () => this.ui.quickFilter('status', 'needs-review'),

            // Image
            rotateImage: () => this.ui.rotateImage(),
            zoomIn: () => this.ui.zoomIn(),
            zoomOut: () => this.ui.zoomOut(),
            resetZoom: () => this.ui.resetZoom(),

            // System
            showHelp: () => this.toggleHelp(),
            quickView: () => this.ui.openQuickViewer(),
            undo: () => this.ui.undo(),
            save: () => this.ui.save(),
            export: () => this.ui.exportSelected(),
        };

        if (actions[action]) {
            actions[action]();

            // Log performance
            const elapsed = performance.now() - startTime;
            if (elapsed > 100) {
                console.warn(`Slow action: ${action} took ${elapsed.toFixed(1)}ms`);
            }
        }
    }

    toggleHelp() {
        this.helpVisible = !this.helpVisible;

        if (this.helpVisible) {
            this.showHelpModal();
        } else {
            this.hideHelpModal();
        }
    }

    showHelpModal() {
        // Remove existing modal
        const existing = document.getElementById('keyboard-help-modal');
        if (existing) existing.remove();

        const modal = document.createElement('div');
        modal.id = 'keyboard-help-modal';
        modal.className = 'keyboard-help-modal';
        modal.innerHTML = `
            <div class="help-backdrop" onclick="window.keyboardHandler.toggleHelp()"></div>
            <div class="help-content">
                <div class="help-header">
                    <h2>⌨️ Keyboard Shortcuts</h2>
                    <button class="help-close" onclick="window.keyboardHandler.toggleHelp()">×</button>
                </div>
                <div class="help-body">
                    ${this.renderShortcutCategories()}
                </div>
                <div class="help-footer">
                    Press <kbd>?</kbd> to toggle this help
                </div>
            </div>
        `;

        document.body.appendChild(modal);
        requestAnimationFrame(() => modal.classList.add('visible'));
    }

    hideHelpModal() {
        const modal = document.getElementById('keyboard-help-modal');
        if (modal) {
            modal.classList.remove('visible');
            setTimeout(() => modal.remove(), 200);
        }
    }

    renderShortcutCategories() {
        const categoryNames = {
            navigation: '🧭 Navigation',
            quickActions: '⚡ Quick Actions',
            businessType: '🏢 Business Type',
            ai: '🤖 AI Actions',
            bulk: '📦 Bulk Operations',
            search: '🔍 Search & Filter',
            image: '🖼️ Image Controls',
            system: '⚙️ System',
        };

        let html = '<div class="shortcut-grid">';

        for (const [category, shortcuts] of Object.entries(this.shortcuts)) {
            html += `
                <div class="shortcut-category">
                    <h3>${categoryNames[category] || category}</h3>
                    <div class="shortcut-list">
                        ${Object.values(shortcuts).map(s => `
                            <div class="shortcut-item">
                                <kbd>${s.key}</kbd>
                                <span>${s.desc}</span>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }

        // Add Ctrl shortcuts
        html += `
            <div class="shortcut-category">
                <h3>⌘ Ctrl/Cmd Shortcuts</h3>
                <div class="shortcut-list">
                    ${Object.values(this.ctrlShortcuts).map(s => `
                        <div class="shortcut-item">
                            <kbd>${s.key}</kbd>
                            <span>${s.desc}</span>
                        </div>
                    `).join('')}
                </div>
            </div>
        `;

        html += '</div>';
        return html;
    }

    enable() {
        this.enabled = true;
    }

    disable() {
        this.enabled = false;
    }

    setModalOpen(open) {
        this.modalOpen = open;
    }
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = KeyboardHandler;
}

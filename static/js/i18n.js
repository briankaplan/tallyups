/**
 * TallyUps Internationalization (i18n) Module
 * ============================================
 * Provides multi-language support with browser language detection
 * and fallback to English.
 *
 * Usage:
 *   // Initialize (auto-detects language)
 *   await i18n.init();
 *
 *   // Get translation
 *   const text = t('auth.signIn'); // Returns "Iniciar sesion" for Spanish
 *
 *   // With interpolation
 *   const greeting = t('dashboard.welcome', { name: 'John' }); // "Welcome, John!"
 *
 *   // Change language
 *   await i18n.setLocale('es');
 *
 *   // Get current locale
 *   const locale = i18n.getLocale(); // "es"
 */

const i18n = (function() {
    'use strict';

    // Configuration
    const config = {
        defaultLocale: 'en',
        supportedLocales: ['en', 'es'],
        fallbackLocale: 'en',
        storageKey: 'tallyups_locale',
        translationsPath: '/static/js/i18n'
    };

    // State
    let currentLocale = config.defaultLocale;
    let translations = {};
    let isInitialized = false;

    /**
     * Detect the user's preferred language from browser settings
     * @returns {string} Detected locale code
     */
    function detectBrowserLocale() {
        // Check navigator.languages (array of preferred languages)
        if (navigator.languages && navigator.languages.length > 0) {
            for (const lang of navigator.languages) {
                const locale = normalizeLocale(lang);
                if (config.supportedLocales.includes(locale)) {
                    return locale;
                }
            }
        }

        // Fallback to navigator.language
        if (navigator.language) {
            const locale = normalizeLocale(navigator.language);
            if (config.supportedLocales.includes(locale)) {
                return locale;
            }
        }

        // Fallback to navigator.userLanguage (IE)
        if (navigator.userLanguage) {
            const locale = normalizeLocale(navigator.userLanguage);
            if (config.supportedLocales.includes(locale)) {
                return locale;
            }
        }

        return config.defaultLocale;
    }

    /**
     * Normalize locale code (e.g., "es-MX" -> "es")
     * @param {string} locale - Full locale code
     * @returns {string} Normalized locale code
     */
    function normalizeLocale(locale) {
        if (!locale) return config.defaultLocale;
        // Get the primary language subtag (first part before hyphen)
        return locale.split('-')[0].toLowerCase();
    }

    /**
     * Get stored locale preference from localStorage
     * @returns {string|null} Stored locale or null
     */
    function getStoredLocale() {
        try {
            const stored = localStorage.getItem(config.storageKey);
            if (stored && config.supportedLocales.includes(stored)) {
                return stored;
            }
        } catch (e) {
            // localStorage might not be available
            console.warn('[i18n] Could not access localStorage:', e);
        }
        return null;
    }

    /**
     * Store locale preference in localStorage
     * @param {string} locale - Locale to store
     */
    function storeLocale(locale) {
        try {
            localStorage.setItem(config.storageKey, locale);
        } catch (e) {
            console.warn('[i18n] Could not store locale:', e);
        }
    }

    /**
     * Load translations for a specific locale
     * @param {string} locale - Locale to load
     * @returns {Promise<Object>} Translations object
     */
    async function loadTranslations(locale) {
        // Skip loading English if we're using inline fallbacks
        if (locale === 'en') {
            return getEnglishTranslations();
        }

        const url = `${config.translationsPath}/${locale}.json`;

        try {
            const response = await fetch(url);
            if (!response.ok) {
                throw new Error(`HTTP ${response.status}`);
            }
            const data = await response.json();
            return data;
        } catch (error) {
            console.warn(`[i18n] Failed to load translations for "${locale}":`, error);
            return null;
        }
    }

    /**
     * Get English translations (inline fallback)
     * @returns {Object} English translations
     */
    function getEnglishTranslations() {
        return {
            meta: {
                locale: 'en',
                name: 'English',
                nativeName: 'English',
                direction: 'ltr'
            },
            common: {
                appName: 'TallyUps',
                loading: 'Loading...',
                save: 'Save',
                cancel: 'Cancel',
                delete: 'Delete',
                edit: 'Edit',
                close: 'Close',
                confirm: 'Confirm',
                back: 'Back',
                next: 'Next',
                previous: 'Previous',
                search: 'Search',
                filter: 'Filter',
                clear: 'Clear',
                reset: 'Reset',
                submit: 'Submit',
                refresh: 'Refresh',
                retry: 'Retry',
                viewAll: 'View All',
                seeMore: 'See More',
                showLess: 'Show Less',
                yes: 'Yes',
                no: 'No',
                all: 'All',
                none: 'None',
                select: 'Select',
                selected: 'Selected',
                download: 'Download',
                upload: 'Upload',
                export: 'Export',
                import: 'Import',
                print: 'Print',
                share: 'Share',
                copy: 'Copy',
                paste: 'Paste',
                undo: 'Undo',
                redo: 'Redo',
                help: 'Help',
                about: 'About',
                version: 'Version',
                today: 'Today',
                yesterday: 'Yesterday',
                thisWeek: 'This Week',
                thisMonth: 'This Month',
                thisYear: 'This Year',
                lastWeek: 'Last Week',
                lastMonth: 'Last Month',
                lastYear: 'Last Year'
            },
            auth: {
                signIn: 'Sign In',
                signUp: 'Sign Up',
                signOut: 'Sign Out',
                login: 'Log In',
                logout: 'Log Out',
                register: 'Register',
                createAccount: 'Create Account',
                welcomeBack: 'Welcome back',
                signInToContinue: 'Sign in to your account to continue',
                createAccountTitle: 'Create account',
                getStarted: 'Get started with TallyUps today',
                email: 'Email',
                emailPlaceholder: 'you@example.com',
                password: 'Password',
                passwordPlaceholder: 'Enter your password',
                createPasswordPlaceholder: 'Create a password',
                confirmPassword: 'Confirm Password',
                fullName: 'Full Name',
                fullNamePlaceholder: 'John Doe',
                forgotPassword: 'Forgot your password?',
                resetPassword: 'Reset Password',
                sendResetLink: 'Send Reset Link',
                backToLogin: 'Back to Login',
                rememberMe: 'Remember me',
                orContinueWith: 'or continue with email',
                continueWithApple: 'Continue with Apple',
                continueWithGoogle: 'Continue with Google',
                signInWithApple: 'Sign in with Apple',
                signInWithGoogle: 'Sign in with Google',
                termsAgreement: 'By signing up, you agree to our',
                termsOfService: 'Terms of Service',
                and: 'and',
                privacyPolicy: 'Privacy Policy',
                alreadyHaveAccount: 'Already have an account?',
                dontHaveAccount: "Don't have an account?",
                signInInstead: 'Sign in instead',
                signUpInstead: 'Sign up instead',
                accountCreated: 'Account created! Redirecting...',
                loginSuccess: 'Success! Redirecting...',
                passwordRequirements: 'At least 8 characters with a number',
                passwordStrength: {
                    weak: 'Weak',
                    fair: 'Fair',
                    good: 'Good',
                    strong: 'Strong'
                },
                linkAccount: 'Link Your Account?',
                linkAccountMessage: 'An account with this email already exists. Would you like to link your Apple ID to this account?',
                linkAccountConfirm: 'Link Account',
                errors: {
                    invalidCredentials: 'Invalid email or password',
                    emailExists: 'Email already registered',
                    weakPassword: 'Password must be at least 8 characters',
                    passwordMismatch: 'Passwords do not match',
                    invalidEmail: 'Please enter a valid email address',
                    required: 'This field is required',
                    networkError: 'Connection error. Please try again.',
                    serverError: 'Server error. Please try again later.',
                    sessionExpired: 'Your session has expired. Please log in again.',
                    accountLocked: 'Account locked. Please contact support.',
                    tooManyAttempts: 'Too many attempts. Please try again later.'
                }
            },
            dashboard: {
                title: 'Dashboard',
                subtitle: "Welcome back! Here's your expense overview.",
                overview: 'Overview',
                recentActivity: 'Recent Activity',
                quickActions: 'Quick Actions',
                stats: {
                    business: 'Business',
                    secondary: 'Secondary',
                    personal: 'Personal',
                    receiptsCaputed: 'Receipts Captured',
                    vsLastMonth: 'vs last month',
                    thisWeek: 'this week',
                    totalExpenses: 'Total Expenses',
                    pendingReview: 'Pending Review',
                    matchedReceipts: 'Matched Receipts',
                    unmatchedReceipts: 'Unmatched Receipts'
                },
                actions: {
                    scan: 'Scan',
                    inbox: 'Inbox',
                    library: 'Library',
                    reports: 'Reports',
                    reconciler: 'Reconciler',
                    settings: 'Settings'
                },
                noReceipts: 'No receipts found',
                scanFirstReceipt: 'Scan your first receipt',
                noMatchingFilter: 'No receipts match this filter'
            },
            receipts: {
                title: 'Receipts',
                receipt: 'Receipt',
                receipts: 'Receipts',
                library: 'Receipt Library',
                inbox: 'Inbox',
                scan: 'Scan Receipt',
                scanReceipt: 'Scan Receipt',
                upload: 'Upload Receipt',
                uploadReceipt: 'Upload Receipt',
                dragDropHere: 'Drag and drop receipts here',
                orClickToUpload: 'or click to upload',
                supportedFormats: 'Supported formats: JPG, PNG, PDF, HEIC',
                processing: 'Processing...',
                processingReceipt: 'Processing receipt...',
                extractingData: 'Extracting data...',
                details: 'Receipt Details',
                merchant: 'Merchant',
                amount: 'Amount',
                date: 'Date',
                category: 'Category',
                businessType: 'Business Type',
                paymentMethod: 'Payment Method',
                notes: 'Notes',
                tags: 'Tags',
                addNote: 'Add Note',
                addTag: 'Add Tag',
                linkedTransaction: 'Linked Transaction',
                noLinkedTransaction: 'No linked transaction',
                linkTransaction: 'Link Transaction',
                unlinkTransaction: 'Unlink Transaction',
                viewOriginal: 'View Original',
                downloadOriginal: 'Download Original',
                deleteReceipt: 'Delete Receipt',
                confirmDelete: 'Are you sure you want to delete this receipt?',
                status: {
                    pending: 'Pending',
                    verified: 'Verified',
                    mismatch: 'Mismatch',
                    needsReview: 'Needs Review',
                    matched: 'Matched',
                    unmatched: 'Unmatched'
                },
                filters: {
                    all: 'All',
                    needsReview: 'Needs Review',
                    verified: 'Verified',
                    mismatch: 'Mismatch',
                    business: 'Business',
                    personal: 'Personal',
                    thisMonth: 'This Month',
                    lastMonth: 'Last Month',
                    custom: 'Custom'
                },
                sort: {
                    date: 'Date',
                    amount: 'Amount',
                    merchant: 'Merchant',
                    newest: 'Newest',
                    oldest: 'Oldest',
                    highestAmount: 'Highest Amount',
                    lowestAmount: 'Lowest Amount'
                },
                empty: {
                    title: 'No receipts',
                    description: 'Scan or upload your first receipt to get started',
                    action: 'Scan Receipt'
                },
                viewer: {
                    zoomIn: 'Zoom In',
                    zoomOut: 'Zoom Out',
                    rotateLeft: 'Rotate Left',
                    rotateRight: 'Rotate Right',
                    fitToScreen: 'Fit to Screen',
                    actualSize: 'Actual Size',
                    fullscreen: 'Fullscreen',
                    exitFullscreen: 'Exit Fullscreen'
                }
            },
            transactions: {
                title: 'Transactions',
                transaction: 'Transaction',
                transactions: 'Transactions',
                description: 'Description',
                amount: 'Amount',
                date: 'Date',
                category: 'Category',
                account: 'Account',
                status: 'Status',
                withReceipt: 'With Receipt',
                withoutReceipt: 'Without Receipt',
                matchReceipt: 'Match Receipt',
                unmatchReceipt: 'Unmatch Receipt',
                viewDetails: 'View Details',
                filters: {
                    all: 'All',
                    withReceipt: 'With Receipt',
                    withoutReceipt: 'Without Receipt',
                    business: 'Business',
                    personal: 'Personal'
                },
                empty: {
                    title: 'No transactions',
                    description: 'Connect your bank to import transactions automatically'
                }
            },
            reconciler: {
                title: 'Reconciler',
                subtitle: 'Match receipts with bank transactions',
                autoMatch: 'Auto Match',
                manualMatch: 'Manual Match',
                review: 'Review',
                approve: 'Approve',
                reject: 'Reject',
                skip: 'Skip',
                matchConfidence: 'Match Confidence',
                suggestedMatches: 'Suggested Matches',
                noSuggestions: 'No suggestions available',
                confirmMatch: 'Confirm Match',
                undoMatch: 'Undo Match',
                status: {
                    matched: 'Matched',
                    unmatched: 'Unmatched',
                    reviewing: 'Reviewing',
                    confirmed: 'Confirmed'
                }
            },
            reports: {
                title: 'Reports',
                expenseReport: 'Expense Report',
                createReport: 'Create Report',
                newReport: 'New Report',
                reportName: 'Report Name',
                dateRange: 'Date Range',
                startDate: 'Start Date',
                endDate: 'End Date',
                includeReceipts: 'Include Receipts',
                generatePdf: 'Generate PDF',
                generateCsv: 'Generate CSV',
                downloadReport: 'Download Report',
                shareReport: 'Share Report',
                emailReport: 'Email Report',
                summary: 'Summary',
                totalAmount: 'Total Amount',
                numberOfReceipts: 'Number of Receipts',
                byCategory: 'By Category',
                byMerchant: 'By Merchant',
                byDate: 'By Date',
                status: {
                    draft: 'Draft',
                    pending: 'Pending',
                    submitted: 'Submitted',
                    approved: 'Approved',
                    rejected: 'Rejected'
                },
                empty: {
                    title: 'No reports',
                    description: 'Create your first expense report',
                    action: 'Create Report'
                }
            },
            settings: {
                title: 'Settings',
                account: 'Account',
                profile: 'Profile',
                preferences: 'Preferences',
                notifications: 'Notifications',
                security: 'Security',
                privacy: 'Privacy',
                billing: 'Billing',
                integrations: 'Integrations',
                connectedAccounts: 'Connected Accounts',
                language: 'Language',
                theme: 'Theme',
                darkMode: 'Dark Mode',
                lightMode: 'Light Mode',
                systemDefault: 'System Default',
                currency: 'Currency',
                timezone: 'Timezone',
                dateFormat: 'Date Format',
                changePassword: 'Change Password',
                currentPassword: 'Current Password',
                newPassword: 'New Password',
                confirmNewPassword: 'Confirm New Password',
                twoFactorAuth: 'Two-Factor Authentication',
                enableTwoFactor: 'Enable Two-Factor Authentication',
                disableTwoFactor: 'Disable Two-Factor Authentication',
                sessions: 'Active Sessions',
                logoutAllDevices: 'Log Out All Devices',
                deleteAccount: 'Delete Account',
                deleteAccountWarning: 'This action is permanent and cannot be undone.',
                exportData: 'Export My Data',
                dataRetention: 'Data Retention',
                bankConnections: 'Bank Connections',
                connectBank: 'Connect Bank',
                disconnectBank: 'Disconnect Bank',
                syncFrequency: 'Sync Frequency',
                lastSync: 'Last Sync',
                emailNotifications: 'Email Notifications',
                pushNotifications: 'Push Notifications',
                notifyOnNewReceipt: 'Notify on new receipt',
                notifyOnMatch: 'Notify on transaction match',
                weeklyDigest: 'Weekly Digest',
                monthlyReport: 'Monthly Report',
                categories: {
                    title: 'Categories',
                    addCategory: 'Add Category',
                    editCategory: 'Edit Category',
                    deleteCategory: 'Delete Category',
                    categoryName: 'Category Name',
                    categoryColor: 'Category Color',
                    defaultCategory: 'Default Category'
                },
                businessTypes: {
                    title: 'Business Types',
                    business: 'Business',
                    personal: 'Personal',
                    secondary: 'Secondary'
                },
                saved: 'Settings saved',
                saveFailed: 'Failed to save settings'
            },
            scanner: {
                title: 'Scanner',
                takePhoto: 'Take Photo',
                chooseFromLibrary: 'Choose from Library',
                flash: 'Flash',
                flashOn: 'Flash On',
                flashOff: 'Flash Off',
                flashAuto: 'Flash Auto',
                switchCamera: 'Switch Camera',
                capturing: 'Capturing...',
                processing: 'Processing...',
                retake: 'Retake',
                usePhoto: 'Use Photo',
                tips: {
                    title: 'Tips for better results',
                    lighting: 'Ensure good lighting',
                    flat: 'Place receipt on a flat surface',
                    focus: 'Wait for camera to focus',
                    edges: 'Include all edges of the receipt'
                },
                errors: {
                    cameraPermission: 'Camera permission required',
                    cameraNotAvailable: 'Camera not available',
                    processingFailed: 'Failed to process image'
                }
            },
            errors: {
                generic: 'An error occurred',
                notFound: 'Resource not found',
                unauthorized: 'Unauthorized',
                forbidden: 'Access denied',
                serverError: 'Server error',
                networkError: 'Connection error',
                timeout: 'Request timed out',
                invalidInput: 'Invalid input',
                validationError: 'Validation error',
                uploadFailed: 'Upload failed',
                downloadFailed: 'Download failed',
                deleteFailed: 'Delete failed',
                saveFailed: 'Save failed',
                loadFailed: 'Failed to load data',
                sessionExpired: 'Your session has expired',
                pleaseLogin: 'Please log in to continue',
                permissionDenied: 'You do not have permission to perform this action',
                resourceNotFound: 'Resource not found',
                tryAgain: 'Please try again',
                contactSupport: 'If the problem persists, contact support',
                connectionLost: 'Connection lost',
                reconnecting: 'Reconnecting...',
                offline: 'No internet connection',
                online: 'Connection restored'
            },
            success: {
                saved: 'Saved successfully',
                deleted: 'Deleted successfully',
                uploaded: 'Uploaded successfully',
                downloaded: 'Downloaded successfully',
                copied: 'Copied to clipboard',
                sent: 'Sent successfully',
                updated: 'Updated successfully',
                created: 'Created successfully',
                matched: 'Matched successfully',
                unmatched: 'Unmatched successfully'
            },
            confirmations: {
                deleteTitle: 'Confirm Delete',
                deleteMessage: 'Are you sure you want to delete this item?',
                deleteWarning: 'This action cannot be undone.',
                unsavedChanges: 'You have unsaved changes. Are you sure you want to leave?',
                logoutTitle: 'Log Out',
                logoutMessage: 'Are you sure you want to log out?',
                cancelAction: 'Are you sure you want to cancel?'
            },
            pagination: {
                showing: 'Showing',
                of: 'of',
                results: 'results',
                page: 'Page',
                first: 'First',
                last: 'Last',
                previous: 'Previous',
                next: 'Next',
                perPage: 'Per Page'
            },
            dates: {
                today: 'Today',
                yesterday: 'Yesterday',
                tomorrow: 'Tomorrow',
                thisWeek: 'This Week',
                lastWeek: 'Last Week',
                thisMonth: 'This Month',
                lastMonth: 'Last Month',
                thisYear: 'This Year',
                lastYear: 'Last Year',
                custom: 'Custom',
                from: 'From',
                to: 'To',
                days: {
                    sunday: 'Sunday',
                    monday: 'Monday',
                    tuesday: 'Tuesday',
                    wednesday: 'Wednesday',
                    thursday: 'Thursday',
                    friday: 'Friday',
                    saturday: 'Saturday'
                },
                daysShort: {
                    sun: 'Sun',
                    mon: 'Mon',
                    tue: 'Tue',
                    wed: 'Wed',
                    thu: 'Thu',
                    fri: 'Fri',
                    sat: 'Sat'
                },
                months: {
                    january: 'January',
                    february: 'February',
                    march: 'March',
                    april: 'April',
                    may: 'May',
                    june: 'June',
                    july: 'July',
                    august: 'August',
                    september: 'September',
                    october: 'October',
                    november: 'November',
                    december: 'December'
                },
                monthsShort: {
                    jan: 'Jan',
                    feb: 'Feb',
                    mar: 'Mar',
                    apr: 'Apr',
                    may: 'May',
                    jun: 'Jun',
                    jul: 'Jul',
                    aug: 'Aug',
                    sep: 'Sep',
                    oct: 'Oct',
                    nov: 'Nov',
                    dec: 'Dec'
                }
            },
            footer: {
                terms: 'Terms',
                privacy: 'Privacy',
                help: 'Help',
                support: 'Support',
                contact: 'Contact',
                copyright: 'TallyUps. All rights reserved.'
            },
            hero: {
                title: 'TallyUps',
                subtitle: 'The smartest way to manage receipts and expenses for your business',
                features: {
                    snapCapture: {
                        title: 'Snap & Capture',
                        description: 'Scan receipts instantly with AI-powered extraction'
                    },
                    autoMatch: {
                        title: 'Auto-Match',
                        description: 'Link receipts to bank transactions automatically'
                    },
                    expenseReports: {
                        title: 'Expense Reports',
                        description: 'Generate professional reports in seconds'
                    }
                }
            },
            accessibility: {
                skipToContent: 'Skip to content',
                closeDialog: 'Close dialog',
                openMenu: 'Open menu',
                closeMenu: 'Close menu',
                expandSection: 'Expand section',
                collapseSection: 'Collapse section',
                loading: 'Loading content',
                loadingComplete: 'Loading complete'
            }
        };
    }

    /**
     * Get a value from a nested object using dot notation
     * @param {Object} obj - Object to traverse
     * @param {string} path - Dot-notation path (e.g., "auth.signIn")
     * @returns {*} Value at path or undefined
     */
    function getNestedValue(obj, path) {
        if (!obj || !path) return undefined;

        const keys = path.split('.');
        let current = obj;

        for (const key of keys) {
            if (current === undefined || current === null) {
                return undefined;
            }
            current = current[key];
        }

        return current;
    }

    /**
     * Interpolate variables in a string
     * @param {string} str - String with placeholders like {{name}}
     * @param {Object} vars - Variables to interpolate
     * @returns {string} Interpolated string
     */
    function interpolate(str, vars) {
        if (!str || typeof str !== 'string' || !vars) return str;

        return str.replace(/\{\{(\w+)\}\}/g, (match, key) => {
            return vars.hasOwnProperty(key) ? vars[key] : match;
        });
    }

    /**
     * Public API
     */
    return {
        /**
         * Initialize the i18n module
         * @param {Object} options - Optional configuration overrides
         * @returns {Promise<void>}
         */
        async init(options = {}) {
            // Merge options
            Object.assign(config, options);

            // Determine locale (priority: stored > URL param > browser > default)
            const urlParams = new URLSearchParams(window.location.search);
            const urlLocale = urlParams.get('lang') || urlParams.get('locale');

            let locale = config.defaultLocale;

            // Check URL parameter first
            if (urlLocale && config.supportedLocales.includes(urlLocale)) {
                locale = urlLocale;
                storeLocale(locale);
            }
            // Then check stored preference
            else if (getStoredLocale()) {
                locale = getStoredLocale();
            }
            // Finally, detect from browser
            else {
                locale = detectBrowserLocale();
            }

            // Load translations
            const loaded = await loadTranslations(locale);
            if (loaded) {
                translations = loaded;
                currentLocale = locale;
            } else {
                // Fallback to English
                translations = getEnglishTranslations();
                currentLocale = config.fallbackLocale;
            }

            // Set HTML lang attribute
            document.documentElement.lang = currentLocale;

            // Set text direction if specified
            if (translations.meta && translations.meta.direction) {
                document.documentElement.dir = translations.meta.direction;
            }

            isInitialized = true;

            // Dispatch event for components to update
            window.dispatchEvent(new CustomEvent('i18n:loaded', {
                detail: { locale: currentLocale }
            }));

            console.log(`[i18n] Initialized with locale: ${currentLocale}`);
        },

        /**
         * Get translation for a key
         * @param {string} key - Dot-notation key (e.g., "auth.signIn")
         * @param {Object} vars - Optional variables for interpolation
         * @returns {string} Translated string or key if not found
         */
        t(key, vars = null) {
            if (!isInitialized) {
                console.warn('[i18n] Not initialized. Call i18n.init() first.');
                return key;
            }

            let value = getNestedValue(translations, key);

            // Fallback to English if not found
            if (value === undefined && currentLocale !== 'en') {
                const englishTranslations = getEnglishTranslations();
                value = getNestedValue(englishTranslations, key);
            }

            // Return key if still not found
            if (value === undefined) {
                console.warn(`[i18n] Missing translation for key: ${key}`);
                return key;
            }

            // Interpolate variables if provided
            if (vars && typeof value === 'string') {
                value = interpolate(value, vars);
            }

            return value;
        },

        /**
         * Change the current locale
         * @param {string} locale - New locale code
         * @returns {Promise<boolean>} Success status
         */
        async setLocale(locale) {
            if (!config.supportedLocales.includes(locale)) {
                console.warn(`[i18n] Unsupported locale: ${locale}`);
                return false;
            }

            if (locale === currentLocale) {
                return true;
            }

            const loaded = await loadTranslations(locale);
            if (loaded) {
                translations = loaded;
                currentLocale = locale;
                storeLocale(locale);

                // Update HTML attributes
                document.documentElement.lang = locale;
                if (translations.meta && translations.meta.direction) {
                    document.documentElement.dir = translations.meta.direction;
                }

                // Dispatch event for components to update
                window.dispatchEvent(new CustomEvent('i18n:changed', {
                    detail: { locale: currentLocale }
                }));

                console.log(`[i18n] Locale changed to: ${locale}`);
                return true;
            }

            return false;
        },

        /**
         * Get the current locale
         * @returns {string} Current locale code
         */
        getLocale() {
            return currentLocale;
        },

        /**
         * Get list of supported locales
         * @returns {string[]} Array of supported locale codes
         */
        getSupportedLocales() {
            return [...config.supportedLocales];
        },

        /**
         * Check if a locale is supported
         * @param {string} locale - Locale code to check
         * @returns {boolean} True if supported
         */
        isSupported(locale) {
            return config.supportedLocales.includes(locale);
        },

        /**
         * Check if i18n is initialized
         * @returns {boolean} True if initialized
         */
        isReady() {
            return isInitialized;
        },

        /**
         * Get all translations for current locale
         * @returns {Object} Translations object
         */
        getTranslations() {
            return { ...translations };
        },

        /**
         * Format a number according to locale
         * @param {number} num - Number to format
         * @param {Object} options - Intl.NumberFormat options
         * @returns {string} Formatted number
         */
        formatNumber(num, options = {}) {
            const localeMap = { en: 'en-US', es: 'es-ES' };
            const locale = localeMap[currentLocale] || 'en-US';
            return new Intl.NumberFormat(locale, options).format(num);
        },

        /**
         * Format currency according to locale
         * @param {number} amount - Amount to format
         * @param {string} currency - Currency code (default: USD)
         * @returns {string} Formatted currency
         */
        formatCurrency(amount, currency = 'USD') {
            const localeMap = { en: 'en-US', es: 'es-ES' };
            const locale = localeMap[currentLocale] || 'en-US';
            return new Intl.NumberFormat(locale, {
                style: 'currency',
                currency: currency
            }).format(amount);
        },

        /**
         * Format date according to locale
         * @param {Date|string} date - Date to format
         * @param {Object} options - Intl.DateTimeFormat options
         * @returns {string} Formatted date
         */
        formatDate(date, options = {}) {
            const localeMap = { en: 'en-US', es: 'es-ES' };
            const locale = localeMap[currentLocale] || 'en-US';
            const dateObj = typeof date === 'string' ? new Date(date) : date;

            const defaultOptions = {
                year: 'numeric',
                month: 'short',
                day: 'numeric'
            };

            return new Intl.DateTimeFormat(locale, { ...defaultOptions, ...options }).format(dateObj);
        }
    };
})();

/**
 * Shorthand translation function
 * @param {string} key - Translation key
 * @param {Object} vars - Optional interpolation variables
 * @returns {string} Translated string
 */
function t(key, vars = null) {
    return i18n.t(key, vars);
}

// Auto-initialize when DOM is ready
if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => i18n.init());
} else {
    i18n.init();
}

// Export for module usage
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { i18n, t };
}

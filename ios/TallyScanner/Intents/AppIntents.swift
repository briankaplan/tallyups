import AppIntents
import SwiftUI

// MARK: - Scan Receipt Intent

/// Siri: "Hey Siri, scan a receipt with TallyUps"
struct ScanReceiptIntent: AppIntent {
    static var title: LocalizedStringResource = "Scan Receipt"
    static var description = IntentDescription("Open the camera to scan a receipt")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        // Post notification to open scanner
        NotificationCenter.default.post(name: .navigateToScanner, object: nil)
        return .result()
    }
}

// MARK: - Check Inbox Intent

/// Siri: "Hey Siri, check my receipt inbox"
struct CheckInboxIntent: AppIntent {
    static var title: LocalizedStringResource = "Check Receipt Inbox"
    static var description = IntentDescription("View pending receipts in your inbox")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        NotificationCenter.default.post(name: .navigateToInbox, object: nil)
        return .result()
    }
}

// MARK: - Show Spending Intent

/// Siri: "Hey Siri, show my spending in TallyUps"
struct ShowSpendingIntent: AppIntent {
    static var title: LocalizedStringResource = "Show Spending"
    static var description = IntentDescription("View your spending summary and transactions")
    static var openAppWhenRun: Bool = true

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        NotificationCenter.default.post(name: .navigateToTransactions, object: nil)
        return .result()
    }
}

// MARK: - Get Spending Total Intent

/// Siri: "Hey Siri, how much did I spend today?"
struct GetSpendingTotalIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Spending Total"
    static var description = IntentDescription("Get your spending total for a time period")

    @Parameter(title: "Time Period")
    var timePeriod: SpendingTimePeriod

    init() {
        self.timePeriod = .today
    }

    init(timePeriod: SpendingTimePeriod) {
        self.timePeriod = timePeriod
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Load spending data from widget data store
        guard let userDefaults = UserDefaults(suiteName: "group.com.tallyups.scanner"),
              let data = userDefaults.data(forKey: "widgetSpendingData"),
              let spendingData = try? JSONDecoder().decode(SpendingDataForIntent.self, from: data) else {
            return .result(dialog: "I couldn't load your spending data. Please open TallyUps first.")
        }

        let amount: Double
        let periodName: String

        switch timePeriod {
        case .today:
            amount = spendingData.dailyTotal
            periodName = "today"
        case .thisWeek:
            amount = spendingData.weeklyTotal
            periodName = "this week"
        case .thisMonth:
            amount = spendingData.monthlyTotal
            periodName = "this month"
        }

        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        let formattedAmount = formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"

        return .result(dialog: "You've spent \(formattedAmount) \(periodName).")
    }
}

// MARK: - Get Pending Receipts Intent

/// Siri: "Hey Siri, how many receipts are pending?"
struct GetPendingReceiptsIntent: AppIntent {
    static var title: LocalizedStringResource = "Get Pending Receipts"
    static var description = IntentDescription("Check how many receipts are waiting in your inbox")

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        guard let userDefaults = UserDefaults(suiteName: "group.com.tallyups.scanner") else {
            return .result(dialog: "I couldn't access your receipt data.")
        }

        let pendingCount = userDefaults.integer(forKey: "widget_pending_count")

        if pendingCount == 0 {
            return .result(dialog: "You're all caught up! No receipts are waiting to be matched.")
        } else if pendingCount == 1 {
            return .result(dialog: "You have 1 receipt waiting in your inbox.")
        } else {
            return .result(dialog: "You have \(pendingCount) receipts waiting in your inbox.")
        }
    }
}

// MARK: - Time Period Enum

enum SpendingTimePeriod: String, AppEnum {
    case today
    case thisWeek
    case thisMonth

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Time Period"

    static var caseDisplayRepresentations: [SpendingTimePeriod: DisplayRepresentation] = [
        .today: "Today",
        .thisWeek: "This Week",
        .thisMonth: "This Month"
    ]
}

// MARK: - Internal Model for Decoding

private struct SpendingDataForIntent: Codable {
    let dailyTotal: Double
    let weeklyTotal: Double
    let monthlyTotal: Double
    let pendingReceipts: Int
    let matchedReceipts: Int
}

// MARK: - App Shortcuts Provider

struct TallyScannerShortcuts: AppShortcutsProvider {
    static var appShortcuts: [AppShortcut] {
        // Scan Receipt
        AppShortcut(
            intent: ScanReceiptIntent(),
            phrases: [
                "Scan a receipt with \(.applicationName)",
                "Scan receipt in \(.applicationName)",
                "Take a receipt photo with \(.applicationName)",
                "Capture receipt with \(.applicationName)"
            ],
            shortTitle: "Scan Receipt",
            systemImageName: "camera.fill"
        )

        // Check Inbox
        AppShortcut(
            intent: CheckInboxIntent(),
            phrases: [
                "Check my receipt inbox in \(.applicationName)",
                "Show pending receipts in \(.applicationName)",
                "Open inbox in \(.applicationName)"
            ],
            shortTitle: "Check Inbox",
            systemImageName: "tray.fill"
        )

        // Show Spending
        AppShortcut(
            intent: ShowSpendingIntent(),
            phrases: [
                "Show my spending in \(.applicationName)",
                "View spending in \(.applicationName)",
                "Open spending summary in \(.applicationName)"
            ],
            shortTitle: "Show Spending",
            systemImageName: "chart.line.uptrend.xyaxis"
        )

        // Get Spending Total - Today
        AppShortcut(
            intent: GetSpendingTotalIntent(timePeriod: .today),
            phrases: [
                "How much did I spend today in \(.applicationName)",
                "What's my spending today in \(.applicationName)",
                "Today's spending in \(.applicationName)"
            ],
            shortTitle: "Today's Spending",
            systemImageName: "dollarsign.circle.fill"
        )

        // Get Spending Total - This Week
        AppShortcut(
            intent: GetSpendingTotalIntent(timePeriod: .thisWeek),
            phrases: [
                "How much did I spend this week in \(.applicationName)",
                "What's my weekly spending in \(.applicationName)",
                "This week's spending in \(.applicationName)"
            ],
            shortTitle: "Weekly Spending",
            systemImageName: "dollarsign.circle.fill"
        )

        // Get Spending Total - This Month
        AppShortcut(
            intent: GetSpendingTotalIntent(timePeriod: .thisMonth),
            phrases: [
                "How much did I spend this month in \(.applicationName)",
                "What's my monthly spending in \(.applicationName)",
                "This month's spending in \(.applicationName)"
            ],
            shortTitle: "Monthly Spending",
            systemImageName: "dollarsign.circle.fill"
        )

        // Get Pending Receipts
        AppShortcut(
            intent: GetPendingReceiptsIntent(),
            phrases: [
                "How many receipts are pending in \(.applicationName)",
                "Do I have pending receipts in \(.applicationName)",
                "Check pending receipts in \(.applicationName)"
            ],
            shortTitle: "Pending Receipts",
            systemImageName: "doc.text.fill"
        )
    }
}

// MARK: - Log Expense Intent (Manual Transaction)

/// Siri: "Hey Siri, log an expense in TallyUps"
struct LogExpenseIntent: AppIntent {
    static var title: LocalizedStringResource = "Log Expense"
    static var description = IntentDescription("Manually log an expense or transaction")

    @Parameter(title: "Merchant")
    var merchant: String

    @Parameter(title: "Amount")
    var amount: Double

    @Parameter(title: "Category")
    var category: ExpenseCategory?

    @Parameter(title: "Business Type")
    var businessType: BusinessTypeOption?

    @Parameter(title: "Notes")
    var notes: String?

    init() {}

    init(merchant: String, amount: Double, category: ExpenseCategory? = nil, businessType: BusinessTypeOption? = nil, notes: String? = nil) {
        self.merchant = merchant
        self.amount = amount
        self.category = category
        self.businessType = businessType
        self.notes = notes
    }

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Store the expense data for the app to process
        let expenseData: [String: Any] = [
            "merchant": merchant,
            "amount": amount,
            "category": category?.rawValue ?? "",
            "business_type": businessType?.rawValue ?? "Personal",
            "notes": notes ?? "",
            "date": Date().ISO8601Format(),
            "source": "siri_shortcut"
        ]

        if let data = try? JSONSerialization.data(withJSONObject: expenseData) {
            UserDefaults(suiteName: "group.com.tallyups.scanner")?.set(data, forKey: "pending_manual_expense")
        }

        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        let formattedAmount = formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"

        return .result(dialog: "Got it! Logged \(formattedAmount) at \(merchant). Open TallyUps to add a receipt.")
    }
}

// MARK: - Import Receipt From Photo Intent

/// Siri: "Hey Siri, import this receipt to TallyUps"
struct ImportReceiptIntent: AppIntent {
    static var title: LocalizedStringResource = "Import Receipt"
    static var description = IntentDescription("Import a receipt from a photo or screenshot")
    static var openAppWhenRun: Bool = true

    @Parameter(title: "Receipt Image")
    var image: IntentFile?

    init() {}

    init(image: IntentFile) {
        self.image = image
    }

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        // Save image for app to process
        if let image = image, let data = try? Data(contentsOf: image.fileURL!) {
            let documentsPath = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: "group.com.tallyups.scanner")
            let imagePath = documentsPath?.appendingPathComponent("imported_receipt_\(UUID().uuidString).jpg")

            if let imagePath = imagePath {
                try? data.write(to: imagePath)
                UserDefaults(suiteName: "group.com.tallyups.scanner")?.set(imagePath.path, forKey: "pending_import_receipt")
            }
        }

        NotificationCenter.default.post(name: .navigateToInbox, object: nil)
        return .result()
    }
}

// MARK: - Quick Match Intent

/// Siri: "Hey Siri, match my latest receipt"
struct QuickMatchIntent: AppIntent {
    static var title: LocalizedStringResource = "Quick Match Receipt"
    static var description = IntentDescription("Automatically match recent receipts to transactions")
    static var openAppWhenRun: Bool = false

    @MainActor
    func perform() async throws -> some IntentResult & ProvidesDialog {
        // Trigger background matching
        UserDefaults(suiteName: "group.com.tallyups.scanner")?.set(true, forKey: "trigger_auto_match")

        return .result(dialog: "I'll look for matches for your recent receipts. Check TallyUps for results.")
    }
}

// MARK: - Export Report Intent

/// Siri: "Hey Siri, export my expense report"
struct ExportReportIntent: AppIntent {
    static var title: LocalizedStringResource = "Export Expense Report"
    static var description = IntentDescription("Export an expense report for a time period")
    static var openAppWhenRun: Bool = true

    @Parameter(title: "Time Period")
    var timePeriod: ReportTimePeriod

    @Parameter(title: "Include Receipts")
    var includeReceipts: Bool

    init() {
        self.timePeriod = .thisMonth
        self.includeReceipts = true
    }

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        // Store export parameters
        let params: [String: Any] = [
            "period": timePeriod.rawValue,
            "include_receipts": includeReceipts,
            "triggered_by": "siri"
        ]

        if let data = try? JSONSerialization.data(withJSONObject: params) {
            UserDefaults(suiteName: "group.com.tallyups.scanner")?.set(data, forKey: "pending_export")
        }

        NotificationCenter.default.post(name: .navigateToReportExport, object: nil)
        return .result()
    }
}

// MARK: - Search Transactions Intent

/// Siri: "Hey Siri, find my Starbucks transactions"
struct SearchTransactionsIntent: AppIntent {
    static var title: LocalizedStringResource = "Search Transactions"
    static var description = IntentDescription("Search for transactions by merchant or category")
    static var openAppWhenRun: Bool = true

    @Parameter(title: "Search Term")
    var searchTerm: String

    init() {
        self.searchTerm = ""
    }

    init(searchTerm: String) {
        self.searchTerm = searchTerm
    }

    @MainActor
    func perform() async throws -> some IntentResult & OpensIntent {
        UserDefaults(suiteName: "group.com.tallyups.scanner")?.set(searchTerm, forKey: "search_query")
        NotificationCenter.default.post(name: .navigateToTransactions, object: searchTerm)
        return .result()
    }
}

// MARK: - Enums for Intents

enum ExpenseCategory: String, AppEnum {
    case food = "Food & Dining"
    case transportation = "Transportation"
    case shopping = "Shopping"
    case entertainment = "Entertainment"
    case utilities = "Utilities"
    case travel = "Travel"
    case health = "Health"
    case office = "Office Supplies"
    case other = "Other"

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Category"

    static var caseDisplayRepresentations: [ExpenseCategory: DisplayRepresentation] = [
        .food: "Food & Dining",
        .transportation: "Transportation",
        .shopping: "Shopping",
        .entertainment: "Entertainment",
        .utilities: "Utilities",
        .travel: "Travel",
        .health: "Health",
        .office: "Office Supplies",
        .other: "Other"
    ]
}

enum BusinessTypeOption: String, AppEnum {
    case personal = "Personal"
    case business = "Business"

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Business Type"

    static var caseDisplayRepresentations: [BusinessTypeOption: DisplayRepresentation] = [
        .personal: "Personal",
        .business: "Business"
    ]
}

enum ReportTimePeriod: String, AppEnum {
    case lastWeek = "Last Week"
    case thisMonth = "This Month"
    case lastMonth = "Last Month"
    case thisQuarter = "This Quarter"
    case thisYear = "This Year"

    static var typeDisplayRepresentation: TypeDisplayRepresentation = "Time Period"

    static var caseDisplayRepresentations: [ReportTimePeriod: DisplayRepresentation] = [
        .lastWeek: "Last Week",
        .thisMonth: "This Month",
        .lastMonth: "Last Month",
        .thisQuarter: "This Quarter",
        .thisYear: "This Year"
    ]
}

// MARK: - Enhanced Shortcuts Provider

extension TallyScannerShortcuts {
    static var additionalShortcuts: [AppShortcut] {
        // Log Expense
        AppShortcut(
            intent: LogExpenseIntent(),
            phrases: [
                "Log an expense in \(.applicationName)",
                "Add expense to \(.applicationName)",
                "Record a purchase in \(.applicationName)",
                "Log \(\.$amount) at \(\.$merchant) in \(.applicationName)"
            ],
            shortTitle: "Log Expense",
            systemImageName: "plus.circle.fill"
        )

        // Import Receipt
        AppShortcut(
            intent: ImportReceiptIntent(),
            phrases: [
                "Import receipt to \(.applicationName)",
                "Add this receipt to \(.applicationName)",
                "Save receipt in \(.applicationName)"
            ],
            shortTitle: "Import Receipt",
            systemImageName: "square.and.arrow.down.fill"
        )

        // Quick Match
        AppShortcut(
            intent: QuickMatchIntent(),
            phrases: [
                "Match my receipts in \(.applicationName)",
                "Auto-match receipts in \(.applicationName)",
                "Find matches in \(.applicationName)"
            ],
            shortTitle: "Quick Match",
            systemImageName: "wand.and.stars"
        )

        // Export Report
        AppShortcut(
            intent: ExportReportIntent(),
            phrases: [
                "Export expense report from \(.applicationName)",
                "Create expense report in \(.applicationName)",
                "Generate report from \(.applicationName)"
            ],
            shortTitle: "Export Report",
            systemImageName: "doc.text.fill"
        )

        // Search
        AppShortcut(
            intent: SearchTransactionsIntent(),
            phrases: [
                "Find \(\.$searchTerm) in \(.applicationName)",
                "Search \(\.$searchTerm) in \(.applicationName)",
                "Look for \(\.$searchTerm) transactions in \(.applicationName)"
            ],
            shortTitle: "Search",
            systemImageName: "magnifyingglass"
        )
    }
}

// MARK: - Notification Names

extension Notification.Name {
    static let navigateToScanner = Notification.Name("navigateToScanner")
    static let navigateToTransactions = Notification.Name("navigateToTransactions")
    static let navigateToLibrary = Notification.Name("navigateToLibrary")
    static let navigateToInbox = Notification.Name("navigateToInbox")
    static let navigateToSettings = Notification.Name("navigateToSettings")
    static let navigateToReportExport = Notification.Name("navigateToReportExport")
}

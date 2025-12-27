import Foundation
import WidgetKit

// MARK: - App Group Identifier (must match widget extension)
private let appGroupIdentifier = "group.com.tallyups.scanner"

/// Service for updating widget data from the main app
@MainActor
class WidgetService: ObservableObject {
    static let shared = WidgetService()

    private let userDefaults: UserDefaults?
    private let dataKey = "widgetSpendingData"

    private init() {
        userDefaults = UserDefaults(suiteName: appGroupIdentifier)
    }

    // MARK: - Update Spending Data

    /// Update widget spending data based on current transactions
    func updateSpendingData(
        transactions: [Transaction],
        pendingReceipts: Int,
        matchedReceipts: Int
    ) {
        let calendar = Calendar.current
        let now = Date()

        // Calculate date ranges
        let startOfDay = calendar.startOfDay(for: now)
        let startOfWeek = calendar.date(from: calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: now)) ?? now
        let startOfMonth = calendar.date(from: calendar.dateComponents([.year, .month], from: now)) ?? now

        // Calculate totals (expenses are negative amounts)
        let dailyTotal = transactions
            .filter { calendar.isDate($0.date, inSameDayAs: now) }
            .reduce(0) { $0 + abs($1.amount) }

        let weeklyTotal = transactions
            .filter { $0.date >= startOfWeek }
            .reduce(0) { $0 + abs($1.amount) }

        let monthlyTotal = transactions
            .filter { $0.date >= startOfMonth }
            .reduce(0) { $0 + abs($1.amount) }

        // Get recent transactions for widget display
        let recentTransactions = Array(transactions
            .sorted { $0.date > $1.date }
            .prefix(5)
            .map { transaction in
                WidgetTransactionData(
                    index: transaction.index,
                    merchant: transaction.merchant,
                    amount: transaction.amount,
                    date: transaction.date,
                    hasReceipt: transaction.hasReceipt,
                    category: transaction.category
                )
            })

        let data = WidgetSpendingDataModel(
            dailyTotal: dailyTotal,
            weeklyTotal: weeklyTotal,
            monthlyTotal: monthlyTotal,
            pendingReceipts: pendingReceipts,
            matchedReceipts: matchedReceipts,
            recentTransactions: recentTransactions,
            lastUpdated: now
        )

        saveSpendingData(data)
    }

    /// Save spending data to app group for widgets
    private func saveSpendingData(_ data: WidgetSpendingDataModel) {
        guard let encoded = try? JSONEncoder().encode(data) else {
            print("WidgetService: Failed to encode spending data")
            return
        }

        userDefaults?.set(encoded, forKey: dataKey)
        print("WidgetService: Saved spending data - Daily: $\(data.dailyTotal), Pending: \(data.pendingReceipts)")

        // Reload all widget timelines
        WidgetCenter.shared.reloadAllTimelines()
    }

    // MARK: - Update Specific Values

    /// Update pending receipts count
    func updatePendingCount(_ count: Int) {
        userDefaults?.set(count, forKey: "widget_pending_count")
        WidgetCenter.shared.reloadTimelines(ofKind: "InboxWidget")
        WidgetCenter.shared.reloadTimelines(ofKind: "QuickScanWidget")
    }

    /// Update authentication state
    func updateAuthenticationState(_ authenticated: Bool) {
        userDefaults?.set(authenticated, forKey: "widget_is_authenticated")
        WidgetCenter.shared.reloadAllTimelines()
    }

    // MARK: - Reload Widgets

    /// Force reload all widget timelines
    func reloadAllWidgets() {
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Reload specific widget
    func reloadWidget(kind: String) {
        WidgetCenter.shared.reloadTimelines(ofKind: kind)
    }
}

// MARK: - Internal Models (match widget extension models)

private struct WidgetSpendingDataModel: Codable {
    let dailyTotal: Double
    let weeklyTotal: Double
    let monthlyTotal: Double
    let pendingReceipts: Int
    let matchedReceipts: Int
    let recentTransactions: [WidgetTransactionData]
    let lastUpdated: Date
}

private struct WidgetTransactionData: Codable {
    let index: Int
    let merchant: String
    let amount: Double
    let date: Date
    let hasReceipt: Bool
    let category: String?
}

// MARK: - Deep Link Handler

enum DeepLink {
    case scan
    case inbox
    case transaction(id: Int)
    case dashboard
    case profile
    case settings

    init?(url: URL) {
        guard url.scheme == "tallyscanner" else { return nil }

        switch url.host {
        case "scan":
            self = .scan
        case "inbox":
            self = .inbox
        case "transaction":
            if let idString = url.pathComponents.last,
               let id = Int(idString) {
                self = .transaction(id: id)
            } else {
                return nil
            }
        case "dashboard":
            self = .dashboard
        case "profile":
            self = .profile
        case "settings":
            self = .settings
        default:
            return nil
        }
    }
}

/// Observable object to handle deep links from widgets
@MainActor
class DeepLinkHandler: ObservableObject {
    static let shared = DeepLinkHandler()

    @Published var pendingDeepLink: DeepLink?
    @Published var showScanner = false
    @Published var selectedTab: Tab = .home
    @Published var selectedTransactionId: Int?

    enum Tab: String {
        case home
        case scan
        case library
        case inbox
        case settings
    }

    private init() {}

    func handle(url: URL) {
        guard let deepLink = DeepLink(url: url) else { return }
        handle(deepLink: deepLink)
    }

    func handle(deepLink: DeepLink) {
        switch deepLink {
        case .scan:
            showScanner = true
            selectedTab = .scan
        case .inbox:
            selectedTab = .inbox
        case .transaction(let id):
            selectedTransactionId = id
            selectedTab = .library
        case .dashboard:
            selectedTab = .home
        case .profile, .settings:
            selectedTab = .settings
        }

        pendingDeepLink = nil
    }
}

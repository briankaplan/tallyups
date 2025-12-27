import Foundation
import WidgetKit

// MARK: - App Group Identifier
let appGroupIdentifier = "group.com.tallyups.scanner"

// MARK: - Widget Data Model
struct WidgetSpendingData: Codable {
    let dailyTotal: Double
    let weeklyTotal: Double
    let monthlyTotal: Double
    let pendingReceipts: Int
    let matchedReceipts: Int
    let recentTransactions: [WidgetTransaction]
    let lastUpdated: Date

    static var empty: WidgetSpendingData {
        WidgetSpendingData(
            dailyTotal: 0,
            weeklyTotal: 0,
            monthlyTotal: 0,
            pendingReceipts: 0,
            matchedReceipts: 0,
            recentTransactions: [],
            lastUpdated: Date()
        )
    }
}

struct WidgetTransaction: Codable, Identifiable {
    var id: String { String(index) }
    let index: Int
    let merchant: String
    let amount: Double
    let date: Date
    let hasReceipt: Bool
    let category: String?

    var formattedAmount: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }

    var shortMerchant: String {
        // Truncate long merchant names for widget display
        let cleaned = merchant
            .replacingOccurrences(of: "PURCHASE AUTHORIZED ON", with: "")
            .replacingOccurrences(of: "CHECKCARD", with: "")
            .trimmingCharacters(in: .whitespaces)

        if cleaned.count > 20 {
            return String(cleaned.prefix(17)) + "..."
        }
        return cleaned
    }
}

// MARK: - Widget Data Store
class WidgetDataStore {
    static let shared = WidgetDataStore()

    private let userDefaults: UserDefaults?
    private let dataKey = "widgetSpendingData"

    private init() {
        userDefaults = UserDefaults(suiteName: appGroupIdentifier)
    }

    /// Save spending data for widgets to access
    func saveSpendingData(_ data: WidgetSpendingData) {
        guard let encoded = try? JSONEncoder().encode(data) else { return }
        userDefaults?.set(encoded, forKey: dataKey)

        // Reload widgets
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Load spending data for widget display
    func loadSpendingData() -> WidgetSpendingData {
        guard let data = userDefaults?.data(forKey: dataKey),
              let decoded = try? JSONDecoder().decode(WidgetSpendingData.self, from: data) else {
            return .empty
        }
        return decoded
    }

    /// Save quick stat for simple widgets
    func saveQuickStat(key: String, value: Double) {
        userDefaults?.set(value, forKey: "widget_\(key)")
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Load quick stat
    func loadQuickStat(key: String) -> Double {
        userDefaults?.double(forKey: "widget_\(key)") ?? 0
    }

    /// Save pending receipts count
    func savePendingCount(_ count: Int) {
        userDefaults?.set(count, forKey: "widget_pending_count")
        WidgetCenter.shared.reloadAllTimelines()
    }

    /// Load pending receipts count
    func loadPendingCount() -> Int {
        userDefaults?.integer(forKey: "widget_pending_count") ?? 0
    }

    /// Check if user is authenticated
    var isAuthenticated: Bool {
        userDefaults?.bool(forKey: "widget_is_authenticated") ?? false
    }

    /// Save authentication state
    func saveAuthenticationState(_ authenticated: Bool) {
        userDefaults?.set(authenticated, forKey: "widget_is_authenticated")
    }
}

// MARK: - Timeline Provider Protocol
protocol TallyWidgetTimelineProvider {
    associatedtype Entry: TimelineEntry
    func getSnapshot(in context: Context, completion: @escaping (Entry) -> Void)
    func getTimeline(in context: Context, completion: @escaping (Timeline<Entry>) -> Void)
    func placeholder(in context: Context) -> Entry
}

// MARK: - Spending Timeline Entry
struct SpendingEntry: TimelineEntry {
    let date: Date
    let data: WidgetSpendingData
    let configuration: SpendingWidgetConfiguration

    static var placeholder: SpendingEntry {
        SpendingEntry(
            date: Date(),
            data: WidgetSpendingData(
                dailyTotal: 127.43,
                weeklyTotal: 856.21,
                monthlyTotal: 2341.89,
                pendingReceipts: 5,
                matchedReceipts: 142,
                recentTransactions: [
                    WidgetTransaction(index: 1, merchant: "Starbucks", amount: -5.75, date: Date(), hasReceipt: true, category: "Food & Dining"),
                    WidgetTransaction(index: 2, merchant: "Amazon", amount: -47.99, date: Date(), hasReceipt: false, category: "Shopping"),
                    WidgetTransaction(index: 3, merchant: "Uber", amount: -24.50, date: Date(), hasReceipt: true, category: "Transportation")
                ],
                lastUpdated: Date()
            ),
            configuration: SpendingWidgetConfiguration()
        )
    }
}

// MARK: - Quick Scan Timeline Entry
struct QuickScanEntry: TimelineEntry {
    let date: Date
    let pendingCount: Int
    let isAuthenticated: Bool

    static var placeholder: QuickScanEntry {
        QuickScanEntry(date: Date(), pendingCount: 3, isAuthenticated: true)
    }
}

// MARK: - Configuration Intent (Simple)
struct SpendingWidgetConfiguration {
    var showDailySpending: Bool = true
    var showWeeklySpending: Bool = true
    var showPendingReceipts: Bool = true
}

// MARK: - Deep Link URLs
enum WidgetDeepLink {
    case scan
    case inbox
    case transaction(id: Int)
    case dashboard

    var url: URL {
        switch self {
        case .scan:
            return URL(string: "tallyscanner://scan")!
        case .inbox:
            return URL(string: "tallyscanner://inbox")!
        case .transaction(let id):
            return URL(string: "tallyscanner://transaction/\(id)")!
        case .dashboard:
            return URL(string: "tallyscanner://dashboard")!
        }
    }
}

// MARK: - Formatting Helpers
extension Double {
    var currencyFormatted: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: abs(self))) ?? "$\(Int(abs(self)))"
    }

    var shortCurrencyFormatted: String {
        let absValue = abs(self)
        if absValue >= 1000 {
            let formatter = NumberFormatter()
            formatter.numberStyle = .decimal
            formatter.maximumFractionDigits = 1
            return "$\(formatter.string(from: NSNumber(value: absValue / 1000)) ?? "0")K"
        }
        return currencyFormatted
    }
}

extension Date {
    var widgetTimeAgo: String {
        let interval = Date().timeIntervalSince(self)

        if interval < 60 {
            return "Just now"
        } else if interval < 3600 {
            let minutes = Int(interval / 60)
            return "\(minutes)m ago"
        } else if interval < 86400 {
            let hours = Int(interval / 3600)
            return "\(hours)h ago"
        } else {
            let days = Int(interval / 86400)
            return "\(days)d ago"
        }
    }
}

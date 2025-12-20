import Foundation
import SwiftUI

@MainActor
class ScannerViewModel: ObservableObject {
    @Published var todayCount = 0
    @Published var weekCount = 0
    @Published var recentMerchants: [String] = []
    @Published var presetMerchant: String?

    init() {
        loadStats()
        loadRecentMerchants()
    }

    func loadStats() {
        // Load from UserDefaults for quick display
        todayCount = UserDefaults.standard.integer(forKey: "today_scan_count")
        weekCount = UserDefaults.standard.integer(forKey: "week_scan_count")

        // Refresh from server
        Task {
            await refreshStats()
        }
    }

    func loadRecentMerchants() {
        // Load cached recent merchants
        if let cached = UserDefaults.standard.stringArray(forKey: "recent_merchants") {
            recentMerchants = cached
        } else {
            // Default popular merchants
            recentMerchants = ["Starbucks", "Uber", "Amazon", "Target", "Whole Foods"]
        }

        // Refresh from server
        Task {
            await refreshRecentMerchants()
        }
    }

    func refreshStats() async {
        do {
            let stats = try await APIClient.shared.fetchLibraryStats()
            // Approximate today/week counts from total
            // In production, you'd have specific endpoints for this
            weekCount = stats.pendingReceipts + stats.matchedReceipts
        } catch {
            print("Failed to refresh stats: \(error)")
        }
    }

    func refreshRecentMerchants() async {
        do {
            let receipts = try await APIClient.shared.fetchReceipts(limit: 50)
            let merchants = receipts
                .compactMap { $0.merchant }
                .filter { !$0.isEmpty }

            // Get unique merchants, preserving order
            var seen = Set<String>()
            let unique = merchants.filter { merchant in
                if seen.contains(merchant) { return false }
                seen.insert(merchant)
                return true
            }

            recentMerchants = Array(unique.prefix(10))
            UserDefaults.standard.set(recentMerchants, forKey: "recent_merchants")
        } catch {
            print("Failed to refresh merchants: \(error)")
        }
    }

    func incrementTodayCount() {
        todayCount += 1
        weekCount += 1
        UserDefaults.standard.set(todayCount, forKey: "today_scan_count")
        UserDefaults.standard.set(weekCount, forKey: "week_scan_count")
    }

    func addRecentMerchant(_ merchant: String) {
        guard !merchant.isEmpty else { return }

        // Remove if exists, then add to front
        recentMerchants.removeAll { $0 == merchant }
        recentMerchants.insert(merchant, at: 0)

        // Keep only top 10
        if recentMerchants.count > 10 {
            recentMerchants = Array(recentMerchants.prefix(10))
        }

        UserDefaults.standard.set(recentMerchants, forKey: "recent_merchants")
    }
}

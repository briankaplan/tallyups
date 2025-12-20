import Foundation
import SwiftUI

@MainActor
class LibraryViewModel: ObservableObject {
    @Published var receipts: [Receipt] = []
    @Published var stats: LibraryStats?
    @Published var isLoading = false
    @Published var hasMore = true
    @Published var error: String?

    // Search & Filters
    @Published var searchQuery = ""
    @Published var filterStatus = "all"
    @Published var filterBusiness = "all"
    @Published var filterStartDate: Date?
    @Published var filterEndDate: Date?

    private var currentOffset = 0
    private let pageSize = 50
    private var searchTask: Task<Void, Never>?

    func loadReceipts() async {
        guard !isLoading else { return }

        isLoading = true
        currentOffset = 0
        hasMore = true
        error = nil

        do {
            receipts = try await APIClient.shared.fetchReceipts(
                offset: 0,
                limit: pageSize,
                search: searchQuery.isEmpty ? nil : searchQuery
            )

            hasMore = receipts.count >= pageSize
            currentOffset = receipts.count

            // Also load stats
            stats = try await APIClient.shared.fetchLibraryStats()
        } catch {
            self.error = error.localizedDescription
            print("Failed to load receipts: \(error)")
        }

        isLoading = false
    }

    func loadMore() async {
        guard !isLoading, hasMore else { return }

        isLoading = true

        do {
            let newReceipts = try await APIClient.shared.fetchReceipts(
                offset: currentOffset,
                limit: pageSize,
                search: searchQuery.isEmpty ? nil : searchQuery
            )

            receipts.append(contentsOf: newReceipts)
            hasMore = newReceipts.count >= pageSize
            currentOffset += newReceipts.count
        } catch {
            print("Failed to load more: \(error)")
        }

        isLoading = false
    }

    func refresh() async {
        await loadReceipts()
    }

    func search() async {
        // Cancel previous search
        searchTask?.cancel()

        // Debounce
        searchTask = Task {
            try? await Task.sleep(nanoseconds: 300_000_000) // 300ms

            guard !Task.isCancelled else { return }

            await loadReceipts()
        }
    }

    // MARK: - Filtering

    var filteredReceipts: [Receipt] {
        var filtered = receipts

        // Filter by status
        if filterStatus != "all" {
            filtered = filtered.filter { receipt in
                switch filterStatus {
                case "matched": return receipt.status == .matched
                case "unmatched": return receipt.status == .unmatched
                case "pending": return receipt.status == .pending
                default: return true
                }
            }
        }

        // Filter by business
        if filterBusiness != "all" {
            filtered = filtered.filter { $0.business == filterBusiness }
        }

        // Filter by date
        if let startDate = filterStartDate {
            filtered = filtered.filter { receipt in
                guard let date = receipt.date else { return true }
                return date >= startDate
            }
        }

        if let endDate = filterEndDate {
            filtered = filtered.filter { receipt in
                guard let date = receipt.date else { return true }
                return date <= endDate
            }
        }

        return filtered
    }

    // MARK: - Receipt Actions

    func deleteReceipt(_ receipt: Receipt) async {
        do {
            try await APIClient.shared.deleteReceipt(id: receipt.id)
            receipts.removeAll { $0.id == receipt.id }
        } catch {
            self.error = "Failed to delete receipt"
        }
    }

    func updateReceipt(_ receipt: Receipt, updates: [String: Any]) async -> Receipt? {
        do {
            let updated = try await APIClient.shared.updateReceipt(id: receipt.id, updates: updates)

            // Update local copy
            if let index = receipts.firstIndex(where: { $0.id == receipt.id }) {
                receipts[index] = updated
            }

            return updated
        } catch {
            self.error = "Failed to update receipt"
            return nil
        }
    }
}

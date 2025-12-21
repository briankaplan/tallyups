import Foundation
import SwiftUI

@MainActor
class TransactionsViewModel: ObservableObject {
    @Published var transactions: [Transaction] = []
    @Published var isLoading = true  // Start true to show loading state, not empty state
    @Published var hasMore = true
    @Published var error: String?
    @Published var hasLoaded = false  // Track if initial load completed

    // Search & Filters
    @Published var searchQuery = ""
    @Published var businessFilter: String?

    // Stats
    @Published var stats = TransactionStats()

    private var currentOffset = 0
    private let pageSize = 50

    struct TransactionStats {
        var total: Int = 0
        var withReceipt: Int = 0
        var missing: Int = 0
        var totalAmount: Double = 0
    }

    func loadTransactions() async {
        // Allow first load even when isLoading is true (initial state)
        guard !isLoading || !hasLoaded else { return }

        isLoading = true
        currentOffset = 0
        hasMore = true
        error = nil

        print("💳 TransactionsViewModel: Loading transactions...")

        do {
            transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: pageSize,
                business: businessFilter
            )

            print("💳 TransactionsViewModel: Loaded \(transactions.count) transactions")

            hasMore = transactions.count >= pageSize
            currentOffset = transactions.count

            // Calculate stats
            calculateStats()
        } catch {
            self.error = error.localizedDescription
            print("💳 TransactionsViewModel: Failed to load transactions: \(error)")
        }

        isLoading = false
        hasLoaded = true
    }

    func loadMore() async {
        guard !isLoading, hasMore else { return }

        isLoading = true

        do {
            let newTransactions = try await APIClient.shared.fetchTransactions(
                offset: currentOffset,
                limit: pageSize,
                business: businessFilter
            )

            transactions.append(contentsOf: newTransactions)
            hasMore = newTransactions.count >= pageSize
            currentOffset += newTransactions.count

            // Recalculate stats
            calculateStats()
        } catch {
            print("💳 TransactionsViewModel: Failed to load more: \(error)")
        }

        isLoading = false
    }

    func refresh() async {
        await loadTransactions()
    }

    // MARK: - Filtering

    var filteredTransactions: [Transaction] {
        var filtered = transactions

        // Filter by search query
        if !searchQuery.isEmpty {
            filtered = filtered.filter { transaction in
                transaction.merchant.localizedCaseInsensitiveContains(searchQuery) ||
                (transaction.notes?.localizedCaseInsensitiveContains(searchQuery) ?? false) ||
                (transaction.category?.localizedCaseInsensitiveContains(searchQuery) ?? false)
            }
        }

        return filtered
    }

    // MARK: - Stats

    private func calculateStats() {
        stats.total = transactions.count
        stats.withReceipt = transactions.filter { $0.hasReceipt }.count
        stats.missing = transactions.filter { !$0.hasReceipt }.count
        stats.totalAmount = transactions.reduce(0) { $0 + abs($1.amount) }
    }

    // MARK: - Transaction Actions

    /// Link a receipt to a transaction
    func matchReceipt(transactionIndex: Int, receiptId: String) async -> Bool {
        print("💳 TransactionsViewModel: Matching transaction \(transactionIndex) with receipt \(receiptId)")

        do {
            let success = try await APIClient.shared.linkReceiptToTransaction(
                transactionIndex: transactionIndex,
                receiptId: receiptId
            )

            if success {
                // Update local state
                if let index = transactions.firstIndex(where: { $0.index == transactionIndex }) {
                    transactions[index].hasReceipt = true
                    transactions[index].receiptCount += 1
                }
                calculateStats()
                print("💳 TransactionsViewModel: Successfully matched receipt")
            }

            return success
        } catch {
            self.error = error.localizedDescription
            print("💳 TransactionsViewModel: Match failed: \(error)")
            return false
        }
    }

    /// Unlink a receipt from a transaction
    func unmatchReceipt(transactionIndex: Int, receiptId: String) async -> Bool {
        print("💳 TransactionsViewModel: Unlinking receipt \(receiptId) from transaction \(transactionIndex)")

        do {
            let success = try await APIClient.shared.unlinkReceiptFromTransaction(
                transactionIndex: transactionIndex,
                receiptId: receiptId
            )

            if success {
                // Update local state
                if let index = transactions.firstIndex(where: { $0.index == transactionIndex }) {
                    transactions[index].receiptCount = max(0, transactions[index].receiptCount - 1)
                    transactions[index].hasReceipt = transactions[index].receiptCount > 0
                }
                calculateStats()
                print("💳 TransactionsViewModel: Successfully unlinked receipt")
            }

            return success
        } catch {
            self.error = error.localizedDescription
            print("💳 TransactionsViewModel: Unlink failed: \(error)")
            return false
        }
    }

    /// Exclude a transaction from requiring a receipt
    func excludeTransaction(transactionIndex: Int, reason: String? = nil) async -> Bool {
        print("💳 TransactionsViewModel: Excluding transaction \(transactionIndex)")

        do {
            let success = try await APIClient.shared.excludeTransaction(
                transactionIndex: transactionIndex,
                reason: reason
            )

            if success {
                // Update local state
                if let index = transactions.firstIndex(where: { $0.index == transactionIndex }) {
                    transactions[index].status = .excluded
                }
                calculateStats()
                print("💳 TransactionsViewModel: Successfully excluded transaction")
            }

            return success
        } catch {
            self.error = error.localizedDescription
            print("💳 TransactionsViewModel: Exclude failed: \(error)")
            return false
        }
    }

    /// Unexclude a transaction
    func unexcludeTransaction(transactionIndex: Int) async -> Bool {
        print("💳 TransactionsViewModel: Unexcluding transaction \(transactionIndex)")

        do {
            let success = try await APIClient.shared.unexcludeTransaction(transactionIndex: transactionIndex)

            if success {
                // Update local state
                if let index = transactions.firstIndex(where: { $0.index == transactionIndex }) {
                    transactions[index].status = transactions[index].hasReceipt ? .matched : .unmatched
                }
                calculateStats()
                print("💳 TransactionsViewModel: Successfully unexcluded transaction")
            }

            return success
        } catch {
            self.error = error.localizedDescription
            print("💳 TransactionsViewModel: Unexclude failed: \(error)")
            return false
        }
    }
}

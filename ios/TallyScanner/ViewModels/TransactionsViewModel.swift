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
    @Published var cardFilter: String?  // Filter by card/account

    // Per-user business types (dynamic from API)
    @Published var businessTypes: [APIClient.BusinessType] = []
    @Published var isLoadingBusinessTypes = false

    // Unique cards/accounts from loaded transactions
    @Published var uniqueCards: [CardAccount] = []

    // Stats
    @Published var stats = TransactionStats()

    /// Represents a unique card/account for filtering
    struct CardAccount: Identifiable, Hashable {
        var id: String { accountId ?? cardLast4 ?? UUID().uuidString }
        let accountId: String?
        let accountName: String?
        let cardLast4: String?
        let cardType: String?
        let source: String?
        var transactionCount: Int = 0

        var displayName: String {
            if let last4 = cardLast4, !last4.isEmpty {
                let bankName = accountName ?? "Card"
                return "\(bankName) ••\(last4)"
            } else if let src = source?.lowercased(), src == "manual" {
                return "Manual Entry"
            } else if let name = accountName, !name.isEmpty {
                return name
            }
            return "Unknown"
        }

        var shortName: String {
            if let last4 = cardLast4, !last4.isEmpty {
                return "••\(last4)"
            }
            return displayName.prefix(8).description
        }

        var icon: String {
            guard let type = cardType?.lowercased() else {
                return source?.lowercased() == "manual" ? "pencil.circle" : "creditcard"
            }
            switch type {
            case "credit": return "creditcard.fill"
            case "debit": return "creditcard"
            case "checking": return "banknote"
            case "savings": return "building.columns"
            default: return "creditcard"
            }
        }
    }

    private var currentOffset = 0
    private let pageSize = 50

    struct TransactionStats {
        var total: Int = 0
        var withReceipt: Int = 0
        var missing: Int = 0
        var totalAmount: Double = 0
    }

    // MARK: - Business Types

    /// Fetch user's custom business types from API
    func loadBusinessTypes() async {
        guard !isLoadingBusinessTypes else { return }

        isLoadingBusinessTypes = true

        do {
            let types = try await APIClient.shared.fetchBusinessTypes()
            businessTypes = types
            print("💼 TransactionsViewModel: Loaded \(types.count) business types")
        } catch {
            print("💼 TransactionsViewModel: Failed to load business types: \(error)")
            // Fallback to defaults if API fails
            businessTypes = defaultBusinessTypes
        }

        isLoadingBusinessTypes = false
    }

    /// Default business types as fallback
    private var defaultBusinessTypes: [APIClient.BusinessType] {
        [
            APIClient.BusinessType(
                id: 0, name: "Personal", displayName: "Personal",
                color: "#00FF88", icon: "person.fill", isDefault: true, sortOrder: 1
            ),
            APIClient.BusinessType(
                id: 1, name: "Business", displayName: "Business",
                color: "#4A90D9", icon: "briefcase.fill", isDefault: false, sortOrder: 2
            )
        ]
    }

    /// Get color for a business type name
    func colorForBusiness(_ name: String?) -> Color {
        guard let name = name else { return .gray }
        if let type = businessTypes.first(where: { $0.name.lowercased() == name.lowercased() || $0.displayName.lowercased() == name.lowercased() }) {
            return type.swiftUIColor
        }
        return .gray
    }

    /// Get short name for display
    func shortNameForBusiness(_ name: String) -> String {
        if let type = businessTypes.first(where: { $0.name.lowercased() == name.lowercased() || $0.displayName.lowercased() == name.lowercased() }) {
            // Use abbreviated form for long names
            if type.displayName.count > 10 {
                return String(type.displayName.split(separator: " ").map { $0.prefix(1) }.joined())
            }
            return type.displayName
        }
        return name
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

        // Filter by card/account
        if let cardFilter = cardFilter, cardFilter != "all" {
            filtered = filtered.filter { transaction in
                if let accountId = transaction.accountId {
                    return accountId == cardFilter
                } else if let cardLast4 = transaction.cardLast4 {
                    return cardLast4 == cardFilter
                } else if cardFilter == "manual" {
                    return transaction.source?.lowercased() == "manual"
                }
                return false
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

        // Extract unique cards/accounts
        extractUniqueCards()

        // Update widget data
        updateWidgetData()

        // Update Spotlight index
        updateSpotlightIndex()
    }

    /// Extract unique card/accounts from loaded transactions
    private func extractUniqueCards() {
        var cardDict: [String: CardAccount] = [:]

        for transaction in transactions {
            // Create a unique key for each card
            let key: String
            if let accountId = transaction.accountId, !accountId.isEmpty {
                key = accountId
            } else if let last4 = transaction.cardLast4, !last4.isEmpty {
                key = "card_\(last4)"
            } else if transaction.source?.lowercased() == "manual" {
                key = "manual"
            } else {
                continue // Skip transactions without card info
            }

            if var existing = cardDict[key] {
                existing.transactionCount += 1
                cardDict[key] = existing
            } else {
                cardDict[key] = CardAccount(
                    accountId: transaction.accountId,
                    accountName: transaction.accountName,
                    cardLast4: transaction.cardLast4,
                    cardType: transaction.cardType,
                    source: transaction.source,
                    transactionCount: 1
                )
            }
        }

        // Sort by transaction count (most used first)
        uniqueCards = cardDict.values.sorted { $0.transactionCount > $1.transactionCount }
    }

    /// Update widget spending data with current transactions
    private func updateWidgetData() {
        WidgetService.shared.updateSpendingData(
            transactions: transactions,
            pendingReceipts: stats.missing,
            matchedReceipts: stats.withReceipt
        )
    }

    /// Index transactions for Spotlight search
    private func updateSpotlightIndex() {
        Task {
            await SpotlightService.shared.indexTransactions(transactions)
        }
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

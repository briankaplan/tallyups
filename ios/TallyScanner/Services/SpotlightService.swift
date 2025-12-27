import Foundation
import CoreSpotlight
import MobileCoreServices
import UniformTypeIdentifiers

/// Service for indexing receipts and transactions for iOS Spotlight search
@MainActor
class SpotlightService: ObservableObject {
    static let shared = SpotlightService()

    private let domainIdentifier = "com.tallyups.scanner.receipts"
    private let searchableIndex = CSSearchableIndex.default()

    private init() {}

    // MARK: - Index Transactions

    /// Index all transactions for Spotlight search
    func indexTransactions(_ transactions: [Transaction]) async {
        let items = transactions.compactMap { createSearchableItem(from: $0) }

        do {
            try await searchableIndex.indexSearchableItems(items)
            print("SpotlightService: Indexed \(items.count) transactions")
        } catch {
            print("SpotlightService: Failed to index transactions: \(error)")
        }
    }

    /// Index a single transaction
    func indexTransaction(_ transaction: Transaction) async {
        guard let item = createSearchableItem(from: transaction) else { return }

        do {
            try await searchableIndex.indexSearchableItems([item])
            print("SpotlightService: Indexed transaction \(transaction.index)")
        } catch {
            print("SpotlightService: Failed to index transaction: \(error)")
        }
    }

    /// Remove a transaction from Spotlight index
    func removeTransaction(_ transaction: Transaction) async {
        let identifier = "transaction-\(transaction.index)"

        do {
            try await searchableIndex.deleteSearchableItems(withIdentifiers: [identifier])
            print("SpotlightService: Removed transaction \(transaction.index) from index")
        } catch {
            print("SpotlightService: Failed to remove transaction: \(error)")
        }
    }

    /// Remove all indexed items
    func removeAllIndexedItems() async {
        do {
            try await searchableIndex.deleteSearchableItems(withDomainIdentifiers: [domainIdentifier])
            print("SpotlightService: Removed all indexed items")
        } catch {
            print("SpotlightService: Failed to remove all items: \(error)")
        }
    }

    // MARK: - Create Searchable Item

    private func createSearchableItem(from transaction: Transaction) -> CSSearchableItem? {
        let identifier = "transaction-\(transaction.index)"

        let attributeSet = CSSearchableItemAttributeSet(contentType: .content)

        // Title: Merchant name
        attributeSet.title = cleanMerchantName(transaction.merchant)

        // Content description
        var description = transaction.formattedAmount
        if let category = transaction.category {
            description += " - \(category)"
        }
        if let business = transaction.business {
            description += " (\(business))"
        }
        attributeSet.contentDescription = description

        // Date
        attributeSet.contentCreationDate = transaction.date
        attributeSet.contentModificationDate = transaction.date

        // Keywords for search
        var keywords = [
            cleanMerchantName(transaction.merchant),
            transaction.formattedDate,
            transaction.formattedAmount
        ]

        if let category = transaction.category {
            keywords.append(category)
        }
        if let business = transaction.business {
            keywords.append(business)
        }
        if let notes = transaction.notes {
            keywords.append(notes)
        }

        // Receipt status
        if transaction.hasReceipt {
            keywords.append("receipt")
            keywords.append("matched")
        } else {
            keywords.append("missing")
            keywords.append("pending")
        }

        attributeSet.keywords = keywords

        // Display name
        attributeSet.displayName = "\(cleanMerchantName(transaction.merchant)) - \(transaction.formattedAmount)"

        // Thumbnail if available
        if let receiptUrl = transaction.r2Url ?? transaction.receiptUrl,
           let url = URL(string: receiptUrl),
           let data = try? Data(contentsOf: url) {
            attributeSet.thumbnailData = data
        }

        // Related unique identifier
        attributeSet.relatedUniqueIdentifier = identifier

        // Ranking
        attributeSet.rankingHint = NSNumber(value: Date().timeIntervalSince(transaction.date))

        let item = CSSearchableItem(
            uniqueIdentifier: identifier,
            domainIdentifier: domainIdentifier,
            attributeSet: attributeSet
        )

        // Expiration (keep for 1 year)
        item.expirationDate = Calendar.current.date(byAdding: .year, value: 1, to: Date())

        return item
    }

    // MARK: - Index Receipts

    /// Index receipts for Spotlight search
    func indexReceipts(_ receipts: [Receipt]) async {
        let items = receipts.compactMap { createSearchableItem(from: $0) }

        do {
            try await searchableIndex.indexSearchableItems(items)
            print("SpotlightService: Indexed \(items.count) receipts")
        } catch {
            print("SpotlightService: Failed to index receipts: \(error)")
        }
    }

    private func createSearchableItem(from receipt: Receipt) -> CSSearchableItem? {
        let identifier = "receipt-\(receipt.id)"

        let attributeSet = CSSearchableItemAttributeSet(contentType: .image)

        // Title
        attributeSet.title = receipt.merchant ?? "Receipt"

        // Description
        var description = ""
        if let amount = receipt.amount {
            let formatter = NumberFormatter()
            formatter.numberStyle = .currency
            formatter.currencyCode = "USD"
            description = formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
        }
        if let date = receipt.date {
            let dateFormatter = DateFormatter()
            dateFormatter.dateStyle = .medium
            description += " - \(dateFormatter.string(from: date))"
        }
        attributeSet.contentDescription = description

        // Keywords
        var keywords = ["receipt"]
        if let merchant = receipt.merchant {
            keywords.append(merchant)
        }

        attributeSet.keywords = keywords

        let item = CSSearchableItem(
            uniqueIdentifier: identifier,
            domainIdentifier: domainIdentifier,
            attributeSet: attributeSet
        )

        return item
    }

    // MARK: - Handle Spotlight Selection

    /// Handle when user taps a Spotlight result
    /// Returns the transaction index if it's a transaction result
    func handleSpotlightActivity(_ activity: NSUserActivity) -> Int? {
        guard activity.activityType == CSSearchableItemActionType,
              let identifier = activity.userInfo?[CSSearchableItemActivityIdentifier] as? String else {
            return nil
        }

        if identifier.hasPrefix("transaction-") {
            let indexString = identifier.replacingOccurrences(of: "transaction-", with: "")
            return Int(indexString)
        }

        return nil
    }

    // MARK: - Helpers

    private func cleanMerchantName(_ merchant: String) -> String {
        var cleaned = merchant
            .replacingOccurrences(of: "PURCHASE AUTHORIZED ON", with: "")
            .replacingOccurrences(of: "CHECKCARD", with: "")
            .replacingOccurrences(of: "RECURRING", with: "")
            .trimmingCharacters(in: .whitespaces)

        // Remove date patterns from start
        let datePattern = #"^\d{2}/\d{2}\s*"#
        if let regex = try? NSRegularExpression(pattern: datePattern) {
            cleaned = regex.stringByReplacingMatches(
                in: cleaned,
                range: NSRange(cleaned.startIndex..., in: cleaned),
                withTemplate: ""
            )
        }

        return cleaned.trimmingCharacters(in: .whitespaces)
    }
}

import Foundation

struct Transaction: Identifiable, Codable, Hashable {
    var id: String { String(index) }
    let index: Int
    var merchant: String
    var amount: Double
    var date: Date
    var category: String?
    var notes: String?
    var business: String?
    var receiptCount: Int
    var hasReceipt: Bool
    var status: TransactionStatus

    enum TransactionStatus: String, Codable {
        case pending
        case matched
        case unmatched
        case excluded

        var displayName: String {
            switch self {
            case .pending: return "Pending"
            case .matched: return "Matched"
            case .unmatched: return "Unmatched"
            case .excluded: return "Excluded"
            }
        }
    }

    enum CodingKeys: String, CodingKey {
        case index = "_index"
        case merchant
        case amount
        case date
        case category
        case notes
        case business = "business_type"
        case receiptCount = "receipt_count"
        case hasReceipt = "has_receipt"
        case status
    }

    var formattedAmount: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }

    var formattedDate: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter.string(from: date)
    }
}

// MARK: - API Response Types
struct TransactionListResponse: Codable {
    let transactions: [Transaction]
    let total: Int
    let offset: Int
    let limit: Int
}

struct ReceiptListResponse: Codable {
    let receipts: [Receipt]
    let total: Int?
    let offset: Int?
    let limit: Int?
}

struct IncomingReceiptListResponse: Codable {
    let receipts: [IncomingReceipt]
    let total: Int?
}

struct UploadResponse: Codable {
    let success: Bool
    let receiptId: String?
    let message: String?
    let imageUrl: String?
    let extractedData: OCRResult?

    enum CodingKeys: String, CodingKey {
        case success
        case receiptId = "receipt_id"
        case message
        case imageUrl = "r2_url"
        case extractedData = "extracted_data"
    }
}

struct InboxStats: Codable {
    let pending: Int
    let accepted: Int
    let rejected: Int
    let total: Int

    enum CodingKeys: String, CodingKey {
        case pending = "pending_count"
        case accepted = "accepted_count"
        case rejected = "rejected_count"
        case total = "total_count"
    }
}

struct HealthResponse: Codable {
    let ok: Bool
    let version: String?
    let uptime: Double?
    let poolSize: Int?
    let activeConnections: Int?

    enum CodingKeys: String, CodingKey {
        case ok
        case version
        case uptime
        case poolSize = "pool_size"
        case activeConnections = "active_connections"
    }
}

// MARK: - Contact (for attendee matching)
struct Contact: Identifiable, Codable {
    let id: String
    var name: String
    var email: String?
    var phone: String?
    var company: String?
    var tags: [String]?

    var displayName: String {
        name
    }

    var initials: String {
        let parts = name.split(separator: " ")
        if parts.count >= 2 {
            return String(parts[0].prefix(1)) + String(parts[1].prefix(1))
        }
        return String(name.prefix(2)).uppercased()
    }
}

struct ContactListResponse: Codable {
    let contacts: [Contact]
    let total: Int?
}

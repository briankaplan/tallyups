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
    var receiptCount: Int = 0
    var hasReceipt: Bool = false
    var status: TransactionStatus = .pending
    var receiptUrl: String?
    var r2Url: String?

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
        case merchant = "chase_description"  // Backend uses chase_description
        case amount = "chase_amount"          // Backend uses chase_amount
        case date = "chase_date"              // Backend uses chase_date
        case category
        case notes
        case business = "business_type"
        case receiptCount = "receipt_count"
        case hasReceipt = "has_receipt"
        case status = "review_status"
        case receiptUrl = "receipt_url"
        case r2Url = "r2_url"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        index = try container.decode(Int.self, forKey: .index)
        merchant = try container.decode(String.self, forKey: .merchant)

        // Handle amount - can be Double or String
        if let doubleAmount = try? container.decode(Double.self, forKey: .amount) {
            amount = doubleAmount
        } else if let stringAmount = try? container.decode(String.self, forKey: .amount),
                  let parsed = Double(stringAmount) {
            amount = parsed
        } else {
            amount = 0
        }

        // Handle date - can be various formats
        if let dateValue = try? container.decode(Date.self, forKey: .date) {
            date = dateValue
        } else if let dateString = try? container.decode(String.self, forKey: .date) {
            let formatters = [
                "yyyy-MM-dd",
                "yyyy-MM-dd'T'HH:mm:ss",
                "yyyy-MM-dd HH:mm:ss"
            ]
            var parsedDate: Date?
            for format in formatters {
                let formatter = DateFormatter()
                formatter.dateFormat = format
                formatter.locale = Locale(identifier: "en_US_POSIX")
                if let d = formatter.date(from: dateString) {
                    parsedDate = d
                    break
                }
            }
            date = parsedDate ?? Date()
        } else {
            date = Date()
        }

        category = try container.decodeIfPresent(String.self, forKey: .category)
        notes = try container.decodeIfPresent(String.self, forKey: .notes)
        business = try container.decodeIfPresent(String.self, forKey: .business)
        receiptUrl = try container.decodeIfPresent(String.self, forKey: .receiptUrl)
        r2Url = try container.decodeIfPresent(String.self, forKey: .r2Url)

        // Receipt count - derive from receipt_url if not provided
        if let count = try? container.decode(Int.self, forKey: .receiptCount) {
            receiptCount = count
        } else {
            receiptCount = (receiptUrl != nil || r2Url != nil) ? 1 : 0
        }

        // Has receipt - derive from receipt_url if not provided
        if let has = try? container.decode(Bool.self, forKey: .hasReceipt) {
            hasReceipt = has
        } else {
            hasReceipt = receiptUrl != nil || r2Url != nil
        }

        // Status - handle review_status from backend
        if let statusString = try? container.decode(String.self, forKey: .status) {
            switch statusString.lowercased() {
            case "matched", "verified", "complete":
                status = .matched
            case "excluded", "exclude":
                status = .excluded
            case "unmatched", "needs_review", "missing":
                status = .unmatched
            default:
                status = hasReceipt ? .matched : .pending
            }
        } else {
            status = hasReceipt ? .matched : .pending
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(index, forKey: .index)
        try container.encode(merchant, forKey: .merchant)
        try container.encode(amount, forKey: .amount)
        try container.encode(date, forKey: .date)
        try container.encodeIfPresent(category, forKey: .category)
        try container.encodeIfPresent(notes, forKey: .notes)
        try container.encodeIfPresent(business, forKey: .business)
        try container.encode(receiptCount, forKey: .receiptCount)
        try container.encode(hasReceipt, forKey: .hasReceipt)
        try container.encode(status.rawValue, forKey: .status)
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
    let r2Url: String?
    let receiptImageUrl: String?
    let thumbnailUrl: String?
    let extractedData: OCRResult?
    let merchant: String?
    let amount: Double?
    let date: String?

    enum CodingKeys: String, CodingKey {
        case success
        case receiptId = "receipt_id"
        case message
        case r2Url = "r2_url"
        case receiptImageUrl = "receipt_image_url"
        case thumbnailUrl = "thumbnail_url"
        case extractedData = "ocr"
        case merchant
        case amount
        case date
    }

    /// Best available image URL (prefers R2)
    var imageUrl: String? {
        r2Url ?? receiptImageUrl
    }
}

struct InboxStats: Codable {
    var pending: Int
    var accepted: Int
    var rejected: Int
    var total: Int

    // Nested counts structure from API
    struct Counts: Codable {
        var pending: Int?
        var matched: Int?
        var rejected: Int?
        var auto_rejected: Int?
        var spam: Int?
    }

    enum CodingKeys: String, CodingKey {
        case pending = "pending_count"
        case accepted = "accepted_count"
        case rejected = "rejected_count"
        case total = "total_count"
        case counts
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        // Try nested counts first (from /api/incoming/receipts response)
        if let counts = try? container.decode(Counts.self, forKey: .counts) {
            pending = counts.pending ?? 0
            accepted = counts.matched ?? 0
            rejected = (counts.rejected ?? 0) + (counts.auto_rejected ?? 0)
            total = pending + accepted + rejected
        } else {
            // Direct decoding fallback
            pending = (try? container.decode(Int.self, forKey: .pending)) ?? 0
            accepted = (try? container.decode(Int.self, forKey: .accepted)) ?? 0
            rejected = (try? container.decode(Int.self, forKey: .rejected)) ?? 0
            total = (try? container.decode(Int.self, forKey: .total)) ?? (pending + accepted + rejected)
        }
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(pending, forKey: .pending)
        try container.encode(accepted, forKey: .accepted)
        try container.encode(rejected, forKey: .rejected)
        try container.encode(total, forKey: .total)
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

// MARK: - Calendar Event (for context matching)
struct CalendarEvent: Identifiable, Codable {
    var id: String { eventId }
    let eventId: String
    var title: String
    var startTime: Date?
    var endTime: Date?
    var location: String?
    var attendees: [String]?
    var description: String?

    enum CodingKeys: String, CodingKey {
        case eventId = "event_id"
        case title
        case startTime = "start_time"
        case endTime = "end_time"
        case location
        case attendees
        case description
    }

    var formattedTime: String {
        guard let start = startTime else { return "" }
        let formatter = DateFormatter()
        formatter.timeStyle = .short
        return formatter.string(from: start)
    }

    var attendeeNames: [String] {
        attendees ?? []
    }
}

// MARK: - Scan History Item
struct ScanHistoryItem: Identifiable, Codable {
    let id: UUID
    let imageData: Data
    var merchant: String?
    var amount: Double?
    var date: Date
    var status: ScanStatus
    var r2Url: String?
    var receiptId: String?
    var ocrResult: OCRResult?
    let scannedAt: Date

    enum ScanStatus: String, Codable {
        case pending
        case uploading
        case uploaded
        case failed

        var icon: String {
            switch self {
            case .pending: return "clock.fill"
            case .uploading: return "arrow.up.circle.fill"
            case .uploaded: return "checkmark.circle.fill"
            case .failed: return "xmark.circle.fill"
            }
        }

        var color: String {
            switch self {
            case .pending: return "orange"
            case .uploading: return "blue"
            case .uploaded: return "green"
            case .failed: return "red"
            }
        }
    }

    var formattedAmount: String {
        guard let amount = amount else { return "" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }
}

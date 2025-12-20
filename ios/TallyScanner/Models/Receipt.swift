import Foundation

struct Receipt: Identifiable, Codable, Hashable {
    let id: String
    var merchant: String?
    var amount: Double?
    var date: Date?
    var category: String?
    var notes: String?
    var imageURL: String?
    var thumbnailURL: String?
    var status: ReceiptStatus
    var source: String?
    var business: String?
    var ocrConfidence: Double?
    var createdAt: Date
    var updatedAt: Date?

    // Transaction link
    var transactionIndex: Int?

    enum ReceiptStatus: String, Codable {
        case pending
        case processing
        case matched
        case unmatched
        case rejected
        case accepted

        var displayName: String {
            switch self {
            case .pending: return "Pending"
            case .processing: return "Processing"
            case .matched: return "Matched"
            case .unmatched: return "Unmatched"
            case .rejected: return "Rejected"
            case .accepted: return "Accepted"
            }
        }

        var color: String {
            switch self {
            case .pending: return "yellow"
            case .processing: return "blue"
            case .matched: return "green"
            case .unmatched: return "orange"
            case .rejected: return "red"
            case .accepted: return "green"
            }
        }
    }

    enum CodingKeys: String, CodingKey {
        case id
        case merchant
        case amount
        case date
        case category
        case notes
        case imageURL = "image_url"
        case thumbnailURL = "thumbnail_url"
        case status
        case source
        case business
        case ocrConfidence = "ocr_confidence"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case transactionIndex = "transaction_index"
    }

    var formattedAmount: String {
        guard let amount = amount else { return "$0.00" }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }

    var formattedDate: String {
        guard let date = date else { return "Unknown date" }
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none
        return formatter.string(from: date)
    }
}

// MARK: - Incoming Receipt (from Gmail)
struct IncomingReceipt: Identifiable, Codable {
    let id: String
    var subject: String?
    var sender: String?
    var senderEmail: String?
    var receivedDate: Date?
    var merchant: String?
    var amount: Double?
    var date: Date?
    var imageURL: String?
    var thumbnailURL: String?
    var status: String
    var emailAccount: String?
    var extractedData: ExtractedData?

    struct ExtractedData: Codable {
        var merchant: String?
        var amount: Double?
        var date: String?
        var items: [String]?
        var confidence: Double?
    }

    enum CodingKeys: String, CodingKey {
        case id
        case subject
        case sender
        case senderEmail = "sender_email"
        case receivedDate = "received_date"
        case merchant
        case amount
        case date
        case imageURL = "image_url"
        case thumbnailURL = "thumbnail_url"
        case status
        case emailAccount = "email_account"
        case extractedData = "extracted_data"
    }
}

// MARK: - Upload Item (for queue)
struct UploadItem: Identifiable, Codable {
    let id: UUID
    let imageData: Data
    var merchant: String?
    var amount: Double?
    var date: Date?
    var category: String?
    var notes: String?
    var business: String?
    var latitude: Double?
    var longitude: Double?
    var source: String
    var status: UploadStatus
    var createdAt: Date
    var retryCount: Int
    var lastError: String?

    enum UploadStatus: String, Codable {
        case pending
        case uploading
        case completed
        case failed
    }

    init(
        imageData: Data,
        merchant: String? = nil,
        amount: Double? = nil,
        date: Date? = nil,
        category: String? = nil,
        notes: String? = nil,
        business: String? = nil,
        latitude: Double? = nil,
        longitude: Double? = nil,
        source: String = "ios_scanner"
    ) {
        self.id = UUID()
        self.imageData = imageData
        self.merchant = merchant
        self.amount = amount
        self.date = date
        self.category = category
        self.notes = notes
        self.business = business
        self.latitude = latitude
        self.longitude = longitude
        self.source = source
        self.status = .pending
        self.createdAt = Date()
        self.retryCount = 0
        self.lastError = nil
    }
}

// MARK: - OCR Result
struct OCRResult: Codable {
    var merchant: String?
    var amount: Double?
    var date: String?
    var items: [LineItem]?
    var subtotal: Double?
    var tax: Double?
    var total: Double?
    var paymentMethod: String?
    var confidence: Double?
    var raw: String?

    struct LineItem: Codable {
        var description: String
        var quantity: Int?
        var price: Double?
    }

    enum CodingKeys: String, CodingKey {
        case merchant
        case amount
        case date
        case items
        case subtotal
        case tax
        case total
        case paymentMethod = "payment_method"
        case confidence
        case raw
    }
}

// MARK: - Library Stats
struct LibraryStats: Codable {
    var totalReceipts: Int
    var pendingReceipts: Int
    var matchedReceipts: Int
    var unmatchedReceipts: Int
    var totalAmount: Double

    enum CodingKeys: String, CodingKey {
        case totalReceipts = "total_receipts"
        case pendingReceipts = "pending_receipts"
        case matchedReceipts = "matched_receipts"
        case unmatchedReceipts = "unmatched_receipts"
        case totalAmount = "total_amount"
    }
}

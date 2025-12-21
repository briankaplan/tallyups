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
    var createdAt: Date?
    var updatedAt: Date?

    // Transaction link
    var transactionIndex: Int?

    // Additional fields from API
    var merchantName: String?
    var aiNotes: String?
    var verificationStatus: String?

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
        case merchantName = "merchant_name"
        case amount
        case date
        case category
        case notes
        case aiNotes = "ai_notes"
        case imageURL = "receipt_url"
        case thumbnailURL = "thumbnail_url"
        case status
        case source
        case business = "business_type"
        case ocrConfidence = "ocr_confidence"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
        case transactionIndex = "transaction_id"
        case verificationStatus = "verification_status"
    }

    // Custom decoder to handle edge cases (empty dates, flexible types)
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        // ID can be String or Int
        if let intId = try? container.decode(Int.self, forKey: .id) {
            id = String(intId)
        } else {
            id = try container.decode(String.self, forKey: .id)
        }

        merchant = try? container.decode(String.self, forKey: .merchant)
        merchantName = try? container.decode(String.self, forKey: .merchantName)

        // Amount can be Double or String
        if let doubleAmount = try? container.decode(Double.self, forKey: .amount) {
            amount = doubleAmount
        } else if let stringAmount = try? container.decode(String.self, forKey: .amount),
                  let parsed = Double(stringAmount) {
            amount = parsed
        } else {
            amount = nil
        }

        // Date: handle Date, String (including empty), or nil
        date = Receipt.decodeOptionalDate(from: container, forKey: .date)
        createdAt = Receipt.decodeOptionalDate(from: container, forKey: .createdAt)
        updatedAt = Receipt.decodeOptionalDate(from: container, forKey: .updatedAt)

        category = try? container.decode(String.self, forKey: .category)
        notes = try? container.decode(String.self, forKey: .notes)
        aiNotes = try? container.decode(String.self, forKey: .aiNotes)
        imageURL = try? container.decode(String.self, forKey: .imageURL)
        thumbnailURL = try? container.decode(String.self, forKey: .thumbnailURL)
        source = try? container.decode(String.self, forKey: .source)
        business = try? container.decode(String.self, forKey: .business)
        ocrConfidence = try? container.decode(Double.self, forKey: .ocrConfidence)
        verificationStatus = try? container.decode(String.self, forKey: .verificationStatus)

        // Transaction ID can be Int or String
        if let intIndex = try? container.decode(Int.self, forKey: .transactionIndex) {
            transactionIndex = intIndex
        } else if let stringIndex = try? container.decode(String.self, forKey: .transactionIndex),
                  let parsed = Int(stringIndex) {
            transactionIndex = parsed
        } else {
            transactionIndex = nil
        }

        // Status: default to matched if decoding fails
        status = (try? container.decode(ReceiptStatus.self, forKey: .status)) ?? .matched
    }

    // Helper to decode dates that might be empty strings or null
    private static func decodeOptionalDate(from container: KeyedDecodingContainer<CodingKeys>, forKey key: CodingKeys) -> Date? {
        // Try to decode as Date first (for custom date decoder in APIClient)
        if let date = try? container.decode(Date.self, forKey: key) {
            return date
        }

        // If that fails, try as String and parse manually
        if let dateString = try? container.decode(String.self, forKey: key),
           !dateString.isEmpty,
           dateString.lowercased() != "none",
           dateString.lowercased() != "null" {
            // Try various date formats
            let formatters = [
                "yyyy-MM-dd'T'HH:mm:ss.SSSSSSZ",
                "yyyy-MM-dd'T'HH:mm:ssZ",
                "yyyy-MM-dd HH:mm:ss",
                "yyyy-MM-dd"
            ]

            for format in formatters {
                let formatter = DateFormatter()
                formatter.dateFormat = format
                formatter.locale = Locale(identifier: "en_US_POSIX")
                if let date = formatter.date(from: dateString) {
                    return date
                }
            }

            // Try ISO8601
            if let date = ISO8601DateFormatter().date(from: dateString) {
                return date
            }
        }

        return nil
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encodeIfPresent(merchant, forKey: .merchant)
        try container.encodeIfPresent(merchantName, forKey: .merchantName)
        try container.encodeIfPresent(amount, forKey: .amount)
        try container.encodeIfPresent(date, forKey: .date)
        try container.encodeIfPresent(category, forKey: .category)
        try container.encodeIfPresent(notes, forKey: .notes)
        try container.encodeIfPresent(aiNotes, forKey: .aiNotes)
        try container.encodeIfPresent(imageURL, forKey: .imageURL)
        try container.encodeIfPresent(thumbnailURL, forKey: .thumbnailURL)
        try container.encode(status, forKey: .status)
        try container.encodeIfPresent(source, forKey: .source)
        try container.encodeIfPresent(business, forKey: .business)
        try container.encodeIfPresent(ocrConfidence, forKey: .ocrConfidence)
        try container.encodeIfPresent(createdAt, forKey: .createdAt)
        try container.encodeIfPresent(updatedAt, forKey: .updatedAt)
        try container.encodeIfPresent(transactionIndex, forKey: .transactionIndex)
        try container.encodeIfPresent(verificationStatus, forKey: .verificationStatus)
    }

    // Memberwise init for previews and testing
    init(
        id: String,
        merchant: String? = nil,
        amount: Double? = nil,
        date: Date? = nil,
        category: String? = nil,
        notes: String? = nil,
        imageURL: String? = nil,
        thumbnailURL: String? = nil,
        status: ReceiptStatus = .pending,
        source: String? = nil,
        business: String? = nil,
        ocrConfidence: Double? = nil,
        createdAt: Date? = nil,
        updatedAt: Date? = nil,
        transactionIndex: Int? = nil,
        merchantName: String? = nil,
        aiNotes: String? = nil,
        verificationStatus: String? = nil
    ) {
        self.id = id
        self.merchant = merchant
        self.amount = amount
        self.date = date
        self.category = category
        self.notes = notes
        self.imageURL = imageURL
        self.thumbnailURL = thumbnailURL
        self.status = status
        self.source = source
        self.business = business
        self.ocrConfidence = ocrConfidence
        self.createdAt = createdAt
        self.updatedAt = updatedAt
        self.transactionIndex = transactionIndex
        self.merchantName = merchantName
        self.aiNotes = aiNotes
        self.verificationStatus = verificationStatus
    }

    // Display merchant name (prefer merchant_name over merchant)
    var displayMerchant: String {
        merchantName ?? merchant ?? "Unknown"
    }

    // Display notes (prefer ai_notes over notes)
    var displayNotes: String? {
        if let ai = aiNotes, !ai.isEmpty { return ai }
        return notes
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

    // Is this receipt verified?
    var isVerified: Bool {
        verificationStatus == "verified" || status == .matched
    }
}

// MARK: - Incoming Receipt (from Gmail)
struct IncomingReceipt: Identifiable, Codable {
    var id: String
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

    // Additional fields from API
    var aiNotes: String?
    var businessType: String?
    var category: String?
    var bodySnippet: String?
    var confidenceScore: Double?

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
        case senderEmail = "from_email"
        case receivedDate = "created_at"
        case merchant
        case amount
        case date
        case imageURL = "r2_url"
        case thumbnailURL = "thumbnail_url"
        case status
        case emailAccount = "gmail_account"
        case extractedData = "extracted_data"
        case aiNotes = "ai_notes"
        case businessType = "business_type"
        case category
        case bodySnippet = "body_snippet"
        case confidenceScore = "confidence_score"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        // Handle id as Int or String
        if let intId = try? container.decode(Int.self, forKey: .id) {
            id = String(intId)
        } else {
            id = try container.decode(String.self, forKey: .id)
        }

        subject = try? container.decode(String.self, forKey: .subject)
        sender = try? container.decode(String.self, forKey: .sender)
        senderEmail = try? container.decode(String.self, forKey: .senderEmail)
        receivedDate = try? container.decode(Date.self, forKey: .receivedDate)
        merchant = try? container.decode(String.self, forKey: .merchant)
        amount = try? container.decode(Double.self, forKey: .amount)
        date = try? container.decode(Date.self, forKey: .date)
        imageURL = try? container.decode(String.self, forKey: .imageURL)
        thumbnailURL = try? container.decode(String.self, forKey: .thumbnailURL)
        status = (try? container.decode(String.self, forKey: .status)) ?? "pending"
        emailAccount = try? container.decode(String.self, forKey: .emailAccount)
        extractedData = try? container.decode(ExtractedData.self, forKey: .extractedData)
        aiNotes = try? container.decode(String.self, forKey: .aiNotes)
        businessType = try? container.decode(String.self, forKey: .businessType)
        category = try? container.decode(String.self, forKey: .category)
        bodySnippet = try? container.decode(String.self, forKey: .bodySnippet)
        confidenceScore = try? container.decode(Double.self, forKey: .confidenceScore)
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(id, forKey: .id)
        try container.encodeIfPresent(subject, forKey: .subject)
        try container.encodeIfPresent(sender, forKey: .sender)
        try container.encodeIfPresent(senderEmail, forKey: .senderEmail)
        try container.encodeIfPresent(merchant, forKey: .merchant)
        try container.encodeIfPresent(amount, forKey: .amount)
        try container.encodeIfPresent(imageURL, forKey: .imageURL)
        try container.encodeIfPresent(status, forKey: .status)
        try container.encodeIfPresent(emailAccount, forKey: .emailAccount)
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

    // Nested counts from API
    struct Counts: Codable {
        var total: Int?
        var matched: Int?
        var needs_review: Int?
        var recent: Int?
        var verified: Int?
        var down_home: Int?
        var personal: Int?
        var mcr: Int?
    }

    struct IncomingReceipts: Codable {
        var pending: Int?
        var matched: Int?
        var rejected: Int?
    }

    var counts: Counts?
    var incomingReceipts: IncomingReceipts?
    var transactionReceipts: Int?

    enum CodingKeys: String, CodingKey {
        case counts
        case incomingReceipts = "incoming_receipts"
        case transactionReceipts = "transaction_receipts"
        case totalReceipts = "total"
        case pendingReceipts = "pending_receipts"
        case matchedReceipts = "matched_receipts"
        case unmatchedReceipts = "unmatched_receipts"
        case totalAmount = "total_amount"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        // Try to decode nested structure first (from /api/library/counts)
        counts = try? container.decode(Counts.self, forKey: .counts)
        incomingReceipts = try? container.decode(IncomingReceipts.self, forKey: .incomingReceipts)
        transactionReceipts = try? container.decode(Int.self, forKey: .transactionReceipts)

        // Map to simple stats
        if let c = counts {
            totalReceipts = c.total ?? 0
            matchedReceipts = transactionReceipts ?? c.matched ?? 0
            pendingReceipts = incomingReceipts?.pending ?? c.needs_review ?? 0
            unmatchedReceipts = (c.total ?? 0) - (transactionReceipts ?? c.matched ?? 0)
        } else {
            // Direct decoding fallback
            totalReceipts = (try? container.decode(Int.self, forKey: .totalReceipts)) ?? 0
            matchedReceipts = (try? container.decode(Int.self, forKey: .matchedReceipts)) ?? 0
            pendingReceipts = (try? container.decode(Int.self, forKey: .pendingReceipts)) ?? 0
            unmatchedReceipts = (try? container.decode(Int.self, forKey: .unmatchedReceipts)) ?? 0
        }
        totalAmount = (try? container.decode(Double.self, forKey: .totalAmount)) ?? 0
    }

    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)
        try container.encode(totalReceipts, forKey: .totalReceipts)
        try container.encode(matchedReceipts, forKey: .matchedReceipts)
        try container.encode(pendingReceipts, forKey: .pendingReceipts)
        try container.encode(unmatchedReceipts, forKey: .unmatchedReceipts)
        try container.encode(totalAmount, forKey: .totalAmount)
    }
}

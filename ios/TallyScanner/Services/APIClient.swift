import Foundation
import UIKit

/// API Client for communicating with the TallyUps Flask backend
/// Connects to MySQL database via REST API
actor APIClient {
    static let shared = APIClient()

    // MARK: - Configuration

    /// Base URL for the API - configure this to your Railway deployment
    private var baseURL: String {
        UserDefaults.standard.string(forKey: "api_base_url") ?? "https://your-app.railway.app"
    }

    private var sessionToken: String? {
        KeychainService.shared.get(key: "session_token")
    }

    private var adminKey: String? {
        KeychainService.shared.get(key: "admin_api_key")
    }

    private let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.dateDecodingStrategy = .custom { decoder in
            let container = try decoder.singleValueContainer()
            let dateString = try container.decode(String.self)

            // Try multiple date formats
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

            throw DecodingError.dataCorruptedError(
                in: container,
                debugDescription: "Cannot decode date: \(dateString)"
            )
        }
        return decoder
    }()

    private init() {}

    // MARK: - API Configuration

    func setBaseURL(_ url: String) {
        UserDefaults.standard.set(url, forKey: "api_base_url")
    }

    func setAdminKey(_ key: String) {
        KeychainService.shared.save(key: "admin_api_key", value: key)
    }

    func setSessionToken(_ token: String) {
        KeychainService.shared.save(key: "session_token", value: token)
    }

    func clearCredentials() {
        KeychainService.shared.delete(key: "session_token")
    }

    // MARK: - Health Check

    func checkHealth() async throws -> HealthResponse {
        let request = try makeRequest(path: "/api/health/pool-status", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(HealthResponse.self, from: data)
    }

    // MARK: - Authentication

    func login(password: String) async throws -> Bool {
        var request = try makeRequest(path: "/login", method: "POST")
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let body = "password=\(password.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? password)"
        request.httpBody = body.data(using: .utf8)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 200 {
            // Extract session cookie if present
            if let cookies = HTTPCookieStorage.shared.cookies(for: URL(string: baseURL)!) {
                for cookie in cookies where cookie.name == "session" {
                    setSessionToken(cookie.value)
                }
            }
            return true
        }

        return false
    }

    func loginWithPIN(_ pin: String) async throws -> Bool {
        var request = try makeRequest(path: "/login/pin", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["pin": pin]
        request.httpBody = try JSONEncoder().encode(body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        return httpResponse.statusCode == 200
    }

    func logout() async throws {
        let request = try makeRequest(path: "/logout", method: "POST")
        _ = try? await URLSession.shared.data(for: request)
        clearCredentials()
    }

    // MARK: - Receipt Upload (Main Scanner Endpoint)

    /// Upload a receipt image to the server
    /// Uses the /mobile-upload endpoint which triggers auto OCR
    func uploadReceipt(
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
    ) async throws -> UploadResponse {
        let boundary = UUID().uuidString

        var request = try makeRequest(path: "/mobile-upload", method: "POST")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 120 // 2 minutes for upload

        var body = Data()

        // Add file data
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"receipt.jpg\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(imageData)
        body.append("\r\n".data(using: .utf8)!)

        // Add optional fields
        func addFormField(_ name: String, _ value: String) {
            body.append("--\(boundary)\r\n".data(using: .utf8)!)
            body.append("Content-Disposition: form-data; name=\"\(name)\"\r\n\r\n".data(using: .utf8)!)
            body.append("\(value)\r\n".data(using: .utf8)!)
        }

        if let merchant = merchant { addFormField("merchant", merchant) }
        if let amount = amount { addFormField("amount", String(amount)) }
        if let category = category { addFormField("category", category) }
        if let notes = notes { addFormField("notes", notes) }
        if let business = business { addFormField("business", business) }

        if let date = date {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            addFormField("date", formatter.string(from: date))
        }

        if let lat = latitude, let lon = longitude {
            addFormField("latitude", String(lat))
            addFormField("longitude", String(lon))
        }

        addFormField("source", source)
        addFormField("auto_ocr", "true")

        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard httpResponse.statusCode == 200 || httpResponse.statusCode == 201 else {
            let errorMessage = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(httpResponse.statusCode, errorMessage)
        }

        return try decoder.decode(UploadResponse.self, from: data)
    }

    // MARK: - OCR

    /// Perform OCR on an image
    func performOCR(imageData: Data) async throws -> OCRResult {
        let boundary = UUID().uuidString

        var request = try makeRequest(path: "/ocr", method: "POST")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.timeoutInterval = 60

        var body = Data()
        body.append("--\(boundary)\r\n".data(using: .utf8)!)
        body.append("Content-Disposition: form-data; name=\"file\"; filename=\"receipt.jpg\"\r\n".data(using: .utf8)!)
        body.append("Content-Type: image/jpeg\r\n\r\n".data(using: .utf8)!)
        body.append(imageData)
        body.append("\r\n".data(using: .utf8)!)
        body.append("--\(boundary)--\r\n".data(using: .utf8)!)

        request.httpBody = body

        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(OCRResult.self, from: data)
    }

    // MARK: - Library

    /// Fetch receipts from library
    func fetchReceipts(offset: Int = 0, limit: Int = 50, search: String? = nil) async throws -> [Receipt] {
        var path = "/api/library/receipts?offset=\(offset)&limit=\(limit)"
        if let search = search, !search.isEmpty {
            path += "&search=\(search.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? search)"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        let response = try decoder.decode(ReceiptListResponse.self, from: data)
        return response.receipts
    }

    /// Fetch library statistics
    func fetchLibraryStats() async throws -> LibraryStats {
        let request = try makeRequest(path: "/api/library/counts", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(LibraryStats.self, from: data)
    }

    /// Update receipt metadata
    func updateReceipt(id: String, updates: [String: Any]) async throws -> Receipt {
        var request = try makeRequest(path: "/api/library/receipts/\(id)", method: "PATCH")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONSerialization.data(withJSONObject: updates)

        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(Receipt.self, from: data)
    }

    /// Delete receipt
    func deleteReceipt(id: String) async throws {
        let request = try makeRequest(path: "/api/library/receipts/\(id)", method: "DELETE")
        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 || httpResponse.statusCode == 204 else {
            throw APIError.invalidResponse
        }
    }

    // MARK: - Incoming Receipts (Gmail)

    /// Fetch incoming receipts from Gmail
    func fetchIncomingReceipts(status: String = "pending", limit: Int = 50) async throws -> [IncomingReceipt] {
        let path = "/api/incoming/receipts?status=\(status)&limit=\(limit)"
        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        let response = try decoder.decode(IncomingReceiptListResponse.self, from: data)
        return response.receipts
    }

    /// Get inbox statistics
    func fetchInboxStats() async throws -> InboxStats {
        let request = try makeRequest(path: "/api/incoming/stats", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(InboxStats.self, from: data)
    }

    /// Accept an incoming receipt
    func acceptReceipt(id: String, merchant: String?, amount: Double?, date: Date?) async throws {
        var request = try makeRequest(path: "/api/incoming/accept", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = ["receipt_id": id]
        if let merchant = merchant { body["merchant"] = merchant }
        if let amount = amount { body["amount"] = amount }
        if let date = date {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            body["date"] = formatter.string(from: date)
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)
        let (_, _) = try await URLSession.shared.data(for: request)
    }

    /// Reject an incoming receipt
    func rejectReceipt(id: String) async throws {
        var request = try makeRequest(path: "/api/incoming/reject", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["receipt_id": id])

        let (_, _) = try await URLSession.shared.data(for: request)
    }

    /// Trigger Gmail scan
    func triggerGmailScan() async throws {
        let request = try makeRequest(path: "/api/incoming/scan", method: "POST")
        let (_, _) = try await URLSession.shared.data(for: request)
    }

    // MARK: - Transactions

    /// Fetch transactions
    func fetchTransactions(offset: Int = 0, limit: Int = 100, business: String? = nil) async throws -> [Transaction] {
        var path = "/api/transactions?offset=\(offset)&limit=\(limit)"
        if let business = business {
            path += "&business_type=\(business)"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        let response = try decoder.decode(TransactionListResponse.self, from: data)
        return response.transactions
    }

    /// Get single transaction
    func fetchTransaction(index: Int) async throws -> Transaction {
        let request = try makeRequest(path: "/api/transactions/\(index)", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(Transaction.self, from: data)
    }

    // MARK: - Contacts

    /// Fetch contacts for attendee matching
    func fetchContacts(search: String? = nil, limit: Int = 100) async throws -> [Contact] {
        var path = "/api/contacts?limit=\(limit)"
        if let search = search, !search.isEmpty {
            path += "&search=\(search.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? search)"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        let response = try decoder.decode(ContactListResponse.self, from: data)
        return response.contacts
    }

    // MARK: - Smart Notes

    /// Generate smart note for transaction
    func generateNote(transactionIndex: Int) async throws -> String {
        var request = try makeRequest(path: "/api/notes/generate", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["_index": transactionIndex])

        let (data, _) = try await URLSession.shared.data(for: request)

        struct NoteResponse: Codable {
            let note: String
        }

        let response = try decoder.decode(NoteResponse.self, from: data)
        return response.note
    }

    // MARK: - Calendar Events

    /// Fetch calendar events for a specific date (for context matching)
    func fetchCalendarEvents(date: Date) async throws -> [CalendarEvent] {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let dateStr = formatter.string(from: date)

        let request = try makeRequest(path: "/api/calendar/events?date=\(dateStr)", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        struct EventsResponse: Codable {
            let events: [CalendarEvent]
        }

        let response = try decoder.decode(EventsResponse.self, from: data)
        return response.events
    }

    /// Fetch calendar events for a date range
    func fetchCalendarEventsRange(startDate: Date, endDate: Date) async throws -> [CalendarEvent] {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"

        let path = "/api/calendar/events?start=\(formatter.string(from: startDate))&end=\(formatter.string(from: endDate))"
        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        struct EventsResponse: Codable {
            let events: [CalendarEvent]
        }

        let response = try decoder.decode(EventsResponse.self, from: data)
        return response.events
    }

    // MARK: - Contact Suggestions

    /// Get suggested contacts for a transaction/receipt based on merchant and date
    func suggestContacts(merchant: String, date: Date? = nil) async throws -> [Contact] {
        var path = "/api/contact-hub/suggest?merchant=\(merchant.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? merchant)"

        if let date = date {
            let formatter = DateFormatter()
            formatter.dateFormat = "yyyy-MM-dd"
            path += "&date=\(formatter.string(from: date))"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        let response = try decoder.decode(ContactListResponse.self, from: data)
        return response.contacts
    }

    // MARK: - Private Helpers

    private func makeRequest(path: String, method: String) throws -> URLRequest {
        guard let url = URL(string: baseURL + path) else {
            throw APIError.invalidURL
        }

        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 30

        // Add authentication
        if let adminKey = adminKey {
            request.setValue(adminKey, forHTTPHeaderField: "X-Admin-Key")
        }

        // Add session cookie if available
        if let sessionToken = sessionToken {
            request.setValue("session=\(sessionToken)", forHTTPHeaderField: "Cookie")
        }

        return request
    }
}

// MARK: - API Errors

enum APIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case unauthorized
    case serverError(Int, String)
    case networkError(Error)
    case decodingError(Error)

    var errorDescription: String? {
        switch self {
        case .invalidURL:
            return "Invalid URL"
        case .invalidResponse:
            return "Invalid response from server"
        case .unauthorized:
            return "Not authorized. Please log in again."
        case .serverError(let code, let message):
            return "Server error (\(code)): \(message)"
        case .networkError(let error):
            return "Network error: \(error.localizedDescription)"
        case .decodingError(let error):
            return "Data error: \(error.localizedDescription)"
        }
    }
}

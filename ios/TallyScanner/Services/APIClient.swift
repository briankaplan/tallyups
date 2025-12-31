import Foundation
import UIKit
import SwiftUI

/// API Client for communicating with the TallyUps Flask backend
/// Connects to MySQL database via REST API
actor APIClient {
    static let shared = APIClient()

    // MARK: - Configuration

    /// Base URL for the API - configure this to your Railway deployment
    private var baseURL: String {
        UserDefaults.standard.string(forKey: "api_base_url") ?? "https://tallyups.com"
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
        // Use enhanced security for sensitive API keys
        KeychainService.shared.saveSensitive(key: "admin_api_key", value: key)
    }

    func setSessionToken(_ token: String) {
        // Use enhanced security for session tokens
        KeychainService.shared.saveSensitive(key: "session_token", value: token)
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

    // MARK: - Dashboard Stats

    struct DashboardStats {
        let needsReceiptCount: Int
        let uncategorizedCount: Int
        let weeklySpending: String
        let weeklyTrend: String?
        let matchRate: Int
    }

    struct DashboardStatsResponse: Codable {
        let success: Bool
        let needsReceiptCount: Int
        let uncategorizedCount: Int
        let weeklySpending: String
        let weeklyTrend: String?
        let matchRate: Int
    }

    func fetchDashboardStats() async throws -> DashboardStats {
        let request = try makeRequest(path: "/api/dashboard/stats", method: "GET")
        print("📊 APIClient: Fetching dashboard stats from \(request.url?.absoluteString ?? "nil")")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            print("📊 APIClient: Invalid response type")
            throw APIError.invalidResponse
        }

        print("📊 APIClient: Dashboard stats status: \(httpResponse.statusCode)")

        // Return defaults if not authorized or error
        guard httpResponse.statusCode == 200 else {
            if let responseText = String(data: data, encoding: .utf8) {
                print("📊 APIClient: Dashboard stats error response: \(responseText)")
            }
            return DashboardStats(
                needsReceiptCount: 0,
                uncategorizedCount: 0,
                weeklySpending: "$0.00",
                weeklyTrend: nil,
                matchRate: 100
            )
        }

        if let responseText = String(data: data, encoding: .utf8) {
            print("📊 APIClient: Dashboard stats response: \(responseText)")
        }

        let result = try decoder.decode(DashboardStatsResponse.self, from: data)
        print("📊 APIClient: Decoded stats - needsReceipt: \(result.needsReceiptCount), matchRate: \(result.matchRate)")

        return DashboardStats(
            needsReceiptCount: result.needsReceiptCount,
            uncategorizedCount: result.uncategorizedCount,
            weeklySpending: result.weeklySpending,
            weeklyTrend: result.weeklyTrend,
            matchRate: result.matchRate
        )
    }

    func runAutoMatch() async throws {
        var request = try makeRequest(path: "/api/receipts/auto-match", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              httpResponse.statusCode == 200 else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 500
            throw APIError.serverError(statusCode, "Auto-match failed")
        }
    }

    // MARK: - Authentication

    /// Response from email/password login
    struct EmailLoginResponse: Codable {
        let success: Bool
        let error: String?
        let accessToken: String?
        let refreshToken: String?
        let user: AuthService.UserInfo?

        enum CodingKeys: String, CodingKey {
            case success, error, user
            case accessToken = "access_token"
            case refreshToken = "refresh_token"
        }
    }

    /// Login with email and password (for demo account)
    func loginWithEmail(email: String, password: String) async throws -> EmailLoginResponse {
        var request = try makeRequest(path: "/api/auth/login", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let deviceId = await UIDevice.current.identifierForVendor?.uuidString ?? UUID().uuidString
        let deviceName = await UIDevice.current.name
        let body: [String: Any] = [
            "email": email,
            "password": password,
            "device_id": deviceId,
            "device_name": deviceName
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        print("🔐 APIClient: Attempting email login to \(baseURL)/api/auth/login")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        print("🔐 APIClient: Email login response status: \(httpResponse.statusCode)")

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase

        if httpResponse.statusCode == 200 {
            let loginResponse = try decoder.decode(EmailLoginResponse.self, from: data)

            // Store session cookie if present
            if let url = URL(string: baseURL),
               let cookies = HTTPCookieStorage.shared.cookies(for: url) {
                for cookie in cookies where cookie.name == "session" {
                    setSessionToken(cookie.value)
                }
            }

            return loginResponse
        } else {
            // Try to decode error response
            if let errorResponse = try? decoder.decode(EmailLoginResponse.self, from: data) {
                return errorResponse
            }
            return EmailLoginResponse(success: false, error: "Login failed", accessToken: nil, refreshToken: nil, user: nil)
        }
    }

    func login(password: String) async throws -> Bool {
        var request = try makeRequest(path: "/login", method: "POST")
        request.setValue("application/x-www-form-urlencoded", forHTTPHeaderField: "Content-Type")

        let body = "password=\(password.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? password)"
        request.httpBody = body.data(using: .utf8)

        print("🔐 APIClient: Attempting login to \(baseURL)/login")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        print("🔐 APIClient: Login response status: \(httpResponse.statusCode)")

        if httpResponse.statusCode == 200 {
            // Extract session cookie if present
            if let url = URL(string: baseURL),
               let cookies = HTTPCookieStorage.shared.cookies(for: url) {
                print("🔐 APIClient: Found \(cookies.count) cookies")
                for cookie in cookies {
                    print("🔐 APIClient: Cookie: \(cookie.name) = \(cookie.value.prefix(20))...")
                    if cookie.name == "session" {
                        setSessionToken(cookie.value)
                        print("🔐 APIClient: Session token saved to keychain")
                    }
                }
            } else {
                print("🔐 APIClient: No cookies found for \(baseURL)")
            }

            // Also check Set-Cookie header directly
            if let setCookie = httpResponse.value(forHTTPHeaderField: "Set-Cookie") {
                print("🔐 APIClient: Set-Cookie header: \(setCookie.prefix(50))...")
                // Parse session token from Set-Cookie header if present
                if let sessionRange = setCookie.range(of: "session=") {
                    let afterEquals = setCookie[sessionRange.upperBound...]
                    if let endRange = afterEquals.range(of: ";") {
                        let token = String(afterEquals[..<endRange.lowerBound])
                        setSessionToken(token)
                        print("🔐 APIClient: Extracted session from header")
                    }
                }
            }

            return true
        }

        // Log error response
        if let errorStr = String(data: data, encoding: .utf8) {
            print("🔐 APIClient: Login failed: \(errorStr)")
        }

        return false
    }

    func loginWithPIN(_ pin: String) async throws -> Bool {
        var request = try makeRequest(path: "/login/pin", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["pin": pin]
        request.httpBody = try JSONEncoder().encode(body)

        print("🔐 APIClient: Attempting PIN login to \(baseURL)/login/pin")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        print("🔐 APIClient: PIN login response status: \(httpResponse.statusCode)")

        if httpResponse.statusCode == 200 {
            // Extract session cookie if present
            if let url = URL(string: baseURL),
               let cookies = HTTPCookieStorage.shared.cookies(for: url) {
                print("🔐 APIClient: Found \(cookies.count) cookies after PIN login")
                for cookie in cookies {
                    if cookie.name == "session" {
                        setSessionToken(cookie.value)
                        print("🔐 APIClient: Session token saved from PIN login")
                    }
                }
            }

            // Also check Set-Cookie header directly
            if let setCookie = httpResponse.value(forHTTPHeaderField: "Set-Cookie") {
                print("🔐 APIClient: Set-Cookie header: \(setCookie.prefix(50))...")
                if let sessionRange = setCookie.range(of: "session=") {
                    let afterEquals = setCookie[sessionRange.upperBound...]
                    if let endRange = afterEquals.range(of: ";") {
                        let token = String(afterEquals[..<endRange.lowerBound])
                        setSessionToken(token)
                        print("🔐 APIClient: Extracted session from PIN login header")
                    }
                }
            }

            return true
        }

        // Log error response
        if let errorStr = String(data: data, encoding: .utf8) {
            print("🔐 APIClient: PIN login failed: \(errorStr)")
        }

        return false
    }

    func logout() async throws {
        let request = try makeRequest(path: "/logout", method: "POST")
        _ = try? await URLSession.shared.data(for: request)
        clearCredentials()
    }

    // MARK: - Push Notifications

    /// Register device push token with backend
    func registerPushToken(_ token: String) async throws {
        var request = try makeRequest(path: "/api/notifications/register-device", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let deviceName = await MainActor.run { UIDevice.current.name }
        let body: [String: Any] = [
            "token": token,
            "platform": "ios",
            "device_name": deviceName,
            "app_version": Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0"
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 500
            throw APIError.serverError(statusCode, "Failed to register push token")
        }
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

        print("📡 APIClient: Fetching \(baseURL)\(path)")

        let request = try makeRequest(path: path, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        if let httpResponse = response as? HTTPURLResponse {
            print("📡 APIClient: Response status: \(httpResponse.statusCode)")
            if httpResponse.statusCode == 401 {
                throw APIError.unauthorized
            }
        }

        // Debug: print first 500 chars of response
        if let str = String(data: data, encoding: .utf8) {
            print("📡 APIClient: Response preview: \(String(str.prefix(500)))")
        }

        do {
            let response = try decoder.decode(ReceiptListResponse.self, from: data)
            print("📡 APIClient: Decoded \(response.receipts.count) receipts")
            return response.receipts
        } catch {
            print("📡 APIClient: Decode error: \(error)")
            throw APIError.decodingError(error)
        }
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

    /// Get inbox statistics (uses receipts endpoint which includes counts)
    func fetchInboxStats() async throws -> InboxStats {
        // Use receipts endpoint since /api/incoming/stats has issues
        let request = try makeRequest(path: "/api/incoming/receipts?status=pending&limit=1", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)
        return try decoder.decode(InboxStats.self, from: data)
    }

    /// Accept an incoming receipt
    func acceptReceipt(id: String, merchant: String?, amount: Double?, date: Date?, business: String? = nil, category: String? = nil) async throws {
        var request = try makeRequest(path: "/api/incoming/accept", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = ["receipt_id": id]
        if let merchant = merchant { body["merchant"] = merchant }
        if let amount = amount { body["amount"] = amount }
        if let business = business { body["business_type"] = business }
        if let category = category { body["category"] = category }
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

    /// Unreject an incoming receipt (restore to pending)
    func unrejectReceipt(id: String) async throws {
        var request = try makeRequest(path: "/api/incoming/unreject", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.httpBody = try JSONEncoder().encode(["receipt_id": id])

        let (_, _) = try await URLSession.shared.data(for: request)
    }

    /// Auto-match a receipt to a transaction
    func autoMatchReceipt(id: String) async throws {
        var request = try makeRequest(path: "/api/incoming/auto-match", method: "POST")
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

    /// Link a receipt to a transaction
    func linkReceiptToTransaction(transactionIndex: Int, receiptId: String) async throws -> Bool {
        var request = try makeRequest(path: "/api/transactions/\(transactionIndex)/link", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = ["receipt_id": receiptId]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 200 {
            return true
        }

        // Try to parse error message
        if let errorData = try? JSONSerialization.jsonObject(with: data) as? [String: Any],
           let message = errorData["error"] as? String {
            throw APIError.serverError(httpResponse.statusCode, message)
        }

        return false
    }

    /// Exclude a transaction from receipt matching
    func excludeTransaction(transactionIndex: Int, reason: String? = nil) async throws -> Bool {
        var request = try makeRequest(path: "/api/transactions/\(transactionIndex)/exclude", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = ["excluded": true]
        if let reason = reason {
            body["exclusion_reason"] = reason
        }
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        return httpResponse.statusCode == 200
    }

    /// Unexclude a transaction
    func unexcludeTransaction(transactionIndex: Int) async throws -> Bool {
        var request = try makeRequest(path: "/api/transactions/\(transactionIndex)/exclude", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = ["excluded": false]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        return httpResponse.statusCode == 200
    }

    /// Unlink a receipt from a transaction
    func unlinkReceiptFromTransaction(transactionIndex: Int, receiptId: String) async throws -> Bool {
        var request = try makeRequest(path: "/api/transactions/\(transactionIndex)/unlink", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = ["receipt_id": receiptId]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        return httpResponse.statusCode == 200
    }

    /// Fetch receipts linked to a transaction
    func fetchLinkedReceipts(transactionIndex: Int) async throws -> [Receipt] {
        let request = try makeRequest(path: "/api/transactions/\(transactionIndex)/receipts", method: "GET")
        let (data, _) = try await URLSession.shared.data(for: request)

        struct LinkedReceiptsResponse: Codable {
            let receipts: [Receipt]
        }

        let response = try decoder.decode(LinkedReceiptsResponse.self, from: data)
        return response.receipts
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

    /// Create a new contact
    func createContact(_ contact: AppContact) async throws {
        var request = try makeRequest(path: "/api/contacts", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any?] = [
            "name": contact.name,
            "email": contact.email,
            "phone": contact.phone,
            "company": contact.company,
            "tags": contact.tags
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body.compactMapValues { $0 })

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Update an existing contact
    func updateContact(_ contact: AppContact) async throws {
        var request = try makeRequest(path: "/api/contacts/\(contact.id)", method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any?] = [
            "name": contact.name,
            "email": contact.email,
            "phone": contact.phone,
            "company": contact.company,
            "tags": contact.tags
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body.compactMapValues { $0 })

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Delete a contact
    func deleteContact(id: Int) async throws {
        let request = try makeRequest(path: "/api/contacts/\(id)", method: "DELETE")
        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Suggest contacts for a merchant/transaction
    func suggestContacts(merchant: String, date: Date) async throws -> [AppContact] {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"
        let dateStr = formatter.string(from: date)

        let merchantEncoded = merchant.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? merchant
        let request = try makeRequest(
            path: "/api/contacts/suggest?merchant=\(merchantEncoded)&date=\(dateStr)",
            method: "GET"
        )
        let (data, _) = try await URLSession.shared.data(for: request)

        struct SuggestResponse: Codable {
            let contacts: [AppContact]
        }

        let response = try decoder.decode(SuggestResponse.self, from: data)
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

        // Add JWT Bearer token authentication (primary)
        if let accessToken = KeychainService.shared.get(key: "access_token") {
            request.setValue("Bearer \(accessToken)", forHTTPHeaderField: "Authorization")
        }
        // Fallback to admin key (legacy)
        else if let adminKey = adminKey {
            request.setValue(adminKey, forHTTPHeaderField: "X-Admin-Key")
        }

        // Add session cookie if available (web interface compat)
        if let sessionToken = sessionToken {
            request.setValue("session=\(sessionToken)", forHTTPHeaderField: "Cookie")
        }

        return request
    }

    // MARK: - Apple Sign In Authentication

    /// Authentication result from Apple Sign In
    struct AppleAuthResponse: Codable {
        let accessToken: String
        let refreshToken: String
        let expiresIn: Int
        let user: AuthService.UserInfo

        enum CodingKeys: String, CodingKey {
            case accessToken = "access_token"
            case refreshToken = "refresh_token"
            case expiresIn = "expires_in"
            case user
        }
    }

    /// Token refresh response
    struct TokenRefreshResponse: Codable {
        let accessToken: String
        let refreshToken: String
        let expiresIn: Int

        enum CodingKeys: String, CodingKey {
            case accessToken = "access_token"
            case refreshToken = "refresh_token"
            case expiresIn = "expires_in"
        }
    }

    /// Authenticate with Apple identity token
    func authenticateWithApple(
        identityToken: String,
        userName: String?,
        deviceId: String,
        deviceName: String? = nil
    ) async throws -> AppleAuthResponse {
        var request = try makeRequest(path: "/api/auth/apple", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = [
            "identity_token": identityToken,
            "device_id": deviceId
        ]

        if let userName = userName {
            body["user_name"] = userName
        }
        if let deviceName = deviceName {
            body["device_name"] = deviceName
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(httpResponse.statusCode, message)
        }

        return try decoder.decode(AppleAuthResponse.self, from: data)
    }

    /// Refresh access token using refresh token
    func refreshToken(
        refreshToken: String,
        deviceId: String
    ) async throws -> TokenRefreshResponse {
        var request = try makeRequest(path: "/api/auth/refresh", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: String] = [
            "refresh_token": refreshToken,
            "device_id": deviceId
        ]

        request.httpBody = try JSONEncoder().encode(body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            throw APIError.tokenExpired
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Unknown error"
            throw APIError.serverError(httpResponse.statusCode, message)
        }

        return try decoder.decode(TokenRefreshResponse.self, from: data)
    }

    /// Logout with device ID
    func logout(deviceId: String? = nil) async throws {
        var request = try makeRequest(path: "/api/auth/logout", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let deviceId = deviceId {
            let body = ["device_id": deviceId]
            request.httpBody = try JSONEncoder().encode(body)
        }

        _ = try? await URLSession.shared.data(for: request)
        clearCredentials()
    }

    /// Delete user account (GDPR compliance)
    func deleteAccount() async throws {
        let request = try makeRequest(path: "/api/auth/delete-account", method: "DELETE")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Account deletion failed"
            throw APIError.serverError(httpResponse.statusCode, message)
        }

        clearCredentials()
    }

    /// Get current user profile
    func getCurrentUser() async throws -> AuthService.UserInfo {
        let request = try makeRequest(path: "/api/auth/me", method: "GET")

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Failed to get user")
        }

        return try decoder.decode(AuthService.UserInfo.self, from: data)
    }

    // MARK: - Business Types

    /// Business type model for per-user custom categories
    struct BusinessType: Codable, Identifiable, Hashable {
        let id: Int
        let name: String
        let displayName: String
        let color: String
        let icon: String
        let isDefault: Bool
        let sortOrder: Int

        enum CodingKeys: String, CodingKey {
            case id, name, color, icon
            case displayName = "display_name"
            case isDefault = "is_default"
            case sortOrder = "sort_order"
        }

        /// Convert hex color string to SwiftUI Color
        var swiftUIColor: Color {
            Color(hex: color) ?? .gray
        }
    }

    /// Response for business types list
    struct BusinessTypesResponse: Codable {
        let success: Bool
        let businessTypes: [BusinessType]

        enum CodingKeys: String, CodingKey {
            case success
            case businessTypes = "business_types"
        }
    }

    /// Fetch user's business types (per-user custom categories)
    func fetchBusinessTypes() async throws -> [BusinessType] {
        let request = try makeRequest(path: "/api/business-types", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 401 {
            throw APIError.unauthorized
        }

        let result = try decoder.decode(BusinessTypesResponse.self, from: data)
        return result.businessTypes
    }

    /// Create a new business type
    func createBusinessType(
        name: String,
        displayName: String? = nil,
        color: String = "#00FF88",
        icon: String = "briefcase"
    ) async throws -> BusinessType {
        var request = try makeRequest(path: "/api/business-types", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "name": name,
            "display_name": displayName ?? name,
            "color": color,
            "icon": icon,
            "is_default": false
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct CreateResponse: Codable {
            let success: Bool
            let businessType: BusinessType

            enum CodingKeys: String, CodingKey {
                case success
                case businessType = "business_type"
            }
        }

        let result = try decoder.decode(CreateResponse.self, from: data)
        return result.businessType
    }

    // MARK: - AI Learning & Feedback

    /// AI categorization suggestion
    struct AISuggestion: Codable {
        let category: String?
        let businessType: String?
        let description: String?
        let confidence: Double
        let source: String

        enum CodingKeys: String, CodingKey {
            case category
            case businessType = "business_type"
            case description
            case confidence
            case source
        }
    }

    /// Submit AI feedback for learning
    func submitAIFeedback(
        transactionIndex: Int,
        feedbackType: String,
        suggestedValue: String,
        acceptedValue: String,
        wasAccepted: Bool
    ) async throws {
        var request = try makeRequest(path: "/api/ai/feedback", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "transaction_index": transactionIndex,
            "feedback_type": feedbackType,
            "suggested_value": suggestedValue,
            "accepted_value": acceptedValue,
            "was_accepted": wasAccepted,
            "source": "ios_app"
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            // Silent fail - don't break UX for feedback errors
            print("⚠️ AI feedback submission failed")
            return
        }
    }

    /// Get AI suggestions for a transaction
    func getAISuggestions(transactionIndex: Int) async throws -> AISuggestion {
        let request = try makeRequest(path: "/api/ai/suggest?transaction_index=\(transactionIndex)", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        return try decoder.decode(AISuggestion.self, from: data)
    }

    /// Update transaction with user's corrections (learns from feedback)
    func updateTransaction(
        index: Int,
        category: String? = nil,
        businessType: String? = nil,
        notes: String? = nil
    ) async throws {
        var request = try makeRequest(path: "/api/transactions/\(index)", method: "PATCH")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = [:]
        if let category = category { body["category"] = category }
        if let businessType = businessType { body["business_type"] = businessType }
        if let notes = notes { body["notes"] = notes }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    // MARK: - Duplicate Detection

    /// Check if a receipt image is a duplicate of an existing receipt
    func checkDuplicateReceipt(
        imageHash: String,
        amount: Double?,
        date: String?,
        merchant: String?
    ) async throws -> ScannerService.DuplicateCheckResult {
        var request = try makeRequest(path: "/api/receipts/check-duplicate", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = ["image_hash": imageHash]
        if let amount = amount { body["amount"] = amount }
        if let date = date { body["date"] = date }
        if let merchant = merchant { body["merchant"] = merchant }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // If endpoint doesn't exist yet, return no duplicate
        if httpResponse.statusCode == 404 {
            return ScannerService.DuplicateCheckResult(
                isDuplicate: false,
                existingReceiptId: nil,
                existingReceiptUrl: nil,
                matchConfidence: 0,
                matchType: .exactHash
            )
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Duplicate check failed")
        }

        // Parse the response
        struct DuplicateResponse: Codable {
            let isDuplicate: Bool
            let existingReceiptId: String?
            let existingReceiptUrl: String?
            let matchConfidence: Double?
            let matchType: String?

            enum CodingKeys: String, CodingKey {
                case isDuplicate = "is_duplicate"
                case existingReceiptId = "existing_receipt_id"
                case existingReceiptUrl = "existing_receipt_url"
                case matchConfidence = "match_confidence"
                case matchType = "match_type"
            }
        }

        let duplicateResponse = try decoder.decode(DuplicateResponse.self, from: data)

        let matchType: ScannerService.DuplicateCheckResult.MatchType
        switch duplicateResponse.matchType {
        case "exact_hash": matchType = .exactHash
        case "similar_image": matchType = .similarImage
        case "same_amount_date": matchType = .sameAmountDate
        case "same_transaction": matchType = .sameTransaction
        default: matchType = .exactHash
        }

        return ScannerService.DuplicateCheckResult(
            isDuplicate: duplicateResponse.isDuplicate,
            existingReceiptId: duplicateResponse.existingReceiptId,
            existingReceiptUrl: duplicateResponse.existingReceiptUrl,
            matchConfidence: duplicateResponse.matchConfidence ?? 0,
            matchType: matchType
        )
    }

    // MARK: - Projects

    /// Fetch all projects for the current user
    func fetchProjects() async throws -> [Project] {
        let request = try makeRequest(path: "/api/projects", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // Return empty array if endpoint doesn't exist yet
        if httpResponse.statusCode == 404 {
            return []
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Failed to fetch projects")
        }

        struct ProjectsResponse: Codable {
            let projects: [Project]
        }

        let projectsResponse = try decoder.decode(ProjectsResponse.self, from: data)
        return projectsResponse.projects
    }

    /// Create a new project
    func createProject(
        name: String,
        description: String? = nil,
        color: String = "#00FF88",
        icon: String = "folder.fill",
        budget: Double? = nil,
        startDate: Date? = nil,
        endDate: Date? = nil
    ) async throws -> Project {
        var request = try makeRequest(path: "/api/projects", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = [
            "name": name,
            "color": color,
            "icon": icon
        ]
        if let description = description { body["description"] = description }
        if let budget = budget { body["budget"] = budget }

        let dateFormatter = ISO8601DateFormatter()
        if let startDate = startDate {
            body["start_date"] = dateFormatter.string(from: startDate)
        }
        if let endDate = endDate {
            body["end_date"] = dateFormatter.string(from: endDate)
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        return try decoder.decode(Project.self, from: data)
    }

    /// Update an existing project
    func updateProject(_ project: Project) async throws -> Project {
        var request = try makeRequest(path: "/api/projects/\(project.id)", method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        var body: [String: Any] = [
            "name": project.name,
            "color": project.color,
            "icon": project.icon,
            "is_active": project.isActive
        ]
        if let description = project.description { body["description"] = description }
        if let budget = project.budget { body["budget"] = budget }

        let dateFormatter = ISO8601DateFormatter()
        if let startDate = project.startDate {
            body["start_date"] = dateFormatter.string(from: startDate)
        }
        if let endDate = project.endDate {
            body["end_date"] = dateFormatter.string(from: endDate)
        }

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        return try decoder.decode(Project.self, from: data)
    }

    /// Delete a project
    func deleteProject(id: String) async throws {
        let request = try makeRequest(path: "/api/projects/\(id)", method: "DELETE")
        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Assign a transaction to a project
    func assignTransactionToProject(transactionIndex: Int, projectId: String?) async throws {
        var request = try makeRequest(path: "/api/transactions/\(transactionIndex)/project", method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any?] = ["project_id": projectId]
        request.httpBody = try JSONSerialization.data(withJSONObject: body.compactMapValues { $0 })

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Bulk assign transactions to a project
    func bulkAssignTransactionsToProject(transactionIndexes: [Int], projectId: String) async throws {
        var request = try makeRequest(path: "/api/projects/\(projectId)/transactions", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["transaction_indexes": transactionIndexes]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Get transactions for a specific project
    func fetchProjectTransactions(projectId: String, offset: Int = 0, limit: Int = 50) async throws -> [Transaction] {
        let request = try makeRequest(
            path: "/api/projects/\(projectId)/transactions?offset=\(offset)&limit=\(limit)",
            method: "GET"
        )
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        let transactionResponse = try decoder.decode(TransactionListResponse.self, from: data)
        return transactionResponse.transactions
    }

    // MARK: - Email Mapping Rules

    /// Fetch all email-to-business-type mapping rules
    func fetchEmailMappingRules() async throws -> [EmailBusinessRule] {
        let request = try makeRequest(path: "/api/email-rules", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct RulesResponse: Codable {
            let rules: [EmailBusinessRule]
        }

        let rulesResponse = try decoder.decode(RulesResponse.self, from: data)
        return rulesResponse.rules
    }

    /// Create a new email mapping rule
    func createEmailMappingRule(
        emailPattern: String,
        businessType: String,
        priority: Int = 0
    ) async throws -> EmailBusinessRule {
        var request = try makeRequest(path: "/api/email-rules", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "email_pattern": emailPattern,
            "business_type": businessType,
            "priority": priority
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        return try decoder.decode(EmailBusinessRule.self, from: data)
    }

    /// Update an existing email mapping rule
    func updateEmailMappingRule(_ rule: EmailBusinessRule) async throws -> EmailBusinessRule {
        var request = try makeRequest(path: "/api/email-rules/\(rule.id)", method: "PUT")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "email_pattern": rule.emailPattern,
            "business_type": rule.businessType,
            "priority": rule.priority,
            "is_active": rule.isActive
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        return try decoder.decode(EmailBusinessRule.self, from: data)
    }

    /// Delete an email mapping rule
    func deleteEmailMappingRule(id: String) async throws {
        let request = try makeRequest(path: "/api/email-rules/\(id)", method: "DELETE")
        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Test which business type an email would match
    func testEmailMapping(email: String) async throws -> String? {
        var request = try makeRequest(path: "/api/email-rules/test", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body = ["email": email]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct TestResponse: Codable {
            let matched: Bool
            let businessType: String?

            enum CodingKeys: String, CodingKey {
                case matched
                case businessType = "business_type"
            }
        }

        let testResponse = try decoder.decode(TestResponse.self, from: data)
        return testResponse.businessType
    }

    // MARK: - Expense Reports

    /// Report data model
    struct ExpenseReport: Codable {
        let totalSpent: Double
        let transactionCount: Int
        let receiptCount: Int
        let dailyAverage: Double
        let categories: [CategoryBreakdown]
        let merchants: [MerchantBreakdown]
        let timeline: [DailySpending]

        enum CodingKeys: String, CodingKey {
            case totalSpent = "total_spent"
            case transactionCount = "transaction_count"
            case receiptCount = "receipt_count"
            case dailyAverage = "daily_average"
            case categories, merchants, timeline
        }
    }

    struct CategoryBreakdown: Codable, Identifiable {
        var id: String { category }
        let category: String
        let amount: Double
        let count: Int
        let percentage: Double
    }

    struct MerchantBreakdown: Codable, Identifiable {
        var id: String { merchant }
        let merchant: String
        let amount: Double
        let count: Int
    }

    struct DailySpending: Codable, Identifiable {
        var id: String { date }
        let date: String
        let amount: Double
        let count: Int
    }

    /// Fetch expense report for a date range
    func fetchExpenseReport(
        startDate: Date,
        endDate: Date,
        businessType: String? = nil
    ) async throws -> ExpenseReport {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"

        var path = "/api/reports/expenses?start=\(formatter.string(from: startDate))&end=\(formatter.string(from: endDate))"
        if let business = businessType, business != "all" {
            path += "&business_type=\(business.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? business)"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // Return empty report if endpoint doesn't exist yet
        if httpResponse.statusCode == 404 {
            return ExpenseReport(
                totalSpent: 0,
                transactionCount: 0,
                receiptCount: 0,
                dailyAverage: 0,
                categories: [],
                merchants: [],
                timeline: []
            )
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Failed to fetch report")
        }

        return try decoder.decode(ExpenseReport.self, from: data)
    }

    /// Export report as PDF or CSV
    func exportReport(
        startDate: Date,
        endDate: Date,
        businessType: String? = nil,
        format: String = "pdf"
    ) async throws -> Data {
        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"

        var path = "/api/reports/export?start=\(formatter.string(from: startDate))&end=\(formatter.string(from: endDate))&format=\(format)"
        if let business = businessType, business != "all" {
            path += "&business_type=\(business.addingPercentEncoding(withAllowedCharacters: .urlQueryAllowed) ?? business)"
        }

        let request = try makeRequest(path: path, method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError((response as? HTTPURLResponse)?.statusCode ?? 500, "Export failed")
        }

        return data
    }

    // MARK: - Connected Services

    /// Connected service status model
    struct ConnectedService: Codable, Identifiable {
        let id: String
        let type: String
        let email: String?
        let isConnected: Bool
        let lastSync: Date?
        let status: String

        enum CodingKeys: String, CodingKey {
            case id, type, email, status
            case isConnected = "is_connected"
            case lastSync = "last_sync"
        }
    }

    /// Fetch all connected services status
    func fetchConnectedServices() async throws -> [ConnectedService] {
        let request = try makeRequest(path: "/api/services/status", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        if httpResponse.statusCode == 404 {
            return []
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Failed to fetch services")
        }

        struct ServicesResponse: Codable {
            let services: [ConnectedService]
        }

        let servicesResponse = try decoder.decode(ServicesResponse.self, from: data)
        return servicesResponse.services
    }

    /// Get OAuth URL for Gmail connection
    func getGmailOAuthURL() async throws -> URL {
        let request = try makeRequest(path: "/api/services/gmail/auth-url", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct AuthURLResponse: Codable {
            let url: String
        }

        let authResponse = try decoder.decode(AuthURLResponse.self, from: data)
        guard let url = URL(string: authResponse.url) else {
            throw APIError.invalidURL
        }
        return url
    }

    /// Get OAuth URL for Calendar connection
    func getCalendarOAuthURL() async throws -> URL {
        let request = try makeRequest(path: "/api/services/calendar/auth-url", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct AuthURLResponse: Codable {
            let url: String
        }

        let authResponse = try decoder.decode(AuthURLResponse.self, from: data)
        guard let url = URL(string: authResponse.url) else {
            throw APIError.invalidURL
        }
        return url
    }

    /// Disconnect a service
    func disconnectService(type: String, accountId: String? = nil) async throws {
        var path = "/api/services/\(type)/disconnect"
        if let accountId = accountId {
            path += "?account_id=\(accountId)"
        }

        let request = try makeRequest(path: path, method: "POST")
        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    /// Get Plaid link token for bank connection
    func getPlaidLinkToken() async throws -> String {
        let request = try makeRequest(path: "/api/services/plaid/link-token", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }

        struct LinkTokenResponse: Codable {
            let linkToken: String

            enum CodingKeys: String, CodingKey {
                case linkToken = "link_token"
            }
        }

        let tokenResponse = try decoder.decode(LinkTokenResponse.self, from: data)
        return tokenResponse.linkToken
    }

    /// Exchange Plaid public token for access
    func exchangePlaidToken(publicToken: String, institutionId: String, accountIds: [String]) async throws {
        var request = try makeRequest(path: "/api/services/plaid/exchange", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "public_token": publicToken,
            "institution_id": institutionId,
            "account_ids": accountIds
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw APIError.invalidResponse
        }
    }

    // MARK: - API Keys Management

    /// API Keys status response
    struct APIKeysStatus: Codable {
        let openai: Bool
        let gemini: Bool
        let anthropic: Bool
        let taskade: Bool
    }

    /// Get status of configured API keys
    func getAPIKeysStatus() async throws -> APIKeysStatus {
        let request = try makeRequest(path: "/api/credentials/status", method: "GET")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // Return all false if endpoint doesn't exist yet
        if httpResponse.statusCode == 404 {
            return APIKeysStatus(openai: false, gemini: false, anthropic: false, taskade: false)
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw APIError.serverError(httpResponse.statusCode, "Failed to get API key status")
        }

        return try decoder.decode(APIKeysStatus.self, from: data)
    }

    /// Save an API key for a service
    func saveAPIKey(service: String, key: String) async throws {
        var request = try makeRequest(path: "/api/credentials/\(service)", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "api_key": key
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Failed to save API key"
            throw APIError.serverError(httpResponse.statusCode, message)
        }
    }

    /// Remove an API key for a service
    func removeAPIKey(service: String) async throws {
        let request = try makeRequest(path: "/api/credentials/\(service)", method: "DELETE")
        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            let message = String(data: data, encoding: .utf8) ?? "Failed to remove API key"
            throw APIError.serverError(httpResponse.statusCode, message)
        }
    }

    /// Validate an API key with the provider (optional check)
    func validateAPIKey(service: String, key: String) async throws -> Bool {
        var request = try makeRequest(path: "/api/credentials/\(service)/validate", method: "POST")
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let body: [String: Any] = [
            "api_key": key
        ]
        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse else {
            throw APIError.invalidResponse
        }

        // If validation endpoint doesn't exist, assume valid
        if httpResponse.statusCode == 404 {
            return true
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            return false
        }

        struct ValidationResponse: Codable {
            let valid: Bool
        }

        let validationResponse = try decoder.decode(ValidationResponse.self, from: data)
        return validationResponse.valid
    }
}

// MARK: - Color Extension for Hex

extension Color {
    init?(hex: String) {
        var hexSanitized = hex.trimmingCharacters(in: .whitespacesAndNewlines)
        hexSanitized = hexSanitized.replacingOccurrences(of: "#", with: "")

        var rgb: UInt64 = 0
        guard Scanner(string: hexSanitized).scanHexInt64(&rgb) else { return nil }

        let r = Double((rgb & 0xFF0000) >> 16) / 255.0
        let g = Double((rgb & 0x00FF00) >> 8) / 255.0
        let b = Double(rgb & 0x0000FF) / 255.0

        self.init(red: r, green: g, blue: b)
    }
}

// MARK: - API Errors

enum APIError: LocalizedError {
    case invalidURL
    case invalidResponse
    case unauthorized
    case tokenExpired
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
        case .tokenExpired:
            return "Session expired. Please sign in again."
        case .serverError(let code, let message):
            return "Server error (\(code)): \(message)"
        case .networkError(let error):
            return "Network error: \(error.localizedDescription)"
        case .decodingError(let error):
            return "Data error: \(error.localizedDescription)"
        }
    }
}

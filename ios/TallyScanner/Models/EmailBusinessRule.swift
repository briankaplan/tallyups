import Foundation

/// Rule for automatically mapping email domains to business types
struct EmailBusinessRule: Identifiable, Codable, Hashable {
    let id: String
    var emailPattern: String      // e.g., "@businessmusic.com" or "*@company.com"
    var businessType: String      // e.g., "Business"
    var priority: Int             // Higher priority rules match first
    var isActive: Bool
    var matchCount: Int           // How many times this rule has matched
    var createdAt: Date
    var updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id
        case emailPattern = "email_pattern"
        case businessType = "business_type"
        case priority
        case isActive = "is_active"
        case matchCount = "match_count"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decode(String.self, forKey: .id)
        emailPattern = try container.decode(String.self, forKey: .emailPattern)
        businessType = try container.decode(String.self, forKey: .businessType)
        priority = try container.decodeIfPresent(Int.self, forKey: .priority) ?? 0
        isActive = try container.decodeIfPresent(Bool.self, forKey: .isActive) ?? true
        matchCount = try container.decodeIfPresent(Int.self, forKey: .matchCount) ?? 0

        // Parse dates
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        if let createdStr = try container.decodeIfPresent(String.self, forKey: .createdAt) {
            createdAt = dateFormatter.date(from: createdStr) ?? Date()
        } else {
            createdAt = Date()
        }

        if let updatedStr = try container.decodeIfPresent(String.self, forKey: .updatedAt) {
            updatedAt = dateFormatter.date(from: updatedStr)
        } else {
            updatedAt = nil
        }
    }

    init(
        id: String = UUID().uuidString,
        emailPattern: String,
        businessType: String,
        priority: Int = 0,
        isActive: Bool = true,
        matchCount: Int = 0,
        createdAt: Date = Date(),
        updatedAt: Date? = nil
    ) {
        self.id = id
        self.emailPattern = emailPattern
        self.businessType = businessType
        self.priority = priority
        self.isActive = isActive
        self.matchCount = matchCount
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    /// Check if this rule matches the given email
    func matches(email: String) -> Bool {
        let pattern = emailPattern.lowercased()
        let testEmail = email.lowercased()

        // Simple domain match: "@domain.com"
        if pattern.hasPrefix("@") {
            return testEmail.hasSuffix(pattern)
        }

        // Wildcard match: "*@domain.com"
        if pattern.hasPrefix("*@") {
            let domain = String(pattern.dropFirst(1))
            return testEmail.hasSuffix(domain)
        }

        // Exact match
        if pattern == testEmail {
            return true
        }

        // Contains match: "domain.com"
        if testEmail.contains(pattern) {
            return true
        }

        return false
    }

    var displayPattern: String {
        if emailPattern.hasPrefix("@") {
            return "*\(emailPattern)"
        }
        return emailPattern
    }
}

// MARK: - Common Email Patterns

extension EmailBusinessRule {
    /// Common patterns for auto-detection
    static var suggestedPatterns: [String] {
        [
            "@gmail.com",
            "@icloud.com",
            "@yahoo.com",
            "@outlook.com",
            "@company.com",
            "@work.com"
        ]
    }
}

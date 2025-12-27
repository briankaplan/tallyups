import Foundation
import SwiftUI

/// Types of relationships between contacts
enum RelationshipType: String, Codable, CaseIterable, Identifiable {
    case coworker = "coworker"
    case family = "family"
    case friend = "friend"
    case client = "client"
    case vendor = "vendor"
    case travelCompanion = "travel_companion"
    case mealPartner = "meal_partner"
    case meetingAttendee = "meeting_attendee"
    case other = "other"

    var id: String { rawValue }

    var displayName: String {
        switch self {
        case .coworker: return "Co-worker"
        case .family: return "Family"
        case .friend: return "Friend"
        case .client: return "Client"
        case .vendor: return "Vendor"
        case .travelCompanion: return "Travel Companion"
        case .mealPartner: return "Meal Partner"
        case .meetingAttendee: return "Meeting Attendee"
        case .other: return "Other"
        }
    }

    var icon: String {
        switch self {
        case .coworker: return "briefcase.fill"
        case .family: return "house.fill"
        case .friend: return "person.2.fill"
        case .client: return "person.crop.circle.fill"
        case .vendor: return "shippingbox.fill"
        case .travelCompanion: return "airplane"
        case .mealPartner: return "fork.knife"
        case .meetingAttendee: return "calendar"
        case .other: return "person.fill"
        }
    }

    var color: Color {
        switch self {
        case .coworker: return .blue
        case .family: return .pink
        case .friend: return .green
        case .client: return .orange
        case .vendor: return .purple
        case .travelCompanion: return .cyan
        case .mealPartner: return .yellow
        case .meetingAttendee: return .indigo
        case .other: return .gray
        }
    }
}

/// A relationship between two contacts with context
struct ContactRelationship: Identifiable, Codable, Hashable {
    let id: String
    var contactId: Int
    var relatedContactId: Int?
    var relatedContactName: String?
    var type: RelationshipType
    var context: String?           // e.g., "Q4 Planning Meeting", "Nashville Trip"
    var transactionCount: Int      // Number of transactions together
    var firstEncounter: Date?
    var lastEncounter: Date?
    var isConfirmed: Bool          // User confirmed vs. AI suggested
    var confidence: Double         // AI confidence score

    enum CodingKeys: String, CodingKey {
        case id
        case contactId = "contact_id"
        case relatedContactId = "related_contact_id"
        case relatedContactName = "related_contact_name"
        case type
        case context
        case transactionCount = "transaction_count"
        case firstEncounter = "first_encounter"
        case lastEncounter = "last_encounter"
        case isConfirmed = "is_confirmed"
        case confidence
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decode(String.self, forKey: .id)
        contactId = try container.decode(Int.self, forKey: .contactId)
        relatedContactId = try container.decodeIfPresent(Int.self, forKey: .relatedContactId)
        relatedContactName = try container.decodeIfPresent(String.self, forKey: .relatedContactName)

        let typeString = try container.decode(String.self, forKey: .type)
        type = RelationshipType(rawValue: typeString) ?? .other

        context = try container.decodeIfPresent(String.self, forKey: .context)
        transactionCount = try container.decodeIfPresent(Int.self, forKey: .transactionCount) ?? 0
        isConfirmed = try container.decodeIfPresent(Bool.self, forKey: .isConfirmed) ?? false
        confidence = try container.decodeIfPresent(Double.self, forKey: .confidence) ?? 0.0

        // Parse dates
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        if let firstStr = try container.decodeIfPresent(String.self, forKey: .firstEncounter) {
            firstEncounter = dateFormatter.date(from: firstStr)
        } else {
            firstEncounter = nil
        }

        if let lastStr = try container.decodeIfPresent(String.self, forKey: .lastEncounter) {
            lastEncounter = dateFormatter.date(from: lastStr)
        } else {
            lastEncounter = nil
        }
    }

    init(
        id: String = UUID().uuidString,
        contactId: Int,
        relatedContactId: Int? = nil,
        relatedContactName: String? = nil,
        type: RelationshipType,
        context: String? = nil,
        transactionCount: Int = 0,
        firstEncounter: Date? = nil,
        lastEncounter: Date? = nil,
        isConfirmed: Bool = false,
        confidence: Double = 0.0
    ) {
        self.id = id
        self.contactId = contactId
        self.relatedContactId = relatedContactId
        self.relatedContactName = relatedContactName
        self.type = type
        self.context = context
        self.transactionCount = transactionCount
        self.firstEncounter = firstEncounter
        self.lastEncounter = lastEncounter
        self.isConfirmed = isConfirmed
        self.confidence = confidence
    }

    var formattedDateRange: String? {
        guard let first = firstEncounter else { return nil }

        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none

        if let last = lastEncounter, last != first {
            return "\(formatter.string(from: first)) - \(formatter.string(from: last))"
        }
        return formatter.string(from: first)
    }
}

/// A trip or event with associated contacts and transactions
struct TripEvent: Identifiable, Codable, Hashable {
    let id: String
    var name: String
    var startDate: Date
    var endDate: Date?
    var location: String?
    var attendeeIds: [Int]
    var transactionIndexes: [Int]
    var totalSpent: Double
    var category: TripCategory

    enum TripCategory: String, Codable, CaseIterable {
        case businessTrip = "business_trip"
        case vacation = "vacation"
        case conference = "conference"
        case meeting = "meeting"
        case familyEvent = "family_event"
        case other = "other"

        var displayName: String {
            switch self {
            case .businessTrip: return "Business Trip"
            case .vacation: return "Vacation"
            case .conference: return "Conference"
            case .meeting: return "Meeting"
            case .familyEvent: return "Family Event"
            case .other: return "Other"
            }
        }

        var icon: String {
            switch self {
            case .businessTrip: return "briefcase.fill"
            case .vacation: return "sun.max.fill"
            case .conference: return "person.3.fill"
            case .meeting: return "calendar"
            case .familyEvent: return "house.fill"
            case .other: return "folder.fill"
            }
        }
    }

    enum CodingKeys: String, CodingKey {
        case id, name
        case startDate = "start_date"
        case endDate = "end_date"
        case location
        case attendeeIds = "attendee_ids"
        case transactionIndexes = "transaction_indexes"
        case totalSpent = "total_spent"
        case category
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decode(String.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)

        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        if let startStr = try container.decodeIfPresent(String.self, forKey: .startDate) {
            startDate = dateFormatter.date(from: startStr) ?? Date()
        } else {
            startDate = Date()
        }

        if let endStr = try container.decodeIfPresent(String.self, forKey: .endDate) {
            endDate = dateFormatter.date(from: endStr)
        } else {
            endDate = nil
        }

        location = try container.decodeIfPresent(String.self, forKey: .location)
        attendeeIds = try container.decodeIfPresent([Int].self, forKey: .attendeeIds) ?? []
        transactionIndexes = try container.decodeIfPresent([Int].self, forKey: .transactionIndexes) ?? []
        totalSpent = try container.decodeIfPresent(Double.self, forKey: .totalSpent) ?? 0

        let categoryStr = try container.decodeIfPresent(String.self, forKey: .category) ?? "other"
        category = TripCategory(rawValue: categoryStr) ?? .other
    }

    init(
        id: String = UUID().uuidString,
        name: String,
        startDate: Date,
        endDate: Date? = nil,
        location: String? = nil,
        attendeeIds: [Int] = [],
        transactionIndexes: [Int] = [],
        totalSpent: Double = 0,
        category: TripCategory = .other
    ) {
        self.id = id
        self.name = name
        self.startDate = startDate
        self.endDate = endDate
        self.location = location
        self.attendeeIds = attendeeIds
        self.transactionIndexes = transactionIndexes
        self.totalSpent = totalSpent
        self.category = category
    }

    var formattedDateRange: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none

        if let end = endDate {
            return "\(formatter.string(from: startDate)) - \(formatter.string(from: end))"
        }
        return formatter.string(from: startDate)
    }

    var formattedTotalSpent: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: totalSpent)) ?? "$0.00"
    }
}

/// Smart contact with enhanced relationship tracking
struct SmartContact: Identifiable, Codable, Hashable {
    let id: Int
    var name: String
    var email: String?
    var phone: String?
    var company: String?
    var jobTitle: String?
    var tags: [String]
    var relationships: [ContactRelationship]
    var transactionCount: Int
    var totalSpent: Double
    var lastInteraction: Date?
    var frequencyScore: Double     // How often we interact (0-1)
    var importanceScore: Double    // Calculated importance (0-1)

    enum CodingKeys: String, CodingKey {
        case id, name, email, phone, company
        case jobTitle = "job_title"
        case tags, relationships
        case transactionCount = "transaction_count"
        case totalSpent = "total_spent"
        case lastInteraction = "last_interaction"
        case frequencyScore = "frequency_score"
        case importanceScore = "importance_score"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decode(Int.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        email = try container.decodeIfPresent(String.self, forKey: .email)
        phone = try container.decodeIfPresent(String.self, forKey: .phone)
        company = try container.decodeIfPresent(String.self, forKey: .company)
        jobTitle = try container.decodeIfPresent(String.self, forKey: .jobTitle)
        tags = try container.decodeIfPresent([String].self, forKey: .tags) ?? []
        relationships = try container.decodeIfPresent([ContactRelationship].self, forKey: .relationships) ?? []
        transactionCount = try container.decodeIfPresent(Int.self, forKey: .transactionCount) ?? 0
        totalSpent = try container.decodeIfPresent(Double.self, forKey: .totalSpent) ?? 0
        frequencyScore = try container.decodeIfPresent(Double.self, forKey: .frequencyScore) ?? 0
        importanceScore = try container.decodeIfPresent(Double.self, forKey: .importanceScore) ?? 0

        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        if let lastStr = try container.decodeIfPresent(String.self, forKey: .lastInteraction) {
            lastInteraction = dateFormatter.date(from: lastStr)
        } else {
            lastInteraction = nil
        }
    }

    init(
        id: Int,
        name: String,
        email: String? = nil,
        phone: String? = nil,
        company: String? = nil,
        jobTitle: String? = nil,
        tags: [String] = [],
        relationships: [ContactRelationship] = [],
        transactionCount: Int = 0,
        totalSpent: Double = 0,
        lastInteraction: Date? = nil,
        frequencyScore: Double = 0,
        importanceScore: Double = 0
    ) {
        self.id = id
        self.name = name
        self.email = email
        self.phone = phone
        self.company = company
        self.jobTitle = jobTitle
        self.tags = tags
        self.relationships = relationships
        self.transactionCount = transactionCount
        self.totalSpent = totalSpent
        self.lastInteraction = lastInteraction
        self.frequencyScore = frequencyScore
        self.importanceScore = importanceScore
    }

    var displayName: String {
        if !name.isEmpty {
            return name
        } else if let company = company, !company.isEmpty {
            return company
        } else if let email = email {
            return email
        }
        return "Unknown"
    }

    var initials: String {
        let components = name.split(separator: " ")
        if components.count >= 2 {
            return "\(components[0].prefix(1))\(components[1].prefix(1))".uppercased()
        } else if let first = components.first {
            return String(first.prefix(2)).uppercased()
        }
        return "?"
    }

    var primaryRelationship: RelationshipType? {
        relationships.max(by: { $0.transactionCount < $1.transactionCount })?.type
    }

    var formattedTotalSpent: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: totalSpent)) ?? "$0.00"
    }

    /// Convert from basic AppContact
    static func from(_ contact: AppContact) -> SmartContact {
        SmartContact(
            id: contact.id,
            name: contact.name,
            email: contact.email,
            phone: contact.phone,
            company: contact.company,
            tags: contact.tags
        )
    }
}

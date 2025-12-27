import Foundation
import SwiftUI

/// Represents a project for expense tracking
struct Project: Identifiable, Codable, Hashable {
    let id: String
    var name: String
    var description: String?
    var color: String
    var icon: String
    var budget: Double?
    var startDate: Date?
    var endDate: Date?
    var isActive: Bool
    var transactionCount: Int
    var totalSpent: Double
    var createdAt: Date
    var updatedAt: Date?

    enum CodingKeys: String, CodingKey {
        case id, name, description, color, icon, budget
        case startDate = "start_date"
        case endDate = "end_date"
        case isActive = "is_active"
        case transactionCount = "transaction_count"
        case totalSpent = "total_spent"
        case createdAt = "created_at"
        case updatedAt = "updated_at"
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decode(String.self, forKey: .id)
        name = try container.decode(String.self, forKey: .name)
        description = try container.decodeIfPresent(String.self, forKey: .description)
        color = try container.decodeIfPresent(String.self, forKey: .color) ?? "#00FF88"
        icon = try container.decodeIfPresent(String.self, forKey: .icon) ?? "folder.fill"
        budget = try container.decodeIfPresent(Double.self, forKey: .budget)
        isActive = try container.decodeIfPresent(Bool.self, forKey: .isActive) ?? true
        transactionCount = try container.decodeIfPresent(Int.self, forKey: .transactionCount) ?? 0
        totalSpent = try container.decodeIfPresent(Double.self, forKey: .totalSpent) ?? 0

        // Parse dates
        let dateFormatter = ISO8601DateFormatter()
        dateFormatter.formatOptions = [.withInternetDateTime, .withFractionalSeconds]

        if let startDateStr = try container.decodeIfPresent(String.self, forKey: .startDate) {
            startDate = dateFormatter.date(from: startDateStr) ?? Date()
        } else {
            startDate = nil
        }

        if let endDateStr = try container.decodeIfPresent(String.self, forKey: .endDate) {
            endDate = dateFormatter.date(from: endDateStr)
        } else {
            endDate = nil
        }

        if let createdAtStr = try container.decodeIfPresent(String.self, forKey: .createdAt) {
            createdAt = dateFormatter.date(from: createdAtStr) ?? Date()
        } else {
            createdAt = Date()
        }

        if let updatedAtStr = try container.decodeIfPresent(String.self, forKey: .updatedAt) {
            updatedAt = dateFormatter.date(from: updatedAtStr)
        } else {
            updatedAt = nil
        }
    }

    init(
        id: String = UUID().uuidString,
        name: String,
        description: String? = nil,
        color: String = "#00FF88",
        icon: String = "folder.fill",
        budget: Double? = nil,
        startDate: Date? = nil,
        endDate: Date? = nil,
        isActive: Bool = true,
        transactionCount: Int = 0,
        totalSpent: Double = 0,
        createdAt: Date = Date(),
        updatedAt: Date? = nil
    ) {
        self.id = id
        self.name = name
        self.description = description
        self.color = color
        self.icon = icon
        self.budget = budget
        self.startDate = startDate
        self.endDate = endDate
        self.isActive = isActive
        self.transactionCount = transactionCount
        self.totalSpent = totalSpent
        self.createdAt = createdAt
        self.updatedAt = updatedAt
    }

    // MARK: - Computed Properties

    var swiftUIColor: Color {
        Color(hex: color) ?? .tallyAccent
    }

    var budgetProgress: Double? {
        guard let budget = budget, budget > 0 else { return nil }
        return min(totalSpent / budget, 1.0)
    }

    var budgetRemaining: Double? {
        guard let budget = budget else { return nil }
        return max(budget - totalSpent, 0)
    }

    var isOverBudget: Bool {
        guard let budget = budget else { return false }
        return totalSpent > budget
    }

    var formattedBudget: String? {
        guard let budget = budget else { return nil }
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: budget))
    }

    var formattedTotalSpent: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: totalSpent)) ?? "$0.00"
    }

    var dateRangeText: String? {
        guard let start = startDate else { return nil }

        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        formatter.timeStyle = .none

        if let end = endDate {
            return "\(formatter.string(from: start)) - \(formatter.string(from: end))"
        } else {
            return "Started \(formatter.string(from: start))"
        }
    }
}

// MARK: - Project Templates

extension Project {
    /// Common project templates
    static var templates: [Project] {
        [
            Project(
                name: "Business Trip",
                description: "Travel expenses for business",
                color: "#4A90D9",
                icon: "airplane"
            ),
            Project(
                name: "Client Project",
                description: "Expenses for a specific client",
                color: "#E91E63",
                icon: "briefcase.fill"
            ),
            Project(
                name: "Home Office",
                description: "Work from home expenses",
                color: "#9C27B0",
                icon: "house.fill"
            ),
            Project(
                name: "Marketing Campaign",
                description: "Marketing and advertising expenses",
                color: "#FF9800",
                icon: "megaphone.fill"
            ),
            Project(
                name: "Equipment",
                description: "Hardware and equipment purchases",
                color: "#607D8B",
                icon: "desktopcomputer"
            ),
            Project(
                name: "Training",
                description: "Education and training costs",
                color: "#00BCD4",
                icon: "book.fill"
            )
        ]
    }
}

// MARK: - Project Icons

extension Project {
    static var availableIcons: [String] {
        [
            "folder.fill",
            "briefcase.fill",
            "airplane",
            "car.fill",
            "house.fill",
            "building.2.fill",
            "desktopcomputer",
            "laptopcomputer",
            "iphone",
            "camera.fill",
            "film",
            "music.note",
            "book.fill",
            "graduationcap.fill",
            "stethoscope",
            "wrench.and.screwdriver.fill",
            "hammer.fill",
            "paintbrush.fill",
            "megaphone.fill",
            "chart.bar.fill",
            "gift.fill",
            "heart.fill",
            "star.fill",
            "flag.fill",
            "map.fill",
            "globe",
            "leaf.fill",
            "flame.fill",
            "bolt.fill",
            "sparkles"
        ]
    }

    static var availableColors: [String] {
        [
            "#00FF88",  // Tally Green
            "#4A90D9",  // Blue
            "#E91E63",  // Pink
            "#9C27B0",  // Purple
            "#673AB7",  // Deep Purple
            "#3F51B5",  // Indigo
            "#00BCD4",  // Cyan
            "#009688",  // Teal
            "#4CAF50",  // Green
            "#8BC34A",  // Light Green
            "#CDDC39",  // Lime
            "#FFEB3B",  // Yellow
            "#FFC107",  // Amber
            "#FF9800",  // Orange
            "#FF5722",  // Deep Orange
            "#795548",  // Brown
            "#607D8B",  // Blue Grey
            "#F44336"   // Red
        ]
    }
}

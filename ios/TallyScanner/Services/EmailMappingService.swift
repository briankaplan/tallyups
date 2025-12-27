import Foundation
import SwiftUI

/// Service for managing email-to-business-type mapping rules
@MainActor
class EmailMappingService: ObservableObject {
    static let shared = EmailMappingService()

    @Published var rules: [EmailBusinessRule] = []
    @Published var isLoading = false
    @Published var error: String?

    private init() {}

    // MARK: - Load Rules

    func loadRules() async {
        guard !isLoading else { return }

        isLoading = true
        error = nil

        do {
            rules = try await APIClient.shared.fetchEmailMappingRules()
            // Sort by priority (highest first)
            rules.sort { $0.priority > $1.priority }
            print("📧 EmailMappingService: Loaded \(rules.count) rules")
        } catch {
            self.error = error.localizedDescription
            print("📧 EmailMappingService: Failed to load rules: \(error)")
        }

        isLoading = false
    }

    func loadIfNeeded() async {
        if rules.isEmpty {
            await loadRules()
        }
    }

    // MARK: - CRUD Operations

    func createRule(
        emailPattern: String,
        businessType: String,
        priority: Int = 0
    ) async -> EmailBusinessRule? {
        do {
            let rule = try await APIClient.shared.createEmailMappingRule(
                emailPattern: emailPattern,
                businessType: businessType,
                priority: priority
            )

            rules.append(rule)
            rules.sort { $0.priority > $1.priority }

            print("📧 EmailMappingService: Created rule '\(emailPattern)' -> '\(businessType)'")
            return rule
        } catch {
            self.error = error.localizedDescription
            print("📧 EmailMappingService: Failed to create rule: \(error)")
            return nil
        }
    }

    func updateRule(_ rule: EmailBusinessRule) async -> Bool {
        do {
            let updated = try await APIClient.shared.updateEmailMappingRule(rule)

            if let index = rules.firstIndex(where: { $0.id == rule.id }) {
                rules[index] = updated
            }

            rules.sort { $0.priority > $1.priority }
            print("📧 EmailMappingService: Updated rule '\(rule.emailPattern)'")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📧 EmailMappingService: Failed to update rule: \(error)")
            return false
        }
    }

    func deleteRule(id: String) async -> Bool {
        do {
            try await APIClient.shared.deleteEmailMappingRule(id: id)

            rules.removeAll { $0.id == id }

            print("📧 EmailMappingService: Deleted rule \(id)")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📧 EmailMappingService: Failed to delete rule: \(error)")
            return false
        }
    }

    func toggleRule(id: String) async -> Bool {
        guard var rule = rules.first(where: { $0.id == id }) else {
            return false
        }

        rule.isActive.toggle()
        return await updateRule(rule)
    }

    // MARK: - Matching

    /// Find the best matching business type for an email
    func matchBusinessType(for email: String) -> String? {
        // Filter active rules, sorted by priority
        let activeRules = rules.filter { $0.isActive }.sorted { $0.priority > $1.priority }

        for rule in activeRules {
            if rule.matches(email: email) {
                return rule.businessType
            }
        }

        return nil
    }

    /// Get all matching rules for an email (for debugging/display)
    func matchingRules(for email: String) -> [EmailBusinessRule] {
        rules.filter { $0.isActive && $0.matches(email: email) }
            .sorted { $0.priority > $1.priority }
    }

    // MARK: - Helpers

    func rule(withId id: String) -> EmailBusinessRule? {
        rules.first { $0.id == id }
    }

    /// Get unique business types from all rules
    var usedBusinessTypes: [String] {
        Array(Set(rules.map { $0.businessType })).sorted()
    }

    /// Get rules for a specific business type
    func rules(for businessType: String) -> [EmailBusinessRule] {
        rules.filter { $0.businessType.lowercased() == businessType.lowercased() }
    }
}

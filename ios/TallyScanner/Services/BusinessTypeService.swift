import SwiftUI

/// Shared service for managing user's business types
/// Provides consistent coloring and naming across all views
@MainActor
class BusinessTypeService: ObservableObject {
    static let shared = BusinessTypeService()

    @Published var businessTypes: [APIClient.BusinessType] = []
    @Published var isLoading = false

    private var hasLoaded = false

    private init() {}

    // MARK: - Loading

    /// Load business types from API (calls once, caches result)
    func loadIfNeeded() async {
        guard !hasLoaded, !isLoading else { return }

        isLoading = true

        do {
            businessTypes = try await APIClient.shared.fetchBusinessTypes()
            hasLoaded = true
            print("💼 BusinessTypeService: Loaded \(businessTypes.count) business types")
        } catch {
            print("💼 BusinessTypeService: Failed to load: \(error)")
            // Use defaults on error
            businessTypes = defaultTypes
            hasLoaded = true
        }

        isLoading = false
    }

    /// Force reload from API
    func reload() async {
        hasLoaded = false
        await loadIfNeeded()
    }

    // MARK: - Helpers

    /// Get color for a business type name
    func color(for name: String?) -> Color {
        guard let name = name else { return .gray }

        if let type = businessTypes.first(where: {
            $0.name.lowercased() == name.lowercased() ||
            $0.displayName.lowercased() == name.lowercased()
        }) {
            return type.swiftUIColor
        }

        // Fallback colors for legacy data
        return legacyColor(for: name)
    }

    /// Get display name for a business type
    func displayName(for name: String?) -> String {
        guard let name = name else { return "Personal" }

        if let type = businessTypes.first(where: {
            $0.name.lowercased() == name.lowercased() ||
            $0.displayName.lowercased() == name.lowercased()
        }) {
            return type.displayName
        }

        return name
    }

    /// Get short name for display (abbreviate long names)
    func shortName(for name: String?) -> String {
        guard let name = name else { return "" }

        if let type = businessTypes.first(where: {
            $0.name.lowercased() == name.lowercased() ||
            $0.displayName.lowercased() == name.lowercased()
        }) {
            if type.displayName.count > 12 {
                // Abbreviate: "Music City Rodeo" -> "MCR"
                return String(type.displayName.split(separator: " ").map { $0.prefix(1) }.joined())
            }
            return type.displayName
        }

        return name
    }

    /// Get icon for a business type
    func icon(for name: String?) -> String {
        guard let name = name else { return "briefcase" }

        if let type = businessTypes.first(where: {
            $0.name.lowercased() == name.lowercased() ||
            $0.displayName.lowercased() == name.lowercased()
        }) {
            return type.icon
        }

        return "briefcase"
    }

    // MARK: - Defaults & Legacy

    private var defaultTypes: [APIClient.BusinessType] {
        [
            APIClient.BusinessType(
                id: 0, name: "Personal", displayName: "Personal",
                color: "#00FF88", icon: "person.fill", isDefault: true, sortOrder: 1
            ),
            APIClient.BusinessType(
                id: 1, name: "Business", displayName: "Business",
                color: "#4A90D9", icon: "briefcase.fill", isDefault: false, sortOrder: 2
            )
        ]
    }

    /// Legacy color mapping for existing data
    private func legacyColor(for name: String) -> Color {
        switch name.lowercased() {
        case "personal": return Color(hex: "#00FF88") ?? .green
        case "down home", "downhome", "down_home": return .orange
        case "music city rodeo", "mcr", "music_city_rodeo": return .purple
        case "em.co", "emco": return .teal
        case "business": return Color(hex: "#4A90D9") ?? .blue
        default: return .gray
        }
    }
}

// MARK: - Business Type Badge View

struct BusinessTypeBadge: View {
    let name: String?
    @ObservedObject private var service = BusinessTypeService.shared

    var body: some View {
        if let name = name, !name.isEmpty {
            HStack(spacing: 3) {
                Image(systemName: service.icon(for: name))
                    .font(.system(size: 8))
                Text(service.shortName(for: name))
            }
            .font(.caption2.weight(.medium))
            .foregroundColor(.white)
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .background(service.color(for: name))
            .cornerRadius(4)
        }
    }
}

// MARK: - AI Suggestion Badge

struct AISuggestionBadge: View {
    let text: String
    let confidence: Double
    let onAccept: () -> Void
    let onReject: () -> Void

    @State private var isExpanded = false

    var body: some View {
        HStack(spacing: 6) {
            // AI sparkle icon
            Image(systemName: "sparkles")
                .font(.caption2)
                .foregroundColor(.purple)

            Text(text)
                .font(.caption)
                .foregroundColor(.white)

            if confidence >= 0.8 {
                Image(systemName: "checkmark.seal.fill")
                    .font(.caption2)
                    .foregroundColor(.green)
            }

            Spacer()

            // Accept/Reject buttons
            if isExpanded {
                Button(action: {
                    HapticService.shared.impact(.light)
                    onAccept()
                }) {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.subheadline)
                        .foregroundColor(.green)
                }

                Button(action: {
                    HapticService.shared.impact(.light)
                    onReject()
                }) {
                    Image(systemName: "xmark.circle.fill")
                        .font(.subheadline)
                        .foregroundColor(.red.opacity(0.7))
                }
            } else {
                Image(systemName: "chevron.right")
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
        }
        .padding(.horizontal, 10)
        .padding(.vertical, 6)
        .background(
            LinearGradient(
                colors: [Color.purple.opacity(0.2), Color.blue.opacity(0.1)],
                startPoint: .leading,
                endPoint: .trailing
            )
        )
        .cornerRadius(8)
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .strokeBorder(Color.purple.opacity(0.3), lineWidth: 1)
        )
        .onTapGesture {
            withAnimation(.spring(response: 0.3)) {
                isExpanded.toggle()
            }
        }
    }
}

// MARK: - Category Suggestion Row

struct CategorySuggestionRow: View {
    let category: String
    let confidence: Double
    let onAccept: () -> Void

    var body: some View {
        Button(action: onAccept) {
            HStack(spacing: 8) {
                Image(systemName: "sparkles")
                    .font(.caption)
                    .foregroundColor(.purple)

                Text("AI suggests: \(category)")
                    .font(.caption)
                    .foregroundColor(.white.opacity(0.9))

                Spacer()

                // Confidence indicator
                HStack(spacing: 2) {
                    ForEach(0..<5) { i in
                        Circle()
                            .fill(Double(i) / 5.0 < confidence ? Color.purple : Color.gray.opacity(0.3))
                            .frame(width: 4, height: 4)
                    }
                }

                Text("Apply")
                    .font(.caption.bold())
                    .foregroundColor(.purple)
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color.purple.opacity(0.1))
            .cornerRadius(8)
        }
        .buttonStyle(.plain)
    }
}

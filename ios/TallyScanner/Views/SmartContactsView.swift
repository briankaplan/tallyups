import SwiftUI

/// Enhanced contacts view with smart relationship tracking
struct SmartContactsView: View {
    @StateObject private var contactsService = ContactsService.shared

    @State private var searchText = ""
    @State private var selectedFilter: ContactFilter = .all
    @State private var selectedContact: SmartContact?
    @State private var showingAddRelationship = false

    enum ContactFilter: String, CaseIterable {
        case all = "All"
        case coworkers = "Co-workers"
        case family = "Family"
        case clients = "Clients"
        case travelCompanions = "Travel"
        case frequent = "Frequent"
    }

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Filter Pills
                    filterPills

                    // Contacts List
                    if filteredContacts.isEmpty && !contactsService.isLoading {
                        emptyStateView
                    } else {
                        contactsList
                    }
                }
            }
            .navigationTitle("Contacts")
            .navigationBarTitleDisplayMode(.large)
            .searchable(text: $searchText, prompt: "Search contacts...")
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Menu {
                        Button(action: syncContacts) {
                            Label("Sync Contacts", systemImage: "arrow.triangle.2.circlepath")
                        }
                        Button(action: { showingAddRelationship = true }) {
                            Label("Add Relationship", systemImage: "person.2.badge.plus")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle.fill")
                            .foregroundColor(.tallyAccent)
                    }
                }
            }
            .sheet(item: $selectedContact) { contact in
                SmartContactDetailSheet(contact: contact)
            }
            .task {
                await contactsService.syncContacts()
            }
        }
    }

    private var filterPills: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(ContactFilter.allCases, id: \.self) { filter in
                    Button(action: { selectedFilter = filter }) {
                        Text(filter.rawValue)
                            .font(.subheadline.weight(.medium))
                            .foregroundColor(selectedFilter == filter ? .black : .white)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(selectedFilter == filter ? Color.tallyAccent : Color.white.opacity(0.1))
                            .cornerRadius(20)
                    }
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 12)
        }
    }

    private var contactsList: some View {
        List {
            // Frequent Contacts Section
            if selectedFilter == .all && !frequentContacts.isEmpty {
                Section {
                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 16) {
                            ForEach(frequentContacts) { contact in
                                FrequentContactCard(contact: contact)
                                    .onTapGesture {
                                        selectedContact = contact
                                    }
                            }
                        }
                        .padding(.horizontal)
                    }
                } header: {
                    Text("Frequent")
                        .font(.headline)
                        .foregroundColor(.white)
                }
                .listRowBackground(Color.clear)
                .listRowInsets(EdgeInsets())
            }

            // All Contacts
            Section {
                ForEach(filteredContacts) { contact in
                    SmartContactRow(contact: contact)
                        .onTapGesture {
                            selectedContact = contact
                        }
                        .listRowBackground(Color.clear)
                        .listRowSeparator(.hidden)
                }
            } header: {
                if selectedFilter != .all {
                    Text("\(selectedFilter.rawValue) (\(filteredContacts.count))")
                        .font(.headline)
                        .foregroundColor(.white)
                }
            }
        }
        .listStyle(.plain)
        .refreshable {
            await contactsService.syncContacts()
        }
    }

    private var emptyStateView: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "person.crop.circle.badge.questionmark")
                .font(.system(size: 60))
                .foregroundColor(.gray)

            Text("No Contacts Found")
                .font(.title2.bold())
                .foregroundColor(.white)

            Text("Sync your contacts or add relationships\nto track who you meet with.")
                .font(.subheadline)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Button(action: syncContacts) {
                HStack {
                    Image(systemName: "arrow.triangle.2.circlepath")
                    Text("Sync Contacts")
                }
                .font(.headline)
                .foregroundColor(.black)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }

            Spacer()
        }
    }

    // MARK: - Computed Properties

    private var filteredContacts: [SmartContact] {
        let smartContacts = contactsService.contacts.map { SmartContact.from($0) }

        var filtered = smartContacts

        // Apply search filter
        if !searchText.isEmpty {
            let query = searchText.lowercased()
            filtered = filtered.filter {
                $0.name.lowercased().contains(query) ||
                ($0.email?.lowercased().contains(query) ?? false) ||
                ($0.company?.lowercased().contains(query) ?? false)
            }
        }

        // Apply category filter
        switch selectedFilter {
        case .all:
            break
        case .coworkers:
            filtered = filtered.filter { $0.primaryRelationship == .coworker || $0.tags.contains("coworker") }
        case .family:
            filtered = filtered.filter { $0.primaryRelationship == .family || $0.tags.contains("family") }
        case .clients:
            filtered = filtered.filter { $0.primaryRelationship == .client || $0.tags.contains("client") }
        case .travelCompanions:
            filtered = filtered.filter { $0.primaryRelationship == .travelCompanion || $0.tags.contains("travel") }
        case .frequent:
            filtered = filtered.filter { $0.frequencyScore > 0.5 || $0.transactionCount > 5 }
        }

        return filtered.sorted { $0.name < $1.name }
    }

    private var frequentContacts: [SmartContact] {
        let smartContacts = contactsService.contacts.map { SmartContact.from($0) }
        return Array(smartContacts
            .filter { $0.transactionCount > 0 || $0.frequencyScore > 0.3 }
            .sorted { $0.frequencyScore > $1.frequencyScore }
            .prefix(8))
    }

    private func syncContacts() {
        Task {
            await contactsService.syncContacts()
            HapticService.shared.notification(.success)
        }
    }
}

// MARK: - Frequent Contact Card

struct FrequentContactCard: View {
    let contact: SmartContact

    var body: some View {
        VStack(spacing: 8) {
            // Avatar
            ZStack {
                Circle()
                    .fill(Color(hex: contact.avatarColor) ?? .gray)
                    .frame(width: 50, height: 50)

                Text(contact.initials)
                    .font(.headline.bold())
                    .foregroundColor(.white)

                // Relationship badge
                if let relationship = contact.primaryRelationship {
                    Image(systemName: relationship.icon)
                        .font(.caption2)
                        .foregroundColor(.white)
                        .padding(4)
                        .background(relationship.color)
                        .clipShape(Circle())
                        .offset(x: 18, y: 18)
                }
            }

            Text(contact.name.components(separatedBy: " ").first ?? contact.name)
                .font(.caption)
                .foregroundColor(.white)
                .lineLimit(1)
        }
        .frame(width: 70)
    }

    private var avatarColor: String {
        let colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD"]
        let hash = abs(contact.name.hashValue)
        return colors[hash % colors.count]
    }
}

// MARK: - Smart Contact Row

struct SmartContactRow: View {
    let contact: SmartContact

    var body: some View {
        HStack(spacing: 12) {
            // Avatar
            ZStack {
                Circle()
                    .fill(Color(hex: contact.avatarColor) ?? .gray)
                    .frame(width: 44, height: 44)

                Text(contact.initials)
                    .font(.subheadline.bold())
                    .foregroundColor(.white)
            }

            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(contact.displayName)
                        .font(.headline)
                        .foregroundColor(.white)

                    if let relationship = contact.primaryRelationship {
                        RelationshipBadge(type: relationship)
                    }
                }

                HStack(spacing: 8) {
                    if let company = contact.company, !company.isEmpty {
                        Text(company)
                            .font(.caption)
                            .foregroundColor(.gray)
                    }

                    if contact.transactionCount > 0 {
                        HStack(spacing: 2) {
                            Image(systemName: "receipt")
                                .font(.caption2)
                            Text("\(contact.transactionCount)")
                                .font(.caption)
                        }
                        .foregroundColor(.gray)
                    }
                }
            }

            Spacer()

            // Frequency indicator
            if contact.frequencyScore > 0 {
                FrequencyIndicator(score: contact.frequencyScore)
            }

            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding()
        .background(Color.white.opacity(0.05))
        .cornerRadius(12)
    }

    private var avatarColor: String {
        let colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD"]
        let hash = abs(contact.name.hashValue)
        return colors[hash % colors.count]
    }
}

// MARK: - Relationship Badge

struct RelationshipBadge: View {
    let type: RelationshipType

    var body: some View {
        HStack(spacing: 3) {
            Image(systemName: type.icon)
                .font(.system(size: 8))
            Text(type.displayName)
                .font(.caption2.weight(.medium))
        }
        .foregroundColor(.white)
        .padding(.horizontal, 6)
        .padding(.vertical, 2)
        .background(type.color)
        .cornerRadius(4)
    }
}

// MARK: - Frequency Indicator

struct FrequencyIndicator: View {
    let score: Double

    var body: some View {
        HStack(spacing: 2) {
            ForEach(0..<3) { i in
                Circle()
                    .fill(Double(i) / 3.0 < score ? Color.tallyAccent : Color.gray.opacity(0.3))
                    .frame(width: 6, height: 6)
            }
        }
    }
}

// MARK: - Smart Contact Detail Sheet

private struct SmartContactDetailSheet: View {
    let contact: SmartContact
    @Environment(\.dismiss) private var dismiss

    @State private var showingAddRelationship = false
    @State private var showingAddToTrip = false

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // Header
                        contactHeader

                        // Stats
                        statsSection

                        // Relationships
                        relationshipsSection

                        // Actions
                        actionsSection
                    }
                    .padding()
                }
            }
            .navigationTitle("Contact")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Done") { dismiss() }
                        .foregroundColor(.tallyAccent)
                }
            }
            .sheet(isPresented: $showingAddRelationship) {
                AddRelationshipView(contact: contact)
            }
        }
    }

    private var contactHeader: some View {
        VStack(spacing: 16) {
            // Large Avatar
            ZStack {
                Circle()
                    .fill(Color(hex: avatarColor) ?? .gray)
                    .frame(width: 80, height: 80)

                Text(contact.initials)
                    .font(.title.bold())
                    .foregroundColor(.white)
            }

            VStack(spacing: 4) {
                Text(contact.displayName)
                    .font(.title2.bold())
                    .foregroundColor(.white)

                if let company = contact.company {
                    Text(company)
                        .font(.subheadline)
                        .foregroundColor(.gray)
                }

                if let email = contact.email {
                    Text(email)
                        .font(.caption)
                        .foregroundColor(.tallyAccent)
                }
            }

            // Primary Relationship Badge
            if let relationship = contact.primaryRelationship {
                HStack(spacing: 6) {
                    Image(systemName: relationship.icon)
                    Text(relationship.displayName)
                }
                .font(.subheadline.weight(.medium))
                .foregroundColor(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(relationship.color)
                .cornerRadius(20)
            }
        }
    }

    private var statsSection: some View {
        HStack(spacing: 20) {
            ContactStatCard(
                icon: "receipt",
                value: "\(contact.transactionCount)",
                label: "Transactions"
            )

            ContactStatCard(
                icon: "dollarsign.circle",
                value: contact.formattedTotalSpent,
                label: "Total Spent"
            )

            ContactStatCard(
                icon: "chart.line.uptrend.xyaxis",
                value: "\(Int(contact.frequencyScore * 100))%",
                label: "Frequency"
            )
        }
    }

    private var relationshipsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Relationships")
                    .font(.headline)
                    .foregroundColor(.white)

                Spacer()

                Button(action: { showingAddRelationship = true }) {
                    Image(systemName: "plus.circle.fill")
                        .foregroundColor(.tallyAccent)
                }
            }

            if contact.relationships.isEmpty {
                Text("No relationships added yet")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color.white.opacity(0.05))
                    .cornerRadius(12)
            } else {
                ForEach(contact.relationships) { relationship in
                    RelationshipRow(relationship: relationship)
                }
            }
        }
    }

    private var actionsSection: some View {
        VStack(spacing: 12) {
            Button(action: { showingAddRelationship = true }) {
                HStack {
                    Image(systemName: "person.2.badge.plus")
                    Text("Add Relationship")
                }
                .font(.headline)
                .foregroundColor(.tallyAccent)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.tallyAccent.opacity(0.1))
                .cornerRadius(12)
            }

            Button(action: { showingAddToTrip = true }) {
                HStack {
                    Image(systemName: "airplane")
                    Text("Add to Trip")
                }
                .font(.headline)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.white.opacity(0.1))
                .cornerRadius(12)
            }
        }
    }

    private var avatarColor: String {
        let colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD"]
        let hash = abs(contact.name.hashValue)
        return colors[hash % colors.count]
    }
}

// MARK: - Contact Stat Card

private struct ContactStatCard: View {
    let icon: String
    let value: String
    let label: String

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(.tallyAccent)

            Text(value)
                .font(.headline)
                .foregroundColor(.white)

            Text(label)
                .font(.caption)
                .foregroundColor(.gray)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color.white.opacity(0.05))
        .cornerRadius(12)
    }
}

// MARK: - Relationship Row

struct RelationshipRow: View {
    let relationship: ContactRelationship

    var body: some View {
        HStack {
            Image(systemName: relationship.type.icon)
                .foregroundColor(relationship.type.color)
                .frame(width: 30)

            VStack(alignment: .leading, spacing: 2) {
                Text(relationship.type.displayName)
                    .font(.subheadline.weight(.medium))
                    .foregroundColor(.white)

                if let context = relationship.context {
                    Text(context)
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }

            Spacer()

            if relationship.transactionCount > 0 {
                Text("\(relationship.transactionCount) txns")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            if relationship.isConfirmed {
                Image(systemName: "checkmark.seal.fill")
                    .font(.caption)
                    .foregroundColor(.green)
            }
        }
        .padding()
        .background(Color.white.opacity(0.05))
        .cornerRadius(12)
    }
}

// MARK: - Add Relationship View

struct AddRelationshipView: View {
    let contact: SmartContact
    @Environment(\.dismiss) private var dismiss

    @State private var selectedType: RelationshipType = .coworker
    @State private var context = ""

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 24) {
                    // Relationship Type Selection
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Relationship Type")
                            .font(.headline)
                            .foregroundColor(.white)

                        LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                            ForEach(RelationshipType.allCases) { type in
                                Button(action: { selectedType = type }) {
                                    HStack {
                                        Image(systemName: type.icon)
                                        Text(type.displayName)
                                            .font(.subheadline)
                                    }
                                    .foregroundColor(selectedType == type ? .black : .white)
                                    .frame(maxWidth: .infinity)
                                    .padding()
                                    .background(selectedType == type ? type.color : Color.white.opacity(0.1))
                                    .cornerRadius(12)
                                }
                            }
                        }
                    }

                    // Context
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Context (Optional)")
                            .font(.headline)
                            .foregroundColor(.white)

                        TextField("e.g., Q4 Planning, Nashville Trip", text: $context)
                            .padding()
                            .background(Color.white.opacity(0.1))
                            .cornerRadius(12)
                            .foregroundColor(.white)
                    }

                    Spacer()

                    // Save Button
                    Button(action: saveRelationship) {
                        Text("Add Relationship")
                            .font(.headline)
                            .foregroundColor(.black)
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.tallyAccent)
                            .cornerRadius(12)
                    }
                }
                .padding()
            }
            .navigationTitle("Add Relationship")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundColor(.gray)
                }
            }
        }
    }

    private func saveRelationship() {
        // TODO: Save to API
        HapticService.shared.notification(.success)
        dismiss()
    }
}

// MARK: - Extension for Avatar Color

extension SmartContact {
    var avatarColor: String {
        let colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"]
        let hash = abs(name.hashValue)
        return colors[hash % colors.count]
    }
}

#Preview {
    SmartContactsView()
}

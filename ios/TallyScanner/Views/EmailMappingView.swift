import SwiftUI

/// View for managing email-to-business-type mapping rules
struct EmailMappingView: View {
    @StateObject private var service = EmailMappingService.shared
    @StateObject private var businessTypeService = BusinessTypeService.shared

    @State private var showingCreateSheet = false
    @State private var searchText = ""
    @State private var testEmail = ""
    @State private var testResult: String?

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Test Email Section
                    testEmailSection

                    // Rules List
                    if service.rules.isEmpty && !service.isLoading {
                        emptyStateView
                    } else {
                        rulesList
                    }
                }
            }
            .navigationTitle("Email Rules")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button(action: { showingCreateSheet = true }) {
                        Image(systemName: "plus.circle.fill")
                            .foregroundColor(.tallyAccent)
                    }
                }
            }
            .sheet(isPresented: $showingCreateSheet) {
                CreateEmailRuleView()
            }
            .task {
                await service.loadIfNeeded()
                await businessTypeService.loadIfNeeded()
            }
        }
    }

    private var testEmailSection: some View {
        VStack(spacing: 12) {
            HStack {
                Image(systemName: "envelope.fill")
                    .foregroundColor(.gray)

                TextField("Test an email address...", text: $testEmail)
                    .textContentType(.emailAddress)
                    .keyboardType(.emailAddress)
                    .autocapitalization(.none)
                    .foregroundColor(.white)

                if !testEmail.isEmpty {
                    Button(action: testEmailMapping) {
                        Text("Test")
                            .font(.caption.bold())
                            .foregroundColor(.black)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(Color.tallyAccent)
                            .cornerRadius(8)
                    }
                }
            }
            .padding()
            .background(Color.white.opacity(0.05))
            .cornerRadius(12)

            if let result = testResult {
                HStack {
                    Image(systemName: result.isEmpty ? "xmark.circle.fill" : "checkmark.circle.fill")
                        .foregroundColor(result.isEmpty ? .red : .green)

                    Text(result.isEmpty ? "No matching rule found" : "Matches: \(result)")
                        .font(.subheadline)
                        .foregroundColor(result.isEmpty ? .red : .green)

                    Spacer()

                    Button(action: { testResult = nil }) {
                        Image(systemName: "xmark")
                            .foregroundColor(.gray)
                    }
                }
                .padding()
                .background(Color.white.opacity(0.05))
                .cornerRadius(12)
            }
        }
        .padding()
    }

    private var rulesList: some View {
        List {
            ForEach(filteredRules) { rule in
                EmailRuleRow(rule: rule)
                    .listRowBackground(Color.clear)
                    .listRowSeparator(.hidden)
            }
            .onDelete(perform: deleteRules)
        }
        .listStyle(.plain)
        .refreshable {
            await service.loadRules()
        }
    }

    private var filteredRules: [EmailBusinessRule] {
        if searchText.isEmpty {
            return service.rules
        }
        return service.rules.filter {
            $0.emailPattern.localizedCaseInsensitiveContains(searchText) ||
            $0.businessType.localizedCaseInsensitiveContains(searchText)
        }
    }

    private var emptyStateView: some View {
        VStack(spacing: 20) {
            Spacer()

            Image(systemName: "envelope.badge.shield.half.filled")
                .font(.system(size: 60))
                .foregroundColor(.gray)

            Text("No Email Rules")
                .font(.title2.bold())
                .foregroundColor(.white)

            Text("Create rules to automatically assign business types\nbased on email domains from your receipts.")
                .font(.subheadline)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)
                .padding(.horizontal, 40)

            Button(action: { showingCreateSheet = true }) {
                HStack {
                    Image(systemName: "plus.circle.fill")
                    Text("Create First Rule")
                }
                .font(.headline)
                .foregroundColor(.black)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }
            .padding(.top, 10)

            Spacer()
        }
    }

    private func testEmailMapping() {
        guard !testEmail.isEmpty else { return }

        if let match = service.matchBusinessType(for: testEmail) {
            testResult = match
        } else {
            testResult = ""
        }

        HapticService.shared.impact(.light)
    }

    private func deleteRules(at offsets: IndexSet) {
        Task {
            for index in offsets {
                let rule = filteredRules[index]
                await service.deleteRule(id: rule.id)
            }
        }
    }
}

// MARK: - Email Rule Row

struct EmailRuleRow: View {
    let rule: EmailBusinessRule
    @StateObject private var service = EmailMappingService.shared

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                // Pattern
                HStack(spacing: 6) {
                    Image(systemName: "envelope.fill")
                        .font(.caption)
                        .foregroundColor(.tallyAccent)

                    Text(rule.displayPattern)
                        .font(.headline)
                        .foregroundColor(.white)
                }

                Spacer()

                // Active toggle
                Button(action: toggleActive) {
                    Image(systemName: rule.isActive ? "checkmark.circle.fill" : "circle")
                        .foregroundColor(rule.isActive ? .green : .gray)
                }
            }

            HStack {
                // Business Type
                BusinessTypeBadge(name: rule.businessType)

                Spacer()

                // Match count
                if rule.matchCount > 0 {
                    HStack(spacing: 4) {
                        Image(systemName: "number")
                            .font(.caption2)
                        Text("\(rule.matchCount) matches")
                            .font(.caption)
                    }
                    .foregroundColor(.gray)
                }

                // Priority
                HStack(spacing: 4) {
                    Image(systemName: "arrow.up.arrow.down")
                        .font(.caption2)
                    Text("P\(rule.priority)")
                        .font(.caption)
                }
                .foregroundColor(.gray)
            }
        }
        .padding()
        .background(Color.white.opacity(0.05))
        .cornerRadius(12)
    }

    private func toggleActive() {
        Task {
            await service.toggleRule(id: rule.id)
            HapticService.shared.impact(.light)
        }
    }
}

// MARK: - Create Email Rule View

struct CreateEmailRuleView: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var service = EmailMappingService.shared
    @StateObject private var businessTypeService = BusinessTypeService.shared

    @State private var emailPattern = ""
    @State private var selectedBusinessType = ""
    @State private var priority = 0
    @State private var isSaving = false

    var body: some View {
        NavigationView {
            ZStack {
                Color.black.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // Email Pattern
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Email Pattern")
                                .font(.headline)
                                .foregroundColor(.white)

                            TextField("@domain.com or *@company.com", text: $emailPattern)
                                .textContentType(.URL)
                                .keyboardType(.emailAddress)
                                .autocapitalization(.none)
                                .padding()
                                .background(Color.white.opacity(0.1))
                                .cornerRadius(12)
                                .foregroundColor(.white)

                            Text("Examples: @company.com, *@gmail.com, user@specific.com")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }

                        // Business Type Selection
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Business Type")
                                .font(.headline)
                                .foregroundColor(.white)

                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 10) {
                                    ForEach(businessTypeService.businessTypes, id: \.id) { type in
                                        Button(action: { selectedBusinessType = type.name }) {
                                            HStack(spacing: 6) {
                                                Image(systemName: type.icon)
                                                    .font(.caption)
                                                Text(type.displayName)
                                                    .font(.subheadline)
                                            }
                                            .foregroundColor(selectedBusinessType == type.name ? .black : .white)
                                            .padding(.horizontal, 12)
                                            .padding(.vertical, 8)
                                            .background(
                                                selectedBusinessType == type.name
                                                    ? type.swiftUIColor
                                                    : Color.white.opacity(0.1)
                                            )
                                            .cornerRadius(8)
                                        }
                                    }
                                }
                                .padding(.horizontal, 1)
                            }
                        }

                        // Priority
                        VStack(alignment: .leading, spacing: 8) {
                            Text("Priority")
                                .font(.headline)
                                .foregroundColor(.white)

                            HStack {
                                Text("Lower")
                                    .font(.caption)
                                    .foregroundColor(.gray)

                                Slider(value: Binding(
                                    get: { Double(priority) },
                                    set: { priority = Int($0) }
                                ), in: 0...10, step: 1)
                                    .accentColor(.tallyAccent)

                                Text("Higher")
                                    .font(.caption)
                                    .foregroundColor(.gray)
                            }

                            Text("Priority: \(priority) - Higher priority rules are matched first")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }

                        Spacer(minLength: 40)

                        // Create Button
                        Button(action: createRule) {
                            HStack {
                                if isSaving {
                                    ProgressView()
                                        .progressViewStyle(CircularProgressViewStyle(tint: .black))
                                } else {
                                    Image(systemName: "plus.circle.fill")
                                    Text("Create Rule")
                                }
                            }
                            .font(.headline)
                            .foregroundColor(.black)
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(isValid ? Color.tallyAccent : Color.gray)
                            .cornerRadius(12)
                        }
                        .disabled(!isValid || isSaving)
                    }
                    .padding()
                }
            }
            .navigationTitle("New Email Rule")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") { dismiss() }
                        .foregroundColor(.gray)
                }
            }
        }
    }

    private var isValid: Bool {
        !emailPattern.isEmpty && !selectedBusinessType.isEmpty
    }

    private func createRule() {
        guard isValid else { return }

        isSaving = true

        Task {
            if await service.createRule(
                emailPattern: emailPattern,
                businessType: selectedBusinessType,
                priority: priority
            ) != nil {
                HapticService.shared.notification(.success)
                dismiss()
            } else {
                HapticService.shared.notification(.error)
            }
            isSaving = false
        }
    }
}

#Preview {
    EmailMappingView()
}

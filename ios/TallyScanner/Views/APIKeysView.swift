import SwiftUI

/// View for managing user's personal API keys
struct APIKeysView: View {
    @StateObject private var viewModel = APIKeysViewModel()
    @State private var showingInfoSheet = false

    var body: some View {
        List {
            // Info banner
            Section {
                HStack(spacing: 12) {
                    Image(systemName: "info.circle.fill")
                        .font(.title2)
                        .foregroundColor(.tallyAccent)

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Your API Keys")
                            .font(.subheadline)
                            .fontWeight(.semibold)

                        Text("Add your own API keys to use AI features. Your keys are encrypted and stored securely.")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }

            // OpenAI API Key
            Section {
                APIKeyRow(
                    serviceName: "OpenAI",
                    icon: "brain",
                    iconColor: .green,
                    isConfigured: viewModel.openAIConfigured,
                    apiKey: $viewModel.openAIKey,
                    isEditing: $viewModel.editingOpenAI,
                    isSaving: viewModel.savingOpenAI,
                    onSave: { await viewModel.saveOpenAIKey() },
                    onRemove: { await viewModel.removeOpenAIKey() }
                )
            } header: {
                Text("AI Services")
            } footer: {
                Text("Used for advanced receipt OCR and smart categorization. Get your key at platform.openai.com")
            }

            // Google Gemini API Key
            Section {
                APIKeyRow(
                    serviceName: "Google Gemini",
                    icon: "sparkles",
                    iconColor: .blue,
                    isConfigured: viewModel.geminiConfigured,
                    apiKey: $viewModel.geminiKey,
                    isEditing: $viewModel.editingGemini,
                    isSaving: viewModel.savingGemini,
                    onSave: { await viewModel.saveGeminiKey() },
                    onRemove: { await viewModel.removeGeminiKey() }
                )
            } footer: {
                Text("Alternative AI for receipt processing. Get your key at aistudio.google.com")
            }

            // Anthropic API Key
            Section {
                APIKeyRow(
                    serviceName: "Anthropic Claude",
                    icon: "text.bubble",
                    iconColor: .orange,
                    isConfigured: viewModel.anthropicConfigured,
                    apiKey: $viewModel.anthropicKey,
                    isEditing: $viewModel.editingAnthropic,
                    isSaving: viewModel.savingAnthropic,
                    onSave: { await viewModel.saveAnthropicKey() },
                    onRemove: { await viewModel.removeAnthropicKey() }
                )
            } footer: {
                Text("Premium AI for complex receipt analysis. Get your key at console.anthropic.com")
            }

            // Taskade API Key (for project management)
            Section {
                APIKeyRow(
                    serviceName: "Taskade",
                    icon: "checklist",
                    iconColor: .purple,
                    isConfigured: viewModel.taskadeConfigured,
                    apiKey: $viewModel.taskadeKey,
                    isEditing: $viewModel.editingTaskade,
                    isSaving: viewModel.savingTaskade,
                    onSave: { await viewModel.saveTaskadeKey() },
                    onRemove: { await viewModel.removeTaskadeKey() }
                )
            } header: {
                Text("Productivity")
            } footer: {
                Text("Connect to Taskade for expense tracking projects. Get your key at taskade.com/settings/api")
            }

            // Info section
            Section {
                Button(action: { showingInfoSheet = true }) {
                    HStack {
                        Label("Why use my own keys?", systemImage: "questionmark.circle")
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                }
                .foregroundColor(.primary)
            }
        }
        .navigationTitle("API Keys")
        .navigationBarTitleDisplayMode(.inline)
        .refreshable {
            await viewModel.loadKeys()
        }
        .task {
            await viewModel.loadKeys()
        }
        .alert("Error", isPresented: $viewModel.showError) {
            Button("OK", role: .cancel) {}
        } message: {
            Text(viewModel.errorMessage)
        }
        .sheet(isPresented: $showingInfoSheet) {
            APIKeysInfoSheet()
        }
    }
}

// MARK: - API Key Row Component

struct APIKeyRow: View {
    let serviceName: String
    let icon: String
    let iconColor: Color
    let isConfigured: Bool
    @Binding var apiKey: String
    @Binding var isEditing: Bool
    let isSaving: Bool
    let onSave: () async -> Void
    let onRemove: () async -> Void

    @State private var showingRemoveConfirm = false

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            // Header
            HStack {
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.15))
                        .frame(width: 36, height: 36)

                    Image(systemName: icon)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(iconColor)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(serviceName)
                        .font(.subheadline)
                        .fontWeight(.medium)

                    HStack(spacing: 4) {
                        Image(systemName: isConfigured ? "checkmark.circle.fill" : "circle.dashed")
                            .font(.caption)
                            .foregroundColor(isConfigured ? .green : .gray)

                        Text(isConfigured ? "Configured" : "Not configured")
                            .font(.caption)
                            .foregroundColor(isConfigured ? .green : .gray)
                    }
                }

                Spacer()

                if !isEditing {
                    Button(action: { isEditing = true }) {
                        Text(isConfigured ? "Edit" : "Add")
                            .font(.subheadline)
                            .fontWeight(.medium)
                    }
                }
            }

            // Edit mode
            if isEditing {
                VStack(spacing: 12) {
                    SecureField("API Key", text: $apiKey)
                        .textFieldStyle(.roundedBorder)
                        .font(.system(.body, design: .monospaced))
                        .autocapitalization(.none)
                        .autocorrectionDisabled()

                    HStack(spacing: 12) {
                        Button("Cancel") {
                            apiKey = ""
                            isEditing = false
                        }
                        .foregroundColor(.gray)

                        Spacer()

                        if isConfigured {
                            Button("Remove", role: .destructive) {
                                showingRemoveConfirm = true
                            }
                        }

                        Button(action: {
                            Task {
                                await onSave()
                            }
                        }) {
                            if isSaving {
                                ProgressView()
                                    .scaleEffect(0.8)
                            } else {
                                Text("Save")
                                    .fontWeight(.semibold)
                            }
                        }
                        .disabled(apiKey.isEmpty || isSaving)
                        .buttonStyle(.borderedProminent)
                        .tint(.tallyAccent)
                    }
                }
                .padding(.top, 4)
            }
        }
        .padding(.vertical, 4)
        .alert("Remove API Key", isPresented: $showingRemoveConfirm) {
            Button("Cancel", role: .cancel) {}
            Button("Remove", role: .destructive) {
                Task {
                    await onRemove()
                }
            }
        } message: {
            Text("Are you sure you want to remove your \(serviceName) API key?")
        }
    }
}

// MARK: - Info Sheet

struct APIKeysInfoSheet: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(alignment: .leading, spacing: 24) {
                    // Header
                    VStack(alignment: .leading, spacing: 8) {
                        Image(systemName: "key.fill")
                            .font(.largeTitle)
                            .foregroundColor(.tallyAccent)

                        Text("Why Use Your Own API Keys?")
                            .font(.title2)
                            .fontWeight(.bold)
                    }

                    // Benefits
                    VStack(alignment: .leading, spacing: 16) {
                        BenefitRow(
                            icon: "dollarsign.circle.fill",
                            color: .green,
                            title: "No Usage Limits",
                            description: "Use AI features without worrying about shared quotas. Your usage, your limits."
                        )

                        BenefitRow(
                            icon: "bolt.fill",
                            color: .yellow,
                            title: "Better Performance",
                            description: "Direct access to AI services means faster response times and no queuing."
                        )

                        BenefitRow(
                            icon: "lock.shield.fill",
                            color: .blue,
                            title: "Privacy",
                            description: "Your receipts are processed with your keys, giving you complete control over your data."
                        )

                        BenefitRow(
                            icon: "star.fill",
                            color: .purple,
                            title: "Latest Features",
                            description: "Access to the newest AI models and features as they become available."
                        )
                    }

                    Divider()

                    // How it works
                    VStack(alignment: .leading, spacing: 12) {
                        Text("How It Works")
                            .font(.headline)

                        Text("1. Sign up for an account with the AI provider (OpenAI, Google, etc.)")
                        Text("2. Generate an API key from their dashboard")
                        Text("3. Add the key here - it's encrypted and stored securely")
                        Text("4. TallyUps will use your key for AI-powered features")
                    }
                    .font(.subheadline)
                    .foregroundColor(.secondary)

                    Divider()

                    // No key?
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Don't Have Keys?")
                            .font(.headline)

                        Text("No problem! TallyUps works without your own keys. You'll use our shared service, which may have usage limits during peak times.")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }
                }
                .padding()
            }
            .navigationTitle("API Keys")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
        }
    }
}

struct BenefitRow: View {
    let icon: String
    let color: Color
    let title: String
    let description: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundColor(color)
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 4) {
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.semibold)

                Text(description)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
    }
}

// MARK: - View Model

@MainActor
class APIKeysViewModel: ObservableObject {
    @Published var openAIKey = ""
    @Published var geminiKey = ""
    @Published var anthropicKey = ""
    @Published var taskadeKey = ""

    @Published var openAIConfigured = false
    @Published var geminiConfigured = false
    @Published var anthropicConfigured = false
    @Published var taskadeConfigured = false

    @Published var editingOpenAI = false
    @Published var editingGemini = false
    @Published var editingAnthropic = false
    @Published var editingTaskade = false

    @Published var savingOpenAI = false
    @Published var savingGemini = false
    @Published var savingAnthropic = false
    @Published var savingTaskade = false

    @Published var showError = false
    @Published var errorMessage = ""

    func loadKeys() async {
        do {
            let status = try await APIClient.shared.getAPIKeysStatus()
            openAIConfigured = status.openai
            geminiConfigured = status.gemini
            anthropicConfigured = status.anthropic
            taskadeConfigured = status.taskade
        } catch {
            // Silently fail - keys just show as not configured
            print("Failed to load API key status: \(error)")
        }
    }

    func saveOpenAIKey() async {
        savingOpenAI = true
        defer { savingOpenAI = false }

        do {
            try await APIClient.shared.saveAPIKey(service: "openai", key: openAIKey)
            openAIConfigured = true
            editingOpenAI = false
            openAIKey = ""
        } catch {
            showError(error)
        }
    }

    func removeOpenAIKey() async {
        savingOpenAI = true
        defer { savingOpenAI = false }

        do {
            try await APIClient.shared.removeAPIKey(service: "openai")
            openAIConfigured = false
            editingOpenAI = false
        } catch {
            showError(error)
        }
    }

    func saveGeminiKey() async {
        savingGemini = true
        defer { savingGemini = false }

        do {
            try await APIClient.shared.saveAPIKey(service: "gemini", key: geminiKey)
            geminiConfigured = true
            editingGemini = false
            geminiKey = ""
        } catch {
            showError(error)
        }
    }

    func removeGeminiKey() async {
        savingGemini = true
        defer { savingGemini = false }

        do {
            try await APIClient.shared.removeAPIKey(service: "gemini")
            geminiConfigured = false
            editingGemini = false
        } catch {
            showError(error)
        }
    }

    func saveAnthropicKey() async {
        savingAnthropic = true
        defer { savingAnthropic = false }

        do {
            try await APIClient.shared.saveAPIKey(service: "anthropic", key: anthropicKey)
            anthropicConfigured = true
            editingAnthropic = false
            anthropicKey = ""
        } catch {
            showError(error)
        }
    }

    func removeAnthropicKey() async {
        savingAnthropic = true
        defer { savingAnthropic = false }

        do {
            try await APIClient.shared.removeAPIKey(service: "anthropic")
            anthropicConfigured = false
            editingAnthropic = false
        } catch {
            showError(error)
        }
    }

    func saveTaskadeKey() async {
        savingTaskade = true
        defer { savingTaskade = false }

        do {
            try await APIClient.shared.saveAPIKey(service: "taskade", key: taskadeKey)
            taskadeConfigured = true
            editingTaskade = false
            taskadeKey = ""
        } catch {
            showError(error)
        }
    }

    func removeTaskadeKey() async {
        savingTaskade = true
        defer { savingTaskade = false }

        do {
            try await APIClient.shared.removeAPIKey(service: "taskade")
            taskadeConfigured = false
            editingTaskade = false
        } catch {
            showError(error)
        }
    }

    private func showError(_ error: Error) {
        errorMessage = error.localizedDescription
        showError = true
    }
}

#Preview {
    NavigationStack {
        APIKeysView()
    }
}

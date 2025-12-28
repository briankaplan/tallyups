import SwiftUI

// MARK: - API Keys View

struct APIKeysView: View {
    @EnvironmentObject var authService: AuthService
    @State private var openAIKey = ""
    @State private var geminiKey = ""
    @State private var anthropicKey = ""
    @State private var isLoading = false
    @State private var isSaving = false
    @State private var showAlert = false
    @State private var alertMessage = ""
    @State private var showKeys = false

    var body: some View {
        Form {
            Section {
                VStack(alignment: .leading, spacing: 12) {
                    HStack {
                        Image(systemName: "info.circle.fill")
                            .foregroundColor(.tallyAccent)
                        Text("API Keys for AI Features")
                            .font(.headline)
                    }

                    Text("Add your API keys to enable AI-powered receipt processing, smart categorization, and expense insights.")
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
                .padding(.vertical, 8)
            }

            Section("OpenAI") {
                HStack {
                    Group {
                        if showKeys {
                            TextField("sk-...", text: $openAIKey)
                        } else {
                            SecureField("sk-...", text: $openAIKey)
                        }
                    }
                    .textContentType(.none)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                    if !openAIKey.isEmpty {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    }
                }

                Text("Used for GPT-4 Vision receipt processing")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Section("Gemini (Google AI)") {
                HStack {
                    Group {
                        if showKeys {
                            TextField("AIza...", text: $geminiKey)
                        } else {
                            SecureField("AIza...", text: $geminiKey)
                        }
                    }
                    .textContentType(.none)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                    if !geminiKey.isEmpty {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    }
                }

                Text("Used for Gemini Vision receipt analysis")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Section("Anthropic (Claude)") {
                HStack {
                    Group {
                        if showKeys {
                            TextField("sk-ant-...", text: $anthropicKey)
                        } else {
                            SecureField("sk-ant-...", text: $anthropicKey)
                        }
                    }
                    .textContentType(.none)
                    .autocorrectionDisabled()
                    .textInputAutocapitalization(.never)

                    if !anthropicKey.isEmpty {
                        Image(systemName: "checkmark.circle.fill")
                            .foregroundColor(.green)
                    }
                }

                Text("Used for Claude-powered expense insights")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Section {
                Toggle("Show Keys", isOn: $showKeys)

                Button(action: saveKeys) {
                    HStack {
                        if isSaving {
                            ProgressView()
                                .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        } else {
                            Image(systemName: "square.and.arrow.down.fill")
                        }
                        Text(isSaving ? "Saving..." : "Save API Keys")
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 8)
                }
                .disabled(isSaving)
                .buttonStyle(.borderedProminent)
                .tint(.tallyAccent)
            }

            Section {
                Link(destination: URL(string: "https://platform.openai.com/api-keys")!) {
                    Label("Get OpenAI Key", systemImage: "arrow.up.right.square")
                }

                Link(destination: URL(string: "https://aistudio.google.com/apikey")!) {
                    Label("Get Gemini Key", systemImage: "arrow.up.right.square")
                }

                Link(destination: URL(string: "https://console.anthropic.com/")!) {
                    Label("Get Anthropic Key", systemImage: "arrow.up.right.square")
                }
            } header: {
                Text("Get API Keys")
            } footer: {
                Text("API keys are stored securely and only used for processing your receipts.")
            }
        }
        .navigationTitle("API Keys")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            loadKeys()
        }
        .alert("API Keys", isPresented: $showAlert) {
            Button("OK", role: .cancel) { }
        } message: {
            Text(alertMessage)
        }
        .overlay {
            if isLoading {
                ProgressView("Loading...")
                    .padding()
                    .background(Color(.systemBackground).opacity(0.9))
                    .cornerRadius(12)
            }
        }
    }

    private func loadKeys() {
        isLoading = true

        Task {
            do {
                let status = try await APIClient.shared.getAPIKeysStatus()
                await MainActor.run {
                    // Show placeholder text for configured keys
                    openAIKey = status.openai ? "••••••••" : ""
                    geminiKey = status.gemini ? "••••••••" : ""
                    anthropicKey = status.anthropic ? "••••••••" : ""
                    isLoading = false
                }
            } catch {
                await MainActor.run {
                    isLoading = false
                }
            }
        }
    }

    private func saveKeys() {
        isSaving = true

        Task {
            do {
                // Save each key that has a value and isn't just the placeholder
                if !openAIKey.isEmpty && openAIKey != "••••••••" {
                    try await APIClient.shared.saveAPIKey(service: "openai", key: openAIKey)
                }
                if !geminiKey.isEmpty && geminiKey != "••••••••" {
                    try await APIClient.shared.saveAPIKey(service: "gemini", key: geminiKey)
                }
                if !anthropicKey.isEmpty && anthropicKey != "••••••••" {
                    try await APIClient.shared.saveAPIKey(service: "anthropic", key: anthropicKey)
                }
                await MainActor.run {
                    isSaving = false
                    alertMessage = "API keys saved successfully!"
                    showAlert = true
                }
            } catch {
                await MainActor.run {
                    isSaving = false
                    alertMessage = "Failed to save API keys: \(error.localizedDescription)"
                    showAlert = true
                }
            }
        }
    }
}

#Preview {
    NavigationStack {
        APIKeysView()
            .environmentObject(AuthService.shared)
    }
}

import SwiftUI

struct ProfileView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) private var dismiss

    @State private var connectedServices: [ConnectedService] = []
    @State private var isLoadingServices = true
    @State private var showingDeleteConfirm = false
    @State private var showingLogoutConfirm = false
    @State private var deleteConfirmText = ""
    @State private var isDeleting = false

    struct ConnectedService: Identifiable {
        let id = UUID()
        let type: String
        let email: String?
        let isActive: Bool
        let connectedAt: Date?
    }

    var body: some View {
        NavigationStack {
            List {
                // User Info Section
                userInfoSection

                // Connected Services Section
                connectedServicesSection

                // Data & Privacy Section
                dataPrivacySection

                // Account Actions
                accountActionsSection
            }
            .navigationTitle("Profile")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                }
            }
            .onAppear {
                loadConnectedServices()
            }
            .alert("Sign Out", isPresented: $showingLogoutConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Sign Out", role: .destructive) {
                    Task {
                        await authService.logout()
                        dismiss()
                    }
                }
            } message: {
                Text("Are you sure you want to sign out?")
            }
            .alert("Delete Account", isPresented: $showingDeleteConfirm) {
                TextField("Type DELETE to confirm", text: $deleteConfirmText)
                Button("Cancel", role: .cancel) {
                    deleteConfirmText = ""
                }
                Button("Delete", role: .destructive) {
                    deleteAccount()
                }
                .disabled(deleteConfirmText != "DELETE")
            } message: {
                Text("This will permanently delete your account and all associated data. This action cannot be undone.")
            }
        }
    }

    // MARK: - User Info Section

    private var userInfoSection: some View {
        Section {
            HStack(spacing: 16) {
                // Avatar
                ZStack {
                    Circle()
                        .fill(Color.tallyAccent.opacity(0.2))
                        .frame(width: 70, height: 70)

                    Text(userInitials)
                        .font(.title)
                        .fontWeight(.semibold)
                        .foregroundColor(.tallyAccent)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(authService.currentUser?.name ?? "TallyUps User")
                        .font(.title2.bold())

                    if let email = authService.currentUser?.email {
                        Text(email)
                            .font(.subheadline)
                            .foregroundColor(.gray)
                    }

                    HStack(spacing: 4) {
                        Image(systemName: "apple.logo")
                            .font(.caption)
                        Text("Signed in with Apple")
                            .font(.caption)
                    }
                    .foregroundColor(.gray)
                }

                Spacer()
            }
            .padding(.vertical, 8)
        }
    }

    private var userInitials: String {
        guard let name = authService.currentUser?.name else {
            return "U"
        }

        let components = name.components(separatedBy: " ")
        if components.count >= 2 {
            let first = components[0].prefix(1)
            let last = components[1].prefix(1)
            return "\(first)\(last)"
        } else {
            return String(name.prefix(2)).uppercased()
        }
    }

    // MARK: - Connected Services Section

    private var connectedServicesSection: some View {
        Section {
            if isLoadingServices {
                HStack {
                    ProgressView()
                    Text("Loading connected services...")
                        .foregroundColor(.gray)
                }
            } else if connectedServices.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("No connected services")
                        .foregroundColor(.gray)
                    Text("Connect Gmail, Calendar, or other services in the web dashboard.")
                        .font(.caption)
                        .foregroundColor(.gray.opacity(0.8))
                }
            } else {
                ForEach(connectedServices) { service in
                    serviceRow(service)
                }
            }

            NavigationLink {
                ConnectServicesInfoView()
            } label: {
                Label("Connect More Services", systemImage: "plus.circle")
            }
        } header: {
            Text("Connected Services")
        } footer: {
            Text("Services like Gmail and Calendar can be connected from the web dashboard.")
        }
    }

    private func serviceRow(_ service: ConnectedService) -> some View {
        HStack {
            Image(systemName: serviceIcon(for: service.type))
                .font(.title2)
                .foregroundColor(serviceColor(for: service.type))
                .frame(width: 32)

            VStack(alignment: .leading, spacing: 2) {
                Text(serviceDisplayName(for: service.type))
                    .font(.headline)

                if let email = service.email {
                    Text(email)
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }

            Spacer()

            if service.isActive {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green)
            } else {
                Text("Expired")
                    .font(.caption)
                    .foregroundColor(.orange)
            }
        }
    }

    private func serviceIcon(for type: String) -> String {
        switch type.lowercased() {
        case "gmail": return "envelope.fill"
        case "calendar": return "calendar"
        case "taskade": return "checklist"
        case "openai": return "brain"
        case "gemini": return "sparkles"
        case "anthropic": return "bubble.left.and.bubble.right"
        default: return "link.circle"
        }
    }

    private func serviceColor(for type: String) -> Color {
        switch type.lowercased() {
        case "gmail": return .red
        case "calendar": return .blue
        case "taskade": return .purple
        case "openai": return .green
        case "gemini": return .orange
        case "anthropic": return .brown
        default: return .gray
        }
    }

    private func serviceDisplayName(for type: String) -> String {
        switch type.lowercased() {
        case "gmail": return "Gmail"
        case "calendar": return "Google Calendar"
        case "taskade": return "Taskade"
        case "openai": return "OpenAI"
        case "gemini": return "Google Gemini"
        case "anthropic": return "Anthropic Claude"
        default: return type.capitalized
        }
    }

    // MARK: - Data & Privacy Section

    private var dataPrivacySection: some View {
        Section("Data & Privacy") {
            NavigationLink {
                DataExportView()
            } label: {
                Label("Export My Data", systemImage: "arrow.down.doc")
            }

            NavigationLink {
                PrivacyInfoView()
            } label: {
                Label("Privacy Policy", systemImage: "hand.raised")
            }

            NavigationLink {
                TermsOfServiceView()
            } label: {
                Label("Terms of Service", systemImage: "doc.text")
            }
        }
    }

    // MARK: - Account Actions Section

    private var accountActionsSection: some View {
        Section {
            Button(action: { showingLogoutConfirm = true }) {
                Label("Sign Out", systemImage: "rectangle.portrait.and.arrow.forward")
            }

            Button(role: .destructive, action: { showingDeleteConfirm = true }) {
                HStack {
                    if isDeleting {
                        ProgressView()
                    } else {
                        Label("Delete Account", systemImage: "trash")
                    }
                }
            }
            .disabled(isDeleting)
        } footer: {
            Text("Deleting your account will permanently remove all your data including receipts, transactions, and connected services.")
        }
    }

    // MARK: - Actions

    private func loadConnectedServices() {
        isLoadingServices = true

        Task {
            do {
                let services = try await fetchConnectedServices()
                await MainActor.run {
                    connectedServices = services
                    isLoadingServices = false
                }
            } catch {
                await MainActor.run {
                    connectedServices = []
                    isLoadingServices = false
                }
            }
        }
    }

    private func fetchConnectedServices() async throws -> [ConnectedService] {
        guard let url = URL(string: "\(authService.serverURL)/api/credentials") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = KeychainService.shared.get(key: "access_token") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (data, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            return []
        }

        struct ServiceResponse: Decodable {
            let credentials: [CredentialItem]

            struct CredentialItem: Decodable {
                let service_type: String
                let account_email: String?
                let is_active: Bool
            }
        }

        let decoded = try JSONDecoder().decode(ServiceResponse.self, from: data)

        return decoded.credentials.map { item in
            ConnectedService(
                type: item.service_type,
                email: item.account_email,
                isActive: item.is_active,
                connectedAt: nil
            )
        }
    }

    private func deleteAccount() {
        guard deleteConfirmText == "DELETE" else { return }

        isDeleting = true

        Task {
            let success = await authService.deleteAccount()

            await MainActor.run {
                if success {
                    dismiss()
                } else {
                    isDeleting = false
                }
            }
        }
    }
}

// MARK: - Connect Services Info View

struct ConnectServicesInfoView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "link.circle.fill")
                .font(.system(size: 80))
                .foregroundColor(.tallyAccent)

            Text("Connect Services")
                .font(.title.bold())

            Text("To connect Gmail, Google Calendar, Taskade, or AI services, please visit the TallyUps web dashboard.")
                .multilineTextAlignment(.center)
                .foregroundColor(.gray)
                .padding(.horizontal)

            if !authService.serverURL.isEmpty {
                Link(destination: URL(string: "\(authService.serverURL)/settings")!) {
                    Text("Open Web Dashboard")
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent)
                        .cornerRadius(12)
                }
                .padding(.horizontal)
            }

            Spacer()
        }
        .padding(.top, 40)
        .navigationTitle("Connect Services")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Data Export View

struct DataExportView: View {
    @EnvironmentObject var authService: AuthService
    @State private var isExporting = false
    @State private var exportResult: ExportResult?

    enum ExportResult {
        case success(URL)
        case failure(String)
    }

    var body: some View {
        VStack(spacing: 24) {
            Image(systemName: "arrow.down.doc.fill")
                .font(.system(size: 80))
                .foregroundColor(.tallyAccent)

            Text("Export Your Data")
                .font(.title.bold())

            Text("Download all your data including receipts, transactions, and settings in a portable format.")
                .multilineTextAlignment(.center)
                .foregroundColor(.gray)
                .padding(.horizontal)

            VStack(alignment: .leading, spacing: 12) {
                exportInfoRow(icon: "doc.text", text: "Transactions (CSV)")
                exportInfoRow(icon: "photo.stack", text: "Receipt images (ZIP)")
                exportInfoRow(icon: "gearshape", text: "Settings (JSON)")
            }
            .padding()
            .background(Color.tallyCard)
            .cornerRadius(12)
            .padding(.horizontal)

            Button(action: requestExport) {
                HStack {
                    if isExporting {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .black))
                    } else {
                        Image(systemName: "arrow.down.circle")
                        Text("Request Export")
                    }
                }
                .font(.headline)
                .foregroundColor(.black)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }
            .disabled(isExporting)
            .padding(.horizontal)

            if case .success = exportResult {
                Text("Export requested. You'll receive an email when it's ready.")
                    .font(.caption)
                    .foregroundColor(.green)
            } else if case .failure(let error) = exportResult {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.red)
            }

            Spacer()
        }
        .padding(.top, 40)
        .navigationTitle("Export Data")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func exportInfoRow(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .foregroundColor(.tallyAccent)
                .frame(width: 24)
            Text(text)
                .foregroundColor(.white)
            Spacer()
        }
    }

    private func requestExport() {
        isExporting = true

        Task {
            do {
                try await requestDataExport()
                await MainActor.run {
                    exportResult = .success(URL(string: "https://example.com")!)
                    isExporting = false
                }
            } catch {
                await MainActor.run {
                    exportResult = .failure(error.localizedDescription)
                    isExporting = false
                }
            }
        }
    }

    private func requestDataExport() async throws {
        guard let url = URL(string: "\(authService.serverURL)/api/account/export") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = KeychainService.shared.get(key: "access_token") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }
    }
}

// MARK: - Privacy Info View

struct PrivacyInfoView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Privacy Policy")
                    .font(.title.bold())

                Text("Last updated: December 2024")
                    .font(.caption)
                    .foregroundColor(.gray)

                Group {
                    sectionHeader("Data We Collect")
                    bulletPoint("Receipt images you upload")
                    bulletPoint("Transaction data from linked accounts")
                    bulletPoint("Email address (via Sign in with Apple)")

                    sectionHeader("How We Use Your Data")
                    bulletPoint("Process and organize your receipts")
                    bulletPoint("Match receipts to transactions")
                    bulletPoint("Provide expense tracking features")

                    sectionHeader("Data Storage")
                    bulletPoint("Data is stored securely on our servers")
                    bulletPoint("Images are stored in Cloudflare R2")
                    bulletPoint("We use encryption in transit and at rest")

                    sectionHeader("Your Rights")
                    bulletPoint("Export all your data at any time")
                    bulletPoint("Delete your account and all data")
                    bulletPoint("Control what services are connected")
                }

                if !authService.serverURL.isEmpty {
                    Link(destination: URL(string: "\(authService.serverURL)/privacy")!) {
                        Text("View Full Privacy Policy")
                            .foregroundColor(.tallyAccent)
                    }
                    .padding(.top)
                }
            }
            .padding()
        }
        .navigationTitle("Privacy")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func sectionHeader(_ text: String) -> some View {
        Text(text)
            .font(.headline)
            .padding(.top, 8)
    }

    private func bulletPoint(_ text: String) -> some View {
        HStack(alignment: .top, spacing: 8) {
            Text("•")
            Text(text)
        }
        .foregroundColor(.gray)
    }
}

// MARK: - Terms of Service View

struct TermsOfServiceView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {
                Text("Terms of Service")
                    .font(.title.bold())

                Text("Last updated: December 2024")
                    .font(.caption)
                    .foregroundColor(.gray)

                Text("By using TallyUps, you agree to these terms of service. Please read them carefully.")
                    .foregroundColor(.gray)

                if !authService.serverURL.isEmpty {
                    Link(destination: URL(string: "\(authService.serverURL)/terms")!) {
                        Text("View Full Terms of Service")
                            .foregroundColor(.tallyAccent)
                    }
                    .padding(.top)
                }
            }
            .padding()
        }
        .navigationTitle("Terms")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Previews

#Preview {
    ProfileView()
        .environmentObject(AuthService.shared)
}

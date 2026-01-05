import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var authService: AuthService
    @EnvironmentObject var uploadQueue: UploadQueue

    @State private var showingLogoutConfirm = false
    @State private var showingClearQueueConfirm = false
    @State private var showingServerSettings = false
    @State private var healthStatus: HealthResponse?
    @State private var isCheckingHealth = false

    var body: some View {
        NavigationStack {
            List {
                // Account Section
                accountSection

                // Connected Services Section
                connectedServicesSection

                // Upload Queue Section
                uploadQueueSection

                // Server Section
                serverSection

                // Features Section
                featuresSection

                // Preferences Section
                preferencesSection

                // Legal Section
                legalSection

                // About Section
                aboutSection

                // Logout
                logoutSection
            }
            .navigationTitle("Settings")
            .navigationBarTitleDisplayMode(.large)
            .sheet(isPresented: $showingServerSettings) {
                ServerSetupView(serverURL: .constant(authService.serverURL))
            }
            .alert("Sign Out", isPresented: $showingLogoutConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Sign Out", role: .destructive) {
                    Task {
                        await authService.logout()
                    }
                }
            } message: {
                Text("Are you sure you want to sign out?")
            }
            .alert("Clear Upload Queue", isPresented: $showingClearQueueConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Clear All", role: .destructive) {
                    uploadQueue.clearAll()
                }
            } message: {
                Text("This will remove all pending uploads. This action cannot be undone.")
            }
        }
    }

    // MARK: - Account Section

    @State private var showingProfile = false

    private var accountSection: some View {
        Section("Account") {
            Button(action: { showingProfile = true }) {
                HStack {
                    // User avatar
                    ZStack {
                        Circle()
                            .fill(Color.tallyAccent.opacity(0.2))
                            .frame(width: 50, height: 50)

                        Text(userInitials)
                            .font(.headline)
                            .fontWeight(.semibold)
                            .foregroundColor(.tallyAccent)
                    }
                    .accessibilityHidden(true)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(authService.currentUser?.name ?? "TallyUps User")
                            .font(.headline)
                            .foregroundColor(.primary)

                        if let email = authService.currentUser?.email {
                            Text(email)
                                .font(.caption)
                                .foregroundColor(.gray)
                        } else {
                            Text("Signed in with Apple")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundColor(.gray)
                        .accessibilityHidden(true)
                }
            }
            .padding(.vertical, 4)
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Profile: \(authService.currentUser?.name ?? "TallyUps User")")
            .accessibilityHint("Double tap to view and edit your profile")

            // Biometric Settings
            if authService.biometricType != .none {
                Toggle(isOn: Binding(
                    get: { authService.biometricsEnabled },
                    set: { newValue in
                        // Haptic feedback: toggle changed
                        HapticService.shared.toggleChanged()
                        if newValue {
                            // User wants to enable - they'll set it up on next login
                        } else {
                            authService.clearStoredCredentials()
                        }
                    }
                )) {
                    Label(
                        "Sign in with \(authService.biometricType.name)",
                        systemImage: authService.biometricType.icon
                    )
                }
                .accessibilityLabel("Sign in with \(authService.biometricType.name), \(authService.biometricsEnabled ? "enabled" : "disabled")")
                .accessibilityHint("Double tap to \(authService.biometricsEnabled ? "disable" : "enable") biometric sign in")
            }
        }
        .sheet(isPresented: $showingProfile) {
            ProfileView()
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
            NavigationLink {
                ConnectedServicesView()
            } label: {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(Color.tallyAccent.opacity(0.15))
                            .frame(width: 36, height: 36)

                        Image(systemName: "link.circle.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(.tallyAccent)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Connected Services")
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .foregroundColor(.primary)

                        Text("Gmail, Calendar, Bank Accounts")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }

            NavigationLink {
                APIKeysView()
            } label: {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(Color.orange.opacity(0.15))
                            .frame(width: 36, height: 36)

                        Image(systemName: "key.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(.orange)
                    }

                    VStack(alignment: .leading, spacing: 2) {
                        Text("API Keys")
                            .font(.subheadline)
                            .fontWeight(.medium)
                            .foregroundColor(.primary)

                        Text("OpenAI, Gemini, Anthropic")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
                .padding(.vertical, 4)
            }
        } header: {
            Text("Integrations")
        } footer: {
            Text("Connect your email, calendar, and bank accounts for automatic receipt import and transaction matching.")
        }
    }

    // MARK: - Upload Queue Section

    private var uploadQueueSection: some View {
        Section("Upload Queue") {
            HStack {
                Label("Pending Uploads", systemImage: "arrow.up.circle")
                Spacer()
                Text("\(uploadQueue.pendingCount)")
                    .foregroundColor(.gray)
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Pending uploads: \(uploadQueue.pendingCount)")

            if uploadQueue.isUploading {
                HStack {
                    ProgressView()
                    Text("Uploading...")
                        .foregroundColor(.gray)
                }
                .accessibilityLabel("Upload in progress")
            }

            if uploadQueue.pendingCount > 0 {
                Button("Clear Queue", role: .destructive) {
                    showingClearQueueConfirm = true
                }
                .accessibilityLabel("Clear upload queue")
                .accessibilityHint("Remove all \(uploadQueue.pendingCount) pending uploads. This cannot be undone.")
            }
        }
    }

    // MARK: - Server Section

    private var serverSection: some View {
        Section("Server") {
            HStack {
                Label("Server URL", systemImage: "server.rack")
                Spacer()
                Text(authService.serverURL.isEmpty ? "Not configured" : shortenURL(authService.serverURL))
                    .foregroundColor(.gray)
                    .lineLimit(1)
            }
            .onTapGesture {
                showingServerSettings = true
            }
            .accessibilityElement(children: .combine)
            .accessibilityLabel("Server URL: \(authService.serverURL.isEmpty ? "Not configured" : shortenURL(authService.serverURL))")
            .accessibilityHint("Double tap to change server settings")
            .accessibilityAddTraits(.isButton)

            Button(action: checkServerHealth) {
                HStack {
                    Label("Check Connection", systemImage: "network")
                    Spacer()
                    if isCheckingHealth {
                        ProgressView()
                            .accessibilityHidden(true)
                    } else if let health = healthStatus {
                        Image(systemName: health.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundColor(health.ok ? .green : .red)
                            .accessibilityHidden(true)
                    }
                }
            }
            .accessibilityLabel(serverConnectionAccessibilityLabel)
            .accessibilityHint("Double tap to test server connection")

            if let health = healthStatus {
                if let version = health.version {
                    HStack {
                        Text("Server Version")
                        Spacer()
                        Text(version)
                            .foregroundColor(.gray)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Server version: \(version)")
                }

                if let poolSize = health.poolSize, let active = health.activeConnections {
                    HStack {
                        Text("DB Connections")
                        Spacer()
                        Text("\(active)/\(poolSize)")
                            .foregroundColor(.gray)
                    }
                    .accessibilityElement(children: .combine)
                    .accessibilityLabel("Database connections: \(active) of \(poolSize) active")
                }
            }
        }
    }

    private var serverConnectionAccessibilityLabel: String {
        if isCheckingHealth {
            return "Checking server connection"
        } else if let health = healthStatus {
            return "Check connection, status: \(health.ok ? "connected" : "disconnected")"
        } else {
            return "Check server connection"
        }
    }

    // MARK: - Features Section

    private var featuresSection: some View {
        Section("Features") {
            NavigationLink {
                ProjectsView()
            } label: {
                Label("Projects", systemImage: "folder.fill")
            }

            NavigationLink {
                ContactsView()
            } label: {
                Label("Contacts", systemImage: "person.2.fill")
            }

            NavigationLink {
                SmartContactsView()
            } label: {
                Label("Smart Contacts", systemImage: "person.crop.circle.badge.checkmark")
            }

            NavigationLink {
                EmailMappingView()
            } label: {
                Label("Email Rules", systemImage: "envelope.badge.fill")
            }

            NavigationLink {
                ReportsView()
            } label: {
                Label("Reports", systemImage: "chart.bar.doc.horizontal.fill")
            }
        }
    }

    // MARK: - Preferences Section

    private var preferencesSection: some View {
        Section("Preferences") {
            NavigationLink {
                DefaultsSettingsView()
            } label: {
                Label("Default Values", systemImage: "slider.horizontal.3")
            }

            NavigationLink {
                NotificationSettingsView()
            } label: {
                Label("Notifications", systemImage: "bell")
            }

            NavigationLink {
                StorageSettingsView()
            } label: {
                Label("Storage & Data", systemImage: "internaldrive")
            }
        }
    }

    // MARK: - Legal Section

    @State private var showingTerms = false
    @State private var showingPrivacy = false

    private var legalSection: some View {
        Section("Legal") {
            Button(action: { showingTerms = true }) {
                HStack {
                    Label("Terms of Service", systemImage: "doc.text.fill")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }
            .foregroundColor(.primary)
            .sheet(isPresented: $showingTerms) {
                TermsOfServiceView()
            }

            Button(action: { showingPrivacy = true }) {
                HStack {
                    Label("Privacy Policy", systemImage: "lock.shield.fill")
                    Spacer()
                    Image(systemName: "chevron.right")
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }
            .foregroundColor(.primary)
            .sheet(isPresented: $showingPrivacy) {
                PrivacyPolicyView()
            }
        }
    }

    // MARK: - About Section

    private var aboutSection: some View {
        Section("About") {
            HStack {
                Text("Version")
                Spacer()
                Text(Bundle.main.infoDictionary?["CFBundleShortVersionString"] as? String ?? "1.0")
                    .foregroundColor(.gray)
            }

            HStack {
                Text("Build")
                Spacer()
                Text(Bundle.main.infoDictionary?["CFBundleVersion"] as? String ?? "1")
                    .foregroundColor(.gray)
            }

            Link(destination: URL(string: "https://github.com/tallyups")!) {
                Label("GitHub", systemImage: "link")
            }

            Link(destination: URL(string: "https://tallyups.com")!) {
                Label("Website", systemImage: "globe")
            }
        }
    }

    // MARK: - Logout Section

    private var logoutSection: some View {
        Section {
            Button("Sign Out", role: .destructive) {
                showingLogoutConfirm = true
            }
        }
    }

    // MARK: - Helpers

    private func shortenURL(_ url: String) -> String {
        url.replacingOccurrences(of: "https://", with: "")
           .replacingOccurrences(of: "http://", with: "")
    }

    private func checkServerHealth() {
        isCheckingHealth = true

        Task {
            do {
                healthStatus = try await APIClient.shared.checkHealth()
            } catch {
                healthStatus = HealthResponse(ok: false, version: nil, uptime: nil, poolSize: nil, activeConnections: nil)
            }
            isCheckingHealth = false
        }
    }
}

// MARK: - Defaults Settings View

struct DefaultsSettingsView: View {
    @AppStorage("default_business") private var defaultBusiness = "personal"
    @AppStorage("auto_ocr") private var autoOCR = true
    @AppStorage("auto_enhance") private var autoEnhance = true
    @AppStorage("save_location") private var saveLocation = true
    @ObservedObject private var businessTypeService = BusinessTypeService.shared

    var body: some View {
        Form {
            Section("Business") {
                if businessTypeService.isLoading {
                    HStack {
                        Text("Loading business types...")
                            .foregroundColor(.gray)
                        Spacer()
                        ProgressView()
                    }
                } else {
                    Picker("Default Business", selection: $defaultBusiness) {
                        ForEach(businessTypeService.businessTypes) { type in
                            HStack {
                                Image(systemName: type.icon)
                                    .foregroundColor(type.swiftUIColor)
                                Text(type.displayName)
                            }
                            .tag(type.name.lowercased())
                        }
                    }
                }
            }

            Section("Scanning") {
                Toggle("Auto OCR on upload", isOn: Binding(
                    get: { autoOCR },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        autoOCR = newValue
                    }
                ))
                .accessibilityLabel("Auto OCR on upload, \(autoOCR ? "enabled" : "disabled")")
                .accessibilityHint("When enabled, automatically extracts text from receipts after upload")

                Toggle("Auto-enhance images", isOn: Binding(
                    get: { autoEnhance },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        autoEnhance = newValue
                    }
                ))
                .accessibilityLabel("Auto-enhance images, \(autoEnhance ? "enabled" : "disabled")")
                .accessibilityHint("When enabled, automatically improves image quality for better OCR")

                Toggle("Save location with receipts", isOn: Binding(
                    get: { saveLocation },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        saveLocation = newValue
                    }
                ))
                .accessibilityLabel("Save location with receipts, \(saveLocation ? "enabled" : "disabled")")
                .accessibilityHint("When enabled, stores GPS coordinates when scanning receipts")
            }
        }
        .navigationTitle("Default Values")
        .navigationBarTitleDisplayMode(.inline)
        .task {
            await businessTypeService.loadIfNeeded()
        }
    }
}

// MARK: - Notification Settings View

struct NotificationSettingsView: View {
    @AppStorage("notify_upload_complete") private var notifyUploadComplete = true
    @AppStorage("notify_ocr_complete") private var notifyOCRComplete = true
    @AppStorage("notify_match_found") private var notifyMatchFound = true

    var body: some View {
        Form {
            Section("Notifications") {
                Toggle("Upload complete", isOn: Binding(
                    get: { notifyUploadComplete },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        notifyUploadComplete = newValue
                    }
                ))
                .accessibilityLabel("Upload complete notification, \(notifyUploadComplete ? "enabled" : "disabled")")
                .accessibilityHint("Notify when receipt upload finishes")

                Toggle("OCR extraction complete", isOn: Binding(
                    get: { notifyOCRComplete },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        notifyOCRComplete = newValue
                    }
                ))
                .accessibilityLabel("OCR extraction complete notification, \(notifyOCRComplete ? "enabled" : "disabled")")
                .accessibilityHint("Notify when text extraction from receipt finishes")

                Toggle("Match found", isOn: Binding(
                    get: { notifyMatchFound },
                    set: { newValue in
                        HapticService.shared.toggleChanged()
                        notifyMatchFound = newValue
                    }
                ))
                .accessibilityLabel("Match found notification, \(notifyMatchFound ? "enabled" : "disabled")")
                .accessibilityHint("Notify when a receipt is matched to a transaction")
            }
        }
        .navigationTitle("Notifications")
        .navigationBarTitleDisplayMode(.inline)
    }
}

// MARK: - Storage Settings View

struct StorageSettingsView: View {
    @State private var cacheSize = "Calculating..."
    @State private var isClearing = false

    var body: some View {
        Form {
            Section("Cache") {
                HStack {
                    Text("Image Cache")
                    Spacer()
                    Text(cacheSize)
                        .foregroundColor(.gray)
                }
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Image cache size: \(cacheSize)")

                Button("Clear Cache") {
                    // Haptic feedback: action started
                    HapticService.shared.buttonPress()
                    clearCache()
                }
                .disabled(isClearing)
                .accessibilityLabel("Clear cache")
                .accessibilityHint("Remove all cached images to free up storage space")
            }

            Section("Data") {
                Button("Clear All Local Data", role: .destructive) {
                    // Haptic feedback: warning for destructive action
                    HapticService.shared.warning()
                    clearAllData()
                }
                .accessibilityLabel("Clear all local data")
                .accessibilityHint("Remove all locally stored data. This cannot be undone.")
            }
        }
        .navigationTitle("Storage & Data")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            calculateCacheSize()
        }
    }

    private func calculateCacheSize() {
        guard let cacheURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else {
            cacheSize = "Unknown"
            return
        }
        var size: Int64 = 0

        if let enumerator = FileManager.default.enumerator(at: cacheURL, includingPropertiesForKeys: [.fileSizeKey]) {
            for case let fileURL as URL in enumerator {
                if let fileSize = try? fileURL.resourceValues(forKeys: [.fileSizeKey]).fileSize {
                    size += Int64(fileSize)
                }
            }
        }

        let formatter = ByteCountFormatter()
        formatter.allowedUnits = [.useKB, .useMB, .useGB]
        formatter.countStyle = .file
        cacheSize = formatter.string(fromByteCount: size)
    }

    private func clearCache() {
        isClearing = true

        Task {
            guard let cacheURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first else {
                await MainActor.run {
                    isClearing = false
                    // Haptic feedback: error
                    HapticService.shared.error()
                }
                return
            }
            try? FileManager.default.removeItem(at: cacheURL)
            try? FileManager.default.createDirectory(at: cacheURL, withIntermediateDirectories: true)

            await MainActor.run {
                calculateCacheSize()
                isClearing = false
                // Haptic feedback: cache cleared successfully
                HapticService.shared.success()
            }
        }
    }

    private func clearAllData() {
        if let bundleId = Bundle.main.bundleIdentifier {
            UserDefaults.standard.removePersistentDomain(forName: bundleId)
        }
        KeychainService.shared.clearAll()
        clearCache()
        // Haptic feedback: all data cleared
        HapticService.shared.success()
    }
}

#Preview {
    SettingsView()
        .environmentObject(AuthService.shared)
        .environmentObject(UploadQueue.shared)
}

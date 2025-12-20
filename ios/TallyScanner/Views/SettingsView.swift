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

                // Upload Queue Section
                uploadQueueSection

                // Server Section
                serverSection

                // Preferences Section
                preferencesSection

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

    private var accountSection: some View {
        Section("Account") {
            HStack {
                Image(systemName: "person.circle.fill")
                    .font(.largeTitle)
                    .foregroundColor(.tallyAccent)

                VStack(alignment: .leading) {
                    Text("TallyUps User")
                        .font(.headline)
                    Text("Connected")
                        .font(.caption)
                        .foregroundColor(.green)
                }
            }
            .padding(.vertical, 4)

            // Biometric Settings
            if authService.biometricType != .none {
                Toggle(isOn: Binding(
                    get: { authService.biometricsEnabled },
                    set: { newValue in
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
            }
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

            if uploadQueue.isUploading {
                HStack {
                    ProgressView()
                    Text("Uploading...")
                        .foregroundColor(.gray)
                }
            }

            if uploadQueue.pendingCount > 0 {
                Button("Clear Queue", role: .destructive) {
                    showingClearQueueConfirm = true
                }
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

            Button(action: checkServerHealth) {
                HStack {
                    Label("Check Connection", systemImage: "network")
                    Spacer()
                    if isCheckingHealth {
                        ProgressView()
                    } else if let health = healthStatus {
                        Image(systemName: health.ok ? "checkmark.circle.fill" : "xmark.circle.fill")
                            .foregroundColor(health.ok ? .green : .red)
                    }
                }
            }

            if let health = healthStatus {
                if let version = health.version {
                    HStack {
                        Text("Server Version")
                        Spacer()
                        Text(version)
                            .foregroundColor(.gray)
                    }
                }

                if let poolSize = health.poolSize, let active = health.activeConnections {
                    HStack {
                        Text("DB Connections")
                        Spacer()
                        Text("\(active)/\(poolSize)")
                            .foregroundColor(.gray)
                    }
                }
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

    var body: some View {
        Form {
            Section("Business") {
                Picker("Default Business", selection: $defaultBusiness) {
                    Text("Personal").tag("personal")
                    Text("Down Home").tag("downhome")
                    Text("MCR").tag("mcr")
                }
            }

            Section("Scanning") {
                Toggle("Auto OCR on upload", isOn: $autoOCR)
                Toggle("Auto-enhance images", isOn: $autoEnhance)
                Toggle("Save location with receipts", isOn: $saveLocation)
            }
        }
        .navigationTitle("Default Values")
        .navigationBarTitleDisplayMode(.inline)
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
                Toggle("Upload complete", isOn: $notifyUploadComplete)
                Toggle("OCR extraction complete", isOn: $notifyOCRComplete)
                Toggle("Match found", isOn: $notifyMatchFound)
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

                Button("Clear Cache") {
                    clearCache()
                }
                .disabled(isClearing)
            }

            Section("Data") {
                Button("Clear All Local Data", role: .destructive) {
                    clearAllData()
                }
            }
        }
        .navigationTitle("Storage & Data")
        .navigationBarTitleDisplayMode(.inline)
        .onAppear {
            calculateCacheSize()
        }
    }

    private func calculateCacheSize() {
        let cacheURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
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
            let cacheURL = FileManager.default.urls(for: .cachesDirectory, in: .userDomainMask).first!
            try? FileManager.default.removeItem(at: cacheURL)
            try? FileManager.default.createDirectory(at: cacheURL, withIntermediateDirectories: true)

            await MainActor.run {
                calculateCacheSize()
                isClearing = false
            }
        }
    }

    private func clearAllData() {
        UserDefaults.standard.removePersistentDomain(forName: Bundle.main.bundleIdentifier!)
        KeychainService.shared.clearAll()
        clearCache()
    }
}

#Preview {
    SettingsView()
        .environmentObject(AuthService.shared)
        .environmentObject(UploadQueue.shared)
}

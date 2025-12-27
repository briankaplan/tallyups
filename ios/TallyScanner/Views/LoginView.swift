import SwiftUI
import AuthenticationServices

struct LoginView: View {
    @EnvironmentObject var authService: AuthService

    @State private var serverURL = ""
    @State private var password = ""
    @State private var pin = ""
    @State private var apiKey = ""
    @State private var loginMethod = LoginMethod.password
    @State private var showingSetup = false
    @State private var showingLegacyLogin = false
    @State private var isAnimating = false

    enum LoginMethod: String, CaseIterable {
        case password = "Password"
        case pin = "PIN"
        case apiKey = "API Key"
    }

    var body: some View {
        ZStack {
            // Background
            Color.tallyBackground.ignoresSafeArea()

            VStack(spacing: 32) {
                Spacer()

                // Logo
                VStack(spacing: 16) {
                    Image(systemName: "doc.viewfinder.fill")
                        .font(.system(size: 80))
                        .foregroundColor(.tallyAccent)
                        .scaleEffect(isAnimating ? 1.05 : 1.0)
                        .animation(.easeInOut(duration: 2).repeatForever(autoreverses: true), value: isAnimating)

                    Text("TallyUps")
                        .font(.largeTitle.bold())
                        .foregroundColor(.white)

                    Text("Never do expenses again. Seriously.")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                }

                Spacer()

                // Primary Login Options
                VStack(spacing: 20) {
                    // Sign in with Apple (Primary)
                    appleSignInButton

                    // Biometric Login (if available and has stored credentials)
                    if authService.canUseBiometrics {
                        biometricButton
                    }

                    // Divider with "or"
                    HStack {
                        Rectangle()
                            .fill(Color.gray.opacity(0.3))
                            .frame(height: 1)
                        Text("or")
                            .font(.caption)
                            .foregroundColor(.gray)
                        Rectangle()
                            .fill(Color.gray.opacity(0.3))
                            .frame(height: 1)
                    }
                    .padding(.vertical, 8)

                    // Legacy Login Toggle
                    Button(action: { withAnimation { showingLegacyLogin.toggle() } }) {
                        HStack {
                            Text("Other sign in options")
                                .font(.subheadline)
                            Image(systemName: showingLegacyLogin ? "chevron.up" : "chevron.down")
                                .font(.caption)
                        }
                        .foregroundColor(.gray)
                    }

                    // Legacy Login Form (collapsible)
                    if showingLegacyLogin {
                        legacyLoginForm
                            .transition(.opacity.combined(with: .move(edge: .top)))
                    }

                    // Error Message
                    if let error = authService.error {
                        Text(error)
                            .font(.caption)
                            .foregroundColor(.red)
                            .multilineTextAlignment(.center)
                            .padding(.top, 8)
                    }
                }
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(20)
                .padding(.horizontal)

                // Server Setup
                Button(action: { showingSetup = true }) {
                    HStack {
                        Image(systemName: "gear")
                        Text("Server Settings")
                    }
                    .font(.subheadline)
                    .foregroundColor(.gray)
                }

                Spacer()
            }
        }
        .onAppear {
            isAnimating = true
            serverURL = authService.serverURL
        }
        .sheet(isPresented: $showingSetup) {
            ServerSetupView(serverURL: $serverURL)
        }
    }

    // MARK: - Sign in with Apple Button

    private var appleSignInButton: some View {
        Button(action: signInWithApple) {
            HStack(spacing: 8) {
                if authService.isLoading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .black))
                } else {
                    Image(systemName: "apple.logo")
                        .font(.title2)
                    Text("Sign in with Apple")
                        .font(.headline)
                }
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color.white)
            .foregroundColor(.black)
            .cornerRadius(12)
        }
        .disabled(authService.isLoading)
    }

    // MARK: - Biometric Button

    private var biometricButton: some View {
        Button(action: loginWithBiometrics) {
            HStack {
                Image(systemName: authService.biometricType.icon)
                    .font(.title2)
                Text("Sign in with \(authService.biometricType.name)")
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color.tallyBackground)
            .foregroundColor(.white)
            .cornerRadius(12)
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .strokeBorder(Color.tallyAccent, lineWidth: 1)
            )
        }
    }

    // MARK: - Legacy Login Form

    private var legacyLoginForm: some View {
        VStack(spacing: 16) {
            // Login Method Picker
            Picker("Login Method", selection: $loginMethod) {
                ForEach(LoginMethod.allCases, id: \.self) { method in
                    Text(method.rawValue).tag(method)
                }
            }
            .pickerStyle(.segmented)

            // Login Fields
            switch loginMethod {
            case .password:
                passwordField
            case .pin:
                pinField
            case .apiKey:
                apiKeyField
            }

            // Login Button
            Button(action: legacyLogin) {
                if authService.isLoading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .black))
                } else {
                    Text("Sign In")
                        .font(.headline)
                }
            }
            .frame(maxWidth: .infinity)
            .padding()
            .background(Color.tallyAccent)
            .foregroundColor(.black)
            .cornerRadius(12)
            .disabled(authService.isLoading)
        }
    }

    // MARK: - Login Fields

    private var passwordField: some View {
        SecureField("Password", text: $password)
            .textContentType(.password)
            .padding()
            .background(Color.tallyBackground)
            .cornerRadius(8)
    }

    private var pinField: some View {
        SecureField("PIN", text: $pin)
            .keyboardType(.numberPad)
            .textContentType(.oneTimeCode)
            .padding()
            .background(Color.tallyBackground)
            .cornerRadius(8)
    }

    private var apiKeyField: some View {
        SecureField("API Key", text: $apiKey)
            .textContentType(.password)
            .padding()
            .background(Color.tallyBackground)
            .cornerRadius(8)
    }

    // MARK: - Login Actions

    private func signInWithApple() {
        Task {
            _ = await authService.signInWithApple()
        }
    }

    private func legacyLogin() {
        Task {
            var success = false

            switch loginMethod {
            case .password:
                success = await authService.loginWithPassword(password)
                if success && authService.biometricType != .none {
                    authService.storePasswordForBiometrics(password)
                }
            case .pin:
                success = await authService.loginWithPIN(pin)
                if success && authService.biometricType != .none {
                    authService.storePINForBiometrics(pin)
                }
            case .apiKey:
                success = await authService.loginWithAPIKey(apiKey)
            }
        }
    }

    private func loginWithBiometrics() {
        Task {
            _ = await authService.authenticateWithBiometrics()
        }
    }
}

// MARK: - Server Setup View

struct ServerSetupView: View {
    @Binding var serverURL: String
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var authService: AuthService

    @State private var isTestingConnection = false
    @State private var connectionStatus: ConnectionStatus = .unknown

    enum ConnectionStatus {
        case unknown
        case success
        case failure(String)
    }

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("https://your-app.railway.app", text: $serverURL)
                        .keyboardType(.URL)
                        .textContentType(.URL)
                        .autocapitalization(.none)
                        .autocorrectionDisabled()
                } header: {
                    Text("Server URL")
                } footer: {
                    Text("Enter the URL of your TallyUps server")
                }

                Section {
                    Button(action: testConnection) {
                        HStack {
                            if isTestingConnection {
                                ProgressView()
                            } else {
                                Image(systemName: statusIcon)
                                    .foregroundColor(statusColor)
                            }
                            Text("Test Connection")
                        }
                    }
                    .disabled(serverURL.isEmpty || isTestingConnection)
                } footer: {
                    if case .failure(let error) = connectionStatus {
                        Text(error)
                            .foregroundColor(.red)
                    } else if case .success = connectionStatus {
                        Text("Connection successful!")
                            .foregroundColor(.green)
                    }
                }

                Section {
                    Text("The iOS app connects to your TallyUps server to upload receipts and sync data. Your server should be running on Railway or another hosting provider.")
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }
            .navigationTitle("Server Settings")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        authService.serverURL = serverURL
                        dismiss()
                    }
                    .disabled(serverURL.isEmpty)
                }
            }
        }
    }

    private var statusIcon: String {
        switch connectionStatus {
        case .unknown: return "questionmark.circle"
        case .success: return "checkmark.circle.fill"
        case .failure: return "xmark.circle.fill"
        }
    }

    private var statusColor: Color {
        switch connectionStatus {
        case .unknown: return .gray
        case .success: return .green
        case .failure: return .red
        }
    }

    private func testConnection() {
        isTestingConnection = true
        connectionStatus = .unknown

        Task {
            // Temporarily set URL for testing
            await APIClient.shared.setBaseURL(serverURL)

            do {
                let health = try await APIClient.shared.checkHealth()
                await MainActor.run {
                    if health.ok {
                        connectionStatus = .success
                    } else {
                        connectionStatus = .failure("Server responded but reported unhealthy status")
                    }
                }
            } catch {
                await MainActor.run {
                    connectionStatus = .failure(error.localizedDescription)
                }
            }

            isTestingConnection = false
        }
    }
}

#Preview {
    LoginView()
        .environmentObject(AuthService.shared)
}

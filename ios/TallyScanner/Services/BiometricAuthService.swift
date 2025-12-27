import LocalAuthentication
import SwiftUI

/// Service for Face ID / Touch ID biometric authentication
@MainActor
class BiometricAuthService: ObservableObject {
    static let shared = BiometricAuthService()

    @Published var isAvailable = false
    @Published var biometricType: BiometricType = .none
    @Published var isAuthenticated = false
    @Published var error: String?

    enum BiometricType: String {
        case none = "None"
        case faceID = "Face ID"
        case touchID = "Touch ID"
        case opticID = "Optic ID"

        var icon: String {
            switch self {
            case .none: return "lock.fill"
            case .faceID: return "faceid"
            case .touchID: return "touchid"
            case .opticID: return "opticid"
            }
        }
    }

    private let context = LAContext()

    private init() {
        checkAvailability()
    }

    // MARK: - Availability

    /// Check if biometric authentication is available
    func checkAvailability() {
        var error: NSError?
        isAvailable = context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)

        if isAvailable {
            switch context.biometryType {
            case .faceID:
                biometricType = .faceID
            case .touchID:
                biometricType = .touchID
            case .opticID:
                biometricType = .opticID
            @unknown default:
                biometricType = .none
            }
        } else {
            biometricType = .none
            if let error = error {
                print("🔐 BiometricAuth: Not available - \(error.localizedDescription)")
            }
        }

        print("🔐 BiometricAuth: Available: \(isAvailable), Type: \(biometricType.rawValue)")
    }

    // MARK: - Authentication

    /// Authenticate using biometrics
    func authenticate(reason: String = "Unlock TallyUps to access your receipts") async -> Bool {
        guard isAvailable else {
            error = "Biometric authentication not available"
            return false
        }

        let context = LAContext()
        context.localizedCancelTitle = "Use PIN"
        context.localizedFallbackTitle = "Use PIN"

        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: reason
            )

            isAuthenticated = success
            error = nil

            if success {
                HapticService.shared.notification(.success)
                print("🔐 BiometricAuth: Authentication successful")
            }

            return success
        } catch let authError as LAError {
            isAuthenticated = false
            error = mapError(authError)
            print("🔐 BiometricAuth: Failed - \(error ?? "Unknown")")

            // Provide haptic feedback for failure
            if authError.code != .userCancel && authError.code != .userFallback {
                HapticService.shared.notification(.error)
            }

            return false
        } catch {
            isAuthenticated = false
            self.error = error.localizedDescription
            return false
        }
    }

    /// Authenticate with fallback to device passcode
    func authenticateWithPasscode(reason: String = "Unlock TallyUps") async -> Bool {
        let context = LAContext()
        context.localizedCancelTitle = "Cancel"

        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthentication,  // Allows passcode fallback
                localizedReason: reason
            )

            isAuthenticated = success
            error = nil
            return success
        } catch {
            isAuthenticated = false
            self.error = error.localizedDescription
            return false
        }
    }

    // MARK: - Settings

    /// Whether biometric unlock is enabled (user preference)
    var isBiometricUnlockEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: "biometric_unlock_enabled") }
        set { UserDefaults.standard.set(newValue, forKey: "biometric_unlock_enabled") }
    }

    /// Enable biometric unlock (prompts user to authenticate first)
    func enableBiometricUnlock() async -> Bool {
        guard isAvailable else { return false }

        let success = await authenticate(reason: "Enable \(biometricType.rawValue) for quick access")
        if success {
            isBiometricUnlockEnabled = true
        }
        return success
    }

    /// Disable biometric unlock
    func disableBiometricUnlock() {
        isBiometricUnlockEnabled = false
    }

    // MARK: - Error Mapping

    private func mapError(_ error: LAError) -> String {
        switch error.code {
        case .authenticationFailed:
            return "Authentication failed. Please try again."
        case .userCancel:
            return "Authentication cancelled."
        case .userFallback:
            return "Switched to PIN entry."
        case .biometryNotAvailable:
            return "\(biometricType.rawValue) is not available on this device."
        case .biometryNotEnrolled:
            return "No \(biometricType.rawValue) enrolled. Please set up in Settings."
        case .biometryLockout:
            return "\(biometricType.rawValue) is locked. Use your device passcode."
        case .passcodeNotSet:
            return "Please set a device passcode to enable \(biometricType.rawValue)."
        default:
            return "Authentication error. Please try again."
        }
    }
}

// MARK: - Biometric Settings View

struct BiometricSettingsView: View {
    @ObservedObject var service = BiometricAuthService.shared
    @State private var isEnabling = false

    var body: some View {
        if service.isAvailable {
            VStack(alignment: .leading, spacing: 12) {
                HStack {
                    Image(systemName: service.biometricType.icon)
                        .font(.title2)
                        .foregroundColor(.tallyAccent)
                        .frame(width: 30)

                    VStack(alignment: .leading, spacing: 2) {
                        Text(service.biometricType.rawValue)
                            .font(.headline)
                            .foregroundColor(.white)

                        Text("Quick unlock with \(service.biometricType.rawValue)")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }

                    Spacer()

                    if isEnabling {
                        ProgressView()
                    } else {
                        Toggle("", isOn: Binding(
                            get: { service.isBiometricUnlockEnabled },
                            set: { newValue in
                                Task {
                                    isEnabling = true
                                    if newValue {
                                        await service.enableBiometricUnlock()
                                    } else {
                                        service.disableBiometricUnlock()
                                    }
                                    isEnabling = false
                                }
                            }
                        ))
                        .labelsHidden()
                        .tint(.tallyAccent)
                    }
                }
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(12)

                if let error = service.error {
                    Text(error)
                        .font(.caption)
                        .foregroundColor(.orange)
                        .padding(.horizontal)
                }
            }
        }
    }
}

// MARK: - Biometric Prompt View

struct BiometricPromptView: View {
    @ObservedObject var service = BiometricAuthService.shared
    let onSuccess: () -> Void
    let onFallback: () -> Void

    @State private var isAuthenticating = false
    @State private var showError = false

    var body: some View {
        VStack(spacing: 32) {
            Spacer()

            // Icon
            ZStack {
                Circle()
                    .fill(Color.tallyAccent.opacity(0.1))
                    .frame(width: 120, height: 120)

                Image(systemName: service.biometricType.icon)
                    .font(.system(size: 50))
                    .foregroundColor(.tallyAccent)
            }

            // Title
            VStack(spacing: 8) {
                Text("Welcome Back")
                    .font(.title.bold())
                    .foregroundColor(.white)

                Text("Use \(service.biometricType.rawValue) to unlock")
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }

            Spacer()

            // Error message
            if showError, let error = service.error {
                Text(error)
                    .font(.caption)
                    .foregroundColor(.orange)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            // Authenticate button
            Button(action: authenticate) {
                HStack {
                    if isAuthenticating {
                        ProgressView()
                            .tint(.black)
                    } else {
                        Image(systemName: service.biometricType.icon)
                        Text("Unlock with \(service.biometricType.rawValue)")
                    }
                }
                .font(.headline)
                .foregroundColor(.black)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }
            .disabled(isAuthenticating)
            .padding(.horizontal, 24)

            // Fallback button
            Button(action: onFallback) {
                Text("Use PIN Instead")
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }
            .padding(.bottom, 32)
        }
        .background(Color.tallyBackground.ignoresSafeArea())
        .onAppear {
            // Auto-prompt on appear
            if service.isBiometricUnlockEnabled {
                authenticate()
            }
        }
    }

    private func authenticate() {
        isAuthenticating = true
        showError = false

        Task {
            let success = await service.authenticate()
            isAuthenticating = false

            if success {
                onSuccess()
            } else if service.error != nil {
                showError = true
            }
        }
    }
}

// MARK: - Preview

#Preview("Settings") {
    BiometricSettingsView()
        .padding()
        .background(Color.tallyBackground)
}

#Preview("Prompt") {
    BiometricPromptView(
        onSuccess: { print("Success") },
        onFallback: { print("Fallback") }
    )
}

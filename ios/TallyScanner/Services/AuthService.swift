import Foundation
import LocalAuthentication
import SwiftUI
import AuthenticationServices

@MainActor
class AuthService: ObservableObject {
    static let shared = AuthService()

    @Published var isAuthenticated = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var biometricType: BiometricType = .none

    // User info (for multi-user mode)
    @Published var currentUser: UserInfo?
    @Published var needsOnboarding = false

    /// Represents the authenticated user
    struct UserInfo: Codable {
        let id: String
        let email: String?
        let name: String?
        let role: String
        let onboardingCompleted: Bool

        enum CodingKeys: String, CodingKey {
            case id, email, name, role
            case onboardingCompleted = "onboarding_completed"
        }
    }

    enum BiometricType {
        case none
        case touchID
        case faceID

        var icon: String {
            switch self {
            case .none: return "lock.fill"
            case .touchID: return "touchid"
            case .faceID: return "faceid"
            }
        }

        var name: String {
            switch self {
            case .none: return "Password"
            case .touchID: return "Touch ID"
            case .faceID: return "Face ID"
            }
        }
    }

    private let context = LAContext()

    private init() {
        checkBiometricType()
        checkExistingSession()

        // Setup credential revocation observer
        _ = AppleCredentialObserver.shared
    }

    // MARK: - Biometric Support

    private func checkBiometricType() {
        var error: NSError?

        if context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error) {
            switch context.biometryType {
            case .faceID:
                biometricType = .faceID
            case .touchID:
                biometricType = .touchID
            default:
                biometricType = .none
            }
        } else {
            biometricType = .none
        }
    }

    var canUseBiometrics: Bool {
        biometricType != .none && biometricsEnabled
    }

    var biometricsEnabled: Bool {
        get { UserDefaults.standard.bool(forKey: "biometrics_enabled") }
        set { UserDefaults.standard.set(newValue, forKey: "biometrics_enabled") }
    }

    // MARK: - Session Management

    private func checkExistingSession() {
        // Check if we have a stored session
        if KeychainService.shared.get(key: "session_token") != nil ||
           KeychainService.shared.get(key: "admin_api_key") != nil {

            // Validate session with server
            Task {
                await validateSession()
            }
        }
    }

    private func validateSession() async {
        do {
            let health = try await APIClient.shared.checkHealth()
            if health.ok {
                isAuthenticated = true
            }
        } catch {
            // Session invalid, require re-login
            isAuthenticated = false
        }
    }

    // MARK: - Login Methods

    func loginWithPassword(_ password: String) async -> Bool {
        isLoading = true
        error = nil

        defer { isLoading = false }

        do {
            let success = try await APIClient.shared.login(password: password)
            if success {
                isAuthenticated = true
                return true
            } else {
                error = "Invalid password"
                return false
            }
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func loginWithPIN(_ pin: String) async -> Bool {
        isLoading = true
        error = nil

        defer { isLoading = false }

        do {
            let success = try await APIClient.shared.loginWithPIN(pin)
            if success {
                isAuthenticated = true
                return true
            } else {
                error = "Invalid PIN"
                return false
            }
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    func loginWithAPIKey(_ apiKey: String) async -> Bool {
        isLoading = true
        error = nil

        defer { isLoading = false }

        await APIClient.shared.setAdminKey(apiKey)

        do {
            let health = try await APIClient.shared.checkHealth()
            if health.ok {
                isAuthenticated = true
                return true
            } else {
                error = "Invalid API key"
                await APIClient.shared.clearCredentials()
                return false
            }
        } catch {
            self.error = error.localizedDescription
            await APIClient.shared.clearCredentials()
            return false
        }
    }

    func authenticateWithBiometrics() async -> Bool {
        guard canUseBiometrics else {
            error = "Biometrics not available"
            return false
        }

        let context = LAContext()
        var authError: NSError?

        guard context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &authError) else {
            error = authError?.localizedDescription ?? "Biometrics unavailable"
            return false
        }

        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: "Unlock TallyUps"
            )

            if success {
                // Use stored credentials
                if let storedPassword = KeychainService.shared.get(key: "stored_password") {
                    return await loginWithPassword(storedPassword)
                } else if let storedPIN = KeychainService.shared.get(key: "stored_pin") {
                    return await loginWithPIN(storedPIN)
                } else if KeychainService.shared.get(key: "admin_api_key") != nil {
                    isAuthenticated = true
                    return true
                }
            }

            return false
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    // MARK: - Sign in with Apple

    /// Sign in with Apple - primary authentication method
    func signInWithApple() async -> Bool {
        isLoading = true
        error = nil

        defer { isLoading = false }

        do {
            // Get Apple credential
            let appleResult = try await AppleSignInService.shared.signIn()

            // Get device ID
            let deviceId = getOrCreateDeviceId()
            let deviceName = await MainActor.run { UIDevice.current.name }

            // Authenticate with backend
            let authResult = try await APIClient.shared.authenticateWithApple(
                identityToken: appleResult.identityToken,
                userName: appleResult.fullName,
                deviceId: deviceId,
                deviceName: deviceName
            )

            // Store tokens
            KeychainService.shared.saveSensitive(key: "access_token", value: authResult.accessToken)
            KeychainService.shared.saveSensitive(key: "refresh_token", value: authResult.refreshToken)
            KeychainService.shared.save(key: "apple_user_id", value: appleResult.userID)

            // Update state
            currentUser = authResult.user
            needsOnboarding = !(authResult.user.onboardingCompleted)
            isAuthenticated = true

            return true

        } catch let error as AppleSignInError where error == .cancelled {
            // User cancelled - not an error
            return false
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    /// Check and refresh access token if needed
    func refreshTokenIfNeeded() async -> Bool {
        guard let refreshToken = KeychainService.shared.get(key: "refresh_token") else {
            return false
        }

        let deviceId = getOrCreateDeviceId()

        do {
            let tokens = try await APIClient.shared.refreshToken(
                refreshToken: refreshToken,
                deviceId: deviceId
            )

            // Store new tokens
            KeychainService.shared.saveSensitive(key: "access_token", value: tokens.accessToken)
            KeychainService.shared.saveSensitive(key: "refresh_token", value: tokens.refreshToken)

            return true
        } catch {
            // Refresh failed - need to re-authenticate
            return false
        }
    }

    /// Handle Apple credential revocation
    func handleAppleCredentialRevoked() async {
        // Clear credentials and log out
        await logout()
        error = "Your Apple ID was disconnected. Please sign in again."
    }

    // MARK: - Device ID Management

    private func getOrCreateDeviceId() -> String {
        if let deviceId = KeychainService.shared.get(key: "device_id") {
            return deviceId
        }

        let deviceId = UUID().uuidString
        KeychainService.shared.save(key: "device_id", value: deviceId)
        return deviceId
    }

    // MARK: - Logout

    func logout() async {
        let deviceId = getOrCreateDeviceId()

        do {
            try await APIClient.shared.logout(deviceId: deviceId)
        } catch {
            // Ignore logout errors
        }

        // Clear stored credentials
        KeychainService.shared.delete(key: "access_token")
        KeychainService.shared.delete(key: "refresh_token")
        KeychainService.shared.delete(key: "apple_user_id")

        currentUser = nil
        needsOnboarding = false
        isAuthenticated = false
    }

    /// Delete user account (GDPR compliance)
    func deleteAccount() async -> Bool {
        do {
            try await APIClient.shared.deleteAccount()

            // Clear all credentials
            KeychainService.shared.delete(key: "access_token")
            KeychainService.shared.delete(key: "refresh_token")
            KeychainService.shared.delete(key: "apple_user_id")
            KeychainService.shared.delete(key: "device_id")
            KeychainService.shared.delete(key: "admin_api_key")

            currentUser = nil
            isAuthenticated = false

            return true
        } catch {
            self.error = error.localizedDescription
            return false
        }
    }

    // MARK: - Credential Storage for Biometrics

    func storePasswordForBiometrics(_ password: String) {
        // Use enhanced security for sensitive credentials
        KeychainService.shared.saveSensitive(key: "stored_password", value: password)
        biometricsEnabled = true
    }

    func storePINForBiometrics(_ pin: String) {
        // Use enhanced security for sensitive credentials
        KeychainService.shared.saveSensitive(key: "stored_pin", value: pin)
        biometricsEnabled = true
    }

    func clearStoredCredentials() {
        KeychainService.shared.delete(key: "stored_password")
        KeychainService.shared.delete(key: "stored_pin")
        biometricsEnabled = false
    }

    // MARK: - Server Configuration

    var serverURL: String {
        get { UserDefaults.standard.string(forKey: "api_base_url") ?? "" }
        set {
            UserDefaults.standard.set(newValue, forKey: "api_base_url")
            Task {
                await APIClient.shared.setBaseURL(newValue)
            }
        }
    }
}

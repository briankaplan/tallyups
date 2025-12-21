import Foundation
import LocalAuthentication
import SwiftUI

@MainActor
class AuthService: ObservableObject {
    static let shared = AuthService()

    @Published var isAuthenticated = false
    @Published var isLoading = false
    @Published var error: String?
    @Published var biometricType: BiometricType = .none

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
                localizedReason: "Unlock TallyScanner"
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

    // MARK: - Logout

    func logout() async {
        do {
            try await APIClient.shared.logout()
        } catch {
            // Ignore logout errors
        }

        isAuthenticated = false
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

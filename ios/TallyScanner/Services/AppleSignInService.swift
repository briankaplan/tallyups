import Foundation
import AuthenticationServices
import CryptoKit

/// Service for handling Sign in with Apple authentication
@MainActor
class AppleSignInService: NSObject, ObservableObject {
    static let shared = AppleSignInService()

    @Published var isSigningIn = false
    @Published var error: String?

    /// Current nonce for Apple Sign In request
    private var currentNonce: String?

    /// Completion handler for sign in flow
    private var signInCompletion: ((Result<AppleSignInResult, Error>) -> Void)?

    private override init() {
        super.init()
    }

    // MARK: - Public API

    /// Sign in with Apple
    /// - Parameter completion: Completion handler with result
    func signIn() async throws -> AppleSignInResult {
        return try await withCheckedThrowingContinuation { continuation in
            performSignIn { result in
                continuation.resume(with: result)
            }
        }
    }

    /// Check if a Sign in with Apple credential is still valid
    func checkCredentialState(userID: String) async -> ASAuthorizationAppleIDProvider.CredentialState {
        await withCheckedContinuation { continuation in
            let provider = ASAuthorizationAppleIDProvider()
            provider.getCredentialState(forUserID: userID) { state, _ in
                continuation.resume(returning: state)
            }
        }
    }

    // MARK: - Private Implementation

    private func performSignIn(completion: @escaping (Result<AppleSignInResult, Error>) -> Void) {
        isSigningIn = true
        error = nil
        signInCompletion = completion

        // Generate nonce for security
        let nonce = randomNonceString()
        currentNonce = nonce

        // Create request
        let appleIDProvider = ASAuthorizationAppleIDProvider()
        let request = appleIDProvider.createRequest()
        request.requestedScopes = [.fullName, .email]
        request.nonce = sha256(nonce)

        // Create authorization controller
        let authorizationController = ASAuthorizationController(authorizationRequests: [request])
        authorizationController.delegate = self
        authorizationController.presentationContextProvider = self
        authorizationController.performRequests()
    }

    // MARK: - Nonce Generation

    /// Generate a random nonce string for Apple Sign In
    private func randomNonceString(length: Int = 32) -> String {
        precondition(length > 0)
        var randomBytes = [UInt8](repeating: 0, count: length)
        let errorCode = SecRandomCopyBytes(kSecRandomDefault, randomBytes.count, &randomBytes)
        if errorCode != errSecSuccess {
            fatalError("Unable to generate nonce. SecRandomCopyBytes failed with OSStatus \(errorCode)")
        }

        let charset: [Character] = Array("0123456789ABCDEFGHIJKLMNOPQRSTUVXYZabcdefghijklmnopqrstuvwxyz-._")

        let nonce = randomBytes.map { byte in
            charset[Int(byte) % charset.count]
        }

        return String(nonce)
    }

    /// SHA256 hash of a string
    private func sha256(_ input: String) -> String {
        let inputData = Data(input.utf8)
        let hashedData = SHA256.hash(data: inputData)
        let hashString = hashedData.compactMap {
            String(format: "%02x", $0)
        }.joined()

        return hashString
    }
}

// MARK: - ASAuthorizationControllerDelegate

extension AppleSignInService: ASAuthorizationControllerDelegate {

    func authorizationController(controller: ASAuthorizationController, didCompleteWithAuthorization authorization: ASAuthorization) {
        isSigningIn = false

        guard let appleIDCredential = authorization.credential as? ASAuthorizationAppleIDCredential else {
            let error = AppleSignInError.invalidCredential
            self.error = error.localizedDescription
            signInCompletion?(.failure(error))
            signInCompletion = nil
            return
        }

        guard let identityTokenData = appleIDCredential.identityToken,
              let identityToken = String(data: identityTokenData, encoding: .utf8) else {
            let error = AppleSignInError.missingIdentityToken
            self.error = error.localizedDescription
            signInCompletion?(.failure(error))
            signInCompletion = nil
            return
        }

        // Extract user info
        let userID = appleIDCredential.user
        let email = appleIDCredential.email
        let fullName = appleIDCredential.fullName

        // Build user name from components
        var userName: String?
        if let fullName = fullName {
            let components = [fullName.givenName, fullName.familyName].compactMap { $0 }
            if !components.isEmpty {
                userName = components.joined(separator: " ")
            }
        }

        let result = AppleSignInResult(
            userID: userID,
            identityToken: identityToken,
            email: email,
            fullName: userName,
            nonce: currentNonce
        )

        signInCompletion?(.success(result))
        signInCompletion = nil
        currentNonce = nil
    }

    func authorizationController(controller: ASAuthorizationController, didCompleteWithError error: Error) {
        isSigningIn = false

        if let authError = error as? ASAuthorizationError {
            switch authError.code {
            case .canceled:
                self.error = nil // User cancelled, not an error
                signInCompletion?(.failure(AppleSignInError.cancelled))
            case .invalidResponse:
                self.error = "Invalid response from Apple"
                signInCompletion?(.failure(AppleSignInError.invalidResponse))
            case .notHandled:
                self.error = "Request not handled"
                signInCompletion?(.failure(AppleSignInError.notHandled))
            case .failed:
                self.error = "Authentication failed"
                signInCompletion?(.failure(AppleSignInError.failed))
            case .unknown:
                self.error = "Unknown error occurred"
                signInCompletion?(.failure(AppleSignInError.unknown))
            case .notInteractive:
                self.error = "Not interactive"
                signInCompletion?(.failure(AppleSignInError.notInteractive))
            @unknown default:
                self.error = error.localizedDescription
                signInCompletion?(.failure(error))
            }
        } else {
            self.error = error.localizedDescription
            signInCompletion?(.failure(error))
        }

        signInCompletion = nil
        currentNonce = nil
    }
}

// MARK: - ASAuthorizationControllerPresentationContextProviding

extension AppleSignInService: ASAuthorizationControllerPresentationContextProviding {

    func presentationAnchor(for controller: ASAuthorizationController) -> ASPresentationAnchor {
        // Get the key window for presentation
        guard let scene = UIApplication.shared.connectedScenes.first as? UIWindowScene,
              let window = scene.windows.first else {
            fatalError("No window available for presentation")
        }
        return window
    }
}

// MARK: - Result Types

/// Result from successful Apple Sign In
struct AppleSignInResult {
    let userID: String
    let identityToken: String
    let email: String?
    let fullName: String?
    let nonce: String?
}

/// Errors that can occur during Apple Sign In
enum AppleSignInError: LocalizedError, Equatable {
    case cancelled
    case invalidCredential
    case missingIdentityToken
    case invalidResponse
    case notHandled
    case failed
    case unknown
    case notInteractive
    case serverError(String)

    var errorDescription: String? {
        switch self {
        case .cancelled:
            return "Sign in was cancelled"
        case .invalidCredential:
            return "Invalid credential received"
        case .missingIdentityToken:
            return "Missing identity token"
        case .invalidResponse:
            return "Invalid response from Apple"
        case .notHandled:
            return "Request was not handled"
        case .failed:
            return "Authentication failed"
        case .unknown:
            return "An unknown error occurred"
        case .notInteractive:
            return "Not interactive"
        case .serverError(let message):
            return message
        }
    }
}

// MARK: - Credential State Observer

/// Observer for Apple ID credential revocation
class AppleCredentialObserver {
    static let shared = AppleCredentialObserver()

    private init() {
        setupObserver()
    }

    private func setupObserver() {
        // Observe credential revocation notifications
        NotificationCenter.default.addObserver(
            self,
            selector: #selector(handleCredentialRevoked),
            name: ASAuthorizationAppleIDProvider.credentialRevokedNotification,
            object: nil
        )
    }

    @objc private func handleCredentialRevoked() {
        // User revoked their Apple ID credential
        // Log out the user
        Task { @MainActor in
            await AuthService.shared.handleAppleCredentialRevoked()
        }
    }
}

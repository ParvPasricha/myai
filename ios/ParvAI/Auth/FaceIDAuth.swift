import LocalAuthentication
import Foundation

/// Face ID / Touch ID authentication → JWT token from the server.
///
/// Flow:
///   1. Prompt Face ID locally (no network)
///   2. On success, POST /auth/token with a signed challenge (Phase 3: simple token)
///   3. Store JWT in Keychain via ConnectionManager
@MainActor
final class FaceIDAuth: ObservableObject {

    @Published var isAuthenticated = false
    @Published var errorMessage: String?

    private let context = LAContext()

    var isBiometricAvailable: Bool {
        var error: NSError?
        return context.canEvaluatePolicy(.deviceOwnerAuthenticationWithBiometrics, error: &error)
    }

    func authenticate() async -> Bool {
        guard isBiometricAvailable else {
            errorMessage = "Face ID not available on this device."
            return false
        }

        do {
            let success = try await context.evaluatePolicy(
                .deviceOwnerAuthenticationWithBiometrics,
                localizedReason: "Authenticate with PARV-AI"
            )
            guard success else { return false }

            // After biometric success, get token from server
            let gotToken = await ConnectionManager.shared.authenticate()
            if gotToken {
                isAuthenticated = true
                PingService.shared.start()
            } else {
                errorMessage = "Could not reach PARV-AI server. Check your connection."
            }
            return gotToken

        } catch let err as LAError {
            switch err.code {
            case .userCancel, .appCancel:
                break
            case .biometryNotEnrolled:
                errorMessage = "Face ID not enrolled. Enable it in Settings."
            default:
                errorMessage = err.localizedDescription
            }
            return false
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    func signOut() {
        isAuthenticated = false
        KeychainHelper.delete(key: "jwt")
        PingService.shared.stop()
        ConnectionManager.shared.disconnectWebSocket()
    }
}

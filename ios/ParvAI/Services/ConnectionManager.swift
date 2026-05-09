import Foundation
import Combine

/// Handles all network I/O: HTTP REST, JWT auth, and WebSocket push.
@MainActor
final class ConnectionManager: ObservableObject {

    static let shared = ConnectionManager()

    @Published var isConnected = false
    @Published var lastError: String?
    @Published var brainStatePush: BrainState?     // latest push from server
    @Published var suggestionPush: String?          // latest AI suggestion

    private var token: String? {
        get { KeychainHelper.read(key: "jwt") }
        set {
            if let v = newValue { KeychainHelper.write(key: "jwt", value: v) }
            else { KeychainHelper.delete(key: "jwt") }
        }
    }

    private var wsTask: URLSessionWebSocketTask?
    private var wsSession: URLSession?
    private var config: AppConfig { AppConfig.shared }

    // MARK: — Connection path selection

    enum ConnectionPath: String {
        case local      = "LAN"
        case tailscale  = "Tailscale"
        case tor        = "Tor (.onion)"
    }

    @Published var activePath: ConnectionPath = .tailscale

    /// Returns the best reachable base URL in priority order:
    /// 1. Configured serverURL (LAN or Tailscale)
    /// 2. .onion URL via Orbot SOCKS5 (if onionAddress is set)
    private func resolveBaseURL() async -> (url: String, path: ConnectionPath) {
        let primary = config.serverURL
        if await isReachable(primary) {
            return (primary, .tailscale)
        }
        if let onion = config.onionAPIURL, await isReachable(onion) {
            return (onion, .tor)
        }
        return (primary, .tailscale)   // fall back even if unreachable
    }

    private func isReachable(_ urlString: String) async -> Bool {
        guard let url = URL(string: urlString + "/health") else { return false }
        var req = URLRequest(url: url, timeoutInterval: 5)
        req.httpMethod = "GET"
        do {
            let (_, response) = try await URLSession.shared.data(for: req)
            return (response as? HTTPURLResponse)?.statusCode == 200
        } catch { return false }
    }

    /// Fetch the .onion address from the server and save it to AppConfig.
    func fetchAndSaveOnionAddress() async {
        guard token != nil else { return }
        do {
            struct OnionResp: Decodable { let onion: String? }
            let resp: OnionResp = try await get("/security/onion")
            if let onion = resp.onion {
                await MainActor.run { config.onionAddress = onion }
            }
        } catch {}
    }

    // MARK: — Auth

    func authenticate() async -> Bool {
        // Phase 3: dev token endpoint; replaced by Face ID → JWT in FaceIDAuth
        guard let url = URL(string: config.serverURL + "/auth/token") else { return false }
        do {
            var req = URLRequest(url: url)
            req.httpMethod = "POST"
            let (data, _) = try await URLSession.shared.data(for: req)
            let json = try JSONDecoder().decode([String: String].self, from: data)
            token = json["access_token"]
            isConnected = true
            return true
        } catch {
            lastError = error.localizedDescription
            return false
        }
    }

    func setToken(_ t: String) {
        token = t
        isConnected = true
    }

    // MARK: — HTTP

    func get<T: Decodable>(_ path: String) async throws -> T {
        try await request(path: path, method: "GET", body: nil)
    }

    func post<B: Encodable, T: Decodable>(_ path: String, body: B) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await request(path: path, method: "POST", body: data)
    }

    func patch<B: Encodable, T: Decodable>(_ path: String, body: B) async throws -> T {
        let data = try JSONEncoder().encode(body)
        return try await request(path: path, method: "PATCH", body: data)
    }

    private func request<T: Decodable>(path: String, method: String, body: Data?) async throws -> T {
        guard let url = URL(string: config.serverURL + path) else {
            throw URLError(.badURL)
        }
        var req = URLRequest(url: url, timeoutInterval: 15)
        req.httpMethod = method
        if let body { req.httpBody = body; req.setValue("application/json", forHTTPHeaderField: "Content-Type") }
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }

        let (data, response) = try await URLSession.shared.data(for: req)
        if let http = response as? HTTPURLResponse, http.statusCode == 401 {
            self.token = nil
            isConnected = false
            throw URLError(.userAuthenticationRequired)
        }
        return try JSONDecoder().decode(T.self, from: data)
    }

    // MARK: — Ping

    func ping() async {
        guard token != nil else { return }
        do {
            let _: [String: String] = try await post("/security/ping", body: EmptyBody())
        } catch {
            lastError = error.localizedDescription
        }
    }

    // MARK: — WebSocket

    func connectWebSocket() {
        guard let url = URL(string: config.serverURL.replacingOccurrences(of: "http", with: "ws") + "/ws") else { return }
        var req = URLRequest(url: url)
        if let token { req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization") }
        wsSession = URLSession(configuration: .default)
        wsTask = wsSession?.webSocketTask(with: req)
        wsTask?.resume()
        receiveNext()
    }

    func disconnectWebSocket() {
        wsTask?.cancel(with: .normalClosure, reason: nil)
        wsTask = nil
    }

    private func receiveNext() {
        wsTask?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let msg):
                Task { @MainActor in
                    self.handleWSMessage(msg)
                    self.receiveNext()
                }
            case .failure:
                Task { @MainActor in self.isConnected = false }
            }
        }
    }

    private func handleWSMessage(_ msg: URLSessionWebSocketTask.Message) {
        guard case .string(let text) = msg,
              let data = text.data(using: .utf8),
              let json = try? JSONDecoder().decode(WSEvent.self, from: data)
        else { return }

        switch json.type {
        case "brain_state_update":
            if let bs = try? JSONDecoder().decode(BrainState.self, from: data) {
                brainStatePush = bs
            }
        case "ai_suggestion":
            suggestionPush = json.payload
        default:
            break
        }
    }
}

// MARK: — Helpers

private struct EmptyBody: Encodable {}

private struct WSEvent: Decodable {
    let type: String
    let payload: String?
}

enum KeychainHelper {
    static func write(key: String, value: String) {
        let data = value.data(using: .utf8)!
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecValueData as String: data
        ]
        SecItemDelete(query as CFDictionary)
        SecItemAdd(query as CFDictionary, nil)
    }
    static func read(key: String) -> String? {
        let query: [String: Any] = [
            kSecClass as String: kSecClassGenericPassword,
            kSecAttrAccount as String: key,
            kSecReturnData as String: true
        ]
        var result: AnyObject?
        guard SecItemCopyMatching(query as CFDictionary, &result) == errSecSuccess,
              let data = result as? Data else { return nil }
        return String(data: data, encoding: .utf8)
    }
    static func delete(key: String) {
        let query: [String: Any] = [kSecClass as String: kSecClassGenericPassword, kSecAttrAccount as String: key]
        SecItemDelete(query as CFDictionary)
    }
}

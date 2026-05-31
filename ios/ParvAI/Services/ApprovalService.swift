import Foundation
import Combine

/// Polls /ws/approvals for pending send-on-behalf requests (texts, emails).
/// Publishes new approvals so ApprovalView can show the banner.
@MainActor
final class ApprovalService: ObservableObject {

    static let shared = ApprovalService()

    @Published var pending: [ApprovalRequest] = []

    private var ws: URLSessionWebSocketTask?
    private let session = URLSession(configuration: .default)

    struct ApprovalRequest: Identifiable, Codable {
        let id: String
        let type: String        // message | email | action
        let recipient: String
        let content: String
        let created_at: Double
        var edited: String?

        var displayType: String { type == "message" ? "iMessage" : "Email" }
    }

    func connect(token: String, host: String = "localhost:8000") {
        guard let url = URL(string: "ws://\(host)/ws/approvals") else { return }
        var req = URLRequest(url: url)
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        ws = session.webSocketTask(with: req)
        ws?.resume()
        listen()
        ping()
    }

    func disconnect() { ws?.cancel(); ws = nil }

    private func listen() {
        ws?.receive { [weak self] result in
            guard let self else { return }
            switch result {
            case .success(let msg):
                if case .string(let text) = msg,
                   let data = text.data(using: .utf8),
                   let evt  = try? JSONDecoder().decode(WSEvent.self, from: data) {
                    Task { @MainActor in
                        if evt.type == "approval_request", let req = evt.approval {
                            self.pending.append(req)
                        }
                    }
                }
                self.listen()
            case .failure:
                // Reconnect after 5s
                Task { @MainActor in
                    try? await Task.sleep(nanoseconds: 5_000_000_000)
                    self.listen()
                }
            }
        }
    }

    private func ping() {
        Task {
            while ws != nil {
                try? await Task.sleep(nanoseconds: 25_000_000_000)
                try? await ws?.send(.string("ping"))
            }
        }
    }

    func approve(_ request: ApprovalRequest, token: String, host: String = "localhost:8000") async {
        await post("/approvals/\(request.id)/approve", token: token, host: host, body: nil)
        pending.removeAll { $0.id == request.id }
    }

    func deny(_ request: ApprovalRequest, token: String, host: String = "localhost:8000") async {
        await post("/approvals/\(request.id)/deny", token: token, host: host, body: nil)
        pending.removeAll { $0.id == request.id }
    }

    func editAndApprove(_ request: ApprovalRequest, edited: String,
                        token: String, host: String = "localhost:8000") async {
        await post("/approvals/\(request.id)/edit", token: token, host: host,
                   body: ["content": edited])
        pending.removeAll { $0.id == request.id }
    }

    private func post(_ path: String, token: String, host: String, body: [String: String]?) async {
        guard let url = URL(string: "http://\(host)\(path)") else { return }
        var req = URLRequest(url: url)
        req.httpMethod = "POST"
        req.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        req.setValue("application/json", forHTTPHeaderField: "Content-Type")
        if let body { req.httpBody = try? JSONEncoder().encode(body) }
        _ = try? await URLSession.shared.data(for: req)
    }

    private struct WSEvent: Decodable {
        let type: String
        let approval: ApprovalRequest?

        enum CodingKeys: String, CodingKey { case type, approval }
        init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            type = try c.decode(String.self, forKey: .type)
            if type == "approval_request" {
                approval = try? ApprovalRequest(from: decoder)
            } else {
                approval = nil
            }
        }
    }
}

import Foundation
import Combine

/// Sends a heartbeat to /security/ping on a configurable interval.
/// Keeps the dead man's switch alive.
@MainActor
final class PingService: ObservableObject {

    static let shared = PingService()

    @Published var lastPingDate: Date?
    @Published var nextDeadline: Date?
    @Published var timeRemaining: TimeInterval = 0

    private var timer: Timer?
    private var countdown: Timer?

    private var intervalSeconds: TimeInterval {
        TimeInterval(AppConfig.shared.pingIntervalMinutes * 60)
    }

    func start() {
        stop()
        Task { await sendPing() }   // immediate first ping
        timer = Timer.scheduledTimer(withTimeInterval: intervalSeconds, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { await self.sendPing() }
        }
        startCountdown()
    }

    func stop() {
        timer?.invalidate()
        timer = nil
        countdown?.invalidate()
        countdown = nil
    }

    private func sendPing() async {
        do {
            let result: PingResponse = try await ConnectionManager.shared.post("/security/ping", body: EmptyBody())
            lastPingDate = .now
            if let deadline = result.nextDeadline {
                nextDeadline = Date(timeIntervalSince1970: deadline)
                timeRemaining = nextDeadline!.timeIntervalSinceNow
            }
        } catch {
            // Connection failure — don't crash, just log
        }
    }

    private func startCountdown() {
        countdown = Timer.scheduledTimer(withTimeInterval: 1, repeats: true) { [weak self] _ in
            guard let self else { return }
            Task { @MainActor in
                guard let deadline = self.nextDeadline else { return }
                self.timeRemaining = max(0, deadline.timeIntervalSinceNow)
            }
        }
    }
}

private struct EmptyBody: Encodable {}
private struct PingResponse: Decodable {
    let ok: Bool
    let nextDeadline: Double?
    enum CodingKeys: String, CodingKey {
        case ok
        case nextDeadline = "next_deadline"
    }
}

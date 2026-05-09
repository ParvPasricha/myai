import SwiftUI

struct StatusView: View {
    @StateObject private var ping = PingService.shared
    @StateObject private var conn = ConnectionManager.shared
    @State private var health: HealthResponse?
    @State private var isRefreshing = false

    var body: some View {
        NavigationStack {
            List {
                Section("Dead Man's Switch") {
                    DeadmanRow(ping: ping)
                }

                Section("System Health") {
                    if let h = health {
                        ForEach(Array(h.subsystems.sorted(by: { $0.key < $1.key })), id: \.key) { name, sub in
                            SubsystemRow(name: name, status: sub.status)
                        }
                    } else {
                        ProgressView("Loading…")
                    }
                }

                Section("Connection") {
                    LabeledContent("Server", value: AppConfig.shared.serverURL)
                    LabeledContent("Status", value: conn.isConnected ? "Connected" : "Disconnected")
                        .foregroundStyle(conn.isConnected ? .green : .red)
                    LabeledContent("Path", value: conn.activePath.rawValue)
                    if !AppConfig.shared.onionAddress.isEmpty {
                        LabeledContent(".onion", value: AppConfig.shared.onionAddress)
                            .font(.caption)
                    }
                }
            }
            .navigationTitle("Status")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button { Task { await refresh() } } label: {
                        Image(systemName: "arrow.clockwise")
                            .rotationEffect(.degrees(isRefreshing ? 360 : 0))
                            .animation(isRefreshing ? .linear(duration: 1).repeatForever(autoreverses: false) : .default,
                                       value: isRefreshing)
                    }
                }
            }
            .task { await refresh() }
        }
    }

    private func refresh() async {
        isRefreshing = true
        do {
            health = try await conn.get("/health")
        } catch { }
        isRefreshing = false
    }
}

struct DeadmanRow: View {
    @ObservedObject var ping: PingService

    private var pct: Double {
        guard ping.nextDeadline != nil else { return 1 }
        let total = AppConfig.shared.pingIntervalMinutes * 60
        return min(1, ping.timeRemaining / Double(total))
    }

    private var color: Color {
        pct > 0.5 ? .green : pct > 0.2 ? .orange : .red
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: "heart.fill").foregroundStyle(color)
                Text("Time Remaining")
                Spacer()
                Text(formatTime(ping.timeRemaining))
                    .monospacedDigit()
                    .foregroundStyle(color)
            }
            ProgressView(value: pct)
                .tint(color)
            if let last = ping.lastPingDate {
                Text("Last ping: \(last.formatted(.relative(presentation: .named)))")
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.vertical, 4)
    }

    private func formatTime(_ secs: TimeInterval) -> String {
        let s = Int(secs)
        return String(format: "%02d:%02d", s / 60, s % 60)
    }
}

struct SubsystemRow: View {
    let name: String
    let status: String

    private var icon: String {
        switch status {
        case "ok": return "checkmark.circle.fill"
        case "degraded": return "exclamationmark.triangle.fill"
        case "not_configured": return "minus.circle"
        default: return "xmark.circle.fill"
        }
    }

    private var color: Color {
        switch status {
        case "ok": return .green
        case "degraded": return .orange
        case "not_configured": return .secondary
        default: return .red
        }
    }

    var body: some View {
        LabeledContent(name.capitalized) {
            Label(status.replacingOccurrences(of: "_", with: " ").capitalized,
                  systemImage: icon)
                .foregroundStyle(color)
                .font(.caption)
        }
    }
}

// MARK: — Response Types

struct HealthResponse: Decodable {
    let status: String
    let subsystems: [String: SubsystemStatus]
}

struct SubsystemStatus: Decodable {
    let status: String
}

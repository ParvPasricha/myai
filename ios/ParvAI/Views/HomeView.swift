import SwiftUI

struct HomeView: View {
    @StateObject private var conn = ConnectionManager.shared
    @StateObject private var ping = PingService.shared
    @State private var brainState: BrainState = .placeholder
    @State private var isLoading = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    BrainStateCard(state: brainState)
                    PingStatusBar(service: ping)
                    ActivityCard(state: brainState)
                    Spacer()
                }
                .padding()
            }
            .navigationTitle("PARV-AI")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Circle()
                        .fill(conn.isConnected ? Color.green : Color.red)
                        .frame(width: 10, height: 10)
                }
            }
            .task { await loadBrainState() }
            .onChange(of: conn.brainStatePush) { _, new in
                if let new { brainState = new }
            }
        }
    }

    private func loadBrainState() async {
        do {
            brainState = try await conn.get("/brain/state")
        } catch { }
        isLoading = false
    }
}

// MARK: — Subviews

struct BrainStateCard: View {
    let state: BrainState

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Brain State")
                .font(.headline)
                .foregroundStyle(.secondary)

            HStack(spacing: 16) {
                MetricPill(label: "Focus", value: state.focus, color: .blue)
                MetricPill(label: "Energy", value: state.energy, color: .green)
                MetricPill(label: "Stress", value: state.stress, color: .orange)
            }

            if state.deepWork {
                Label("Deep Work", systemImage: "brain.head.profile")
                    .font(.caption)
                    .foregroundStyle(.purple)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

struct MetricPill: View {
    let label: String
    let value: Double
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            ZStack {
                Circle()
                    .stroke(color.opacity(0.25), lineWidth: 6)
                Circle()
                    .trim(from: 0, to: value / 10)
                    .stroke(color, style: StrokeStyle(lineWidth: 6, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                Text(String(Int(value)))
                    .font(.system(size: 18, weight: .bold, design: .rounded))
            }
            .frame(width: 64, height: 64)
            Text(label)
                .font(.caption2)
                .foregroundStyle(.secondary)
        }
    }
}

struct PingStatusBar: View {
    @ObservedObject var service: PingService

    private var formatted: String {
        let secs = Int(service.timeRemaining)
        let m = secs / 60
        let s = secs % 60
        return String(format: "%02d:%02d", m, s)
    }

    var body: some View {
        HStack {
            Image(systemName: "heart.fill")
                .foregroundStyle(.red)
            Text("Deadman: \(formatted) remaining")
                .font(.caption)
                .monospacedDigit()
            Spacer()
            if let last = service.lastPingDate {
                Text("Pinged \(last, style: .relative) ago")
                    .font(.caption2)
                    .foregroundStyle(.secondary)
            }
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.red.opacity(0.08), in: RoundedRectangle(cornerRadius: 10))
    }
}

struct ActivityCard: View {
    let state: BrainState

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text("Current Activity")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(state.currentActivity.capitalized)
                    .font(.title3.weight(.semibold))
            }
            Spacer()
            VStack(alignment: .trailing, spacing: 4) {
                Text("Location")
                    .font(.caption)
                    .foregroundStyle(.secondary)
                Text(state.location.capitalized)
                    .font(.title3.weight(.semibold))
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
    }
}

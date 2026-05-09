import SwiftUI

struct SettingsView: View {
    @StateObject private var config = AppConfig.shared
    @StateObject private var auth = FaceIDAuth()
    @State private var showingSignOut = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Server") {
                    LabeledContent("Primary URL") {
                        TextField("http://...", text: $config.serverURL)
                            .multilineTextAlignment(.trailing)
                            .keyboardType(.URL)
                            .autocorrectionDisabled()
                    }
                    LabeledContent("Tor .onion") {
                        TextField("abc123.onion (optional)", text: $config.onionAddress)
                            .multilineTextAlignment(.trailing)
                            .keyboardType(.URL)
                            .autocorrectionDisabled()
                            .font(.caption)
                    }
                    Button("Fetch .onion from server") {
                        Task { await ConnectionManager.shared.fetchAndSaveOnionAddress() }
                    }
                    .font(.caption)
                }

                Section {
                    Stepper("Ping interval: \(config.pingIntervalMinutes) min",
                            value: $config.pingIntervalMinutes, in: 1...1440)
                    Text("How often the app sends a heartbeat. If missed for this long, system locks.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Dead Man's Switch")
                }

                Section {
                    Picker("Mic Stage", selection: $config.micStage) {
                        Text("Push-to-talk").tag(1)
                        Text("Wake phrase").tag(2)
                        Text("Passive context").tag(3)
                        Text("Always-on (VoIP)").tag(4)
                    }
                    Text(stageDescription)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                } header: {
                    Text("Microphone")
                }

                Section("Account") {
                    Button("Sign Out", role: .destructive) {
                        showingSignOut = true
                    }
                }
            }
            .navigationTitle("Settings")
            .confirmationDialog("Sign Out", isPresented: $showingSignOut) {
                Button("Sign Out", role: .destructive) { auth.signOut() }
                Button("Cancel", role: .cancel) { }
            }
        }
    }

    private var stageDescription: String {
        switch config.micStage {
        case 1: return "Hold the mic button to record. Safest, lowest battery impact."
        case 2: return "Say 'Hey Parv' to activate. No background drain."
        case 3: return "Mic active during pre-set hours only."
        case 4: return "Always-on via VoIP mode. Requires sideloading with Apple Developer account."
        default: return ""
        }
    }
}

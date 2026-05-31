import SwiftUI

@main
struct ParvAIApp: App {
    @StateObject private var auth = FaceIDAuth()

    var body: some Scene {
        WindowGroup {
            if auth.isAuthenticated {
                MainTabView()
                    .environmentObject(auth)
            } else {
                LoginView(auth: auth)
            }
        }
    }
}

struct MainTabView: View {
    var body: some View {
        TabView {
            HomeView()
                .tabItem { Label("Home", systemImage: "house.fill") }
            ChatView()
                .tabItem { Label("Chat", systemImage: "mic.fill") }
            ResearchView()
                .tabItem { Label("Research", systemImage: "books.vertical.fill") }
            StatusView()
                .tabItem { Label("Status", systemImage: "heart.text.square.fill") }
            SettingsView()
                .tabItem { Label("Settings", systemImage: "gear") }
        }
        .onAppear {
            ConnectionManager.shared.connectWebSocket()
            PingService.shared.start()
        }
    }
}

struct LoginView: View {
    @ObservedObject var auth: FaceIDAuth
    @State private var isAuthenticating = false
    @State private var showServerSetup = false
    @StateObject private var config = AppConfig.shared

    private var serverIsLocalhost: Bool {
        ConnectionManager.shared.isServerLocalhost
    }

    var body: some View {
        VStack(spacing: 32) {
            Spacer()
            Image(systemName: "brain.head.profile")
                .font(.system(size: 80))
                .foregroundStyle(.blue)
            Text("PARV-AI")
                .font(.largeTitle.bold())
            Text("Your personal AI brain")
                .foregroundStyle(.secondary)
            Spacer()

            // Server warning
            if serverIsLocalhost {
                VStack(spacing: 8) {
                    Label("Server not configured", systemImage: "exclamationmark.triangle.fill")
                        .font(.subheadline.weight(.semibold))
                        .foregroundStyle(.orange)
                    Text("Set your Mac's IP address before logging in.")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                        .multilineTextAlignment(.center)
                    Button("Configure Server →") { showServerSetup = true }
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.blue)
                }
                .padding()
                .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                .padding(.horizontal, 32)
            }

            if let err = auth.errorMessage {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            Button {
                isAuthenticating = true
                Task {
                    _ = await auth.authenticate()
                    isAuthenticating = false
                }
            } label: {
                Group {
                    if isAuthenticating {
                        ProgressView().tint(.white)
                    } else {
                        Label("Authenticate with Face ID", systemImage: "faceid")
                    }
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(serverIsLocalhost ? Color.gray : Color.blue,
                            in: RoundedRectangle(cornerRadius: 14))
                .foregroundStyle(.white)
                .font(.headline)
            }
            .disabled(isAuthenticating || serverIsLocalhost)
            .padding(.horizontal, 32)
            .padding(.bottom, 48)
        }
        .sheet(isPresented: $showServerSetup) {
            ServerSetupSheet(isPresented: $showServerSetup)
        }
    }
}

struct ServerSetupSheet: View {
    @Binding var isPresented: Bool
    @StateObject private var config = AppConfig.shared
    @State private var url = AppConfig.shared.serverURL

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("http://192.168.x.x:8000", text: $url)
                        .keyboardType(.URL)
                        .autocorrectionDisabled()
                        .autocapitalization(.none)
                } header: {
                    Text("Mac IP address")
                } footer: {
                    Text("Run  ifconfig | grep 'inet '  on your Mac to find the IP. Both devices must be on the same Wi-Fi.")
                }

                Section("Quick presets") {
                    Button("Use 192.168.2.108:8000 (your Mac)") {
                        url = "http://192.168.2.108:8000"
                    }
                }
            }
            .navigationTitle("Server Setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        config.serverURL = url
                        isPresented = false
                    }
                    .fontWeight(.semibold)
                }
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }
                }
            }
        }
        .presentationDetents([.medium])
    }
}

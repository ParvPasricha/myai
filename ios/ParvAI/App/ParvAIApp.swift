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

            if let err = auth.errorMessage {
                Text(err)
                    .font(.caption)
                    .foregroundStyle(.red)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal)
            }

            Button {
                isAuthenticating = true
                Task {
                    _ = await auth.authenticate()
                    isAuthenticating = false
                }
            } label: {
                Label("Authenticate with Face ID",
                      systemImage: "faceid")
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                    .foregroundStyle(.white)
                    .font(.headline)
            }
            .disabled(isAuthenticating)
            .padding(.horizontal, 32)
            .padding(.bottom, 48)
        }
    }
}

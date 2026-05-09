import SwiftUI

struct ChatView: View {
    @StateObject private var audio = AudioService.shared
    @StateObject private var conn  = ConnectionManager.shared

    @State private var messages: [ChatMessage] = []
    @State private var isSending = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                MessageList(messages: messages)
                Divider()
                InputBar(audio: audio, isSending: isSending, onSend: sendTranscript)
            }
            .navigationTitle("Chat")
        }
        .task { _ = await audio.requestPermissions() }
        .onChange(of: conn.suggestionPush) { _, suggestion in
            if let s = suggestion {
                messages.append(.assistant("💡 " + s))
            }
        }
    }

    private func sendTranscript(_ text: String) {
        guard !text.isEmpty, !isSending else { return }
        messages.append(.user(text))
        isSending = true
        Task {
            do {
                struct ChatBody: Encodable { let prompt: String }
                struct ChatResp: Decodable { let text: String }
                let resp: ChatResp = try await conn.post("/ai/chat", body: ChatBody(prompt: text))
                messages.append(.assistant(resp.text))
            } catch {
                messages.append(.assistant("⚠ \(error.localizedDescription)"))
            }
            isSending = false
        }
    }
}

// MARK: — Subviews

struct MessageList: View {
    let messages: [ChatMessage]

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(alignment: .leading, spacing: 12) {
                    ForEach(messages) { msg in
                        MessageBubble(message: msg)
                            .id(msg.id)
                    }
                }
                .padding()
            }
            .onChange(of: messages.count) { _, _ in
                if let last = messages.last {
                    withAnimation { proxy.scrollTo(last.id, anchor: .bottom) }
                }
            }
        }
    }
}

struct MessageBubble: View {
    let message: ChatMessage
    private var isUser: Bool { message.role == .user }

    var body: some View {
        HStack {
            if isUser { Spacer(minLength: 60) }
            Text(message.text)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .background(isUser ? Color.blue : Color(.systemGray5),
                            in: RoundedRectangle(cornerRadius: 18))
                .foregroundStyle(isUser ? .white : .primary)
            if !isUser { Spacer(minLength: 60) }
        }
    }
}

struct InputBar: View {
    @ObservedObject var audio: AudioService
    let isSending: Bool
    let onSend: (String) -> Void

    var body: some View {
        HStack(spacing: 12) {
            // Live transcript preview
            if audio.isRecording {
                Text(audio.transcript.isEmpty ? "Listening…" : audio.transcript)
                    .font(.callout)
                    .foregroundStyle(.secondary)
                    .lineLimit(2)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else {
                Text("Hold to speak")
                    .font(.callout)
                    .foregroundStyle(.tertiary)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }

            if isSending {
                ProgressView().scaleEffect(0.8)
            }

            // Push-to-talk button
            Circle()
                .fill(audio.isRecording ? Color.red : Color.blue)
                .frame(width: 52, height: 52)
                .overlay {
                    Image(systemName: audio.isRecording ? "stop.fill" : "mic.fill")
                        .foregroundStyle(.white)
                        .font(.system(size: 20))
                }
                .scaleEffect(audio.isRecording ? 1.15 : 1.0)
                .animation(.spring(response: 0.3), value: audio.isRecording)
                .gesture(
                    DragGesture(minimumDistance: 0)
                        .onChanged { _ in
                            if !audio.isRecording {
                                audio.startRecording(onReady: onSend)
                            }
                        }
                        .onEnded { _ in
                            audio.stopRecording()
                        }
                )
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial)
    }
}

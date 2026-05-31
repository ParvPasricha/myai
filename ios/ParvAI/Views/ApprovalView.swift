import SwiftUI

/// Floating approval banner — appears over any screen when Jarvis
/// wants to send a message or email on your behalf.
struct ApprovalBanner: View {

    @ObservedObject var service = ApprovalService.shared
    @State private var editing: String? = nil
    @State private var editText: String = ""
    @AppStorage("serverToken") private var token: String = ""

    var body: some View {
        if let request = service.pending.first {
            VStack(spacing: 0) {
                Spacer()
                cardView(request)
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                    .animation(.spring(response: 0.4, dampingFraction: 0.8), value: service.pending.count)
            }
            .ignoresSafeArea(edges: .bottom)
        }
    }

    @ViewBuilder
    private func cardView(_ req: ApprovalService.ApprovalRequest) -> some View {
        VStack(alignment: .leading, spacing: 12) {

            // Header
            HStack {
                Image(systemName: req.type == "message" ? "message.fill" : "envelope.fill")
                    .foregroundStyle(req.type == "message" ? .blue : .orange)
                VStack(alignment: .leading, spacing: 2) {
                    Text("Jarvis wants to send a \(req.displayType)")
                        .font(.subheadline).fontWeight(.semibold)
                    Text("To: \(req.recipient)")
                        .font(.caption).foregroundStyle(.secondary)
                }
                Spacer()
                Text(timeAgo(req.created_at))
                    .font(.caption2).foregroundStyle(.tertiary)
            }

            Divider()

            // Content preview or edit field
            if editing == req.id {
                TextField("Edit message...", text: $editText, axis: .vertical)
                    .lineLimit(3...6)
                    .font(.callout)
                    .padding(8)
                    .background(Color(.systemGray6))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
            } else {
                Text(req.content)
                    .font(.callout)
                    .lineLimit(4)
                    .foregroundStyle(.primary)
            }

            // Actions
            HStack(spacing: 10) {
                // Deny
                Button {
                    Task { await service.deny(req, token: token) }
                } label: {
                    Label("Deny", systemImage: "xmark")
                        .font(.subheadline.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Color(.systemRed).opacity(0.15))
                        .foregroundStyle(.red)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                // Edit toggle
                Button {
                    if editing == req.id {
                        editing = nil
                    } else {
                        editText = req.content
                        editing  = req.id
                    }
                } label: {
                    Label(editing == req.id ? "Cancel" : "Edit", systemImage: "pencil")
                        .font(.subheadline.weight(.medium))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Color(.systemGray5))
                        .foregroundStyle(.primary)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                // Approve
                Button {
                    Task {
                        if editing == req.id && !editText.isEmpty {
                            await service.editAndApprove(req, edited: editText, token: token)
                        } else {
                            await service.approve(req, token: token)
                        }
                        editing = nil
                    }
                } label: {
                    Label("Send", systemImage: "paperplane.fill")
                        .font(.subheadline.weight(.semibold))
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(Color.blue)
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }

            // Queue indicator
            if service.pending.count > 1 {
                Text("\(service.pending.count - 1) more approval\(service.pending.count > 2 ? "s" : "") waiting")
                    .font(.caption).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity, alignment: .center)
            }
        }
        .padding(16)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 20))
        .padding(.horizontal, 12)
        .padding(.bottom, 24)
        .shadow(color: .black.opacity(0.2), radius: 20, y: -4)
    }

    private func timeAgo(_ ts: Double) -> String {
        let diff = Int(Date().timeIntervalSince1970 - ts)
        if diff < 60  { return "\(diff)s ago" }
        if diff < 3600 { return "\(diff/60)m ago" }
        return "\(diff/3600)h ago"
    }
}

#Preview {
    ZStack {
        Color(.systemBackground).ignoresSafeArea()
        Text("App content behind")
        ApprovalBanner()
    }
}

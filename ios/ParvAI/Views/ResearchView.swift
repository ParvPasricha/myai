import SwiftUI

// MARK: — Models

struct TopicResponse: Decodable {
    let id: Int
    let date: String
    let topic: String
    let description: String
    let domains: [String]
}

struct QuizResponse: Decodable {
    let quizId: Int
    let topicId: Int
    let date: String
    let questions: [QuizQuestion]
    let completed: Bool
    let score: Double?
    enum CodingKeys: String, CodingKey {
        case quizId = "quiz_id"
        case topicId = "topic_id"
        case date, questions, completed, score
    }
}

struct QuizQuestion: Decodable, Identifiable {
    let id: Int
    let question: String
    let options: [String]
}

struct QuizResult: Decodable {
    let score: Double
    let correct: Int
    let total: Int
    let streak: Int
    let grade: String
    let breakdown: [BreakdownItem]
}

struct BreakdownItem: Decodable, Identifiable {
    let id: Int
    let question: String
    let userAnswer: String
    let correctAnswer: String
    let correct: Bool
    let explanation: String
    enum CodingKeys: String, CodingKey {
        case id, question, correct, explanation
        case userAnswer = "user_answer"
        case correctAnswer = "correct_answer"
    }
}

// MARK: — ViewModel

@MainActor
final class ResearchViewModel: ObservableObject {
    @Published var topic: TopicResponse?
    @Published var quiz: QuizResponse?
    @Published var result: QuizResult?
    @Published var selectedAnswers: [Int: String] = [:]
    @Published var phase: Phase = .loading
    @Published var isLoading = false
    @Published var errorMessage: String?

    enum Phase { case loading, topic, quiz, result }

    private let conn = ConnectionManager.shared

    func load() async {
        isLoading = true
        defer { isLoading = false }
        do {
            topic = try await conn.get("/research/today")
            quiz = try await conn.get("/research/quiz")
            if quiz?.completed == true { phase = .result }
            else if topic != nil { phase = quiz != nil ? .quiz : .topic }
            else { phase = .topic }
        } catch {
            errorMessage = error.localizedDescription
            phase = .topic
        }
    }

    func submitQuiz() async {
        guard let quiz else { return }
        isLoading = true
        defer { isLoading = false }
        let answers = quiz.questions.map { q in selectedAnswers[q.id] ?? "" }
        do {
            struct Body: Encodable { let answers: [String] }
            result = try await conn.post("/research/quiz/\(quiz.quizId)", body: Body(answers: answers))
            withAnimation(.spring(response: 0.6)) { phase = .result }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func logEntry(title: String, summary: String) async {
        struct Body: Encodable { let title: String; let summary: String; let source: String }
        struct Resp: Decodable { let ok: Bool }
        _ = try? await conn.post("/research/log", body: Body(title: title, summary: summary, source: "manual")) as Resp
    }
}

// MARK: — Root View

struct ResearchView: View {
    @StateObject private var vm = ResearchViewModel()

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .loading:    ProgressView("Loading today's mission…")
                case .topic:      TopicCardView(vm: vm)
                case .quiz:       QuizView(vm: vm)
                case .result:     ResultView(vm: vm)
                }
            }
            .navigationTitle("Research")
            .toolbar {
                if vm.phase == .topic || vm.phase == .quiz {
                    ToolbarItem(placement: .topBarTrailing) {
                        Button("Quiz") { withAnimation { vm.phase = .quiz } }
                            .disabled(vm.quiz == nil)
                    }
                }
            }
            .alert("Error", isPresented: .constant(vm.errorMessage != nil)) {
                Button("OK") { vm.errorMessage = nil }
            } message: {
                Text(vm.errorMessage ?? "")
            }
        }
        .task { await vm.load() }
    }
}

// MARK: — Topic Card

struct TopicCardView: View {
    @ObservedObject var vm: ResearchViewModel

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 20) {
                if let topic = vm.topic {
                    VStack(alignment: .leading, spacing: 12) {
                        Label("Today's Mission", systemImage: "brain.head.profile")
                            .font(.caption.weight(.semibold))
                            .foregroundStyle(.secondary)

                        Text(topic.topic)
                            .font(.title2.bold())

                        Text(topic.description)
                            .foregroundStyle(.secondary)

                        HStack {
                            ForEach(topic.domains, id: \.self) { domain in
                                Text(domain)
                                    .font(.caption2)
                                    .padding(.horizontal, 8).padding(.vertical, 4)
                                    .background(.blue.opacity(0.12), in: Capsule())
                                    .foregroundStyle(.blue)
                            }
                        }
                    }
                    .padding()
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))

                    QuizCountdown()

                    Button {
                        withAnimation { vm.phase = .quiz }
                    } label: {
                        Label("Take Quiz Now", systemImage: "checkmark.circle.fill")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                            .foregroundStyle(.white)
                            .font(.headline)
                    }
                    .disabled(vm.quiz == nil)
                } else {
                    ContentUnavailableView("No topic today", systemImage: "brain",
                                          description: Text("Pull to refresh or check back later."))
                }
            }
            .padding()
        }
        .refreshable { await vm.load() }
    }
}

struct QuizCountdown: View {
    @State private var hoursLeft: Int = 0

    var body: some View {
        HStack {
            Image(systemName: "clock.fill").foregroundStyle(.orange)
            Text("Quiz unlocks at 10:00 PM")
                .font(.caption)
            Spacer()
        }
        .padding(.horizontal, 12).padding(.vertical, 8)
        .background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 10))
    }
}

// MARK: — Quiz View

struct QuizView: View {
    @ObservedObject var vm: ResearchViewModel
    @State private var currentIndex = 0

    var questions: [QuizQuestion] { vm.quiz?.questions ?? [] }
    var isLast: Bool { currentIndex == questions.count - 1 }
    var allAnswered: Bool {
        questions.allSatisfy { vm.selectedAnswers[$0.id] != nil }
    }

    var body: some View {
        VStack(spacing: 0) {
            // Progress bar
            ProgressView(value: Double(vm.selectedAnswers.count), total: Double(questions.count))
                .padding(.horizontal)
                .padding(.top, 8)

            Text("\(vm.selectedAnswers.count) / \(questions.count) answered")
                .font(.caption)
                .foregroundStyle(.secondary)
                .padding(.bottom, 8)

            if !questions.isEmpty {
                TabView(selection: $currentIndex) {
                    ForEach(Array(questions.enumerated()), id: \.offset) { idx, q in
                        QuestionCard(question: q, selected: vm.selectedAnswers[q.id]) { answer in
                            vm.selectedAnswers[q.id] = answer
                            if idx < questions.count - 1 {
                                withAnimation { currentIndex = idx + 1 }
                            }
                        }
                        .tag(idx)
                        .padding(.horizontal)
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))

                if allAnswered {
                    Button {
                        Task { await vm.submitQuiz() }
                    } label: {
                        Group {
                            if vm.isLoading {
                                ProgressView().tint(.white)
                            } else {
                                Label("Submit Quiz", systemImage: "paperplane.fill")
                            }
                        }
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(.green, in: RoundedRectangle(cornerRadius: 14))
                        .foregroundStyle(.white)
                        .font(.headline)
                    }
                    .padding()
                    .transition(.move(edge: .bottom).combined(with: .opacity))
                }
            }
        }
    }
}

struct QuestionCard: View {
    let question: QuizQuestion
    let selected: String?
    let onSelect: (String) -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(question.question)
                .font(.body.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)

            VStack(spacing: 10) {
                ForEach(question.options, id: \.self) { option in
                    let letter = String(option.prefix(1))
                    let isSelected = selected == letter
                    Button { onSelect(letter) } label: {
                        HStack {
                            Text(option)
                                .multilineTextAlignment(.leading)
                            Spacer()
                            if isSelected {
                                Image(systemName: "checkmark.circle.fill")
                                    .foregroundStyle(.blue)
                            }
                        }
                        .padding(.horizontal, 14).padding(.vertical, 12)
                        .background(
                            isSelected ? Color.blue.opacity(0.12) : Color(.systemGray6),
                            in: RoundedRectangle(cornerRadius: 12)
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 12)
                                .stroke(isSelected ? Color.blue : .clear, lineWidth: 1.5)
                        )
                    }
                    .buttonStyle(.plain)
                }
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 18))
    }
}

// MARK: — Result View

struct ResultView: View {
    @ObservedObject var vm: ResearchViewModel
    @State private var showBreakdown = false

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                if let result = vm.result ?? (vm.quiz?.score.map {
                    QuizResult(score: $0, correct: 0, total: 10, streak: 0, grade: grade($0), breakdown: [])
                }) {
                    ScoreBadge(result: result)
                    StreakRow(streak: result.streak)

                    if !result.breakdown.isEmpty {
                        Button(showBreakdown ? "Hide Breakdown" : "Show Breakdown") {
                            withAnimation { showBreakdown.toggle() }
                        }
                        .font(.subheadline)

                        if showBreakdown {
                            ForEach(result.breakdown) { item in
                                BreakdownRow(item: item)
                            }
                        }
                    }
                }

                Button("New Topic Tomorrow →") { }
                    .font(.footnote)
                    .foregroundStyle(.secondary)
            }
            .padding()
        }
    }

    private func grade(_ score: Double) -> String {
        if score >= 90 { return "S" }
        if score >= 80 { return "A" }
        if score >= 70 { return "B" }
        if score >= 60 { return "C" }
        return "F"
    }
}

struct ScoreBadge: View {
    let result: QuizResult

    private var color: Color {
        result.score >= 80 ? .green : result.score >= 60 ? .orange : .red
    }

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle().stroke(color.opacity(0.2), lineWidth: 16).frame(width: 140, height: 140)
                Circle()
                    .trim(from: 0, to: result.score / 100)
                    .stroke(color, style: StrokeStyle(lineWidth: 16, lineCap: .round))
                    .rotationEffect(.degrees(-90))
                    .frame(width: 140, height: 140)
                    .animation(.spring(response: 1.2), value: result.score)
                VStack(spacing: 2) {
                    Text(result.grade)
                        .font(.system(size: 42, weight: .black, design: .rounded))
                        .foregroundStyle(color)
                    Text("\(Int(result.score))%")
                        .font(.title3.bold())
                }
            }
            Text("\(result.correct) / \(result.total) correct")
                .foregroundStyle(.secondary)
        }
    }
}

struct StreakRow: View {
    let streak: Int
    var body: some View {
        HStack {
            Text("🔥").font(.title2)
            Text("\(streak) day streak")
                .font(.headline)
            Spacer()
            if streak >= 7 { Text("Week warrior!").font(.caption).foregroundStyle(.orange) }
        }
        .padding()
        .background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
    }
}

struct BreakdownRow: View {
    let item: BreakdownItem
    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            HStack(alignment: .top) {
                Image(systemName: item.correct ? "checkmark.circle.fill" : "xmark.circle.fill")
                    .foregroundStyle(item.correct ? .green : .red)
                Text(item.question).font(.callout)
            }
            if !item.explanation.isEmpty {
                Text(item.explanation)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .padding(.leading, 24)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

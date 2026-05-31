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
        case quizId = "quiz_id"; case topicId = "topic_id"
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
        case userAnswer = "user_answer"; case correctAnswer = "correct_answer"
    }
}

struct TopicSuggestion: Decodable, Identifiable {
    var id: String { topic }
    let topic: String
    let description: String
    let domain: String
    let type: String   // deepen | revisit | explore
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
    @Published var isRefreshing = false
    @Published var errorMessage: String?
    @Published var suggestions: [TopicSuggestion] = []
    @Published var loadingSuggestions = false

    enum Phase { case loading, topic, quiz, result }

    private let conn = ConnectionManager.shared

    // MARK: Load

    func load() async {
        isLoading = true
        errorMessage = nil
        defer { isLoading = false }
        do {
            topic = try await conn.get("/research/today")
            quiz  = try await conn.get("/research/quiz")
            if quiz?.completed == true {
                phase = .result
            } else if topic != nil {
                phase = quiz != nil ? .quiz : .topic
            } else {
                phase = .topic
            }
        } catch {
            errorMessage = error.localizedDescription
            phase = .topic
        }
    }

    func refresh() async {
        isRefreshing = true
        defer { isRefreshing = false }
        do {
            topic = try await conn.post("/research/topic/refresh", body: EmptyBody())
            quiz  = nil
            selectedAnswers = [:]
            result = nil
            quiz  = try await conn.get("/research/quiz")
            phase = quiz != nil ? .quiz : .topic
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func setCustomTopic(_ topicName: String) async {
        isLoading = true
        defer { isLoading = false }
        do {
            struct Body: Encodable { let topic: String }
            topic = try await conn.post("/research/topic/custom", body: Body(topic: topicName))
            quiz  = nil
            selectedAnswers = [:]
            result = nil
            quiz  = try await conn.get("/research/quiz")
            phase = quiz != nil ? .quiz : .topic
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func loadSuggestions() async {
        loadingSuggestions = true
        defer { loadingSuggestions = false }
        do {
            struct Resp: Decodable { let suggestions: [TopicSuggestion] }
            let r: Resp = try await conn.get("/research/suggestions")
            suggestions = r.suggestions
        } catch {
            suggestions = []
        }
    }

    // MARK: Quiz

    func submitQuiz() async {
        guard let quiz else { return }
        isLoading = true
        defer { isLoading = false }
        let answers = quiz.questions.map { selectedAnswers[$0.id] ?? "" }
        do {
            struct Body: Encodable { let answers: [String] }
            result = try await conn.post("/research/quiz/\(quiz.quizId)", body: Body(answers: answers))
            withAnimation(.spring(response: 0.6)) { phase = .result }
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func clearAnswer(for questionId: Int) {
        selectedAnswers.removeValue(forKey: questionId)
    }

    func clearAllAnswers() {
        selectedAnswers = [:]
    }
}

private struct EmptyBody: Encodable {}

// MARK: — Root View

struct ResearchView: View {
    @StateObject private var vm = ResearchViewModel()
    @State private var showSuggestions = false

    var body: some View {
        NavigationStack {
            Group {
                switch vm.phase {
                case .loading:
                    ProgressView("Loading today's mission…")
                case .topic:
                    TopicCardView(vm: vm, showSuggestions: $showSuggestions)
                case .quiz:
                    QuizView(vm: vm)
                case .result:
                    ResultView(vm: vm)
                }
            }
            .navigationTitle("Research")
            .toolbar { toolbarContent }
            .alert("Error", isPresented: .constant(vm.errorMessage != nil)) {
                Button("OK") { vm.errorMessage = nil }
            } message: {
                Text(vm.errorMessage ?? "")
            }
            .sheet(isPresented: $showSuggestions) {
                SuggestionsSheet(vm: vm, isPresented: $showSuggestions)
            }
        }
        .task { await vm.load() }
    }

    @ToolbarContentBuilder
    private var toolbarContent: some ToolbarContent {
        ToolbarItem(placement: .topBarLeading) {
            Button {
                showSuggestions = true
            } label: {
                Image(systemName: "sparkles")
            }
        }
        ToolbarItem(placement: .topBarTrailing) {
            Button {
                Task { await vm.refresh() }
            } label: {
                if vm.isRefreshing {
                    ProgressView().scaleEffect(0.7)
                } else {
                    Image(systemName: "arrow.clockwise")
                }
            }
            .disabled(vm.isRefreshing)
        }
    }
}

// MARK: — Topic Card

struct TopicCardView: View {
    @ObservedObject var vm: ResearchViewModel
    @Binding var showSuggestions: Bool

    @State private var customInput = ""
    @State private var showInput   = false
    @FocusState private var inputFocused: Bool

    var body: some View {
        ScrollView {
            VStack(alignment: .leading, spacing: 16) {

                // ── Custom topic input ────────────────────────────────────
                VStack(alignment: .leading, spacing: 8) {
                    Text("Research topic")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(.secondary)

                    HStack(spacing: 8) {
                        TextField("Type any topic to research…", text: $customInput)
                            .focused($inputFocused)
                            .textFieldStyle(.plain)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 10)
                            .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 10))
                            .onSubmit { submitCustom() }

                        Button(action: submitCustom) {
                            Image(systemName: "arrow.up.circle.fill")
                                .font(.system(size: 28))
                                .foregroundStyle(customInput.trimmingCharacters(in: .whitespaces).isEmpty ? Color.secondary : Color.blue)
                        }
                        .disabled(customInput.trimmingCharacters(in: .whitespaces).isEmpty || vm.isLoading)
                    }
                }

                // ── Divider with OR ───────────────────────────────────────
                HStack {
                    Rectangle().fill(Color.secondary.opacity(0.2)).frame(height: 1)
                    Text("or").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 6)
                    Rectangle().fill(Color.secondary.opacity(0.2)).frame(height: 1)
                }

                // ── Today's AI topic ──────────────────────────────────────
                if vm.isLoading {
                    HStack { Spacer(); ProgressView("Generating topic…"); Spacer() }
                        .padding(.vertical, 24)
                } else if let topic = vm.topic {
                    VStack(alignment: .leading, spacing: 10) {
                        HStack {
                            Label("Today's topic", systemImage: "brain.head.profile")
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.secondary)
                            Spacer()
                            // Renew button
                            Button {
                                Task { await vm.refresh() }
                            } label: {
                                HStack(spacing: 4) {
                                    if vm.isRefreshing {
                                        ProgressView().scaleEffect(0.6)
                                    } else {
                                        Image(systemName: "arrow.clockwise")
                                    }
                                    Text("Renew")
                                }
                                .font(.caption.weight(.semibold))
                                .foregroundStyle(.blue)
                            }
                            .disabled(vm.isRefreshing)
                        }

                        Text(topic.topic)
                            .font(.title3.bold())

                        Text(topic.description)
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                            .fixedSize(horizontal: false, vertical: true)

                        if !topic.domains.isEmpty {
                            HStack {
                                ForEach(topic.domains, id: \.self) { d in
                                    Text(d)
                                        .font(.caption2)
                                        .padding(.horizontal, 8).padding(.vertical, 3)
                                        .background(.blue.opacity(0.12), in: Capsule())
                                        .foregroundStyle(.blue)
                                }
                            }
                        }

                        // ── Start Quiz button ─────────────────────────────
                        if vm.quiz != nil {
                            Button {
                                withAnimation { vm.phase = .quiz }
                            } label: {
                                Label("Start Quiz", systemImage: "checkmark.circle.fill")
                                    .frame(maxWidth: .infinity)
                                    .padding()
                                    .background(.blue, in: RoundedRectangle(cornerRadius: 14))
                                    .foregroundStyle(.white)
                                    .font(.headline)
                            }
                            .padding(.top, 4)
                        } else {
                            Text("Quiz will be available once the topic is loaded.")
                                .font(.caption)
                                .foregroundStyle(.secondary)
                                .padding(.top, 4)
                        }
                    }
                    .padding()
                    .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 16))
                } else {
                    // No topic yet
                    VStack(spacing: 12) {
                        Image(systemName: "brain")
                            .font(.system(size: 40))
                            .foregroundStyle(.secondary)
                        Text("No topic yet")
                            .font(.headline)
                        Text("Type a topic above or tap Renew to let the AI pick one.")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                            .multilineTextAlignment(.center)
                        Button("Generate topic") {
                            Task { await vm.refresh() }
                        }
                        .buttonStyle(.borderedProminent)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 32)
                }

                // ── Suggestions row ───────────────────────────────────────
                Button {
                    showSuggestions = true
                } label: {
                    HStack {
                        Image(systemName: "sparkles").foregroundStyle(.purple)
                        Text("See personalised suggestions")
                            .font(.subheadline.weight(.medium))
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                    .background(Color.purple.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
                }
                .buttonStyle(.plain)
            }
            .padding()
        }
        .refreshable { await vm.refresh() }
    }

    private func submitCustom() {
        let t = customInput.trimmingCharacters(in: .whitespaces)
        guard !t.isEmpty else { return }
        inputFocused = false
        customInput = ""
        Task { await vm.setCustomTopic(t) }
    }
}

// MARK: — Quiz View (single-card, no TabView)

struct QuizView: View {
    @ObservedObject var vm: ResearchViewModel
    @State private var currentIndex = 0

    private var questions: [QuizQuestion] { vm.quiz?.questions ?? [] }
    private var current: QuizQuestion? { questions[safe: currentIndex] }
    private var answeredCount: Int { vm.selectedAnswers.count }
    private var allAnswered: Bool { answeredCount == questions.count }
    private var isFirst: Bool { currentIndex == 0 }
    private var isLast: Bool { currentIndex == questions.count - 1 }

    var body: some View {
        VStack(spacing: 0) {
            // Progress header
            VStack(spacing: 6) {
                HStack {
                    Text("Question \(currentIndex + 1) of \(questions.count)")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                    Spacer()
                    Text("\(answeredCount)/\(questions.count) answered")
                        .font(.caption.weight(.semibold))
                        .foregroundStyle(allAnswered ? .green : .secondary)
                }
                ProgressView(value: Double(answeredCount), total: Double(questions.count))
                    .tint(allAnswered ? .green : .blue)
            }
            .padding(.horizontal)
            .padding(.top, 12)
            .padding(.bottom, 8)

            Divider()

            // Question card — no TabView, explicit navigation
            if let q = current {
                ScrollView {
                    QuestionCard(
                        question: q,
                        selected: vm.selectedAnswers[q.id],
                        onSelect: { answer in
                            vm.selectedAnswers[q.id] = answer
                            // Auto-advance if not last
                            if !isLast {
                                withAnimation(.easeInOut(duration: 0.25)) {
                                    currentIndex += 1
                                }
                            }
                        },
                        onClear: { vm.clearAnswer(for: q.id) }
                    )
                    .padding()
                }
                .animation(.easeInOut(duration: 0.2), value: currentIndex)
            }

            Spacer(minLength: 0)
            Divider()

            // Navigation bar
            HStack(spacing: 16) {
                // Back
                Button {
                    withAnimation { currentIndex -= 1 }
                } label: {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 18, weight: .semibold))
                        .frame(width: 44, height: 44)
                        .background(Color.secondary.opacity(0.12), in: Circle())
                }
                .disabled(isFirst)
                .opacity(isFirst ? 0.3 : 1)

                // Dot indicators
                HStack(spacing: 6) {
                    ForEach(questions.indices, id: \.self) { i in
                        Circle()
                            .fill(dotColor(for: i))
                            .frame(width: i == currentIndex ? 10 : 7,
                                   height: i == currentIndex ? 10 : 7)
                            .onTapGesture { withAnimation { currentIndex = i } }
                            .animation(.spring(response: 0.3), value: currentIndex)
                    }
                }
                .frame(maxWidth: .infinity)

                // Forward / Submit
                if isLast && allAnswered {
                    Button {
                        Task { await vm.submitQuiz() }
                    } label: {
                        Group {
                            if vm.isLoading {
                                ProgressView().tint(.white).scaleEffect(0.8)
                            } else {
                                Label("Submit", systemImage: "paperplane.fill")
                                    .font(.subheadline.weight(.semibold))
                            }
                        }
                        .padding(.horizontal, 16).padding(.vertical, 10)
                        .background(.green, in: Capsule())
                        .foregroundStyle(.white)
                    }
                } else {
                    Button {
                        withAnimation { currentIndex += 1 }
                    } label: {
                        Image(systemName: "chevron.right")
                            .font(.system(size: 18, weight: .semibold))
                            .frame(width: 44, height: 44)
                            .background(Color.secondary.opacity(0.12), in: Circle())
                    }
                    .disabled(isLast)
                    .opacity(isLast ? 0.3 : 1)
                }
            }
            .padding(.horizontal, 20)
            .padding(.vertical, 12)
        }
    }

    private func dotColor(for index: Int) -> Color {
        let q = questions[safe: index]
        if index == currentIndex { return .blue }
        if let q, vm.selectedAnswers[q.id] != nil { return .green }
        return Color.secondary.opacity(0.25)
    }
}

// MARK: — Question Card

struct QuestionCard: View {
    let question: QuizQuestion
    let selected: String?
    let onSelect: (String) -> Void
    let onClear: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            // Question text
            Text(question.question)
                .font(.body.weight(.medium))
                .fixedSize(horizontal: false, vertical: true)
                .frame(maxWidth: .infinity, alignment: .leading)

            // Options
            VStack(spacing: 10) {
                ForEach(question.options, id: \.self) { option in
                    let letter = String(option.prefix(1))
                    let isSelected = selected == letter
                    let displayText = option.count > 2 ? String(option.dropFirst(2)) : option
                    Button {
                        if isSelected { onClear() } else { onSelect(letter) }
                    } label: {
                        OptionRow(letter: letter, text: displayText, isSelected: isSelected)
                    }
                    .buttonStyle(.plain)
                    .animation(.spring(response: 0.25), value: isSelected)
                }
            }

            // Clear selection button — only shown when an answer is selected
            if selected != nil {
                Button {
                    withAnimation { onClear() }
                } label: {
                    Label("Clear selection", systemImage: "xmark.circle")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
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

    private func grade(_ s: Double) -> String {
        s >= 90 ? "S" : s >= 80 ? "A" : s >= 70 ? "B" : s >= 60 ? "C" : "F"
    }

    private var displayResult: QuizResult? {
        if let r = vm.result { return r }
        guard let score = vm.quiz?.score else { return nil }
        return QuizResult(score: score, correct: 0, total: 10,
                          streak: 0, grade: grade(score), breakdown: [])
    }

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                if let result = displayResult {
                    ScoreBadge(result: result)
                    StreakRow(streak: result.streak)

                    // Retry button
                    Button {
                        vm.clearAllAnswers()
                        vm.result = nil
                        withAnimation { vm.phase = .quiz }
                    } label: {
                        Label("Retry Quiz", systemImage: "arrow.counterclockwise")
                            .frame(maxWidth: .infinity)
                            .padding()
                            .background(Color.secondary.opacity(0.12), in: RoundedRectangle(cornerRadius: 14))
                            .font(.subheadline.weight(.semibold))
                    }
                    .buttonStyle(.plain)

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
            }
            .padding()
        }
    }
}

// MARK: — Suggestions Sheet

struct SuggestionsSheet: View {
    @ObservedObject var vm: ResearchViewModel
    @Binding var isPresented: Bool
    @State private var customTopic = ""
    @State private var showCustom = false

    var body: some View {
        NavigationStack {
            List {
                // Custom topic section
                Section {
                    if showCustom {
                        VStack(alignment: .leading, spacing: 8) {
                            TextField("e.g. Fourier Transforms, Startup fundraising…", text: $customTopic)
                                .textFieldStyle(.plain)
                            Button("Set this topic") {
                                guard !customTopic.trimmingCharacters(in: .whitespaces).isEmpty else { return }
                                isPresented = false
                                Task { await vm.setCustomTopic(customTopic) }
                            }
                            .disabled(customTopic.trimmingCharacters(in: .whitespaces).isEmpty)
                            .font(.subheadline.weight(.semibold))
                            .foregroundStyle(.blue)
                        }
                    } else {
                        Button {
                            withAnimation { showCustom = true }
                        } label: {
                            Label("Research something specific…", systemImage: "pencil")
                        }
                    }
                } header: {
                    Text("Custom")
                }

                // AI suggestions
                Section {
                    if vm.loadingSuggestions {
                        HStack {
                            Spacer()
                            ProgressView("Generating suggestions…")
                            Spacer()
                        }
                    } else if vm.suggestions.isEmpty {
                        Text("No suggestions yet")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(vm.suggestions) { s in
                            Button {
                                isPresented = false
                                Task { await vm.setCustomTopic(s.topic) }
                            } label: {
                                VStack(alignment: .leading, spacing: 4) {
                                    HStack {
                                        Text(s.topic)
                                            .font(.subheadline.weight(.semibold))
                                            .foregroundStyle(.primary)
                                        Spacer()
                                        suggestionBadge(s.type)
                                    }
                                    Text(s.description)
                                        .font(.caption)
                                        .foregroundStyle(.secondary)
                                        .fixedSize(horizontal: false, vertical: true)
                                }
                                .padding(.vertical, 2)
                            }
                            .buttonStyle(.plain)
                        }
                    }
                } header: {
                    HStack {
                        Text("AI Suggestions")
                        Spacer()
                        Button("Refresh") {
                            Task { await vm.loadSuggestions() }
                        }
                        .font(.caption)
                        .disabled(vm.loadingSuggestions)
                    }
                }
            }
            .navigationTitle("Choose Topic")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { isPresented = false }
                }
            }
        }
        .task { await vm.loadSuggestions() }
    }

    @ViewBuilder
    private func suggestionBadge(_ type: String) -> some View {
        let (label, color): (String, Color) = switch type {
            case "revisit": ("Revisit", .orange)
            case "explore": ("Explore", .purple)
            default:        ("Deepen", .blue)
        }
        Text(label)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6).padding(.vertical, 2)
            .background(color.opacity(0.15), in: Capsule())
            .foregroundStyle(color)
    }
}

// MARK: — Shared subviews (Score, Streak, Breakdown)

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
            Text("\(streak) day streak").font(.headline)
            Spacer()
            if streak >= 7 {
                Text("Week warrior!").font(.caption).foregroundStyle(.orange)
            }
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
                    .font(.caption).foregroundStyle(.secondary).padding(.leading, 24)
            }
        }
        .padding()
        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
}

// MARK: — Option Row (extracted to help Swift type-checker)

struct OptionRow: View {
    let letter: String
    let text: String
    let isSelected: Bool

    var body: some View {
        HStack(spacing: 12) {
            Text(letter)
                .font(.caption.weight(.bold))
                .frame(width: 26, height: 26)
                .background(isSelected ? Color.blue : Color.secondary.opacity(0.2), in: Circle())
                .foregroundStyle(isSelected ? Color.white : Color.secondary)
            Text(text)
                .font(.subheadline)
                .multilineTextAlignment(.leading)
                .frame(maxWidth: .infinity, alignment: .leading)
                .foregroundStyle(Color.primary)
            if isSelected {
                Image(systemName: "checkmark.circle.fill")
                    .foregroundStyle(Color.blue)
            }
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(isSelected ? Color.blue.opacity(0.10) : Color.secondary.opacity(0.08),
                    in: RoundedRectangle(cornerRadius: 12))
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .stroke(isSelected ? Color.blue : Color.clear, lineWidth: 1.5)
        )
    }
}

// MARK: — Helpers

extension Array {
    subscript(safe index: Int) -> Element? {
        indices.contains(index) ? self[index] : nil
    }
}

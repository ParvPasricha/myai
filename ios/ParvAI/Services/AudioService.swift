import AVFoundation
import Speech
import Combine

/// Push-to-talk audio recording + on-device STT.
///
/// Stage 1 (current): AVAudioEngine + Apple SFSpeechRecognizer (no internet needed).
/// Stage 4 (future):  Replace recogniser with WhisperKit for better accuracy + no Apple dependency.
@MainActor
final class AudioService: NSObject, ObservableObject {

    static let shared = AudioService()

    @Published var isRecording = false
    @Published var transcript = ""
    @Published var error: String?

    private let engine = AVAudioEngine()
    private var recognitionRequest: SFSpeechAudioBufferRecognitionRequest?
    private var recognitionTask: SFSpeechRecognitionTask?
    private let recogniser = SFSpeechRecognizer(locale: Locale(identifier: "en-US"))

    private var onTranscriptReady: ((String) -> Void)?

    // MARK: — Permissions

    func requestPermissions() async -> Bool {
        let mic = await AVAudioApplication.requestRecordPermission()
        let speech = await withCheckedContinuation { cont in
            SFSpeechRecognizer.requestAuthorization { status in
                cont.resume(returning: status == .authorized)
            }
        }
        return mic && speech
    }

    // MARK: — Recording

    func startRecording(onReady: @escaping (String) -> Void) {
        guard !isRecording else { return }
        onTranscriptReady = onReady
        transcript = ""
        error = nil

        do {
            let session = AVAudioSession.sharedInstance()
            try session.setCategory(.record, mode: .measurement, options: .duckOthers)
            try session.setActive(true, options: .notifyOthersOnDeactivation)

            recognitionRequest = SFSpeechAudioBufferRecognitionRequest()
            guard let req = recognitionRequest else { return }
            req.shouldReportPartialResults = true
            req.requiresOnDeviceRecognition = true   // no audio leaves device

            let inputNode = engine.inputNode
            let fmt = inputNode.outputFormat(forBus: 0)
            inputNode.installTap(onBus: 0, bufferSize: 1024, format: fmt) { [weak self] buffer, _ in
                self?.recognitionRequest?.append(buffer)
            }

            engine.prepare()
            try engine.start()

            recognitionTask = recogniser?.recognitionTask(with: req) { [weak self] result, err in
                guard let self else { return }
                if let result {
                    Task { @MainActor in
                        self.transcript = result.bestTranscription.formattedString
                    }
                }
                if err != nil || result?.isFinal == true {
                    self.finishRecording()
                }
            }
            isRecording = true
        } catch {
            self.error = error.localizedDescription
        }
    }

    func stopRecording() {
        guard isRecording else { return }
        engine.stop()
        engine.inputNode.removeTap(onBus: 0)
        recognitionRequest?.endAudio()
    }

    private func finishRecording() {
        isRecording = false
        recognitionTask = nil
        recognitionRequest = nil
        try? AVAudioSession.sharedInstance().setActive(false)

        let final = transcript
        if !final.isEmpty {
            onTranscriptReady?(final)
        }
    }

    // MARK: — WhisperKit hook (Phase 6)
    //
    // To upgrade to WhisperKit:
    // 1. Import WhisperKit
    // 2. let whisper = try await WhisperKit()
    // 3. Replace recognitionTask block with:
    //      let results = try await whisper.transcribe(audioPath: recordedFileURL.path)
    //      transcript = results.first?.text ?? ""
    //
    // WhisperKit runs entirely on-device via Core ML / Apple Neural Engine.
    // No changes to the rest of AudioService are needed.
}

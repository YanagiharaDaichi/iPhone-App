import Foundation

#if canImport(FoundationModels)
    import FoundationModels
#endif

/// Apple's built-in on-device model (iOS 26+, Apple Intelligence capable devices).
/// Nothing to download, but it needs Apple Intelligence turned on in Settings.
enum AppleIntelligence {
    /// `nil` when the model can be used, otherwise a reason to show the user.
    static var unavailableReason: String? {
        #if canImport(FoundationModels)
            if #available(iOS 26.0, *) {
                switch SystemLanguageModel.default.availability {
                case .available:
                    return nil
                case .unavailable(let reason):
                    switch reason {
                    case .deviceNotEligible:
                        return "この iPhone は Apple Intelligence に対応していません。"
                    case .appleIntelligenceNotEnabled:
                        return "設定アプリで Apple Intelligence をオンにしてください。"
                    case .modelNotReady:
                        return "モデルを準備中です。しばらくしてからお試しください。"
                    @unknown default:
                        return "現在利用できません。"
                    }
                }
            }
        #endif
        return "iOS 26 以降が必要です。"
    }

    static var isAvailable: Bool { unavailableReason == nil }

    @MainActor
    static func makeEngine(settings: ChatSettings) -> (any ChatEngine)? {
        #if canImport(FoundationModels)
            if #available(iOS 26.0, *), isAvailable {
                return AppleIntelligenceEngine(settings: settings)
            }
        #endif
        return nil
    }
}

#if canImport(FoundationModels)
    @available(iOS 26.0, *)
    @MainActor
    final class AppleIntelligenceEngine: ChatEngine {
        private var session: LanguageModelSession
        /// Whether `session` has seen any turns. Its instructions are fixed at creation,
        /// so a fresh session is made when settings change before the first message.
        private var hasHistory = false
        private var instructions: String

        var supportsThinking: Bool { false }

        init(settings: ChatSettings) {
            instructions = settings.systemPrompt
            session = LanguageModelSession(instructions: settings.systemPrompt)
        }

        func respond(to prompt: String, settings: ChatSettings) -> AsyncThrowingStream<EngineEvent, Error> {
            if !hasHistory, instructions != settings.systemPrompt {
                instructions = settings.systemPrompt
                session = LanguageModelSession(instructions: settings.systemPrompt)
            }
            hasHistory = true

            let session = self.session
            let options = GenerationOptions(
                temperature: settings.temperature,
                maximumResponseTokens: settings.maxTokens)

            return AsyncThrowingStream { continuation in
                let task = Task {
                    do {
                        let start = Date.now
                        var latest = ""
                        // Each element is a snapshot of the whole response so far.
                        for try await snapshot in session.streamResponse(to: prompt, options: options) {
                            latest = snapshot.content
                            continuation.yield(.replace(latest))
                        }
                        let seconds = Date.now.timeIntervalSince(start)
                        continuation.yield(
                            .stats("\(latest.count) 文字・\(seconds.formatted(.number.precision(.fractionLength(1)))) 秒"))
                        continuation.finish()
                    } catch {
                        continuation.finish(throwing: error)
                    }
                }
                continuation.onTermination = { _ in task.cancel() }
            }
        }

        func reset(history: [ChatMessage], settings: ChatSettings) {
            instructions = settings.systemPrompt
            session = LanguageModelSession(
                instructions: Self.carryOverInstructions(settings.systemPrompt, history: history))
            hasHistory = !history.isEmpty
        }

        /// Folds earlier turns (e.g. from another model, or before a stopped reply) into
        /// the instructions, keeping the tail so it fits the model's small context window.
        private static func carryOverInstructions(_ base: String, history: [ChatMessage]) -> String {
            let lines = history.compactMap { message -> String? in
                let text = message.role == .user ? message.text : message.parsed.answer
                guard !text.isEmpty else { return nil }
                return (message.role == .user ? "ユーザー: " : "アシスタント: ") + text
            }
            guard !lines.isEmpty else { return base }

            var transcript = lines.joined(separator: "\n")
            if transcript.count > 2000 {
                transcript = "…" + transcript.suffix(2000)
            }
            return base + "\n\n以下はこれまでの会話です。この続きとして応答してください。\n" + transcript
        }
    }
#endif

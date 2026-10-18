import Foundation
import MLX
import MLXLLM
import MLXLMCommon

/// Runs a Hugging Face MLX model on the iPhone's GPU.
@MainActor
final class MLXEngine: ChatEngine {
    let model: LocalModel
    private let container: ModelContainer
    private var session: ChatSession

    var supportsThinking: Bool { model.supportsThinking }

    private init(model: LocalModel, container: ModelContainer, settings: ChatSettings) {
        self.model = model
        self.container = container
        self.session = ChatSession(container)
        apply(settings)
    }

    /// Downloads the weights if needed and loads them into memory.
    ///
    /// - Parameter progress: download progress (0...1); reaches 1 before weights are loaded.
    static func load(
        _ model: LocalModel,
        settings: ChatSettings,
        progress: @escaping @MainActor @Sendable (Double) -> Void
    ) async throws -> MLXEngine {
        // Keep MLX's buffer cache small; the weights themselves are not affected.
        Memory.cacheLimit = 20 * 1024 * 1024

        let container = try await LLMModelFactory.shared.loadContainer(
            from: ModelStorage.downloader,
            using: TransformersTokenizerLoader(),
            configuration: model.configuration
        ) { downloadProgress in
            let fraction = downloadProgress.fractionCompleted
            Task { @MainActor in progress(fraction) }
        }
        return MLXEngine(model: model, container: container, settings: settings)
    }

    func respond(to prompt: String, settings: ChatSettings) -> AsyncThrowingStream<EngineEvent, Error> {
        apply(settings)
        let details = session.streamDetails(to: prompt)

        return AsyncThrowingStream { continuation in
            let task = Task {
                do {
                    for try await item in details {
                        switch item {
                        case .chunk(let text):
                            continuation.yield(.append(text))
                        case .info(let info):
                            let speed = info.tokensPerSecond.formatted(.number.precision(.fractionLength(1)))
                            continuation.yield(.stats("\(info.generationTokenCount) トークン・\(speed) トークン/秒"))
                        default:
                            break
                        }
                    }
                    continuation.finish()
                } catch {
                    continuation.finish(throwing: error)
                }
            }
            continuation.onTermination = { _ in task.cancel() }
        }
    }

    func reset(history: [ChatMessage], settings: ChatSettings) {
        let messages: [Chat.Message] = history.compactMap { message in
            switch message.role {
            case .user:
                return .user(message.text)
            case .assistant:
                // Past reasoning is dropped, as the Qwen3 chat template does itself.
                let answer = message.parsed.answer
                return answer.isEmpty ? nil : .assistant(answer)
            }
        }
        session = messages.isEmpty ? ChatSession(container) : ChatSession(container, history: messages)
        apply(settings)
    }

    private func apply(_ settings: ChatSettings) {
        let instructions = settings.systemPrompt.trimmingCharacters(in: .whitespacesAndNewlines)
        session.instructions = instructions.isEmpty ? nil : instructions
        session.generateParameters = GenerateParameters(
            maxTokens: settings.maxTokens,
            temperature: Float(settings.temperature),
            topP: 0.9,
            topK: 40,
            repetitionPenalty: 1.05
        )
        // Read by the Qwen3 chat template; other templates ignore it.
        session.additionalContext = ["enable_thinking": model.supportsThinking && settings.enableThinking]
    }

    /// Returns MLX's cached GPU buffers to the system; call after dropping an engine.
    static func releaseMemory() {
        Memory.clearCache()
    }
}

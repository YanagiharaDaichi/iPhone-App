import Foundation

/// Incremental output from a model while it answers.
enum EngineEvent {
    /// Text to append to the response.
    case append(String)
    /// The whole response so far (engines that stream snapshots instead of deltas).
    case replace(String)
    /// Performance summary once the response is complete.
    case stats(String)
}

/// An on-device language model that holds one conversation.
@MainActor
protocol ChatEngine: AnyObject {
    var supportsThinking: Bool { get }

    /// Sends `prompt` as the next user turn and streams the reply.
    func respond(to prompt: String, settings: ChatSettings) -> AsyncThrowingStream<EngineEvent, Error>

    /// Replaces the engine's conversation with `history` (empty for a new chat).
    func reset(history: [ChatMessage], settings: ChatSettings)
}

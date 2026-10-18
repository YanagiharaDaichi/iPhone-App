import Foundation

/// One turn in the conversation shown on screen.
struct ChatMessage: Identifiable, Equatable {
    enum Role {
        case user
        case assistant
    }

    let id = UUID()
    var role: Role
    /// Raw model output for assistant turns, which may contain a `<think>…</think>` block.
    var text: String
    /// Generation speed etc., shown under finished assistant turns.
    var stats: String?
    var isStreaming = false

    static func user(_ text: String) -> ChatMessage {
        ChatMessage(role: .user, text: text)
    }

    static func assistant(_ text: String = "", isStreaming: Bool = false) -> ChatMessage {
        ChatMessage(role: .assistant, text: text, isStreaming: isStreaming)
    }

    var parsed: ParsedResponse { ParsedResponse(raw: text) }
}

/// Splits the reasoning part (`<think>…</think>`) of a response from the visible answer.
///
/// Handles three shapes:
/// - `<think>reasoning</think>answer` (Qwen3 with thinking enabled)
/// - `reasoning</think>answer` (templates that prefill `<think>` into the prompt)
/// - `<think>reasoning…` (still streaming the reasoning)
struct ParsedResponse: Equatable {
    var thinking: String?
    var answer: String
    var isThinking: Bool

    init(raw: String) {
        if let end = raw.range(of: "</think>") {
            var head = raw[..<end.lowerBound]
            if let start = head.range(of: "<think>") {
                head = head[start.upperBound...]
            }
            let reasoning = head.trimmingCharacters(in: .whitespacesAndNewlines)
            thinking = reasoning.isEmpty ? nil : reasoning
            answer = raw[end.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines)
            isThinking = false
        } else if let start = raw.range(of: "<think>") {
            let reasoning = raw[start.upperBound...].trimmingCharacters(in: .whitespacesAndNewlines)
            thinking = reasoning
            answer = raw[..<start.lowerBound].trimmingCharacters(in: .whitespacesAndNewlines)
            isThinking = true
        } else {
            thinking = nil
            answer = raw.trimmingCharacters(in: .whitespacesAndNewlines)
            isThinking = false
        }
    }
}

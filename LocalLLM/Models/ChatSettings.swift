import Foundation

/// User-tunable generation settings, persisted in UserDefaults.
struct ChatSettings: Codable, Equatable {
    static let defaultSystemPrompt =
        "あなたは親切で有能なアシスタントです。ユーザーと同じ言語で、簡潔かつ正確に答えてください。"

    var systemPrompt = ChatSettings.defaultSystemPrompt
    var temperature = 0.7
    var maxTokens = 1024
    /// Lets reasoning models (Qwen3 family) think before answering. Slower but smarter.
    var enableThinking = false

    private static let storageKey = "chatSettings"

    static func load() -> ChatSettings {
        guard let data = UserDefaults.standard.data(forKey: storageKey),
            let settings = try? JSONDecoder().decode(ChatSettings.self, from: data)
        else { return ChatSettings() }
        return settings
    }

    func save() {
        if let data = try? JSONEncoder().encode(self) {
            UserDefaults.standard.set(data, forKey: Self.storageKey)
        }
    }
}

import Foundation
import Observation
import UIKit

/// Which model answers: Apple's built-in one or a downloaded MLX model.
enum ModelChoice: Hashable, Identifiable {
    case appleIntelligence
    case mlx(LocalModel)

    static let appleID = "apple-intelligence"

    var id: String {
        switch self {
        case .appleIntelligence: Self.appleID
        case .mlx(let model): model.id
        }
    }

    var displayName: String {
        switch self {
        case .appleIntelligence: "Apple Intelligence"
        case .mlx(let model): model.name
        }
    }
}

@MainActor
@Observable
final class ChatStore {
    enum EngineState: Equatable {
        /// No model chosen yet.
        case idle
        /// `progress` is the download fraction, `nil` while loading weights into memory.
        case loading(ModelChoice, progress: Double?)
        case ready(ModelChoice)
        case failed(ModelChoice, message: String)
    }

    private(set) var messages: [ChatMessage] = []
    var input = ""
    private(set) var isGenerating = false
    private(set) var engineState: EngineState = .idle
    var errorMessage: String?

    private var storedSettings = ChatSettings.load()
    var settings: ChatSettings {
        get { storedSettings }
        set {
            storedSettings = newValue
            newValue.save()
        }
    }

    private(set) var downloadedIDs = ModelStorage.downloadedIDs
    private var storedCustomModelIDs = UserDefaults.standard.stringArray(forKey: "customModelIDs") ?? []
    private(set) var customModelIDs: [String] {
        get { storedCustomModelIDs }
        set {
            storedCustomModelIDs = newValue
            UserDefaults.standard.set(newValue, forKey: Self.customModelsKey)
        }
    }

    private var engine: (any ChatEngine)?
    private var generationTask: Task<Void, Never>?
    /// Identifies the reply being generated, so a stopped task cannot clobber a newer one.
    private var generatingReplyID: UUID?
    private var loadTask: Task<Void, Never>?

    private static let lastModelKey = "lastModelID"
    private static let customModelsKey = "customModelIDs"

    init() {
        restoreLastModel()
    }

    // MARK: - Model state

    var activeChoice: ModelChoice? {
        if case .ready(let choice) = engineState { return choice }
        return nil
    }

    var isReady: Bool { activeChoice != nil }

    var supportsThinking: Bool { engine?.supportsThinking ?? false }

    var customModels: [LocalModel] { customModelIDs.map(LocalModel.custom(id:)) }

    func isDownloaded(_ model: LocalModel) -> Bool { downloadedIDs.contains(model.id) }

    /// Reopens the previous model at launch, as long as that needs no download.
    private func restoreLastModel() {
        guard let id = UserDefaults.standard.string(forKey: Self.lastModelKey) else { return }
        if id == ModelChoice.appleID {
            if AppleIntelligence.isAvailable { activate(.appleIntelligence) }
        } else if let model = ModelCatalog.model(id: id, customIDs: customModelIDs),
            isDownloaded(model)
        {
            activate(.mlx(model))
        }
    }

    /// Switches to `choice`, downloading its weights first if needed.
    /// The current conversation carries over to the new model.
    func activate(_ choice: ModelChoice) {
        if activeChoice == choice { return }
        if case .loading(choice, _) = engineState { return }
        stopGenerating()
        loadTask?.cancel()
        engine = nil
        MLXEngine.releaseMemory()

        switch choice {
        case .appleIntelligence:
            guard let engine = AppleIntelligence.makeEngine(settings: settings) else {
                engineState = .failed(
                    choice, message: AppleIntelligence.unavailableReason ?? "利用できません。")
                return
            }
            engine.reset(history: messages, settings: settings)
            self.engine = engine
            engineState = .ready(choice)
            UserDefaults.standard.set(choice.id, forKey: Self.lastModelKey)

        case .mlx(let model):
            engineState = .loading(choice, progress: isDownloaded(model) ? nil : 0)
            // Downloads stop when the phone sleeps, so keep the screen on meanwhile.
            UIApplication.shared.isIdleTimerDisabled = true

            loadTask = Task {
                defer {
                    // Leave it on if another model's download has taken over.
                    if case .loading = engineState {} else {
                        UIApplication.shared.isIdleTimerDisabled = false
                    }
                }
                do {
                    let engine = try await MLXEngine.load(model, settings: settings) { [weak self] fraction in
                        self?.updateLoadProgress(for: choice, fraction: fraction)
                    }
                    try Task.checkCancellation()

                    engine.reset(history: messages, settings: settings)
                    self.engine = engine
                    engineState = .ready(choice)
                    ModelStorage.markDownloaded(model.id)
                    downloadedIDs = ModelStorage.downloadedIDs
                    UserDefaults.standard.set(choice.id, forKey: Self.lastModelKey)
                } catch is CancellationError {
                    if case .loading(choice, _) = engineState { engineState = .idle }
                } catch {
                    guard case .loading(choice, _) = engineState else { return }
                    engineState = .failed(choice, message: Self.describe(error))
                }
            }
        }
    }

    private func updateLoadProgress(for choice: ModelChoice, fraction: Double) {
        guard case .loading(choice, _) = engineState else { return }
        // Once the download completes, the weights are still being loaded into memory.
        engineState = .loading(choice, progress: fraction < 1 ? fraction : nil)
    }

    func cancelLoading() {
        loadTask?.cancel()
        loadTask = nil
        engineState = .idle
    }

    func retryLoading() {
        guard case .failed(let choice, _) = engineState else { return }
        engineState = .idle
        activate(choice)
    }

    func deleteModel(_ model: LocalModel) {
        if engineState.choice == .mlx(model) {
            stopGenerating()
            loadTask?.cancel()
            engine = nil
            engineState = .idle
            MLXEngine.releaseMemory()
            UserDefaults.standard.removeObject(forKey: Self.lastModelKey)
        }
        do {
            try ModelStorage.delete(model.id)
        } catch {
            errorMessage = "削除できませんでした: \(error.localizedDescription)"
        }
        downloadedIDs = ModelStorage.downloadedIDs
    }

    /// Adds a Hugging Face MLX model by id and returns it, or `nil` if the id is malformed.
    func addCustomModel(id rawID: String) -> LocalModel? {
        let id = rawID.trimmingCharacters(in: .whitespacesAndNewlines)
        let parts = id.split(separator: "/", omittingEmptySubsequences: false)
        guard parts.count == 2, parts.allSatisfy({ !$0.isEmpty && !$0.contains(" ") }) else {
            return nil
        }
        if let builtIn = ModelCatalog.builtIn.first(where: { $0.id == id }) {
            return builtIn
        }
        if !customModelIDs.contains(id) {
            customModelIDs.append(id)
        }
        return .custom(id: id)
    }

    func removeCustomModel(_ model: LocalModel) {
        if isDownloaded(model) {
            deleteModel(model)
        }
        customModelIDs.removeAll { $0 == model.id }
    }

    // MARK: - Conversation

    func send(_ text: String? = nil) {
        let prompt = (text ?? input).trimmingCharacters(in: .whitespacesAndNewlines)
        guard !prompt.isEmpty, !isGenerating, let engine else { return }
        if text == nil { input = "" }
        errorMessage = nil

        messages.append(.user(prompt))
        let reply = ChatMessage.assistant(isStreaming: true)
        let replyID = reply.id
        messages.append(reply)
        isGenerating = true
        generatingReplyID = replyID

        let stream = engine.respond(to: prompt, settings: settings)
        generationTask = Task {
            do {
                for try await event in stream {
                    guard let index = messages.firstIndex(where: { $0.id == replyID }) else { break }
                    switch event {
                    case .append(let chunk): messages[index].text += chunk
                    case .replace(let whole): messages[index].text = whole
                    case .stats(let stats): messages[index].stats = stats
                    }
                }
            } catch is CancellationError {
            } catch {
                if !Task.isCancelled {
                    errorMessage = Self.describe(error)
                }
            }
            guard generatingReplyID == replyID else { return }

            if let index = messages.firstIndex(where: { $0.id == replyID }) {
                messages[index].isStreaming = false
                if messages[index].text.isEmpty, Task.isCancelled || errorMessage != nil {
                    messages.remove(at: index)
                }
            }
            if Task.isCancelled || errorMessage != nil {
                // A stopped or failed reply is not in the engine's own history; resync it
                // with what is on screen so the next turn sees the same conversation.
                self.engine?.reset(history: messages, settings: settings)
            }
            isGenerating = false
            generationTask = nil
            generatingReplyID = nil
        }
    }

    func stopGenerating() {
        generationTask?.cancel()
    }

    func newChat() {
        stopGenerating()
        generationTask = nil
        generatingReplyID = nil
        isGenerating = false
        messages.removeAll()
        errorMessage = nil
        engine?.reset(history: [], settings: settings)
    }

    private static func describe(_ error: Error) -> String {
        if let urlError = error as? URLError, urlError.code == .notConnectedToInternet {
            return "インターネットに接続できません。モデルの初回ダウンロードには通信が必要です。"
        }
        return (error as? LocalizedError)?.errorDescription ?? error.localizedDescription
    }
}

extension ChatStore.EngineState {
    var choice: ModelChoice? {
        switch self {
        case .idle: nil
        case .loading(let choice, _), .ready(let choice), .failed(let choice, _): choice
        }
    }
}

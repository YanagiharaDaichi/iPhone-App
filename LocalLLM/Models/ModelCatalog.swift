import Foundation
import MLXLLM
import MLXLMCommon

/// A model that runs on the device through MLX after being downloaded from Hugging Face.
struct LocalModel: Identifiable, Hashable {
    /// Hugging Face repository id, e.g. `mlx-community/Qwen3-1.7B-4bit`.
    let id: String
    let name: String
    let summary: String
    /// Download size in bytes; `nil` when unknown (custom models).
    let approxBytes: Int64?
    /// Physical memory the model is comfortable with.
    let recommendedRAMGB: Int
    let supportsThinking: Bool
    let configuration: ModelConfiguration
    let isCustom: Bool

    init(
        name: String, summary: String, approxBytes: Int64?, recommendedRAMGB: Int,
        supportsThinking: Bool, configuration: ModelConfiguration, isCustom: Bool = false
    ) {
        self.id = configuration.name
        self.name = name
        self.summary = summary
        self.approxBytes = approxBytes
        self.recommendedRAMGB = recommendedRAMGB
        self.supportsThinking = supportsThinking
        self.configuration = configuration
        self.isCustom = isCustom
    }

    static func == (lhs: LocalModel, rhs: LocalModel) -> Bool { lhs.id == rhs.id }
    func hash(into hasher: inout Hasher) { hasher.combine(id) }

    /// A model the user added by its Hugging Face id.
    static func custom(id: String) -> LocalModel {
        let lowered = id.lowercased()
        return LocalModel(
            name: id.split(separator: "/").last.map(String.init) ?? id,
            summary: id,
            approxBytes: nil,
            recommendedRAMGB: 0,
            supportsThinking: lowered.contains("qwen3"),
            // Known ids pick up their tuned configuration (stop tokens etc.).
            configuration: LLMRegistry.shared.configuration(id: id),
            isCustom: true)
    }
}

/// Models that fit on an iPhone and handle Japanese well.
enum ModelCatalog {
    static let builtIn: [LocalModel] = [
        LocalModel(
            name: "Qwen3 1.7B",
            summary: "おすすめ。日本語の会話が自然で、速さと賢さのバランスが良いモデル。",
            approxBytes: 984_013_244,
            recommendedRAMGB: 6,
            supportsThinking: true,
            configuration: LLMRegistry.qwen3_1_7b_4bit),
        LocalModel(
            name: "Qwen3.5 2B",
            summary: "新しい世代の小型モデル。推論力が高め。",
            approxBytes: 1_749_079_691,
            recommendedRAMGB: 6,
            supportsThinking: true,
            configuration: LLMRegistry.qwen3_5_2b_4bit),
        LocalModel(
            name: "Qwen3 4B",
            summary: "高品質。iPhone 15 Pro 以降（メモリ 8GB 以上）向け。",
            approxBytes: 2_278_969_756,
            recommendedRAMGB: 8,
            supportsThinking: true,
            configuration: LLMRegistry.qwen3_4b_4bit),
        LocalModel(
            name: "Gemma 3 1B",
            summary: "Google 製の軽量モデル。応答が速い。",
            approxBytes: 771_860_249,
            recommendedRAMGB: 4,
            supportsThinking: false,
            configuration: LLMRegistry.gemma3_1B_qat_4bit),
        LocalModel(
            name: "Qwen3 0.6B",
            summary: "最軽量。古い機種や動作確認向け（精度は控えめ）。",
            approxBytes: 351_383_618,
            recommendedRAMGB: 4,
            supportsThinking: true,
            configuration: LLMRegistry.qwen3_0_6b_4bit),
    ]

    static let recommended = builtIn[0]

    static func model(id: String, customIDs: [String]) -> LocalModel? {
        if let model = builtIn.first(where: { $0.id == id }) {
            return model
        }
        return customIDs.contains(id) ? .custom(id: id) : nil
    }
}

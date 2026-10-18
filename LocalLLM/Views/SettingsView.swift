import SwiftUI

struct SettingsView: View {
    @Environment(ChatStore.self) private var store
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        @Bindable var store = store

        NavigationStack {
            Form {
                Section {
                    TextField("システムプロンプト", text: $store.settings.systemPrompt, axis: .vertical)
                        .lineLimit(3...8)
                } header: {
                    Text("システムプロンプト")
                } footer: {
                    Text("AI の役割や話し方を指定します。次の送信から反映されます（Apple Intelligence は新しいチャットから）。")
                }

                Section {
                    VStack(alignment: .leading) {
                        LabeledContent("創造性（温度）") {
                            Text(store.settings.temperature.formatted(.number.precision(.fractionLength(1))))
                                .monospacedDigit()
                        }
                        Slider(value: $store.settings.temperature, in: 0...1.5, step: 0.1)
                    }
                    Stepper(value: $store.settings.maxTokens, in: 256...4096, step: 256) {
                        LabeledContent("最大応答長", value: "\(store.settings.maxTokens) トークン")
                    }
                } header: {
                    Text("生成")
                } footer: {
                    Text("温度を下げると正確で安定した回答に、上げると多様な回答になります。")
                }

                Section {
                    Toggle("思考モード", isOn: $store.settings.enableThinking)
                        .disabled(!store.supportsThinking)
                } footer: {
                    Text(
                        store.supportsThinking
                            ? "回答の前にじっくり考えます。複雑な質問で賢くなりますが、応答までの時間が長くなります。"
                            : "現在のモデルは思考モードに対応していません（Qwen 系モデルで使えます）。"
                    )
                }

                Section {
                    Button("設定を初期値に戻す", role: .destructive) {
                        store.settings = ChatSettings()
                    }
                }

                Section("プライバシー") {
                    Text("すべての処理は iPhone の中で行われます。インターネットを使うのはモデルのダウンロード時だけで、会話の内容が外部に送信されることはありません。")
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                }
            }
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完了") { dismiss() }
                }
            }
        }
    }
}

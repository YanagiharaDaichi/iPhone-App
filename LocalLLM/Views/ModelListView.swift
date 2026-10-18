import SwiftUI

struct ModelListView: View {
    @Environment(ChatStore.self) private var store
    @Environment(\.dismiss) private var dismiss
    @State private var pendingDownload: LocalModel?
    @State private var customID = ""
    @State private var customIDInvalid = false
    @State private var storageUsed: Int64 = 0

    var body: some View {
        NavigationStack {
            List {
                Section {
                    LabeledContent("この iPhone のメモリ", value: "\(DeviceInfo.memoryGB) GB")
                    LabeledContent("モデルの保存容量", value: DeviceInfo.formattedBytes(storageUsed))
                } footer: {
                    Text("ダウンロードしたモデルは端末内に保存され、オフラインで使えます。")
                }

                Section("内蔵モデル") {
                    AppleIntelligenceRow { choose(.appleIntelligence) }
                }

                Section {
                    ForEach(ModelCatalog.builtIn) { model in
                        row(for: model)
                    }
                } header: {
                    Text("ダウンロードして使うモデル")
                } footer: {
                    Text("ダウンロード済みのモデルは左にスワイプすると削除できます。")
                }

                Section {
                    ForEach(store.customModels) { model in
                        row(for: model, removable: true)
                    }
                    HStack {
                        TextField("mlx-community/モデル名", text: $customID)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                            .onSubmit(addCustomModel)
                        Button("追加", action: addCustomModel)
                            .disabled(customID.isEmpty)
                    }
                } header: {
                    Text("その他のモデル")
                } footer: {
                    Text(
                        customIDInvalid
                            ? "「作者/モデル名」の形式で入力してください。"
                            : "Hugging Face の MLX 形式（mlx-community など）のテキストモデルを ID で追加できます。端末のメモリに収まるサイズ（目安: 4bit で 3B 以下）を選んでください。"
                    )
                    .foregroundStyle(customIDInvalid ? Color.red : Color.secondary)
                }
            }
            .navigationTitle("モデル")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .confirmationAction) {
                    Button("完了") { dismiss() }
                }
            }
            .onAppear(perform: refreshStorage)
            .onChange(of: store.downloadedIDs) { refreshStorage() }
            .confirmationDialog(
                downloadTitle,
                isPresented: Binding(
                    get: { pendingDownload != nil },
                    set: { if !$0 { pendingDownload = nil } }),
                titleVisibility: .visible,
                presenting: pendingDownload
            ) { model in
                Button("ダウンロード") { choose(.mlx(model)) }
                Button("キャンセル", role: .cancel) {}
            } message: { model in
                Text(downloadMessage(for: model))
            }
        }
    }

    @ViewBuilder
    private func row(for model: LocalModel, removable: Bool = false) -> some View {
        let downloaded = store.isDownloaded(model)
        Button {
            if downloaded {
                choose(.mlx(model))
            } else {
                pendingDownload = model
            }
        } label: {
            ModelRow(model: model, downloaded: downloaded)
        }
        .foregroundStyle(.primary)
        .swipeActions(edge: .trailing) {
            if removable {
                Button("リストから外す", systemImage: "minus.circle", role: .destructive) {
                    store.removeCustomModel(model)
                }
            } else if downloaded {
                Button("削除", systemImage: "trash", role: .destructive) {
                    store.deleteModel(model)
                }
            }
        }
    }

    private func choose(_ choice: ModelChoice) {
        store.activate(choice)
        dismiss()
    }

    private func addCustomModel() {
        if let model = store.addCustomModel(id: customID) {
            customID = ""
            customIDInvalid = false
            if !store.isDownloaded(model) {
                pendingDownload = model
            }
        } else {
            customIDInvalid = true
        }
    }

    private func refreshStorage() {
        storageUsed = ModelStorage.diskUsage()
    }

    private var downloadTitle: String {
        pendingDownload.map { "\($0.name) をダウンロードしますか？" } ?? ""
    }

    private func downloadMessage(for model: LocalModel) -> String {
        var lines: [String] = []
        if let bytes = model.approxBytes {
            lines.append("約 \(DeviceInfo.formattedBytes(bytes)) をダウンロードします。Wi-Fi での接続をおすすめします。")
        } else {
            lines.append("Hugging Face からモデルをダウンロードします。Wi-Fi での接続をおすすめします。")
        }
        if model.recommendedRAMGB > DeviceInfo.memoryGB {
            lines.append(
                "このモデルはメモリ \(model.recommendedRAMGB)GB 以上を推奨しています。この iPhone（\(DeviceInfo.memoryGB)GB）ではメモリ不足でアプリが終了する可能性があります。"
            )
        }
        return lines.joined(separator: "\n\n")
    }
}

private struct ModelRow: View {
    @Environment(ChatStore.self) private var store
    let model: LocalModel
    let downloaded: Bool

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            VStack(alignment: .leading, spacing: 4) {
                HStack(spacing: 6) {
                    Text(model.name).font(.headline)
                    if model.supportsThinking {
                        Tag(text: "思考", color: .purple)
                    }
                }
                if !model.isCustom || model.summary != model.name {
                    Text(model.summary)
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                HStack(spacing: 10) {
                    if let bytes = model.approxBytes {
                        Label(DeviceInfo.formattedBytes(bytes), systemImage: "arrow.down.circle")
                    }
                    if model.recommendedRAMGB > 0 {
                        Label("メモリ \(model.recommendedRAMGB)GB〜", systemImage: "memorychip")
                            .foregroundStyle(model.recommendedRAMGB > DeviceInfo.memoryGB ? Color.orange : Color.secondary)
                    }
                }
                .font(.caption)
                .foregroundStyle(.secondary)
            }
            Spacer()
            status
        }
        .padding(.vertical, 4)
    }

    @ViewBuilder
    private var status: some View {
        let choice = ModelChoice.mlx(model)
        switch store.engineState {
        case .ready(choice):
            Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
        case .loading(choice, let progress):
            if let progress {
                Text("\(Int(progress * 100))%").font(.caption.monospacedDigit())
            } else {
                ProgressView()
            }
        default:
            if downloaded {
                Text("保存済み").font(.caption).foregroundStyle(.secondary)
            } else {
                Image(systemName: "icloud.and.arrow.down").foregroundStyle(.tint)
            }
        }
    }
}

private struct AppleIntelligenceRow: View {
    @Environment(ChatStore.self) private var store
    let action: () -> Void

    var body: some View {
        let reason = AppleIntelligence.unavailableReason
        Button(action: action) {
            HStack(alignment: .top, spacing: 12) {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Apple Intelligence").font(.headline)
                    Text(reason ?? "iOS に内蔵された Apple のモデル。ダウンロード不要ですぐ使えます。")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                Spacer()
                if store.activeChoice == .appleIntelligence {
                    Image(systemName: "checkmark.circle.fill").foregroundStyle(.green)
                }
            }
            .padding(.vertical, 4)
        }
        .foregroundStyle(.primary)
        .disabled(reason != nil)
    }
}

private struct Tag: View {
    let text: String
    let color: Color

    var body: some View {
        Text(text)
            .font(.caption2.weight(.semibold))
            .padding(.horizontal, 6)
            .padding(.vertical, 2)
            .foregroundStyle(color)
            .background(color.opacity(0.15), in: .capsule)
    }
}

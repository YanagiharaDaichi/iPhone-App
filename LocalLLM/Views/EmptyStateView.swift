import SwiftUI

/// What the chat area shows before the first message: model status or prompt ideas.
struct EmptyStateView: View {
    @Environment(ChatStore.self) private var store
    let showModels: () -> Void

    private static let suggestions = [
        "日本の四季の魅力を3行で教えて",
        "取引先へのお礼メールを丁寧に書いて",
        "Swift で配列を逆順にする方法は？",
        "冷蔵庫にある卵と玉ねぎで作れる料理は？",
    ]

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                Image(systemName: "brain.head.profile")
                    .font(.system(size: 52))
                    .foregroundStyle(.tint)
                    .padding(.top, 48)

                content
            }
            .padding(.horizontal, 24)
            .frame(maxWidth: .infinity)
        }
    }

    @ViewBuilder
    private var content: some View {
        switch store.engineState {
        case .idle:
            Text("iPhone の中で動く AI")
                .font(.title2.bold())
            Text("モデルを一度ダウンロードすれば、あとは通信なし（機内モードでも）で会話できます。会話の内容が外部に送られることはありません。")
                .multilineTextAlignment(.center)
                .foregroundStyle(.secondary)
            Button("モデルを選ぶ", action: showModels)
                .buttonStyle(.borderedProminent)
                .controlSize(.large)

        case .loading(let choice, let progress):
            if let progress {
                Text("\(choice.displayName) をダウンロード中")
                    .font(.headline)
                ProgressView(value: progress)
                Text("\(Int(progress * 100))% ・ 完了するまでアプリを開いたままにしてください")
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                    .multilineTextAlignment(.center)
            } else {
                Text("\(choice.displayName) を読み込み中")
                    .font(.headline)
                ProgressView()
            }
            Button("キャンセル", role: .cancel) { store.cancelLoading() }

        case .ready(let choice):
            Text("\(choice.displayName) で会話できます")
                .font(.headline)
            VStack(spacing: 10) {
                ForEach(Self.suggestions, id: \.self) { suggestion in
                    Button {
                        store.send(suggestion)
                    } label: {
                        Text(suggestion)
                            .frame(maxWidth: .infinity, alignment: .leading)
                            .padding(12)
                            .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 12))
                    }
                    .buttonStyle(.plain)
                }
            }

        case .failed(let choice, let message):
            Text("\(choice.displayName) を使えませんでした")
                .font(.headline)
            Text(message)
                .font(.callout)
                .foregroundStyle(.secondary)
                .multilineTextAlignment(.center)
            HStack {
                Button("再試行") { store.retryLoading() }
                    .buttonStyle(.borderedProminent)
                Button("別のモデルを選ぶ", action: showModels)
                    .buttonStyle(.bordered)
            }
        }
    }
}

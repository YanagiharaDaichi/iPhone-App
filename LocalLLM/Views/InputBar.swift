import SwiftUI

struct InputBar: View {
    @Environment(ChatStore.self) private var store
    @FocusState private var focused: Bool

    var body: some View {
        @Bindable var store = store

        HStack(alignment: .bottom, spacing: 8) {
            TextField(placeholder, text: $store.input, axis: .vertical)
                .lineLimit(1...6)
                .focused($focused)
                .padding(.horizontal, 14)
                .padding(.vertical, 9)
                .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 20))
                .disabled(!store.isReady)

            if store.isGenerating {
                Button("停止", systemImage: "stop.circle.fill") {
                    store.stopGenerating()
                }
                .labelStyle(.iconOnly)
                .font(.system(size: 32))
                .foregroundStyle(.primary)
            } else {
                Button("送信", systemImage: "arrow.up.circle.fill") {
                    store.send()
                }
                .labelStyle(.iconOnly)
                .font(.system(size: 32))
                .disabled(!canSend)
            }
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.bar)
    }

    private var canSend: Bool {
        store.isReady && !store.input.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    }

    private var placeholder: String {
        store.isReady ? "メッセージ" : "モデルを準備してください"
    }
}

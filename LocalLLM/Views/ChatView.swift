import SwiftUI

struct ChatView: View {
    @Environment(ChatStore.self) private var store
    @State private var showingModels = false
    @State private var showingSettings = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 0) {
                if store.messages.isEmpty {
                    EmptyStateView(showModels: { showingModels = true })
                } else {
                    MessageList()
                }
                if !store.messages.isEmpty, case .loading = store.engineState {
                    LoadingBanner()
                }
                if let error = store.errorMessage {
                    ErrorBanner(message: error) { store.errorMessage = nil }
                }
                InputBar()
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("新しいチャット", systemImage: "square.and.pencil") {
                        store.newChat()
                    }
                    .disabled(store.messages.isEmpty)
                }
                ToolbarItem(placement: .principal) {
                    ModelTitleButton { showingModels = true }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button("設定", systemImage: "slider.horizontal.3") {
                        showingSettings = true
                    }
                }
            }
            .sheet(isPresented: $showingModels) {
                ModelListView()
            }
            .sheet(isPresented: $showingSettings) {
                SettingsView()
            }
        }
    }
}

/// The model name in the navigation bar; tapping it opens the model list.
private struct ModelTitleButton: View {
    @Environment(ChatStore.self) private var store
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                switch store.engineState {
                case .idle:
                    Text("モデルを選択")
                case .loading(let choice, _):
                    ProgressView().controlSize(.small)
                    Text(choice.displayName)
                case .ready(let choice):
                    Text(choice.displayName)
                case .failed(let choice, _):
                    Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
                    Text(choice.displayName)
                }
                Image(systemName: "chevron.down")
                    .font(.caption2.weight(.bold))
                    .foregroundStyle(.secondary)
            }
            .font(.headline)
            .foregroundStyle(.primary)
        }
        .accessibilityHint("使用するモデルを切り替えます")
    }
}

private struct MessageList: View {
    @Environment(ChatStore.self) private var store

    var body: some View {
        ScrollViewReader { proxy in
            ScrollView {
                LazyVStack(spacing: 16) {
                    ForEach(store.messages) { message in
                        MessageRow(message: message)
                            .id(message.id)
                    }
                    Color.clear.frame(height: 1).id(Self.bottomID)
                }
                .padding(.horizontal)
                .padding(.vertical, 12)
            }
            .scrollDismissesKeyboard(.interactively)
            .onChange(of: store.messages.count) {
                withAnimation { proxy.scrollTo(Self.bottomID, anchor: .bottom) }
            }
            .onChange(of: store.messages.last?.text) {
                proxy.scrollTo(Self.bottomID, anchor: .bottom)
            }
            .onAppear {
                proxy.scrollTo(Self.bottomID, anchor: .bottom)
            }
        }
    }

    private static let bottomID = "bottom"
}

private struct LoadingBanner: View {
    @Environment(ChatStore.self) private var store

    var body: some View {
        if case .loading(let choice, let progress) = store.engineState {
            Group {
                if let progress {
                    ProgressView(value: progress) {
                        Text("\(choice.displayName) をダウンロード中…")
                    }
                } else {
                    HStack {
                        ProgressView()
                        Text("\(choice.displayName) を読み込み中…")
                    }
                    .frame(maxWidth: .infinity, alignment: .leading)
                }
            }
            .font(.footnote)
            .padding(.horizontal)
            .padding(.vertical, 8)
            .background(.bar)
        }
    }
}

private struct ErrorBanner: View {
    let message: String
    let dismiss: () -> Void

    var body: some View {
        HStack(alignment: .top) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(.orange)
            Text(message)
                .font(.footnote)
                .frame(maxWidth: .infinity, alignment: .leading)
            Button("閉じる", systemImage: "xmark", action: dismiss)
                .labelStyle(.iconOnly)
                .foregroundStyle(.secondary)
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
        .background(.orange.opacity(0.12))
    }
}

#Preview {
    ChatView()
        .environment(ChatStore())
}

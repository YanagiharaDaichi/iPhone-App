import PhotosUI
import SwiftUI

struct ContentView: View {
    @State private var viewModel = SearchViewModel()
    @State private var pickerItem: PhotosPickerItem?
    @State private var isShowingCamera = false
    @State private var isShowingSettings = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    if let image = viewModel.selectedImage {
                        Image(uiImage: image)
                            .resizable()
                            .scaledToFit()
                            .frame(maxHeight: 280)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                    }

                    sourceButtons

                    phaseView
                }
                .padding()
            }
            .navigationTitle("類似画像検索")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("設定", systemImage: "gearshape") {
                        isShowingSettings = true
                    }
                }
            }
            .sheet(isPresented: $isShowingSettings, onDismiss: { viewModel.retryIfFailed() }) {
                SettingsView()
            }
            .fullScreenCover(isPresented: $isShowingCamera) {
                CameraPicker { image in
                    viewModel.search(with: image)
                }
                .ignoresSafeArea()
            }
            .onChange(of: pickerItem) { _, item in
                guard let item else { return }
                viewModel.search(with: item)
                // 同じ写真をもう一度選んでも検索されるように選択を戻しておく。
                pickerItem = nil
            }
        }
    }

    private var sourceButtons: some View {
        HStack(spacing: 12) {
            PhotosPicker(selection: $pickerItem, matching: .images) {
                Label("写真を選ぶ", systemImage: "photo.on.rectangle")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.borderedProminent)

            if UIImagePickerController.isSourceTypeAvailable(.camera) {
                Button {
                    isShowingCamera = true
                } label: {
                    Label("撮影する", systemImage: "camera")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
            }
        }
        .controlSize(.large)
        .disabled(viewModel.isSearching)
    }

    @ViewBuilder
    private var phaseView: some View {
        switch viewModel.phase {
        case .idle:
            ContentUnavailableView(
                "画像を選んでください",
                systemImage: "photo.on.rectangle.angled",
                description: Text("写真を選ぶか撮影すると、その画像に似た画像や、同じ画像が掲載されているページをネット上から探します。")
            )
        case .searching:
            ProgressView("検索中…")
                .padding(.vertical, 40)
        case .finished(let detection):
            ResultsView(detection: detection)
        case .failed(let message):
            ContentUnavailableView {
                Label("検索できませんでした", systemImage: "exclamationmark.triangle")
            } description: {
                Text(message)
            } actions: {
                Button("もう一度試す") {
                    viewModel.retryIfFailed()
                }
            }
        }
    }
}

#Preview {
    ContentView()
}

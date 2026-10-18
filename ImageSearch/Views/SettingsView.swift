import SwiftUI

struct SettingsView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var apiKey = APIKeyStore.load() ?? ""
    @State private var isShowingSaveError = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    SecureField("API キー", text: $apiKey)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                } header: {
                    Text("Google Cloud Vision API")
                } footer: {
                    Text("類似画像の検索には Google Cloud Vision API を使います。Google Cloud で Cloud Vision API を有効にして API キーを作成し、ここに貼り付けてください。キーはこの端末のキーチェーンに保存されます。空にして保存すると削除されます。")
                }

                Section("API キーの準備") {
                    Link(
                        "Cloud Vision API を有効にする",
                        destination: URL(string: "https://console.cloud.google.com/apis/library/vision.googleapis.com")!
                    )
                    Link(
                        "API キーを作成する",
                        destination: URL(string: "https://console.cloud.google.com/apis/credentials")!
                    )
                }
            }
            .navigationTitle("設定")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("キャンセル") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("保存") {
                        save()
                    }
                }
            }
            .alert("API キーを保存できませんでした", isPresented: $isShowingSaveError) {
                Button("OK", role: .cancel) {}
            }
        }
    }

    private func save() {
        let key = apiKey.trimmingCharacters(in: .whitespacesAndNewlines)
        if APIKeyStore.save(key) {
            dismiss()
        } else {
            isShowingSaveError = true
        }
    }
}

#Preview {
    SettingsView()
}

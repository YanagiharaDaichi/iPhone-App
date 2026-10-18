import Observation
import PhotosUI
import SwiftUI

@MainActor
@Observable
final class SearchViewModel {
    enum Phase {
        case idle
        case searching
        case finished(WebDetection)
        case failed(String)
    }

    private(set) var selectedImage: UIImage?
    private(set) var phase: Phase = .idle
    @ObservationIgnored private var task: Task<Void, Never>?

    var isSearching: Bool {
        if case .searching = phase { return true }
        return false
    }

    /// フォトライブラリで選んだ画像を読み込んで検索する。
    func search(with item: PhotosPickerItem) {
        run {
            guard let data = try await item.loadTransferable(type: Data.self),
                  let image = UIImage(data: data) else {
                throw ImageLoadError()
            }
            return image
        }
    }

    /// カメラで撮影した画像を検索する。
    func search(with image: UIImage) {
        run { image }
    }

    /// 直前の検索が失敗していれば、同じ画像でやり直す(API キーを登録した後など)。
    func retryIfFailed() {
        guard case .failed = phase, let image = selectedImage else { return }
        search(with: image)
    }

    private func run(loadImage: @escaping @MainActor () async throws -> UIImage) {
        task?.cancel()
        phase = .searching
        task = Task {
            do {
                let image = try await loadImage()
                selectedImage = image

                guard let apiKey = APIKeyStore.load() else {
                    throw VisionAPIError.missingAPIKey
                }
                guard let imageData = image.jpegDataForUpload() else {
                    throw VisionAPIError.imageEncodingFailed
                }
                let detection = try await VisionAPIClient(apiKey: apiKey).detectWeb(imageData: imageData)
                try Task.checkCancellation()
                phase = .finished(detection)
            } catch {
                // 新しい検索に置き換えられた場合は結果を反映しない。
                guard !Task.isCancelled else { return }
                phase = .failed(error.localizedDescription)
            }
        }
    }
}

private struct ImageLoadError: LocalizedError {
    var errorDescription: String? { "画像を読み込めませんでした。" }
}

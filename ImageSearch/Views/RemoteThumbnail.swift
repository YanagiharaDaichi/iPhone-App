import SwiftUI

/// ネット上の画像を正方形に切り抜いて表示する。
struct RemoteThumbnail: View {
    let urlString: String?

    private var url: URL? {
        urlString.flatMap(URL.secureImage)
    }

    var body: some View {
        Color(uiColor: .secondarySystemBackground)
            .aspectRatio(1, contentMode: .fit)
            .overlay {
                AsyncImage(url: url) { phase in
                    if let image = phase.image {
                        image
                            .resizable()
                            .scaledToFill()
                    } else if url != nil, phase.error == nil {
                        ProgressView()
                    } else {
                        Image(systemName: "photo")
                            .foregroundStyle(.secondary)
                    }
                }
            }
            .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

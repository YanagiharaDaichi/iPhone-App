import UIKit

extension UIImage {
    /// 長辺が `maxDimension` ピクセル以下になるよう縮小して JPEG に変換する。
    /// Vision API のリクエストサイズ上限に収め、通信量も抑えるため。
    func jpegDataForUpload(maxDimension: CGFloat = 1600, compressionQuality: CGFloat = 0.8) -> Data? {
        let pixelSize = CGSize(width: size.width * scale, height: size.height * scale)
        let longestSide = max(pixelSize.width, pixelSize.height)
        guard longestSide > 0 else { return nil }

        let ratio = min(1, maxDimension / longestSide)
        let targetSize = CGSize(
            width: (pixelSize.width * ratio).rounded(),
            height: (pixelSize.height * ratio).rounded()
        )

        let format = UIGraphicsImageRendererFormat()
        format.scale = 1
        format.opaque = true
        // draw(in:) は画像の向き(EXIF の回転情報)を反映して描画する。
        let resized = UIGraphicsImageRenderer(size: targetSize, format: format).image { _ in
            draw(in: CGRect(origin: .zero, size: targetSize))
        }
        return resized.jpegData(compressionQuality: compressionQuality)
    }
}

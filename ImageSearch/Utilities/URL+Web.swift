import Foundation

extension URL {
    /// ブラウザで開ける http / https の URL。それ以外のスキームは nil。
    static func webPage(_ string: String) -> URL? {
        guard let url = URL(string: string),
              let scheme = url.scheme?.lowercased(),
              scheme == "http" || scheme == "https" else {
            return nil
        }
        return url
    }

    /// サムネイル表示用の URL。App Transport Security により http の画像は読み込めないため、
    /// https に置き換えて読み込みを試みる。
    static func secureImage(_ string: String) -> URL? {
        guard let url = webPage(string),
              var components = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return nil
        }
        components.scheme = "https"
        return components.url
    }

    /// キーワードで Google 画像検索を行う URL。
    static func googleImageSearch(_ keyword: String) -> URL? {
        var components = URLComponents(string: "https://www.google.com/search")
        components?.queryItems = [
            URLQueryItem(name: "tbm", value: "isch"),
            URLQueryItem(name: "q", value: keyword),
        ]
        return components?.url
    }
}

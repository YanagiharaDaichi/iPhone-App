import Foundation

/// Google Cloud Vision API の Web 検出(WEB_DETECTION)で、画像に似た画像や
/// その画像が掲載されているページをネット上から探す。
/// https://cloud.google.com/vision/docs/detecting-web
struct VisionAPIClient {
    static let endpoint = URL(string: "https://vision.googleapis.com/v1/images:annotate")!

    var apiKey: String
    var maxResults = 30
    var session: URLSession = .shared

    func detectWeb(imageData: Data) async throws -> WebDetection {
        let request = try makeRequest(imageData: imageData)
        let (data, response) = try await session.data(for: request)
        return try Self.parse(data: data, response: response)
    }

    func makeRequest(imageData: Data) throws -> URLRequest {
        var request = URLRequest(url: Self.endpoint)
        request.httpMethod = "POST"
        request.timeoutInterval = 60
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")
        request.setValue(apiKey, forHTTPHeaderField: "X-Goog-Api-Key")
        // API キーを「iOS アプリ」に制限している場合に必要。
        if let bundleIdentifier = Bundle.main.bundleIdentifier {
            request.setValue(bundleIdentifier, forHTTPHeaderField: "X-Ios-Bundle-Identifier")
        }

        let body = AnnotateRequest(requests: [
            .init(
                image: .init(content: imageData.base64EncodedString()),
                features: [.init(type: "WEB_DETECTION", maxResults: maxResults)],
                imageContext: .init(webDetectionParams: .init(includeGeoResults: true))
            ),
        ])
        request.httpBody = try JSONEncoder().encode(body)
        return request
    }

    static func parse(data: Data, response: URLResponse) throws -> WebDetection {
        let statusCode = (response as? HTTPURLResponse)?.statusCode ?? 200
        let decoded = try? JSONDecoder().decode(AnnotateResponse.self, from: data)

        if let error = decoded?.error ?? decoded?.responses?.first?.error {
            throw VisionAPIError.server(code: error.code ?? statusCode, message: error.message ?? "")
        }
        guard (200..<300).contains(statusCode) else {
            throw VisionAPIError.server(
                code: statusCode,
                message: HTTPURLResponse.localizedString(forStatusCode: statusCode)
            )
        }
        guard let first = decoded?.responses?.first else {
            throw VisionAPIError.invalidResponse
        }
        // 何も見つからなかった場合は webDetection 自体が省略される。
        return first.webDetection ?? WebDetection()
    }
}

enum VisionAPIError: LocalizedError, Equatable {
    case missingAPIKey
    case imageEncodingFailed
    case server(code: Int, message: String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .missingAPIKey:
            "API キーが設定されていません。右上の設定から Google Cloud Vision API の API キーを登録してください。"
        case .imageEncodingFailed:
            "画像を送信用のデータに変換できませんでした。"
        case .server(let code, let message):
            "検索に失敗しました(\(code)): \(message)"
        case .invalidResponse:
            "サーバーから想定外の応答が返されました。"
        }
    }
}

// MARK: - リクエスト / レスポンスの JSON

private struct AnnotateRequest: Encodable {
    struct Item: Encodable {
        struct Image: Encodable {
            var content: String
        }

        struct Feature: Encodable {
            var type: String
            var maxResults: Int
        }

        struct ImageContext: Encodable {
            struct WebDetectionParams: Encodable {
                var includeGeoResults: Bool
            }

            var webDetectionParams: WebDetectionParams
        }

        var image: Image
        var features: [Feature]
        var imageContext: ImageContext
    }

    var requests: [Item]
}

private struct AnnotateResponse: Decodable {
    struct Item: Decodable {
        var webDetection: WebDetection?
        var error: Status?
    }

    struct Status: Decodable {
        var code: Int?
        var message: String?
    }

    var responses: [Item]?
    var error: Status?
}

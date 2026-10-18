import Foundation
import Testing
@testable import ImageSearch

struct VisionAPIClientTests {
    private let okResponse = HTTPURLResponse(
        url: VisionAPIClient.endpoint, statusCode: 200, httpVersion: nil, headerFields: nil
    )!

    @Test func makesWebDetectionRequest() throws {
        let client = VisionAPIClient(apiKey: "test-key", maxResults: 10)
        let request = try client.makeRequest(imageData: Data([0x01, 0x02, 0x03]))

        #expect(request.url == VisionAPIClient.endpoint)
        #expect(request.httpMethod == "POST")
        #expect(request.value(forHTTPHeaderField: "X-Goog-Api-Key") == "test-key")
        #expect(request.value(forHTTPHeaderField: "Content-Type") == "application/json")

        let body = try #require(request.httpBody)
        let json = try #require(JSONSerialization.jsonObject(with: body) as? [String: Any])
        let item = try #require((json["requests"] as? [[String: Any]])?.first)
        let image = try #require(item["image"] as? [String: Any])
        let feature = try #require((item["features"] as? [[String: Any]])?.first)

        #expect(image["content"] as? String == "AQID")
        #expect(feature["type"] as? String == "WEB_DETECTION")
        #expect(feature["maxResults"] as? Int == 10)
    }

    @Test func parsesWebDetection() throws {
        let json = """
        {
          "responses": [{
            "webDetection": {
              "webEntities": [
                {"entityId": "/m/02j81", "score": 1.2, "description": "Eiffel Tower"},
                {"entityId": "/m/05qtj", "score": 0.8}
              ],
              "fullMatchingImages": [{"url": "https://example.com/full.jpg"}],
              "partialMatchingImages": [
                {"url": "https://example.com/partial.jpg"},
                {"url": "https://example.com/full.jpg"}
              ],
              "pagesWithMatchingImages": [{
                "url": "https://example.com/page",
                "pageTitle": "<b>Eiffel Tower</b> &amp; Paris",
                "partialMatchingImages": [{"url": "https://example.com/partial.jpg"}]
              }],
              "visuallySimilarImages": [
                {"url": "https://example.com/similar1.jpg"},
                {"url": "http://example.com/similar2.jpg"}
              ],
              "bestGuessLabels": [{"label": "eiffel tower", "languageCode": "en"}]
            }
          }]
        }
        """

        let detection = try VisionAPIClient.parse(data: Data(json.utf8), response: okResponse)

        #expect(detection.keywords == ["eiffel tower"])
        #expect(detection.visuallySimilarImages.map(\.url) == [
            "https://example.com/similar1.jpg",
            "http://example.com/similar2.jpg",
        ])
        #expect(detection.matchingImages.map(\.url) == [
            "https://example.com/full.jpg",
            "https://example.com/partial.jpg",
        ])

        let page = try #require(detection.pagesWithMatchingImages.first)
        #expect(page.displayTitle == "Eiffel Tower & Paris")
        #expect(page.host == "example.com")
        #expect(page.previewImageURL == "https://example.com/partial.jpg")
        #expect(!detection.isEmpty)
    }

    @Test func treatsMissingWebDetectionAsEmpty() throws {
        let json = #"{"responses": [{}]}"#

        let detection = try VisionAPIClient.parse(data: Data(json.utf8), response: okResponse)

        #expect(detection.isEmpty)
    }

    @Test func throwsTopLevelError() {
        let json = """
        {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.", "status": "INVALID_ARGUMENT"}}
        """
        let response = HTTPURLResponse(
            url: VisionAPIClient.endpoint, statusCode: 400, httpVersion: nil, headerFields: nil
        )!

        #expect(throws: VisionAPIError.server(code: 400, message: "API key not valid. Please pass a valid API key.")) {
            try VisionAPIClient.parse(data: Data(json.utf8), response: response)
        }
    }

    @Test func throwsPerImageError() {
        let json = #"{"responses": [{"error": {"code": 3, "message": "Bad image data."}}]}"#

        #expect(throws: VisionAPIError.server(code: 3, message: "Bad image data.")) {
            try VisionAPIClient.parse(data: Data(json.utf8), response: okResponse)
        }
    }

    @Test func throwsOnNonJSONErrorResponse() {
        let response = HTTPURLResponse(
            url: VisionAPIClient.endpoint, statusCode: 503, httpVersion: nil, headerFields: nil
        )!

        #expect(throws: VisionAPIError.self) {
            try VisionAPIClient.parse(data: Data("Service Unavailable".utf8), response: response)
        }
    }
}

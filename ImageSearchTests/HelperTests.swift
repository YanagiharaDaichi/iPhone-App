import Foundation
import Testing
@testable import ImageSearch

struct HelperTests {
    @Test func stripsHTMLFromPageTitles() {
        #expect("<b>Mount</b> Fuji".strippingHTML == "Mount Fuji")
        #expect("Tom &amp; Jerry &quot;Show&quot;".strippingHTML == "Tom & Jerry \"Show\"")
        #expect("&amp;lt;b&amp;gt;".strippingHTML == "&lt;b&gt;")
    }

    @Test func upgradesImageURLsToHTTPS() {
        #expect(URL.secureImage("http://example.com/a.jpg")?.absoluteString == "https://example.com/a.jpg")
        #expect(URL.secureImage("https://example.com/a.jpg")?.absoluteString == "https://example.com/a.jpg")
        #expect(URL.secureImage("data:image/png;base64,AAAA") == nil)
    }

    @Test func acceptsOnlyWebPageURLs() {
        #expect(URL.webPage("http://example.com") != nil)
        #expect(URL.webPage("ftp://example.com") == nil)
        #expect(URL.webPage("javascript:alert(1)") == nil)
    }

    @Test func buildsGoogleImageSearchURL() throws {
        let url = try #require(URL.googleImageSearch("富士山"))
        let components = try #require(URLComponents(url: url, resolvingAgainstBaseURL: false))

        #expect(components.host == "www.google.com")
        #expect(components.queryItems?.first { $0.name == "q" }?.value == "富士山")
    }

    @Test func deduplicatesKeywords() {
        let detection = WebDetection(
            webEntities: [
                WebEntity(description: "Mount Fuji"),
                WebEntity(description: " "),
                WebEntity(description: "Volcano"),
            ],
            bestGuessLabels: [WebLabel(label: "mount fuji")]
        )

        #expect(detection.keywords == ["mount fuji", "Volcano"])
    }
}

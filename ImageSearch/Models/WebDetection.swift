import Foundation

/// Cloud Vision API の WEB_DETECTION の結果。
/// https://cloud.google.com/vision/docs/reference/rest/v1/AnnotateImageResponse#WebDetection
struct WebDetection: Decodable, Equatable {
    var webEntities: [WebEntity]
    var fullMatchingImages: [WebImage]
    var partialMatchingImages: [WebImage]
    var pagesWithMatchingImages: [WebPage]
    var visuallySimilarImages: [WebImage]
    var bestGuessLabels: [WebLabel]

    init(
        webEntities: [WebEntity] = [],
        fullMatchingImages: [WebImage] = [],
        partialMatchingImages: [WebImage] = [],
        pagesWithMatchingImages: [WebPage] = [],
        visuallySimilarImages: [WebImage] = [],
        bestGuessLabels: [WebLabel] = []
    ) {
        self.webEntities = webEntities
        self.fullMatchingImages = fullMatchingImages
        self.partialMatchingImages = partialMatchingImages
        self.pagesWithMatchingImages = pagesWithMatchingImages
        self.visuallySimilarImages = visuallySimilarImages
        self.bestGuessLabels = bestGuessLabels
    }

    // 該当がない項目はキーごと省略されて返ってくるため、空配列として扱う。
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        webEntities = try container.decodeIfPresent([WebEntity].self, forKey: .webEntities) ?? []
        fullMatchingImages = try container.decodeIfPresent([WebImage].self, forKey: .fullMatchingImages) ?? []
        partialMatchingImages = try container.decodeIfPresent([WebImage].self, forKey: .partialMatchingImages) ?? []
        pagesWithMatchingImages = try container.decodeIfPresent([WebPage].self, forKey: .pagesWithMatchingImages) ?? []
        visuallySimilarImages = try container.decodeIfPresent([WebImage].self, forKey: .visuallySimilarImages) ?? []
        bestGuessLabels = try container.decodeIfPresent([WebLabel].self, forKey: .bestGuessLabels) ?? []
    }

    private enum CodingKeys: String, CodingKey {
        case webEntities
        case fullMatchingImages
        case partialMatchingImages
        case pagesWithMatchingImages
        case visuallySimilarImages
        case bestGuessLabels
    }

    /// 完全一致・部分一致の画像をまとめたもの(重複は除く)。
    var matchingImages: [WebImage] {
        var seen = Set<String>()
        return (fullMatchingImages + partialMatchingImages).filter { seen.insert($0.url).inserted }
    }

    /// 推定ラベルと関連エンティティを重複なしで並べたキーワード。
    var keywords: [String] {
        let candidates = bestGuessLabels.map(\.label) + webEntities.compactMap(\.description)
        var seen = Set<String>()
        return candidates
            .map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }
            .filter { !$0.isEmpty && seen.insert($0.lowercased()).inserted }
    }

    var isEmpty: Bool {
        keywords.isEmpty
            && matchingImages.isEmpty
            && pagesWithMatchingImages.isEmpty
            && visuallySimilarImages.isEmpty
    }
}

struct WebEntity: Decodable, Equatable {
    var entityId: String?
    var score: Double?
    var description: String?
}

struct WebImage: Decodable, Equatable {
    var url: String
    var score: Double?
}

struct WebPage: Decodable, Equatable {
    var url: String
    var score: Double?
    var pageTitle: String?
    var fullMatchingImages: [WebImage]?
    var partialMatchingImages: [WebImage]?

    /// pageTitle には `<b>` タグなどが含まれるので取り除いて表示する。
    var displayTitle: String {
        if let title = pageTitle?.strippingHTML, !title.isEmpty {
            return title
        }
        return host
    }

    var host: String {
        URL(string: url)?.host ?? url
    }

    /// 一覧のサムネイルに使う、そのページに掲載されている一致画像。
    var previewImageURL: String? {
        fullMatchingImages?.first?.url ?? partialMatchingImages?.first?.url
    }
}

struct WebLabel: Decodable, Equatable {
    var label: String
    var languageCode: String?
}

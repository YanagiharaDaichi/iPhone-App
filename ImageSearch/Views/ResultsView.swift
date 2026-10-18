import SwiftUI

struct ResultsView: View {
    let detection: WebDetection

    @State private var browsingPage: BrowsingPage?

    private let columns = [GridItem(.adaptive(minimum: 100), spacing: 8)]

    var body: some View {
        if detection.isEmpty {
            ContentUnavailableView(
                "見つかりませんでした",
                systemImage: "magnifyingglass",
                description: Text("似ている画像は見つかりませんでした。別の画像でお試しください。")
            )
        } else {
            VStack(alignment: .leading, spacing: 28) {
                if !detection.keywords.isEmpty {
                    keywordSection
                }
                if !detection.visuallySimilarImages.isEmpty {
                    imageSection("類似画像", images: detection.visuallySimilarImages)
                }
                if !detection.matchingImages.isEmpty {
                    imageSection("同じ画像", images: detection.matchingImages)
                }
                if !detection.pagesWithMatchingImages.isEmpty {
                    pageSection
                }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .sheet(item: $browsingPage) { page in
                SafariView(url: page.url)
                    .ignoresSafeArea()
            }
        }
    }

    private var keywordSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("キーワード", count: nil)
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 8) {
                    ForEach(detection.keywords, id: \.self) { keyword in
                        Button(keyword) {
                            browsingPage = URL.googleImageSearch(keyword).map(BrowsingPage.init)
                        }
                        .buttonStyle(.bordered)
                        .buttonBorderShape(.capsule)
                    }
                }
            }
        }
    }

    private func imageSection(_ title: String, images: [WebImage]) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader(title, count: images.count)
            LazyVGrid(columns: columns, spacing: 8) {
                ForEach(Array(images.enumerated()), id: \.offset) { _, image in
                    Button {
                        open(image.url)
                    } label: {
                        RemoteThumbnail(urlString: image.url)
                    }
                    .buttonStyle(.plain)
                }
            }
        }
    }

    private var pageSection: some View {
        VStack(alignment: .leading, spacing: 8) {
            sectionHeader("この画像が掲載されているページ", count: detection.pagesWithMatchingImages.count)
            ForEach(Array(detection.pagesWithMatchingImages.enumerated()), id: \.offset) { _, page in
                Button {
                    open(page.url)
                } label: {
                    PageRow(page: page)
                }
                .buttonStyle(.plain)
                Divider()
            }
        }
    }

    private func sectionHeader(_ title: String, count: Int?) -> some View {
        HStack(alignment: .firstTextBaseline) {
            Text(title)
                .font(.headline)
            if let count {
                Text("\(count)件")
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
            }
        }
    }

    private func open(_ urlString: String) {
        browsingPage = URL.webPage(urlString).map(BrowsingPage.init)
    }
}

private struct BrowsingPage: Identifiable {
    let url: URL
    var id: URL { url }
}

private struct PageRow: View {
    let page: WebPage

    var body: some View {
        HStack(spacing: 12) {
            RemoteThumbnail(urlString: page.previewImageURL)
                .frame(width: 56, height: 56)
            VStack(alignment: .leading, spacing: 2) {
                Text(page.displayTitle)
                    .font(.subheadline)
                    .lineLimit(2)
                Text(page.host)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
            }
            Spacer(minLength: 0)
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundStyle(.tertiary)
        }
        .contentShape(Rectangle())
    }
}

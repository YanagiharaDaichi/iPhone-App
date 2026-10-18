import Foundation

extension String {
    /// HTML タグを取り除き、よく使われる文字参照を元の文字に戻す。
    var strippingHTML: String {
        var text = replacingOccurrences(of: "<[^>]+>", with: "", options: .regularExpression)
        // "&amp;lt;" を "<" にしてしまわないよう、"&amp;" は最後に置き換える。
        let entities = [
            ("&lt;", "<"),
            ("&gt;", ">"),
            ("&quot;", "\""),
            ("&#39;", "'"),
            ("&apos;", "'"),
            ("&nbsp;", " "),
            ("&amp;", "&"),
        ]
        for (entity, character) in entities {
            text = text.replacingOccurrences(of: entity, with: character)
        }
        return text.trimmingCharacters(in: .whitespacesAndNewlines)
    }
}

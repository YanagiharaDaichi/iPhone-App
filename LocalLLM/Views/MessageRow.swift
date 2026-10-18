import SwiftUI
import UIKit

struct MessageRow: View {
    let message: ChatMessage

    var body: some View {
        switch message.role {
        case .user:
            UserBubble(text: message.text)
        case .assistant:
            AssistantMessage(message: message)
        }
    }
}

private struct UserBubble: View {
    let text: String

    var body: some View {
        HStack {
            Spacer(minLength: 48)
            Text(text)
                .textSelection(.enabled)
                .padding(.horizontal, 14)
                .padding(.vertical, 10)
                .foregroundStyle(.white)
                .background(Color.accentColor, in: .rect(cornerRadius: 18))
        }
    }
}

private struct AssistantMessage: View {
    let message: ChatMessage
    @State private var showThinking = false

    var body: some View {
        let parsed = message.parsed

        VStack(alignment: .leading, spacing: 8) {
            if let thinking = parsed.thinking {
                DisclosureGroup(isExpanded: $showThinking) {
                    Text(thinking)
                        .font(.footnote)
                        .foregroundStyle(.secondary)
                        .textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .padding(.top, 4)
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "brain")
                        Text(parsed.isThinking ? "考えています…" : "思考過程")
                        if parsed.isThinking {
                            ProgressView().controlSize(.mini)
                        }
                    }
                    .font(.footnote)
                    .foregroundStyle(.secondary)
                }
                .padding(10)
                .background(Color(.secondarySystemBackground), in: .rect(cornerRadius: 12))
            }

            if !parsed.answer.isEmpty {
                Text(Self.markdown(parsed.answer))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            } else if message.isStreaming, parsed.thinking == nil {
                TypingIndicator()
            }

            if let stats = message.stats, !message.isStreaming {
                Text(stats)
                    .font(.caption2)
                    .foregroundStyle(.tertiary)
            }
        }
        .contextMenu {
            Button("コピー", systemImage: "doc.on.doc") {
                UIPasteboard.general.string = parsed.answer
            }
            ShareLink(item: parsed.answer)
        }
    }

    /// Renders inline Markdown (bold, code, links) while keeping line breaks as written.
    private static func markdown(_ text: String) -> AttributedString {
        let options = AttributedString.MarkdownParsingOptions(
            interpretedSyntax: .inlineOnlyPreservingWhitespace)
        return (try? AttributedString(markdown: text, options: options)) ?? AttributedString(text)
    }
}

private struct TypingIndicator: View {
    @State private var phase = 0.0

    var body: some View {
        HStack(spacing: 5) {
            ForEach(0..<3) { index in
                Circle()
                    .frame(width: 7, height: 7)
                    .opacity(phase == Double(index) ? 1 : 0.3)
            }
        }
        .foregroundStyle(.secondary)
        .padding(.vertical, 6)
        .task {
            while !Task.isCancelled {
                try? await Task.sleep(for: .milliseconds(350))
                withAnimation(.easeInOut(duration: 0.2)) {
                    phase = (phase + 1).truncatingRemainder(dividingBy: 3)
                }
            }
        }
        .accessibilityLabel("応答を生成中")
    }
}

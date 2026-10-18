import SwiftUI

@main
struct LocalLLMApp: App {
    @State private var store = ChatStore()

    var body: some Scene {
        WindowGroup {
            ChatView()
                .environment(store)
        }
    }
}

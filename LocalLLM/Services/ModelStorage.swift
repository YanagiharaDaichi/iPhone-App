import Foundation
import HuggingFace

/// Where downloaded model weights live, and bookkeeping for which ones are complete.
///
/// Weights go to Application Support (not Caches, which iOS may purge when storage is
/// low) and are excluded from iCloud backup.
enum ModelStorage {
    static let cache: HubCache = {
        var directory = URL.applicationSupportDirectory
            .appending(path: "huggingface/hub", directoryHint: .isDirectory)
        try? FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
        var values = URLResourceValues()
        values.isExcludedFromBackup = true
        try? directory.setResourceValues(values)
        return HubCache(cacheDirectory: directory)
    }()

    static let downloader = HubDownloader(client: HubClient(cache: cache))

    private static let completedKey = "completedModelDownloads"

    /// Ids whose download finished and loaded successfully at least once.
    static var downloadedIDs: Set<String> {
        let ids = Set(UserDefaults.standard.stringArray(forKey: completedKey) ?? [])
        return ids.filter { id in
            directory(for: id).map { FileManager.default.fileExists(atPath: $0.path) } ?? false
        }
    }

    static func markDownloaded(_ id: String) {
        var ids = Set(UserDefaults.standard.stringArray(forKey: completedKey) ?? [])
        ids.insert(id)
        UserDefaults.standard.set(Array(ids).sorted(), forKey: completedKey)
    }

    static func delete(_ id: String) throws {
        var ids = Set(UserDefaults.standard.stringArray(forKey: completedKey) ?? [])
        ids.remove(id)
        UserDefaults.standard.set(Array(ids).sorted(), forKey: completedKey)
        if let directory = directory(for: id), FileManager.default.fileExists(atPath: directory.path) {
            try FileManager.default.removeItem(at: directory)
        }
    }

    static func directory(for id: String) -> URL? {
        guard let repo = Repo.ID(rawValue: id) else { return nil }
        return cache.repoDirectory(repo: repo, kind: .model)
    }

    /// Bytes on disk for one model (`id`) or for every downloaded model (`nil`).
    static func diskUsage(of id: String? = nil) -> Int64 {
        let root = id.flatMap(directory(for:)) ?? cache.cacheDirectory
        let keys: [URLResourceKey] = [.isRegularFileKey, .totalFileAllocatedSizeKey]
        guard
            let enumerator = FileManager.default.enumerator(
                at: root, includingPropertiesForKeys: keys)
        else { return 0 }

        var total: Int64 = 0
        for case let url as URL in enumerator {
            // Snapshot entries are symlinks into `blobs/`; only count the regular files.
            guard let values = try? url.resourceValues(forKeys: Set(keys)),
                values.isRegularFile == true
            else { continue }
            total += Int64(values.totalFileAllocatedSize ?? 0)
        }
        return total
    }
}

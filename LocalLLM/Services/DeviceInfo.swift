import Foundation

enum DeviceInfo {
    /// Installed RAM in GB, rounded to the marketing figure (an 8GB iPhone reports ~7.5GB).
    static let memoryGB: Int = {
        let bytes = Double(ProcessInfo.processInfo.physicalMemory)
        return Int((bytes / 1_073_741_824).rounded())
    }()

    static func formattedBytes(_ bytes: Int64) -> String {
        ByteCountFormatter.string(fromByteCount: bytes, countStyle: .file)
    }
}

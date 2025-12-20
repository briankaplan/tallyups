import Foundation
import SwiftUI
import BackgroundTasks

/// Persistent upload queue with offline support
/// Stores pending uploads locally and syncs when network is available
@MainActor
class UploadQueue: ObservableObject {
    static let shared = UploadQueue()

    @Published var pendingItems: [UploadItem] = []
    @Published var isUploading = false
    @Published var currentProgress: Double?
    @Published var lastError: String?

    private let storageKey = "pending_uploads"
    private let maxRetries = 3
    private var uploadTask: Task<Void, Never>?

    var pendingCount: Int { pendingItems.count }

    private init() {
        loadPendingItems()
    }

    // MARK: - Queue Management

    /// Add a new item to the upload queue
    func enqueue(_ item: UploadItem) {
        var newItem = item
        newItem.status = .pending
        pendingItems.append(newItem)
        savePendingItems()

        // Start upload if connected
        if NetworkMonitor.shared.isConnected {
            startUploadIfNeeded()
        }
    }

    /// Create and enqueue a receipt image
    func enqueueReceipt(
        imageData: Data,
        merchant: String? = nil,
        amount: Double? = nil,
        date: Date? = nil,
        category: String? = nil,
        notes: String? = nil,
        business: String? = nil,
        latitude: Double? = nil,
        longitude: Double? = nil
    ) {
        let item = UploadItem(
            imageData: imageData,
            merchant: merchant,
            amount: amount,
            date: date,
            category: category,
            notes: notes,
            business: business,
            latitude: latitude,
            longitude: longitude,
            source: "ios_scanner"
        )
        enqueue(item)
    }

    /// Remove an item from the queue
    func remove(_ item: UploadItem) {
        pendingItems.removeAll { $0.id == item.id }
        savePendingItems()
    }

    /// Clear all pending items
    func clearAll() {
        pendingItems.removeAll()
        savePendingItems()
    }

    // MARK: - Upload Processing

    /// Resume pending uploads when network becomes available
    func resumePendingUploads() {
        guard !isUploading else { return }
        startUploadIfNeeded()
    }

    /// Pause current uploads
    func pauseUploads() {
        uploadTask?.cancel()
        uploadTask = nil
        isUploading = false
        currentProgress = nil
    }

    /// Process uploads in background
    func processBackgroundUploads() async {
        guard !pendingItems.isEmpty else { return }

        for (index, item) in pendingItems.enumerated() where item.status == .pending {
            do {
                try await uploadItem(at: index)
            } catch {
                // Continue with next item
            }
        }
    }

    private func startUploadIfNeeded() {
        guard !isUploading else { return }
        guard pendingItems.contains(where: { $0.status == .pending }) else { return }

        uploadTask = Task {
            await processQueue()
        }
    }

    private func processQueue() async {
        isUploading = true

        while let index = pendingItems.firstIndex(where: { $0.status == .pending }) {
            guard !Task.isCancelled else { break }

            do {
                try await uploadItem(at: index)
            } catch {
                // Mark as failed and continue
                if index < pendingItems.count {
                    pendingItems[index].status = .failed
                    pendingItems[index].lastError = error.localizedDescription
                    pendingItems[index].retryCount += 1

                    // Remove if max retries exceeded
                    if pendingItems[index].retryCount >= maxRetries {
                        lastError = "Upload failed after \(maxRetries) attempts"
                    }
                }
                savePendingItems()
            }
        }

        isUploading = false
        currentProgress = nil
    }

    private func uploadItem(at index: Int) async throws {
        guard index < pendingItems.count else { return }

        pendingItems[index].status = .uploading
        savePendingItems()

        let item = pendingItems[index]

        // Update progress
        let totalCount = Double(pendingItems.count)
        currentProgress = Double(index) / totalCount

        // Upload to server
        let response = try await APIClient.shared.uploadReceipt(
            imageData: item.imageData,
            merchant: item.merchant,
            amount: item.amount,
            date: item.date,
            category: item.category,
            notes: item.notes,
            business: item.business,
            latitude: item.latitude,
            longitude: item.longitude,
            source: item.source
        )

        if response.success {
            // Remove from queue
            pendingItems.removeAll { $0.id == item.id }
            savePendingItems()

            // Show success notification
            await MainActor.run {
                NotificationCenter.default.post(
                    name: .receiptUploaded,
                    object: nil,
                    userInfo: ["receiptId": response.receiptId ?? ""]
                )
            }
        } else {
            throw APIError.serverError(500, response.message ?? "Upload failed")
        }
    }

    // MARK: - Persistence

    private func savePendingItems() {
        do {
            let data = try JSONEncoder().encode(pendingItems)
            UserDefaults.standard.set(data, forKey: storageKey)
        } catch {
            print("Failed to save pending items: \(error)")
        }
    }

    private func loadPendingItems() {
        guard let data = UserDefaults.standard.data(forKey: storageKey) else { return }

        do {
            var items = try JSONDecoder().decode([UploadItem].self, from: data)

            // Reset uploading items to pending (app was killed during upload)
            for i in 0..<items.count {
                if items[i].status == .uploading {
                    items[i].status = .pending
                }
            }

            pendingItems = items
        } catch {
            print("Failed to load pending items: \(error)")
        }
    }
}

// MARK: - Notifications

extension Notification.Name {
    static let receiptUploaded = Notification.Name("receiptUploaded")
    static let uploadFailed = Notification.Name("uploadFailed")
}

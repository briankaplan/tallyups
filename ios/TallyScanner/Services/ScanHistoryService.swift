import Foundation
import SwiftUI

/// Manages scan history with local persistence
@MainActor
class ScanHistoryService: ObservableObject {
    static let shared = ScanHistoryService()

    @Published var history: [ScanHistoryItem] = []

    private let storageKey = "scan_history"
    private let maxHistoryItems = 100

    private init() {
        loadHistory()
    }

    // MARK: - History Management

    /// Add a new scan to history
    func addScan(
        imageData: Data,
        merchant: String? = nil,
        amount: Double? = nil,
        date: Date = Date()
    ) -> ScanHistoryItem {
        let item = ScanHistoryItem(
            id: UUID(),
            imageData: imageData,
            merchant: merchant,
            amount: amount,
            date: date,
            status: .pending,
            r2Url: nil,
            receiptId: nil,
            ocrResult: nil,
            scannedAt: Date()
        )

        history.insert(item, at: 0)

        // Trim to max size
        if history.count > maxHistoryItems {
            history = Array(history.prefix(maxHistoryItems))
        }

        saveHistory()
        return item
    }

    /// Update scan status after upload
    func updateScan(
        id: UUID,
        status: ScanHistoryItem.ScanStatus,
        r2Url: String? = nil,
        receiptId: String? = nil,
        merchant: String? = nil,
        amount: Double? = nil,
        ocrResult: OCRResult? = nil
    ) {
        guard let index = history.firstIndex(where: { $0.id == id }) else { return }

        history[index].status = status
        if let r2Url = r2Url { history[index].r2Url = r2Url }
        if let receiptId = receiptId { history[index].receiptId = receiptId }
        if let merchant = merchant { history[index].merchant = merchant }
        if let amount = amount { history[index].amount = amount }
        if let ocrResult = ocrResult { history[index].ocrResult = ocrResult }

        saveHistory()
    }

    /// Mark scan as failed
    func markFailed(id: UUID) {
        updateScan(id: id, status: .failed)
    }

    /// Mark scan as uploaded
    func markUploaded(id: UUID, r2Url: String?, receiptId: String?) {
        updateScan(id: id, status: .uploaded, r2Url: r2Url, receiptId: receiptId)
    }

    /// Delete a specific scan from history
    func deleteScan(id: UUID) {
        history.removeAll { $0.id == id }
        saveHistory()
    }

    /// Clear all history
    func clearHistory() {
        history.removeAll()
        saveHistory()
    }

    /// Clear only uploaded/successful scans
    func clearCompletedScans() {
        history.removeAll { $0.status == .uploaded }
        saveHistory()
    }

    /// Clear failed scans
    func clearFailedScans() {
        history.removeAll { $0.status == .failed }
        saveHistory()
    }

    // MARK: - Filtered Access

    var pendingScans: [ScanHistoryItem] {
        history.filter { $0.status == .pending || $0.status == .uploading }
    }

    var completedScans: [ScanHistoryItem] {
        history.filter { $0.status == .uploaded }
    }

    var failedScans: [ScanHistoryItem] {
        history.filter { $0.status == .failed }
    }

    var todayScans: [ScanHistoryItem] {
        let calendar = Calendar.current
        return history.filter { calendar.isDateInToday($0.scannedAt) }
    }

    var thisWeekScans: [ScanHistoryItem] {
        let calendar = Calendar.current
        let weekAgo = calendar.date(byAdding: .day, value: -7, to: Date()) ?? Date()
        return history.filter { $0.scannedAt >= weekAgo }
    }

    // MARK: - Stats

    var totalScansToday: Int { todayScans.count }
    var totalScansThisWeek: Int { thisWeekScans.count }
    var pendingCount: Int { pendingScans.count }
    var failedCount: Int { failedScans.count }

    var totalAmountToday: Double {
        todayScans.compactMap { $0.amount }.reduce(0, +)
    }

    // MARK: - Persistence

    private func saveHistory() {
        do {
            // Only save metadata, not full image data for performance
            let lightHistory = history.map { item -> [String: Any] in
                var dict: [String: Any] = [
                    "id": item.id.uuidString,
                    "date": item.date.timeIntervalSince1970,
                    "status": item.status.rawValue,
                    "scannedAt": item.scannedAt.timeIntervalSince1970
                ]
                if let merchant = item.merchant { dict["merchant"] = merchant }
                if let amount = item.amount { dict["amount"] = amount }
                if let r2Url = item.r2Url { dict["r2Url"] = r2Url }
                if let receiptId = item.receiptId { dict["receiptId"] = receiptId }
                return dict
            }

            let data = try JSONSerialization.data(withJSONObject: lightHistory)
            UserDefaults.standard.set(data, forKey: storageKey)
        } catch {
            print("Failed to save scan history: \(error)")
        }
    }

    private func loadHistory() {
        guard let data = UserDefaults.standard.data(forKey: storageKey) else { return }

        do {
            guard let items = try JSONSerialization.jsonObject(with: data) as? [[String: Any]] else { return }

            history = items.compactMap { dict -> ScanHistoryItem? in
                guard let idString = dict["id"] as? String,
                      let id = UUID(uuidString: idString),
                      let dateInterval = dict["date"] as? TimeInterval,
                      let statusString = dict["status"] as? String,
                      let status = ScanHistoryItem.ScanStatus(rawValue: statusString),
                      let scannedAtInterval = dict["scannedAt"] as? TimeInterval
                else { return nil }

                return ScanHistoryItem(
                    id: id,
                    imageData: Data(), // Don't store full image data in history
                    merchant: dict["merchant"] as? String,
                    amount: dict["amount"] as? Double,
                    date: Date(timeIntervalSince1970: dateInterval),
                    status: status,
                    r2Url: dict["r2Url"] as? String,
                    receiptId: dict["receiptId"] as? String,
                    ocrResult: nil,
                    scannedAt: Date(timeIntervalSince1970: scannedAtInterval)
                )
            }
        } catch {
            print("Failed to load scan history: \(error)")
        }
    }
}

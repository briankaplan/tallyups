import Foundation
import UserNotifications
import UIKit

/// Service for handling local notifications
@MainActor
class NotificationService: ObservableObject {
    static let shared = NotificationService()

    @Published var isAuthorized = false
    @Published var pendingNotifications: Int = 0

    private let center = UNUserNotificationCenter.current()

    private init() {
        checkAuthorizationStatus()
    }

    // MARK: - Authorization

    /// Request notification permissions
    func requestAuthorization() async -> Bool {
        do {
            let granted = try await center.requestAuthorization(options: [.alert, .sound, .badge])
            isAuthorized = granted
            return granted
        } catch {
            print("🔔 NotificationService: Authorization error: \(error)")
            return false
        }
    }

    /// Check current authorization status
    func checkAuthorizationStatus() {
        center.getNotificationSettings { [weak self] settings in
            Task { @MainActor in
                self?.isAuthorized = settings.authorizationStatus == .authorized
            }
        }
    }

    // MARK: - Receipt Match Notifications

    /// Notify when a receipt is matched to a transaction
    func notifyReceiptMatched(merchant: String, amount: String, transactionDate: String) {
        let content = UNMutableNotificationContent()
        content.title = "Receipt Matched!"
        content.body = "\(merchant) - \(amount) matched to transaction on \(transactionDate)"
        content.sound = .default
        content.categoryIdentifier = "RECEIPT_MATCHED"

        // Add action buttons
        let viewAction = UNNotificationAction(
            identifier: "VIEW_TRANSACTION",
            title: "View Transaction",
            options: .foreground
        )
        let category = UNNotificationCategory(
            identifier: "RECEIPT_MATCHED",
            actions: [viewAction],
            intentIdentifiers: []
        )
        center.setNotificationCategories([category])

        let request = UNNotificationRequest(
            identifier: UUID().uuidString,
            content: content,
            trigger: nil // Deliver immediately
        )

        center.add(request) { error in
            if let error = error {
                print("🔔 NotificationService: Failed to schedule match notification: \(error)")
            } else {
                print("🔔 NotificationService: Match notification scheduled")
            }
        }
    }

    /// Notify when a receipt is auto-matched by the server
    func notifyAutoMatch(count: Int, merchant: String? = nil) {
        let content = UNMutableNotificationContent()

        if count == 1, let merchant = merchant {
            content.title = "Receipt Auto-Matched"
            content.body = "Your \(merchant) receipt was automatically matched to a transaction"
        } else {
            content.title = "Receipts Auto-Matched"
            content.body = "\(count) receipts were automatically matched to transactions"
        }

        content.sound = .default
        content.badge = NSNumber(value: count)

        let request = UNNotificationRequest(
            identifier: "auto-match-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    // MARK: - Upload Notifications

    /// Notify when upload completes
    func notifyUploadComplete(merchant: String?, amount: String?, success: Bool) {
        let content = UNMutableNotificationContent()

        if success {
            content.title = "Receipt Uploaded"
            if let merchant = merchant, let amount = amount {
                content.body = "\(merchant) - \(amount) uploaded successfully"
            } else if let merchant = merchant {
                content.body = "\(merchant) receipt uploaded successfully"
            } else {
                content.body = "Your receipt was uploaded successfully"
            }
            content.sound = .default
        } else {
            content.title = "Upload Failed"
            content.body = "Failed to upload receipt. Will retry when connected."
            content.sound = UNNotificationSound(named: UNNotificationSoundName("error.wav"))
        }

        let request = UNNotificationRequest(
            identifier: "upload-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    /// Notify when batch upload completes
    func notifyBatchUploadComplete(successful: Int, failed: Int) {
        guard successful > 0 || failed > 0 else { return }

        let content = UNMutableNotificationContent()
        content.title = "Upload Complete"

        if failed == 0 {
            content.body = "\(successful) receipt\(successful == 1 ? "" : "s") uploaded successfully"
            content.sound = .default
        } else if successful == 0 {
            content.body = "\(failed) receipt\(failed == 1 ? "" : "s") failed to upload"
            content.sound = UNNotificationSound(named: UNNotificationSoundName("error.wav"))
        } else {
            content.body = "\(successful) uploaded, \(failed) failed"
            content.sound = .default
        }

        let request = UNNotificationRequest(
            identifier: "batch-upload-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    // MARK: - Incoming Receipt Notifications

    /// Notify when new receipts arrive from Gmail
    func notifyNewIncomingReceipts(count: Int, source: String = "Gmail") {
        guard count > 0 else { return }

        let content = UNMutableNotificationContent()
        content.title = "New Receipts Found"
        content.body = "\(count) new receipt\(count == 1 ? "" : "s") found in \(source)"
        content.sound = .default
        content.badge = NSNumber(value: count)
        content.categoryIdentifier = "INCOMING_RECEIPTS"

        // Add action buttons
        let reviewAction = UNNotificationAction(
            identifier: "REVIEW_RECEIPTS",
            title: "Review",
            options: .foreground
        )
        let category = UNNotificationCategory(
            identifier: "INCOMING_RECEIPTS",
            actions: [reviewAction],
            intentIdentifiers: []
        )
        center.setNotificationCategories([category])

        let request = UNNotificationRequest(
            identifier: "incoming-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    // MARK: - Transaction Notifications

    /// Notify when transactions need receipts
    func notifyMissingReceipts(count: Int) {
        guard count > 0 else { return }

        let content = UNMutableNotificationContent()
        content.title = "Receipts Needed"
        content.body = "\(count) transaction\(count == 1 ? " needs" : "s need") receipts"
        content.sound = .default
        content.categoryIdentifier = "MISSING_RECEIPTS"

        let request = UNNotificationRequest(
            identifier: "missing-receipts",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    // MARK: - Batch Sync Notifications

    /// Celebrate when a large batch of receipts syncs
    func notifyBatchSync(count: Int, matchedCount: Int) {
        guard count > 0 else { return }

        let content = UNMutableNotificationContent()

        if count >= 10 {
            content.title = "Receipts Synced!"
            content.body = "\(count) receipts synced! \(matchedCount) matched to transactions."
            content.interruptionLevel = .active
        } else {
            content.title = "Sync Complete"
            content.body = "\(count) receipt\(count == 1 ? "" : "s") synced successfully"
        }

        content.sound = .default

        let request = UNNotificationRequest(
            identifier: "batch-sync-\(UUID().uuidString)",
            content: content,
            trigger: nil
        )

        center.add(request)

        // Trigger haptic celebration
        Task { @MainActor in
            HapticService.shared.batchSyncComplete(count: count)
        }
    }

    // MARK: - Milestone Notifications

    /// Celebrate milestones like 100 receipts scanned
    func notifyMilestone(type: MilestoneType) {
        let content = UNMutableNotificationContent()

        switch type {
        case .firstReceipt:
            content.title = "First Receipt!"
            content.body = "You scanned your first receipt. You're on your way!"
        case .tenReceipts:
            content.title = "Getting Started!"
            content.body = "You've scanned 10 receipts. Keep it up!"
        case .fiftyReceipts:
            content.title = "Receipt Pro!"
            content.body = "50 receipts scanned! You're becoming a pro."
        case .hundredReceipts:
            content.title = "Century Club!"
            content.body = "100 receipts! You're officially a receipt master."
        case .weekStreak(let days):
            content.title = "\(days)-Day Streak!"
            content.body = "You've scanned receipts \(days) days in a row!"
        case .allMatched:
            content.title = "Perfect Match!"
            content.body = "All your receipts are matched to transactions!"
        case .monthlyGoal(let amount):
            content.title = "Monthly Goal Reached!"
            content.body = "You've tracked $\(String(format: "%.0f", amount)) this month!"
        }

        content.sound = .default
        content.interruptionLevel = .active

        let request = UNNotificationRequest(
            identifier: "milestone-\(type.identifier)",
            content: content,
            trigger: nil
        )

        center.add(request)

        // Trigger celebration haptic
        Task { @MainActor in
            HapticService.shared.milestoneReached()
        }
    }

    // MARK: - Weekly Summary

    /// Schedule weekly summary notification
    func scheduleWeeklySummary() {
        // Schedule for Sunday at 6pm
        var dateComponents = DateComponents()
        dateComponents.weekday = 1 // Sunday
        dateComponents.hour = 18
        dateComponents.minute = 0

        let trigger = UNCalendarNotificationTrigger(dateMatching: dateComponents, repeats: true)

        let content = UNMutableNotificationContent()
        content.title = "Weekly Receipt Summary"
        content.body = "Tap to see your spending breakdown for this week!"
        content.sound = .default
        content.categoryIdentifier = "WEEKLY_SUMMARY"

        let summaryAction = UNNotificationAction(
            identifier: "VIEW_SUMMARY",
            title: "View Summary",
            options: .foreground
        )
        let category = UNNotificationCategory(
            identifier: "WEEKLY_SUMMARY",
            actions: [summaryAction],
            intentIdentifiers: []
        )
        center.setNotificationCategories([category])

        let request = UNNotificationRequest(
            identifier: "weekly-summary",
            content: content,
            trigger: trigger
        )

        center.add(request)
    }

    /// Send weekly summary with actual data
    func sendWeeklySummary(receiptCount: Int, totalAmount: Double, topMerchant: String?) {
        let content = UNMutableNotificationContent()
        content.title = "Your Week in Receipts"

        var body = "You tracked \(receiptCount) receipt\(receiptCount == 1 ? "" : "s") totaling $\(String(format: "%.2f", totalAmount))"
        if let merchant = topMerchant {
            body += ". Most visits: \(merchant)"
        }
        content.body = body
        content.sound = .default
        content.categoryIdentifier = "WEEKLY_SUMMARY"

        let request = UNNotificationRequest(
            identifier: "weekly-summary-\(Date().timeIntervalSince1970)",
            content: content,
            trigger: nil
        )

        center.add(request)
    }

    // MARK: - Proactive Reminders

    /// Remind user to scan receipts if they haven't in a while
    func scheduleInactivityReminder() {
        // Remind after 3 days of inactivity
        let trigger = UNTimeIntervalNotificationTrigger(
            timeInterval: 3 * 24 * 60 * 60, // 3 days
            repeats: false
        )

        let content = UNMutableNotificationContent()
        content.title = "Any Receipts Piling Up?"
        content.body = "Haven't seen you in a while! Got any receipts that need scanning?"
        content.sound = .default
        content.categoryIdentifier = "INACTIVITY_REMINDER"

        let scanAction = UNNotificationAction(
            identifier: "OPEN_SCANNER",
            title: "Scan Now",
            options: .foreground
        )
        let category = UNNotificationCategory(
            identifier: "INACTIVITY_REMINDER",
            actions: [scanAction],
            intentIdentifiers: []
        )
        center.setNotificationCategories([category])

        let request = UNNotificationRequest(
            identifier: "inactivity-reminder",
            content: content,
            trigger: trigger
        )

        center.add(request)
    }

    /// Cancel inactivity reminder (call when user scans a receipt)
    func cancelInactivityReminder() {
        center.removePendingNotificationRequests(withIdentifiers: ["inactivity-reminder"])
    }

    /// Reset inactivity timer (call after each scan)
    func resetInactivityTimer() {
        cancelInactivityReminder()
        scheduleInactivityReminder()
    }

    // MARK: - Badge Management

    /// Update app badge count
    func updateBadge(count: Int) {
        Task { @MainActor in
            UNUserNotificationCenter.current().setBadgeCount(count)
            pendingNotifications = count
        }
    }

    /// Clear all notifications
    func clearAllNotifications() {
        center.removeAllDeliveredNotifications()
        center.removeAllPendingNotificationRequests()
        updateBadge(count: 0)
    }

    /// Clear notifications of a specific type
    func clearNotifications(withPrefix prefix: String) {
        center.getDeliveredNotifications { [weak self] notifications in
            let idsToRemove = notifications
                .filter { $0.request.identifier.hasPrefix(prefix) }
                .map { $0.request.identifier }
            Task { @MainActor in
                self?.center.removeDeliveredNotifications(withIdentifiers: idsToRemove)
            }
        }
    }
}

// MARK: - Milestone Types

enum MilestoneType {
    case firstReceipt
    case tenReceipts
    case fiftyReceipts
    case hundredReceipts
    case weekStreak(days: Int)
    case allMatched
    case monthlyGoal(amount: Double)

    var identifier: String {
        switch self {
        case .firstReceipt: return "first"
        case .tenReceipts: return "ten"
        case .fiftyReceipts: return "fifty"
        case .hundredReceipts: return "hundred"
        case .weekStreak(let days): return "streak-\(days)"
        case .allMatched: return "all-matched"
        case .monthlyGoal: return "monthly-goal"
        }
    }
}

// MARK: - Notification Delegate

class NotificationDelegate: NSObject, UNUserNotificationCenterDelegate {
    static let shared = NotificationDelegate()

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        willPresent notification: UNNotification
    ) async -> UNNotificationPresentationOptions {
        // Show notification even when app is in foreground
        // Trigger haptic for in-app notifications
        Task { @MainActor in
            HapticService.shared.lightTap()
        }
        return [.banner, .sound, .badge]
    }

    func userNotificationCenter(
        _ center: UNUserNotificationCenter,
        didReceive response: UNNotificationResponse
    ) async {
        let actionIdentifier = response.actionIdentifier
        let categoryIdentifier = response.notification.request.content.categoryIdentifier

        // Haptic feedback on interaction
        Task { @MainActor in
            HapticService.shared.mediumTap()
        }

        switch actionIdentifier {
        case "VIEW_TRANSACTION":
            NotificationCenter.default.post(name: .navigateToTransactions, object: nil)

        case "REVIEW_RECEIPTS":
            NotificationCenter.default.post(name: .navigateToInbox, object: nil)

        case "SCAN_NOW", "OPEN_SCANNER":
            NotificationCenter.default.post(name: .navigateToScanner, object: nil)

        case "VIEW_SUMMARY":
            NotificationCenter.default.post(name: .navigateToLibrary, object: nil)

        case "SKIP":
            // User dismissed receipt reminder - do nothing
            break

        case UNNotificationDefaultActionIdentifier:
            // User tapped notification body - navigate based on category
            switch categoryIdentifier {
            case "RECEIPT_REMINDER", "INACTIVITY_REMINDER":
                NotificationCenter.default.post(name: .navigateToScanner, object: nil)
            case "INCOMING_RECEIPTS":
                NotificationCenter.default.post(name: .navigateToInbox, object: nil)
            case "RECEIPT_MATCHED", "MISSING_RECEIPTS":
                NotificationCenter.default.post(name: .navigateToTransactions, object: nil)
            case "WEEKLY_SUMMARY":
                NotificationCenter.default.post(name: .navigateToLibrary, object: nil)
            default:
                break
            }

        default:
            break
        }
    }
}

// MARK: - Navigation Notifications

extension Notification.Name {
    static let navigateToTransactions = Notification.Name("navigateToTransactions")
    static let navigateToInbox = Notification.Name("navigateToInbox")
    static let navigateToLibrary = Notification.Name("navigateToLibrary")
    static let navigateToScanner = Notification.Name("navigateToScanner")
}

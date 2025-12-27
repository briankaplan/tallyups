import UIKit
import SwiftUI

// MARK: - Quick Action Types

enum QuickActionType: String {
    case scanReceipt = "com.tallyups.scanner.scan"
    case checkInbox = "com.tallyups.scanner.inbox"
    case viewSpending = "com.tallyups.scanner.spending"
    case searchReceipts = "com.tallyups.scanner.search"

    var shortcutItem: UIApplicationShortcutItem {
        switch self {
        case .scanReceipt:
            return UIApplicationShortcutItem(
                type: rawValue,
                localizedTitle: "Scan Receipt",
                localizedSubtitle: "Capture a new receipt",
                icon: UIApplicationShortcutIcon(systemImageName: "camera.fill"),
                userInfo: nil
            )
        case .checkInbox:
            return UIApplicationShortcutItem(
                type: rawValue,
                localizedTitle: "Check Inbox",
                localizedSubtitle: "View pending receipts",
                icon: UIApplicationShortcutIcon(systemImageName: "tray.fill"),
                userInfo: nil
            )
        case .viewSpending:
            return UIApplicationShortcutItem(
                type: rawValue,
                localizedTitle: "View Spending",
                localizedSubtitle: "See your transactions",
                icon: UIApplicationShortcutIcon(systemImageName: "chart.line.uptrend.xyaxis"),
                userInfo: nil
            )
        case .searchReceipts:
            return UIApplicationShortcutItem(
                type: rawValue,
                localizedTitle: "Search",
                localizedSubtitle: "Find a receipt",
                icon: UIApplicationShortcutIcon(systemImageName: "magnifyingglass"),
                userInfo: nil
            )
        }
    }
}

// MARK: - Quick Actions Manager

class QuickActionsManager {
    static let shared = QuickActionsManager()

    private init() {}

    /// Register all quick actions with the app
    func registerQuickActions() {
        UIApplication.shared.shortcutItems = [
            QuickActionType.scanReceipt.shortcutItem,
            QuickActionType.checkInbox.shortcutItem,
            QuickActionType.viewSpending.shortcutItem,
            QuickActionType.searchReceipts.shortcutItem
        ]
    }

    /// Update quick action badge (e.g., pending receipts count)
    func updateInboxBadge(count: Int) {
        var items = UIApplication.shared.shortcutItems ?? []

        // Find and update the inbox action
        if let index = items.firstIndex(where: { $0.type == QuickActionType.checkInbox.rawValue }) {
            let subtitle = count > 0 ? "\(count) pending receipt\(count == 1 ? "" : "s")" : "All caught up!"
            items[index] = UIApplicationShortcutItem(
                type: QuickActionType.checkInbox.rawValue,
                localizedTitle: "Check Inbox",
                localizedSubtitle: subtitle,
                icon: UIApplicationShortcutIcon(systemImageName: "tray.fill"),
                userInfo: nil
            )
        }

        UIApplication.shared.shortcutItems = items
    }

    /// Handle a quick action
    func handleQuickAction(_ shortcutItem: UIApplicationShortcutItem) -> Bool {
        guard let actionType = QuickActionType(rawValue: shortcutItem.type) else {
            return false
        }

        // Give haptic feedback
        HapticService.shared.impact(.medium)

        // Post navigation notification
        DispatchQueue.main.async {
            switch actionType {
            case .scanReceipt:
                NotificationCenter.default.post(name: .navigateToScanner, object: nil)
            case .checkInbox:
                NotificationCenter.default.post(name: .navigateToInbox, object: nil)
            case .viewSpending:
                NotificationCenter.default.post(name: .navigateToTransactions, object: nil)
            case .searchReceipts:
                NotificationCenter.default.post(name: .navigateToLibrary, object: nil)
            }
        }

        return true
    }
}

// MARK: - Scene Delegate Extension for Quick Actions

extension UIWindowSceneDelegate {
    func handleQuickAction(_ shortcutItem: UIApplicationShortcutItem) {
        _ = QuickActionsManager.shared.handleQuickAction(shortcutItem)
    }
}

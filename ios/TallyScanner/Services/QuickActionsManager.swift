import UIKit
import SwiftUI

/// Manages Home Screen Quick Actions (3D Touch / Haptic Touch shortcuts)
class QuickActionsManager {
    static let shared = QuickActionsManager()

    // MARK: - Quick Action Types

    enum ActionType: String {
        case scanReceipt = "com.tallyups.scanner.scan"
        case viewRecent = "com.tallyups.scanner.recent"
        case searchTransactions = "com.tallyups.scanner.search"
        case openInbox = "com.tallyups.scanner.inbox"

        var title: String {
            switch self {
            case .scanReceipt: return "Scan Receipt"
            case .viewRecent: return "Recent Receipts"
            case .searchTransactions: return "Search"
            case .openInbox: return "Inbox"
            }
        }

        var subtitle: String? {
            switch self {
            case .scanReceipt: return "Capture a new receipt"
            case .viewRecent: return nil
            case .searchTransactions: return "Find transactions"
            case .openInbox: return nil
            }
        }

        var iconName: String {
            switch self {
            case .scanReceipt: return "camera.fill"
            case .viewRecent: return "clock.fill"
            case .searchTransactions: return "magnifyingglass"
            case .openInbox: return "tray.fill"
            }
        }
    }

    private init() {}

    // MARK: - Register Quick Actions

    /// Register all quick actions on app launch
    func registerQuickActions() {
        configureQuickActions()
    }

    /// Update the app's quick actions based on user state
    func configureQuickActions() {
        var shortcuts: [UIApplicationShortcutItem] = []

        // Primary action: Scan Receipt
        shortcuts.append(createShortcutItem(for: .scanReceipt))

        // Secondary actions
        shortcuts.append(createShortcutItem(for: .openInbox))
        shortcuts.append(createShortcutItem(for: .viewRecent))
        shortcuts.append(createShortcutItem(for: .searchTransactions))

        UIApplication.shared.shortcutItems = shortcuts
    }

    private func createShortcutItem(for actionType: ActionType) -> UIApplicationShortcutItem {
        let icon = UIApplicationShortcutIcon(systemImageName: actionType.iconName)

        return UIApplicationShortcutItem(
            type: actionType.rawValue,
            localizedTitle: actionType.title,
            localizedSubtitle: actionType.subtitle,
            icon: icon,
            userInfo: nil
        )
    }

    // MARK: - Handle Quick Actions

    /// Handle a quick action from the Home Screen
    /// - Parameter shortcutItem: The shortcut item that was activated
    /// - Returns: True if the action was handled
    @discardableResult
    func handleQuickAction(_ shortcutItem: UIApplicationShortcutItem) -> Bool {
        guard let actionType = ActionType(rawValue: shortcutItem.type) else {
            return false
        }

        // Post notification for the main app to handle
        NotificationCenter.default.post(
            name: .quickActionTriggered,
            object: nil,
            userInfo: ["destination": getDestination(for: actionType)]
        )

        return true
    }

    /// Get the destination for a quick action type
    func getDestination(for actionType: ActionType) -> QuickActionDestination {
        switch actionType {
        case .scanReceipt:
            return .scanner
        case .viewRecent:
            return .library
        case .searchTransactions:
            return .transactions
        case .openInbox:
            return .inbox
        }
    }

    /// Get the destination for a shortcut item
    func destination(for shortcutItem: UIApplicationShortcutItem) -> QuickActionDestination? {
        guard let actionType = ActionType(rawValue: shortcutItem.type) else {
            return nil
        }
        return getDestination(for: actionType)
    }

    /// Handle a quick action URL
    func handleQuickActionURL(_ url: URL) -> QuickActionDestination? {
        guard url.scheme == "tallyups" else { return nil }

        switch url.host {
        case "scan":
            return .scanner
        case "library":
            return .library
        case "transactions":
            return .transactions
        case "inbox":
            return .inbox
        case "settings":
            return .settings
        default:
            return nil
        }
    }
}

// MARK: - Quick Action Destination

/// Destinations that can be navigated to from quick actions
enum QuickActionDestination: Hashable {
    case scanner
    case library
    case transactions
    case inbox
    case settings
    case receipt(id: String)
    case transaction(index: Int)

    var tabIndex: Int {
        switch self {
        case .scanner: return 0
        case .library: return 1
        case .transactions: return 2
        case .inbox: return 3
        case .settings: return 4
        case .receipt, .transaction: return 1
        }
    }
}

// MARK: - Notification Names

extension Notification.Name {
    static let quickActionTriggered = Notification.Name("com.tallyups.quickActionTriggered")
}

import WidgetKit
import SwiftUI

@main
struct TallyScannerWidgetsBundle: WidgetBundle {
    var body: some Widget {
        // Spending summary widget - shows daily/weekly/monthly totals
        SpendingWidget()

        // Quick scan widget - one-tap access to camera
        QuickScanWidget()

        // Inbox widget - shows pending receipts count
        InboxWidget()
    }
}

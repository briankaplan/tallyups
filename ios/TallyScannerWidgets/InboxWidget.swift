import WidgetKit
import SwiftUI

// MARK: - Inbox Widget Entry
struct InboxEntry: TimelineEntry {
    let date: Date
    let pendingCount: Int
    let matchedCount: Int
    let rejectedCount: Int
    let recentReceipts: [WidgetInboxReceipt]

    static var placeholder: InboxEntry {
        InboxEntry(
            date: Date(),
            pendingCount: 5,
            matchedCount: 12,
            rejectedCount: 2,
            recentReceipts: [
                WidgetInboxReceipt(id: "1", merchant: "Starbucks", amount: 5.75, source: "Gmail"),
                WidgetInboxReceipt(id: "2", merchant: "Amazon", amount: 47.99, source: "Upload"),
                WidgetInboxReceipt(id: "3", merchant: "Uber", amount: 24.50, source: "Photo Library")
            ]
        )
    }
}

struct WidgetInboxReceipt: Identifiable, Codable {
    let id: String
    let merchant: String
    let amount: Double
    let source: String

    var formattedAmount: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }

    var sourceIcon: String {
        switch source.lowercased() {
        case "gmail", "email": return "envelope.fill"
        case "upload", "photo library": return "photo.fill"
        case "scan", "camera": return "camera.fill"
        default: return "doc.fill"
        }
    }
}

// MARK: - Inbox Widget Provider
struct InboxWidgetProvider: TimelineProvider {
    typealias Entry = InboxEntry

    func placeholder(in context: Context) -> InboxEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (InboxEntry) -> Void) {
        let data = WidgetDataStore.shared.loadSpendingData()
        let entry = InboxEntry(
            date: Date(),
            pendingCount: data.pendingReceipts,
            matchedCount: data.matchedReceipts,
            rejectedCount: 0,
            recentReceipts: []
        )
        completion(entry)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<InboxEntry>) -> Void) {
        let data = WidgetDataStore.shared.loadSpendingData()
        let entry = InboxEntry(
            date: Date(),
            pendingCount: data.pendingReceipts,
            matchedCount: data.matchedReceipts,
            rejectedCount: 0,
            recentReceipts: []
        )

        let nextUpdate = Calendar.current.date(byAdding: .minute, value: 15, to: Date())!
        let timeline = Timeline(entries: [entry], policy: .after(nextUpdate))
        completion(timeline)
    }
}

// MARK: - Inbox Widget View
struct InboxWidgetEntryView: View {
    var entry: InboxEntry
    @Environment(\.widgetFamily) var family

    var body: some View {
        switch family {
        case .systemSmall:
            SmallInboxView(entry: entry)
        case .systemMedium:
            MediumInboxView(entry: entry)
        case .accessoryCircular:
            CircularInboxView(entry: entry)
        case .accessoryRectangular:
            RectangularInboxView(entry: entry)
        @unknown default:
            SmallInboxView(entry: entry)
        }
    }
}

// MARK: - Small Inbox View
struct SmallInboxView: View {
    let entry: InboxEntry

    var body: some View {
        Link(destination: WidgetDeepLink.inbox.url) {
            VStack(spacing: 12) {
                // Icon with badge
                ZStack(alignment: .topTrailing) {
                    Image(systemName: "tray.fill")
                        .font(.system(size: 36))
                        .foregroundColor(entry.pendingCount > 0 ? .orange : .secondary)

                    if entry.pendingCount > 0 {
                        Text("\(entry.pendingCount)")
                            .font(.caption2.bold())
                            .foregroundColor(.white)
                            .padding(4)
                            .background(Color.red)
                            .clipShape(Circle())
                            .offset(x: 8, y: -8)
                    }
                }

                // Status text
                VStack(spacing: 2) {
                    if entry.pendingCount > 0 {
                        Text("\(entry.pendingCount)")
                            .font(.title.bold())
                        Text("Pending")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("All Clear!")
                            .font(.headline)
                            .foregroundColor(.green)
                        Text("No pending receipts")
                            .font(.caption2)
                            .foregroundColor(.secondary)
                    }
                }
            }
            .padding()
        }
    }
}

// MARK: - Medium Inbox View
struct MediumInboxView: View {
    let entry: InboxEntry

    var body: some View {
        HStack(spacing: 16) {
            // Left side - Stats
            VStack(alignment: .leading, spacing: 8) {
                Text("Receipt Inbox")
                    .font(.caption.bold())
                    .foregroundColor(.secondary)

                HStack(spacing: 16) {
                    InboxStatView(
                        count: entry.pendingCount,
                        label: "Pending",
                        color: .orange,
                        icon: "clock.fill"
                    )

                    InboxStatView(
                        count: entry.matchedCount,
                        label: "Matched",
                        color: .green,
                        icon: "checkmark.circle.fill"
                    )
                }

                Spacer()

                // Quick action
                Link(destination: WidgetDeepLink.inbox.url) {
                    HStack {
                        Text("Review Inbox")
                            .font(.caption.bold())
                        Image(systemName: "chevron.right")
                            .font(.caption2)
                    }
                    .foregroundColor(.orange)
                }
            }

            Divider()

            // Right side - Recent receipts
            if !entry.recentReceipts.isEmpty {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Recent")
                        .font(.caption.bold())
                        .foregroundColor(.secondary)

                    ForEach(entry.recentReceipts.prefix(3)) { receipt in
                        HStack(spacing: 6) {
                            Image(systemName: receipt.sourceIcon)
                                .font(.caption2)
                                .foregroundColor(.secondary)
                            Text(receipt.merchant)
                                .font(.caption)
                                .lineLimit(1)
                            Spacer()
                            Text(receipt.formattedAmount)
                                .font(.caption2.bold())
                        }
                        .padding(.vertical, 2)
                    }

                    Spacer()
                }
            } else {
                VStack {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.largeTitle)
                        .foregroundColor(.green)
                    Text("All caught up!")
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                .frame(maxWidth: .infinity)
            }
        }
        .padding()
    }
}

// MARK: - Lock Screen Widgets

struct CircularInboxView: View {
    let entry: InboxEntry

    var body: some View {
        ZStack {
            AccessoryWidgetBackground()
            VStack(spacing: 2) {
                Image(systemName: "tray.fill")
                    .font(.title3)
                Text("\(entry.pendingCount)")
                    .font(.caption.bold())
                    .foregroundColor(entry.pendingCount > 0 ? .orange : .secondary)
            }
        }
        .widgetURL(WidgetDeepLink.inbox.url)
    }
}

struct RectangularInboxView: View {
    let entry: InboxEntry

    var body: some View {
        HStack {
            Image(systemName: "tray.fill")
                .font(.title2)
                .foregroundColor(entry.pendingCount > 0 ? .orange : .secondary)
            VStack(alignment: .leading, spacing: 2) {
                Text("Receipt Inbox")
                    .font(.headline)
                if entry.pendingCount > 0 {
                    Text("\(entry.pendingCount) receipts waiting")
                        .font(.caption2)
                        .foregroundColor(.orange)
                } else {
                    Text("All caught up!")
                        .font(.caption2)
                        .foregroundColor(.green)
                }
            }
            Spacer()
        }
        .widgetURL(WidgetDeepLink.inbox.url)
    }
}

// MARK: - Helper Views

struct InboxStatView: View {
    let count: Int
    let label: String
    let color: Color
    let icon: String

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .foregroundColor(color)
                Text("\(count)")
                    .font(.title2.bold())
            }
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
    }
}

// MARK: - Widget Definition
struct InboxWidget: Widget {
    let kind: String = "InboxWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: InboxWidgetProvider()) { entry in
            InboxWidgetEntryView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Receipt Inbox")
        .description("See pending receipts at a glance.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .accessoryCircular,
            .accessoryRectangular
        ])
    }
}

// MARK: - Preview
#Preview(as: .systemSmall) {
    InboxWidget()
} timeline: {
    InboxEntry.placeholder
    InboxEntry(date: Date(), pendingCount: 0, matchedCount: 50, rejectedCount: 3, recentReceipts: [])
}

#Preview(as: .systemMedium) {
    InboxWidget()
} timeline: {
    InboxEntry.placeholder
}

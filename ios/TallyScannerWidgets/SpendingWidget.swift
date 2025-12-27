import WidgetKit
import SwiftUI

// MARK: - Spending Widget Provider
struct SpendingWidgetProvider: TimelineProvider {
    typealias Entry = SpendingEntry

    func placeholder(in context: Context) -> SpendingEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (SpendingEntry) -> Void) {
        let data = WidgetDataStore.shared.loadSpendingData()
        let entry = SpendingEntry(
            date: Date(),
            data: data,
            configuration: SpendingWidgetConfiguration()
        )
        completion(entry)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<SpendingEntry>) -> Void) {
        let data = WidgetDataStore.shared.loadSpendingData()
        let entry = SpendingEntry(
            date: Date(),
            data: data,
            configuration: SpendingWidgetConfiguration()
        )

        // Refresh every 30 minutes
        let nextUpdate = Calendar.current.date(byAdding: .minute, value: 30, to: Date())!
        let timeline = Timeline(entries: [entry], policy: .after(nextUpdate))
        completion(timeline)
    }
}

// MARK: - Spending Widget View
struct SpendingWidgetEntryView: View {
    var entry: SpendingEntry
    @Environment(\.widgetFamily) var family

    var body: some View {
        switch family {
        case .systemSmall:
            SmallSpendingView(entry: entry)
        case .systemMedium:
            MediumSpendingView(entry: entry)
        case .systemLarge:
            LargeSpendingView(entry: entry)
        case .accessoryCircular:
            CircularAccessoryView(entry: entry)
        case .accessoryRectangular:
            RectangularAccessoryView(entry: entry)
        case .accessoryInline:
            InlineAccessoryView(entry: entry)
        @unknown default:
            SmallSpendingView(entry: entry)
        }
    }
}

// MARK: - Small Widget View
struct SmallSpendingView: View {
    let entry: SpendingEntry

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            // Header
            HStack {
                Image(systemName: "chart.line.uptrend.xyaxis")
                    .font(.caption)
                    .foregroundColor(.green)
                Text("Today")
                    .font(.caption.bold())
                    .foregroundColor(.secondary)
                Spacer()
            }

            // Daily Total
            Text(entry.data.dailyTotal.currencyFormatted)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundColor(.primary)
                .minimumScaleFactor(0.7)

            Spacer()

            // Pending indicator
            if entry.data.pendingReceipts > 0 {
                HStack(spacing: 4) {
                    Image(systemName: "doc.text")
                        .font(.caption2)
                        .foregroundColor(.orange)
                    Text("\(entry.data.pendingReceipts) pending")
                        .font(.caption2)
                        .foregroundColor(.orange)
                }
            }

            // Last updated
            Text(entry.data.lastUpdated.widgetTimeAgo)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
        .padding()
        .widgetURL(WidgetDeepLink.dashboard.url)
    }
}

// MARK: - Medium Widget View
struct MediumSpendingView: View {
    let entry: SpendingEntry

    var body: some View {
        HStack(spacing: 16) {
            // Left side - Spending totals
            VStack(alignment: .leading, spacing: 12) {
                // Daily
                SpendingRow(
                    icon: "sun.max.fill",
                    label: "Today",
                    amount: entry.data.dailyTotal,
                    color: .orange
                )

                // Weekly
                SpendingRow(
                    icon: "calendar",
                    label: "This Week",
                    amount: entry.data.weeklyTotal,
                    color: .blue
                )

                // Monthly
                SpendingRow(
                    icon: "calendar.badge.clock",
                    label: "This Month",
                    amount: entry.data.monthlyTotal,
                    color: .purple
                )
            }

            Divider()

            // Right side - Quick stats
            VStack(alignment: .leading, spacing: 8) {
                Text("Receipts")
                    .font(.caption.bold())
                    .foregroundColor(.secondary)

                StatBadge(
                    icon: "checkmark.circle.fill",
                    count: entry.data.matchedReceipts,
                    label: "Matched",
                    color: .green
                )

                StatBadge(
                    icon: "clock.fill",
                    count: entry.data.pendingReceipts,
                    label: "Pending",
                    color: .orange
                )

                Spacer()

                // Quick scan button
                Link(destination: WidgetDeepLink.scan.url) {
                    HStack {
                        Image(systemName: "camera.fill")
                        Text("Scan")
                    }
                    .font(.caption.bold())
                    .foregroundColor(.black)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 6)
                    .background(Color.green)
                    .cornerRadius(8)
                }
            }
        }
        .padding()
    }
}

// MARK: - Large Widget View
struct LargeSpendingView: View {
    let entry: SpendingEntry

    var body: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                VStack(alignment: .leading) {
                    Text("Spending Summary")
                        .font(.headline)
                    Text(entry.data.lastUpdated.widgetTimeAgo)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
                Spacer()
                Link(destination: WidgetDeepLink.scan.url) {
                    Image(systemName: "camera.fill")
                        .font(.title2)
                        .foregroundColor(.green)
                }
            }

            // Spending cards
            HStack(spacing: 12) {
                SpendingCard(
                    title: "Today",
                    amount: entry.data.dailyTotal,
                    icon: "sun.max.fill",
                    color: .orange
                )
                SpendingCard(
                    title: "Week",
                    amount: entry.data.weeklyTotal,
                    icon: "calendar",
                    color: .blue
                )
                SpendingCard(
                    title: "Month",
                    amount: entry.data.monthlyTotal,
                    icon: "calendar.badge.clock",
                    color: .purple
                )
            }

            Divider()

            // Recent transactions
            VStack(alignment: .leading, spacing: 4) {
                Text("Recent Transactions")
                    .font(.caption.bold())
                    .foregroundColor(.secondary)

                ForEach(entry.data.recentTransactions.prefix(4)) { transaction in
                    Link(destination: WidgetDeepLink.transaction(id: transaction.index).url) {
                        TransactionRow(transaction: transaction)
                    }
                }
            }

            Spacer()

            // Footer with pending count
            if entry.data.pendingReceipts > 0 {
                Link(destination: WidgetDeepLink.inbox.url) {
                    HStack {
                        Image(systemName: "tray.fill")
                        Text("\(entry.data.pendingReceipts) receipts waiting in inbox")
                        Spacer()
                        Image(systemName: "chevron.right")
                    }
                    .font(.caption)
                    .foregroundColor(.orange)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color.orange.opacity(0.2))
                    .cornerRadius(8)
                }
            }
        }
        .padding()
    }
}

// MARK: - Lock Screen Widgets

struct CircularAccessoryView: View {
    let entry: SpendingEntry

    var body: some View {
        ZStack {
            AccessoryWidgetBackground()
            VStack(spacing: 2) {
                Image(systemName: "dollarsign.circle.fill")
                    .font(.title3)
                Text(entry.data.dailyTotal.shortCurrencyFormatted)
                    .font(.caption2.bold())
            }
        }
    }
}

struct RectangularAccessoryView: View {
    let entry: SpendingEntry

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Today's Spending")
                    .font(.caption2)
                    .foregroundColor(.secondary)
                Text(entry.data.dailyTotal.currencyFormatted)
                    .font(.headline)
            }
            Spacer()
            if entry.data.pendingReceipts > 0 {
                VStack {
                    Image(systemName: "doc.text.fill")
                    Text("\(entry.data.pendingReceipts)")
                        .font(.caption2)
                }
                .foregroundColor(.orange)
            }
        }
    }
}

struct InlineAccessoryView: View {
    let entry: SpendingEntry

    var body: some View {
        Label {
            Text("Today: \(entry.data.dailyTotal.currencyFormatted)")
        } icon: {
            Image(systemName: "chart.line.uptrend.xyaxis")
        }
    }
}

// MARK: - Helper Views

struct SpendingRow: View {
    let icon: String
    let label: String
    let amount: Double
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundColor(color)
                .frame(width: 20)
            VStack(alignment: .leading, spacing: 0) {
                Text(label)
                    .font(.caption)
                    .foregroundColor(.secondary)
                Text(amount.currencyFormatted)
                    .font(.subheadline.bold())
            }
        }
    }
}

struct SpendingCard: View {
    let title: String
    let amount: Double
    let icon: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .foregroundColor(color)
            Text(title)
                .font(.caption2)
                .foregroundColor(.secondary)
            Text(amount.shortCurrencyFormatted)
                .font(.subheadline.bold())
                .minimumScaleFactor(0.7)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 8)
        .background(Color(UIColor.secondarySystemBackground))
        .cornerRadius(8)
    }
}

struct StatBadge: View {
    let icon: String
    let count: Int
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .foregroundColor(color)
                .font(.caption)
            Text("\(count)")
                .font(.caption.bold())
            Text(label)
                .font(.caption2)
                .foregroundColor(.secondary)
        }
    }
}

struct TransactionRow: View {
    let transaction: WidgetTransaction

    var body: some View {
        HStack {
            Circle()
                .fill(transaction.hasReceipt ? Color.green : Color.orange)
                .frame(width: 6, height: 6)
            Text(transaction.shortMerchant)
                .font(.caption)
                .lineLimit(1)
            Spacer()
            Text(transaction.formattedAmount)
                .font(.caption.bold())
                .foregroundColor(transaction.amount < 0 ? .primary : .green)
        }
        .padding(.vertical, 2)
    }
}

// MARK: - Widget Definition
struct SpendingWidget: Widget {
    let kind: String = "SpendingWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: SpendingWidgetProvider()) { entry in
            SpendingWidgetEntryView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Spending Summary")
        .description("Track your daily, weekly, and monthly spending at a glance.")
        .supportedFamilies([
            .systemSmall,
            .systemMedium,
            .systemLarge,
            .accessoryCircular,
            .accessoryRectangular,
            .accessoryInline
        ])
    }
}

// MARK: - Preview
#Preview(as: .systemSmall) {
    SpendingWidget()
} timeline: {
    SpendingEntry.placeholder
}

#Preview(as: .systemMedium) {
    SpendingWidget()
} timeline: {
    SpendingEntry.placeholder
}

#Preview(as: .systemLarge) {
    SpendingWidget()
} timeline: {
    SpendingEntry.placeholder
}

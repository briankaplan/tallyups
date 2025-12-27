import WidgetKit
import SwiftUI

// MARK: - Quick Scan Widget Provider
struct QuickScanWidgetProvider: TimelineProvider {
    typealias Entry = QuickScanEntry

    func placeholder(in context: Context) -> QuickScanEntry {
        .placeholder
    }

    func getSnapshot(in context: Context, completion: @escaping (QuickScanEntry) -> Void) {
        let dataStore = WidgetDataStore.shared
        let entry = QuickScanEntry(
            date: Date(),
            pendingCount: dataStore.loadPendingCount(),
            isAuthenticated: dataStore.isAuthenticated
        )
        completion(entry)
    }

    func getTimeline(in context: Context, completion: @escaping (Timeline<QuickScanEntry>) -> Void) {
        let dataStore = WidgetDataStore.shared
        let entry = QuickScanEntry(
            date: Date(),
            pendingCount: dataStore.loadPendingCount(),
            isAuthenticated: dataStore.isAuthenticated
        )

        // Refresh every hour
        let nextUpdate = Calendar.current.date(byAdding: .hour, value: 1, to: Date())!
        let timeline = Timeline(entries: [entry], policy: .after(nextUpdate))
        completion(timeline)
    }
}

// MARK: - Quick Scan Widget View
struct QuickScanWidgetEntryView: View {
    var entry: QuickScanEntry
    @Environment(\.widgetFamily) var family

    var body: some View {
        switch family {
        case .systemSmall:
            SmallQuickScanView(entry: entry)
        case .systemMedium:
            MediumQuickScanView(entry: entry)
        case .accessoryCircular:
            CircularQuickScanView(entry: entry)
        case .accessoryRectangular:
            RectangularQuickScanView(entry: entry)
        @unknown default:
            SmallQuickScanView(entry: entry)
        }
    }
}

// MARK: - Small Quick Scan View
struct SmallQuickScanView: View {
    let entry: QuickScanEntry

    var body: some View {
        Link(destination: WidgetDeepLink.scan.url) {
            ZStack {
                // Gradient background
                LinearGradient(
                    colors: [
                        Color(red: 0, green: 0.8, blue: 0.4),
                        Color(red: 0, green: 1, blue: 0.53)
                    ],
                    startPoint: .topLeading,
                    endPoint: .bottomTrailing
                )

                VStack(spacing: 12) {
                    // Camera icon with animation hint
                    ZStack {
                        Circle()
                            .fill(.white.opacity(0.2))
                            .frame(width: 60, height: 60)

                        Image(systemName: "camera.fill")
                            .font(.system(size: 28))
                            .foregroundColor(.white)
                    }

                    Text("Scan Receipt")
                        .font(.headline)
                        .foregroundColor(.white)

                    // Pending indicator
                    if entry.pendingCount > 0 {
                        HStack(spacing: 4) {
                            Image(systemName: "tray.fill")
                                .font(.caption2)
                            Text("\(entry.pendingCount) in inbox")
                                .font(.caption2)
                        }
                        .foregroundColor(.white.opacity(0.8))
                    }
                }
            }
        }
    }
}

// MARK: - Medium Quick Scan View
struct MediumQuickScanView: View {
    let entry: QuickScanEntry

    var body: some View {
        HStack(spacing: 16) {
            // Quick Scan Button
            Link(destination: WidgetDeepLink.scan.url) {
                VStack(spacing: 8) {
                    ZStack {
                        Circle()
                            .fill(
                                LinearGradient(
                                    colors: [
                                        Color(red: 0, green: 0.8, blue: 0.4),
                                        Color(red: 0, green: 1, blue: 0.53)
                                    ],
                                    startPoint: .top,
                                    endPoint: .bottom
                                )
                            )
                            .frame(width: 60, height: 60)

                        Image(systemName: "camera.fill")
                            .font(.title2)
                            .foregroundColor(.white)
                    }

                    Text("Scan")
                        .font(.caption.bold())
                        .foregroundColor(.primary)
                }
            }

            Divider()

            // Stats and quick actions
            VStack(alignment: .leading, spacing: 12) {
                // Inbox status
                Link(destination: WidgetDeepLink.inbox.url) {
                    HStack {
                        Image(systemName: "tray.fill")
                            .foregroundColor(entry.pendingCount > 0 ? .orange : .secondary)
                        VStack(alignment: .leading, spacing: 0) {
                            Text("\(entry.pendingCount)")
                                .font(.headline)
                            Text("Pending")
                                .font(.caption2)
                                .foregroundColor(.secondary)
                        }
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }

                Divider()

                // Dashboard link
                Link(destination: WidgetDeepLink.dashboard.url) {
                    HStack {
                        Image(systemName: "chart.line.uptrend.xyaxis")
                            .foregroundColor(.blue)
                        Text("Dashboard")
                            .font(.caption)
                        Spacer()
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    }
                }
            }
        }
        .padding()
    }
}

// MARK: - Lock Screen Widgets

struct CircularQuickScanView: View {
    let entry: QuickScanEntry

    var body: some View {
        ZStack {
            AccessoryWidgetBackground()
            VStack(spacing: 2) {
                Image(systemName: "camera.fill")
                    .font(.title2)
                if entry.pendingCount > 0 {
                    Text("\(entry.pendingCount)")
                        .font(.caption2.bold())
                        .foregroundColor(.orange)
                }
            }
        }
        .widgetURL(WidgetDeepLink.scan.url)
    }
}

struct RectangularQuickScanView: View {
    let entry: QuickScanEntry

    var body: some View {
        HStack {
            Image(systemName: "camera.fill")
                .font(.title2)
            VStack(alignment: .leading, spacing: 2) {
                Text("Quick Scan")
                    .font(.headline)
                if entry.pendingCount > 0 {
                    Text("\(entry.pendingCount) pending receipts")
                        .font(.caption2)
                        .foregroundColor(.orange)
                } else {
                    Text("Tap to capture")
                        .font(.caption2)
                        .foregroundColor(.secondary)
                }
            }
            Spacer()
        }
        .widgetURL(WidgetDeepLink.scan.url)
    }
}

// MARK: - Widget Definition
struct QuickScanWidget: Widget {
    let kind: String = "QuickScanWidget"

    var body: some WidgetConfiguration {
        StaticConfiguration(kind: kind, provider: QuickScanWidgetProvider()) { entry in
            QuickScanWidgetEntryView(entry: entry)
                .containerBackground(.fill.tertiary, for: .widget)
        }
        .configurationDisplayName("Quick Scan")
        .description("Instantly scan receipts with one tap.")
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
    QuickScanWidget()
} timeline: {
    QuickScanEntry.placeholder
    QuickScanEntry(date: Date(), pendingCount: 0, isAuthenticated: true)
}

#Preview(as: .systemMedium) {
    QuickScanWidget()
} timeline: {
    QuickScanEntry.placeholder
}

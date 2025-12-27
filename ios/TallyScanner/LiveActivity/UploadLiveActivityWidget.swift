import ActivityKit
import SwiftUI
import WidgetKit

/// Live Activity Widget for upload progress
@available(iOS 16.2, *)
struct UploadLiveActivityWidget: Widget {
    var body: some WidgetConfiguration {
        ActivityConfiguration(for: UploadActivityAttributes.self) { context in
            // Lock Screen / Banner view
            LockScreenLiveActivityView(context: context)
        } dynamicIsland: { context in
            // Dynamic Island views
            DynamicIsland {
                // Expanded view
                DynamicIslandExpandedRegion(.leading) {
                    HStack {
                        Image(systemName: "doc.text.viewfinder")
                            .foregroundColor(.green)
                        Text("\(context.state.completedReceipts)/\(context.state.totalReceipts)")
                            .font(.caption.bold())
                    }
                }

                DynamicIslandExpandedRegion(.trailing) {
                    Text("\(context.state.progressPercentage)%")
                        .font(.caption.bold())
                        .foregroundColor(.green)
                }

                DynamicIslandExpandedRegion(.center) {
                    VStack(spacing: 4) {
                        if let merchant = context.state.currentMerchant {
                            Text(merchant)
                                .font(.caption2)
                                .lineLimit(1)
                        }
                        ProgressView(value: context.state.progress)
                            .progressViewStyle(.linear)
                            .tint(.green)
                    }
                }

                DynamicIslandExpandedRegion(.bottom) {
                    Text(context.state.statusText)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }
            } compactLeading: {
                // Compact leading
                Image(systemName: uploadIcon(for: context.state.status))
                    .foregroundColor(uploadColor(for: context.state.status))
            } compactTrailing: {
                // Compact trailing
                Text("\(context.state.progressPercentage)%")
                    .font(.caption.bold())
                    .foregroundColor(.green)
            } minimal: {
                // Minimal (when competing with other activities)
                Image(systemName: "doc.text.viewfinder")
                    .foregroundColor(.green)
            }
        }
    }

    private func uploadIcon(for status: UploadActivityAttributes.ContentState.UploadStatus) -> String {
        switch status {
        case .preparing: return "doc.text"
        case .uploading: return "arrow.up.circle"
        case .processing: return "gearshape"
        case .completed: return "checkmark.circle.fill"
        case .failed: return "xmark.circle.fill"
        }
    }

    private func uploadColor(for status: UploadActivityAttributes.ContentState.UploadStatus) -> Color {
        switch status {
        case .preparing: return .orange
        case .uploading: return .blue
        case .processing: return .purple
        case .completed: return .green
        case .failed: return .red
        }
    }
}

/// Lock Screen Live Activity View
@available(iOS 16.2, *)
struct LockScreenLiveActivityView: View {
    let context: ActivityViewContext<UploadActivityAttributes>

    var body: some View {
        VStack(spacing: 12) {
            // Header
            HStack {
                Image(systemName: "doc.text.viewfinder")
                    .font(.title3)
                    .foregroundColor(.green)

                VStack(alignment: .leading, spacing: 2) {
                    Text("Uploading Receipts")
                        .font(.headline)
                    Text(context.state.statusText)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                Spacer()

                // Count badge
                Text("\(context.state.completedReceipts)/\(context.state.totalReceipts)")
                    .font(.subheadline.bold())
                    .padding(.horizontal, 10)
                    .padding(.vertical, 4)
                    .background(Color.green.opacity(0.2))
                    .cornerRadius(8)
            }

            // Progress bar
            VStack(alignment: .leading, spacing: 4) {
                ProgressView(value: context.state.progress)
                    .progressViewStyle(.linear)
                    .tint(progressColor)

                HStack {
                    if let merchant = context.state.currentMerchant {
                        Text(merchant)
                            .font(.caption)
                            .foregroundColor(.secondary)
                            .lineLimit(1)
                    }

                    Spacer()

                    Text("\(context.state.progressPercentage)%")
                        .font(.caption.bold())
                        .foregroundColor(progressColor)
                }
            }

            // Time remaining (if available)
            if let remaining = context.state.estimatedTimeRemaining, remaining > 0 {
                Text("~\(formatTime(remaining)) remaining")
                    .font(.caption2)
                    .foregroundColor(.secondary)
            }
        }
        .padding()
        .background(Color(UIColor.secondarySystemBackground))
    }

    private var progressColor: Color {
        switch context.state.status {
        case .preparing: return .orange
        case .uploading: return .blue
        case .processing: return .purple
        case .completed: return .green
        case .failed: return .red
        }
    }

    private func formatTime(_ seconds: Int) -> String {
        if seconds < 60 {
            return "\(seconds)s"
        } else {
            let minutes = seconds / 60
            return "\(minutes)m"
        }
    }
}

// MARK: - Preview

@available(iOS 16.2, *)
#Preview("Upload Activity", as: .content, using: UploadActivityAttributes(
    sessionId: "preview",
    startTime: Date()
)) {
    UploadLiveActivityWidget()
} contentStates: {
    UploadActivityAttributes.ContentState(
        progress: 0.45,
        totalReceipts: 5,
        completedReceipts: 2,
        currentMerchant: "Starbucks Coffee",
        status: .uploading,
        estimatedTimeRemaining: 30
    )
    UploadActivityAttributes.ContentState(
        progress: 1.0,
        totalReceipts: 5,
        completedReceipts: 5,
        currentMerchant: nil,
        status: .completed,
        estimatedTimeRemaining: nil
    )
}

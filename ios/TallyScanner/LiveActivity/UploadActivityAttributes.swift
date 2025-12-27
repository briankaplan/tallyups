import ActivityKit
import Foundation
import SwiftUI

/// Attributes for the receipt upload Live Activity
struct UploadActivityAttributes: ActivityAttributes {
    public struct ContentState: Codable, Hashable {
        /// Current upload progress (0.0 to 1.0)
        var progress: Double

        /// Number of receipts being uploaded
        var totalReceipts: Int

        /// Number of completed uploads
        var completedReceipts: Int

        /// Current receipt merchant name (if available)
        var currentMerchant: String?

        /// Upload status
        var status: UploadStatus

        /// Estimated time remaining (seconds)
        var estimatedTimeRemaining: Int?

        enum UploadStatus: String, Codable, Hashable {
            case preparing
            case uploading
            case processing
            case completed
            case failed
        }

        var statusText: String {
            switch status {
            case .preparing: return "Preparing..."
            case .uploading: return "Uploading..."
            case .processing: return "Processing..."
            case .completed: return "Complete!"
            case .failed: return "Failed"
            }
        }

        var progressPercentage: Int {
            Int(progress * 100)
        }
    }

    /// Session ID for this upload batch
    var sessionId: String

    /// Start time
    var startTime: Date
}

// MARK: - Live Activity Manager

@available(iOS 16.2, *)
@MainActor
class UploadLiveActivityManager: ObservableObject {
    static let shared = UploadLiveActivityManager()

    private var currentActivity: Activity<UploadActivityAttributes>?

    private init() {}

    /// Start a new upload Live Activity
    func startUploadActivity(totalReceipts: Int) async {
        // Check if Live Activities are enabled
        guard ActivityAuthorizationInfo().areActivitiesEnabled else {
            print("Live Activities not enabled")
            return
        }

        // End any existing activity
        await endActivity()

        let attributes = UploadActivityAttributes(
            sessionId: UUID().uuidString,
            startTime: Date()
        )

        let initialState = UploadActivityAttributes.ContentState(
            progress: 0,
            totalReceipts: totalReceipts,
            completedReceipts: 0,
            currentMerchant: nil,
            status: .preparing,
            estimatedTimeRemaining: nil
        )

        do {
            let activity = try Activity.request(
                attributes: attributes,
                content: .init(state: initialState, staleDate: nil),
                pushType: nil
            )
            currentActivity = activity
            print("Started Live Activity: \(activity.id)")
        } catch {
            print("Failed to start Live Activity: \(error)")
        }
    }

    /// Update the upload progress
    func updateProgress(
        progress: Double,
        completedReceipts: Int,
        totalReceipts: Int,
        currentMerchant: String? = nil,
        estimatedTimeRemaining: Int? = nil
    ) async {
        guard let activity = currentActivity else { return }

        let state = UploadActivityAttributes.ContentState(
            progress: progress,
            totalReceipts: totalReceipts,
            completedReceipts: completedReceipts,
            currentMerchant: currentMerchant,
            status: .uploading,
            estimatedTimeRemaining: estimatedTimeRemaining
        )

        await activity.update(ActivityContent(state: state, staleDate: nil))
    }

    /// Mark as processing (after upload, during OCR)
    func markAsProcessing() async {
        guard let activity = currentActivity else { return }

        let currentState = activity.content.state
        let state = UploadActivityAttributes.ContentState(
            progress: 0.9,
            totalReceipts: currentState.totalReceipts,
            completedReceipts: currentState.completedReceipts,
            currentMerchant: nil,
            status: .processing,
            estimatedTimeRemaining: nil
        )

        await activity.update(ActivityContent(state: state, staleDate: nil))
    }

    /// Mark as completed
    func markAsCompleted(totalReceipts: Int) async {
        guard let activity = currentActivity else { return }

        let state = UploadActivityAttributes.ContentState(
            progress: 1.0,
            totalReceipts: totalReceipts,
            completedReceipts: totalReceipts,
            currentMerchant: nil,
            status: .completed,
            estimatedTimeRemaining: nil
        )

        await activity.update(ActivityContent(state: state, staleDate: nil))

        // End after a delay
        try? await Task.sleep(nanoseconds: 3_000_000_000) // 3 seconds
        await endActivity()
    }

    /// Mark as failed
    func markAsFailed() async {
        guard let activity = currentActivity else { return }

        let currentState = activity.content.state
        let state = UploadActivityAttributes.ContentState(
            progress: currentState.progress,
            totalReceipts: currentState.totalReceipts,
            completedReceipts: currentState.completedReceipts,
            currentMerchant: nil,
            status: .failed,
            estimatedTimeRemaining: nil
        )

        await activity.update(ActivityContent(state: state, staleDate: nil))

        // End after a delay
        try? await Task.sleep(nanoseconds: 5_000_000_000) // 5 seconds
        await endActivity()
    }

    /// End the current activity
    func endActivity() async {
        guard let activity = currentActivity else { return }

        await activity.end(nil, dismissalPolicy: .immediate)
        currentActivity = nil
        print("Ended Live Activity")
    }
}

import Foundation
import UIKit
import CoreHaptics

/// Service for providing haptic feedback throughout the app
@MainActor
class HapticService {
    static let shared = HapticService()

    private var engine: CHHapticEngine?
    private var supportsHaptics: Bool = false

    // Impact generators for different intensities
    private let lightImpact = UIImpactFeedbackGenerator(style: .light)
    private let mediumImpact = UIImpactFeedbackGenerator(style: .medium)
    private let heavyImpact = UIImpactFeedbackGenerator(style: .heavy)
    private let rigidImpact = UIImpactFeedbackGenerator(style: .rigid)
    private let softImpact = UIImpactFeedbackGenerator(style: .soft)

    // Notification generator for success/warning/error
    private let notificationFeedback = UINotificationFeedbackGenerator()

    // Selection generator for UI selections
    private let selectionFeedback = UISelectionFeedbackGenerator()

    private init() {
        setupHapticEngine()
        prepareGenerators()
    }

    private func setupHapticEngine() {
        supportsHaptics = CHHapticEngine.capabilitiesForHardware().supportsHaptics

        guard supportsHaptics else { return }

        do {
            engine = try CHHapticEngine()
            try engine?.start()

            // Restart engine on reset
            engine?.resetHandler = { [weak self] in
                do {
                    try self?.engine?.start()
                } catch {
                    print("Failed to restart haptic engine: \(error)")
                }
            }
        } catch {
            print("Failed to create haptic engine: \(error)")
        }
    }

    private func prepareGenerators() {
        lightImpact.prepare()
        mediumImpact.prepare()
        heavyImpact.prepare()
        notificationFeedback.prepare()
        selectionFeedback.prepare()
    }

    // MARK: - Basic Haptics

    /// Light tap for subtle interactions
    func lightTap() {
        lightImpact.impactOccurred()
    }

    /// Medium tap for button presses
    func mediumTap() {
        mediumImpact.impactOccurred()
    }

    /// Heavy tap for significant actions
    func heavyTap() {
        heavyImpact.impactOccurred()
    }

    /// Rigid tap for firm confirmations
    func rigidTap() {
        rigidImpact.impactOccurred()
    }

    /// Soft tap for gentle feedback
    func softTap() {
        softImpact.impactOccurred()
    }

    /// Selection changed (for pickers, toggles)
    func selection() {
        selectionFeedback.selectionChanged()
    }

    // MARK: - Semantic Haptics

    /// Success feedback - for completed actions
    func success() {
        notificationFeedback.notificationOccurred(.success)
    }

    /// Warning feedback - for attention needed
    func warning() {
        notificationFeedback.notificationOccurred(.warning)
    }

    /// Error feedback - for failures
    func error() {
        notificationFeedback.notificationOccurred(.error)
    }

    /// Notification haptic feedback with type
    func notification(_ type: UINotificationFeedbackGenerator.FeedbackType) {
        notificationFeedback.notificationOccurred(type)
    }

    /// Impact haptic feedback with style
    func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle) {
        switch style {
        case .light:
            lightImpact.impactOccurred()
        case .medium:
            mediumImpact.impactOccurred()
        case .heavy:
            heavyImpact.impactOccurred()
        case .rigid:
            rigidImpact.impactOccurred()
        case .soft:
            softImpact.impactOccurred()
        @unknown default:
            mediumImpact.impactOccurred()
        }
    }

    // MARK: - Receipt-Specific Haptics

    /// Shutter click when capturing receipt photo
    func shutterClick() {
        rigidImpact.impactOccurred(intensity: 0.7)

        // Double tap for authentic camera feel
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) { [weak self] in
            self?.lightImpact.impactOccurred(intensity: 0.4)
        }
    }

    /// Receipt scanned successfully
    func scanSuccess() {
        // Triple pulse for celebration
        heavyImpact.impactOccurred(intensity: 1.0)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.1) { [weak self] in
            self?.mediumImpact.impactOccurred(intensity: 0.8)
        }

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.2) { [weak self] in
            self?.lightImpact.impactOccurred(intensity: 0.5)
        }
    }

    /// Receipt matched to transaction
    func matchSuccess() {
        // Satisfying double tap
        notificationFeedback.notificationOccurred(.success)

        DispatchQueue.main.asyncAfter(deadline: .now() + 0.15) { [weak self] in
            self?.mediumImpact.impactOccurred()
        }
    }

    /// Swipe action completed
    func swipeComplete() {
        mediumImpact.impactOccurred(intensity: 0.6)
    }

    /// Upload complete
    func uploadComplete() {
        success()
    }

    /// Batch of items synced
    func batchSyncComplete(count: Int) {
        guard count > 0 else { return }

        // Number of pulses based on quantity (max 5)
        let pulseCount = min(count, 5)

        for i in 0..<pulseCount {
            DispatchQueue.main.asyncAfter(deadline: .now() + Double(i) * 0.08) { [weak self] in
                self?.lightImpact.impactOccurred(intensity: 0.5 + Double(i) * 0.1)
            }
        }

        // Final success pulse
        DispatchQueue.main.asyncAfter(deadline: .now() + Double(pulseCount) * 0.08 + 0.1) { [weak self] in
            self?.notificationFeedback.notificationOccurred(.success)
        }
    }

    /// Tab selection
    func tabSwitch() {
        lightImpact.impactOccurred(intensity: 0.4)
    }

    /// Pull to refresh activated
    func pullToRefresh() {
        mediumImpact.impactOccurred(intensity: 0.5)
    }

    /// Button pressed
    func buttonPress() {
        lightImpact.impactOccurred(intensity: 0.5)
    }

    /// Card tapped
    func cardTap() {
        softImpact.impactOccurred(intensity: 0.4)
    }

    /// Long press triggered
    func longPress() {
        heavyImpact.impactOccurred(intensity: 0.8)
    }

    /// Milestone reached (e.g., 100 receipts scanned)
    func milestoneReached() {
        playMilestonePattern()
    }

    // MARK: - Custom Patterns (CoreHaptics)

    private func playMilestonePattern() {
        guard supportsHaptics, let engine = engine else {
            // Fallback to basic haptics
            success()
            return
        }

        do {
            // Create a celebration pattern
            var events: [CHHapticEvent] = []

            // Rising intensity
            for i in 0..<5 {
                let intensity = CHHapticEventParameter(parameterID: .hapticIntensity, value: Float(i) * 0.2 + 0.2)
                let sharpness = CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.3 + Float(i) * 0.1)

                let event = CHHapticEvent(
                    eventType: .hapticTransient,
                    parameters: [intensity, sharpness],
                    relativeTime: TimeInterval(i) * 0.08
                )
                events.append(event)
            }

            // Final big tap
            let finalIntensity = CHHapticEventParameter(parameterID: .hapticIntensity, value: 1.0)
            let finalSharpness = CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.8)
            let finalEvent = CHHapticEvent(
                eventType: .hapticTransient,
                parameters: [finalIntensity, finalSharpness],
                relativeTime: 0.5
            )
            events.append(finalEvent)

            let pattern = try CHHapticPattern(events: events, parameters: [])
            let player = try engine.makePlayer(with: pattern)
            try player.start(atTime: 0)

        } catch {
            // Fallback
            success()
        }
    }

    /// Play custom "receipt capture" pattern
    func playCapturePattern() {
        guard supportsHaptics, let engine = engine else {
            shutterClick()
            return
        }

        do {
            var events: [CHHapticEvent] = []

            // Shutter open
            let openIntensity = CHHapticEventParameter(parameterID: .hapticIntensity, value: 0.8)
            let openSharpness = CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.9)
            let openEvent = CHHapticEvent(
                eventType: .hapticTransient,
                parameters: [openIntensity, openSharpness],
                relativeTime: 0
            )
            events.append(openEvent)

            // Shutter close
            let closeIntensity = CHHapticEventParameter(parameterID: .hapticIntensity, value: 0.5)
            let closeSharpness = CHHapticEventParameter(parameterID: .hapticSharpness, value: 0.7)
            let closeEvent = CHHapticEvent(
                eventType: .hapticTransient,
                parameters: [closeIntensity, closeSharpness],
                relativeTime: 0.06
            )
            events.append(closeEvent)

            let pattern = try CHHapticPattern(events: events, parameters: [])
            let player = try engine.makePlayer(with: pattern)
            try player.start(atTime: 0)

        } catch {
            shutterClick()
        }
    }
}

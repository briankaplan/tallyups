import SwiftUI
import Combine

// MARK: - Tutorial Step

struct TutorialStep: Identifiable, Equatable {
    let id = UUID()
    let title: String
    let description: String
    let icon: String
    let targetElementId: String?
    let highlightShape: HighlightShape
    let position: TipPosition
    let action: TutorialAction?

    enum HighlightShape {
        case circle
        case rectangle
        case roundedRectangle(cornerRadius: CGFloat)
        case capsule
    }

    enum TipPosition {
        case above
        case below
        case leading
        case trailing
        case center
    }

    struct TutorialAction {
        let label: String
        let systemImage: String?
    }

    static func == (lhs: TutorialStep, rhs: TutorialStep) -> Bool {
        lhs.id == rhs.id
    }
}

// MARK: - Feature Tutorial

struct FeatureTutorial: Identifiable {
    let id: String
    let name: String
    let icon: String
    let steps: [TutorialStep]
    let completionMessage: String
}

// MARK: - Tutorial Service

@MainActor
class TutorialService: ObservableObject {
    static let shared = TutorialService()

    // MARK: - Published State

    @Published var activeTutorial: FeatureTutorial?
    @Published var currentStepIndex: Int = 0
    @Published var isShowingTutorial: Bool = false
    @Published var completedTutorials: Set<String> = []

    // MARK: - Feature Tutorial Completion Keys

    private let completedTutorialsKey = "completed_feature_tutorials"
    private let tutorialVersionKey = "tutorial_version"
    private let currentVersion = 1

    // MARK: - Available Tutorials

    let scannerTutorial = FeatureTutorial(
        id: "scanner",
        name: "Scanner Tutorial",
        icon: "camera.viewfinder",
        steps: [
            TutorialStep(
                title: "Point at Your Receipt",
                description: "Position your camera so the entire receipt is visible. The blue border shows the detected edges.",
                icon: "viewfinder",
                targetElementId: "camera-preview",
                highlightShape: .roundedRectangle(cornerRadius: 16),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Quality Score",
                description: "Watch the quality indicator at the top-left. Green means excellent quality for best text recognition.",
                icon: "checkmark.circle.fill",
                targetElementId: "quality-overlay",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Glare Detection",
                description: "If there's glare on your receipt, you'll see a warning. Tilt the receipt slightly to reduce reflections.",
                icon: "light.max",
                targetElementId: "glare-warning",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Tap to Focus",
                description: "Tap anywhere on the receipt to focus on that area. This helps with blurry images.",
                icon: "camera.metering.spot",
                targetElementId: "camera-preview",
                highlightShape: .circle,
                position: .center,
                action: TutorialStep.TutorialAction(label: "Tap to Focus", systemImage: "hand.tap")
            ),
            TutorialStep(
                title: "Capture Button",
                description: "When the quality looks good, tap the capture button. For multiple receipts, enable batch mode.",
                icon: "camera.circle.fill",
                targetElementId: "capture-button",
                highlightShape: .circle,
                position: .above,
                action: TutorialStep.TutorialAction(label: "Capture", systemImage: "camera.fill")
            ),
            TutorialStep(
                title: "Batch Mode",
                description: "Toggle batch mode to scan multiple receipts in a row. Great for catching up on receipts!",
                icon: "square.stack.3d.up.fill",
                targetElementId: "batch-toggle",
                highlightShape: .circle,
                position: .below,
                action: nil
            )
        ],
        completionMessage: "You're ready to scan! Remember: good lighting and steady hands make the best scans."
    )

    let transactionsTutorial = FeatureTutorial(
        id: "transactions",
        name: "Transactions Tutorial",
        icon: "creditcard.fill",
        steps: [
            TutorialStep(
                title: "Your Charges",
                description: "This shows all charges from your connected bank accounts. Swipe down to refresh.",
                icon: "list.bullet.rectangle",
                targetElementId: "transactions-list",
                highlightShape: .roundedRectangle(cornerRadius: 0),
                position: .center,
                action: nil
            ),
            TutorialStep(
                title: "Filter by Business",
                description: "Tap these pills to filter by business type. Great for separating personal and work expenses.",
                icon: "line.3.horizontal.decrease",
                targetElementId: "business-filter",
                highlightShape: .capsule,
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Card Filter",
                description: "Filter by specific cards or accounts. Helpful when reconciling statements.",
                icon: "creditcard",
                targetElementId: "card-filter",
                highlightShape: .capsule,
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Batch Selection",
                description: "Tap the checkmark to enter batch mode. Select multiple transactions to reassign business type or category at once.",
                icon: "checkmark.circle",
                targetElementId: "batch-button",
                highlightShape: .circle,
                position: .below,
                action: TutorialStep.TutorialAction(label: "Enable Batch Mode", systemImage: "checkmark.circle")
            ),
            TutorialStep(
                title: "Search",
                description: "Search by merchant name, amount, or category to quickly find specific transactions.",
                icon: "magnifyingglass",
                targetElementId: "search-bar",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Transaction Details",
                description: "Tap any transaction to see details, attach receipts, or change the category.",
                icon: "doc.text.magnifyingglass",
                targetElementId: "transaction-row",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .center,
                action: TutorialStep.TutorialAction(label: "View Details", systemImage: "chevron.right")
            )
        ],
        completionMessage: "You're all set to manage your transactions! Matching receipts helps with expense reports."
    )

    let libraryTutorial = FeatureTutorial(
        id: "library",
        name: "Library Tutorial",
        icon: "photo.on.rectangle",
        steps: [
            TutorialStep(
                title: "Your Receipt Library",
                description: "All your scanned and imported receipts live here. Search, filter, and organize them.",
                icon: "photo.stack",
                targetElementId: "library-list",
                highlightShape: .roundedRectangle(cornerRadius: 0),
                position: .center,
                action: nil
            ),
            TutorialStep(
                title: "Quick Stats",
                description: "See your totals at a glance - matched, unmatched, and total amounts.",
                icon: "chart.bar.fill",
                targetElementId: "stats-bar",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Search Receipts",
                description: "Search by merchant, amount, or date. Our OCR makes all receipt text searchable!",
                icon: "magnifyingglass",
                targetElementId: "search-bar",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Filters",
                description: "Use filters to narrow down by status, business type, or date range.",
                icon: "line.3.horizontal.decrease.circle",
                targetElementId: "filter-button",
                highlightShape: .circle,
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Scan History",
                description: "Switch to Scan History to see all your scanning sessions and when receipts were captured.",
                icon: "clock.arrow.circlepath",
                targetElementId: "scan-history-tab",
                highlightShape: .capsule,
                position: .below,
                action: nil
            )
        ],
        completionMessage: "Your library is ready! Tap any receipt to view details or match it to a transaction."
    )

    let inboxTutorial = FeatureTutorial(
        id: "inbox",
        name: "Inbox Tutorial",
        icon: "tray.full.fill",
        steps: [
            TutorialStep(
                title: "Unmatched Receipts",
                description: "These are receipts that haven't been matched to a bank transaction yet.",
                icon: "tray",
                targetElementId: "inbox-list",
                highlightShape: .roundedRectangle(cornerRadius: 0),
                position: .center,
                action: nil
            ),
            TutorialStep(
                title: "Filter by Source",
                description: "See where receipts came from - scanned, imported from email, or uploaded.",
                icon: "arrow.down.doc",
                targetElementId: "source-filter",
                highlightShape: .capsule,
                position: .below,
                action: nil
            ),
            TutorialStep(
                title: "Auto-Match",
                description: "Tap Auto-Match to let us find matching transactions automatically using merchant names and amounts.",
                icon: "link",
                targetElementId: "auto-match-button",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .below,
                action: TutorialStep.TutorialAction(label: "Auto-Match", systemImage: "link")
            ),
            TutorialStep(
                title: "Manual Match",
                description: "Tap any receipt to manually match it to a specific transaction.",
                icon: "hand.tap",
                targetElementId: "receipt-row",
                highlightShape: .roundedRectangle(cornerRadius: 12),
                position: .center,
                action: nil
            )
        ],
        completionMessage: "Check your inbox regularly to keep receipts matched!"
    )

    // MARK: - Initialization

    private init() {
        loadCompletedTutorials()
    }

    // MARK: - Tutorial Management

    var currentStep: TutorialStep? {
        guard let tutorial = activeTutorial,
              currentStepIndex < tutorial.steps.count else {
            return nil
        }
        return tutorial.steps[currentStepIndex]
    }

    var progress: Double {
        guard let tutorial = activeTutorial, !tutorial.steps.isEmpty else {
            return 0
        }
        return Double(currentStepIndex + 1) / Double(tutorial.steps.count)
    }

    var isLastStep: Bool {
        guard let tutorial = activeTutorial else { return false }
        return currentStepIndex >= tutorial.steps.count - 1
    }

    func startTutorial(_ tutorial: FeatureTutorial) {
        activeTutorial = tutorial
        currentStepIndex = 0
        isShowingTutorial = true
        HapticService.shared.lightTap()
    }

    func nextStep() {
        guard let tutorial = activeTutorial else { return }

        if currentStepIndex < tutorial.steps.count - 1 {
            currentStepIndex += 1
            HapticService.shared.lightTap()
        } else {
            completeTutorial()
        }
    }

    func previousStep() {
        if currentStepIndex > 0 {
            currentStepIndex -= 1
            HapticService.shared.lightTap()
        }
    }

    func skipTutorial() {
        guard let tutorial = activeTutorial else { return }
        markTutorialComplete(tutorial.id)
        dismissTutorial()
    }

    func completeTutorial() {
        guard let tutorial = activeTutorial else { return }
        markTutorialComplete(tutorial.id)
        HapticService.shared.success()
        dismissTutorial()
    }

    func dismissTutorial() {
        isShowingTutorial = false
        activeTutorial = nil
        currentStepIndex = 0
    }

    // MARK: - Completion Tracking

    func isTutorialCompleted(_ tutorialId: String) -> Bool {
        completedTutorials.contains(tutorialId)
    }

    func shouldShowTutorial(for feature: String) -> Bool {
        !completedTutorials.contains(feature)
    }

    private func markTutorialComplete(_ tutorialId: String) {
        completedTutorials.insert(tutorialId)
        saveCompletedTutorials()
    }

    func resetTutorial(_ tutorialId: String) {
        completedTutorials.remove(tutorialId)
        saveCompletedTutorials()
    }

    func resetAllTutorials() {
        completedTutorials.removeAll()
        saveCompletedTutorials()
    }

    // MARK: - Persistence

    private func loadCompletedTutorials() {
        let savedVersion = UserDefaults.standard.integer(forKey: tutorialVersionKey)

        // Reset if version changed
        if savedVersion < currentVersion {
            UserDefaults.standard.set(currentVersion, forKey: tutorialVersionKey)
            completedTutorials = []
            return
        }

        if let data = UserDefaults.standard.data(forKey: completedTutorialsKey),
           let tutorials = try? JSONDecoder().decode(Set<String>.self, from: data) {
            completedTutorials = tutorials
        }
    }

    private func saveCompletedTutorials() {
        if let data = try? JSONEncoder().encode(completedTutorials) {
            UserDefaults.standard.set(data, forKey: completedTutorialsKey)
        }
    }

    // MARK: - Available Tutorials List

    var allTutorials: [FeatureTutorial] {
        [scannerTutorial, transactionsTutorial, libraryTutorial, inboxTutorial]
    }
}

// MARK: - Tutorial Overlay View

struct TutorialOverlayView: View {
    @ObservedObject var tutorialService: TutorialService
    let elementFrames: [String: CGRect]

    var body: some View {
        if tutorialService.isShowingTutorial,
           let step = tutorialService.currentStep {
            ZStack {
                // Dimmed background
                Color.black.opacity(0.7)
                    .ignoresSafeArea()
                    .onTapGesture {
                        // Prevent accidental dismissal
                    }

                // Spotlight cutout (if we have a target)
                if let targetId = step.targetElementId,
                   let frame = elementFrames[targetId] {
                    SpotlightView(frame: frame, shape: step.highlightShape)
                }

                // Tutorial card
                VStack {
                    if step.position == .below || step.position == .center {
                        Spacer()
                    }

                    TutorialCardView(
                        step: step,
                        progress: tutorialService.progress,
                        isLastStep: tutorialService.isLastStep,
                        onNext: { tutorialService.nextStep() },
                        onPrevious: { tutorialService.previousStep() },
                        onSkip: { tutorialService.skipTutorial() }
                    )
                    .padding(.horizontal, 20)

                    if step.position == .above || step.position == .center {
                        Spacer()
                    }
                }
            }
            .transition(.opacity)
            .animation(.easeInOut(duration: 0.3), value: tutorialService.currentStepIndex)
        }
    }
}

// MARK: - Spotlight View

struct SpotlightView: View {
    let frame: CGRect
    let shape: TutorialStep.HighlightShape

    var body: some View {
        GeometryReader { geometry in
            Path { path in
                // Full screen rectangle
                path.addRect(geometry.frame(in: .global))

                // Cut out spotlight area
                let insetFrame = frame.insetBy(dx: -8, dy: -8)

                switch shape {
                case .circle:
                    let diameter = max(insetFrame.width, insetFrame.height)
                    let center = CGPoint(x: insetFrame.midX, y: insetFrame.midY)
                    path.addEllipse(in: CGRect(
                        x: center.x - diameter/2,
                        y: center.y - diameter/2,
                        width: diameter,
                        height: diameter
                    ))
                case .rectangle:
                    path.addRect(insetFrame)
                case .roundedRectangle(let cornerRadius):
                    path.addRoundedRect(in: insetFrame, cornerSize: CGSize(width: cornerRadius, height: cornerRadius))
                case .capsule:
                    path.addRoundedRect(in: insetFrame, cornerSize: CGSize(width: insetFrame.height/2, height: insetFrame.height/2))
                }
            }
            .fill(style: FillStyle(eoFill: true))
            .foregroundColor(.clear)
        }
        .compositingGroup()
        .luminanceToAlpha()
    }
}

// MARK: - Tutorial Card View

struct TutorialCardView: View {
    let step: TutorialStep
    let progress: Double
    let isLastStep: Bool
    let onNext: () -> Void
    let onPrevious: () -> Void
    let onSkip: () -> Void

    var body: some View {
        VStack(spacing: 20) {
            // Progress bar
            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.gray.opacity(0.3))
                        .frame(height: 4)

                    Capsule()
                        .fill(Color.tallyAccent)
                        .frame(width: geometry.size.width * progress, height: 4)
                }
            }
            .frame(height: 4)

            // Icon and title
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(Color.tallyAccent.opacity(0.2))
                        .frame(width: 48, height: 48)

                    Image(systemName: step.icon)
                        .font(.title2)
                        .foregroundColor(.tallyAccent)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(step.title)
                        .font(.headline)
                        .foregroundColor(.white)

                    Text(step.description)
                        .font(.subheadline)
                        .foregroundColor(.gray)
                        .fixedSize(horizontal: false, vertical: true)
                }

                Spacer()
            }

            // Action hint if applicable
            if let action = step.action {
                HStack {
                    if let systemImage = action.systemImage {
                        Image(systemName: systemImage)
                    }
                    Text(action.label)
                }
                .font(.caption.bold())
                .foregroundColor(.tallyAccent)
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(Color.tallyAccent.opacity(0.15))
                .cornerRadius(20)
            }

            // Navigation buttons
            HStack(spacing: 12) {
                // Skip button
                Button(action: onSkip) {
                    Text("Skip")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                }

                Spacer()

                // Previous button (if not first step)
                if progress > 0.2 {
                    Button(action: onPrevious) {
                        Image(systemName: "chevron.left")
                            .font(.headline)
                            .foregroundColor(.white)
                            .frame(width: 44, height: 44)
                            .background(Color.tallyCard)
                            .cornerRadius(12)
                    }
                }

                // Next/Done button
                Button(action: onNext) {
                    HStack(spacing: 8) {
                        Text(isLastStep ? "Got it!" : "Next")
                            .font(.headline.bold())

                        if !isLastStep {
                            Image(systemName: "chevron.right")
                                .font(.headline)
                        }
                    }
                    .foregroundColor(.black)
                    .padding(.horizontal, 24)
                    .padding(.vertical, 12)
                    .background(Color.tallyAccent)
                    .cornerRadius(12)
                }
            }
        }
        .padding(20)
        .background(Color.tallyCard)
        .cornerRadius(20)
        .shadow(color: .black.opacity(0.3), radius: 20, x: 0, y: 10)
    }
}

// MARK: - Tutorial Trigger Button

struct TutorialHelpButton: View {
    let tutorial: FeatureTutorial
    @ObservedObject var tutorialService: TutorialService

    var body: some View {
        Button(action: {
            tutorialService.startTutorial(tutorial)
        }) {
            Image(systemName: "questionmark.circle")
                .font(.title3)
                .foregroundColor(.tallyAccent)
        }
        .accessibilityLabel("Show \(tutorial.name)")
        .accessibilityHint("Opens a guided tutorial for this feature")
    }
}

// MARK: - Tutorials List View (for Settings)

struct TutorialsListView: View {
    @ObservedObject var tutorialService = TutorialService.shared
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ForEach(tutorialService.allTutorials) { tutorial in
                        TutorialListRow(
                            tutorial: tutorial,
                            isCompleted: tutorialService.isTutorialCompleted(tutorial.id),
                            onStart: {
                                dismiss()
                                DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                                    tutorialService.startTutorial(tutorial)
                                }
                            },
                            onReset: {
                                tutorialService.resetTutorial(tutorial.id)
                            }
                        )
                    }
                }
                .listRowBackground(Color.tallyCard)

                Section {
                    Button(action: {
                        tutorialService.resetAllTutorials()
                        HapticService.shared.success()
                    }) {
                        HStack {
                            Image(systemName: "arrow.counterclockwise")
                            Text("Reset All Tutorials")
                        }
                        .foregroundColor(.orange)
                    }
                }
                .listRowBackground(Color.tallyCard)
            }
            .listStyle(.insetGrouped)
            .scrollContentBackground(.hidden)
            .background(Color.tallyBackground)
            .navigationTitle("Tutorials")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Tutorial List Row

struct TutorialListRow: View {
    let tutorial: FeatureTutorial
    let isCompleted: Bool
    let onStart: () -> Void
    let onReset: () -> Void

    var body: some View {
        HStack(spacing: 16) {
            // Icon
            ZStack {
                Circle()
                    .fill(isCompleted ? Color.green.opacity(0.2) : Color.tallyAccent.opacity(0.2))
                    .frame(width: 44, height: 44)

                Image(systemName: isCompleted ? "checkmark.circle.fill" : tutorial.icon)
                    .font(.title3)
                    .foregroundColor(isCompleted ? .green : .tallyAccent)
            }

            // Info
            VStack(alignment: .leading, spacing: 4) {
                Text(tutorial.name)
                    .font(.headline)
                    .foregroundColor(.white)

                Text("\(tutorial.steps.count) steps")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Spacer()

            // Actions
            if isCompleted {
                Button(action: onReset) {
                    Text("Replay")
                        .font(.caption.bold())
                        .foregroundColor(.tallyAccent)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.tallyAccent.opacity(0.15))
                        .cornerRadius(8)
                }
            } else {
                Button(action: onStart) {
                    Text("Start")
                        .font(.caption.bold())
                        .foregroundColor(.black)
                        .padding(.horizontal, 12)
                        .padding(.vertical, 6)
                        .background(Color.tallyAccent)
                        .cornerRadius(8)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

// MARK: - View Extension for Tutorial Support

extension View {
    func tutorialHighlight(id: String, updateFrame: @escaping (CGRect) -> Void) -> some View {
        self.background(
            GeometryReader { geometry in
                Color.clear
                    .preference(key: TutorialFramePreferenceKey.self, value: [id: geometry.frame(in: .global)])
            }
        )
        .onPreferenceChange(TutorialFramePreferenceKey.self) { frames in
            if let frame = frames[id] {
                updateFrame(frame)
            }
        }
    }
}

struct TutorialFramePreferenceKey: PreferenceKey {
    static var defaultValue: [String: CGRect] = [:]

    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue()) { $1 }
    }
}

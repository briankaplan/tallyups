import SwiftUI
import AVFoundation
import Photos
import UserNotifications

// MARK: - Onboarding Step Data

struct OnboardingStep: Identifiable {
    let id = UUID()
    let icon: String
    let title: String
    let subtitle: String
    let description: String
    let tips: [String]
    let imageName: String?
    let backgroundColor: Color
}

// MARK: - Onboarding View

struct OnboardingView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) private var dismiss

    @State private var currentStep = 0
    @State private var cameraPermissionGranted = false
    @State private var photoLibraryPermissionGranted = false
    @State private var notificationPermissionGranted = false
    @State private var isCompletingOnboarding = false

    private let steps: [OnboardingStep] = [
        OnboardingStep(
            icon: "hand.wave.fill",
            title: "Welcome to TallyUps",
            subtitle: "Your Personal Receipt Manager",
            description: "Keep all your receipts organized in one place. No more lost receipts or messy folders!",
            tips: [
                "Snap photos of paper receipts",
                "Import receipts from email",
                "Match receipts to bank charges"
            ],
            imageName: nil,
            backgroundColor: Color.tallyAccent.opacity(0.15)
        ),
        OnboardingStep(
            icon: "camera.viewfinder",
            title: "Scan Your Receipts",
            subtitle: "It's Easy as 1-2-3",
            description: "Just point your camera at any receipt and tap the button. We'll do the rest!",
            tips: [
                "Hold your phone steady over the receipt",
                "Make sure there's good lighting",
                "The whole receipt should be visible"
            ],
            imageName: nil,
            backgroundColor: Color.blue.opacity(0.15)
        ),
        OnboardingStep(
            icon: "creditcard.fill",
            title: "Track Your Charges",
            subtitle: "See Where Your Money Goes",
            description: "Connect your bank to automatically import charges. We'll help you match receipts to each purchase.",
            tips: [
                "View all your credit card charges",
                "See which charges have receipts",
                "Never miss an expense report item"
            ],
            imageName: nil,
            backgroundColor: Color.green.opacity(0.15)
        ),
        OnboardingStep(
            icon: "folder.fill.badge.gearshape",
            title: "Stay Organized",
            subtitle: "Tips for Managing Expenses",
            description: "A few simple habits will keep your receipts perfectly organized.",
            tips: [
                "Scan receipts right after you shop",
                "Check the Inbox for unmatched items",
                "Use projects to group related expenses"
            ],
            imageName: nil,
            backgroundColor: Color.purple.opacity(0.15)
        ),
        OnboardingStep(
            icon: "checkmark.seal.fill",
            title: "You're All Set!",
            subtitle: "Let's Get Started",
            description: "You're ready to start scanning. We just need a couple of permissions first.",
            tips: [
                "Camera access to scan receipts",
                "Photo library to import images",
                "Notifications for updates (optional)"
            ],
            imageName: nil,
            backgroundColor: Color.tallyAccent.opacity(0.15)
        )
    ]

    private var totalSteps: Int { steps.count }

    var body: some View {
        ZStack {
            // Background
            Color.tallyBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                // Header with progress and skip
                headerView
                    .padding(.top, 8)

                // Main content
                TabView(selection: $currentStep) {
                    ForEach(Array(steps.enumerated()), id: \.element.id) { index, step in
                        if index < steps.count - 1 {
                            TutorialStepView(step: step)
                                .tag(index)
                        } else {
                            permissionsStep
                                .tag(index)
                        }
                    }
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .animation(.easeInOut(duration: 0.3), value: currentStep)

                // Navigation buttons
                navigationButtons
                    .padding(.horizontal, 24)
                    .padding(.bottom, 40)
            }
        }
    }

    // MARK: - Header View

    private var headerView: some View {
        VStack(spacing: 16) {
            // Skip button (top right)
            HStack {
                Spacer()

                if currentStep < totalSteps - 1 {
                    Button(action: skipToEnd) {
                        Text("Skip")
                            .font(.body)
                            .foregroundColor(.gray)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                    }
                    .accessibilityLabel("Skip to permissions")
                    .accessibilityHint("Skips tutorial steps and goes to permission requests")
                }
            }
            .padding(.horizontal, 16)

            // Progress indicator
            progressIndicator
        }
    }

    // MARK: - Progress Indicator

    private var progressIndicator: some View {
        VStack(spacing: 8) {
            // Step counter text
            Text("Step \(currentStep + 1) of \(totalSteps)")
                .font(.subheadline)
                .foregroundColor(.gray)

            // Progress bar
            HStack(spacing: 8) {
                ForEach(0..<totalSteps, id: \.self) { step in
                    Capsule()
                        .fill(step <= currentStep ? Color.tallyAccent : Color.gray.opacity(0.3))
                        .frame(height: 6)
                        .animation(.spring(response: 0.3), value: currentStep)
                }
            }
            .padding(.horizontal, 40)
        }
    }

    // MARK: - Permissions Step (Final Step)

    private var permissionsStep: some View {
        ScrollView {
            VStack(spacing: 24) {
                // Icon and title
                VStack(spacing: 16) {
                    ZStack {
                        Circle()
                            .fill(steps.last?.backgroundColor ?? Color.tallyCard)
                            .frame(width: 120, height: 120)

                        Image(systemName: steps.last?.icon ?? "checkmark.seal.fill")
                            .font(.system(size: 60))
                            .foregroundColor(.tallyAccent)
                    }
                    .padding(.top, 20)

                    Text(steps.last?.title ?? "You're All Set!")
                        .font(.system(size: 32, weight: .bold))
                        .foregroundColor(.white)
                        .multilineTextAlignment(.center)

                    Text(steps.last?.subtitle ?? "Let's Get Started")
                        .font(.title3)
                        .foregroundColor(.tallyAccent)
                }

                // Permissions section
                VStack(spacing: 16) {
                    Text("We need a few permissions:")
                        .font(.headline)
                        .foregroundColor(.white)

                    // Camera permission
                    OnboardingPermissionRow(
                        icon: "camera.fill",
                        title: "Camera",
                        description: "To scan your receipts",
                        isGranted: cameraPermissionGranted,
                        isRequired: true,
                        action: requestCameraPermission
                    )

                    // Photo library permission
                    OnboardingPermissionRow(
                        icon: "photo.on.rectangle",
                        title: "Photo Library",
                        description: "To import receipt images",
                        isGranted: photoLibraryPermissionGranted,
                        isRequired: false,
                        action: requestPhotoLibraryPermission
                    )

                    // Notifications permission
                    OnboardingPermissionRow(
                        icon: "bell.fill",
                        title: "Notifications",
                        description: "To alert you about receipts",
                        isGranted: notificationPermissionGranted,
                        isRequired: false,
                        action: requestNotificationPermission
                    )
                }
                .padding(.horizontal, 24)

                Spacer(minLength: 60)
            }
        }
        .onAppear {
            checkCurrentPermissions()
        }
    }

    // MARK: - Navigation Buttons

    private var navigationButtons: some View {
        HStack(spacing: 16) {
            // Back button (not on first step)
            if currentStep > 0 {
                Button(action: goBack) {
                    HStack(spacing: 8) {
                        Image(systemName: "chevron.left")
                            .font(.headline)
                        Text("Back")
                            .font(.headline)
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 18)
                    .background(Color.tallyCard)
                    .cornerRadius(16)
                }
                .accessibilityLabel("Back")
                .accessibilityHint("Go to previous step")
            }

            // Next/Get Started button
            Button(action: handleNextStep) {
                HStack(spacing: 8) {
                    if isCompletingOnboarding {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .black))
                    } else {
                        Text(currentStep == totalSteps - 1 ? "Get Started" : "Next")
                            .font(.headline.bold())
                        if currentStep < totalSteps - 1 {
                            Image(systemName: "chevron.right")
                                .font(.headline)
                        }
                    }
                }
                .foregroundColor(.black)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 18)
                .background(Color.tallyAccent)
                .cornerRadius(16)
            }
            .disabled(isCompletingOnboarding)
            .accessibilityLabel(currentStep == totalSteps - 1 ? "Get Started" : "Next step")
            .accessibilityHint(currentStep == totalSteps - 1 ? "Complete onboarding and start using the app" : "Go to next tutorial step")
        }
    }

    // MARK: - Actions

    private func goBack() {
        withAnimation(.spring(response: 0.3)) {
            currentStep = max(0, currentStep - 1)
        }
        HapticService.shared.lightTap()
    }

    private func skipToEnd() {
        withAnimation(.spring(response: 0.3)) {
            currentStep = totalSteps - 1
        }
        HapticService.shared.lightTap()
    }

    private func handleNextStep() {
        if currentStep == totalSteps - 1 {
            completeOnboarding()
        } else {
            withAnimation(.spring(response: 0.3)) {
                currentStep += 1
            }
            HapticService.shared.lightTap()
        }
    }

    private func completeOnboarding() {
        isCompletingOnboarding = true
        HapticService.shared.success()

        // Store completion locally
        UserDefaults.standard.set(true, forKey: "onboarding_completed")
        UserDefaults.standard.set(Date(), forKey: "onboarding_completed_date")

        Task {
            do {
                // Mark onboarding complete on server
                try await markOnboardingComplete()

                await MainActor.run {
                    authService.needsOnboarding = false
                    dismiss()
                }
            } catch {
                // Still dismiss - we can retry later
                await MainActor.run {
                    authService.needsOnboarding = false
                    dismiss()
                }
            }

            isCompletingOnboarding = false
        }
    }

    private func markOnboardingComplete() async throws {
        guard let url = URL(string: "\(authService.serverURL)/api/onboarding/complete") else {
            throw URLError(.badURL)
        }

        var request = URLRequest(url: url)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        if let token = KeychainService.shared.get(key: "access_token") {
            request.setValue("Bearer \(token)", forHTTPHeaderField: "Authorization")
        }

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw URLError(.badServerResponse)
        }
    }

    // MARK: - Permission Checking

    private func checkCurrentPermissions() {
        // Check camera
        let cameraStatus = AVCaptureDevice.authorizationStatus(for: .video)
        cameraPermissionGranted = (cameraStatus == .authorized)

        // Check photo library
        let photoStatus = PHPhotoLibrary.authorizationStatus(for: .readWrite)
        photoLibraryPermissionGranted = (photoStatus == .authorized || photoStatus == .limited)

        // Check notifications
        UNUserNotificationCenter.current().getNotificationSettings { settings in
            DispatchQueue.main.async {
                notificationPermissionGranted = (settings.authorizationStatus == .authorized)
            }
        }
    }

    // MARK: - Permission Requests

    private func requestCameraPermission() {
        AVCaptureDevice.requestAccess(for: .video) { granted in
            DispatchQueue.main.async {
                cameraPermissionGranted = granted
                if granted {
                    HapticService.shared.success()
                }
            }
        }
    }

    private func requestPhotoLibraryPermission() {
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            DispatchQueue.main.async {
                photoLibraryPermissionGranted = (status == .authorized || status == .limited)
                if photoLibraryPermissionGranted {
                    HapticService.shared.success()
                }
            }
        }
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
            DispatchQueue.main.async {
                notificationPermissionGranted = granted
                if granted {
                    HapticService.shared.success()
                }
            }
        }
    }
}

// MARK: - Tutorial Step View

struct TutorialStepView: View {
    let step: OnboardingStep

    var body: some View {
        ScrollView {
            VStack(spacing: 24) {
                Spacer(minLength: 20)

                // Large icon with background
                ZStack {
                    Circle()
                        .fill(step.backgroundColor)
                        .frame(width: 140, height: 140)

                    Image(systemName: step.icon)
                        .font(.system(size: 70))
                        .foregroundColor(.tallyAccent)
                }
                .padding(.top, 20)
                .accessibilityHidden(true)

                // Title section
                VStack(spacing: 12) {
                    Text(step.title)
                        .font(.system(size: 32, weight: .bold))
                        .foregroundColor(.white)
                        .multilineTextAlignment(.center)
                        .lineLimit(2)
                        .minimumScaleFactor(0.8)

                    Text(step.subtitle)
                        .font(.title3)
                        .foregroundColor(.tallyAccent)
                        .multilineTextAlignment(.center)
                }
                .padding(.horizontal, 24)
                .accessibilityElement(children: .combine)

                // Description
                Text(step.description)
                    .font(.body)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .lineSpacing(4)
                    .padding(.horizontal, 32)

                // Tips section
                VStack(alignment: .leading, spacing: 16) {
                    ForEach(step.tips, id: \.self) { tip in
                        TipRow(text: tip)
                    }
                }
                .padding(20)
                .background(Color.tallyCard)
                .cornerRadius(20)
                .padding(.horizontal, 24)
                .accessibilityElement(children: .contain)
                .accessibilityLabel("Tips")

                Spacer(minLength: 80)
            }
        }
    }
}

// MARK: - Tip Row

struct TipRow: View {
    let text: String

    var body: some View {
        HStack(alignment: .top, spacing: 14) {
            Image(systemName: "checkmark.circle.fill")
                .font(.title2)
                .foregroundColor(.tallyAccent)
                .accessibilityHidden(true)

            Text(text)
                .font(.body)
                .foregroundColor(.white)
                .lineSpacing(2)

            Spacer()
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel(text)
    }
}

// MARK: - Onboarding Permission Row

struct OnboardingPermissionRow: View {
    let icon: String
    let title: String
    let description: String
    let isGranted: Bool
    let isRequired: Bool
    let action: () -> Void

    private var accessibilityDescription: String {
        var parts = [title, description]
        if isRequired {
            parts.append("Required")
        }
        parts.append(isGranted ? "Granted" : "Not granted")
        return parts.joined(separator: ", ")
    }

    var body: some View {
        HStack(spacing: 16) {
            // Icon
            ZStack {
                Circle()
                    .fill(isGranted ? Color.green.opacity(0.2) : Color.tallyCard)
                    .frame(width: 50, height: 50)

                Image(systemName: isGranted ? "checkmark.circle.fill" : icon)
                    .font(.title2)
                    .foregroundColor(isGranted ? .green : .tallyAccent)
            }
            .accessibilityHidden(true)

            // Text
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(title)
                        .font(.headline)
                        .foregroundColor(.white)

                    if isRequired {
                        Text("Required")
                            .font(.caption)
                            .foregroundColor(.orange)
                            .padding(.horizontal, 8)
                            .padding(.vertical, 2)
                            .background(Color.orange.opacity(0.2))
                            .cornerRadius(8)
                    }
                }

                Text(description)
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }

            Spacer()

            // Action button
            if !isGranted {
                Button(action: action) {
                    Text("Allow")
                        .font(.subheadline.bold())
                        .foregroundColor(.black)
                        .padding(.horizontal, 16)
                        .padding(.vertical, 10)
                        .background(Color.tallyAccent)
                        .cornerRadius(10)
                }
                .accessibilityLabel("Allow \(title)")
                .accessibilityHint("Requests permission for \(description.lowercased())")
            } else {
                Image(systemName: "checkmark.circle.fill")
                    .font(.title2)
                    .foregroundColor(.green)
                    .accessibilityLabel("\(title) permission granted")
            }
        }
        .padding(16)
        .background(Color.tallyCard)
        .cornerRadius(16)
        .accessibilityElement(children: .contain)
    }
}

// MARK: - Onboarding Manager

class OnboardingManager: ObservableObject {
    static let shared = OnboardingManager()

    @Published var hasCompletedOnboarding: Bool
    @Published var shouldShowOnboarding: Bool = false

    private let completedKey = "onboarding_completed"
    private let versionKey = "onboarding_version"
    private let currentVersion = 1 // Increment this to force re-show onboarding

    private init() {
        let completed = UserDefaults.standard.bool(forKey: completedKey)
        let savedVersion = UserDefaults.standard.integer(forKey: versionKey)

        // Show onboarding if never completed or if version changed
        if !completed || savedVersion < currentVersion {
            hasCompletedOnboarding = false
        } else {
            hasCompletedOnboarding = true
        }
    }

    func markOnboardingComplete() {
        UserDefaults.standard.set(true, forKey: completedKey)
        UserDefaults.standard.set(currentVersion, forKey: versionKey)
        hasCompletedOnboarding = true
        shouldShowOnboarding = false
    }

    func resetOnboarding() {
        UserDefaults.standard.set(false, forKey: completedKey)
        hasCompletedOnboarding = false
    }

    func checkShouldShowOnboarding() {
        shouldShowOnboarding = !hasCompletedOnboarding
    }
}

// MARK: - Previews

#Preview("Onboarding Flow") {
    OnboardingView()
        .environmentObject(AuthService.shared)
}

#Preview("Tutorial Step") {
    TutorialStepView(step: OnboardingStep(
        icon: "camera.viewfinder",
        title: "Scan Your Receipts",
        subtitle: "It's Easy as 1-2-3",
        description: "Just point your camera at any receipt and tap the button. We'll do the rest!",
        tips: [
            "Hold your phone steady over the receipt",
            "Make sure there's good lighting",
            "The whole receipt should be visible"
        ],
        imageName: nil,
        backgroundColor: Color.blue.opacity(0.15)
    ))
    .background(Color.tallyBackground)
}

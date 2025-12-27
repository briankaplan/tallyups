import SwiftUI
import AVFoundation
import Photos
import UserNotifications

struct OnboardingView: View {
    @EnvironmentObject var authService: AuthService
    @Environment(\.dismiss) private var dismiss

    @State private var currentStep = 0
    @State private var cameraPermissionGranted = false
    @State private var photoLibraryPermissionGranted = false
    @State private var notificationPermissionGranted = false
    @State private var isCompletingOnboarding = false

    private let totalSteps = 5

    var body: some View {
        ZStack {
            Color.tallyBackground.ignoresSafeArea()

            VStack(spacing: 0) {
                // Progress indicator
                progressIndicator
                    .padding(.top, 20)

                // Content
                TabView(selection: $currentStep) {
                    welcomeStep.tag(0)
                    cameraStep.tag(1)
                    photoLibraryStep.tag(2)
                    notificationsStep.tag(3)
                    readyStep.tag(4)
                }
                .tabViewStyle(.page(indexDisplayMode: .never))
                .animation(.easeInOut, value: currentStep)

                // Navigation buttons
                navigationButtons
                    .padding(.horizontal, 24)
                    .padding(.bottom, 40)
            }
        }
    }

    // MARK: - Progress Indicator

    private var progressIndicator: some View {
        HStack(spacing: 8) {
            ForEach(0..<totalSteps, id: \.self) { step in
                Capsule()
                    .fill(step <= currentStep ? Color.tallyAccent : Color.gray.opacity(0.3))
                    .frame(height: 4)
            }
        }
        .padding(.horizontal, 40)
    }

    // MARK: - Step 1: Welcome

    private var welcomeStep: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "doc.viewfinder.fill")
                .font(.system(size: 100))
                .foregroundColor(.tallyAccent)

            VStack(spacing: 16) {
                Text("Welcome to TallyUps")
                    .font(.largeTitle.bold())
                    .foregroundColor(.white)
                    .multilineTextAlignment(.center)

                if let userName = authService.currentUser?.name {
                    Text("Hi, \(userName)!")
                        .font(.title2)
                        .foregroundColor(.tallyAccent)
                }

                Text("Let's get you set up to scan and manage your receipts in just a few steps.")
                    .font(.body)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            Spacer()
            Spacer()
        }
    }

    // MARK: - Step 2: Camera Permission

    private var cameraStep: some View {
        permissionStep(
            icon: "camera.fill",
            title: "Camera Access",
            description: "TallyUps needs camera access to scan your receipts. This is required for the scanner to work.",
            isGranted: cameraPermissionGranted,
            grantAction: requestCameraPermission
        )
    }

    // MARK: - Step 3: Photo Library

    private var photoLibraryStep: some View {
        permissionStep(
            icon: "photo.on.rectangle",
            title: "Photo Library",
            description: "Allow access to your photo library to import existing receipt images and save scanned receipts.",
            isGranted: photoLibraryPermissionGranted,
            grantAction: requestPhotoLibraryPermission
        )
    }

    // MARK: - Step 4: Notifications

    private var notificationsStep: some View {
        permissionStep(
            icon: "bell.fill",
            title: "Notifications",
            description: "Get notified when receipts are processed, matched to transactions, or need your attention.",
            isGranted: notificationPermissionGranted,
            grantAction: requestNotificationPermission,
            isOptional: true
        )
    }

    // MARK: - Step 5: Ready

    private var readyStep: some View {
        VStack(spacing: 32) {
            Spacer()

            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 100))
                .foregroundColor(.green)

            VStack(spacing: 16) {
                Text("You're All Set!")
                    .font(.largeTitle.bold())
                    .foregroundColor(.white)
                    .multilineTextAlignment(.center)

                Text("Start scanning receipts right away. You can connect additional services like Gmail and Calendar later in Settings.")
                    .font(.body)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            // Quick tips
            VStack(alignment: .leading, spacing: 12) {
                tipRow(icon: "camera.viewfinder", text: "Tap the camera button to scan")
                tipRow(icon: "photo.stack", text: "Import from photo library")
                tipRow(icon: "doc.text.magnifyingglass", text: "Auto-matching with transactions")
            }
            .padding()
            .background(Color.tallyCard)
            .cornerRadius(16)
            .padding(.horizontal, 24)

            Spacer()
            Spacer()
        }
    }

    // MARK: - Helper Views

    private func permissionStep(
        icon: String,
        title: String,
        description: String,
        isGranted: Bool,
        grantAction: @escaping () -> Void,
        isOptional: Bool = false
    ) -> some View {
        VStack(spacing: 32) {
            Spacer()

            ZStack {
                Circle()
                    .fill(isGranted ? Color.green.opacity(0.2) : Color.tallyCard)
                    .frame(width: 120, height: 120)

                Image(systemName: isGranted ? "checkmark.circle.fill" : icon)
                    .font(.system(size: 50))
                    .foregroundColor(isGranted ? .green : .tallyAccent)
            }

            VStack(spacing: 16) {
                Text(title)
                    .font(.title.bold())
                    .foregroundColor(.white)

                Text(description)
                    .font(.body)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)

                if isOptional {
                    Text("(Optional)")
                        .font(.caption)
                        .foregroundColor(.gray.opacity(0.7))
                }
            }

            if !isGranted {
                Button(action: grantAction) {
                    Text("Allow Access")
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent)
                        .cornerRadius(12)
                }
                .padding(.horizontal, 40)
            } else {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundColor(.green)
                    Text("Permission Granted")
                        .foregroundColor(.green)
                }
                .font(.headline)
            }

            Spacer()
            Spacer()
        }
    }

    private func tipRow(icon: String, text: String) -> some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(.tallyAccent)
                .frame(width: 30)

            Text(text)
                .font(.subheadline)
                .foregroundColor(.white)

            Spacer()
        }
    }

    // MARK: - Navigation Buttons

    private var navigationButtons: some View {
        HStack(spacing: 16) {
            // Back button (not on first step)
            if currentStep > 0 {
                Button(action: { withAnimation { currentStep -= 1 } }) {
                    HStack {
                        Image(systemName: "chevron.left")
                        Text("Back")
                    }
                    .font(.headline)
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                }
            }

            // Next/Finish button
            Button(action: handleNextStep) {
                HStack {
                    if isCompletingOnboarding {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .black))
                    } else {
                        Text(currentStep == totalSteps - 1 ? "Get Started" : "Continue")
                        if currentStep < totalSteps - 1 {
                            Image(systemName: "chevron.right")
                        }
                    }
                }
                .font(.headline)
                .foregroundColor(.black)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }
            .disabled(isCompletingOnboarding)
        }
    }

    // MARK: - Actions

    private func handleNextStep() {
        if currentStep == totalSteps - 1 {
            completeOnboarding()
        } else {
            withAnimation {
                currentStep += 1
            }
        }
    }

    private func completeOnboarding() {
        isCompletingOnboarding = true

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

    // MARK: - Permission Requests

    private func requestCameraPermission() {
        AVCaptureDevice.requestAccess(for: .video) { granted in
            DispatchQueue.main.async {
                cameraPermissionGranted = granted
            }
        }
    }

    private func requestPhotoLibraryPermission() {
        PHPhotoLibrary.requestAuthorization(for: .readWrite) { status in
            DispatchQueue.main.async {
                photoLibraryPermissionGranted = (status == .authorized || status == .limited)
            }
        }
    }

    private func requestNotificationPermission() {
        UNUserNotificationCenter.current().requestAuthorization(options: [.alert, .badge, .sound]) { granted, _ in
            DispatchQueue.main.async {
                notificationPermissionGranted = granted
            }
        }
    }
}

// MARK: - Previews

#Preview {
    OnboardingView()
        .environmentObject(AuthService.shared)
}

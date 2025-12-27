import SwiftUI

struct ContentView: View {
    @EnvironmentObject var authService: AuthService
    @EnvironmentObject var uploadQueue: UploadQueue
    @StateObject private var deepLinkHandler = DeepLinkHandler.shared
    @State private var selectedTab = 0
    @State private var showFullScreenScanner = false
    @State private var selectedTransactionId: Int?

    var body: some View {
        Group {
            if authService.isAuthenticated {
                mainTabView
            } else {
                LoginView()
            }
        }
        .animation(.easeInOut, value: authService.isAuthenticated)
        // Handle deep links from widgets
        .onOpenURL { url in
            handleDeepLink(url)
        }
        // Handle navigation notifications
        .onReceive(NotificationCenter.default.publisher(for: .navigateToScanner)) { _ in
            withAnimation(.spring(response: 0.3)) {
                selectedTab = 0
            }
            HapticService.shared.mediumTap()
        }
        .onReceive(NotificationCenter.default.publisher(for: .navigateToTransactions)) { _ in
            withAnimation(.spring(response: 0.3)) {
                selectedTab = 1
            }
            HapticService.shared.mediumTap()
        }
        .onReceive(NotificationCenter.default.publisher(for: .navigateToLibrary)) { _ in
            withAnimation(.spring(response: 0.3)) {
                selectedTab = 2
            }
            HapticService.shared.mediumTap()
        }
        .onReceive(NotificationCenter.default.publisher(for: .navigateToInbox)) { _ in
            withAnimation(.spring(response: 0.3)) {
                selectedTab = 3
            }
            HapticService.shared.mediumTap()
        }
        // Watch for deep link handler changes
        .onChange(of: deepLinkHandler.showScanner) { _, newValue in
            if newValue {
                showFullScreenScanner = true
                deepLinkHandler.showScanner = false
            }
        }
        .fullScreenCover(isPresented: $showFullScreenScanner) {
            FullScreenScannerView(isPresented: $showFullScreenScanner) { capturedImage in
                handleCapturedImage(capturedImage)
            }
        }
    }

    // MARK: - Deep Link Handling

    private func handleDeepLink(_ url: URL) {
        guard let deepLink = DeepLink(url: url) else { return }

        HapticService.shared.impact(.medium)

        withAnimation(.spring(response: 0.3)) {
            switch deepLink {
            case .scan:
                showFullScreenScanner = true
            case .inbox:
                selectedTab = 3
            case .transaction(let id):
                selectedTransactionId = id
                selectedTab = 2
            case .dashboard:
                selectedTab = 1
            case .profile, .settings:
                selectedTab = 4
            }
        }
    }

    private func handleCapturedImage(_ image: UIImage) {
        guard let imageData = image.jpegData(compressionQuality: 0.8) else { return }

        uploadQueue.enqueueReceipt(imageData: imageData)
        HapticService.shared.success()
    }

    private var mainTabView: some View {
        TabView(selection: $selectedTab) {
            ScannerView()
                .tabItem {
                    Label("Scan", systemImage: "camera.fill")
                }
                .tag(0)

            TransactionsView()
                .tabItem {
                    Label("Charges", systemImage: "creditcard.fill")
                }
                .tag(1)

            LibraryView()
                .tabItem {
                    Label("Library", systemImage: "photo.stack.fill")
                }
                .tag(2)

            ReceiptInboxView()
                .tabItem {
                    Label("Receipts", systemImage: "tray.full.fill")
                }
                .tag(3)

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape.fill")
                }
                .tag(4)
        }
        .tint(Color.tallyAccent)
        .onChange(of: selectedTab) { oldValue, newValue in
            HapticService.shared.tabSwitch()
        }
        .overlay(alignment: .top) {
            uploadQueueIndicator
        }
    }

    @ViewBuilder
    private var uploadQueueIndicator: some View {
        if uploadQueue.pendingCount > 0 {
            HStack(spacing: 8) {
                if uploadQueue.isUploading {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        .scaleEffect(0.8)
                }

                Text("\(uploadQueue.pendingCount) pending upload\(uploadQueue.pendingCount == 1 ? "" : "s")")
                    .font(.caption)
                    .foregroundColor(.white)

                if let progress = uploadQueue.currentProgress {
                    Text("\(Int(progress * 100))%")
                        .font(.caption.bold())
                        .foregroundColor(Color.tallyAccent)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(Color.tallyCard)
            .cornerRadius(20)
            .shadow(radius: 4)
            .padding(.top, 8)
        }
    }
}

#Preview {
    ContentView()
        .environmentObject(AuthService.shared)
        .environmentObject(UploadQueue.shared)
        .environmentObject(NetworkMonitor.shared)
}

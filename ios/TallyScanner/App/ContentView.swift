import SwiftUI

struct ContentView: View {
    @EnvironmentObject var authService: AuthService
    @EnvironmentObject var uploadQueue: UploadQueue
    @State private var selectedTab = 0

    var body: some View {
        Group {
            if authService.isAuthenticated {
                mainTabView
            } else {
                LoginView()
            }
        }
        .animation(.easeInOut, value: authService.isAuthenticated)
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

            InboxView()
                .tabItem {
                    Label("Inbox", systemImage: "tray.fill")
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

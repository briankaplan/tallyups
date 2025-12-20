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
    }

    private var mainTabView: some View {
        TabView(selection: $selectedTab) {
            ScannerView()
                .tabItem {
                    Label("Scan", systemImage: "camera.fill")
                }
                .tag(0)

            LibraryView()
                .tabItem {
                    Label("Library", systemImage: "photo.stack.fill")
                }
                .tag(1)

            InboxView()
                .tabItem {
                    Label("Inbox", systemImage: "tray.fill")
                }
                .tag(2)

            SettingsView()
                .tabItem {
                    Label("Settings", systemImage: "gearshape.fill")
                }
                .tag(3)
        }
        .tint(Color.tallyAccent)
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

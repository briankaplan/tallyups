import SwiftUI
import BackgroundTasks
import UserNotifications

@main
struct TallyScannerApp: App {
    @StateObject private var authService = AuthService.shared
    @StateObject private var uploadQueue = UploadQueue.shared
    @StateObject private var networkMonitor = NetworkMonitor.shared
    @StateObject private var notificationService = NotificationService.shared

    @UIApplicationDelegateAdaptor(AppDelegate.self) var appDelegate

    init() {
        // Configure app appearance
        configureAppearance()

        // Register background tasks
        registerBackgroundTasks()

        // Set notification delegate
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
    }

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(authService)
                .environmentObject(uploadQueue)
                .environmentObject(networkMonitor)
                .environmentObject(notificationService)
                .preferredColorScheme(.dark)
                .onAppear {
                    // Start network monitoring
                    networkMonitor.start()

                    // Resume pending uploads if authenticated
                    if authService.isAuthenticated {
                        uploadQueue.resumePendingUploads()
                    }

                    // Request notification permissions
                    Task {
                        _ = await notificationService.requestAuthorization()
                    }
                }
        }
    }

    private func configureAppearance() {
        // Configure navigation bar appearance
        let appearance = UINavigationBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(Color.tallyBackground)
        appearance.titleTextAttributes = [.foregroundColor: UIColor.white]
        appearance.largeTitleTextAttributes = [.foregroundColor: UIColor.white]

        UINavigationBar.appearance().standardAppearance = appearance
        UINavigationBar.appearance().scrollEdgeAppearance = appearance
        UINavigationBar.appearance().compactAppearance = appearance

        // Configure tab bar appearance
        let tabBarAppearance = UITabBarAppearance()
        tabBarAppearance.configureWithOpaqueBackground()
        tabBarAppearance.backgroundColor = UIColor(Color.tallyBackground)

        UITabBar.appearance().standardAppearance = tabBarAppearance
        UITabBar.appearance().scrollEdgeAppearance = tabBarAppearance
    }

    private func registerBackgroundTasks() {
        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: "com.tallyups.scanner.upload",
            using: nil
        ) { task in
            self.handleBackgroundUpload(task: task as! BGProcessingTask)
        }

        BGTaskScheduler.shared.register(
            forTaskWithIdentifier: "com.tallyups.scanner.sync",
            using: nil
        ) { task in
            self.handleBackgroundSync(task: task as! BGAppRefreshTask)
        }
    }

    private func handleBackgroundUpload(task: BGProcessingTask) {
        task.expirationHandler = {
            UploadQueue.shared.pauseUploads()
        }

        Task {
            await UploadQueue.shared.processBackgroundUploads()
            task.setTaskCompleted(success: true)
            scheduleBackgroundUpload()
        }
    }

    private func handleBackgroundSync(task: BGAppRefreshTask) {
        task.expirationHandler = {}

        Task {
            // Sync library data in background
            _ = try? await APIClient.shared.fetchReceipts(limit: 50)
            task.setTaskCompleted(success: true)
            scheduleBackgroundSync()
        }
    }

    private func scheduleBackgroundUpload() {
        let request = BGProcessingTaskRequest(identifier: "com.tallyups.scanner.upload")
        request.requiresNetworkConnectivity = true
        request.requiresExternalPower = false

        try? BGTaskScheduler.shared.submit(request)
    }

    private func scheduleBackgroundSync() {
        let request = BGAppRefreshTaskRequest(identifier: "com.tallyups.scanner.sync")
        request.earliestBeginDate = Date(timeIntervalSinceNow: 15 * 60) // 15 minutes

        try? BGTaskScheduler.shared.submit(request)
    }
}

// MARK: - App Delegate

class AppDelegate: NSObject, UIApplicationDelegate {
    func application(
        _ application: UIApplication,
        didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]? = nil
    ) -> Bool {
        // Request notification permissions on first launch
        UNUserNotificationCenter.current().delegate = NotificationDelegate.shared
        return true
    }

    func application(
        _ application: UIApplication,
        didRegisterForRemoteNotificationsWithDeviceToken deviceToken: Data
    ) {
        // Convert token to string for backend registration
        let tokenParts = deviceToken.map { data in String(format: "%02.2hhx", data) }
        let token = tokenParts.joined()
        print("🔔 Push token: \(token)")

        // Send token to backend for push notifications
        Task {
            do {
                try await APIClient.shared.registerPushToken(token)
                print("🔔 Push token registered with backend")
            } catch {
                print("🔔 Failed to register push token: \(error)")
            }
        }
    }

    func application(
        _ application: UIApplication,
        didFailToRegisterForRemoteNotificationsWithError error: Error
    ) {
        print("🔔 Failed to register for push notifications: \(error)")
    }
}

// MARK: - Color Extensions
extension Color {
    static let tallyBackground = Color(red: 0.05, green: 0.05, blue: 0.05)
    static let tallyCard = Color(red: 0.1, green: 0.1, blue: 0.1)
    static let tallyAccent = Color(red: 0, green: 1, blue: 0.53) // #00ff88
    static let tallySecondary = Color(red: 0.4, green: 0.4, blue: 0.4)
    static let tallySuccess = Color(red: 0.2, green: 0.8, blue: 0.4)
    static let tallyWarning = Color(red: 1, green: 0.8, blue: 0)
    static let tallyError = Color(red: 1, green: 0.3, blue: 0.3)
}

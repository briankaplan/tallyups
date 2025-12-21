import Foundation
import CoreLocation
import UserNotifications

/// Service for location-based receipt reminders
@MainActor
class LocationService: NSObject, ObservableObject, CLLocationManagerDelegate {
    static let shared = LocationService()

    private let locationManager = CLLocationManager()

    @Published var currentLocation: CLLocation?
    @Published var currentPlaceName: String?
    @Published var isAtKnownMerchant: Bool = false
    @Published var nearbyMerchantName: String?

    // Known merchant locations (could be synced from server)
    private var knownLocations: [MerchantLocation] = []

    // Tracking when user arrived at a location
    private var arrivalTime: Date?
    private var lastNotifiedLocation: String?

    // Geofence radius in meters
    private let geofenceRadius: Double = 100

    private override init() {
        super.init()
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationManager.allowsBackgroundLocationUpdates = false
        locationManager.pausesLocationUpdatesAutomatically = true
    }

    // MARK: - Authorization

    func requestAuthorization() {
        locationManager.requestWhenInUseAuthorization()
    }

    func requestAlwaysAuthorization() {
        locationManager.requestAlwaysAuthorization()
    }

    var authorizationStatus: CLAuthorizationStatus {
        locationManager.authorizationStatus
    }

    // MARK: - Location Updates

    func startUpdating() {
        locationManager.startUpdatingLocation()
    }

    func stopUpdating() {
        locationManager.stopUpdatingLocation()
    }

    // MARK: - CLLocationManagerDelegate

    nonisolated func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }

        Task { @MainActor in
            self.currentLocation = location
            await self.checkNearbyMerchants(location: location)
            await self.reverseGeocode(location: location)
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didFailWithError error: Error) {
        print("Location error: \(error)")
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        Task { @MainActor in
            switch status {
            case .authorizedWhenInUse, .authorizedAlways:
                self.startUpdating()
            default:
                break
            }
        }
    }

    nonisolated func locationManager(_ manager: CLLocationManager, didExitRegion region: CLRegion) {
        // User left a monitored location - trigger reminder!
        Task { @MainActor in
            await self.handleExitRegion(region)
        }
    }

    // MARK: - Smart Location Features

    private func checkNearbyMerchants(location: CLLocation) async {
        // Check against known merchant locations
        for merchant in knownLocations {
            let merchantLocation = CLLocation(
                latitude: merchant.latitude,
                longitude: merchant.longitude
            )

            let distance = location.distance(from: merchantLocation)

            if distance < geofenceRadius {
                // User is at a known merchant!
                if nearbyMerchantName != merchant.name {
                    nearbyMerchantName = merchant.name
                    isAtKnownMerchant = true
                    arrivalTime = Date()

                    // Start monitoring for exit
                    startMonitoringExit(for: merchant)
                }
                return
            }
        }

        // Not at any known location
        if isAtKnownMerchant {
            isAtKnownMerchant = false
            nearbyMerchantName = nil
        }
    }

    private func reverseGeocode(location: CLLocation) async {
        let geocoder = CLGeocoder()

        do {
            let placemarks = try await geocoder.reverseGeocodeLocation(location)
            if let placemark = placemarks.first {
                // Try to get a meaningful place name
                if let name = placemark.name, !name.isEmpty {
                    currentPlaceName = name
                } else if let thoroughfare = placemark.thoroughfare {
                    currentPlaceName = thoroughfare
                } else if let locality = placemark.locality {
                    currentPlaceName = locality
                }
            }
        } catch {
            print("Geocoding error: \(error)")
        }
    }

    // MARK: - Geofencing

    private func startMonitoringExit(for merchant: MerchantLocation) {
        guard CLLocationManager.isMonitoringAvailable(for: CLCircularRegion.self) else { return }

        let region = CLCircularRegion(
            center: CLLocationCoordinate2D(latitude: merchant.latitude, longitude: merchant.longitude),
            radius: geofenceRadius,
            identifier: "merchant_\(merchant.name)"
        )
        region.notifyOnEntry = false
        region.notifyOnExit = true

        locationManager.startMonitoring(for: region)
    }

    private func handleExitRegion(_ region: CLRegion) async {
        guard region.identifier.hasPrefix("merchant_") else { return }

        let merchantName = String(region.identifier.dropFirst("merchant_".count))

        // Don't notify for the same location twice in quick succession
        if lastNotifiedLocation == merchantName {
            return
        }
        lastNotifiedLocation = merchantName

        // Calculate how long user was at location
        let timeSpent = arrivalTime.map { Date().timeIntervalSince($0) } ?? 0

        // Only remind if they were there for at least 2 minutes (likely made a purchase)
        guard timeSpent > 120 else { return }

        // Send "Don't forget your receipt!" notification
        await sendReceiptReminder(merchantName: merchantName)

        // Stop monitoring this region
        locationManager.stopMonitoring(for: region)
    }

    private func sendReceiptReminder(merchantName: String) async {
        let content = UNMutableNotificationContent()
        content.title = "Don't Forget Your Receipt!"
        content.body = "Did you get a receipt from \(merchantName)? Snap it now before you lose it!"
        content.sound = .default
        content.categoryIdentifier = "RECEIPT_REMINDER"
        content.interruptionLevel = .timeSensitive

        // Add quick action buttons
        let scanAction = UNNotificationAction(
            identifier: "SCAN_NOW",
            title: "Scan Receipt",
            options: .foreground
        )
        let skipAction = UNNotificationAction(
            identifier: "SKIP",
            title: "No Receipt",
            options: []
        )
        let category = UNNotificationCategory(
            identifier: "RECEIPT_REMINDER",
            actions: [scanAction, skipAction],
            intentIdentifiers: []
        )
        UNUserNotificationCenter.current().setNotificationCategories([category])

        let request = UNNotificationRequest(
            identifier: "reminder-\(merchantName)-\(UUID().uuidString)",
            content: content,
            trigger: nil // Immediate
        )

        do {
            try await UNUserNotificationCenter.current().add(request)
            print("Sent receipt reminder for \(merchantName)")
        } catch {
            print("Failed to send reminder: \(error)")
        }
    }

    // MARK: - Known Locations Management

    /// Add a location when user scans a receipt
    func learnLocation(merchant: String, latitude: Double, longitude: Double) {
        // Don't duplicate
        if knownLocations.contains(where: { $0.name.lowercased() == merchant.lowercased() }) {
            return
        }

        let location = MerchantLocation(
            name: merchant,
            latitude: latitude,
            longitude: longitude,
            visitCount: 1,
            lastVisit: Date()
        )

        knownLocations.append(location)
        saveKnownLocations()

        print("Learned new location: \(merchant) at \(latitude), \(longitude)")
    }

    /// Get known locations for a merchant name
    func getLocations(for merchant: String) -> [MerchantLocation] {
        knownLocations.filter { $0.name.lowercased().contains(merchant.lowercased()) }
    }

    // MARK: - Persistence

    private func saveKnownLocations() {
        let encoder = JSONEncoder()
        if let data = try? encoder.encode(knownLocations) {
            UserDefaults.standard.set(data, forKey: "knownMerchantLocations")
        }
    }

    private func loadKnownLocations() {
        let decoder = JSONDecoder()
        if let data = UserDefaults.standard.data(forKey: "knownMerchantLocations"),
           let locations = try? decoder.decode([MerchantLocation].self, from: data) {
            knownLocations = locations
        }
    }

    /// Sync known locations from server (for popular merchants)
    func syncKnownLocations() async {
        loadKnownLocations()

        // Could fetch from server here
        // let serverLocations = try await APIClient.shared.fetchKnownMerchantLocations()
        // Merge with local locations
    }
}

// MARK: - Models

struct MerchantLocation: Codable, Identifiable {
    var id: String { name + "\(latitude)\(longitude)" }
    let name: String
    let latitude: Double
    let longitude: Double
    var visitCount: Int
    var lastVisit: Date
}

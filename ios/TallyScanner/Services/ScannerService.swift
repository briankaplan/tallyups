import Foundation
import AVFoundation
import UIKit
import VisionKit
import CoreLocation
import Vision
import CryptoKit

/// Service for camera and document scanning
class ScannerService: NSObject, ObservableObject {
    static let shared = ScannerService()

    @Published var cameraPermissionStatus: AVAuthorizationStatus = .notDetermined
    @Published var locationPermissionStatus: CLAuthorizationStatus = .notDetermined
    @Published var isProcessing = false
    @Published var lastError: String?
    @Published var currentLocationName: String?

    // Duplicate detection
    @Published var duplicateResult: DuplicateCheckResult?
    private var recentImageHashes: [String: String] = [:]  // hash -> receiptId

    private let locationManager = CLLocationManager()
    private var lastLocation: CLLocation?
    private let geocoder = CLGeocoder()

    /// Result of duplicate check
    struct DuplicateCheckResult {
        let isDuplicate: Bool
        let existingReceiptId: String?
        let existingReceiptUrl: String?
        let matchConfidence: Double
        let matchType: MatchType

        enum MatchType: String {
            case exactHash = "Exact match"
            case similarImage = "Similar image"
            case sameAmountDate = "Same amount & date"
            case sameTransaction = "Already linked"
        }
    }

    override init() {
        super.init()
        checkCameraPermission()
        setupLocationManager()
    }

    // MARK: - Permissions

    func checkCameraPermission() {
        cameraPermissionStatus = AVCaptureDevice.authorizationStatus(for: .video)
    }

    func requestCameraPermission() async -> Bool {
        let status = await AVCaptureDevice.requestAccess(for: .video)
        await MainActor.run {
            checkCameraPermission()
        }
        return status
    }

    private func setupLocationManager() {
        locationManager.delegate = self
        locationManager.desiredAccuracy = kCLLocationAccuracyBest
        locationPermissionStatus = locationManager.authorizationStatus
    }

    func requestLocationPermission() {
        locationManager.requestWhenInUseAuthorization()
    }

    // MARK: - Document Scanner Support

    static var isDocumentScannerSupported: Bool {
        VNDocumentCameraViewController.isSupported
    }

    // MARK: - Image Processing

    /// Compress image data for upload
    func compressImage(_ image: UIImage, maxSize: CGSize = CGSize(width: 2048, height: 2048), quality: CGFloat = 0.8) -> Data? {
        var actualImage = image

        // Resize if needed
        if image.size.width > maxSize.width || image.size.height > maxSize.height {
            let ratio = min(maxSize.width / image.size.width, maxSize.height / image.size.height)
            let newSize = CGSize(width: image.size.width * ratio, height: image.size.height * ratio)

            UIGraphicsBeginImageContextWithOptions(newSize, true, 1.0)
            image.draw(in: CGRect(origin: .zero, size: newSize))
            actualImage = UIGraphicsGetImageFromCurrentImageContext() ?? image
            UIGraphicsEndImageContext()
        }

        return actualImage.jpegData(compressionQuality: quality)
    }

    /// Auto-enhance image for better OCR
    func enhanceImage(_ image: UIImage) -> UIImage {
        guard let ciImage = CIImage(image: image) else { return image }

        let context = CIContext()

        // Apply auto-enhancement filters
        let filters = ciImage.autoAdjustmentFilters(options: [
            CIImageAutoAdjustmentOption.redEye: false
        ])

        var outputImage = ciImage
        for filter in filters {
            filter.setValue(outputImage, forKey: kCIInputImageKey)
            if let output = filter.outputImage {
                outputImage = output
            }
        }

        // Apply additional sharpening for text
        if let sharpenFilter = CIFilter(name: "CISharpenLuminance") {
            sharpenFilter.setValue(outputImage, forKey: kCIInputImageKey)
            sharpenFilter.setValue(0.5, forKey: kCIInputSharpnessKey)
            if let output = sharpenFilter.outputImage {
                outputImage = output
            }
        }

        // Increase contrast slightly
        if let contrastFilter = CIFilter(name: "CIColorControls") {
            contrastFilter.setValue(outputImage, forKey: kCIInputImageKey)
            contrastFilter.setValue(1.1, forKey: kCIInputContrastKey)
            if let output = contrastFilter.outputImage {
                outputImage = output
            }
        }

        guard let cgImage = context.createCGImage(outputImage, from: outputImage.extent) else {
            return image
        }

        return UIImage(cgImage: cgImage, scale: image.scale, orientation: image.imageOrientation)
    }

    /// Convert HEIC to JPEG for upload
    func convertToJPEG(_ imageData: Data, quality: CGFloat = 0.85) -> Data? {
        guard let image = UIImage(data: imageData) else { return nil }
        return image.jpegData(compressionQuality: quality)
    }

    // MARK: - Duplicate Detection

    /// Check if a scanned image is a duplicate of an existing receipt
    func checkForDuplicate(_ image: UIImage, extractedData: OCRResult? = nil) async -> DuplicateCheckResult {
        // Generate perceptual hash for the image
        let imageHash = generatePerceptualHash(image)

        // Check local cache first
        if let existingId = recentImageHashes[imageHash] {
            return DuplicateCheckResult(
                isDuplicate: true,
                existingReceiptId: existingId,
                existingReceiptUrl: nil,
                matchConfidence: 1.0,
                matchType: .exactHash
            )
        }

        // Check API for duplicates
        do {
            let result = try await APIClient.shared.checkDuplicateReceipt(
                imageHash: imageHash,
                amount: extractedData?.amount,
                date: extractedData?.date,
                merchant: extractedData?.merchant
            )

            if result.isDuplicate {
                // Cache this hash for future quick checks
                if let receiptId = result.existingReceiptId {
                    recentImageHashes[imageHash] = receiptId
                }
            }

            await MainActor.run {
                self.duplicateResult = result
            }

            return result
        } catch {
            print("Duplicate check failed: \(error)")
            return DuplicateCheckResult(
                isDuplicate: false,
                existingReceiptId: nil,
                existingReceiptUrl: nil,
                matchConfidence: 0,
                matchType: .exactHash
            )
        }
    }

    /// Generate a perceptual hash (pHash) of an image for similarity comparison
    func generatePerceptualHash(_ image: UIImage) -> String {
        // Resize to 8x8 grayscale for consistent hashing
        let targetSize = CGSize(width: 8, height: 8)

        UIGraphicsBeginImageContextWithOptions(targetSize, true, 1.0)
        image.draw(in: CGRect(origin: .zero, size: targetSize))
        let smallImage = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        guard let cgImage = smallImage?.cgImage else {
            // Fallback to data hash
            if let data = image.jpegData(compressionQuality: 0.5) {
                let hash = SHA256.hash(data: data)
                return hash.compactMap { String(format: "%02x", $0) }.joined()
            }
            return UUID().uuidString
        }

        // Extract pixel luminance values
        let width = cgImage.width
        let height = cgImage.height
        var pixelData = [UInt8](repeating: 0, count: width * height)

        guard let context = CGContext(
            data: &pixelData,
            width: width,
            height: height,
            bitsPerComponent: 8,
            bytesPerRow: width,
            space: CGColorSpaceCreateDeviceGray(),
            bitmapInfo: CGImageAlphaInfo.none.rawValue
        ) else {
            return UUID().uuidString
        }

        context.draw(cgImage, in: CGRect(x: 0, y: 0, width: width, height: height))

        // Calculate average
        let average = Double(pixelData.reduce(0) { $0 + Int($1) }) / Double(pixelData.count)

        // Generate hash based on whether each pixel is above/below average
        var hash: UInt64 = 0
        for (i, pixel) in pixelData.enumerated() {
            if Double(pixel) > average {
                hash |= (1 << i)
            }
        }

        return String(format: "%016llx", hash)
    }

    /// Calculate similarity between two perceptual hashes (Hamming distance)
    func hashSimilarity(_ hash1: String, _ hash2: String) -> Double {
        guard hash1.count == hash2.count else { return 0 }

        let hash1Int = UInt64(hash1, radix: 16) ?? 0
        let hash2Int = UInt64(hash2, radix: 16) ?? 0

        let xor = hash1Int ^ hash2Int
        let hammingDistance = xor.nonzeroBitCount

        // Convert to similarity (0 = completely different, 1 = identical)
        return 1.0 - (Double(hammingDistance) / 64.0)
    }

    /// Clear the duplicate check result
    func clearDuplicateResult() {
        duplicateResult = nil
    }

    // MARK: - Location

    var currentLocation: (latitude: Double, longitude: Double)? {
        guard let location = lastLocation else { return nil }
        return (location.coordinate.latitude, location.coordinate.longitude)
    }

    func startUpdatingLocation() {
        if locationPermissionStatus == .authorizedWhenInUse || locationPermissionStatus == .authorizedAlways {
            locationManager.startUpdatingLocation()
        }
    }

    func stopUpdatingLocation() {
        locationManager.stopUpdatingLocation()
    }
}

// MARK: - CLLocationManagerDelegate

extension ScannerService: CLLocationManagerDelegate {
    func locationManager(_ manager: CLLocationManager, didUpdateLocations locations: [CLLocation]) {
        guard let location = locations.last else { return }
        lastLocation = location

        // Geocode to get place name
        geocoder.reverseGeocodeLocation(location) { [weak self] placemarks, error in
            guard let self = self else { return }

            Task { @MainActor in
                if let placemark = placemarks?.first {
                    var components: [String] = []

                    // Try to get the most useful location info
                    if let name = placemark.name, !name.isEmpty,
                       name != placemark.thoroughfare { // Avoid just showing street name
                        components.append(name)
                    }

                    if let locality = placemark.locality {
                        components.append(locality)
                    }

                    if components.isEmpty {
                        if let thoroughfare = placemark.thoroughfare {
                            components.append(thoroughfare)
                        }
                        if let subLocality = placemark.subLocality {
                            components.append(subLocality)
                        }
                    }

                    self.currentLocationName = components.isEmpty ? nil : components.joined(separator: ", ")
                } else {
                    self.currentLocationName = nil
                }
            }
        }
    }

    func locationManager(_ manager: CLLocationManager, didChangeAuthorization status: CLAuthorizationStatus) {
        Task { @MainActor in
            locationPermissionStatus = status
            if status == .authorizedWhenInUse || status == .authorizedAlways {
                locationManager.startUpdatingLocation()
            }
        }
    }

    func locationManagerDidChangeAuthorization(_ manager: CLLocationManager) {
        Task { @MainActor in
            locationPermissionStatus = manager.authorizationStatus
            if manager.authorizationStatus == .authorizedWhenInUse || manager.authorizationStatus == .authorizedAlways {
                locationManager.startUpdatingLocation()
            }
        }
    }
}

// MARK: - Image Extensions

extension UIImage {
    /// Fix image orientation for upload
    var fixedOrientation: UIImage {
        guard imageOrientation != .up else { return self }

        UIGraphicsBeginImageContextWithOptions(size, false, scale)
        draw(in: CGRect(origin: .zero, size: size))
        let normalizedImage = UIGraphicsGetImageFromCurrentImageContext()
        UIGraphicsEndImageContext()

        return normalizedImage ?? self
    }

    /// Crop to receipt aspect ratio (typically 1:1.5 or similar)
    func cropToReceipt() -> UIImage {
        let targetRatio: CGFloat = 0.7 // width/height for receipt

        let currentRatio = size.width / size.height
        var cropRect: CGRect

        if currentRatio > targetRatio {
            // Image is wider, crop sides
            let newWidth = size.height * targetRatio
            let xOffset = (size.width - newWidth) / 2
            cropRect = CGRect(x: xOffset, y: 0, width: newWidth, height: size.height)
        } else {
            // Image is taller, crop top/bottom
            let newHeight = size.width / targetRatio
            let yOffset = (size.height - newHeight) / 2
            cropRect = CGRect(x: 0, y: yOffset, width: size.width, height: newHeight)
        }

        guard let cgImage = cgImage?.cropping(to: cropRect) else { return self }
        return UIImage(cgImage: cgImage, scale: scale, orientation: imageOrientation)
    }
}

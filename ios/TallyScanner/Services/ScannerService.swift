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

    // MARK: - Image Quality Assessment

    /// Quality assessment result for an image
    struct ImageQualityResult {
        let overallScore: Int  // 0-100
        let sharpnessScore: Double  // 0-1
        let brightnessScore: Double  // 0-1
        let contrastScore: Double  // 0-1
        let isAcceptable: Bool
        let feedback: [QualityFeedback]

        var qualityLevel: QualityLevel {
            if overallScore >= 75 { return .excellent }
            if overallScore >= 50 { return .good }
            if overallScore >= 30 { return .fair }
            return .poor
        }

        enum QualityLevel: String {
            case excellent = "Excellent"
            case good = "Good"
            case fair = "Fair"
            case poor = "Poor"

            var color: String {
                switch self {
                case .excellent: return "green"
                case .good: return "green"
                case .fair: return "yellow"
                case .poor: return "red"
                }
            }
        }

        struct QualityFeedback {
            let type: FeedbackType
            let message: String
            let severity: Severity

            enum FeedbackType {
                case sharpness
                case brightness
                case contrast
            }

            enum Severity {
                case info
                case warning
                case critical
            }
        }

        static let acceptable = ImageQualityResult(
            overallScore: 75,
            sharpnessScore: 0.75,
            brightnessScore: 0.75,
            contrastScore: 0.75,
            isAcceptable: true,
            feedback: []
        )
    }

    /// Calculate image sharpness using Laplacian variance method
    /// Returns a value between 0 and 1, where 1 is perfectly sharp
    func calculateSharpness(_ image: UIImage) -> Double {
        guard let cgImage = image.cgImage else { return 0 }

        let ciImage = CIImage(cgImage: cgImage)

        // Apply Laplacian filter to detect edges
        guard let laplacianFilter = CIFilter(name: "CIConvolution3X3") else { return 0 }

        // Laplacian kernel for edge detection
        let laplacianKernel: [CGFloat] = [
            0, 1, 0,
            1, -4, 1,
            0, 1, 0
        ]

        laplacianFilter.setValue(ciImage, forKey: kCIInputImageKey)
        laplacianFilter.setValue(CIVector(values: laplacianKernel, count: 9), forKey: "inputWeights")
        laplacianFilter.setValue(0, forKey: "inputBias")

        guard let outputImage = laplacianFilter.outputImage else { return 0 }

        // Calculate variance of the Laplacian output
        // Higher variance = sharper image
        let context = CIContext()

        // Sample the image at multiple points to calculate variance
        let extent = outputImage.extent
        let sampleSize = 64
        let sampleRect = CGRect(
            x: extent.midX - CGFloat(sampleSize) / 2,
            y: extent.midY - CGFloat(sampleSize) / 2,
            width: CGFloat(sampleSize),
            height: CGFloat(sampleSize)
        )

        guard let bitmap = context.createCGImage(outputImage, from: sampleRect) else { return 0 }

        // Extract pixel values
        let width = bitmap.width
        let height = bitmap.height
        let bytesPerPixel = 4
        let bytesPerRow = width * bytesPerPixel
        var pixelData = [UInt8](repeating: 0, count: width * height * bytesPerPixel)

        guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
              let ctx = CGContext(
                data: &pixelData,
                width: width,
                height: height,
                bitsPerComponent: 8,
                bytesPerRow: bytesPerRow,
                space: colorSpace,
                bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue
              ) else { return 0 }

        ctx.draw(bitmap, in: CGRect(x: 0, y: 0, width: width, height: height))

        // Calculate variance
        var sum: Double = 0
        var sumSquared: Double = 0
        var count = 0

        for y in 0..<height {
            for x in 0..<width {
                let offset = (y * bytesPerRow) + (x * bytesPerPixel)
                // Use grayscale approximation
                let gray = Double(pixelData[offset]) * 0.299 +
                          Double(pixelData[offset + 1]) * 0.587 +
                          Double(pixelData[offset + 2]) * 0.114
                sum += gray
                sumSquared += gray * gray
                count += 1
            }
        }

        let mean = sum / Double(count)
        let variance = (sumSquared / Double(count)) - (mean * mean)

        // Normalize variance to 0-1 range
        // Typical sharp images have variance > 500, blurry < 100
        let normalizedSharpness = min(1.0, variance / 1000.0)

        return normalizedSharpness
    }

    /// Assess lighting quality of an image
    /// Returns brightness (0-1) and evenness assessment
    func assessLighting(_ image: UIImage) -> (brightness: Double, isEven: Bool, feedback: String?) {
        guard let cgImage = image.cgImage else {
            return (0.5, true, nil)
        }

        let width = cgImage.width
        let height = cgImage.height

        // Sample at grid points for efficiency
        let gridSize = 8
        var brightnessValues: [Double] = []
        var regionBrightness: [[Double]] = Array(repeating: Array(repeating: 0, count: gridSize), count: gridSize)

        guard let dataProvider = cgImage.dataProvider,
              let data = dataProvider.data,
              let bytes = CFDataGetBytePtr(data) else {
            return (0.5, true, nil)
        }

        let bytesPerPixel = cgImage.bitsPerPixel / 8
        let bytesPerRow = cgImage.bytesPerRow

        for row in 0..<gridSize {
            for col in 0..<gridSize {
                let x = (col * width) / gridSize
                let y = (row * height) / gridSize

                let offset = (y * bytesPerRow) + (x * bytesPerPixel)

                // RGB to luminance
                let r = Double(bytes[offset])
                let g = Double(bytes[offset + 1])
                let b = Double(bytes[offset + 2])

                let luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                brightnessValues.append(luminance)
                regionBrightness[row][col] = luminance
            }
        }

        // Calculate overall brightness
        let avgBrightness = brightnessValues.reduce(0, +) / Double(brightnessValues.count)

        // Check for evenness (compare quadrants)
        let topHalf = regionBrightness[0..<gridSize/2].flatMap { $0 }
        let bottomHalf = regionBrightness[gridSize/2..<gridSize].flatMap { $0 }
        let leftHalf = regionBrightness.flatMap { Array($0[0..<gridSize/2]) }
        let rightHalf = regionBrightness.flatMap { Array($0[gridSize/2..<gridSize]) }

        let topAvg = topHalf.reduce(0, +) / Double(topHalf.count)
        let bottomAvg = bottomHalf.reduce(0, +) / Double(bottomHalf.count)
        let leftAvg = leftHalf.reduce(0, +) / Double(leftHalf.count)
        let rightAvg = rightHalf.reduce(0, +) / Double(rightHalf.count)

        // Check if lighting is uneven (>20% difference between regions)
        let verticalDiff = abs(topAvg - bottomAvg)
        let horizontalDiff = abs(leftAvg - rightAvg)
        let isEven = verticalDiff < 0.2 && horizontalDiff < 0.2

        // Generate feedback
        var feedback: String?
        if avgBrightness < 0.25 {
            feedback = "Too dark"
        } else if avgBrightness > 0.85 {
            feedback = "Too bright"
        } else if !isEven {
            feedback = "Uneven lighting"
        }

        return (avgBrightness, isEven, feedback)
    }

    /// Calculate contrast of an image
    func calculateContrast(_ image: UIImage) -> Double {
        guard let cgImage = image.cgImage else { return 0.5 }

        let width = cgImage.width
        let height = cgImage.height

        guard let dataProvider = cgImage.dataProvider,
              let data = dataProvider.data,
              let bytes = CFDataGetBytePtr(data) else {
            return 0.5
        }

        let bytesPerPixel = cgImage.bitsPerPixel / 8
        let bytesPerRow = cgImage.bytesPerRow

        var minLuminance: Double = 1.0
        var maxLuminance: Double = 0.0

        // Sample image
        let step = max(1, (width * height) / 10000)
        var index = 0

        for y in stride(from: 0, to: height, by: Int(sqrt(Double(step)))) {
            for x in stride(from: 0, to: width, by: Int(sqrt(Double(step)))) {
                let offset = (y * bytesPerRow) + (x * bytesPerPixel)

                let r = Double(bytes[offset])
                let g = Double(bytes[offset + 1])
                let b = Double(bytes[offset + 2])

                let luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
                minLuminance = min(minLuminance, luminance)
                maxLuminance = max(maxLuminance, luminance)
                index += 1
            }
        }

        // Contrast is the range of luminance values
        let contrast = maxLuminance - minLuminance

        return contrast
    }

    /// Comprehensive image quality assessment
    func assessImageQuality(_ image: UIImage) -> ImageQualityResult {
        let sharpness = calculateSharpness(image)
        let (brightness, isEven, lightingFeedback) = assessLighting(image)
        let contrast = calculateContrast(image)

        var feedback: [ImageQualityResult.QualityFeedback] = []

        // Sharpness feedback
        if sharpness < 0.3 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .sharpness,
                message: "Hold steady",
                severity: .critical
            ))
        } else if sharpness < 0.5 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .sharpness,
                message: "Slightly blurry",
                severity: .warning
            ))
        }

        // Brightness feedback
        if brightness < 0.25 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .brightness,
                message: "Too dark",
                severity: .critical
            ))
        } else if brightness > 0.85 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .brightness,
                message: "Too bright",
                severity: .warning
            ))
        } else if brightness >= 0.35 && brightness <= 0.75 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .brightness,
                message: "Good lighting",
                severity: .info
            ))
        }

        // Contrast feedback
        if contrast < 0.3 {
            feedback.append(ImageQualityResult.QualityFeedback(
                type: .contrast,
                message: "Low contrast",
                severity: .warning
            ))
        }

        // Calculate overall score
        // Weights: sharpness 40%, brightness 35%, contrast 25%
        let sharpnessComponent = sharpness * 40
        let brightnessComponent: Double
        if brightness < 0.2 || brightness > 0.9 {
            brightnessComponent = 0
        } else if brightness < 0.35 || brightness > 0.75 {
            brightnessComponent = 20
        } else {
            brightnessComponent = 35
        }
        let contrastComponent = contrast * 25

        let overallScore = Int(sharpnessComponent + brightnessComponent + contrastComponent)

        // Quality is acceptable if score >= 45 or if we have good individual metrics
        let isAcceptable = overallScore >= 45 ||
            (sharpness >= 0.4 && brightness >= 0.25 && brightness <= 0.85)

        return ImageQualityResult(
            overallScore: min(100, overallScore),
            sharpnessScore: sharpness,
            brightnessScore: brightness,
            contrastScore: contrast,
            isAcceptable: isAcceptable,
            feedback: feedback
        )
    }

    /// Quick quality check for real-time feedback (optimized for performance)
    func quickQualityCheck(pixelBuffer: CVPixelBuffer) -> (sharpness: Double, brightness: Double, isAcceptable: Bool) {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            return (0.5, 0.5, true)
        }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)

        // Quick brightness sampling
        var brightnessSum: Double = 0
        var samples = 0

        // Quick sharpness via gradient magnitude
        var gradientSum: Double = 0
        var gradientSamples = 0

        let stepX = max(1, width / 20)
        let stepY = max(1, height / 20)

        for y in stride(from: stepY, to: height - stepY, by: stepY) {
            for x in stride(from: stepX, to: width - stepX, by: stepX) {
                let offset = y * bytesPerRow + x * 4
                let pixel = baseAddress.advanced(by: offset).assumingMemoryBound(to: UInt8.self)

                // Brightness
                let brightness = (Double(pixel[0]) + Double(pixel[1]) + Double(pixel[2])) / (3 * 255)
                brightnessSum += brightness
                samples += 1

                // Gradient for sharpness (simple Sobel-like)
                let offsetRight = y * bytesPerRow + (x + stepX) * 4
                let offsetDown = (y + stepY) * bytesPerRow + x * 4

                if offsetRight < bytesPerRow * height && offsetDown < bytesPerRow * height {
                    let pixelRight = baseAddress.advanced(by: offsetRight).assumingMemoryBound(to: UInt8.self)
                    let pixelDown = baseAddress.advanced(by: offsetDown).assumingMemoryBound(to: UInt8.self)

                    let grayCenter = Double(pixel[0]) * 0.299 + Double(pixel[1]) * 0.587 + Double(pixel[2]) * 0.114
                    let grayRight = Double(pixelRight[0]) * 0.299 + Double(pixelRight[1]) * 0.587 + Double(pixelRight[2]) * 0.114
                    let grayDown = Double(pixelDown[0]) * 0.299 + Double(pixelDown[1]) * 0.587 + Double(pixelDown[2]) * 0.114

                    let gradX = abs(grayRight - grayCenter)
                    let gradY = abs(grayDown - grayCenter)
                    gradientSum += sqrt(gradX * gradX + gradY * gradY)
                    gradientSamples += 1
                }
            }
        }

        let avgBrightness = samples > 0 ? brightnessSum / Double(samples) : 0.5
        let avgGradient = gradientSamples > 0 ? gradientSum / Double(gradientSamples) : 0

        // Normalize gradient to 0-1 sharpness score
        let sharpness = min(1.0, avgGradient / 50.0)

        // Check acceptability
        let isAcceptable = sharpness >= 0.3 && avgBrightness >= 0.2 && avgBrightness <= 0.9

        return (sharpness, avgBrightness, isAcceptable)
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

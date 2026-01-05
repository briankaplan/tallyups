import Foundation
import CoreImage
import UIKit
import Vision
import Accelerate

/// High-performance glare detection service for receipt scanning
/// Uses Core Image and Accelerate framework for efficient real-time analysis
final class GlareDetector {

    // MARK: - Types

    /// Result of glare analysis
    struct GlareResult {
        /// Whether significant glare was detected
        let hasGlare: Bool

        /// Severity level (0.0 = none, 1.0 = severe)
        let severity: CGFloat

        /// Regions where glare was detected (normalized 0-1 coordinates)
        let glareRegions: [CGRect]

        /// Percentage of image affected by glare
        let affectedPercentage: CGFloat

        /// Recommended action for the user
        let guidance: GlareGuidance

        /// Whether glare is blocking text (detected in receipt area)
        let isBlockingText: Bool

        static let none = GlareResult(
            hasGlare: false,
            severity: 0,
            glareRegions: [],
            affectedPercentage: 0,
            guidance: .none,
            isBlockingText: false
        )
    }

    /// Guidance for user when glare is detected
    enum GlareGuidance: Equatable {
        case none
        case tiltReceipt
        case moveLight
        case adjustAngle
        case severGlare

        var message: String {
            switch self {
            case .none:
                return ""
            case .tiltReceipt:
                return "Tilt the receipt slightly"
            case .moveLight:
                return "Move away from direct light"
            case .adjustAngle:
                return "Adjust your angle"
            case .severGlare:
                return "Strong glare detected"
            }
        }

        var icon: String {
            switch self {
            case .none:
                return ""
            case .tiltReceipt:
                return "rectangle.portrait.rotate"
            case .moveLight:
                return "lightbulb.slash"
            case .adjustAngle:
                return "arrow.triangle.2.circlepath"
            case .severGlare:
                return "exclamationmark.triangle.fill"
            }
        }
    }

    // MARK: - Configuration

    /// Threshold for considering a pixel as overexposed (0-1)
    private let brightnessThreshold: CGFloat = 0.92

    /// Minimum cluster size to be considered glare (relative to image)
    private let minimumGlareAreaRatio: CGFloat = 0.008

    /// Threshold for severity where we warn user
    private let warningSeverityThreshold: CGFloat = 0.15

    /// Threshold for blocking capture
    private let blockingSeverityThreshold: CGFloat = 0.35

    /// Sample grid size for efficient processing
    private let sampleGridSize: Int = 40

    // MARK: - Cached Resources

    private let ciContext: CIContext
    private var lastAnalysisTime: CFTimeInterval = 0
    private let minimumAnalysisInterval: CFTimeInterval = 0.05 // 20Hz max

    // MARK: - Initialization

    init() {
        // Use Metal for GPU-accelerated processing
        if let metalDevice = MTLCreateSystemDefaultDevice() {
            self.ciContext = CIContext(mtlDevice: metalDevice, options: [
                .cacheIntermediates: false,
                .priorityRequestLow: true
            ])
        } else {
            self.ciContext = CIContext(options: [
                .useSoftwareRenderer: false,
                .cacheIntermediates: false
            ])
        }
    }

    // MARK: - Public API

    /// Analyze a pixel buffer for glare (optimized for real-time use)
    /// - Parameters:
    ///   - pixelBuffer: The camera frame to analyze
    ///   - receiptRect: Optional rectangle defining the receipt area (normalized 0-1)
    /// - Returns: GlareResult with detection info
    func analyzeFrame(_ pixelBuffer: CVPixelBuffer, receiptRect: VNRectangleObservation? = nil) -> GlareResult {
        // Rate limit analysis
        let currentTime = CACurrentMediaTime()
        guard currentTime - lastAnalysisTime >= minimumAnalysisInterval else {
            return .none
        }
        lastAnalysisTime = currentTime

        // Get buffer dimensions
        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)

        // Lock buffer for reading
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else {
            return .none
        }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)

        // Analyze using grid sampling for performance
        let result = analyzeWithGridSampling(
            baseAddress: baseAddress,
            width: width,
            height: height,
            bytesPerRow: bytesPerRow,
            receiptRect: receiptRect
        )

        return result
    }

    /// Analyze a UIImage for glare (for captured images)
    /// - Parameter image: The image to analyze
    /// - Returns: GlareResult with detection info
    func analyzeImage(_ image: UIImage) -> GlareResult {
        guard let cgImage = image.cgImage else {
            return .none
        }

        let ciImage = CIImage(cgImage: cgImage)
        return analyzeCIImage(ciImage)
    }

    // MARK: - Private Analysis Methods

    /// Grid-based sampling for real-time performance
    private func analyzeWithGridSampling(
        baseAddress: UnsafeMutableRawPointer,
        width: Int,
        height: Int,
        bytesPerRow: Int,
        receiptRect: VNRectangleObservation?
    ) -> GlareResult {

        var overexposedCount = 0
        var totalSamples = 0
        var glarePoints: [(x: Int, y: Int)] = []
        var textAreaGlareCount = 0
        var textAreaSamples = 0

        // Define receipt bounds if available
        let receiptBounds: CGRect?
        if let rect = receiptRect {
            receiptBounds = CGRect(
                x: CGFloat(width) * rect.bottomLeft.x,
                y: CGFloat(height) * (1 - rect.topLeft.y),
                width: CGFloat(width) * (rect.topRight.x - rect.topLeft.x),
                height: CGFloat(height) * (rect.topLeft.y - rect.bottomLeft.y)
            )
        } else {
            receiptBounds = nil
        }

        // Sample grid points
        let stepX = max(1, width / sampleGridSize)
        let stepY = max(1, height / sampleGridSize)

        for y in stride(from: stepY / 2, to: height, by: stepY) {
            for x in stride(from: stepX / 2, to: width, by: stepX) {
                let offset = y * bytesPerRow + x * 4
                let pixel = baseAddress.advanced(by: offset).assumingMemoryBound(to: UInt8.self)

                // BGRA format - calculate luminance
                let b = CGFloat(pixel[0]) / 255.0
                let g = CGFloat(pixel[1]) / 255.0
                let r = CGFloat(pixel[2]) / 255.0

                // Standard luminance calculation
                let luminance = 0.299 * r + 0.587 * g + 0.114 * b

                // Also check for near-white pixels (glare often saturates all channels)
                let isOverexposed = luminance > brightnessThreshold ||
                    (r > 0.95 && g > 0.95 && b > 0.95)

                totalSamples += 1

                if isOverexposed {
                    overexposedCount += 1
                    glarePoints.append((x: x, y: y))
                }

                // Check if within receipt area
                if let bounds = receiptBounds {
                    let point = CGPoint(x: CGFloat(x), y: CGFloat(y))
                    if bounds.contains(point) {
                        textAreaSamples += 1
                        if isOverexposed {
                            textAreaGlareCount += 1
                        }
                    }
                }
            }
        }

        guard totalSamples > 0 else { return .none }

        // Calculate metrics
        let overexposedRatio = CGFloat(overexposedCount) / CGFloat(totalSamples)
        let textAreaGlareRatio = textAreaSamples > 0 ?
            CGFloat(textAreaGlareCount) / CGFloat(textAreaSamples) : 0

        // Cluster glare points to find regions
        let glareRegions = clusterGlarePoints(
            glarePoints,
            imageWidth: width,
            imageHeight: height,
            stepX: stepX,
            stepY: stepY
        )

        // Calculate severity based on multiple factors
        let severity = calculateSeverity(
            overexposedRatio: overexposedRatio,
            textAreaRatio: textAreaGlareRatio,
            clusterCount: glareRegions.count
        )

        // Determine if glare is blocking text
        let isBlockingText = textAreaGlareRatio > 0.1

        // Determine guidance
        let guidance = determineGuidance(
            severity: severity,
            overexposedRatio: overexposedRatio,
            hasTextAreaGlare: isBlockingText
        )

        // Has glare if severity exceeds warning threshold
        let hasGlare = severity >= warningSeverityThreshold

        return GlareResult(
            hasGlare: hasGlare,
            severity: severity,
            glareRegions: glareRegions,
            affectedPercentage: overexposedRatio * 100,
            guidance: guidance,
            isBlockingText: isBlockingText
        )
    }

    /// Analyze CIImage for more detailed glare detection
    private func analyzeCIImage(_ ciImage: CIImage) -> GlareResult {
        let extent = ciImage.extent

        // Apply threshold filter to find bright spots
        guard let thresholdFilter = CIFilter(name: "CIColorThreshold") else {
            return .none
        }
        thresholdFilter.setValue(ciImage, forKey: kCIInputImageKey)
        thresholdFilter.setValue(brightnessThreshold, forKey: "inputThreshold")

        guard let thresholded = thresholdFilter.outputImage else {
            return .none
        }

        // Calculate histogram of thresholded image
        var bitmap = [UInt8](repeating: 0, count: 4)
        let targetRect = CGRect(x: 0, y: 0, width: 1, height: 1)

        // Average the thresholded image
        guard let areaAverage = CIFilter(name: "CIAreaAverage") else {
            return .none
        }
        areaAverage.setValue(thresholded, forKey: kCIInputImageKey)
        areaAverage.setValue(CIVector(cgRect: extent), forKey: "inputExtent")

        guard let avgOutput = areaAverage.outputImage else {
            return .none
        }

        ciContext.render(
            avgOutput,
            toBitmap: &bitmap,
            rowBytes: 4,
            bounds: targetRect,
            format: .RGBA8,
            colorSpace: CGColorSpaceCreateDeviceRGB()
        )

        let overexposedRatio = CGFloat(bitmap[0]) / 255.0
        let severity = min(1.0, overexposedRatio * 3) // Scale up for visibility

        return GlareResult(
            hasGlare: severity >= warningSeverityThreshold,
            severity: severity,
            glareRegions: [],
            affectedPercentage: overexposedRatio * 100,
            guidance: determineGuidance(severity: severity, overexposedRatio: overexposedRatio, hasTextAreaGlare: false),
            isBlockingText: false
        )
    }

    /// Cluster nearby glare points into regions
    private func clusterGlarePoints(
        _ points: [(x: Int, y: Int)],
        imageWidth: Int,
        imageHeight: Int,
        stepX: Int,
        stepY: Int
    ) -> [CGRect] {
        guard !points.isEmpty else { return [] }

        var regions: [CGRect] = []
        var visited = Set<Int>()
        let clusterDistance = max(stepX, stepY) * 2

        for (index, point) in points.enumerated() {
            guard !visited.contains(index) else { continue }

            // Start new cluster
            var clusterPoints = [point]
            visited.insert(index)

            // Find nearby points
            for (otherIndex, otherPoint) in points.enumerated() {
                guard !visited.contains(otherIndex) else { continue }

                let dx = abs(point.x - otherPoint.x)
                let dy = abs(point.y - otherPoint.y)

                if dx <= clusterDistance && dy <= clusterDistance {
                    clusterPoints.append(otherPoint)
                    visited.insert(otherIndex)
                }
            }

            // Create bounding rect for cluster
            if clusterPoints.count >= 2 {
                let minX = clusterPoints.map { $0.x }.min() ?? 0
                let maxX = clusterPoints.map { $0.x }.max() ?? 0
                let minY = clusterPoints.map { $0.y }.min() ?? 0
                let maxY = clusterPoints.map { $0.y }.max() ?? 0

                // Convert to normalized coordinates
                let rect = CGRect(
                    x: CGFloat(minX) / CGFloat(imageWidth),
                    y: CGFloat(minY) / CGFloat(imageHeight),
                    width: CGFloat(maxX - minX) / CGFloat(imageWidth),
                    height: CGFloat(maxY - minY) / CGFloat(imageHeight)
                )

                // Only add if significant size
                if rect.width * rect.height >= minimumGlareAreaRatio {
                    regions.append(rect)
                }
            }
        }

        return regions
    }

    /// Calculate overall severity from multiple factors
    private func calculateSeverity(
        overexposedRatio: CGFloat,
        textAreaRatio: CGFloat,
        clusterCount: Int
    ) -> CGFloat {
        // Weight factors
        let overexposedWeight: CGFloat = 0.4
        let textAreaWeight: CGFloat = 0.45
        let clusterWeight: CGFloat = 0.15

        // Normalize cluster count (cap at 5 regions)
        let normalizedClusterCount = min(CGFloat(clusterCount) / 5.0, 1.0)

        // Calculate weighted severity
        let severity = (overexposedRatio * 3 * overexposedWeight) +
                      (textAreaRatio * 2 * textAreaWeight) +
                      (normalizedClusterCount * clusterWeight)

        return min(1.0, severity)
    }

    /// Determine appropriate guidance based on glare analysis
    private func determineGuidance(
        severity: CGFloat,
        overexposedRatio: CGFloat,
        hasTextAreaGlare: Bool
    ) -> GlareGuidance {
        if severity < warningSeverityThreshold {
            return .none
        }

        if severity >= blockingSeverityThreshold {
            return .severGlare
        }

        if hasTextAreaGlare {
            return .tiltReceipt
        }

        if overexposedRatio > 0.15 {
            return .moveLight
        }

        return .adjustAngle
    }

    // MARK: - Utility

    /// Check if glare severity should block auto-capture
    func shouldBlockCapture(_ result: GlareResult) -> Bool {
        return result.severity >= blockingSeverityThreshold || result.isBlockingText
    }

    /// Check if glare severity warrants a warning
    func shouldWarn(_ result: GlareResult) -> Bool {
        return result.hasGlare
    }
}

// MARK: - Analytics Extension

extension GlareDetector.GlareResult {
    /// Convert to dictionary for analytics logging
    var analyticsData: [String: Any] {
        return [
            "has_glare": hasGlare,
            "severity": severity,
            "affected_percentage": affectedPercentage,
            "region_count": glareRegions.count,
            "is_blocking_text": isBlockingText,
            "guidance": guidance.message
        ]
    }
}

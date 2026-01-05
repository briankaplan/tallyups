import SwiftUI
import AVFoundation
import Vision
import CoreImage
import VisionKit

// MARK: - World Class Receipt Scanner

/// Premium full-screen receipt scanner with intelligent edge detection,
/// tap-to-focus, lighting analysis, burst mode, and smart enhancement
struct FullScreenScannerView: View {
    @StateObject private var camera = PremiumCameraController()
    @Binding var isPresented: Bool
    let onCapture: (UIImage) -> Void

    // Scanner State
    @State private var scanLineOffset: CGFloat = 0
    @State private var isScanning = true
    @State private var flashEnabled = false
    @State private var autoCapture = true
    @State private var batchMode = false
    @State private var batchImages: [UIImage] = []

    // Captured Images
    @State private var capturedImage: UIImage?
    @State private var showingPreview = false
    @State private var showingBatchReview = false

    // UI State
    @State private var showingDocumentScanner = false
    @State private var showZoomSlider = false
    @State private var showingSettings = false

    // Focus Animation
    @State private var focusPoint: CGPoint?
    @State private var showFocusRing = false

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Camera Preview
                PremiumPreviewLayer(controller: camera)
                    .ignoresSafeArea()
                    .gesture(tapToFocusGesture(in: geometry))
                    .gesture(pinchToZoomGesture)

                // Edge Detection Overlay
                EdgeOverlayView(
                    detectedRectangle: camera.detectedRectangle,
                    viewSize: geometry.size,
                    isStable: camera.isEdgeStable
                )
                .ignoresSafeArea()
                .animation(.easeInOut(duration: 0.15), value: camera.detectedRectangle != nil)

                // Scanning Guide Overlay
                scanningOverlay(geometry: geometry)

                // Live Text Preview
                if camera.isEdgeStable, let texts = camera.detectedTexts, !texts.isEmpty {
                    liveTextPreview(texts: texts, geometry: geometry)
                }

                // Focus Ring Animation
                if showFocusRing, let point = focusPoint {
                    FocusRingView(point: point)
                }

                // Glare Region Overlay
                if camera.hasGlareWarning {
                    GlareOverlayView(
                        glareResult: camera.glareResult,
                        viewSize: geometry.size
                    )
                    .ignoresSafeArea()
                    .allowsHitTesting(false)
                }

                // Controls Layer
                VStack(spacing: 0) {
                    topBar
                    Spacer()

                    // Glare Warning Indicator (shown above lighting indicator)
                    if camera.hasGlareWarning {
                        glareWarningIndicator
                    }

                    lightingIndicator
                    edgeStatusIndicator
                    if showZoomSlider { zoomSlider }
                    bottomControls(geometry: geometry)
                }

                // Batch Counter
                if batchMode && !batchImages.isEmpty {
                    batchCounter
                }

                // Quality Score Overlay (top-left, shown when receipt detected)
                VStack {
                    HStack {
                        QualityScoreOverlay(
                            qualityScore: camera.qualityScore,
                            qualityLevel: camera.qualityLevel,
                            sharpnessScore: camera.sharpnessScore,
                            brightnessScore: camera.brightnessScore,
                            feedback: camera.qualityFeedback,
                            isVisible: camera.detectedRectangle != nil
                        )
                        Spacer()
                    }
                    .padding(.leading, 16)
                    .padding(.top, 120)
                    Spacer()
                }
            }
        }
        .statusBarHidden()
        .onAppear {
            camera.configure()
            camera.start()
            camera.onAutoCapture = handleAutoCapture
            startScanAnimation()
        }
        .onDisappear {
            camera.stop()
        }
        .sheet(isPresented: $showingDocumentScanner) {
            DocumentScannerView { images in
                handleDocumentScan(images)
            }
        }
        .fullScreenCover(isPresented: $showingPreview) {
            if let image = capturedImage {
                PremiumPreviewView(
                    image: image,
                    ocrPreview: camera.detectedTexts?.joined(separator: " "),
                    onConfirm: handlePreviewConfirm
                )
            }
        }
        .fullScreenCover(isPresented: $showingBatchReview) {
            BatchReviewView(images: batchImages) { confirmedImages in
                handleBatchConfirm(confirmedImages)
            }
        }
    }

    // MARK: - Top Bar

    private var topBar: some View {
        HStack(spacing: 12) {
            // Close
            GlassButton(icon: "xmark") {
                if batchMode && !batchImages.isEmpty {
                    showingBatchReview = true
                } else {
                    isPresented = false
                }
            }
            .accessibilityLabel(batchMode && !batchImages.isEmpty ? "Review batch" : "Close scanner")
            .accessibilityHint(batchMode && !batchImages.isEmpty ? "Review \(batchImages.count) captured receipts" : "Returns to previous screen")

            Spacer()

            // Batch Mode Toggle
            GlassButton(
                icon: batchMode ? "square.stack.fill" : "square.stack",
                isActive: batchMode,
                label: batchMode ? "\(batchImages.count)" : nil
            ) {
                withAnimation(.spring(response: 0.3)) {
                    batchMode.toggle()
                    if !batchMode { batchImages.removeAll() }
                }
            }
            .accessibilityLabel("Batch mode, \(batchMode ? "on" : "off")")
            .accessibilityValue(batchMode ? "\(batchImages.count) receipts captured" : "")
            .accessibilityHint("Double tap to \(batchMode ? "disable" : "enable") capturing multiple receipts")

            // Auto Toggle
            GlassButton(
                icon: autoCapture ? "a.circle.fill" : "a.circle",
                isActive: autoCapture,
                label: "Auto"
            ) {
                withAnimation(.spring(response: 0.3)) {
                    autoCapture.toggle()
                }
            }
            .accessibilityLabel("Auto capture, \(autoCapture ? "on" : "off")")
            .accessibilityHint("When enabled, automatically captures when receipt is detected and stable")

            // Flash
            GlassButton(
                icon: flashEnabled ? "bolt.fill" : "bolt.slash.fill",
                isActive: flashEnabled,
                tint: flashEnabled ? .yellow : nil
            ) {
                flashEnabled.toggle()
                camera.toggleFlash(flashEnabled)
            }
            .accessibilityLabel("Flash, \(flashEnabled ? "on" : "off")")
            .accessibilityHint("Double tap to toggle camera flash")

            // Settings
            GlassButton(icon: "gearshape.fill") {
                showingSettings.toggle()
            }
            .accessibilityLabel("Scanner settings")
        }
        .padding(.horizontal, 16)
        .padding(.top, 60)
    }

    // MARK: - Lighting Indicator

    private var lightingIndicator: some View {
        Group {
            if let quality = camera.lightingQuality, quality != .good {
                HStack(spacing: 8) {
                    Image(systemName: quality.icon)
                        .foregroundColor(quality.color)
                        .accessibilityHidden(true)
                    Text(quality.message)
                        .font(.caption.weight(.medium))
                        .foregroundColor(.white)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 8)
                .background(quality.color.opacity(0.2))
                .background(.ultraThinMaterial.opacity(0.8))
                .cornerRadius(20)
                .transition(.move(edge: .top).combined(with: .opacity))
                .animation(.spring(response: 0.4), value: camera.lightingQuality)
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Lighting warning: \(quality.message)")
            }
        }
        .padding(.bottom, 8)
    }

    // MARK: - Edge Status Indicator

    private var edgeStatusIndicator: some View {
        VStack(spacing: 8) {
            if camera.detectedRectangle != nil {
                // Smart Guidance Hint
                SmartGuidanceView(
                    guidance: camera.currentGuidance,
                    isStable: camera.isEdgeStable,
                    confidence: camera.captureConfidence,
                    stabilityProgress: camera.stabilityProgress,
                    showProgress: camera.isEdgeStable && autoCapture
                )
            } else {
                // Initial guidance - animated hint
                ScannerGuidanceHint(
                    icon: "viewfinder",
                    message: "Position receipt within frame",
                    color: .white,
                    isAnimating: true
                )
            }
        }
        .padding(.bottom, 12)
        .animation(.spring(response: 0.3), value: camera.detectedRectangle != nil)
        .animation(.spring(response: 0.3), value: camera.isEdgeStable)
        .animation(.spring(response: 0.3), value: camera.currentGuidance)
    }

    // MARK: - Glare Warning Indicator

    private var glareWarningIndicator: some View {
        let result = camera.glareResult
        let severity = result.severity
        let warningColor: Color = severity >= 0.35 ? .red : (severity >= 0.20 ? .orange : .yellow)

        return VStack(spacing: 8) {
            HStack(spacing: 10) {
                // Animated warning icon
                Image(systemName: "sun.max.trianglebadge.exclamationmark.fill")
                    .font(.system(size: 18, weight: .semibold))
                    .foregroundColor(warningColor)
                    .symbolEffect(.pulse, options: .repeating)

                VStack(alignment: .leading, spacing: 2) {
                    Text(result.guidance.message.isEmpty ? "Glare detected" : result.guidance.message)
                        .font(.subheadline.weight(.semibold))
                        .foregroundColor(.white)

                    if result.isBlockingText {
                        Text("May affect text readability")
                            .font(.caption2)
                            .foregroundColor(.white.opacity(0.7))
                    }
                }

                Spacer()

                // Override button if glare is blocking capture
                if camera.glareBlocksCapture {
                    Button(action: {
                        camera.toggleGlareOverride()
                        HapticService.shared.selection()
                    }) {
                        Text("Capture Anyway")
                            .font(.caption.weight(.semibold))
                            .foregroundColor(.black)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(warningColor)
                            .cornerRadius(12)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(warningColor.opacity(0.15))
            .background(.ultraThinMaterial.opacity(0.9))
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(warningColor.opacity(0.3), lineWidth: 1)
            )

            // Severity indicator bar
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Capsule()
                        .fill(Color.white.opacity(0.2))

                    Capsule()
                        .fill(
                            LinearGradient(
                                colors: [.yellow, .orange, .red],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: geo.size.width * severity)
                }
            }
            .frame(height: 4)
            .padding(.horizontal, 20)
        }
        .padding(.horizontal, 16)
        .padding(.bottom, 8)
        .transition(.move(edge: .top).combined(with: .opacity))
        .animation(.spring(response: 0.4), value: camera.hasGlareWarning)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Glare warning: \(result.guidance.message). Severity \(Int(severity * 100)) percent")
    }

    // MARK: - Zoom Slider

    private var zoomSlider: some View {
        HStack(spacing: 16) {
            Image(systemName: "minus.magnifyingglass")
                .foregroundColor(.white.opacity(0.7))
                .accessibilityHidden(true)

            Slider(value: $camera.zoomLevel, in: 1.0...5.0)
                .accentColor(.tallyAccent)
                .onChange(of: camera.zoomLevel) { _, newValue in
                    camera.setZoom(newValue)
                }
                .accessibilityLabel("Camera zoom")
                .accessibilityValue("\(String(format: "%.1f", camera.zoomLevel))x")
                .accessibilityHint("Adjust from 1x to 5x zoom")

            Image(systemName: "plus.magnifyingglass")
                .foregroundColor(.white.opacity(0.7))
                .accessibilityHidden(true)
        }
        .padding(.horizontal, 30)
        .padding(.vertical, 12)
        .background(.ultraThinMaterial.opacity(0.8))
        .cornerRadius(25)
        .padding(.horizontal, 20)
        .padding(.bottom, 12)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    // MARK: - Scanning Overlay

    private func scanningOverlay(geometry: GeometryProxy) -> some View {
        let scanAreaWidth = geometry.size.width * 0.88
        let scanAreaHeight = scanAreaWidth * 1.4

        return ZStack {
            // Dimmed overlay when no detection
            if camera.detectedRectangle == nil {
                Color.black.opacity(0.5)
                    .ignoresSafeArea()
                    .mask(
                        Rectangle()
                            .overlay(
                                RoundedRectangle(cornerRadius: 24)
                                    .frame(width: scanAreaWidth, height: scanAreaHeight)
                                    .blendMode(.destinationOut)
                            )
                    )

                // Animated guide border
                RoundedRectangle(cornerRadius: 24)
                    .strokeBorder(
                        AngularGradient(
                            colors: [.tallyAccent, .tallyAccent.opacity(0.3), .tallyAccent],
                            center: .center,
                            startAngle: .degrees(0),
                            endAngle: .degrees(360)
                        ),
                        lineWidth: 2
                    )
                    .frame(width: scanAreaWidth, height: scanAreaHeight)
                    .rotationEffect(.degrees(isScanning ? 360 : 0))
                    .animation(.linear(duration: 8).repeatForever(autoreverses: false), value: isScanning)

                // Corner brackets
                CornerBrackets(width: scanAreaWidth, height: scanAreaHeight)
            }

            // Animated scan line
            if isScanning && camera.detectedRectangle == nil {
                ScanLineView(width: scanAreaWidth - 48, offset: scanLineOffset)
                    .offset(y: -scanAreaHeight / 2 + 30)
            }
        }
    }

    // MARK: - Live Text Preview

    private func liveTextPreview(texts: [String], geometry: GeometryProxy) -> some View {
        VStack(alignment: .leading, spacing: 4) {
            HStack {
                Image(systemName: "text.viewfinder")
                    .foregroundColor(.tallyAccent)
                Text("Live Preview")
                    .font(.caption.weight(.semibold))
                    .foregroundColor(.tallyAccent)
            }

            Text(texts.prefix(3).joined(separator: " • "))
                .font(.caption)
                .foregroundColor(.white.opacity(0.9))
                .lineLimit(2)
        }
        .padding(12)
        .frame(maxWidth: geometry.size.width * 0.8)
        .background(.ultraThinMaterial)
        .cornerRadius(12)
        .position(x: geometry.size.width / 2, y: 180)
        .transition(.opacity.combined(with: .scale(scale: 0.9)))
    }

    // MARK: - Bottom Controls

    private func bottomControls(geometry: GeometryProxy) -> some View {
        VStack(spacing: 20) {
            // Mode Selector
            HStack(spacing: 24) {
                ModeTab(icon: "camera.fill", label: "Smart", isSelected: true)
                    .accessibilityLabel("Smart mode, selected")
                    .accessibilityHint("Automatic receipt detection with edge tracking")
                ModeTab(icon: "doc.viewfinder", label: "Document", isSelected: false) {
                    showingDocumentScanner = true
                }
                .accessibilityLabel("Document mode")
                .accessibilityHint("Open iOS document scanner for multi-page documents")
                ModeTab(icon: "photo.stack", label: "Batch", isSelected: batchMode) {
                    withAnimation { batchMode.toggle() }
                }
                .accessibilityLabel("Batch mode, \(batchMode ? "selected" : "not selected")")
                .accessibilityHint("Capture multiple receipts in a row")
            }

            // Capture Controls
            HStack(spacing: 40) {
                // Gallery / Zoom Toggle
                GlassCircleButton(icon: showZoomSlider ? "magnifyingglass" : "photo.fill", size: 54) {
                    withAnimation(.spring(response: 0.3)) {
                        showZoomSlider.toggle()
                    }
                }
                .accessibilityLabel(showZoomSlider ? "Hide zoom slider" : "Show zoom slider")
                .accessibilityHint("Toggle camera zoom controls")

                // Main Capture Button
                CaptureButton(
                    isActive: camera.detectedRectangle != nil,
                    isCapturing: camera.isCapturing,
                    progress: camera.isEdgeStable ? camera.stabilityProgress : 0
                ) {
                    performCapture()
                }
                .accessibilityLabel(captureButtonAccessibilityLabel)
                .accessibilityHint(camera.detectedRectangle != nil ? "Capture the receipt" : "Point camera at a receipt first")

                // Flip Camera
                GlassCircleButton(icon: "camera.rotate.fill", size: 54) {
                    camera.flipCamera()
                }
                .accessibilityLabel("Switch camera")
                .accessibilityHint("Toggle between front and back camera")
            }
        }
        .padding(.bottom, 40)
    }

    private var captureButtonAccessibilityLabel: String {
        if camera.isCapturing {
            return "Capturing receipt"
        } else if camera.detectedRectangle != nil {
            if camera.isEdgeStable {
                return "Capture receipt, \(Int(camera.stabilityProgress * 100)) percent ready"
            } else {
                return "Capture receipt, hold steady"
            }
        } else {
            return "Capture button, no receipt detected"
        }
    }

    // MARK: - Batch Counter

    private var batchCounter: some View {
        VStack {
            HStack {
                Spacer()
                HStack(spacing: 6) {
                    Image(systemName: "square.stack.fill")
                    Text("\(batchImages.count)")
                        .font(.headline.bold())
                }
                .foregroundColor(.white)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(Color.tallyAccent)
                .cornerRadius(25)
                .padding(20)
            }
            Spacer()
        }
        .padding(.top, 120)
    }

    // MARK: - Gestures

    private func tapToFocusGesture(in geometry: GeometryProxy) -> some Gesture {
        SpatialTapGesture()
            .onEnded { event in
                let point = event.location
                focusPoint = point

                // Convert to normalized coordinates
                let normalizedPoint = CGPoint(
                    x: point.x / geometry.size.width,
                    y: point.y / geometry.size.height
                )

                camera.focus(at: normalizedPoint)

                // Animate focus ring
                withAnimation(.spring(response: 0.3)) {
                    showFocusRing = true
                }
                DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                    withAnimation(.easeOut(duration: 0.3)) {
                        showFocusRing = false
                    }
                }

                // Haptic feedback for focus
                HapticService.shared.focusAchieved()
            }
    }

    private var pinchToZoomGesture: some Gesture {
        MagnificationGesture()
            .onChanged { scale in
                let newZoom = camera.baseZoom * scale
                camera.zoomLevel = min(max(newZoom, 1.0), 5.0)
                camera.setZoom(camera.zoomLevel)
            }
            .onEnded { _ in
                camera.baseZoom = camera.zoomLevel
            }
    }

    // MARK: - Actions

    private func startScanAnimation() {
        let height = UIScreen.main.bounds.width * 0.88 * 1.4
        withAnimation(.easeInOut(duration: 2.5).repeatForever(autoreverses: true)) {
            scanLineOffset = height - 60
        }
    }

    private func performCapture() {
        // Haptic feedback: shutter click for capture
        HapticService.shared.playCapturePattern()

        camera.captureBurst { images in
            // Pick best image from burst
            if let best = selectBestImage(from: images) {
                if batchMode {
                    batchImages.append(best)
                    camera.resetStability()
                    // Haptic feedback: scan success for batch capture
                    HapticService.shared.scanSuccess()
                } else {
                    capturedImage = best
                    showingPreview = true
                    // Haptic feedback: success for single capture
                    HapticService.shared.success()
                }
            } else {
                // Haptic feedback: error if capture failed
                HapticService.shared.captureError()
            }
        }
    }

    private func handleAutoCapture(_ image: UIImage) {
        guard autoCapture else { return }

        if batchMode {
            batchImages.append(image)
            camera.resetStability()
            // Haptic feedback: scan success for auto batch capture
            HapticService.shared.scanSuccess()
        } else {
            capturedImage = image
            showingPreview = true
            // Haptic feedback: success for auto single capture
            HapticService.shared.success()
        }
    }

    private func handleDocumentScan(_ images: [UIImage]) {
        showingDocumentScanner = false
        if batchMode {
            batchImages.append(contentsOf: images)
        } else if let first = images.first {
            capturedImage = first
            showingPreview = true
        }
    }

    private func handlePreviewConfirm(_ confirmed: Bool) {
        if confirmed, let image = capturedImage {
            onCapture(image)
            isPresented = false
        } else {
            capturedImage = nil
            showingPreview = false
            camera.resetStability()
        }
    }

    private func handleBatchConfirm(_ images: [UIImage]) {
        showingBatchReview = false
        for image in images {
            onCapture(image)
        }
        isPresented = false
    }

    private func selectBestImage(from images: [UIImage]) -> UIImage? {
        guard !images.isEmpty else { return nil }
        if images.count == 1 { return images.first }

        // Score images by sharpness using Laplacian variance
        var bestImage = images.first
        var bestScore: CGFloat = 0

        for image in images {
            if let score = calculateSharpness(image), score > bestScore {
                bestScore = score
                bestImage = image
            }
        }

        return bestImage
    }

    private func calculateSharpness(_ image: UIImage) -> CGFloat? {
        guard let cgImage = image.cgImage else { return nil }
        let ciImage = CIImage(cgImage: cgImage)

        let filter = CIFilter(name: "CILaplacian")
        filter?.setValue(ciImage, forKey: kCIInputImageKey)

        guard let output = filter?.outputImage else { return nil }

        var bitmap = [UInt8](repeating: 0, count: 4)
        let context = CIContext()
        context.render(output, toBitmap: &bitmap, rowBytes: 4, bounds: CGRect(x: 0, y: 0, width: 1, height: 1), format: .RGBA8, colorSpace: CGColorSpaceCreateDeviceRGB())

        return CGFloat(bitmap[0])
    }
}

// MARK: - Premium Camera Controller

class PremiumCameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    private var photoOutput = AVCapturePhotoOutput()
    private var videoOutput = AVCaptureVideoDataOutput()
    private var currentDevice: AVCaptureDevice?
    private var captureCompletion: (([UIImage]) -> Void)?
    private var burstCount = 0
    private var burstImages: [UIImage] = []

    @Published var detectedRectangle: VNRectangleObservation?
    @Published var detectedTexts: [String]?
    @Published var isEdgeStable = false
    @Published var stabilityProgress: CGFloat = 0
    @Published var captureConfidence: CGFloat = 0
    @Published var lightingQuality: LightingQuality?
    @Published var zoomLevel: CGFloat = 1.0
    @Published var isCapturing = false
    @Published var currentGuidance: ScannerGuidance = .positionReceipt

    // Glare Detection
    @Published var glareResult: GlareDetector.GlareResult = .none
    @Published var hasGlareWarning: Bool = false
    @Published var glareBlocksCapture: Bool = false
    private let glareDetector = GlareDetector()
    private var glareCheckCounter = 0
    private let glareCheckInterval = 5 // Check every 5th processed frame for performance
    var allowCaptureWithGlare: Bool = false // Manual override for glare blocking

    // Quality Score Properties
    @Published var qualityScore: Int = 0  // 0-100
    @Published var sharpnessScore: Double = 0.5  // 0-1
    @Published var brightnessScore: Double = 0.5  // 0-1
    @Published var qualityFeedback: String?
    @Published var isQualityAcceptable: Bool = true
    @Published var qualityLevel: QualityLevel = .good
    private var qualityCheckCounter = 0
    private let qualityCheckInterval = 6 // Check every 6th processed frame for performance

    enum QualityLevel: String {
        case excellent = "Excellent"
        case good = "Good"
        case fair = "Fair"
        case poor = "Poor"

        var color: Color {
            switch self {
            case .excellent: return .green
            case .good: return .green
            case .fair: return .yellow
            case .poor: return .red
            }
        }

        var icon: String {
            switch self {
            case .excellent: return "checkmark.circle.fill"
            case .good: return "checkmark.circle"
            case .fair: return "exclamationmark.circle"
            case .poor: return "xmark.circle"
            }
        }
    }

    var baseZoom: CGFloat = 1.0
    var onAutoCapture: ((UIImage) -> Void)?

    // Smart Guidance Types
    enum ScannerGuidance: Equatable {
        case positionReceipt
        case moveCloser
        case moveFarther
        case tiltLess
        case holdSteady
        case capturing
        case perfect
        case glareDetected(severity: GlareSeverity)

        enum GlareSeverity: Equatable {
            case mild
            case moderate
            case severe
        }

        var icon: String {
            switch self {
            case .positionReceipt: return "viewfinder"
            case .moveCloser: return "arrow.up.left.and.arrow.down.right"
            case .moveFarther: return "arrow.down.right.and.arrow.up.left"
            case .tiltLess: return "rectangle.portrait.rotate"
            case .holdSteady: return "hand.raised.fill"
            case .capturing: return "camera.fill"
            case .perfect: return "checkmark.circle.fill"
            case .glareDetected: return "sun.max.trianglebadge.exclamationmark.fill"
            }
        }

        var message: String {
            switch self {
            case .positionReceipt: return "Position receipt in frame"
            case .moveCloser: return "Move closer to receipt"
            case .moveFarther: return "Move back a little"
            case .tiltLess: return "Hold phone more level"
            case .holdSteady: return "Hold steady..."
            case .capturing: return "Capturing..."
            case .perfect: return "Perfect!"
            case .glareDetected(let severity):
                switch severity {
                case .mild: return "Slight glare - try tilting"
                case .moderate: return "Glare detected - tilt receipt"
                case .severe: return "Strong glare - move away from light"
                }
            }
        }

        var color: Color {
            switch self {
            case .positionReceipt: return .white
            case .moveCloser, .moveFarther, .tiltLess: return .orange
            case .holdSteady: return .tallyAccent
            case .capturing: return .blue
            case .perfect: return .green
            case .glareDetected(let severity):
                switch severity {
                case .mild: return .yellow
                case .moderate: return .orange
                case .severe: return .red
                }
            }
        }
    }

    private var lastRectangles: [VNRectangleObservation] = []
    private var stableFrameCount = 0
    private let requiredStableFrames = 25
    private var hasAutoCaptured = false
    private let processingQueue = DispatchQueue(label: "com.tallyups.premium.processing", qos: .userInteractive)
    private var frameCount = 0

    enum LightingQuality: Equatable {
        case good
        case tooDark
        case tooBright
        case uneven

        var icon: String {
            switch self {
            case .good: return "sun.max.fill"
            case .tooDark: return "moon.fill"
            case .tooBright: return "sun.max.trianglebadge.exclamationmark"
            case .uneven: return "circle.lefthalf.filled"
            }
        }

        var color: Color {
            switch self {
            case .good: return .green
            case .tooDark: return .orange
            case .tooBright: return .yellow
            case .uneven: return .orange
            }
        }

        var message: String {
            switch self {
            case .good: return "Good lighting"
            case .tooDark: return "Too dark - add light"
            case .tooBright: return "Too bright - reduce glare"
            case .uneven: return "Uneven lighting"
            }
        }
    }

    func configure() {
        session.beginConfiguration()
        session.sessionPreset = .photo

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera) else { return }

        currentDevice = camera

        // Optimize camera settings
        try? camera.lockForConfiguration()
        camera.focusMode = .continuousAutoFocus
        camera.exposureMode = .continuousAutoExposure
        camera.isSubjectAreaChangeMonitoringEnabled = true
        if camera.isLowLightBoostSupported {
            camera.automaticallyEnablesLowLightBoostWhenAvailable = true
        }
        camera.unlockForConfiguration()

        if session.canAddInput(input) {
            session.addInput(input)
        }

        // Photo output with high quality
        if session.canAddOutput(photoOutput) {
            session.addOutput(photoOutput)
        }

        // Video output for real-time processing
        videoOutput.setSampleBufferDelegate(self, queue: processingQueue)
        videoOutput.alwaysDiscardsLateVideoFrames = true
        if let connection = videoOutput.connection(with: .video) {
            // Use videoRotationAngle instead of deprecated videoOrientation
            connection.videoRotationAngle = 90 // Portrait orientation
        }
        if session.canAddOutput(videoOutput) {
            session.addOutput(videoOutput)
        }

        session.commitConfiguration()
    }

    func start() {
        DispatchQueue.global(qos: .userInitiated).async {
            self.session.startRunning()
        }
    }

    func stop() {
        session.stopRunning()
    }

    func flipCamera() {
        session.beginConfiguration()

        guard let currentInput = session.inputs.first as? AVCaptureDeviceInput else { return }
        session.removeInput(currentInput)

        let newPosition: AVCaptureDevice.Position = currentInput.device.position == .back ? .front : .back

        guard let newCamera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: newPosition),
              let newInput = try? AVCaptureDeviceInput(device: newCamera) else { return }

        currentDevice = newCamera

        if session.canAddInput(newInput) {
            session.addInput(newInput)
        }

        session.commitConfiguration()
    }

    func toggleFlash(_ enabled: Bool) {
        guard let device = currentDevice, device.hasTorch else { return }
        try? device.lockForConfiguration()
        device.torchMode = enabled ? .on : .off
        device.unlockForConfiguration()
    }

    func setZoom(_ level: CGFloat) {
        guard let device = currentDevice else { return }
        try? device.lockForConfiguration()
        device.videoZoomFactor = min(max(level, 1.0), device.activeFormat.videoMaxZoomFactor)
        device.unlockForConfiguration()
    }

    func focus(at point: CGPoint) {
        guard let device = currentDevice else { return }

        try? device.lockForConfiguration()
        if device.isFocusPointOfInterestSupported {
            device.focusPointOfInterest = point
            device.focusMode = .autoFocus
        }
        if device.isExposurePointOfInterestSupported {
            device.exposurePointOfInterest = point
            device.exposureMode = .autoExpose
        }
        device.unlockForConfiguration()
    }

    func resetStability() {
        DispatchQueue.main.async {
            self.stableFrameCount = 0
            self.hasAutoCaptured = false
            self.isEdgeStable = false
            self.stabilityProgress = 0
        }
    }

    func captureBurst(completion: @escaping ([UIImage]) -> Void) {
        isCapturing = true
        captureCompletion = completion
        burstCount = 3
        burstImages = []

        captureNextBurst()
    }

    private func captureNextBurst() {
        guard burstCount > 0 else {
            isCapturing = false
            let images = burstImages
            captureCompletion?(images)
            return
        }

        let settings = AVCapturePhotoSettings()
        // Use max photo dimensions instead of deprecated isHighResolutionPhotoEnabled
        settings.maxPhotoDimensions = photoOutput.maxPhotoDimensions
        if let device = currentDevice, device.hasFlash {
            settings.flashMode = device.torchMode == .on ? .on : .off
        }

        photoOutput.capturePhoto(with: settings, delegate: self)
        burstCount -= 1
    }

    // MARK: - Video Frame Processing

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        frameCount += 1

        // Process every 3rd frame for performance
        guard frameCount % 3 == 0 else { return }

        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        // Edge detection
        let rectRequest = VNDetectRectanglesRequest { [weak self] request, _ in
            self?.handleRectangleDetection(request)
        }
        rectRequest.minimumAspectRatio = 0.3
        rectRequest.maximumAspectRatio = 0.9
        rectRequest.minimumSize = 0.15
        rectRequest.minimumConfidence = 0.7
        rectRequest.maximumObservations = 1

        // Text recognition for preview
        let textRequest = VNRecognizeTextRequest { [weak self] request, _ in
            self?.handleTextRecognition(request)
        }
        textRequest.recognitionLevel = .fast
        textRequest.usesLanguageCorrection = false

        // Lighting analysis (every 15 frames)
        if frameCount % 15 == 0 {
            analyzeLighting(pixelBuffer)
        }

        // Glare detection (every 5th processed frame for performance)
        glareCheckCounter += 1
        if glareCheckCounter >= glareCheckInterval {
            glareCheckCounter = 0
            analyzeGlare(pixelBuffer)
        }

        // Quality analysis (every 6th processed frame for performance)
        qualityCheckCounter += 1
        if qualityCheckCounter >= qualityCheckInterval {
            qualityCheckCounter = 0
            analyzeQuality(pixelBuffer)
        }

        try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
            .perform([rectRequest, textRequest])
    }

    // MARK: - Quality Analysis

    private func analyzeQuality(_ pixelBuffer: CVPixelBuffer) {
        // Use the quick quality check from ScannerService for performance
        let (sharpness, brightness, acceptable) = ScannerService.shared.quickQualityCheck(pixelBuffer: pixelBuffer)

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            self.sharpnessScore = sharpness
            self.brightnessScore = brightness
            self.isQualityAcceptable = acceptable

            // Calculate overall quality score (0-100)
            // Weights: sharpness 50%, brightness 50%
            let sharpnessComponent = sharpness * 50
            let brightnessComponent: Double
            if brightness < 0.2 || brightness > 0.9 {
                brightnessComponent = 0
            } else if brightness < 0.35 || brightness > 0.75 {
                brightnessComponent = 25
            } else {
                brightnessComponent = 50
            }

            self.qualityScore = Int(sharpnessComponent + brightnessComponent)

            // Determine quality level
            if self.qualityScore >= 75 {
                self.qualityLevel = .excellent
                self.qualityFeedback = nil
            } else if self.qualityScore >= 50 {
                self.qualityLevel = .good
                self.qualityFeedback = nil
            } else if self.qualityScore >= 30 {
                self.qualityLevel = .fair
                // Generate feedback
                if sharpness < 0.4 {
                    self.qualityFeedback = "Hold steady"
                } else if brightness < 0.3 {
                    self.qualityFeedback = "Too dark"
                } else if brightness > 0.8 {
                    self.qualityFeedback = "Too bright"
                } else {
                    self.qualityFeedback = "Adjust position"
                }
            } else {
                self.qualityLevel = .poor
                // Generate critical feedback
                if sharpness < 0.3 {
                    self.qualityFeedback = "Hold steady"
                } else if brightness < 0.25 {
                    self.qualityFeedback = "Too dark"
                } else if brightness > 0.85 {
                    self.qualityFeedback = "Too bright"
                } else {
                    self.qualityFeedback = "Poor quality"
                }
            }
        }
    }

    // MARK: - Glare Analysis

    private func analyzeGlare(_ pixelBuffer: CVPixelBuffer) {
        // Perform glare detection with current receipt rectangle for focused analysis
        let result = glareDetector.analyzeFrame(pixelBuffer, receiptRect: detectedRectangle)

        DispatchQueue.main.async { [weak self] in
            guard let self = self else { return }

            self.glareResult = result
            self.hasGlareWarning = self.glareDetector.shouldWarn(result)
            self.glareBlocksCapture = self.glareDetector.shouldBlockCapture(result) && !self.allowCaptureWithGlare

            // Log glare event for analytics if significant
            if result.severity > 0.3 {
                self.logGlareEvent(result)
            }
        }
    }

    private func logGlareEvent(_ result: GlareDetector.GlareResult) {
        // Analytics logging for glare events
        #if DEBUG
        print("[GlareDetector] Severity: \(String(format: "%.1f%%", result.severity * 100)), Affected: \(String(format: "%.1f%%", result.affectedPercentage)), Blocking text: \(result.isBlockingText)")
        #endif
    }

    /// Toggle manual override for glare blocking
    func toggleGlareOverride() {
        allowCaptureWithGlare.toggle()
        if allowCaptureWithGlare {
            glareBlocksCapture = false
        }
    }

    /// Reset glare override (e.g., after capture)
    func resetGlareOverride() {
        allowCaptureWithGlare = false
    }

    private func handleRectangleDetection(_ request: VNRequest) {
        DispatchQueue.main.async {
            if let results = request.results as? [VNRectangleObservation],
               let rect = results.first,
               rect.confidence > 0.8 {
                self.detectedRectangle = rect
                self.captureConfidence = CGFloat(rect.confidence)
                self.updateStability(with: rect)
                self.updateGuidance(with: rect)
            } else {
                self.detectedRectangle = nil
                self.stableFrameCount = 0
                self.isEdgeStable = false
                self.stabilityProgress = 0
                self.captureConfidence = 0
                self.currentGuidance = .positionReceipt
            }
        }
    }

    private func updateGuidance(with rect: VNRectangleObservation) {
        // Calculate rectangle properties for guidance
        let width = abs(rect.topRight.x - rect.topLeft.x)
        let height = abs(rect.topLeft.y - rect.bottomLeft.y)
        let area = width * height

        // Check if too small (move closer)
        if area < 0.15 {
            currentGuidance = .moveCloser
            return
        }

        // Check if too large (move farther)
        if area > 0.85 {
            currentGuidance = .moveFarther
            return
        }

        // Check for excessive tilt (compare top edge to bottom edge lengths)
        let topEdge = hypot(rect.topRight.x - rect.topLeft.x, rect.topRight.y - rect.topLeft.y)
        let bottomEdge = hypot(rect.bottomRight.x - rect.bottomLeft.x, rect.bottomRight.y - rect.bottomLeft.y)
        let edgeRatio = min(topEdge, bottomEdge) / max(topEdge, bottomEdge)

        if edgeRatio < 0.7 {
            currentGuidance = .tiltLess
            return
        }

        // Check for glare (prioritize if blocking text or severe)
        if hasGlareWarning && !allowCaptureWithGlare {
            let severity: ScannerGuidance.GlareSeverity
            if glareResult.severity >= 0.35 || glareResult.isBlockingText {
                severity = .severe
            } else if glareResult.severity >= 0.20 {
                severity = .moderate
            } else {
                severity = .mild
            }
            currentGuidance = .glareDetected(severity: severity)
            return
        }

        // Check stability
        if isCapturing {
            currentGuidance = .capturing
        } else if isEdgeStable {
            currentGuidance = stabilityProgress > 0.9 ? .perfect : .holdSteady
        } else {
            currentGuidance = .holdSteady
        }
    }

    private func handleTextRecognition(_ request: VNRequest) {
        guard let results = request.results as? [VNRecognizedTextObservation] else { return }

        let texts = results.compactMap { $0.topCandidates(1).first?.string }
            .filter { $0.count > 2 }
            .prefix(5)
            .map { String($0) }

        DispatchQueue.main.async {
            self.detectedTexts = texts.isEmpty ? nil : texts
        }
    }

    private func analyzeLighting(_ pixelBuffer: CVPixelBuffer) {
        CVPixelBufferLockBaseAddress(pixelBuffer, .readOnly)
        defer { CVPixelBufferUnlockBaseAddress(pixelBuffer, .readOnly) }

        let width = CVPixelBufferGetWidth(pixelBuffer)
        let height = CVPixelBufferGetHeight(pixelBuffer)
        guard let baseAddress = CVPixelBufferGetBaseAddress(pixelBuffer) else { return }

        let bytesPerRow = CVPixelBufferGetBytesPerRow(pixelBuffer)
        var totalBrightness: CGFloat = 0
        var samples = 0

        // Sample brightness from grid points
        for y in stride(from: 0, to: height, by: height / 10) {
            for x in stride(from: 0, to: width, by: width / 10) {
                let offset = y * bytesPerRow + x * 4
                let pixel = baseAddress.advanced(by: offset).assumingMemoryBound(to: UInt8.self)
                let brightness = (CGFloat(pixel[0]) + CGFloat(pixel[1]) + CGFloat(pixel[2])) / (3 * 255)
                totalBrightness += brightness
                samples += 1
            }
        }

        let avgBrightness = totalBrightness / CGFloat(samples)

        DispatchQueue.main.async {
            if avgBrightness < 0.2 {
                self.lightingQuality = .tooDark
            } else if avgBrightness > 0.85 {
                self.lightingQuality = .tooBright
            } else {
                self.lightingQuality = .good
            }
        }
    }

    private func updateStability(with rect: VNRectangleObservation) {
        if isRectangleStable(rect) {
            stableFrameCount += 1
            stabilityProgress = min(1.0, CGFloat(stableFrameCount) / CGFloat(requiredStableFrames))

            if stableFrameCount >= 8 {
                isEdgeStable = true
            }

            // Only auto-capture if:
            // 1. Enough stable frames accumulated
            // 2. Haven't auto-captured already
            // 3. No blocking glare (or user has overridden glare check)
            if stableFrameCount >= requiredStableFrames && !hasAutoCaptured {
                if !glareBlocksCapture {
                    hasAutoCaptured = true
                    performAutoCapture()
                }
                // If glare is blocking, we pause auto-capture but don't reset stability
                // This allows instant capture when glare clears
            }
        } else {
            stableFrameCount = max(0, stableFrameCount - 2)
            stabilityProgress = CGFloat(stableFrameCount) / CGFloat(requiredStableFrames)
            if stableFrameCount < 8 {
                isEdgeStable = false
            }
        }

        lastRectangles.append(rect)
        if lastRectangles.count > 5 {
            lastRectangles.removeFirst()
        }
    }

    private func isRectangleStable(_ rect: VNRectangleObservation) -> Bool {
        guard let last = lastRectangles.last else { return true }
        let threshold: CGFloat = 0.015

        let diffs = [
            hypot(rect.topLeft.x - last.topLeft.x, rect.topLeft.y - last.topLeft.y),
            hypot(rect.topRight.x - last.topRight.x, rect.topRight.y - last.topRight.y),
            hypot(rect.bottomLeft.x - last.bottomLeft.x, rect.bottomLeft.y - last.bottomLeft.y),
            hypot(rect.bottomRight.x - last.bottomRight.x, rect.bottomRight.y - last.bottomRight.y)
        ]

        return diffs.allSatisfy { $0 < threshold }
    }

    private func performAutoCapture() {
        // Haptic feedback: auto capture triggered
        Task { @MainActor in
            HapticService.shared.scanSuccess()
        }

        let settings = AVCapturePhotoSettings()
        // Use max photo dimensions instead of deprecated isHighResolutionPhotoEnabled
        settings.maxPhotoDimensions = photoOutput.maxPhotoDimensions
        burstCount = 1
        burstImages = []
        captureCompletion = { [weak self] images in
            if let image = images.first {
                self?.onAutoCapture?(image)
            }
        }

        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    // MARK: - Photo Delegate

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            if burstCount <= 0 {
                isCapturing = false
                captureCompletion?([])
            } else {
                captureNextBurst()
            }
            return
        }

        // Process image
        var processed = image.fixedOrientation

        // Perspective correction
        if let rect = detectedRectangle {
            processed = perspectiveCorrect(image: processed, rect: rect) ?? processed
        }

        // Smart enhancement
        processed = smartEnhance(processed)

        burstImages.append(processed)

        if burstCount > 0 {
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.05) {
                self.captureNextBurst()
            }
        } else {
            isCapturing = false
            captureCompletion?(burstImages)
        }
    }

    private func perspectiveCorrect(image: UIImage, rect: VNRectangleObservation) -> UIImage? {
        guard let cgImage = image.cgImage else { return nil }
        let ciImage = CIImage(cgImage: cgImage)
        let size = ciImage.extent.size

        let topLeft = CGPoint(x: rect.topLeft.x * size.width, y: (1 - rect.topLeft.y) * size.height)
        let topRight = CGPoint(x: rect.topRight.x * size.width, y: (1 - rect.topRight.y) * size.height)
        let bottomLeft = CGPoint(x: rect.bottomLeft.x * size.width, y: (1 - rect.bottomLeft.y) * size.height)
        let bottomRight = CGPoint(x: rect.bottomRight.x * size.width, y: (1 - rect.bottomRight.y) * size.height)

        guard let filter = CIFilter(name: "CIPerspectiveCorrection") else { return nil }
        filter.setValue(ciImage, forKey: kCIInputImageKey)
        filter.setValue(CIVector(cgPoint: topLeft), forKey: "inputTopLeft")
        filter.setValue(CIVector(cgPoint: topRight), forKey: "inputTopRight")
        filter.setValue(CIVector(cgPoint: bottomLeft), forKey: "inputBottomLeft")
        filter.setValue(CIVector(cgPoint: bottomRight), forKey: "inputBottomRight")

        guard let output = filter.outputImage else { return nil }
        let context = CIContext()
        guard let cgOutput = context.createCGImage(output, from: output.extent) else { return nil }

        return UIImage(cgImage: cgOutput, scale: image.scale, orientation: image.imageOrientation)
    }

    private func smartEnhance(_ image: UIImage) -> UIImage {
        guard let cgImage = image.cgImage else { return image }
        var ciImage = CIImage(cgImage: cgImage)

        // Auto-enhance
        let filters = ciImage.autoAdjustmentFilters()
        for filter in filters {
            filter.setValue(ciImage, forKey: kCIInputImageKey)
            if let output = filter.outputImage {
                ciImage = output
            }
        }

        // Sharpen
        if let sharpen = CIFilter(name: "CISharpenLuminance") {
            sharpen.setValue(ciImage, forKey: kCIInputImageKey)
            sharpen.setValue(0.4, forKey: kCIInputSharpnessKey)
            if let output = sharpen.outputImage {
                ciImage = output
            }
        }

        // Contrast boost for text
        if let contrast = CIFilter(name: "CIColorControls") {
            contrast.setValue(ciImage, forKey: kCIInputImageKey)
            contrast.setValue(1.05, forKey: kCIInputContrastKey)
            contrast.setValue(0.02, forKey: kCIInputBrightnessKey)
            if let output = contrast.outputImage {
                ciImage = output
            }
        }

        let context = CIContext()
        guard let cgOutput = context.createCGImage(ciImage, from: ciImage.extent) else { return image }

        return UIImage(cgImage: cgOutput, scale: image.scale, orientation: image.imageOrientation)
    }
}

// MARK: - Premium Preview Layer

struct PremiumPreviewLayer: UIViewRepresentable {
    @ObservedObject var controller: PremiumCameraController

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.backgroundColor = .black

        let previewLayer = AVCaptureVideoPreviewLayer(session: controller.session)
        previewLayer.videoGravity = .resizeAspectFill
        view.layer.addSublayer(previewLayer)

        context.coordinator.previewLayer = previewLayer
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        context.coordinator.previewLayer?.frame = uiView.bounds
    }

    func makeCoordinator() -> Coordinator { Coordinator() }

    class Coordinator {
        var previewLayer: AVCaptureVideoPreviewLayer?
    }
}

// MARK: - UI Components

struct GlassButton: View {
    let icon: String
    var isActive: Bool = false
    var tint: Color? = nil
    var label: String? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                if let label = label {
                    Text(label)
                        .font(.caption.bold())
                }
            }
            .foregroundColor(tint ?? (isActive ? .tallyAccent : .white))
            .padding(.horizontal, label != nil ? 14 : 12)
            .padding(.vertical, 12)
            .background(.ultraThinMaterial.opacity(0.9))
            .clipShape(Capsule())
        }
    }
}

struct GlassCircleButton: View {
    let icon: String
    let size: CGFloat
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Image(systemName: icon)
                .font(.system(size: size * 0.4, weight: .semibold))
                .foregroundColor(.white)
                .frame(width: size, height: size)
                .background(.ultraThinMaterial)
                .clipShape(Circle())
        }
    }
}

struct CaptureButton: View {
    let isActive: Bool
    let isCapturing: Bool
    let progress: CGFloat
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                // Outer ring with progress
                Circle()
                    .stroke(Color.white.opacity(0.3), lineWidth: 4)
                    .frame(width: 85, height: 85)

                Circle()
                    .trim(from: 0, to: progress)
                    .stroke(Color.tallyAccent, style: StrokeStyle(lineWidth: 4, lineCap: .round))
                    .frame(width: 85, height: 85)
                    .rotationEffect(.degrees(-90))

                // Inner button
                Circle()
                    .fill(Color.white)
                    .frame(width: 72, height: 72)

                Circle()
                    .fill(isActive ? Color.tallyAccent : Color.gray.opacity(0.5))
                    .frame(width: 64, height: 64)

                if isCapturing {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                } else {
                    Image(systemName: "camera.fill")
                        .font(.title2.weight(.semibold))
                        .foregroundColor(.white)
                }
            }
        }
        .scaleEffect(isCapturing ? 0.95 : 1.0)
        .animation(.spring(response: 0.2), value: isCapturing)
    }
}

struct ModeTab: View {
    let icon: String
    let label: String
    let isSelected: Bool
    var action: (() -> Void)? = nil

    var body: some View {
        Button(action: { action?() }) {
            VStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.system(size: 20))
                Text(label)
                    .font(.caption2.weight(.medium))
            }
            .foregroundColor(isSelected ? .tallyAccent : .white.opacity(0.6))
        }
    }
}

struct ProgressCapsule: View {
    let progress: CGFloat

    var body: some View {
        GeometryReader { geo in
            ZStack(alignment: .leading) {
                Capsule()
                    .fill(Color.white.opacity(0.2))

                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [.tallyAccent, .green],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: geo.size.width * progress)
            }
        }
    }
}

struct FocusRingView: View {
    let point: CGPoint

    @State private var scale: CGFloat = 1.5
    @State private var opacity: CGFloat = 0

    var body: some View {
        ZStack {
            Circle()
                .stroke(Color.tallyAccent, lineWidth: 2)
                .frame(width: 80, height: 80)

            Circle()
                .stroke(Color.tallyAccent.opacity(0.5), lineWidth: 1)
                .frame(width: 60, height: 60)
        }
        .scaleEffect(scale)
        .opacity(opacity)
        .position(point)
        .onAppear {
            withAnimation(.spring(response: 0.3, dampingFraction: 0.6)) {
                scale = 1.0
                opacity = 1.0
            }
        }
    }
}

struct ScanLineView: View {
    let width: CGFloat
    let offset: CGFloat

    var body: some View {
        RoundedRectangle(cornerRadius: 2)
            .fill(
                LinearGradient(
                    colors: [.clear, .tallyAccent, .clear],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .frame(width: width, height: 3)
            .shadow(color: .tallyAccent.opacity(0.8), radius: 15, y: 0)
            .shadow(color: .tallyAccent.opacity(0.4), radius: 30, y: 0)
            .offset(y: offset)
    }
}

struct CornerBrackets: View {
    let width: CGFloat
    let height: CGFloat

    var body: some View {
        ZStack {
            ForEach(0..<4) { index in
                CornerBracket()
                    .stroke(Color.tallyAccent, lineWidth: 3)
                    .frame(width: 35, height: 35)
                    .rotationEffect(.degrees(Double(index) * 90))
                    .offset(
                        x: (index == 0 || index == 3) ? -width/2 + 20 : width/2 - 20,
                        y: (index == 0 || index == 1) ? -height/2 + 20 : height/2 - 20
                    )
            }
        }
    }
}

struct CornerBracket: Shape {
    func path(in rect: CGRect) -> Path {
        var path = Path()
        path.move(to: CGPoint(x: rect.minX, y: rect.midY))
        path.addLine(to: CGPoint(x: rect.minX, y: rect.minY))
        path.addLine(to: CGPoint(x: rect.midX, y: rect.minY))
        return path
    }
}

// MARK: - Edge Overlay

struct EdgeOverlayView: View {
    let detectedRectangle: VNRectangleObservation?
    let viewSize: CGSize
    let isStable: Bool

    var body: some View {
        Canvas { context, size in
            guard let rect = detectedRectangle else { return }

            let topLeft = CGPoint(x: rect.topLeft.x * size.width, y: (1 - rect.topLeft.y) * size.height)
            let topRight = CGPoint(x: rect.topRight.x * size.width, y: (1 - rect.topRight.y) * size.height)
            let bottomLeft = CGPoint(x: rect.bottomLeft.x * size.width, y: (1 - rect.bottomLeft.y) * size.height)
            let bottomRight = CGPoint(x: rect.bottomRight.x * size.width, y: (1 - rect.bottomRight.y) * size.height)

            var path = Path()
            path.move(to: topLeft)
            path.addLine(to: topRight)
            path.addLine(to: bottomRight)
            path.addLine(to: bottomLeft)
            path.closeSubpath()

            let color = isStable ? Color.green : Color.tallyAccent

            // Glow effect
            context.stroke(path, with: .color(color.opacity(0.3)), style: StrokeStyle(lineWidth: 12, lineCap: .round, lineJoin: .round))
            context.stroke(path, with: .color(color), style: StrokeStyle(lineWidth: 3, lineCap: .round, lineJoin: .round))
            context.fill(path, with: .color(color.opacity(0.08)))

            // Corner dots
            for corner in [topLeft, topRight, bottomRight, bottomLeft] {
                var dot = Path()
                dot.addEllipse(in: CGRect(x: corner.x - 12, y: corner.y - 12, width: 24, height: 24))
                context.fill(dot, with: .color(color))

                var inner = Path()
                inner.addEllipse(in: CGRect(x: corner.x - 5, y: corner.y - 5, width: 10, height: 10))
                context.fill(inner, with: .color(.white))
            }
        }
    }
}

// MARK: - Glare Overlay

/// Visual overlay showing detected glare regions on the camera preview
struct GlareOverlayView: View {
    let glareResult: GlareDetector.GlareResult
    let viewSize: CGSize

    @State private var pulseAnimation = false

    var body: some View {
        Canvas { context, size in
            // Draw glare regions
            for region in glareResult.glareRegions {
                // Convert normalized coordinates to view coordinates
                let rect = CGRect(
                    x: region.origin.x * size.width,
                    y: region.origin.y * size.height,
                    width: region.size.width * size.width,
                    height: region.size.height * size.height
                )

                // Expand rect slightly for visibility
                let expandedRect = rect.insetBy(dx: -8, dy: -8)

                // Create rounded rect path
                let path = RoundedRectangle(cornerRadius: 12)
                    .path(in: expandedRect)

                // Severity-based color
                let glareColor: Color = glareResult.severity >= 0.35 ? .red : (glareResult.severity >= 0.20 ? .orange : .yellow)

                // Outer glow
                context.stroke(
                    path,
                    with: .color(glareColor.opacity(0.4)),
                    style: StrokeStyle(lineWidth: 8, lineCap: .round)
                )

                // Inner border
                context.stroke(
                    path,
                    with: .color(glareColor.opacity(0.8)),
                    style: StrokeStyle(lineWidth: 2, lineCap: .round, dash: [6, 4])
                )

                // Fill with semi-transparent color
                context.fill(path, with: .color(glareColor.opacity(0.15)))

                // Add small warning icon at center of region
                let iconCenter = CGPoint(
                    x: expandedRect.midX,
                    y: expandedRect.midY
                )

                // Draw circular background for icon
                var iconBg = Path()
                iconBg.addEllipse(in: CGRect(
                    x: iconCenter.x - 14,
                    y: iconCenter.y - 14,
                    width: 28,
                    height: 28
                ))
                context.fill(iconBg, with: .color(glareColor))
            }
        }
        .opacity(pulseAnimation ? 0.8 : 1.0)
        .animation(
            .easeInOut(duration: 0.8).repeatForever(autoreverses: true),
            value: pulseAnimation
        )
        .onAppear {
            pulseAnimation = true
        }
    }
}

// MARK: - Premium Preview View

struct PremiumPreviewView: View {
    let image: UIImage
    let ocrPreview: String?
    let onConfirm: (Bool) -> Void

    @State private var showOCR = false
    @State private var isCheckingDuplicate = false
    @State private var duplicateResult: ScannerService.DuplicateCheckResult?
    @State private var showDuplicateAlert = false
    @State private var showQualityAlert = false
    @State private var qualityResult: ScannerService.ImageQualityResult?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                // Header
                HStack {
                    Button(action: { onConfirm(false) }) {
                        Image(systemName: "xmark")
                            .font(.title3.weight(.semibold))
                            .foregroundColor(.white)
                            .frame(width: 44, height: 44)
                            .background(.ultraThinMaterial)
                            .clipShape(Circle())
                    }
                    Spacer()

                    if ocrPreview != nil {
                        Button(action: { showOCR.toggle() }) {
                            HStack(spacing: 6) {
                                Image(systemName: "text.viewfinder")
                                Text("Preview OCR")
                                    .font(.caption.bold())
                            }
                            .foregroundColor(.white)
                            .padding(.horizontal, 14)
                            .padding(.vertical, 10)
                            .background(.ultraThinMaterial)
                            .cornerRadius(20)
                        }
                    }
                }
                .padding()

                // Image
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .cornerRadius(20)
                    .shadow(color: .black.opacity(0.5), radius: 20)
                    .padding()

                if showOCR, let text = ocrPreview {
                    Text(text)
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.8))
                        .padding()
                        .background(.ultraThinMaterial)
                        .cornerRadius(12)
                        .padding(.horizontal)
                }

                Spacer()

                // Actions
                HStack(spacing: 50) {
                    Button(action: { onConfirm(false) }) {
                        VStack(spacing: 8) {
                            Circle()
                                .strokeBorder(Color.white.opacity(0.5), lineWidth: 2)
                                .frame(width: 64, height: 64)
                                .overlay(
                                    Image(systemName: "arrow.counterclockwise")
                                        .font(.title2)
                                        .foregroundColor(.white)
                                )
                            Text("Retake")
                                .font(.caption.weight(.medium))
                                .foregroundColor(.white.opacity(0.8))
                        }
                    }

                    Button(action: handleUsePhoto) {
                        VStack(spacing: 8) {
                            Circle()
                                .fill(Color.tallyAccent)
                                .frame(width: 64, height: 64)
                                .overlay(
                                    Group {
                                        if isCheckingDuplicate {
                                            ProgressView()
                                                .progressViewStyle(CircularProgressViewStyle(tint: .black))
                                        } else {
                                            Image(systemName: "checkmark")
                                                .font(.title2.weight(.bold))
                                                .foregroundColor(.black)
                                        }
                                    }
                                )
                            Text("Use Photo")
                                .font(.caption.weight(.medium))
                                .foregroundColor(.white)
                        }
                    }
                    .disabled(isCheckingDuplicate)
                }
                .padding(.bottom, 50)
            }

            // Duplicate Alert Overlay
            if showDuplicateAlert, let duplicate = duplicateResult {
                DuplicateReceiptAlert(
                    result: duplicate,
                    newImage: image,
                    onUseExisting: {
                        showDuplicateAlert = false
                        onConfirm(false)
                    },
                    onUseNew: {
                        showDuplicateAlert = false
                        onConfirm(true)
                    },
                    onCancel: {
                        showDuplicateAlert = false
                    }
                )
                .transition(.opacity.combined(with: .scale(scale: 0.9)))
            }

            // Quality Gate Alert
            if showQualityAlert, let quality = qualityResult {
                QualityGateAlert(
                    qualityScore: quality.overallScore,
                    qualityLevel: quality.qualityLevel.toCameraQualityLevel(),
                    onRetake: {
                        showQualityAlert = false
                        onConfirm(false)
                    },
                    onForceUpload: {
                        showQualityAlert = false
                        // Proceed with duplicate check then upload
                        checkDuplicateAndUpload()
                    },
                    onCancel: {
                        showQualityAlert = false
                    }
                )
                .transition(.opacity.combined(with: .scale(scale: 0.9)))
            }
        }
        .statusBarHidden()
        .animation(.spring(response: 0.3), value: showDuplicateAlert)
        .animation(.spring(response: 0.3), value: showQualityAlert)
    }

    private func handleUsePhoto() {
        isCheckingDuplicate = true

        Task {
            // First check quality
            let quality = ScannerService.shared.assessImageQuality(image)

            await MainActor.run {
                // If quality is not acceptable, show warning
                if !quality.isAcceptable {
                    isCheckingDuplicate = false
                    qualityResult = quality
                    showQualityAlert = true
                    HapticService.shared.warning()
                    return
                }

                // Quality is acceptable, proceed with duplicate check
                checkDuplicateAndUpload()
            }
        }
    }

    private func checkDuplicateAndUpload() {
        isCheckingDuplicate = true

        Task {
            // Check for duplicates before confirming
            let result = await ScannerService.shared.checkForDuplicate(image)

            await MainActor.run {
                isCheckingDuplicate = false

                if result.isDuplicate {
                    duplicateResult = result
                    showDuplicateAlert = true
                    // Haptic feedback: warning for duplicate detected
                    HapticService.shared.warning()
                } else {
                    // Haptic feedback: success for confirmed capture
                    HapticService.shared.saveSuccess()
                    onConfirm(true)
                }
            }
        }
    }
}

// MARK: - Duplicate Receipt Alert

struct DuplicateReceiptAlert: View {
    let result: ScannerService.DuplicateCheckResult
    let newImage: UIImage
    let onUseExisting: () -> Void
    let onUseNew: () -> Void
    let onCancel: () -> Void

    var body: some View {
        ZStack {
            // Dimmed background
            Color.black.opacity(0.85)
                .ignoresSafeArea()
                .onTapGesture { onCancel() }

            VStack(spacing: 24) {
                // Header
                VStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(Color.orange.opacity(0.2))
                            .frame(width: 72, height: 72)

                        Image(systemName: "doc.on.doc.fill")
                            .font(.system(size: 32))
                            .foregroundColor(.orange)
                    }

                    Text("Duplicate Detected")
                        .font(.title2.weight(.bold))
                        .foregroundColor(.white)

                    Text(result.matchType.rawValue)
                        .font(.subheadline)
                        .foregroundColor(.gray)

                    if result.matchConfidence > 0 {
                        HStack(spacing: 4) {
                            Text("\(Int(result.matchConfidence * 100))%")
                                .font(.caption.weight(.bold))
                                .foregroundColor(.tallyAccent)
                            Text("match confidence")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                }

                // Image Comparison
                HStack(spacing: 16) {
                    // Existing Receipt
                    VStack(spacing: 8) {
                        if let url = result.existingReceiptUrl, let imageUrl = URL(string: url) {
                            AsyncImage(url: imageUrl) { phase in
                                switch phase {
                                case .success(let image):
                                    image
                                        .resizable()
                                        .scaledToFill()
                                        .frame(width: 120, height: 160)
                                        .clipped()
                                        .cornerRadius(12)
                                case .failure:
                                    existingPlaceholder
                                default:
                                    ProgressView()
                                        .frame(width: 120, height: 160)
                                }
                            }
                        } else {
                            existingPlaceholder
                        }

                        Text("Existing")
                            .font(.caption.weight(.medium))
                            .foregroundColor(.gray)
                    }

                    // Arrow
                    Image(systemName: "arrow.left.arrow.right")
                        .font(.title3)
                        .foregroundColor(.gray)

                    // New Receipt
                    VStack(spacing: 8) {
                        Image(uiImage: newImage)
                            .resizable()
                            .scaledToFill()
                            .frame(width: 120, height: 160)
                            .clipped()
                            .cornerRadius(12)
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .stroke(Color.tallyAccent, lineWidth: 2)
                            )

                        Text("New")
                            .font(.caption.weight(.medium))
                            .foregroundColor(.tallyAccent)
                    }
                }

                // Actions
                VStack(spacing: 12) {
                    Button(action: onUseExisting) {
                        HStack {
                            Image(systemName: "checkmark.circle.fill")
                            Text("Keep Existing Receipt")
                        }
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.tallyAccent)
                        .cornerRadius(14)
                    }

                    Button(action: onUseNew) {
                        HStack {
                            Image(systemName: "arrow.triangle.2.circlepath")
                            Text("Replace with New")
                        }
                        .font(.headline)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.white.opacity(0.15))
                        .cornerRadius(14)
                    }

                    Button(action: onCancel) {
                        Text("Cancel")
                            .font(.subheadline)
                            .foregroundColor(.gray)
                            .padding(.top, 8)
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: 340)
            .background(
                RoundedRectangle(cornerRadius: 24)
                    .fill(Color(white: 0.12))
            )
        }
    }

    private var existingPlaceholder: some View {
        RoundedRectangle(cornerRadius: 12)
            .fill(Color.white.opacity(0.1))
            .frame(width: 120, height: 160)
            .overlay(
                VStack(spacing: 8) {
                    Image(systemName: "doc.fill")
                        .font(.title)
                        .foregroundColor(.gray)
                    Text("Receipt")
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            )
    }
}

// MARK: - Batch Review View

struct BatchReviewView: View {
    let images: [UIImage]
    let onConfirm: ([UIImage]) -> Void

    @State private var selectedImages: Set<Int>
    @Environment(\.dismiss) private var dismiss

    init(images: [UIImage], onConfirm: @escaping ([UIImage]) -> Void) {
        self.images = images
        self.onConfirm = onConfirm
        self._selectedImages = State(initialValue: Set(0..<images.count))
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], spacing: 12) {
                        ForEach(Array(images.enumerated()), id: \.offset) { index, image in
                            BatchImageCard(
                                image: image,
                                index: index + 1,
                                isSelected: selectedImages.contains(index)
                            ) {
                                if selectedImages.contains(index) {
                                    selectedImages.remove(index)
                                } else {
                                    selectedImages.insert(index)
                                }
                            }
                        }
                    }
                    .padding()
                }
            }
            .navigationTitle("Review \(images.count) Receipts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Upload \(selectedImages.count)") {
                        let selected = selectedImages.sorted().map { images[$0] }
                        onConfirm(selected)
                    }
                    .bold()
                    .disabled(selectedImages.isEmpty)
                }
            }
        }
    }
}

struct BatchImageCard: View {
    let image: UIImage
    let index: Int
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack(alignment: .topTrailing) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(height: 200)
                    .clipped()
                    .cornerRadius(12)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(isSelected ? Color.tallyAccent : Color.clear, lineWidth: 3)
                    )

                ZStack {
                    Circle()
                        .fill(isSelected ? Color.tallyAccent : Color.black.opacity(0.5))
                        .frame(width: 28, height: 28)

                    if isSelected {
                        Image(systemName: "checkmark")
                            .font(.caption.bold())
                            .foregroundColor(.black)
                    } else {
                        Text("\(index)")
                            .font(.caption.bold())
                            .foregroundColor(.white)
                    }
                }
                .padding(8)
            }
        }
    }
}

// MARK: - Smart Guidance Views

struct SmartGuidanceView: View {
    let guidance: PremiumCameraController.ScannerGuidance
    let isStable: Bool
    let confidence: CGFloat
    let stabilityProgress: CGFloat
    let showProgress: Bool

    @State private var pulseScale: CGFloat = 1.0

    var body: some View {
        VStack(spacing: 8) {
            HStack(spacing: 10) {
                // Animated icon
                ZStack {
                    Circle()
                        .fill(guidance.color.opacity(0.2))
                        .frame(width: 32, height: 32)
                        .scaleEffect(pulseScale)

                    Image(systemName: guidance.icon)
                        .foregroundColor(guidance.color)
                        .font(.system(size: 14, weight: .semibold))
                }

                Text(guidance.message)
                    .font(.subheadline.weight(.medium))
                    .foregroundColor(.white)

                if isStable && confidence > 0 {
                    Text("•")
                        .foregroundColor(.gray)
                    Text("\(Int(confidence * 100))%")
                        .font(.caption.weight(.bold))
                        .foregroundColor(.tallyAccent)
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(
                Capsule()
                    .fill(.ultraThinMaterial.opacity(0.9))
                    .overlay(
                        Capsule()
                            .strokeBorder(guidance.color.opacity(0.3), lineWidth: 1)
                    )
            )

            // Stability Progress
            if showProgress {
                ProgressCapsule(progress: stabilityProgress)
                    .frame(width: 140, height: 6)
            }
        }
        .onAppear {
            startPulseAnimation()
        }
        .onChange(of: guidance) { _, _ in
            startPulseAnimation()
        }
    }

    private func startPulseAnimation() {
        pulseScale = 1.0
        withAnimation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true)) {
            pulseScale = 1.15
        }
    }
}

struct ScannerGuidanceHint: View {
    let icon: String
    let message: String
    let color: Color
    let isAnimating: Bool

    @State private var opacity: CGFloat = 0.7
    @State private var iconScale: CGFloat = 1.0

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundColor(color)
                .font(.system(size: 16, weight: .semibold))
                .scaleEffect(iconScale)

            Text(message)
                .font(.subheadline.weight(.medium))
                .foregroundColor(color.opacity(opacity))
        }
        .padding(.horizontal, 20)
        .padding(.vertical, 10)
        .background(.ultraThinMaterial.opacity(0.6))
        .cornerRadius(25)
        .onAppear {
            if isAnimating {
                withAnimation(.easeInOut(duration: 1.2).repeatForever(autoreverses: true)) {
                    opacity = 1.0
                    iconScale = 1.1
                }
            }
        }
    }
}

// MARK: - Quality Score Overlay

struct QualityScoreOverlay: View {
    let qualityScore: Int
    let qualityLevel: PremiumCameraController.QualityLevel
    let sharpnessScore: Double
    let brightnessScore: Double
    let feedback: String?
    let isVisible: Bool

    @State private var animate = false

    var body: some View {
        Group {
            if isVisible {
                VStack(spacing: 6) {
                    // Main quality indicator
                    HStack(spacing: 8) {
                        // Quality icon with color
                        ZStack {
                            Circle()
                                .fill(qualityLevel.color.opacity(0.2))
                                .frame(width: 28, height: 28)

                            Image(systemName: qualityLevel.icon)
                                .font(.system(size: 12, weight: .bold))
                                .foregroundColor(qualityLevel.color)
                        }

                        // Score and level
                        VStack(alignment: .leading, spacing: 2) {
                            HStack(spacing: 4) {
                                Text("\(qualityScore)")
                                    .font(.system(size: 14, weight: .bold, design: .rounded))
                                    .foregroundColor(.white)

                                Text(qualityLevel.rawValue)
                                    .font(.caption2.weight(.medium))
                                    .foregroundColor(qualityLevel.color)
                            }

                            // Mini quality bars
                            HStack(spacing: 4) {
                                QualityMiniBar(
                                    label: "Sharp",
                                    value: sharpnessScore,
                                    color: sharpnessScore >= 0.5 ? .green : (sharpnessScore >= 0.3 ? .yellow : .red)
                                )

                                QualityMiniBar(
                                    label: "Light",
                                    value: brightnessScore >= 0.3 && brightnessScore <= 0.7 ? 1.0 : (brightnessScore >= 0.2 && brightnessScore <= 0.8 ? 0.6 : 0.3),
                                    color: brightnessScore >= 0.3 && brightnessScore <= 0.7 ? .green : (brightnessScore >= 0.2 && brightnessScore <= 0.8 ? .yellow : .red)
                                )
                            }
                        }
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(
                        RoundedRectangle(cornerRadius: 12)
                            .fill(.ultraThinMaterial.opacity(0.9))
                            .overlay(
                                RoundedRectangle(cornerRadius: 12)
                                    .strokeBorder(qualityLevel.color.opacity(0.3), lineWidth: 1)
                            )
                    )

                    // Feedback text (if any)
                    if let feedback = feedback {
                        HStack(spacing: 4) {
                            Image(systemName: "info.circle.fill")
                                .font(.system(size: 10))
                            Text(feedback)
                                .font(.caption2.weight(.medium))
                        }
                        .foregroundColor(qualityLevel.color)
                        .padding(.horizontal, 10)
                        .padding(.vertical, 4)
                        .background(
                            Capsule()
                                .fill(qualityLevel.color.opacity(0.15))
                        )
                        .scaleEffect(animate ? 1.02 : 1.0)
                        .animation(.easeInOut(duration: 0.8).repeatForever(autoreverses: true), value: animate)
                    }
                }
                .transition(.opacity.combined(with: .scale(scale: 0.9)))
                .onAppear {
                    animate = true
                }
            }
        }
        .animation(.spring(response: 0.3), value: isVisible)
        .animation(.spring(response: 0.3), value: qualityLevel)
    }
}

struct QualityMiniBar: View {
    let label: String
    let value: Double
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 2) {
            Text(label)
                .font(.system(size: 8, weight: .medium))
                .foregroundColor(.gray)

            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.white.opacity(0.2))

                    RoundedRectangle(cornerRadius: 2)
                        .fill(color)
                        .frame(width: geo.size.width * CGFloat(value))
                }
            }
            .frame(width: 40, height: 3)
        }
    }
}

// MARK: - Quality Gate Alert

struct QualityGateAlert: View {
    let qualityScore: Int
    let qualityLevel: PremiumCameraController.QualityLevel
    let onRetake: () -> Void
    let onForceUpload: () -> Void
    let onCancel: () -> Void

    var body: some View {
        ZStack {
            // Dimmed background
            Color.black.opacity(0.85)
                .ignoresSafeArea()
                .onTapGesture { onCancel() }

            VStack(spacing: 20) {
                // Header
                VStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(qualityLevel.color.opacity(0.2))
                            .frame(width: 72, height: 72)

                        Image(systemName: qualityLevel.icon)
                            .font(.system(size: 32))
                            .foregroundColor(qualityLevel.color)
                    }

                    Text("Quality Check")
                        .font(.title2.weight(.bold))
                        .foregroundColor(.white)

                    Text("Score: \(qualityScore)/100 (\(qualityLevel.rawValue))")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                }

                // Quality details
                VStack(spacing: 8) {
                    Text("The image quality is below optimal. This may affect text recognition accuracy.")
                        .font(.caption)
                        .foregroundColor(.white.opacity(0.7))
                        .multilineTextAlignment(.center)
                        .padding(.horizontal)
                }

                // Actions
                VStack(spacing: 12) {
                    Button(action: onRetake) {
                        HStack {
                            Image(systemName: "arrow.counterclockwise")
                            Text("Retake Photo")
                        }
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.tallyAccent)
                        .cornerRadius(14)
                    }

                    Button(action: onForceUpload) {
                        HStack {
                            Image(systemName: "arrow.up.circle")
                            Text("Upload Anyway")
                        }
                        .font(.headline)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(Color.white.opacity(0.15))
                        .cornerRadius(14)
                    }

                    Button(action: onCancel) {
                        Text("Cancel")
                            .font(.subheadline)
                            .foregroundColor(.gray)
                            .padding(.top, 8)
                    }
                }
            }
            .padding(24)
            .frame(maxWidth: 320)
            .background(
                RoundedRectangle(cornerRadius: 24)
                    .fill(Color(white: 0.12))
            )
        }
    }
}

// MARK: - Quality Level Conversion Extension

extension ScannerService.ImageQualityResult.QualityLevel {
    /// Convert ScannerService quality level to PremiumCameraController quality level
    func toCameraQualityLevel() -> PremiumCameraController.QualityLevel {
        switch self {
        case .excellent: return .excellent
        case .good: return .good
        case .fair: return .fair
        case .poor: return .poor
        }
    }
}

// MARK: - Preview

#Preview {
    FullScreenScannerView(isPresented: .constant(true)) { _ in }
}

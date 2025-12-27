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

                // Controls Layer
                VStack(spacing: 0) {
                    topBar
                    Spacer()
                    lightingIndicator
                    edgeStatusIndicator
                    if showZoomSlider { zoomSlider }
                    bottomControls(geometry: geometry)
                }

                // Batch Counter
                if batchMode && !batchImages.isEmpty {
                    batchCounter
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

            // Flash
            GlassButton(
                icon: flashEnabled ? "bolt.fill" : "bolt.slash.fill",
                isActive: flashEnabled,
                tint: flashEnabled ? .yellow : nil
            ) {
                flashEnabled.toggle()
                camera.toggleFlash(flashEnabled)
            }

            // Settings
            GlassButton(icon: "gearshape.fill") {
                showingSettings.toggle()
            }
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
            }
        }
        .padding(.bottom, 8)
    }

    // MARK: - Edge Status Indicator

    private var edgeStatusIndicator: some View {
        VStack(spacing: 8) {
            if camera.detectedRectangle != nil {
                HStack(spacing: 8) {
                    Image(systemName: camera.isEdgeStable ? "checkmark.circle.fill" : "viewfinder")
                        .foregroundColor(camera.isEdgeStable ? .green : .tallyAccent)
                        .font(.system(size: 16, weight: .semibold))

                    Text(camera.isEdgeStable ? "Hold steady..." : "Receipt detected")
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(.white)

                    if camera.isEdgeStable {
                        Text("•")
                            .foregroundColor(.gray)
                        Text("\(Int(camera.captureConfidence * 100))%")
                            .font(.caption.weight(.bold))
                            .foregroundColor(.tallyAccent)
                    }
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.ultraThinMaterial.opacity(0.9))
                .cornerRadius(25)

                // Stability Progress
                if camera.isEdgeStable && autoCapture {
                    ProgressCapsule(progress: camera.stabilityProgress)
                        .frame(width: 140, height: 6)
                }
            } else {
                Text("Position receipt within frame")
                    .font(.subheadline.weight(.medium))
                    .foregroundColor(.white.opacity(0.9))
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial.opacity(0.6))
                    .cornerRadius(25)
            }
        }
        .padding(.bottom, 12)
        .animation(.spring(response: 0.3), value: camera.detectedRectangle != nil)
        .animation(.spring(response: 0.3), value: camera.isEdgeStable)
    }

    // MARK: - Zoom Slider

    private var zoomSlider: some View {
        HStack(spacing: 16) {
            Image(systemName: "minus.magnifyingglass")
                .foregroundColor(.white.opacity(0.7))

            Slider(value: $camera.zoomLevel, in: 1.0...5.0)
                .accentColor(.tallyAccent)
                .onChange(of: camera.zoomLevel) { _, newValue in
                    camera.setZoom(newValue)
                }

            Image(systemName: "plus.magnifyingglass")
                .foregroundColor(.white.opacity(0.7))
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
                ModeTab(icon: "doc.viewfinder", label: "Document", isSelected: false) {
                    showingDocumentScanner = true
                }
                ModeTab(icon: "photo.stack", label: "Batch", isSelected: batchMode) {
                    withAnimation { batchMode.toggle() }
                }
            }

            // Capture Controls
            HStack(spacing: 40) {
                // Gallery / Zoom Toggle
                GlassCircleButton(icon: showZoomSlider ? "magnifyingglass" : "photo.fill", size: 54) {
                    withAnimation(.spring(response: 0.3)) {
                        showZoomSlider.toggle()
                    }
                }

                // Main Capture Button
                CaptureButton(
                    isActive: camera.detectedRectangle != nil,
                    isCapturing: camera.isCapturing,
                    progress: camera.isEdgeStable ? camera.stabilityProgress : 0
                ) {
                    performCapture()
                }

                // Flip Camera
                GlassCircleButton(icon: "camera.rotate.fill", size: 54) {
                    camera.flipCamera()
                }
            }
        }
        .padding(.bottom, 40)
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

                // Haptic
                UIImpactFeedbackGenerator(style: .light).impactOccurred()
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
        UIImpactFeedbackGenerator(style: .medium).impactOccurred()

        camera.captureBurst { images in
            // Pick best image from burst
            if let best = selectBestImage(from: images) {
                if batchMode {
                    batchImages.append(best)
                    camera.resetStability()
                    UINotificationFeedbackGenerator().notificationOccurred(.success)
                } else {
                    capturedImage = best
                    showingPreview = true
                }
            }
        }
    }

    private func handleAutoCapture(_ image: UIImage) {
        guard autoCapture else { return }

        if batchMode {
            batchImages.append(image)
            camera.resetStability()
            UINotificationFeedbackGenerator().notificationOccurred(.success)
        } else {
            capturedImage = image
            showingPreview = true
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

    var baseZoom: CGFloat = 1.0
    var onAutoCapture: ((UIImage) -> Void)?

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

        try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:])
            .perform([rectRequest, textRequest])
    }

    private func handleRectangleDetection(_ request: VNRequest) {
        DispatchQueue.main.async {
            if let results = request.results as? [VNRectangleObservation],
               let rect = results.first,
               rect.confidence > 0.8 {
                self.detectedRectangle = rect
                self.captureConfidence = CGFloat(rect.confidence)
                self.updateStability(with: rect)
            } else {
                self.detectedRectangle = nil
                self.stableFrameCount = 0
                self.isEdgeStable = false
                self.stabilityProgress = 0
                self.captureConfidence = 0
            }
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

            if stableFrameCount >= requiredStableFrames && !hasAutoCaptured {
                hasAutoCaptured = true
                performAutoCapture()
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
        UINotificationFeedbackGenerator().notificationOccurred(.success)

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

// MARK: - Premium Preview View

struct PremiumPreviewView: View {
    let image: UIImage
    let ocrPreview: String?
    let onConfirm: (Bool) -> Void

    @State private var showOCR = false
    @State private var isCheckingDuplicate = false
    @State private var duplicateResult: ScannerService.DuplicateCheckResult?
    @State private var showDuplicateAlert = false

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
        }
        .statusBarHidden()
        .animation(.spring(response: 0.3), value: showDuplicateAlert)
    }

    private func handleUsePhoto() {
        isCheckingDuplicate = true

        Task {
            // Check for duplicates before confirming
            let result = await ScannerService.shared.checkForDuplicate(image)

            await MainActor.run {
                isCheckingDuplicate = false

                if result.isDuplicate {
                    duplicateResult = result
                    showDuplicateAlert = true
                    UINotificationFeedbackGenerator().notificationOccurred(.warning)
                } else {
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

// MARK: - Preview

#Preview {
    FullScreenScannerView(isPresented: .constant(true)) { _ in }
}

import SwiftUI
import AVFoundation
import Vision
import CoreImage

/// Full-screen immersive receipt scanner with real-time edge detection
struct FullScreenScannerView: View {
    @StateObject private var camera = EdgeDetectionCameraController()
    @Binding var isPresented: Bool
    let onCapture: (UIImage) -> Void

    @State private var scanLineOffset: CGFloat = 0
    @State private var isScanning = true
    @State private var flashEnabled = false
    @State private var showingDocumentScanner = false
    @State private var capturedImage: UIImage?
    @State private var showingPreview = false
    @State private var autoCapture = true
    @State private var edgeStabilityProgress: CGFloat = 0

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Camera Preview - Full Screen
                EdgeDetectionPreviewLayer(controller: camera)
                    .ignoresSafeArea()

                // Edge Detection Overlay
                EdgeOverlayView(
                    detectedRectangle: camera.detectedRectangle,
                    viewSize: geometry.size,
                    isStable: camera.isEdgeStable
                )
                .ignoresSafeArea()

                // Scanning Overlay (dimmed edges)
                scanningOverlay(geometry: geometry)

                // Controls
                VStack {
                    // Top Bar
                    topBar

                    Spacer()

                    // Edge Detection Status
                    edgeStatusIndicator

                    // Bottom Controls
                    bottomControls(geometry: geometry)
                }
            }
        }
        .statusBarHidden()
        .onAppear {
            camera.configure()
            camera.start()
            camera.onAutoCapture = { image in
                if autoCapture {
                    handleCapturedImage(image)
                }
            }
            startScanAnimation()
        }
        .onDisappear {
            camera.stop()
        }
        .sheet(isPresented: $showingDocumentScanner) {
            DocumentScannerView { images in
                if let first = images.first {
                    capturedImage = first
                    showingPreview = true
                }
                showingDocumentScanner = false
            }
        }
        .fullScreenCover(isPresented: $showingPreview) {
            if let image = capturedImage {
                CapturePreviewView(image: image) { confirmed in
                    if confirmed {
                        onCapture(image)
                        isPresented = false
                    } else {
                        capturedImage = nil
                        showingPreview = false
                        camera.resetStability()
                    }
                }
            }
        }
    }

    // MARK: - Top Bar

    private var topBar: some View {
        HStack {
            // Close Button
            Button(action: { isPresented = false }) {
                Image(systemName: "xmark")
                    .font(.title2.weight(.semibold))
                    .foregroundColor(.white)
                    .frame(width: 44, height: 44)
                    .background(.ultraThinMaterial.opacity(0.8))
                    .clipShape(Circle())
            }

            Spacer()

            // Auto-capture Toggle
            Button(action: { autoCapture.toggle() }) {
                HStack(spacing: 6) {
                    Image(systemName: autoCapture ? "a.circle.fill" : "a.circle")
                    Text("Auto")
                        .font(.caption.bold())
                }
                .foregroundColor(autoCapture ? .tallyAccent : .white)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(.ultraThinMaterial.opacity(0.8))
                .cornerRadius(20)
            }

            // Flash Toggle
            Button(action: {
                flashEnabled.toggle()
                camera.toggleFlash(flashEnabled)
            }) {
                Image(systemName: flashEnabled ? "bolt.fill" : "bolt.slash.fill")
                    .font(.title2.weight(.semibold))
                    .foregroundColor(flashEnabled ? .yellow : .white)
                    .frame(width: 44, height: 44)
                    .background(.ultraThinMaterial.opacity(0.8))
                    .clipShape(Circle())
            }
        }
        .padding(.horizontal, 20)
        .padding(.top, 60)
    }

    // MARK: - Edge Status Indicator

    private var edgeStatusIndicator: some View {
        VStack(spacing: 8) {
            if camera.detectedRectangle != nil {
                HStack(spacing: 8) {
                    Image(systemName: camera.isEdgeStable ? "checkmark.circle.fill" : "viewfinder")
                        .foregroundColor(camera.isEdgeStable ? .green : .tallyAccent)

                    Text(camera.isEdgeStable ? "Hold steady..." : "Receipt detected")
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(.white)
                }
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(.ultraThinMaterial.opacity(0.8))
                .cornerRadius(20)

                // Stability progress bar
                if camera.isEdgeStable && autoCapture {
                    GeometryReader { geo in
                        ZStack(alignment: .leading) {
                            Capsule()
                                .fill(Color.white.opacity(0.3))
                                .frame(height: 4)

                            Capsule()
                                .fill(Color.tallyAccent)
                                .frame(width: geo.size.width * camera.stabilityProgress, height: 4)
                        }
                    }
                    .frame(width: 120, height: 4)
                    .animation(.linear(duration: 0.1), value: camera.stabilityProgress)
                }
            } else {
                Text("Position receipt within frame")
                    .font(.subheadline.weight(.medium))
                    .foregroundColor(.white.opacity(0.9))
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial.opacity(0.6))
                    .cornerRadius(20)
            }
        }
        .padding(.bottom, 20)
    }

    // MARK: - Scanning Overlay

    private func scanningOverlay(geometry: GeometryProxy) -> some View {
        let scanAreaWidth = geometry.size.width * 0.88
        let scanAreaHeight = scanAreaWidth * 1.4

        return ZStack {
            // Only show dimmed overlay when no rectangle detected
            if camera.detectedRectangle == nil {
                Color.black.opacity(0.5)
                    .ignoresSafeArea()
                    .mask(
                        Rectangle()
                            .overlay(
                                RoundedRectangle(cornerRadius: 20)
                                    .frame(width: scanAreaWidth, height: scanAreaHeight)
                                    .blendMode(.destinationOut)
                            )
                    )

                // Guide border
                RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(
                        Color.white.opacity(0.3),
                        style: StrokeStyle(lineWidth: 2, dash: [10, 5])
                    )
                    .frame(width: scanAreaWidth, height: scanAreaHeight)
            }

            // Animated scan line (only when no detection)
            if isScanning && camera.detectedRectangle == nil {
                RoundedRectangle(cornerRadius: 2)
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.tallyAccent.opacity(0),
                                Color.tallyAccent,
                                Color.tallyAccent.opacity(0)
                            ],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .frame(width: scanAreaWidth - 40, height: 3)
                    .shadow(color: Color.tallyAccent.opacity(0.8), radius: 10, y: 0)
                    .offset(y: scanLineOffset - scanAreaHeight / 2 + 20)
            }
        }
    }

    // MARK: - Bottom Controls

    private func bottomControls(geometry: GeometryProxy) -> some View {
        VStack(spacing: 24) {
            // Mode Selector
            HStack(spacing: 30) {
                ModeButton(icon: "camera.fill", label: "Photo", isSelected: true)
                ModeButton(icon: "doc.viewfinder", label: "Document", isSelected: false) {
                    showingDocumentScanner = true
                }
            }
            .padding(.horizontal, 40)

            // Capture Controls
            HStack(spacing: 50) {
                // Gallery
                Button(action: {}) {
                    RoundedRectangle(cornerRadius: 8)
                        .fill(.ultraThinMaterial)
                        .frame(width: 50, height: 50)
                        .overlay(
                            Image(systemName: "photo.fill")
                                .foregroundColor(.white)
                        )
                }

                // Capture Button
                Button(action: manualCapture) {
                    ZStack {
                        Circle()
                            .strokeBorder(Color.white, lineWidth: 4)
                            .frame(width: 80, height: 80)

                        Circle()
                            .fill(Color.white)
                            .frame(width: 65, height: 65)

                        Circle()
                            .fill(camera.detectedRectangle != nil ? Color.tallyAccent : Color.gray)
                            .frame(width: 60, height: 60)

                        Image(systemName: "camera.fill")
                            .font(.title2)
                            .foregroundColor(.white)
                    }
                }

                // Flip Camera
                Button(action: { camera.flipCamera() }) {
                    Circle()
                        .fill(.ultraThinMaterial)
                        .frame(width: 50, height: 50)
                        .overlay(
                            Image(systemName: "camera.rotate.fill")
                                .foregroundColor(.white)
                        )
                }
            }
        }
        .padding(.bottom, 40)
    }

    // MARK: - Actions

    private func startScanAnimation() {
        let scanAreaHeight = UIScreen.main.bounds.width * 0.88 * 1.4

        withAnimation(
            .easeInOut(duration: 2.0)
            .repeatForever(autoreverses: true)
        ) {
            scanLineOffset = scanAreaHeight - 40
        }
    }

    private func manualCapture() {
        let generator = UIImpactFeedbackGenerator(style: .medium)
        generator.impactOccurred()

        camera.capturePhoto { image in
            if let image = image {
                handleCapturedImage(image)
            }
        }
    }

    private func handleCapturedImage(_ image: UIImage) {
        capturedImage = image
        showingPreview = true
    }
}

// MARK: - Edge Detection Camera Controller

class EdgeDetectionCameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate, AVCaptureVideoDataOutputSampleBufferDelegate {
    let session = AVCaptureSession()
    private var photoOutput = AVCapturePhotoOutput()
    private var videoOutput = AVCaptureVideoDataOutput()
    private var currentDevice: AVCaptureDevice?
    private var captureCompletion: ((UIImage?) -> Void)?

    @Published var detectedRectangle: VNRectangleObservation?
    @Published var isEdgeStable = false
    @Published var stabilityProgress: CGFloat = 0

    var onAutoCapture: ((UIImage) -> Void)?

    private var lastRectangles: [VNRectangleObservation] = []
    private var stableFrameCount = 0
    private let requiredStableFrames = 20 // About 0.7 seconds at 30fps
    private var hasAutoCaptured = false
    private let processingQueue = DispatchQueue(label: "com.tallyups.edgedetection", qos: .userInteractive)

    func configure() {
        session.beginConfiguration()
        session.sessionPreset = .photo

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera) else { return }

        currentDevice = camera

        // Configure for better performance
        try? camera.lockForConfiguration()
        if camera.isFocusModeSupported(.continuousAutoFocus) {
            camera.focusMode = .continuousAutoFocus
        }
        if camera.isExposureModeSupported(.continuousAutoExposure) {
            camera.exposureMode = .continuousAutoExposure
        }
        camera.unlockForConfiguration()

        if session.canAddInput(input) {
            session.addInput(input)
        }

        if session.canAddOutput(photoOutput) {
            session.addOutput(photoOutput)
        }

        // Video output for edge detection
        videoOutput.setSampleBufferDelegate(self, queue: processingQueue)
        videoOutput.alwaysDiscardsLateVideoFrames = true
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

    func resetStability() {
        DispatchQueue.main.async {
            self.stableFrameCount = 0
            self.hasAutoCaptured = false
            self.isEdgeStable = false
            self.stabilityProgress = 0
        }
    }

    func capturePhoto(completion: @escaping (UIImage?) -> Void) {
        captureCompletion = completion

        let settings = AVCapturePhotoSettings()
        if let device = currentDevice, device.hasFlash {
            settings.flashMode = device.torchMode == .on ? .on : .off
        }

        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    // MARK: - Video Frame Processing for Edge Detection

    func captureOutput(_ output: AVCaptureOutput, didOutput sampleBuffer: CMSampleBuffer, from connection: AVCaptureConnection) {
        guard let pixelBuffer = CMSampleBufferGetImageBuffer(sampleBuffer) else { return }

        let request = VNDetectRectanglesRequest { [weak self] request, error in
            guard let self = self else { return }

            DispatchQueue.main.async {
                if let results = request.results as? [VNRectangleObservation],
                   let rect = results.first,
                   rect.confidence > 0.8 {
                    self.detectedRectangle = rect
                    self.updateStability(with: rect)
                } else {
                    self.detectedRectangle = nil
                    self.stableFrameCount = 0
                    self.isEdgeStable = false
                    self.stabilityProgress = 0
                }
            }
        }

        request.minimumAspectRatio = 0.3
        request.maximumAspectRatio = 0.9
        request.minimumSize = 0.2
        request.minimumConfidence = 0.7
        request.maximumObservations = 1

        try? VNImageRequestHandler(cvPixelBuffer: pixelBuffer, options: [:]).perform([request])
    }

    private func updateStability(with rect: VNRectangleObservation) {
        if isRectangleStable(rect) {
            stableFrameCount += 1
            stabilityProgress = min(1.0, CGFloat(stableFrameCount) / CGFloat(requiredStableFrames))

            if stableFrameCount >= 5 {
                isEdgeStable = true
            }

            if stableFrameCount >= requiredStableFrames && !hasAutoCaptured {
                hasAutoCaptured = true
                performAutoCapture()
            }
        } else {
            stableFrameCount = max(0, stableFrameCount - 2)
            stabilityProgress = max(0, CGFloat(stableFrameCount) / CGFloat(requiredStableFrames))
            if stableFrameCount < 5 {
                isEdgeStable = false
            }
        }

        // Keep last few rectangles for stability comparison
        lastRectangles.append(rect)
        if lastRectangles.count > 5 {
            lastRectangles.removeFirst()
        }
    }

    private func isRectangleStable(_ rect: VNRectangleObservation) -> Bool {
        guard let lastRect = lastRectangles.last else { return true }

        let threshold: CGFloat = 0.02

        let topLeftDiff = hypot(rect.topLeft.x - lastRect.topLeft.x, rect.topLeft.y - lastRect.topLeft.y)
        let topRightDiff = hypot(rect.topRight.x - lastRect.topRight.x, rect.topRight.y - lastRect.topRight.y)
        let bottomLeftDiff = hypot(rect.bottomLeft.x - lastRect.bottomLeft.x, rect.bottomLeft.y - lastRect.bottomLeft.y)
        let bottomRightDiff = hypot(rect.bottomRight.x - lastRect.bottomRight.x, rect.bottomRight.y - lastRect.bottomRight.y)

        return topLeftDiff < threshold && topRightDiff < threshold &&
               bottomLeftDiff < threshold && bottomRightDiff < threshold
    }

    private func performAutoCapture() {
        // Haptic feedback
        let generator = UINotificationFeedbackGenerator()
        generator.notificationOccurred(.success)

        capturePhoto { [weak self] image in
            guard let self = self, let image = image else { return }

            // Apply perspective correction
            if let correctedImage = self.perspectiveCorrect(image: image) {
                DispatchQueue.main.async {
                    self.onAutoCapture?(correctedImage)
                }
            } else {
                DispatchQueue.main.async {
                    self.onAutoCapture?(image)
                }
            }
        }
    }

    // MARK: - Perspective Correction

    private func perspectiveCorrect(image: UIImage) -> UIImage? {
        guard let rect = detectedRectangle,
              let cgImage = image.cgImage else { return nil }

        let ciImage = CIImage(cgImage: cgImage)

        let imageSize = ciImage.extent.size

        // Convert normalized coordinates to image coordinates
        let topLeft = CGPoint(x: rect.topLeft.x * imageSize.width, y: (1 - rect.topLeft.y) * imageSize.height)
        let topRight = CGPoint(x: rect.topRight.x * imageSize.width, y: (1 - rect.topRight.y) * imageSize.height)
        let bottomLeft = CGPoint(x: rect.bottomLeft.x * imageSize.width, y: (1 - rect.bottomLeft.y) * imageSize.height)
        let bottomRight = CGPoint(x: rect.bottomRight.x * imageSize.width, y: (1 - rect.bottomRight.y) * imageSize.height)

        guard let filter = CIFilter(name: "CIPerspectiveCorrection") else { return nil }

        filter.setValue(ciImage, forKey: kCIInputImageKey)
        filter.setValue(CIVector(cgPoint: topLeft), forKey: "inputTopLeft")
        filter.setValue(CIVector(cgPoint: topRight), forKey: "inputTopRight")
        filter.setValue(CIVector(cgPoint: bottomLeft), forKey: "inputBottomLeft")
        filter.setValue(CIVector(cgPoint: bottomRight), forKey: "inputBottomRight")

        guard let outputImage = filter.outputImage else { return nil }

        let context = CIContext()
        guard let outputCGImage = context.createCGImage(outputImage, from: outputImage.extent) else { return nil }

        return UIImage(cgImage: outputCGImage, scale: image.scale, orientation: image.imageOrientation)
    }

    // MARK: - Photo Capture Delegate

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            captureCompletion?(nil)
            return
        }

        let fixedImage = image.fixedOrientation

        // Apply perspective correction if we have a detected rectangle
        if let corrected = perspectiveCorrect(image: fixedImage) {
            let enhanced = ScannerService.shared.enhanceImage(corrected)
            captureCompletion?(enhanced)
        } else {
            let enhanced = ScannerService.shared.enhanceImage(fixedImage)
            captureCompletion?(enhanced)
        }
    }
}

// MARK: - Edge Detection Preview Layer

struct EdgeDetectionPreviewLayer: UIViewRepresentable {
    @ObservedObject var controller: EdgeDetectionCameraController

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.backgroundColor = .black

        let previewLayer = AVCaptureVideoPreviewLayer(session: controller.session)
        previewLayer.videoGravity = .resizeAspectFill
        previewLayer.frame = view.bounds
        view.layer.addSublayer(previewLayer)

        context.coordinator.previewLayer = previewLayer

        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        DispatchQueue.main.async {
            context.coordinator.previewLayer?.frame = uiView.bounds
        }
    }

    func makeCoordinator() -> Coordinator {
        Coordinator()
    }

    class Coordinator {
        var previewLayer: AVCaptureVideoPreviewLayer?
    }
}

// MARK: - Edge Overlay View

struct EdgeOverlayView: View {
    let detectedRectangle: VNRectangleObservation?
    let viewSize: CGSize
    let isStable: Bool

    var body: some View {
        Canvas { context, size in
            guard let rect = detectedRectangle else { return }

            // Convert normalized coordinates to view coordinates
            let topLeft = CGPoint(x: rect.topLeft.x * size.width, y: (1 - rect.topLeft.y) * size.height)
            let topRight = CGPoint(x: rect.topRight.x * size.width, y: (1 - rect.topRight.y) * size.height)
            let bottomLeft = CGPoint(x: rect.bottomLeft.x * size.width, y: (1 - rect.bottomLeft.y) * size.height)
            let bottomRight = CGPoint(x: rect.bottomRight.x * size.width, y: (1 - rect.bottomRight.y) * size.height)

            // Draw edge lines
            var path = Path()
            path.move(to: topLeft)
            path.addLine(to: topRight)
            path.addLine(to: bottomRight)
            path.addLine(to: bottomLeft)
            path.closeSubpath()

            let strokeColor = isStable ? Color.green : Color.tallyAccent
            context.stroke(path, with: .color(strokeColor), lineWidth: 3)

            // Fill with slight tint
            context.fill(path, with: .color(strokeColor.opacity(0.1)))

            // Draw corner markers
            let cornerSize: CGFloat = 20
            let corners = [topLeft, topRight, bottomRight, bottomLeft]

            for corner in corners {
                var cornerPath = Path()
                cornerPath.addEllipse(in: CGRect(x: corner.x - cornerSize/2, y: corner.y - cornerSize/2, width: cornerSize, height: cornerSize))
                context.fill(cornerPath, with: .color(strokeColor))

                // Inner white dot
                var innerPath = Path()
                innerPath.addEllipse(in: CGRect(x: corner.x - 4, y: corner.y - 4, width: 8, height: 8))
                context.fill(innerPath, with: .color(.white))
            }
        }
    }
}

// MARK: - Mode Button

struct ModeButton: View {
    let icon: String
    let label: String
    var isSelected: Bool = false
    var action: (() -> Void)? = nil

    var body: some View {
        Button(action: { action?() }) {
            VStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.title3)
                Text(label)
                    .font(.caption)
            }
            .foregroundColor(isSelected ? .tallyAccent : .white.opacity(0.7))
        }
    }
}

// MARK: - Capture Preview View

struct CapturePreviewView: View {
    let image: UIImage
    let onConfirm: (Bool) -> Void

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            VStack(spacing: 0) {
                // Image Preview
                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
                    .cornerRadius(16)
                    .padding()

                Spacer()

                // Actions
                HStack(spacing: 60) {
                    // Retake
                    Button(action: { onConfirm(false) }) {
                        VStack(spacing: 8) {
                            Circle()
                                .strokeBorder(Color.white, lineWidth: 2)
                                .frame(width: 60, height: 60)
                                .overlay(
                                    Image(systemName: "arrow.counterclockwise")
                                        .font(.title2)
                                        .foregroundColor(.white)
                                )
                            Text("Retake")
                                .font(.caption)
                                .foregroundColor(.white)
                        }
                    }

                    // Use Photo
                    Button(action: { onConfirm(true) }) {
                        VStack(spacing: 8) {
                            Circle()
                                .fill(Color.tallyAccent)
                                .frame(width: 60, height: 60)
                                .overlay(
                                    Image(systemName: "checkmark")
                                        .font(.title2.weight(.bold))
                                        .foregroundColor(.black)
                                )
                            Text("Use Photo")
                                .font(.caption)
                                .foregroundColor(.white)
                        }
                    }
                }
                .padding(.bottom, 60)
            }
        }
        .statusBarHidden()
    }
}

#Preview {
    FullScreenScannerView(isPresented: .constant(true)) { _ in }
}

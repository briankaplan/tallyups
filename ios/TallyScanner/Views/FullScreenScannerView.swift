import SwiftUI
import AVFoundation
import VisionKit

/// Full-screen immersive receipt scanner with animated scan line
struct FullScreenScannerView: View {
    @StateObject private var camera = FullScreenCameraController()
    @Binding var isPresented: Bool
    let onCapture: (UIImage) -> Void

    @State private var scanLineOffset: CGFloat = 0
    @State private var isScanning = true
    @State private var flashEnabled = false
    @State private var showingDocumentScanner = false
    @State private var capturedImage: UIImage?
    @State private var showingPreview = false
    @State private var zoomLevel: CGFloat = 1.0

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Camera Preview - Full Screen
                CameraPreviewLayer(session: camera.session)
                    .ignoresSafeArea()

                // Scanning Overlay
                scanningOverlay(geometry: geometry)

                // Controls
                VStack {
                    // Top Bar
                    topBar

                    Spacer()

                    // Bottom Controls
                    bottomControls(geometry: geometry)
                }
            }
        }
        .statusBarHidden()
        .onAppear {
            camera.configure()
            camera.start()
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

    // MARK: - Scanning Overlay

    private func scanningOverlay(geometry: GeometryProxy) -> some View {
        let scanAreaWidth = geometry.size.width * 0.88
        let scanAreaHeight = scanAreaWidth * 1.4 // Receipt aspect ratio

        return ZStack {
            // Darkened edges
            Color.black.opacity(0.6)
                .ignoresSafeArea()
                .mask(
                    Rectangle()
                        .overlay(
                            RoundedRectangle(cornerRadius: 20)
                                .frame(width: scanAreaWidth, height: scanAreaHeight)
                                .blendMode(.destinationOut)
                        )
                )

            // Scan area border
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(
                    LinearGradient(
                        colors: [Color.tallyAccent, Color.tallyAccent.opacity(0.5)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 3
                )
                .frame(width: scanAreaWidth, height: scanAreaHeight)

            // Corner accents
            cornerAccents(width: scanAreaWidth, height: scanAreaHeight)

            // Animated scan line
            if isScanning {
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

            // Instructions
            VStack {
                Spacer()
                    .frame(height: (geometry.size.height - scanAreaHeight) / 2 + scanAreaHeight + 20)

                Text("Position receipt within frame")
                    .font(.subheadline.weight(.medium))
                    .foregroundColor(.white.opacity(0.9))
                    .padding(.horizontal, 20)
                    .padding(.vertical, 10)
                    .background(.ultraThinMaterial.opacity(0.6))
                    .cornerRadius(20)

                Spacer()
            }
        }
    }

    private func cornerAccents(width: CGFloat, height: CGFloat) -> some View {
        let cornerLength: CGFloat = 30
        let cornerWidth: CGFloat = 4

        return ZStack {
            // Top Left
            VStack(spacing: 0) {
                HStack(spacing: 0) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.tallyAccent)
                        .frame(width: cornerLength, height: cornerWidth)
                    Spacer()
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.tallyAccent)
                    .frame(width: cornerWidth, height: cornerLength - cornerWidth)
                    .frame(maxWidth: .infinity, alignment: .leading)
                Spacer()
            }

            // Top Right
            VStack(spacing: 0) {
                HStack(spacing: 0) {
                    Spacer()
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.tallyAccent)
                        .frame(width: cornerLength, height: cornerWidth)
                }
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.tallyAccent)
                    .frame(width: cornerWidth, height: cornerLength - cornerWidth)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                Spacer()
            }

            // Bottom Left
            VStack(spacing: 0) {
                Spacer()
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.tallyAccent)
                    .frame(width: cornerWidth, height: cornerLength - cornerWidth)
                    .frame(maxWidth: .infinity, alignment: .leading)
                HStack(spacing: 0) {
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.tallyAccent)
                        .frame(width: cornerLength, height: cornerWidth)
                    Spacer()
                }
            }

            // Bottom Right
            VStack(spacing: 0) {
                Spacer()
                RoundedRectangle(cornerRadius: 2)
                    .fill(Color.tallyAccent)
                    .frame(width: cornerWidth, height: cornerLength - cornerWidth)
                    .frame(maxWidth: .infinity, alignment: .trailing)
                HStack(spacing: 0) {
                    Spacer()
                    RoundedRectangle(cornerRadius: 2)
                        .fill(Color.tallyAccent)
                        .frame(width: cornerLength, height: cornerWidth)
                }
            }
        }
        .frame(width: width - 10, height: height - 10)
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
                Button(action: capturePhoto) {
                    ZStack {
                        Circle()
                            .strokeBorder(Color.white, lineWidth: 4)
                            .frame(width: 80, height: 80)

                        Circle()
                            .fill(Color.white)
                            .frame(width: 65, height: 65)

                        Circle()
                            .fill(Color.tallyAccent)
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

    private func capturePhoto() {
        // Haptic feedback
        let generator = UIImpactFeedbackGenerator(style: .medium)
        generator.impactOccurred()

        camera.capturePhoto { image in
            if let image = image {
                capturedImage = image
                showingPreview = true
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

// MARK: - Camera Preview Layer

struct CameraPreviewLayer: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.backgroundColor = .black

        let previewLayer = AVCaptureVideoPreviewLayer(session: session)
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

// MARK: - Full Screen Camera Controller

class FullScreenCameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    private var photoOutput = AVCapturePhotoOutput()
    private var currentDevice: AVCaptureDevice?
    private var captureCompletion: ((UIImage?) -> Void)?

    func configure() {
        session.beginConfiguration()
        session.sessionPreset = .photo

        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera) else { return }

        currentDevice = camera

        if session.canAddInput(input) {
            session.addInput(input)
        }

        if session.canAddOutput(photoOutput) {
            session.addOutput(photoOutput)
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

    func capturePhoto(completion: @escaping (UIImage?) -> Void) {
        captureCompletion = completion

        let settings = AVCapturePhotoSettings()
        if let device = currentDevice, device.hasFlash {
            settings.flashMode = device.torchMode == .on ? .on : .off
        }

        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            captureCompletion?(nil)
            return
        }

        let fixedImage = image.fixedOrientation
        let enhanced = ScannerService.shared.enhanceImage(fixedImage)
        captureCompletion?(enhanced)
    }
}

// MARK: - Capture Preview View

struct CapturePreviewView: View {
    let image: UIImage
    let onConfirm: (Bool) -> Void

    @State private var showingOCRProgress = false

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

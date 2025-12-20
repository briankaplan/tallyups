import SwiftUI
import AVFoundation

/// Simple camera capture view for quick receipt photos
struct CameraView: UIViewControllerRepresentable {
    let onCapture: (UIImage) -> Void

    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> UIImagePickerController {
        let picker = UIImagePickerController()
        picker.sourceType = .camera
        picker.cameraCaptureMode = .photo
        picker.cameraDevice = .rear
        picker.delegate = context.coordinator

        // Enable flash by default for receipts
        if UIImagePickerController.isFlashAvailable(for: .rear) {
            picker.cameraFlashMode = .auto
        }

        return picker
    }

    func updateUIViewController(_ uiViewController: UIImagePickerController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    class Coordinator: NSObject, UIImagePickerControllerDelegate, UINavigationControllerDelegate {
        let parent: CameraView

        init(_ parent: CameraView) {
            self.parent = parent
        }

        func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo info: [UIImagePickerController.InfoKey : Any]) {
            if let image = info[.originalImage] as? UIImage {
                // Fix orientation and enhance
                let fixedImage = image.fixedOrientation
                let enhanced = ScannerService.shared.enhanceImage(fixedImage)
                parent.onCapture(enhanced)
            }
            parent.dismiss()
        }

        func imagePickerControllerDidCancel(_ picker: UIImagePickerController) {
            parent.dismiss()
        }
    }
}

// MARK: - Advanced Camera View with Custom UI
struct AdvancedCameraView: View {
    @StateObject private var camera = CameraController()
    let onCapture: (UIImage) -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var flashMode: AVCaptureDevice.FlashMode = .auto
    @State private var showingPreview = false
    @State private var capturedImage: UIImage?

    var body: some View {
        ZStack {
            // Camera Preview
            CameraPreviewView(session: camera.session)
                .ignoresSafeArea()

            // Overlay
            VStack {
                // Top Bar
                HStack {
                    Button(action: { dismiss() }) {
                        Image(systemName: "xmark")
                            .font(.title2)
                            .foregroundColor(.white)
                            .padding()
                    }

                    Spacer()

                    Button(action: { cycleFlashMode() }) {
                        Image(systemName: flashIcon)
                            .font(.title2)
                            .foregroundColor(.white)
                            .padding()
                    }
                }
                .background(.ultraThinMaterial.opacity(0.5))

                Spacer()

                // Receipt guide overlay
                receiptGuideOverlay

                Spacer()

                // Capture Button
                HStack {
                    // Gallery shortcut
                    Button(action: {}) {
                        Image(systemName: "photo.fill")
                            .font(.title)
                            .foregroundColor(.white)
                            .frame(width: 60, height: 60)
                    }

                    Spacer()

                    // Capture
                    Button(action: capturePhoto) {
                        ZStack {
                            Circle()
                                .strokeBorder(.white, lineWidth: 4)
                                .frame(width: 80, height: 80)
                            Circle()
                                .fill(.white)
                                .frame(width: 65, height: 65)
                        }
                    }

                    Spacer()

                    // Flip camera
                    Button(action: { camera.flipCamera() }) {
                        Image(systemName: "camera.rotate.fill")
                            .font(.title)
                            .foregroundColor(.white)
                            .frame(width: 60, height: 60)
                    }
                }
                .padding(.horizontal, 30)
                .padding(.bottom, 30)
            }
        }
        .onAppear {
            camera.configure()
            camera.start()
        }
        .onDisappear {
            camera.stop()
        }
        .sheet(isPresented: $showingPreview) {
            if let image = capturedImage {
                ImagePreviewView(image: image) { confirmed in
                    if confirmed {
                        onCapture(image)
                        dismiss()
                    } else {
                        showingPreview = false
                        capturedImage = nil
                    }
                }
            }
        }
    }

    private var flashIcon: String {
        switch flashMode {
        case .auto: return "bolt.badge.automatic.fill"
        case .on: return "bolt.fill"
        case .off: return "bolt.slash.fill"
        @unknown default: return "bolt.fill"
        }
    }

    private func cycleFlashMode() {
        switch flashMode {
        case .auto: flashMode = .on
        case .on: flashMode = .off
        case .off: flashMode = .auto
        @unknown default: flashMode = .auto
        }
    }

    private var receiptGuideOverlay: some View {
        RoundedRectangle(cornerRadius: 16)
            .strokeBorder(Color.tallyAccent.opacity(0.6), lineWidth: 2, antialiased: true)
            .frame(width: UIScreen.main.bounds.width * 0.85, height: UIScreen.main.bounds.width * 1.2)
            .overlay {
                VStack {
                    Text("Align receipt within frame")
                        .font(.caption)
                        .foregroundColor(.white)
                        .padding(8)
                        .background(.ultraThinMaterial)
                        .cornerRadius(8)
                    Spacer()
                }
                .padding(.top, 16)
            }
    }

    private func capturePhoto() {
        camera.capturePhoto(flashMode: flashMode) { image in
            capturedImage = image
            showingPreview = true
        }
    }
}

// MARK: - Camera Controller

class CameraController: NSObject, ObservableObject, AVCapturePhotoCaptureDelegate {
    let session = AVCaptureSession()
    private var photoOutput = AVCapturePhotoOutput()
    private var captureCompletion: ((UIImage?) -> Void)?

    func configure() {
        session.beginConfiguration()
        session.sessionPreset = .photo

        // Add input
        guard let camera = AVCaptureDevice.default(.builtInWideAngleCamera, for: .video, position: .back),
              let input = try? AVCaptureDeviceInput(device: camera) else { return }

        if session.canAddInput(input) {
            session.addInput(input)
        }

        // Add output
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

        if session.canAddInput(newInput) {
            session.addInput(newInput)
        }

        session.commitConfiguration()
    }

    func capturePhoto(flashMode: AVCaptureDevice.FlashMode, completion: @escaping (UIImage?) -> Void) {
        captureCompletion = completion

        let settings = AVCapturePhotoSettings()
        settings.flashMode = flashMode

        photoOutput.capturePhoto(with: settings, delegate: self)
    }

    func photoOutput(_ output: AVCapturePhotoOutput, didFinishProcessingPhoto photo: AVCapturePhoto, error: Error?) {
        guard let data = photo.fileDataRepresentation(),
              let image = UIImage(data: data) else {
            captureCompletion?(nil)
            return
        }

        let fixed = image.fixedOrientation
        let enhanced = ScannerService.shared.enhanceImage(fixed)
        captureCompletion?(enhanced)
    }
}

// MARK: - Camera Preview

struct CameraPreviewView: UIViewRepresentable {
    let session: AVCaptureSession

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)

        let previewLayer = AVCaptureVideoPreviewLayer(session: session)
        previewLayer.videoGravity = .resizeAspectFill
        previewLayer.frame = view.bounds

        view.layer.addSublayer(previewLayer)

        DispatchQueue.main.async {
            previewLayer.frame = view.bounds
        }

        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        if let previewLayer = uiView.layer.sublayers?.first as? AVCaptureVideoPreviewLayer {
            previewLayer.frame = uiView.bounds
        }
    }
}

// MARK: - Image Preview

struct ImagePreviewView: View {
    let image: UIImage
    let onConfirm: (Bool) -> Void

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                Image(uiImage: image)
                    .resizable()
                    .scaledToFit()
            }
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Retake") {
                        onConfirm(false)
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Use Photo") {
                        onConfirm(true)
                    }
                    .bold()
                    .foregroundColor(.tallyAccent)
                }
            }
        }
    }
}

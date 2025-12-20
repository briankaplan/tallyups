import SwiftUI
import VisionKit

/// VisionKit document scanner with auto-edge detection
struct DocumentScannerView: UIViewControllerRepresentable {
    let onScan: ([UIImage]) -> Void

    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> VNDocumentCameraViewController {
        let scanner = VNDocumentCameraViewController()
        scanner.delegate = context.coordinator
        return scanner
    }

    func updateUIViewController(_ uiViewController: VNDocumentCameraViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    class Coordinator: NSObject, VNDocumentCameraViewControllerDelegate {
        let parent: DocumentScannerView

        init(_ parent: DocumentScannerView) {
            self.parent = parent
        }

        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFinishWith scan: VNDocumentCameraScan) {
            var images: [UIImage] = []

            for i in 0..<scan.pageCount {
                let image = scan.imageOfPage(at: i)
                // Apply enhancements for better OCR
                let enhanced = ScannerService.shared.enhanceImage(image)
                images.append(enhanced)
            }

            parent.onScan(images)
        }

        func documentCameraViewControllerDidCancel(_ controller: VNDocumentCameraViewController) {
            parent.dismiss()
        }

        func documentCameraViewController(_ controller: VNDocumentCameraViewController, didFailWithError error: Error) {
            print("Document scanner error: \(error)")
            parent.dismiss()
        }
    }
}

#Preview {
    DocumentScannerView { _ in }
}

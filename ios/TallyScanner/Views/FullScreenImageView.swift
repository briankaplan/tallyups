import SwiftUI

struct FullScreenImageView: View {
    let imageURL: String?

    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var showControls = true

    var body: some View {
        GeometryReader { geometry in
            ZStack {
                // Background
                Color.black.ignoresSafeArea()

                // Image
                AsyncImage(url: URL(string: imageURL ?? "")) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .scaleEffect(scale)
                            .offset(offset)
                            .gesture(pinchGesture)
                            .gesture(panGesture)
                            .gesture(doubleTapGesture)
                            .onTapGesture {
                                withAnimation(.easeInOut(duration: 0.2)) {
                                    showControls.toggle()
                                }
                            }
                    case .failure:
                        VStack(spacing: 16) {
                            Image(systemName: "photo.fill")
                                .font(.system(size: 48))
                                .foregroundColor(.gray)
                            Text("Failed to load image")
                                .foregroundColor(.gray)
                        }
                    case .empty:
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .white))
                            .scaleEffect(1.5)
                    @unknown default:
                        EmptyView()
                    }
                }

                // Controls overlay
                if showControls {
                    VStack {
                        // Top bar
                        HStack {
                            Button(action: { dismiss() }) {
                                Image(systemName: "xmark")
                                    .font(.system(size: 16, weight: .semibold))
                                    .foregroundColor(.white)
                                    .padding(12)
                                    .background(Color.black.opacity(0.5))
                                    .clipShape(Circle())
                            }

                            Spacer()

                            if scale > 1.0 {
                                Button(action: resetZoom) {
                                    Image(systemName: "arrow.counterclockwise")
                                        .font(.system(size: 16, weight: .semibold))
                                        .foregroundColor(.white)
                                        .padding(12)
                                        .background(Color.black.opacity(0.5))
                                        .clipShape(Circle())
                                }
                            }

                            // Share button
                            if let url = imageURL, let shareURL = URL(string: url) {
                                ShareLink(item: shareURL) {
                                    Image(systemName: "square.and.arrow.up")
                                        .font(.system(size: 16, weight: .semibold))
                                        .foregroundColor(.white)
                                        .padding(12)
                                        .background(Color.black.opacity(0.5))
                                        .clipShape(Circle())
                                }
                            }
                        }
                        .padding()

                        Spacer()

                        // Bottom hint
                        Text(zoomHint)
                            .font(.caption)
                            .foregroundColor(.white.opacity(0.7))
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(Color.black.opacity(0.5))
                            .cornerRadius(20)
                            .padding(.bottom, 40)
                    }
                    .transition(.opacity)
                }
            }
        }
        .ignoresSafeArea()
        .statusBarHidden(!showControls)
    }

    // MARK: - Zoom Hint

    private var zoomHint: String {
        if scale > 1.0 {
            return "Pinch or double-tap to zoom out"
        } else {
            return "Pinch or double-tap to zoom in"
        }
    }

    // MARK: - Gestures

    private var pinchGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                let delta = value / lastScale
                lastScale = value
                scale = min(max(scale * delta, 0.5), 5.0)
            }
            .onEnded { _ in
                lastScale = 1.0
                withAnimation(.spring(response: 0.3)) {
                    if scale < 1.0 {
                        scale = 1.0
                        offset = .zero
                        lastOffset = .zero
                    }
                }
            }
    }

    private var panGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                guard scale > 1.0 else { return }
                offset = CGSize(
                    width: lastOffset.width + value.translation.width,
                    height: lastOffset.height + value.translation.height
                )
            }
            .onEnded { value in
                lastOffset = offset

                // Dismiss if dragged far enough at 1x zoom
                if scale <= 1.0 && abs(value.translation.height) > 100 {
                    dismiss()
                }
            }
    }

    private var doubleTapGesture: some Gesture {
        TapGesture(count: 2)
            .onEnded {
                withAnimation(.spring(response: 0.3)) {
                    if scale > 1.0 {
                        resetZoom()
                    } else {
                        scale = 3.0
                    }
                }
            }
    }

    private func resetZoom() {
        withAnimation(.spring(response: 0.3)) {
            scale = 1.0
            offset = .zero
            lastOffset = .zero
        }
    }
}

#Preview {
    FullScreenImageView(imageURL: "https://example.com/receipt.jpg")
}

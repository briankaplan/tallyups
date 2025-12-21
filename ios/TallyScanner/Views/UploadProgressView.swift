import SwiftUI

/// Floating upload progress indicator
struct UploadProgressView: View {
    @EnvironmentObject var uploadQueue: UploadQueue
    @EnvironmentObject var networkMonitor: NetworkMonitor

    var body: some View {
        if uploadQueue.pendingCount > 0 {
            VStack(spacing: 8) {
                // Progress Bar
                if uploadQueue.isUploading, let progress = uploadQueue.currentProgress {
                    GeometryReader { geometry in
                        ZStack(alignment: .leading) {
                            Rectangle()
                                .fill(Color.gray.opacity(0.3))
                                .frame(height: 4)
                                .cornerRadius(2)

                            Rectangle()
                                .fill(Color.tallyAccent)
                                .frame(width: geometry.size.width * progress, height: 4)
                                .cornerRadius(2)
                        }
                    }
                    .frame(height: 4)
                }

                // Status
                HStack {
                    if !networkMonitor.isConnected {
                        Image(systemName: "wifi.slash")
                            .foregroundColor(.orange)
                        Text("Waiting for network...")
                            .font(.caption)
                            .foregroundColor(.orange)
                    } else if uploadQueue.isUploading {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .tallyAccent))
                            .scaleEffect(0.8)
                        Text("Uploading \(uploadQueue.pendingCount) receipt\(uploadQueue.pendingCount == 1 ? "" : "s")...")
                            .font(.caption)
                            .foregroundColor(.white)
                    } else {
                        Image(systemName: "clock.fill")
                            .foregroundColor(.orange)
                        Text("\(uploadQueue.pendingCount) pending")
                            .font(.caption)
                            .foregroundColor(.white)
                    }

                    Spacer()

                    if let error = uploadQueue.lastError {
                        Text(error)
                            .font(.caption2)
                            .foregroundColor(.red)
                            .lineLimit(1)
                    }
                }
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 12)
            .background(Color.tallyCard)
            .cornerRadius(16)
            .shadow(color: .black.opacity(0.3), radius: 8, y: 4)
            .padding(.horizontal)
            .animation(.easeInOut, value: uploadQueue.isUploading)
        }
    }
}

/// Full-screen upload queue view
struct UploadQueueView: View {
    @EnvironmentObject var uploadQueue: UploadQueue
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                if uploadQueue.pendingItems.isEmpty {
                    emptyState
                } else {
                    queueList
                }
            }
            .navigationTitle("Upload Queue")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                }

                if !uploadQueue.pendingItems.isEmpty {
                    ToolbarItem(placement: .topBarTrailing) {
                        Menu {
                            Button(role: .destructive) {
                                uploadQueue.clearAll()
                            } label: {
                                Label("Clear All", systemImage: "trash")
                            }
                        } label: {
                            Image(systemName: "ellipsis.circle")
                        }
                    }
                }
            }
        }
    }

    private var emptyState: some View {
        VStack(spacing: 16) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 44))
                .foregroundColor(.tallyAccent)
            Text("All caught up!")
                .font(.headline)
                .foregroundColor(.white)
            Text("No pending uploads")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
    }

    private var queueList: some View {
        List {
            ForEach(uploadQueue.pendingItems) { item in
                UploadItemRow(item: item)
            }
            .onDelete { indexSet in
                for index in indexSet {
                    uploadQueue.remove(uploadQueue.pendingItems[index])
                }
            }
        }
        .listStyle(.plain)
    }
}

struct UploadItemRow: View {
    let item: UploadItem

    var body: some View {
        HStack(spacing: 12) {
            // Thumbnail
            if let image = UIImage(data: item.imageData) {
                Image(uiImage: image)
                    .resizable()
                    .scaledToFill()
                    .frame(width: 50, height: 50)
                    .cornerRadius(8)
                    .clipped()
            } else {
                Rectangle()
                    .fill(Color.gray.opacity(0.3))
                    .frame(width: 50, height: 50)
                    .cornerRadius(8)
                    .overlay {
                        Image(systemName: "doc.text.fill")
                            .foregroundColor(.gray)
                    }
            }

            // Details
            VStack(alignment: .leading, spacing: 4) {
                Text(item.merchant ?? "Unknown")
                    .font(.headline)
                    .foregroundColor(.white)

                HStack {
                    statusBadge

                    if let amount = item.amount {
                        Text(formatCurrency(amount))
                            .font(.caption)
                            .foregroundColor(.tallyAccent)
                    }
                }

                if let error = item.lastError {
                    Text(error)
                        .font(.caption2)
                        .foregroundColor(.red)
                        .lineLimit(1)
                }
            }

            Spacer()

            // Retry Count
            if item.retryCount > 0 {
                Text("Retry \(item.retryCount)")
                    .font(.caption2)
                    .foregroundColor(.orange)
            }
        }
        .padding(.vertical, 4)
    }

    private var statusBadge: some View {
        HStack(spacing: 4) {
            switch item.status {
            case .pending:
                Image(systemName: "clock.fill")
                    .foregroundColor(.orange)
                Text("Pending")
            case .uploading:
                ProgressView()
                    .scaleEffect(0.6)
                Text("Uploading")
            case .completed:
                Image(systemName: "checkmark.circle.fill")
                    .foregroundColor(.green)
                Text("Done")
            case .failed:
                Image(systemName: "xmark.circle.fill")
                    .foregroundColor(.red)
                Text("Failed")
            }
        }
        .font(.caption)
        .foregroundColor(.gray)
    }

    private func formatCurrency(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }
}

#Preview {
    VStack {
        UploadProgressView()
        Spacer()
    }
    .background(Color.tallyBackground)
    .environmentObject(UploadQueue.shared)
    .environmentObject(NetworkMonitor.shared)
}

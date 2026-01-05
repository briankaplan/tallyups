import SwiftUI

struct ReceiptDetailView: View {
    let receipt: Receipt

    @Environment(\.dismiss) private var dismiss
    @State private var isEditing = false
    @State private var editedMerchant = ""
    @State private var editedAmount = ""
    @State private var editedDate = Date()
    @State private var editedCategory = ""
    @State private var editedNotes = ""
    @State private var isSaving = false
    @State private var showingDeleteConfirm = false

    // Pinch-to-zoom state
    @State private var imageScale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var imageOffset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @State private var showFullScreenImage = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Receipt Image
                    receiptImage

                    // Details Card
                    detailsCard

                    // OCR Confidence
                    if let confidence = receipt.ocrConfidence {
                        confidenceCard(confidence)
                    }

                    // Actions
                    actionsCard
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Receipt Details")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(isEditing ? "Done" : "Edit") {
                        if isEditing {
                            // Haptic feedback: save action
                            HapticService.shared.buttonPress()
                            saveChanges()
                        } else {
                            // Haptic feedback: entering edit mode
                            HapticService.shared.selection()
                            startEditing()
                        }
                    }
                    .bold()
                    .foregroundColor(.tallyAccent)
                }
            }
            .alert("Delete Receipt", isPresented: $showingDeleteConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Delete", role: .destructive) {
                    deleteReceipt()
                }
            } message: {
                Text("Are you sure you want to delete this receipt? This action cannot be undone.")
            }
        }
    }

    // MARK: - Receipt Image

    private var receiptImage: some View {
        AsyncImage(url: URL(string: receipt.imageURL ?? "")) { phase in
            switch phase {
            case .success(let image):
                image
                    .resizable()
                    .scaledToFit()
                    .scaleEffect(imageScale)
                    .offset(imageOffset)
                    .cornerRadius(12)
                    .gesture(pinchGesture)
                    .gesture(panGesture)
                    .gesture(doubleTapGesture)
                    .onTapGesture {
                        showFullScreenImage = true
                    }
                    .animation(.spring(response: 0.3), value: imageScale)
                    .animation(.spring(response: 0.3), value: imageOffset)
                    .accessibilityLabel(receiptImageAccessibilityLabel)
                    .accessibilityHint("Double tap to view full screen. Pinch to zoom.")
                    .accessibilityAddTraits(.isImage)
            case .failure:
                VStack {
                    Image(systemName: "photo.fill")
                        .font(.largeTitle)
                        .foregroundColor(.gray)
                    Text("Failed to load image")
                        .font(.caption)
                        .foregroundColor(.gray)
                }
                .frame(height: 200)
                .frame(maxWidth: .infinity)
                .background(Color.tallyCard)
                .cornerRadius(12)
                .accessibilityLabel("Receipt image failed to load")
            case .empty:
                ProgressView()
                    .frame(height: 200)
                    .frame(maxWidth: .infinity)
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                    .accessibilityLabel("Loading receipt image")
            @unknown default:
                EmptyView()
            }
        }
        .overlay(alignment: .bottomTrailing) {
            if imageScale > 1.0 {
                Button(action: resetZoom) {
                    Image(systemName: "arrow.counterclockwise")
                        .font(.caption)
                        .foregroundColor(.white)
                        .padding(8)
                        .background(Color.black.opacity(0.6))
                        .clipShape(Circle())
                }
                .padding(8)
                .accessibilityLabel("Reset zoom")
                .accessibilityHint("Double tap to reset image to original size")
            }
        }
        .fullScreenCover(isPresented: $showFullScreenImage) {
            FullScreenImageView(imageURL: receipt.imageURL)
        }
    }

    private var receiptImageAccessibilityLabel: String {
        var label = "Receipt image"
        if let merchant = receipt.merchant {
            label += " from \(merchant)"
        }
        label += ", \(receipt.formattedAmount)"
        if imageScale > 1.0 {
            label += ", zoomed to \(Int(imageScale * 100)) percent"
        }
        return label
    }

    // MARK: - Gestures

    private var pinchGesture: some Gesture {
        MagnificationGesture()
            .onChanged { value in
                let delta = value / lastScale
                lastScale = value
                imageScale = min(max(imageScale * delta, 1.0), 5.0)
            }
            .onEnded { _ in
                lastScale = 1.0
                if imageScale < 1.0 {
                    resetZoom()
                }
            }
    }

    private var panGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                guard imageScale > 1.0 else { return }
                imageOffset = CGSize(
                    width: lastOffset.width + value.translation.width,
                    height: lastOffset.height + value.translation.height
                )
            }
            .onEnded { _ in
                lastOffset = imageOffset
            }
    }

    private var doubleTapGesture: some Gesture {
        TapGesture(count: 2)
            .onEnded {
                withAnimation(.spring(response: 0.3)) {
                    if imageScale > 1.0 {
                        resetZoom()
                    } else {
                        imageScale = 2.5
                    }
                }
            }
    }

    private func resetZoom() {
        withAnimation(.spring(response: 0.3)) {
            imageScale = 1.0
            imageOffset = .zero
            lastOffset = .zero
        }
    }

    // MARK: - Details Card

    private var detailsCard: some View {
        VStack(spacing: 16) {
            if isEditing {
                editingFields
            } else {
                displayFields
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    private var displayFields: some View {
        VStack(spacing: 16) {
            ReceiptDetailRow(label: "Merchant", value: receipt.merchant ?? "Unknown")
            ReceiptDetailRow(label: "Amount", value: receipt.formattedAmount)
            ReceiptDetailRow(label: "Date", value: receipt.formattedDate)

            if let category = receipt.category {
                ReceiptDetailRow(label: "Category", value: category)
            }

            if let business = receipt.business {
                ReceiptDetailRow(label: "Business", value: businessDisplayName(business))
            }

            ReceiptDetailRow(label: "Status", value: receipt.status.displayName)

            if let notes = receipt.notes, !notes.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Notes")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                    Text(notes)
                        .foregroundColor(.white)
                }
                .frame(maxWidth: .infinity, alignment: .leading)
            }

            if let source = receipt.source {
                ReceiptDetailRow(label: "Source", value: source)
            }
        }
    }

    private var editingFields: some View {
        VStack(spacing: 16) {
            EditableField(label: "Merchant", text: $editedMerchant)

            EditableField(label: "Amount", text: $editedAmount, keyboardType: .decimalPad)

            VStack(alignment: .leading, spacing: 8) {
                Text("Date")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                DatePicker("", selection: $editedDate, displayedComponents: .date)
                    .labelsHidden()
            }
            .frame(maxWidth: .infinity, alignment: .leading)

            EditableField(label: "Category", text: $editedCategory)

            VStack(alignment: .leading, spacing: 8) {
                Text("Notes")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                TextEditor(text: $editedNotes)
                    .frame(minHeight: 80)
                    .padding(8)
                    .background(Color.tallyBackground)
                    .cornerRadius(8)
            }
        }
    }

    // MARK: - Confidence Card

    private func confidenceCard(_ confidence: Double) -> some View {
        HStack {
            Image(systemName: "checkmark.seal.fill")
                .foregroundColor(confidenceColor(confidence))
                .accessibilityHidden(true)

            VStack(alignment: .leading) {
                Text("OCR Confidence")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                Text("\(Int(confidence * 100))%")
                    .font(.headline)
                    .foregroundColor(.white)
            }

            Spacer()

            ProgressView(value: confidence)
                .progressViewStyle(.linear)
                .tint(confidenceColor(confidence))
                .frame(width: 100)
                .accessibilityHidden(true)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("OCR confidence: \(Int(confidence * 100)) percent, \(confidenceDescription(confidence))")
    }

    private func confidenceDescription(_ confidence: Double) -> String {
        if confidence >= 0.9 { return "high confidence" }
        if confidence >= 0.7 { return "medium confidence" }
        return "low confidence"
    }

    private func confidenceColor(_ confidence: Double) -> Color {
        if confidence >= 0.9 { return .green }
        if confidence >= 0.7 { return .yellow }
        return .orange
    }

    // MARK: - Actions Card

    private var actionsCard: some View {
        VStack(spacing: 12) {
            if receipt.status == .unmatched {
                Button(action: {
                    // Haptic feedback: link action
                    HapticService.shared.buttonPress()
                }) {
                    Label("Match to Transaction", systemImage: "link")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.tallyAccent)
                .accessibilityLabel("Match to Transaction")
                .accessibilityHint("Link this receipt to a credit card transaction")
            }

            Button(action: {
                // Haptic feedback: destructive action warning
                HapticService.shared.warning()
                showingDeleteConfirm = true
            }) {
                Label("Delete Receipt", systemImage: "trash")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .tint(.red)
            .accessibilityLabel("Delete Receipt")
            .accessibilityHint("Permanently delete this receipt. This action cannot be undone.")
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Actions

    private func startEditing() {
        editedMerchant = receipt.merchant ?? ""
        editedAmount = receipt.amount.map { String($0) } ?? ""
        editedDate = receipt.date ?? Date()
        editedCategory = receipt.category ?? ""
        editedNotes = receipt.notes ?? ""
        isEditing = true
    }

    private func saveChanges() {
        isSaving = true

        Task {
            do {
                var updates: [String: Any] = [:]
                if editedMerchant != receipt.merchant { updates["merchant"] = editedMerchant }
                if let amount = Double(editedAmount), amount != receipt.amount { updates["amount"] = amount }
                if editedCategory != receipt.category { updates["category"] = editedCategory }
                if editedNotes != receipt.notes { updates["notes"] = editedNotes }

                if !updates.isEmpty {
                    _ = try await APIClient.shared.updateReceipt(id: receipt.id, updates: updates)
                }

                await MainActor.run {
                    isEditing = false
                    isSaving = false
                    // Haptic feedback: save successful
                    HapticService.shared.saveSuccess()
                }
            } catch {
                await MainActor.run {
                    isSaving = false
                    // Haptic feedback: save failed
                    HapticService.shared.error()
                }
            }
        }
    }

    private func deleteReceipt() {
        // Haptic feedback: destructive action
        HapticService.shared.warning()

        Task {
            do {
                try await APIClient.shared.deleteReceipt(id: receipt.id)
                await MainActor.run {
                    // Haptic feedback: delete successful
                    HapticService.shared.success()
                    dismiss()
                }
            } catch {
                print("Delete failed: \(error)")
                await MainActor.run {
                    // Haptic feedback: delete failed
                    HapticService.shared.error()
                }
            }
        }
    }

    private func businessDisplayName(_ business: String) -> String {
        switch business.lowercased() {
        case "personal": return "Personal"
        case "business": return "Business"
        case "sec": return "MCR"
        default: return business
        }
    }
}

// MARK: - Receipt Detail Row

private struct ReceiptDetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .font(.subheadline)
                .foregroundColor(.gray)
            Spacer()
            Text(value)
                .foregroundColor(.white)
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("\(label): \(value)")
    }
}

// MARK: - Editable Field

struct EditableField: View {
    let label: String
    @Binding var text: String
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(label)
                .font(.subheadline)
                .foregroundColor(.gray)
            TextField(label, text: $text)
                .keyboardType(keyboardType)
                .padding()
                .background(Color.tallyBackground)
                .cornerRadius(8)
                .accessibilityLabel(label)
                .accessibilityValue(text.isEmpty ? "Empty" : text)
                .accessibilityHint("Double tap to edit \(label.lowercased())")
        }
    }
}

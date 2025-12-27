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
                            saveChanges()
                        } else {
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
                    .cornerRadius(12)
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
            case .empty:
                ProgressView()
                    .frame(height: 200)
                    .frame(maxWidth: .infinity)
                    .background(Color.tallyCard)
                    .cornerRadius(12)
            @unknown default:
                EmptyView()
            }
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
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
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
                Button(action: {}) {
                    Label("Match to Transaction", systemImage: "link")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.borderedProminent)
                .tint(.tallyAccent)
            }

            Button(action: { showingDeleteConfirm = true }) {
                Label("Delete Receipt", systemImage: "trash")
                    .frame(maxWidth: .infinity)
            }
            .buttonStyle(.bordered)
            .tint(.red)
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
                }
            } catch {
                await MainActor.run {
                    isSaving = false
                }
            }
        }
    }

    private func deleteReceipt() {
        Task {
            do {
                try await APIClient.shared.deleteReceipt(id: receipt.id)
                await MainActor.run {
                    dismiss()
                }
            } catch {
                print("Delete failed: \(error)")
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
        }
    }
}

import SwiftUI

/// View for manually adding transactions that aren't from Plaid
/// Supports cash purchases, other cards, and custom entries
struct ManualTransactionView: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var businessTypeService = BusinessTypeService.shared

    // Form fields
    @State private var merchant = ""
    @State private var amount = ""
    @State private var date = Date()
    @State private var category = ""
    @State private var selectedBusinessType: APIClient.BusinessType?
    @State private var notes = ""
    @State private var source: TransactionSource = .cash

    // UI State
    @State private var isSubmitting = false
    @State private var showingError = false
    @State private var errorMessage = ""
    @State private var showingCategoryPicker = false
    @State private var showingSourcePicker = false

    // Callback
    var onSave: ((ManualTransaction) -> Void)?

    enum TransactionSource: String, CaseIterable {
        case cash = "Cash"
        case debit = "Debit Card"
        case credit = "Credit Card"
        case venmo = "Venmo"
        case zelle = "Zelle"
        case paypal = "PayPal"
        case applePay = "Apple Pay"
        case other = "Other"

        var icon: String {
            switch self {
            case .cash: return "dollarsign.circle"
            case .debit: return "creditcard"
            case .credit: return "creditcard.fill"
            case .venmo: return "v.circle"
            case .zelle: return "z.circle"
            case .paypal: return "p.circle"
            case .applePay: return "apple.logo"
            case .other: return "ellipsis.circle"
            }
        }
    }

    struct ManualTransaction {
        let merchant: String
        let amount: Double
        let date: Date
        let category: String?
        let businessType: String?
        let notes: String?
        let source: String
    }

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Header
                    headerSection

                    // Main Form
                    VStack(spacing: 16) {
                        // Merchant
                        FormField(title: "Merchant", icon: "storefront") {
                            TextField("Where did you spend?", text: $merchant)
                                .textFieldStyle(.plain)
                                .foregroundColor(.white)
                        }

                        // Amount
                        FormField(title: "Amount", icon: "dollarsign.circle") {
                            HStack {
                                Text("$")
                                    .foregroundColor(.gray)
                                TextField("0.00", text: $amount)
                                    .keyboardType(.decimalPad)
                                    .textFieldStyle(.plain)
                                    .foregroundColor(.white)
                            }
                        }

                        // Date
                        FormField(title: "Date", icon: "calendar") {
                            DatePicker("", selection: $date, displayedComponents: .date)
                                .labelsHidden()
                                .colorScheme(.dark)
                        }

                        // Source
                        FormField(title: "Payment Method", icon: source.icon) {
                            Button(action: { showingSourcePicker = true }) {
                                HStack {
                                    Text(source.rawValue)
                                        .foregroundColor(.white)
                                    Spacer()
                                    Image(systemName: "chevron.down")
                                        .font(.caption)
                                        .foregroundColor(.gray)
                                }
                            }
                        }

                        // Business Type
                        FormField(title: "Business Type", icon: "briefcase") {
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 8) {
                                    ForEach(businessTypeService.businessTypes) { type in
                                        Button(action: {
                                            HapticService.shared.impact(.light)
                                            selectedBusinessType = type
                                        }) {
                                            HStack(spacing: 4) {
                                                Image(systemName: type.icon)
                                                    .font(.caption)
                                                Text(type.displayName)
                                                    .font(.caption)
                                            }
                                            .padding(.horizontal, 10)
                                            .padding(.vertical, 6)
                                            .background(
                                                selectedBusinessType?.id == type.id ?
                                                type.swiftUIColor : Color.tallyCard.opacity(0.5)
                                            )
                                            .foregroundColor(selectedBusinessType?.id == type.id ? .white : .gray)
                                            .cornerRadius(12)
                                        }
                                    }
                                }
                            }
                        }

                        // Category
                        FormField(title: "Category", icon: "tag") {
                            Button(action: { showingCategoryPicker = true }) {
                                HStack {
                                    Text(category.isEmpty ? "Select category" : category)
                                        .foregroundColor(category.isEmpty ? .gray : .white)
                                    Spacer()
                                    Image(systemName: "chevron.down")
                                        .font(.caption)
                                        .foregroundColor(.gray)
                                }
                            }
                        }

                        // Notes
                        FormField(title: "Notes", icon: "note.text") {
                            TextField("Add details or memo", text: $notes)
                                .textFieldStyle(.plain)
                                .foregroundColor(.white)
                        }
                    }

                    // Submit Button
                    Button(action: submit) {
                        HStack {
                            if isSubmitting {
                                ProgressView()
                                    .tint(.black)
                            } else {
                                Image(systemName: "plus.circle.fill")
                                Text("Add Transaction")
                            }
                        }
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(isFormValid ? Color.tallyAccent : Color.gray)
                        .cornerRadius(12)
                    }
                    .disabled(!isFormValid || isSubmitting)
                    .padding(.top)
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Add Transaction")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .sheet(isPresented: $showingCategoryPicker) {
                CategoryPickerView(selectedCategory: $category)
            }
            .sheet(isPresented: $showingSourcePicker) {
                SourcePickerView(selectedSource: $source)
            }
            .alert("Error", isPresented: $showingError) {
                Button("OK") { }
            } message: {
                Text(errorMessage)
            }
            .task {
                await businessTypeService.loadIfNeeded()
                // Set default business type
                if selectedBusinessType == nil {
                    selectedBusinessType = businessTypeService.businessTypes.first(where: { $0.isDefault })
                        ?? businessTypeService.businessTypes.first
                }
            }
        }
    }

    private var headerSection: some View {
        VStack(spacing: 8) {
            Image(systemName: "plus.circle.fill")
                .font(.system(size: 40))
                .foregroundColor(.tallyAccent)

            Text("Manual Entry")
                .font(.headline)
                .foregroundColor(.white)

            Text("Add cash or non-Plaid transactions")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding()
    }

    private var isFormValid: Bool {
        !merchant.isEmpty && !amount.isEmpty && Double(amount) != nil
    }

    private func submit() {
        guard let amountValue = Double(amount) else {
            errorMessage = "Please enter a valid amount"
            showingError = true
            return
        }

        isSubmitting = true
        HapticService.shared.impact(.medium)

        let transaction = ManualTransaction(
            merchant: merchant,
            amount: amountValue,
            date: date,
            category: category.isEmpty ? nil : category,
            businessType: selectedBusinessType?.name,
            notes: notes.isEmpty ? nil : notes,
            source: source.rawValue
        )

        // Submit to API
        Task {
            do {
                try await submitTransaction(transaction)
                HapticService.shared.notification(.success)
                onSave?(transaction)
                dismiss()
            } catch {
                HapticService.shared.notification(.error)
                errorMessage = error.localizedDescription
                showingError = true
            }
            isSubmitting = false
        }
    }

    private func submitTransaction(_ transaction: ManualTransaction) async throws {
        // Call API to create manual transaction
        var request = URLRequest(url: URL(string: "https://tallyups.com/api/transactions/manual")!)
        request.httpMethod = "POST"
        request.setValue("application/json", forHTTPHeaderField: "Content-Type")

        let formatter = DateFormatter()
        formatter.dateFormat = "yyyy-MM-dd"

        let body: [String: Any] = [
            "merchant": transaction.merchant,
            "amount": transaction.amount,
            "date": formatter.string(from: transaction.date),
            "category": transaction.category ?? "",
            "business_type": transaction.businessType ?? "Personal",
            "notes": transaction.notes ?? "",
            "source": transaction.source
        ]

        request.httpBody = try JSONSerialization.data(withJSONObject: body)

        let (_, response) = try await URLSession.shared.data(for: request)

        guard let httpResponse = response as? HTTPURLResponse,
              (200...299).contains(httpResponse.statusCode) else {
            throw NSError(domain: "ManualTransaction", code: 1,
                         userInfo: [NSLocalizedDescriptionKey: "Failed to save transaction"])
        }
    }
}

// MARK: - Form Field Component

struct FormField<Content: View>: View {
    let title: String
    let icon: String
    let content: () -> Content

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack(spacing: 6) {
                Image(systemName: icon)
                    .font(.caption)
                    .foregroundColor(.tallyAccent)
                Text(title)
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            content()
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(12)
        }
    }
}

// MARK: - Category Picker

struct CategoryPickerView: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var selectedCategory: String

    let categories = [
        ("Food & Dining", "fork.knife"),
        ("Transportation", "car.fill"),
        ("Shopping", "bag.fill"),
        ("Entertainment", "tv.fill"),
        ("Utilities", "bolt.fill"),
        ("Travel", "airplane"),
        ("Health", "heart.fill"),
        ("Office Supplies", "pencil.and.outline"),
        ("Subscriptions", "repeat"),
        ("Personal Care", "person.fill"),
        ("Gifts", "gift.fill"),
        ("Education", "book.fill"),
        ("Other", "ellipsis")
    ]

    var body: some View {
        NavigationStack {
            List {
                ForEach(categories, id: \.0) { category in
                    Button(action: {
                        selectedCategory = category.0
                        HapticService.shared.impact(.light)
                        dismiss()
                    }) {
                        HStack {
                            Image(systemName: category.1)
                                .foregroundColor(.tallyAccent)
                                .frame(width: 24)

                            Text(category.0)
                                .foregroundColor(.white)

                            Spacer()

                            if selectedCategory == category.0 {
                                Image(systemName: "checkmark")
                                    .foregroundColor(.tallyAccent)
                            }
                        }
                    }
                    .listRowBackground(Color.tallyCard)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.tallyBackground)
            .navigationTitle("Select Category")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Source Picker

struct SourcePickerView: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var selectedSource: ManualTransactionView.TransactionSource

    var body: some View {
        NavigationStack {
            List {
                ForEach(ManualTransactionView.TransactionSource.allCases, id: \.self) { source in
                    Button(action: {
                        selectedSource = source
                        HapticService.shared.impact(.light)
                        dismiss()
                    }) {
                        HStack {
                            Image(systemName: source.icon)
                                .foregroundColor(.tallyAccent)
                                .frame(width: 24)

                            Text(source.rawValue)
                                .foregroundColor(.white)

                            Spacer()

                            if selectedSource == source {
                                Image(systemName: "checkmark")
                                    .foregroundColor(.tallyAccent)
                            }
                        }
                    }
                    .listRowBackground(Color.tallyCard)
                }
            }
            .scrollContentBackground(.hidden)
            .background(Color.tallyBackground)
            .navigationTitle("Payment Method")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

// MARK: - Preview

#Preview {
    ManualTransactionView()
}

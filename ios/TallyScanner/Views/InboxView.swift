import SwiftUI

struct InboxView: View {
    @State private var receipts: [IncomingReceipt] = []
    @State private var isLoading = false
    @State private var isRefreshing = false
    @State private var stats: InboxStats?
    @State private var selectedTab = "pending"
    @State private var selectedReceipt: IncomingReceipt?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Stats Header
                    if let stats = stats {
                        statsHeader(stats)
                    }

                    // Tab Picker
                    tabPicker

                    // Receipt List
                    if isLoading && receipts.isEmpty {
                        loadingView
                    } else if receipts.isEmpty {
                        emptyView
                    } else {
                        receiptList
                    }
                }
            }
            .navigationTitle("Email Inbox")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: triggerScan) {
                        if isRefreshing {
                            ProgressView()
                        } else {
                            Image(systemName: "envelope.arrow.triangle.branch")
                        }
                    }
                    .disabled(isRefreshing)
                }
            }
            .refreshable {
                await loadReceipts()
            }
            .sheet(item: $selectedReceipt) { receipt in
                IncomingReceiptDetailView(receipt: receipt) {
                    await loadReceipts()
                }
            }
            .task {
                await loadReceipts()
                await loadStats()
            }
        }
    }

    // MARK: - Stats Header

    private func statsHeader(_ stats: InboxStats) -> some View {
        HStack(spacing: 20) {
            VStack {
                Text("\(stats.pending)")
                    .font(.title2.bold())
                    .foregroundColor(.orange)
                Text("Pending")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Divider()
                .frame(height: 40)

            VStack {
                Text("\(stats.accepted)")
                    .font(.title2.bold())
                    .foregroundColor(.green)
                Text("Accepted")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Divider()
                .frame(height: 40)

            VStack {
                Text("\(stats.rejected)")
                    .font(.title2.bold())
                    .foregroundColor(.red)
                Text("Rejected")
                    .font(.caption)
                    .foregroundColor(.gray)
            }
        }
        .padding()
        .background(Color.tallyCard)
    }

    // MARK: - Tab Picker

    private var tabPicker: some View {
        Picker("Status", selection: $selectedTab) {
            Text("Pending").tag("pending")
            Text("Accepted").tag("accepted")
            Text("Rejected").tag("rejected")
        }
        .pickerStyle(.segmented)
        .padding()
        .onChange(of: selectedTab) { oldValue, newValue in
            Task {
                await loadReceipts()
            }
        }
    }

    // MARK: - Receipt List

    private var receiptList: some View {
        List {
            ForEach(receipts) { receipt in
                IncomingReceiptCard(receipt: receipt)
                    .listRowBackground(Color.tallyBackground)
                    .listRowInsets(EdgeInsets(top: 6, leading: 16, bottom: 6, trailing: 16))
                    .listRowSeparator(.hidden)
                    .onTapGesture {
                        selectedReceipt = receipt
                    }
                    .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                        // Reject (red)
                        Button(role: .destructive) {
                            rejectReceipt(receipt)
                        } label: {
                            Label("Reject", systemImage: "xmark.circle.fill")
                        }

                        // Not a Receipt (spam)
                        Button {
                            markAsSpam(receipt)
                        } label: {
                            Label("Not Receipt", systemImage: "trash.fill")
                        }
                        .tint(.orange)
                    }
                    .swipeActions(edge: .leading, allowsFullSwipe: true) {
                        // Quick Accept (Personal)
                        Button {
                            quickAccept(receipt, business: "Personal")
                        } label: {
                            Label("Personal", systemImage: "person.fill")
                        }
                        .tint(.green)

                        // Business
                        Button {
                            quickAccept(receipt, business: "Business")
                        } label: {
                            Label("Business", systemImage: "house.fill")
                        }
                        .tint(.blue)

                        // Secondary
                        Button {
                            quickAccept(receipt, business: "Secondary")
                        } label: {
                            Label("MCR", systemImage: "music.note")
                        }
                        .tint(.purple)
                    }
            }
        }
        .listStyle(.plain)
        .scrollContentBackground(.hidden)
        .background(Color.tallyBackground)
    }

    // MARK: - Swipe Actions

    private func rejectReceipt(_ receipt: IncomingReceipt) {
        HapticService.shared.swipeComplete()

        Task {
            do {
                try await APIClient.shared.rejectReceipt(id: receipt.id)
                await loadReceipts()
                await loadStats()

                HapticService.shared.success()
            } catch {
                print("Reject failed: \(error)")
                HapticService.shared.error()
            }
        }
    }

    private func markAsSpam(_ receipt: IncomingReceipt) {
        HapticService.shared.swipeComplete()

        Task {
            do {
                try await APIClient.shared.rejectReceipt(id: receipt.id)
                await loadReceipts()
                await loadStats()
                HapticService.shared.success()
            } catch {
                print("Mark as spam failed: \(error)")
                HapticService.shared.error()
            }
        }
    }

    private func quickAccept(_ receipt: IncomingReceipt, business: String) {
        HapticService.shared.swipeComplete()

        Task {
            do {
                try await APIClient.shared.acceptReceipt(
                    id: receipt.id,
                    merchant: receipt.merchant,
                    amount: receipt.amount,
                    date: nil,
                    business: business
                )
                await loadReceipts()
                await loadStats()

                // Success celebration!
                HapticService.shared.matchSuccess()

                // Notify of successful match
                NotificationService.shared.notifyReceiptMatched(
                    merchant: receipt.merchant ?? "Receipt",
                    amount: receipt.amount.map { String(format: "$%.2f", $0) } ?? "",
                    transactionDate: business
                )
            } catch {
                print("Quick accept failed: \(error)")
                HapticService.shared.error()
            }
        }
    }

    // MARK: - Empty & Loading Views

    private var loadingView: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.5)
            Text("Loading inbox...")
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyView: some View {
        VStack(spacing: 16) {
            Image(systemName: "envelope.open")
                .font(.system(size: 44))
                .foregroundColor(.gray.opacity(0.6))
            Text("No \(selectedTab) receipts")
                .font(.headline)
                .foregroundColor(.white)
            Text("Tap the scan button to check for new emails")
                .font(.subheadline)
                .foregroundColor(.gray)
                .multilineTextAlignment(.center)
        }
        .frame(maxHeight: .infinity)
        .padding()
    }

    // MARK: - Actions

    private func loadReceipts() async {
        isLoading = true
        defer { isLoading = false }

        do {
            receipts = try await APIClient.shared.fetchIncomingReceipts(status: selectedTab)
        } catch {
            print("Failed to load receipts: \(error)")
        }
    }

    private func loadStats() async {
        do {
            stats = try await APIClient.shared.fetchInboxStats()
        } catch {
            print("Failed to load stats: \(error)")
        }
    }

    private func triggerScan() {
        isRefreshing = true

        Task {
            do {
                try await APIClient.shared.triggerGmailScan()
                await loadReceipts()
                await loadStats()
            } catch {
                print("Scan failed: \(error)")
            }
            isRefreshing = false
        }
    }
}

// MARK: - Incoming Receipt Card

struct IncomingReceiptCard: View {
    let receipt: IncomingReceipt

    var body: some View {
        HStack(spacing: 12) {
            // Thumbnail
            AsyncImage(url: URL(string: receipt.thumbnailURL ?? receipt.imageURL ?? "")) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFill()
                case .failure, .empty:
                    Image(systemName: "envelope.fill")
                        .font(.title)
                        .foregroundColor(.gray)
                @unknown default:
                    EmptyView()
                }
            }
            .frame(width: 60, height: 60)
            .background(Color.tallyBackground)
            .cornerRadius(8)
            .clipped()

            // Details
            VStack(alignment: .leading, spacing: 4) {
                Text(receipt.merchant ?? receipt.sender ?? "Unknown")
                    .font(.headline)
                    .foregroundColor(.white)
                    .lineLimit(1)

                if let subject = receipt.subject {
                    Text(subject)
                        .font(.caption)
                        .foregroundColor(.gray)
                        .lineLimit(1)
                }

                HStack {
                    if let amount = receipt.amount {
                        Text(formatCurrency(amount))
                            .font(.subheadline)
                            .foregroundColor(.tallyAccent)
                    }

                    if let email = receipt.emailAccount {
                        Text(email)
                            .font(.caption2)
                            .foregroundColor(.gray)
                    }
                }
            }

            Spacer()

            Image(systemName: "chevron.right")
                .foregroundColor(.gray)
                .font(.caption)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    private func formatCurrency(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }
}

// MARK: - Incoming Receipt Detail View

struct IncomingReceiptDetailView: View {
    let receipt: IncomingReceipt
    let onAction: () async -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var merchant: String = ""
    @State private var amount: String = ""
    @State private var date = Date()
    @State private var business = "Personal"
    @State private var category = ""
    @State private var notes = ""
    @State private var isProcessing = false

    let businesses = ["Personal", "Business", "Secondary", "Em.co"]
    let categories = ["Food & Dining", "Transportation", "Shopping", "Entertainment", "Travel", "Business", "Subscription", "Utilities", "Other"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Confidence Banner
                    if let confidence = receipt.confidenceScore {
                        confidenceBanner(confidence)
                    }

                    // Image
                    AsyncImage(url: URL(string: receipt.imageURL ?? "")) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .scaledToFit()
                                .cornerRadius(12)
                        case .failure, .empty:
                            Rectangle()
                                .fill(Color.tallyCard)
                                .frame(height: 200)
                                .overlay {
                                    Image(systemName: "photo")
                                        .font(.largeTitle)
                                        .foregroundColor(.gray)
                                }
                                .cornerRadius(12)
                        @unknown default:
                            EmptyView()
                        }
                    }

                    // AI Notes
                    if let aiNotes = receipt.aiNotes, !aiNotes.isEmpty {
                        HStack(spacing: 8) {
                            Image(systemName: "sparkles")
                                .foregroundColor(.purple)
                            Text(aiNotes)
                                .font(.subheadline)
                                .foregroundColor(.white)
                        }
                        .padding()
                        .frame(maxWidth: .infinity, alignment: .leading)
                        .background(Color.purple.opacity(0.2))
                        .cornerRadius(12)
                    }

                    // Email Info
                    VStack(alignment: .leading, spacing: 12) {
                        if let sender = receipt.sender {
                            DetailRow(label: "From", value: sender)
                        }
                        if let subject = receipt.subject {
                            DetailRow(label: "Subject", value: subject)
                        }
                        if let email = receipt.emailAccount {
                            DetailRow(label: "Account", value: email)
                        }
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)

                    // Extracted Data
                    VStack(spacing: 16) {
                        Text("Receipt Details")
                            .font(.headline)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        InboxFormField(title: "Merchant", text: $merchant, placeholder: "Store name")
                        InboxFormField(title: "Amount", text: $amount, placeholder: "0.00", keyboardType: .decimalPad)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Date")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                            DatePicker("", selection: $date, displayedComponents: .date)
                                .labelsHidden()
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)

                    // Categorization Section
                    VStack(spacing: 16) {
                        Text("Categorization")
                            .font(.headline)
                            .frame(maxWidth: .infinity, alignment: .leading)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Business")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                            Picker("Business", selection: $business) {
                                ForEach(businesses, id: \.self) { b in
                                    Text(b).tag(b)
                                }
                            }
                            .pickerStyle(.menu)
                            .tint(.tallyAccent)
                        }
                        .frame(maxWidth: .infinity, alignment: .leading)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Category")
                                .font(.subheadline)
                                .foregroundColor(.gray)

                            // Quick category buttons
                            ScrollView(.horizontal, showsIndicators: false) {
                                HStack(spacing: 8) {
                                    ForEach(categories, id: \.self) { cat in
                                        Button(action: { category = cat }) {
                                            Text(cat)
                                                .font(.caption)
                                                .padding(.horizontal, 12)
                                                .padding(.vertical, 6)
                                                .background(category == cat ? Color.tallyAccent : Color.tallyBackground)
                                                .foregroundColor(category == cat ? .white : .gray)
                                                .cornerRadius(15)
                                        }
                                    }
                                }
                            }
                        }

                        InboxFormField(title: "Notes", text: $notes, placeholder: "Optional notes")
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)

                    // Quick Actions
                    quickActionsSection

                    // Actions
                    HStack(spacing: 16) {
                        Button(action: reject) {
                            Label("Reject", systemImage: "xmark")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.bordered)
                        .tint(.red)

                        Button(action: accept) {
                            Label("Accept", systemImage: "checkmark")
                                .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .tint(.tallyAccent)
                    }
                    .disabled(isProcessing)
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Review Receipt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Close") {
                        dismiss()
                    }
                }
            }
            .onAppear {
                setupInitialValues()
            }
        }
    }

    private func confidenceBanner(_ confidence: Double) -> some View {
        HStack {
            Image(systemName: confidence >= 0.8 ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                .foregroundColor(confidenceColor(confidence))
            Text(confidenceText(confidence))
                .font(.subheadline)
            Spacer()
            Text("\(Int(confidence * 100))%")
                .font(.caption.bold())
                .foregroundColor(confidenceColor(confidence))
        }
        .padding()
        .background(confidenceColor(confidence).opacity(0.15))
        .cornerRadius(12)
    }

    private func confidenceColor(_ confidence: Double) -> Color {
        if confidence >= 0.8 { return .green }
        if confidence >= 0.5 { return .orange }
        return .red
    }

    private func confidenceText(_ confidence: Double) -> String {
        if confidence >= 0.8 { return "High confidence - likely a valid receipt" }
        if confidence >= 0.5 { return "Medium confidence - review recommended" }
        return "Low confidence - may not be a receipt"
    }

    private var quickActionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Quick Actions")
                .font(.headline)

            HStack(spacing: 12) {
                // Auto-categorize based on merchant
                Button(action: autoCategorize) {
                    VStack(spacing: 4) {
                        Image(systemName: "wand.and.stars")
                            .font(.title3)
                        Text("Auto")
                            .font(.caption2)
                    }
                    .foregroundColor(.purple)
                    .frame(width: 60, height: 60)
                    .background(Color.purple.opacity(0.2))
                    .cornerRadius(12)
                }

                // Mark as subscription
                Button(action: { category = "Subscription" }) {
                    VStack(spacing: 4) {
                        Image(systemName: "repeat.circle")
                            .font(.title3)
                        Text("Sub")
                            .font(.caption2)
                    }
                    .foregroundColor(.blue)
                    .frame(width: 60, height: 60)
                    .background(Color.blue.opacity(0.2))
                    .cornerRadius(12)
                }

                // Mark as spam
                Button(action: markAsSpam) {
                    VStack(spacing: 4) {
                        Image(systemName: "trash")
                            .font(.title3)
                        Text("Spam")
                            .font(.caption2)
                    }
                    .foregroundColor(.red)
                    .frame(width: 60, height: 60)
                    .background(Color.red.opacity(0.2))
                    .cornerRadius(12)
                }

                // Flag for review
                Button(action: flagForReview) {
                    VStack(spacing: 4) {
                        Image(systemName: "flag")
                            .font(.title3)
                        Text("Flag")
                            .font(.caption2)
                    }
                    .foregroundColor(.orange)
                    .frame(width: 60, height: 60)
                    .background(Color.orange.opacity(0.2))
                    .cornerRadius(12)
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    private func setupInitialValues() {
        merchant = receipt.merchant ?? receipt.extractedData?.merchant ?? ""
        if let amt = receipt.amount ?? receipt.extractedData?.amount {
            amount = String(format: "%.2f", amt)
        }
        if let bizType = receipt.businessType {
            business = bizType
        }
        if let cat = receipt.category {
            category = cat
        }
        if let notes = receipt.aiNotes {
            self.notes = notes
        }
    }

    private func autoCategorize() {
        // Auto-detect category based on merchant name
        let merchantLower = merchant.lowercased()

        if merchantLower.contains("uber") || merchantLower.contains("lyft") || merchantLower.contains("gas") || merchantLower.contains("fuel") {
            category = "Transportation"
        } else if merchantLower.contains("restaurant") || merchantLower.contains("cafe") || merchantLower.contains("coffee") ||
                    merchantLower.contains("starbucks") || merchantLower.contains("chipotle") || merchantLower.contains("mcdonald") {
            category = "Food & Dining"
        } else if merchantLower.contains("amazon") || merchantLower.contains("target") || merchantLower.contains("walmart") {
            category = "Shopping"
        } else if merchantLower.contains("netflix") || merchantLower.contains("spotify") || merchantLower.contains("apple") ||
                    merchantLower.contains("subscription") {
            category = "Subscription"
        } else if merchantLower.contains("hotel") || merchantLower.contains("airbnb") || merchantLower.contains("airline") ||
                    merchantLower.contains("flight") {
            category = "Travel"
        }
    }

    private func markAsSpam() {
        // Reject as spam
        reject()
    }

    private func flagForReview() {
        notes = "[FLAGGED FOR REVIEW] " + notes
    }

    private func accept() {
        isProcessing = true

        Task {
            do {
                try await APIClient.shared.acceptReceipt(
                    id: receipt.id,
                    merchant: merchant.isEmpty ? nil : merchant,
                    amount: Double(amount),
                    date: date
                )
                await onAction()
                dismiss()
            } catch {
                print("Accept failed: \(error)")
            }
            isProcessing = false
        }
    }

    private func reject() {
        isProcessing = true

        Task {
            do {
                try await APIClient.shared.rejectReceipt(id: receipt.id)
                await onAction()
                dismiss()
            } catch {
                print("Reject failed: \(error)")
            }
            isProcessing = false
        }
    }
}

// MARK: - Inbox Form Field

private struct InboxFormField: View {
    let title: String
    @Binding var text: String
    var placeholder: String = ""
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline)
                .foregroundColor(.gray)
            TextField(placeholder, text: $text)
                .keyboardType(keyboardType)
                .padding()
                .background(Color.tallyBackground)
                .cornerRadius(8)
        }
    }
}

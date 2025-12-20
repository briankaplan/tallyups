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
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(receipts) { receipt in
                    IncomingReceiptCard(receipt: receipt)
                        .onTapGesture {
                            selectedReceipt = receipt
                        }
                }
            }
            .padding()
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
                .font(.system(size: 60))
                .foregroundColor(.gray)
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
    @State private var isProcessing = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
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

                        FormField(title: "Merchant", text: $merchant, placeholder: "Store name")
                        FormField(title: "Amount", text: $amount, placeholder: "0.00", keyboardType: .decimalPad)

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
                merchant = receipt.merchant ?? receipt.extractedData?.merchant ?? ""
                if let amt = receipt.amount ?? receipt.extractedData?.amount {
                    amount = String(format: "%.2f", amt)
                }
            }
        }
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

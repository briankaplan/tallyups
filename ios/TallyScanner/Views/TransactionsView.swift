import SwiftUI

struct TransactionsView: View {
    @StateObject private var viewModel = TransactionsViewModel()
    @State private var searchText = ""
    @State private var selectedTransaction: Transaction?
    @State private var showingFilters = false
    @State private var selectedBusinessFilter = "all"

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Stats Bar
                    statsBar

                    // Business Filter
                    businessFilterBar

                    // Search
                    searchBar

                    // Transaction List
                    if viewModel.isLoading {
                        loadingView
                    } else if viewModel.transactions.isEmpty && viewModel.hasLoaded {
                        emptyView
                            .transition(.opacity.animation(.easeIn(duration: 0.3)))
                    } else {
                        transactionList
                    }
                }
            }
            .navigationTitle("Transactions")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { Task { await viewModel.refresh() } }) {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable {
                await viewModel.refresh()
            }
            .sheet(item: $selectedTransaction) { transaction in
                TransactionDetailView(transaction: transaction, viewModel: viewModel)
            }
            .task {
                await viewModel.loadTransactions()
            }
            .onChange(of: searchText) { _, newValue in
                viewModel.searchQuery = newValue
            }
            .onChange(of: selectedBusinessFilter) { _, newValue in
                viewModel.businessFilter = newValue == "all" ? nil : newValue
                Task { await viewModel.refresh() }
            }
        }
    }

    // MARK: - Stats Bar

    private var statsBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 16) {
                StatPill(
                    title: "Total",
                    value: "\(viewModel.stats.total)",
                    color: .tallyAccent
                )
                StatPill(
                    title: "With Receipt",
                    value: "\(viewModel.stats.withReceipt)",
                    color: .green
                )
                StatPill(
                    title: "Missing",
                    value: "\(viewModel.stats.missing)",
                    color: .orange
                )
                StatPill(
                    title: "This Month",
                    value: formatCurrency(viewModel.stats.totalAmount),
                    color: .blue
                )
            }
            .padding(.horizontal)
            .padding(.vertical, 12)
        }
        .background(Color.tallyCard)
    }

    // MARK: - Business Filter Bar

    private var businessFilterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                ForEach(["all", "Personal", "Down Home", "Music City Rodeo", "Em.co"], id: \.self) { business in
                    Button(action: { selectedBusinessFilter = business }) {
                        Text(business == "all" ? "All" : shortBusinessName(business))
                            .font(.subheadline)
                            .foregroundColor(selectedBusinessFilter == business ? .white : .gray)
                            .padding(.horizontal, 12)
                            .padding(.vertical, 6)
                            .background(
                                selectedBusinessFilter == business ?
                                    businessColor(business) : Color.tallyCard
                            )
                            .cornerRadius(16)
                    }
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
        }
    }

    // MARK: - Search Bar

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass")
                .foregroundColor(.gray)
            TextField("Search transactions...", text: $searchText)
                .textFieldStyle(.plain)
            if !searchText.isEmpty {
                Button(action: { searchText = "" }) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.gray)
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    // MARK: - Transaction List

    private var transactionList: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(viewModel.filteredTransactions) { transaction in
                    TransactionCardView(transaction: transaction)
                        .onTapGesture {
                            selectedTransaction = transaction
                        }
                }

                // Load More
                if viewModel.hasMore {
                    ProgressView()
                        .padding()
                        .onAppear {
                            Task {
                                await viewModel.loadMore()
                            }
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
            Text("Loading transactions...")
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyView: some View {
        VStack(spacing: 16) {
            Image(systemName: "creditcard")
                .font(.system(size: 44))
                .foregroundColor(.gray.opacity(0.6))
            Text("No transactions found")
                .font(.headline)
                .foregroundColor(.white)
            Text("Card charges will appear here")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    private func formatCurrency(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: value)) ?? "$\(value)"
    }

    private func shortBusinessName(_ business: String) -> String {
        switch business {
        case "Music City Rodeo": return "MCR"
        case "Down Home": return "Down Home"
        default: return business
        }
    }

    private func businessColor(_ business: String) -> Color {
        switch business.lowercased() {
        case "down home", "downhome": return .orange
        case "mcr", "music city rodeo": return .purple
        case "em.co", "emco": return .teal
        case "personal": return .blue
        default: return .tallyAccent
        }
    }
}

// MARK: - Transaction Card View

struct TransactionCardView: View {
    let transaction: Transaction

    var body: some View {
        HStack(spacing: 12) {
            // Status indicator
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.2))
                    .frame(width: 44, height: 44)

                Image(systemName: transaction.hasReceipt ? "checkmark.circle.fill" : "doc.text")
                    .font(.title3)
                    .foregroundColor(statusColor)
            }

            // Details
            VStack(alignment: .leading, spacing: 4) {
                HStack {
                    Text(transaction.merchant)
                        .font(.headline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Spacer()

                    Text(transaction.formattedAmount)
                        .font(.headline)
                        .foregroundColor(transaction.hasReceipt ? .green : .white)
                }

                HStack {
                    Text(transaction.formattedDate)
                        .font(.subheadline)
                        .foregroundColor(.gray)

                    Spacer()

                    if let business = transaction.business, !business.isEmpty {
                        Text(shortBusinessName(business))
                            .font(.caption2)
                            .foregroundColor(.white)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 2)
                            .background(businessColor(business))
                            .cornerRadius(4)
                    }
                }

                // Receipt count / status
                HStack {
                    if transaction.hasReceipt {
                        HStack(spacing: 4) {
                            Image(systemName: "doc.fill")
                                .font(.caption)
                            Text("\(transaction.receiptCount) receipt\(transaction.receiptCount == 1 ? "" : "s")")
                                .font(.caption)
                        }
                        .foregroundColor(.green)
                    } else {
                        HStack(spacing: 4) {
                            Image(systemName: "exclamationmark.triangle.fill")
                                .font(.caption)
                            Text("Missing receipt")
                                .font(.caption)
                        }
                        .foregroundColor(.orange)
                    }

                    if let notes = transaction.notes, !notes.isEmpty {
                        Text(notes)
                            .font(.caption)
                            .foregroundColor(.gray)
                            .lineLimit(1)
                    }
                }
            }

            Image(systemName: "chevron.right")
                .foregroundColor(.gray)
                .font(.caption)
        }
        .padding()
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.tallyCard)
                .overlay(
                    // Left border indicator
                    transaction.hasReceipt ?
                    RoundedRectangle(cornerRadius: 12)
                        .strokeBorder(Color.green.opacity(0.5), lineWidth: 2)
                    : nil
                )
        )
    }

    private var statusColor: Color {
        if transaction.hasReceipt {
            return .green
        }
        switch transaction.status {
        case .pending: return .yellow
        case .matched: return .green
        case .unmatched: return .orange
        case .excluded: return .gray
        }
    }

    private func shortBusinessName(_ business: String) -> String {
        switch business {
        case "Music City Rodeo": return "MCR"
        default: return business
        }
    }

    private func businessColor(_ business: String) -> Color {
        switch business.lowercased() {
        case "down home", "downhome": return .orange
        case "mcr", "music city rodeo": return .purple
        case "em.co", "emco": return .teal
        case "personal": return .blue
        default: return .gray
        }
    }
}

// MARK: - Transaction Detail View

struct TransactionDetailView: View {
    let transaction: Transaction
    @ObservedObject var viewModel: TransactionsViewModel
    @Environment(\.dismiss) private var dismiss
    @State private var showingReceiptPicker = false
    @State private var showingLinkedReceipts = false
    @State private var linkedReceipts: [Receipt] = []
    @State private var isLoadingReceipts = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Header
                    headerCard

                    // Receipt Section
                    receiptSection

                    // Details Section
                    detailsSection

                    // Actions
                    actionsSection
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Transaction")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showingReceiptPicker) {
                ReceiptPickerView(transaction: transaction, viewModel: viewModel)
            }
            .sheet(isPresented: $showingLinkedReceipts) {
                LinkedReceiptsView(
                    transaction: transaction,
                    receipts: linkedReceipts,
                    onUnlink: { receiptId in
                        Task {
                            await unlinkReceipt(receiptId: receiptId)
                        }
                    }
                )
            }
        }
    }

    private var headerCard: some View {
        VStack(spacing: 12) {
            Text(transaction.merchant)
                .font(.title2.bold())
                .foregroundColor(.white)

            Text(transaction.formattedAmount)
                .font(.largeTitle.bold())
                .foregroundColor(transaction.hasReceipt ? .green : .tallyAccent)

            Text(transaction.formattedDate)
                .font(.subheadline)
                .foregroundColor(.gray)

            // Status Badge
            HStack {
                Image(systemName: transaction.hasReceipt ? "checkmark.seal.fill" : "exclamationmark.triangle.fill")
                Text(transaction.hasReceipt ? "Receipt Matched" : "Missing Receipt")
            }
            .font(.subheadline.bold())
            .foregroundColor(transaction.hasReceipt ? .green : .orange)
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background((transaction.hasReceipt ? Color.green : Color.orange).opacity(0.2))
            .cornerRadius(20)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    private var receiptSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Receipt")
                .font(.headline)
                .foregroundColor(.white)

            if transaction.hasReceipt {
                Button(action: {
                    Task {
                        await loadLinkedReceipts()
                        showingLinkedReceipts = true
                    }
                }) {
                    HStack {
                        Image(systemName: "doc.fill")
                            .foregroundColor(.green)
                        Text("\(transaction.receiptCount) receipt\(transaction.receiptCount == 1 ? "" : "s") linked")
                            .foregroundColor(.white)
                        Spacer()
                        if isLoadingReceipts {
                            ProgressView()
                                .scaleEffect(0.8)
                        } else {
                            Text("View")
                                .foregroundColor(.tallyAccent)
                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                }
            } else {
                Button(action: { showingReceiptPicker = true }) {
                    HStack {
                        Image(systemName: "plus.circle.fill")
                        Text("Add Receipt")
                    }
                    .font(.headline)
                    .foregroundColor(.tallyAccent)
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .strokeBorder(Color.tallyAccent.opacity(0.5), style: StrokeStyle(lineWidth: 2, dash: [5]))
                    )
                }
            }
        }
    }

    private func loadLinkedReceipts() async {
        isLoadingReceipts = true
        defer { isLoadingReceipts = false }

        do {
            linkedReceipts = try await APIClient.shared.fetchLinkedReceipts(transactionIndex: transaction.index)
        } catch {
            print("Failed to load linked receipts: \(error)")
            linkedReceipts = []
        }
    }

    private func unlinkReceipt(receiptId: Int) async {
        let success = await viewModel.unlinkReceipt(transactionIndex: transaction.index, receiptId: receiptId)
        if success {
            linkedReceipts.removeAll { $0.id == receiptId }
            if linkedReceipts.isEmpty {
                showingLinkedReceipts = false
            }
        }
    }

    private var detailsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Details")
                .font(.headline)
                .foregroundColor(.white)

            VStack(spacing: 0) {
                DetailRow(label: "Category", value: transaction.category ?? "Uncategorized")
                Divider().background(Color.gray.opacity(0.3))
                DetailRow(label: "Business", value: transaction.business ?? "Personal")
                if let notes = transaction.notes, !notes.isEmpty {
                    Divider().background(Color.gray.opacity(0.3))
                    DetailRow(label: "Notes", value: notes)
                }
            }
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
    }

    private var actionsSection: some View {
        VStack(spacing: 12) {
            Button(action: { showingReceiptPicker = true }) {
                HStack {
                    Image(systemName: "camera.fill")
                    Text("Scan Receipt")
                }
                .font(.headline)
                .foregroundColor(.white)
                .frame(maxWidth: .infinity)
                .padding()
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }

            Button(action: {
                Task {
                    _ = await viewModel.excludeTransaction(
                        transactionIndex: transaction.index,
                        reason: "Excluded from iOS app"
                    )
                    dismiss()
                }
            }) {
                HStack {
                    Image(systemName: "xmark.circle")
                    Text("Exclude Transaction")
                }
                .font(.subheadline)
                .foregroundColor(.gray)
            }
        }
    }
}

// MARK: - Receipt Picker View

struct ReceiptPickerView: View {
    let transaction: Transaction
    @ObservedObject var viewModel: TransactionsViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var availableReceipts: [Receipt] = []
    @State private var isLoading = false
    @State private var searchText = ""
    @State private var isLinking = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 16) {
                    // Transaction info header
                    VStack(spacing: 8) {
                        Text(transaction.merchant)
                            .font(.headline)
                            .foregroundColor(.white)
                        Text(transaction.formattedAmount)
                            .font(.title2.bold())
                            .foregroundColor(.tallyAccent)
                        Text(transaction.formattedDate)
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                    .padding()
                    .frame(maxWidth: .infinity)
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                    .padding(.horizontal)

                    // Search bar
                    HStack {
                        Image(systemName: "magnifyingglass")
                            .foregroundColor(.gray)
                        TextField("Search receipts...", text: $searchText)
                            .textFieldStyle(.plain)
                            .foregroundColor(.white)
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(12)
                    .padding(.horizontal)

                    // Receipts list
                    if isLoading {
                        Spacer()
                        ProgressView()
                        Text("Loading receipts...")
                            .foregroundColor(.gray)
                        Spacer()
                    } else if filteredReceipts.isEmpty {
                        Spacer()
                        Image(systemName: "doc.text.magnifyingglass")
                            .font(.system(size: 50))
                            .foregroundColor(.gray)
                        Text("No unmatched receipts found")
                            .foregroundColor(.gray)
                        Text("Try scanning a new receipt")
                            .font(.caption)
                            .foregroundColor(.gray.opacity(0.7))
                        Spacer()
                    } else {
                        ScrollView {
                            LazyVStack(spacing: 12) {
                                ForEach(filteredReceipts) { receipt in
                                    ReceiptMatchCard(receipt: receipt) {
                                        linkReceipt(receipt)
                                    }
                                }
                            }
                            .padding(.horizontal)
                        }
                    }

                    // Scan new receipt button
                    Button(action: { dismiss() }) {
                        HStack {
                            Image(systemName: "camera.fill")
                            Text("Scan New Receipt")
                        }
                        .font(.headline)
                        .foregroundColor(.white)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent)
                        .cornerRadius(12)
                    }
                    .padding(.horizontal)
                    .padding(.bottom)
                }
            }
            .navigationTitle("Link Receipt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task {
                await loadReceipts()
            }
            .overlay {
                if isLinking {
                    ZStack {
                        Color.black.opacity(0.6)
                        VStack(spacing: 16) {
                            ProgressView()
                                .scaleEffect(1.5)
                            Text("Linking receipt...")
                                .foregroundColor(.white)
                        }
                    }
                    .ignoresSafeArea()
                }
            }
        }
    }

    private var filteredReceipts: [Receipt] {
        if searchText.isEmpty {
            return availableReceipts
        }
        return availableReceipts.filter { receipt in
            receipt.displayMerchant.localizedCaseInsensitiveContains(searchText) ||
            receipt.formattedAmount.contains(searchText)
        }
    }

    private func loadReceipts() async {
        isLoading = true
        do {
            // Load recent unmatched receipts that could match this transaction
            let receipts = try await APIClient.shared.fetchReceipts(limit: 50)
            // Filter to show unmatched receipts with similar amounts (within 20%)
            availableReceipts = receipts.filter { receipt in
                !receipt.isVerified &&
                (receipt.amount == nil || abs((receipt.amount ?? 0) - abs(transaction.amount)) < abs(transaction.amount) * 0.2)
            }
        } catch {
            print("Failed to load receipts: \(error)")
        }
        isLoading = false
    }

    private func linkReceipt(_ receipt: Receipt) {
        isLinking = true
        Task {
            let success = await viewModel.matchReceipt(
                transactionIndex: transaction.index,
                receiptId: receipt.id
            )
            isLinking = false
            if success {
                dismiss()
            }
        }
    }
}

// MARK: - Receipt Match Card

struct ReceiptMatchCard: View {
    let receipt: Receipt
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack(spacing: 12) {
                // Thumbnail
                AsyncImage(url: URL(string: receipt.thumbnailURL ?? receipt.imageURL ?? "")) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                    case .failure, .empty:
                        Image(systemName: "doc.text.fill")
                            .font(.title)
                            .foregroundColor(.gray)
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(width: 50, height: 65)
                .background(Color.tallyBackground)
                .cornerRadius(8)
                .clipped()

                // Details
                VStack(alignment: .leading, spacing: 4) {
                    Text(receipt.displayMerchant)
                        .font(.headline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    HStack {
                        Text(receipt.formattedAmount)
                            .font(.subheadline)
                            .foregroundColor(.tallyAccent)

                        Text(receipt.formattedDate)
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                }

                Spacer()

                Image(systemName: "plus.circle.fill")
                    .font(.title2)
                    .foregroundColor(.tallyAccent)
            }
            .padding()
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
    }
}

// MARK: - Linked Receipts View

struct LinkedReceiptsView: View {
    let transaction: Transaction
    let receipts: [Receipt]
    let onUnlink: (Int) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var selectedReceipt: Receipt?
    @State private var showingFullImage = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                if receipts.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "doc.text.magnifyingglass")
                            .font(.system(size: 50))
                            .foregroundColor(.gray)
                        Text("No receipts linked")
                            .foregroundColor(.gray)
                    }
                } else {
                    ScrollView {
                        LazyVStack(spacing: 16) {
                            ForEach(receipts) { receipt in
                                LinkedReceiptCard(
                                    receipt: receipt,
                                    onView: {
                                        selectedReceipt = receipt
                                        showingFullImage = true
                                    },
                                    onUnlink: {
                                        onUnlink(receipt.id)
                                    }
                                )
                            }
                        }
                        .padding()
                    }
                }
            }
            .navigationTitle("Linked Receipts")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showingFullImage) {
                if let receipt = selectedReceipt {
                    ReceiptImageViewer(receipt: receipt)
                }
            }
        }
    }
}

// MARK: - Linked Receipt Card

struct LinkedReceiptCard: View {
    let receipt: Receipt
    let onView: () -> Void
    let onUnlink: () -> Void
    @State private var showingUnlinkConfirm = false

    var body: some View {
        VStack(spacing: 0) {
            // Receipt Image
            AsyncImage(url: URL(string: receipt.imageURL ?? "")) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 300)
                case .failure, .empty:
                    ZStack {
                        Color.tallyCard
                        Image(systemName: "doc.text.fill")
                            .font(.system(size: 40))
                            .foregroundColor(.gray)
                    }
                    .frame(height: 150)
                @unknown default:
                    EmptyView()
                }
            }
            .cornerRadius(12)
            .onTapGesture { onView() }

            // Receipt Details
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(receipt.displayMerchant)
                        .font(.headline)
                        .foregroundColor(.white)
                    HStack {
                        Text(receipt.formattedAmount)
                            .font(.subheadline)
                            .foregroundColor(.tallyAccent)
                        Text(receipt.formattedDate)
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                }

                Spacer()

                Button(action: { showingUnlinkConfirm = true }) {
                    Image(systemName: "link.badge.plus")
                        .rotationEffect(.degrees(45))
                        .font(.title3)
                        .foregroundColor(.orange)
                }
            }
            .padding()
        }
        .background(Color.tallyCard)
        .cornerRadius(16)
        .confirmationDialog(
            "Unlink this receipt?",
            isPresented: $showingUnlinkConfirm,
            titleVisibility: .visible
        ) {
            Button("Unlink", role: .destructive) {
                onUnlink()
            }
            Button("Cancel", role: .cancel) {}
        }
    }
}

// MARK: - Receipt Image Viewer

struct ReceiptImageViewer: View {
    let receipt: Receipt
    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1.0

    var body: some View {
        NavigationStack {
            ZStack {
                Color.black.ignoresSafeArea()

                AsyncImage(url: URL(string: receipt.imageURL ?? "")) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFit()
                            .scaleEffect(scale)
                            .gesture(
                                MagnificationGesture()
                                    .onChanged { value in
                                        scale = value.magnitude
                                    }
                                    .onEnded { _ in
                                        withAnimation(.spring()) {
                                            scale = max(1.0, min(scale, 3.0))
                                        }
                                    }
                            )
                            .onTapGesture(count: 2) {
                                withAnimation(.spring()) {
                                    scale = scale > 1.0 ? 1.0 : 2.0
                                }
                            }
                    case .failure, .empty:
                        Image(systemName: "doc.text.fill")
                            .font(.system(size: 60))
                            .foregroundColor(.gray)
                    @unknown default:
                        EmptyView()
                    }
                }
            }
            .navigationTitle(receipt.displayMerchant)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
    }
}

#Preview {
    TransactionsView()
}

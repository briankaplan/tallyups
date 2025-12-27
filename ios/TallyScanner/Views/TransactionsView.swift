import SwiftUI

struct TransactionsView: View {
    @StateObject private var viewModel = TransactionsViewModel()
    @State private var searchText = ""
    @State private var selectedTransaction: Transaction?
    @State private var showingFilters = false
    @State private var selectedBusinessFilter = "all"
    @State private var selectedCardFilter = "all"

    // Batch selection state
    @State private var isSelectionMode = false
    @State private var selectedTransactions: Set<Int> = []
    @State private var showingBatchActions = false
    @State private var showingBatchBusinessPicker = false
    @State private var showingBatchProjectPicker = false
    @State private var showingBatchCategoryPicker = false
    @State private var isBatchProcessing = false
    @State private var batchProcessingMessage = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Selection Mode Header
                    if isSelectionMode {
                        selectionModeHeader
                    }

                    // Stats Bar
                    if !isSelectionMode {
                        statsBar
                    }

                    // Business Filter - Dynamic from user's business types
                    if !isSelectionMode {
                        businessFilterBar
                    }

                    // Card/Account Filter (only show if multiple cards)
                    if viewModel.uniqueCards.count > 1 && !isSelectionMode {
                        cardFilterBar
                    }

                    // Search
                    searchBar

                    // Transaction List
                    if viewModel.isLoading && !viewModel.hasLoaded {
                        loadingView
                    } else if viewModel.transactions.isEmpty && viewModel.hasLoaded {
                        emptyView
                            .transition(.opacity.animation(.easeIn(duration: 0.3)))
                    } else {
                        transactionList
                    }

                    // Batch Action Bar
                    if isSelectionMode && !selectedTransactions.isEmpty {
                        batchActionBar
                    }
                }

                // Processing overlay
                if isBatchProcessing {
                    batchProcessingOverlay
                }
            }
            .navigationTitle(isSelectionMode ? "Select Charges" : "Charges")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if isSelectionMode {
                        Button("Cancel") {
                            exitSelectionMode()
                        }
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    if isSelectionMode {
                        Button(selectedTransactions.count == viewModel.filteredTransactions.count ? "Deselect All" : "Select All") {
                            toggleSelectAll()
                        }
                    } else {
                        HStack(spacing: 16) {
                            Button(action: { enterSelectionMode() }) {
                                Image(systemName: "checkmark.circle")
                            }
                            Button(action: { Task { await viewModel.refresh() } }) {
                                Image(systemName: "arrow.clockwise")
                            }
                        }
                    }
                }
            }
            .refreshable {
                await viewModel.refresh()
            }
            .sheet(item: $selectedTransaction) { transaction in
                TransactionDetailView(transaction: transaction, viewModel: viewModel)
            }
            .sheet(isPresented: $showingBatchActions) {
                BatchActionsSheet(
                    selectedCount: selectedTransactions.count,
                    onAction: handleBatchAction
                )
            }
            .sheet(isPresented: $showingBatchBusinessPicker) {
                BatchBusinessPickerSheet(
                    selectedCount: selectedTransactions.count,
                    onSelect: { businessType in
                        Task {
                            await applyBatchBusinessType(businessType)
                        }
                    }
                )
            }
            .sheet(isPresented: $showingBatchProjectPicker) {
                BatchProjectPickerSheet(
                    selectedCount: selectedTransactions.count,
                    onSelect: { projectId in
                        Task {
                            await applyBatchProject(projectId)
                        }
                    }
                )
            }
            .sheet(isPresented: $showingBatchCategoryPicker) {
                BatchCategoryPickerSheet(
                    selectedCount: selectedTransactions.count,
                    onSelect: { category in
                        Task {
                            await applyBatchCategory(category)
                        }
                    }
                )
            }
            .task {
                // Load business types first, then transactions
                await viewModel.loadBusinessTypes()
                await viewModel.loadTransactions()
            }
            .onChange(of: searchText) { _, newValue in
                viewModel.searchQuery = newValue
            }
            .onChange(of: selectedBusinessFilter) { _, newValue in
                HapticService.shared.impact(.light)
                viewModel.businessFilter = newValue == "all" ? nil : newValue
                Task { await viewModel.refresh() }
            }
            .onChange(of: selectedCardFilter) { _, newValue in
                HapticService.shared.impact(.light)
                viewModel.cardFilter = newValue == "all" ? nil : newValue
            }
        }
    }

    // MARK: - Selection Mode

    private func enterSelectionMode() {
        withAnimation(.spring(response: 0.3)) {
            isSelectionMode = true
        }
        HapticService.shared.impact(.medium)
    }

    private func exitSelectionMode() {
        withAnimation(.spring(response: 0.3)) {
            isSelectionMode = false
            selectedTransactions.removeAll()
        }
    }

    private func toggleSelectAll() {
        HapticService.shared.impact(.light)
        if selectedTransactions.count == viewModel.filteredTransactions.count {
            selectedTransactions.removeAll()
        } else {
            selectedTransactions = Set(viewModel.filteredTransactions.map { $0.index })
        }
    }

    private func toggleSelection(for transaction: Transaction) {
        HapticService.shared.impact(.light)
        if selectedTransactions.contains(transaction.index) {
            selectedTransactions.remove(transaction.index)
        } else {
            selectedTransactions.insert(transaction.index)
        }
    }

    // MARK: - Selection Mode Header

    private var selectionModeHeader: some View {
        HStack {
            Text("\(selectedTransactions.count) selected")
                .font(.headline)
                .foregroundColor(.white)

            Spacer()

            if selectedTransactions.count > 0 {
                let totalAmount = viewModel.filteredTransactions
                    .filter { selectedTransactions.contains($0.index) }
                    .reduce(0.0) { $0 + abs($1.amount) }

                Text(formatCurrency(totalAmount))
                    .font(.subheadline)
                    .fontWeight(.semibold)
                    .foregroundColor(.tallyAccent)
            }
        }
        .padding()
        .background(Color.tallyCard)
    }

    // MARK: - Batch Action Bar

    private var batchActionBar: some View {
        HStack(spacing: 12) {
            BatchActionButton(icon: "sparkles", label: "Auto") {
                handleBatchAction(.autoCategorize)
            }

            BatchActionButton(icon: "folder.fill", label: "Project") {
                showingBatchProjectPicker = true
            }

            BatchActionButton(icon: "briefcase.fill", label: "Business") {
                showingBatchBusinessPicker = true
            }

            BatchActionButton(icon: "tag.fill", label: "Category") {
                showingBatchCategoryPicker = true
            }

            BatchActionButton(icon: "ellipsis.circle.fill", label: "More") {
                showingBatchActions = true
            }
        }
        .padding()
        .background(Color.tallyCard)
        .transition(.move(edge: .bottom).combined(with: .opacity))
    }

    // MARK: - Batch Processing Overlay

    private var batchProcessingOverlay: some View {
        ZStack {
            Color.black.opacity(0.7)
                .ignoresSafeArea()

            VStack(spacing: 20) {
                ProgressView()
                    .scaleEffect(1.5)
                    .tint(.tallyAccent)

                Text(batchProcessingMessage)
                    .font(.headline)
                    .foregroundColor(.white)

                Text("Processing \(selectedTransactions.count) transactions")
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }
            .padding(40)
            .background(Color.tallyCard)
            .cornerRadius(20)
        }
    }

    // MARK: - Batch Actions

    private func handleBatchAction(_ action: BatchAction) {
        switch action {
        case .autoCategorize:
            Task { await autoCategorizeSelected() }
        case .autoDescriptions:
            Task { await autoDescribeSelected() }
        case .addToReport:
            // Navigate to report creation
            break
        case .exclude:
            Task { await excludeSelected() }
        case .changeBusinessType:
            showingBatchBusinessPicker = true
        case .addToProject:
            showingBatchProjectPicker = true
        case .changeCategory:
            showingBatchCategoryPicker = true
        }
    }

    private func autoCategorizeSelected() async {
        isBatchProcessing = true
        batchProcessingMessage = "Auto-categorizing..."

        for index in selectedTransactions {
            do {
                let suggestion = try await APIClient.shared.getAISuggestions(transactionIndex: index)
                if let category = suggestion.category {
                    try await APIClient.shared.updateTransaction(index: index, category: category)
                }
            } catch {
                print("Failed to categorize transaction \(index): \(error)")
            }
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
    }

    private func autoDescribeSelected() async {
        isBatchProcessing = true
        batchProcessingMessage = "Generating descriptions..."

        for index in selectedTransactions {
            do {
                let note = try await APIClient.shared.generateNote(transactionIndex: index)
                try await APIClient.shared.updateTransaction(index: index, notes: note)
            } catch {
                print("Failed to generate note for transaction \(index): \(error)")
            }
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
    }

    private func excludeSelected() async {
        isBatchProcessing = true
        batchProcessingMessage = "Excluding transactions..."

        for index in selectedTransactions {
            _ = try? await APIClient.shared.excludeTransaction(transactionIndex: index, reason: "Batch excluded from iOS")
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
    }

    private func applyBatchBusinessType(_ businessType: String) async {
        isBatchProcessing = true
        batchProcessingMessage = "Updating business type..."

        for index in selectedTransactions {
            do {
                try await APIClient.shared.updateTransaction(index: index, businessType: businessType)
            } catch {
                print("Failed to update business type for transaction \(index): \(error)")
            }
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
    }

    private func applyBatchProject(_ projectId: String) async {
        isBatchProcessing = true
        batchProcessingMessage = "Adding to project..."

        do {
            try await APIClient.shared.bulkAssignTransactionsToProject(
                transactionIndexes: Array(selectedTransactions),
                projectId: projectId
            )
        } catch {
            print("Failed to assign transactions to project: \(error)")
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
    }

    private func applyBatchCategory(_ category: String) async {
        isBatchProcessing = true
        batchProcessingMessage = "Updating category..."

        for index in selectedTransactions {
            do {
                try await APIClient.shared.updateTransaction(index: index, category: category)
            } catch {
                print("Failed to update category for transaction \(index): \(error)")
            }
        }

        isBatchProcessing = false
        HapticService.shared.notification(.success)
        exitSelectionMode()
        await viewModel.refresh()
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
                    color: Color(red: 1.0, green: 0.45, blue: 0.0)  // Vibrant orange, not muddy brown
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

    // MARK: - Business Filter Bar (Dynamic Per-User Types)

    private var businessFilterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                // "All" option
                FilterPillButton(
                    title: "All",
                    isSelected: selectedBusinessFilter == "all",
                    color: .tallyAccent,
                    icon: nil
                ) {
                    selectedBusinessFilter = "all"
                }

                // Dynamic business types from user's account
                ForEach(viewModel.businessTypes) { businessType in
                    FilterPillButton(
                        title: businessType.displayName.count > 12 ?
                            String(businessType.displayName.split(separator: " ").map { $0.prefix(1) }.joined()) :
                            businessType.displayName,
                        isSelected: selectedBusinessFilter == businessType.name,
                        color: businessType.swiftUIColor,
                        icon: businessType.icon
                    ) {
                        selectedBusinessFilter = businessType.name
                    }
                }

                // Add new business type button
                Button(action: {
                    // TODO: Show add business type sheet
                    HapticService.shared.impact(.medium)
                }) {
                    Image(systemName: "plus.circle.fill")
                        .font(.subheadline)
                        .foregroundColor(.gray)
                        .padding(.horizontal, 8)
                        .padding(.vertical, 6)
                        .background(Color.tallyCard)
                        .cornerRadius(16)
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 8)
        }
    }

    // MARK: - Card/Account Filter Bar

    private var cardFilterBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 8) {
                // "All Cards" option
                CardFilterPill(
                    title: "All Cards",
                    isSelected: selectedCardFilter == "all",
                    icon: "creditcard.and.123"
                ) {
                    selectedCardFilter = "all"
                }

                // Dynamic card options from loaded transactions
                ForEach(viewModel.uniqueCards) { card in
                    CardFilterPill(
                        title: card.shortName,
                        isSelected: selectedCardFilter == card.id,
                        icon: card.icon,
                        count: card.transactionCount
                    ) {
                        selectedCardFilter = card.id
                    }
                }
            }
            .padding(.horizontal)
            .padding(.vertical, 6)
        }
        .background(Color.tallyCard.opacity(0.5))
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
                    SelectableTransactionCard(
                        transaction: transaction,
                        isSelected: selectedTransactions.contains(transaction.index),
                        isSelectionMode: isSelectionMode,
                        onTap: {
                            if isSelectionMode {
                                toggleSelection(for: transaction)
                            } else {
                                selectedTransaction = transaction
                            }
                        },
                        onLongPress: {
                            if !isSelectionMode {
                                enterSelectionMode()
                                toggleSelection(for: transaction)
                            }
                        }
                    )
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
}

// MARK: - Filter Pill Button

struct FilterPillButton: View {
    let title: String
    let isSelected: Bool
    let color: Color
    let icon: String?
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                if let icon = icon {
                    Image(systemName: icon)
                        .font(.caption2)
                }
                Text(title)
                    .font(.subheadline.weight(isSelected ? .semibold : .regular))
            }
            .foregroundColor(isSelected ? .white : .gray)
            .padding(.horizontal, 12)
            .padding(.vertical, 6)
            .background(isSelected ? color : Color.tallyCard)
            .cornerRadius(16)
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .strokeBorder(isSelected ? color : Color.clear, lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Card Filter Pill

struct CardFilterPill: View {
    let title: String
    let isSelected: Bool
    var icon: String = "creditcard"
    var count: Int? = nil
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.caption2)
                Text(title)
                    .font(.caption.weight(isSelected ? .semibold : .regular))
                if let count = count, count > 0, !isSelected {
                    Text("\(count)")
                        .font(.caption2.bold())
                        .foregroundColor(.white.opacity(0.8))
                        .padding(.horizontal, 4)
                        .padding(.vertical, 1)
                        .background(Color.white.opacity(0.2))
                        .cornerRadius(6)
                }
            }
            .foregroundColor(isSelected ? .white : .gray)
            .padding(.horizontal, 10)
            .padding(.vertical, 5)
            .background(isSelected ? Color.blue : Color.tallyCard.opacity(0.8))
            .cornerRadius(12)
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Stat Pill

struct StatPill: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.system(size: 16, weight: .bold, design: .rounded))
                .foregroundColor(color)
            Text(title)
                .font(.caption2)
                .foregroundColor(.gray)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Color.tallyCard.opacity(0.5))
        .cornerRadius(12)
    }
}

// MARK: - Transaction Card View

struct TransactionCardView: View {
    let transaction: Transaction
    var showAISuggestions: Bool = true

    var body: some View {
        VStack(spacing: 0) {
            HStack(spacing: 12) {
                // Status indicator with animation
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
                            .font(.system(.headline, design: .rounded).weight(.semibold))
                            .foregroundColor(transaction.hasReceipt ? .green : .white)
                    }

                    HStack {
                        Text(transaction.formattedDate)
                            .font(.subheadline)
                            .foregroundColor(.gray)

                        Spacer()

                        // Use shared BusinessTypeBadge component
                        BusinessTypeBadge(name: transaction.business)
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

                        Spacer()

                        // Category with AI indicator if it was AI-suggested
                        if let category = transaction.category {
                            HStack(spacing: 3) {
                                if transaction.aiCategory != nil {
                                    Image(systemName: "sparkles")
                                        .font(.system(size: 8))
                                        .foregroundColor(.purple)
                                }
                                Text(category)
                                    .font(.caption)
                                    .foregroundColor(.gray)
                            }
                        }
                    }
                }

                Image(systemName: "chevron.right")
                    .foregroundColor(.gray)
                    .font(.caption)
            }
            .padding()

            // AI Suggestion CTA (if no category set and we have a suggestion)
            if showAISuggestions,
               transaction.category == nil || transaction.category?.isEmpty == true,
               let aiCategory = transaction.aiCategory {
                CategorySuggestionRow(
                    category: aiCategory,
                    confidence: transaction.aiConfidence ?? 0.8,
                    onAccept: {
                        // Accept AI suggestion
                        Task {
                            try? await APIClient.shared.updateTransaction(
                                index: transaction.index,
                                category: aiCategory
                            )
                            // Send feedback for learning
                            try? await APIClient.shared.submitAIFeedback(
                                transactionIndex: transaction.index,
                                feedbackType: "category",
                                suggestedValue: aiCategory,
                                acceptedValue: aiCategory,
                                wasAccepted: true
                            )
                        }
                    }
                )
                .padding(.horizontal)
                .padding(.bottom, 8)
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.tallyCard)
                .overlay(
                    // Left accent border
                    HStack {
                        Rectangle()
                            .fill(statusColor)
                            .frame(width: 3)
                        Spacer()
                    }
                    .clipShape(RoundedRectangle(cornerRadius: 12))
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
}

// MARK: - Detail Row

struct DetailRow: View {
    let label: String
    let value: String

    var body: some View {
        HStack {
            Text(label)
                .foregroundColor(.gray)
            Spacer()
            Text(value)
                .foregroundColor(.white)
        }
        .padding()
    }
}

// MARK: - Transaction Detail View

struct TransactionDetailView: View {
    let transaction: Transaction
    @ObservedObject var viewModel: TransactionsViewModel
    @ObservedObject private var businessTypeService = BusinessTypeService.shared
    @Environment(\.dismiss) private var dismiss

    @State private var showingReceiptPicker = false
    @State private var showingLinkedReceipts = false
    @State private var linkedReceipts: [Receipt] = []
    @State private var isLoadingReceipts = false

    // Inline editing states
    @State private var isEditingCategory = false
    @State private var isEditingBusiness = false
    @State private var isEditingNotes = false
    @State private var editedCategory: String = ""
    @State private var editedBusiness: String = ""
    @State private var editedNotes: String = ""
    @State private var isSaving = false
    @State private var showingCategoryPicker = false
    @State private var showingBusinessPicker = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Header
                    headerCard

                    // Receipt Section
                    receiptSection

                    // Editable Details Section
                    editableDetailsSection

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
            .sheet(isPresented: $showingCategoryPicker) {
                CategoryPickerView(selectedCategory: $editedCategory)
                    .onDisappear {
                        if !editedCategory.isEmpty {
                            saveCategory()
                        }
                    }
            }
            .sheet(isPresented: $showingBusinessPicker) {
                BusinessTypePickerView(
                    selectedBusinessType: $editedBusiness,
                    businessTypes: businessTypeService.businessTypes
                )
                .onDisappear {
                    if !editedBusiness.isEmpty {
                        saveBusinessType()
                    }
                }
            }
            .onAppear {
                editedCategory = transaction.category ?? ""
                editedBusiness = transaction.business ?? "Personal"
                editedNotes = transaction.notes ?? ""
            }
            .task {
                await businessTypeService.loadIfNeeded()
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

    private func unlinkReceipt(receiptId: String) async {
        let success = await viewModel.unmatchReceipt(transactionIndex: transaction.index, receiptId: receiptId)
        if success {
            linkedReceipts.removeAll { $0.id == receiptId }
            if linkedReceipts.isEmpty {
                showingLinkedReceipts = false
            }
        }
    }

    // MARK: - Editable Details Section

    private var editableDetailsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Details")
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                if isSaving {
                    ProgressView()
                        .scaleEffect(0.8)
                }
            }

            VStack(spacing: 0) {
                // Category - Tappable to edit
                Button(action: { showingCategoryPicker = true }) {
                    HStack {
                        Text("Category")
                            .foregroundColor(.gray)
                        Spacer()
                        Text(editedCategory.isEmpty ? "Select category" : editedCategory)
                            .foregroundColor(editedCategory.isEmpty ? .gray.opacity(0.5) : .white)
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                    .padding()
                }

                Divider().background(Color.gray.opacity(0.3))

                // Business Type - Tappable to edit
                Button(action: { showingBusinessPicker = true }) {
                    HStack {
                        Text("Business")
                            .foregroundColor(.gray)
                        Spacer()
                        HStack(spacing: 6) {
                            Circle()
                                .fill(businessTypeService.color(for: editedBusiness))
                                .frame(width: 10, height: 10)
                            Text(businessTypeService.displayName(for: editedBusiness))
                                .foregroundColor(.white)
                        }
                        Image(systemName: "chevron.right")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                    .padding()
                }

                Divider().background(Color.gray.opacity(0.3))

                // Notes - Inline editable
                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Text("Notes")
                            .foregroundColor(.gray)
                        Spacer()
                        if isEditingNotes {
                            Button("Save") {
                                saveNotes()
                            }
                            .font(.caption.bold())
                            .foregroundColor(.tallyAccent)
                        }
                    }

                    if isEditingNotes {
                        TextField("Add notes...", text: $editedNotes, axis: .vertical)
                            .textFieldStyle(.plain)
                            .foregroundColor(.white)
                            .lineLimit(3...6)
                    } else {
                        Text(editedNotes.isEmpty ? "Tap to add notes" : editedNotes)
                            .foregroundColor(editedNotes.isEmpty ? .gray.opacity(0.5) : .white)
                            .lineLimit(3)
                    }
                }
                .padding()
                .contentShape(Rectangle())
                .onTapGesture {
                    isEditingNotes = true
                }
            }
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
    }

    // MARK: - Actions Section

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

            // Show either Exclude or Unexclude based on status
            if transaction.status == .excluded {
                Button(action: {
                    Task {
                        _ = await viewModel.unexcludeTransaction(transactionIndex: transaction.index)
                        HapticService.shared.notification(.success)
                        dismiss()
                    }
                }) {
                    HStack {
                        Image(systemName: "arrow.uturn.backward.circle")
                        Text("Restore Transaction")
                    }
                    .font(.subheadline)
                    .foregroundColor(.green)
                }
            } else {
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

    // MARK: - Save Methods

    private func saveCategory() {
        guard editedCategory != transaction.category else { return }
        isSaving = true
        Task {
            do {
                try await APIClient.shared.updateTransaction(
                    index: transaction.index,
                    category: editedCategory
                )
                HapticService.shared.notification(.success)
            } catch {
                print("Failed to save category: \(error)")
                HapticService.shared.notification(.error)
            }
            isSaving = false
        }
    }

    private func saveBusinessType() {
        guard editedBusiness != transaction.business else { return }
        isSaving = true
        Task {
            do {
                try await APIClient.shared.updateTransaction(
                    index: transaction.index,
                    businessType: editedBusiness
                )
                HapticService.shared.notification(.success)
            } catch {
                print("Failed to save business type: \(error)")
                HapticService.shared.notification(.error)
            }
            isSaving = false
        }
    }

    private func saveNotes() {
        isEditingNotes = false
        guard editedNotes != transaction.notes else { return }
        isSaving = true
        Task {
            do {
                try await APIClient.shared.updateTransaction(
                    index: transaction.index,
                    notes: editedNotes
                )
                HapticService.shared.notification(.success)
            } catch {
                print("Failed to save notes: \(error)")
                HapticService.shared.notification(.error)
            }
            isSaving = false
        }
    }
}

// MARK: - Business Type Picker View

struct BusinessTypePickerView: View {
    @Environment(\.dismiss) private var dismiss
    @Binding var selectedBusinessType: String
    let businessTypes: [APIClient.BusinessType]

    var body: some View {
        NavigationStack {
            List {
                ForEach(businessTypes) { type in
                    Button(action: {
                        selectedBusinessType = type.name
                        HapticService.shared.impact(.light)
                        dismiss()
                    }) {
                        HStack {
                            Circle()
                                .fill(type.swiftUIColor)
                                .frame(width: 12, height: 12)

                            Image(systemName: type.icon)
                                .foregroundColor(type.swiftUIColor)
                                .frame(width: 24)

                            Text(type.displayName)
                                .foregroundColor(.white)

                            Spacer()

                            if selectedBusinessType == type.name {
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
            .navigationTitle("Select Business Type")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
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
    let onUnlink: (String) -> Void
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

// MARK: - Batch Selection Components

/// Selectable transaction card with long-press and selection support
struct SelectableTransactionCard: View {
    let transaction: Transaction
    let isSelected: Bool
    let isSelectionMode: Bool
    let onTap: () -> Void
    let onLongPress: () -> Void

    @State private var isPressed = false

    var body: some View {
        HStack(spacing: 0) {
            // Selection checkbox (when in selection mode)
            if isSelectionMode {
                ZStack {
                    Circle()
                        .fill(isSelected ? Color.tallyAccent : Color.clear)
                        .frame(width: 28, height: 28)

                    Circle()
                        .strokeBorder(isSelected ? Color.tallyAccent : Color.gray, lineWidth: 2)
                        .frame(width: 28, height: 28)

                    if isSelected {
                        Image(systemName: "checkmark")
                            .font(.system(size: 14, weight: .bold))
                            .foregroundColor(.white)
                    }
                }
                .padding(.leading, 12)
                .padding(.trailing, 8)
                .animation(.spring(response: 0.2), value: isSelected)
            }

            TransactionCardView(transaction: transaction, showAISuggestions: !isSelectionMode)
        }
        .scaleEffect(isPressed ? 0.98 : 1.0)
        .animation(.spring(response: 0.2), value: isPressed)
        .contentShape(Rectangle())
        .onTapGesture {
            onTap()
        }
        .onLongPressGesture(minimumDuration: 0.5, pressing: { pressing in
            isPressed = pressing
        }) {
            HapticService.shared.impact(.medium)
            onLongPress()
        }
        .overlay(
            RoundedRectangle(cornerRadius: 12)
                .strokeBorder(isSelected ? Color.tallyAccent : Color.clear, lineWidth: 2)
        )
    }
}

/// Quick action button for batch operations
struct BatchActionButton: View {
    let icon: String
    let label: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.system(size: 20))
                    .foregroundColor(.tallyAccent)

                Text(label)
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 8)
        }
    }
}

/// Enum for batch actions
enum BatchAction {
    case autoCategorize
    case autoDescriptions
    case addToReport
    case exclude
    case changeBusinessType
    case addToProject
    case changeCategory
}

/// Sheet showing all batch action options
struct BatchActionsSheet: View {
    @Environment(\.dismiss) private var dismiss
    let selectedCount: Int
    let onAction: (BatchAction) -> Void

    var body: some View {
        NavigationStack {
            List {
                Section {
                    ActionRow(icon: "sparkles", title: "Auto-Categorize", subtitle: "Use AI to categorize selected transactions", color: .purple) {
                        dismiss()
                        onAction(.autoCategorize)
                    }

                    ActionRow(icon: "text.bubble.fill", title: "Generate Descriptions", subtitle: "Create smart notes for each transaction", color: .blue) {
                        dismiss()
                        onAction(.autoDescriptions)
                    }
                } header: {
                    Text("AI Actions")
                }

                Section {
                    ActionRow(icon: "briefcase.fill", title: "Change Business Type", subtitle: "Set business type for all selected", color: .green) {
                        dismiss()
                        onAction(.changeBusinessType)
                    }

                    ActionRow(icon: "tag.fill", title: "Set Category", subtitle: "Apply category to all selected", color: .orange) {
                        dismiss()
                        onAction(.changeCategory)
                    }

                    ActionRow(icon: "folder.fill", title: "Add to Project", subtitle: "Assign to a project", color: .indigo) {
                        dismiss()
                        onAction(.addToProject)
                    }
                } header: {
                    Text("Organize")
                }

                Section {
                    ActionRow(icon: "doc.text.fill", title: "Add to Report", subtitle: "Include in expense report", color: .cyan) {
                        dismiss()
                        onAction(.addToReport)
                    }
                } header: {
                    Text("Reports")
                }

                Section {
                    ActionRow(icon: "xmark.circle.fill", title: "Exclude Transactions", subtitle: "Remove from receipt matching", color: .red) {
                        dismiss()
                        onAction(.exclude)
                    }
                } header: {
                    Text("Other")
                }
            }
            .navigationTitle("\(selectedCount) Selected")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

struct ActionRow: View {
    let icon: String
    let title: String
    let subtitle: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(color.opacity(0.15))
                        .frame(width: 40, height: 40)

                    Image(systemName: icon)
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundColor(color)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundColor(.primary)

                    Text(subtitle)
                        .font(.caption)
                        .foregroundColor(.secondary)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
            .padding(.vertical, 4)
        }
    }
}

/// Sheet for selecting business type for batch update
struct BatchBusinessPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject private var businessTypeService = BusinessTypeService.shared
    let selectedCount: Int
    let onSelect: (String) -> Void

    var body: some View {
        NavigationStack {
            List {
                ForEach(businessTypeService.businessTypes) { type in
                    Button(action: {
                        dismiss()
                        onSelect(type.name)
                    }) {
                        HStack(spacing: 12) {
                            ZStack {
                                Circle()
                                    .fill(type.swiftUIColor.opacity(0.15))
                                    .frame(width: 40, height: 40)

                                Image(systemName: type.icon)
                                    .font(.system(size: 16))
                                    .foregroundColor(type.swiftUIColor)
                            }

                            Text(type.displayName)
                                .foregroundColor(.primary)

                            Spacer()
                        }
                        .padding(.vertical, 4)
                    }
                }
            }
            .navigationTitle("Select Business Type")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task {
                await businessTypeService.loadIfNeeded()
            }
        }
        .presentationDetents([.medium])
    }
}

/// Sheet for selecting project for batch assignment
struct BatchProjectPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    @State private var projects: [Project] = []
    @State private var isLoading = true
    let selectedCount: Int
    let onSelect: (String) -> Void

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView()
                        .frame(maxHeight: .infinity)
                } else if projects.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "folder.badge.plus")
                            .font(.system(size: 50))
                            .foregroundColor(.gray)

                        Text("No Projects")
                            .font(.headline)
                            .foregroundColor(.primary)

                        Text("Create a project first to organize your transactions")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                            .multilineTextAlignment(.center)
                    }
                    .padding()
                } else {
                    List {
                        ForEach(projects) { project in
                            Button(action: {
                                dismiss()
                                onSelect(project.id)
                            }) {
                                HStack(spacing: 12) {
                                    ZStack {
                                        Circle()
                                            .fill(Color(hex: project.color)?.opacity(0.15) ?? Color.gray.opacity(0.15))
                                            .frame(width: 40, height: 40)

                                        Image(systemName: project.icon)
                                            .font(.system(size: 16))
                                            .foregroundColor(Color(hex: project.color) ?? .gray)
                                    }

                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(project.name)
                                            .foregroundColor(.primary)

                                        if let description = project.description {
                                            Text(description)
                                                .font(.caption)
                                                .foregroundColor(.secondary)
                                                .lineLimit(1)
                                        }
                                    }

                                    Spacer()
                                }
                                .padding(.vertical, 4)
                            }
                        }
                    }
                }
            }
            .navigationTitle("Select Project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task {
                do {
                    projects = try await APIClient.shared.fetchProjects()
                } catch {
                    print("Failed to load projects: \(error)")
                }
                isLoading = false
            }
        }
        .presentationDetents([.medium])
    }
}

/// Sheet for selecting category for batch update
struct BatchCategoryPickerSheet: View {
    @Environment(\.dismiss) private var dismiss
    let selectedCount: Int
    let onSelect: (String) -> Void

    private let categories = [
        "Food & Dining",
        "Transportation",
        "Shopping",
        "Entertainment",
        "Travel",
        "Utilities",
        "Health & Medical",
        "Office Supplies",
        "Software & Subscriptions",
        "Professional Services",
        "Marketing & Advertising",
        "Equipment",
        "Fees & Charges",
        "Insurance",
        "Taxes",
        "Other"
    ]

    var body: some View {
        NavigationStack {
            List {
                ForEach(categories, id: \.self) { category in
                    Button(action: {
                        dismiss()
                        onSelect(category)
                    }) {
                        HStack {
                            Text(category)
                                .foregroundColor(.primary)

                            Spacer()

                            Image(systemName: "chevron.right")
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }
                }
            }
            .navigationTitle("Select Category")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
        .presentationDetents([.medium, .large])
    }
}

#Preview {
    TransactionsView()
}

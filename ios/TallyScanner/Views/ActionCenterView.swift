import SwiftUI

struct ActionCenterView: View {
    @StateObject private var viewModel = ActionCenterViewModel()
    @State private var showScanner = false
    @State private var selectedTransaction: Transaction?
    @State private var showAllNeedsAttention = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 20) {
                        // Summary Cards
                        summaryCards

                        // Quick Actions
                        quickActionsSection

                        // Needs Attention
                        needsAttentionSection

                        // Recent Activity
                        recentActivitySection
                    }
                    .padding()
                }
                .refreshable {
                    await viewModel.refresh()
                }

                // Floating Scan Button
                VStack {
                    Spacer()
                    HStack {
                        Spacer()
                        floatingScanButton
                    }
                }
                .padding()
            }
            .navigationTitle("Dashboard")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { Task { await viewModel.refresh() } }) {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh dashboard")
                    .accessibilityHint("Reloads statistics and action items")
                }
            }
            .fullScreenCover(isPresented: $showScanner) {
                FullScreenScannerView(isPresented: $showScanner) { image in
                    Task {
                        await viewModel.handleScannedImage(image)
                    }
                }
            }
            .sheet(item: $selectedTransaction) { transaction in
                TransactionQuickActionSheet(
                    transaction: transaction,
                    onDismiss: {
                        selectedTransaction = nil
                        Task { await viewModel.refresh() }
                    }
                )
            }
            .task {
                await viewModel.loadData()
            }
        }
    }

    // MARK: - Summary Cards

    private var summaryCards: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 12) {
                DashboardSummaryCard(
                    title: "Needs Receipts",
                    value: "\(viewModel.needsReceiptCount)",
                    icon: "doc.badge.plus",
                    color: viewModel.needsReceiptCount > 0 ? .orange : .green,
                    trend: viewModel.needsReceiptCount > 5 ? "Action needed" : nil
                )

                DashboardSummaryCard(
                    title: "Uncategorized",
                    value: "\(viewModel.uncategorizedCount)",
                    icon: "tag.slash",
                    color: viewModel.uncategorizedCount > 0 ? .yellow : .green,
                    trend: nil
                )

                DashboardSummaryCard(
                    title: "This Week",
                    value: viewModel.weeklySpending,
                    icon: "chart.line.uptrend.xyaxis",
                    color: .tallyAccent,
                    trend: viewModel.weeklyTrend
                )

                DashboardSummaryCard(
                    title: "Match Rate",
                    value: "\(viewModel.matchRate)%",
                    icon: "checkmark.circle",
                    color: viewModel.matchRate >= 90 ? .green : .orange,
                    trend: nil
                )
            }
            .padding(.horizontal, 4)
        }
    }

    // MARK: - Quick Actions

    private var quickActionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Quick Actions")
                .font(.headline)
                .foregroundColor(.secondary)

            HStack(spacing: 12) {
                DashboardQuickActionButton(
                    icon: "camera.fill",
                    label: "Scan",
                    color: .tallyAccent
                ) {
                    showScanner = true
                }

                DashboardQuickActionButton(
                    icon: "sparkles",
                    label: "Auto-Sort",
                    color: .purple
                ) {
                    Task { await viewModel.autoCategorizePending() }
                }

                DashboardQuickActionButton(
                    icon: "link",
                    label: "Auto-Match",
                    color: .blue
                ) {
                    Task { await viewModel.autoMatchReceipts() }
                }

                DashboardQuickActionButton(
                    icon: "doc.text",
                    label: "Report",
                    color: .orange
                ) {
                    // Navigate to reports
                }
            }
        }
    }

    // MARK: - Needs Attention

    private var needsAttentionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Needs Attention")
                    .font(.headline)
                    .foregroundColor(.secondary)

                Spacer()

                if viewModel.actionItems.count > 3 {
                    Button("See All (\(viewModel.actionItems.count))") {
                        showAllNeedsAttention = true
                    }
                    .font(.subheadline)
                    .foregroundColor(.tallyAccent)
                }
            }

            if viewModel.actionItems.isEmpty {
                emptyStateCard
            } else {
                ForEach(viewModel.actionItems.prefix(5)) { item in
                    ActionItemCard(item: item) {
                        handleActionItem(item)
                    }
                }
            }
        }
        .sheet(isPresented: $showAllNeedsAttention) {
            AllActionsSheet(items: viewModel.actionItems) { item in
                handleActionItem(item)
            }
        }
    }

    private var emptyStateCard: some View {
        VStack(spacing: 12) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 48))
                .foregroundColor(.green)
                .accessibilityHidden(true)

            Text("All caught up!")
                .font(.headline)

            Text("No transactions need attention")
                .font(.subheadline)
                .foregroundColor(.secondary)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 32)
        .background(Color.tallyCard)
        .cornerRadius(16)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("All caught up! No transactions need attention.")
    }

    // MARK: - Recent Activity

    private var recentActivitySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Recent Activity")
                .font(.headline)
                .foregroundColor(.secondary)

            ForEach(viewModel.recentTransactions.prefix(5)) { transaction in
                RecentTransactionRow(transaction: transaction)
                    .onTapGesture {
                        selectedTransaction = transaction
                    }
            }

            if viewModel.recentTransactions.isEmpty {
                Text("No recent transactions")
                    .foregroundColor(.secondary)
                    .frame(maxWidth: .infinity)
                    .padding()
            }
        }
    }

    // MARK: - Floating Scan Button

    private var floatingScanButton: some View {
        Button(action: { showScanner = true }) {
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [Color.tallyAccent, Color.tallyAccent.opacity(0.8)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 64, height: 64)
                    .shadow(color: Color.tallyAccent.opacity(0.4), radius: 12, y: 4)

                Image(systemName: "camera.fill")
                    .font(.system(size: 24, weight: .semibold))
                    .foregroundColor(.black)
            }
        }
        .padding(.bottom, 20)
        .accessibilityLabel("Scan receipt")
        .accessibilityHint("Opens camera to scan a new receipt")
    }

    // MARK: - Helpers

    private func handleActionItem(_ item: ActionItem) {
        switch item.type {
        case .needsReceipt, .uncategorized, .aiSuggestion:
            if let transaction = viewModel.getTransaction(for: item) {
                selectedTransaction = transaction
            }
        case .pendingMatch:
            // Handle match flow
            break
        }
    }
}

// MARK: - View Model

@MainActor
class ActionCenterViewModel: ObservableObject {
    @Published var needsReceiptCount = 0
    @Published var uncategorizedCount = 0
    @Published var weeklySpending = "$0"
    @Published var weeklyTrend: String?
    @Published var matchRate = 0
    @Published var actionItems: [ActionItem] = []
    @Published var recentTransactions: [Transaction] = []
    @Published var isLoading = false

    private var allTransactions: [Transaction] = []

    func loadData() async {
        isLoading = true
        defer { isLoading = false }

        await refresh()
    }

    func refresh() async {
        do {
            // Fetch dashboard data
            let stats = try await APIClient.shared.fetchDashboardStats()
            needsReceiptCount = stats.needsReceiptCount
            uncategorizedCount = stats.uncategorizedCount
            weeklySpending = stats.weeklySpending
            weeklyTrend = stats.weeklyTrend
            matchRate = stats.matchRate

            // Fetch transactions needing attention
            let transactions = try await APIClient.shared.fetchTransactions(limit: 100)
            allTransactions = transactions

            // Build action items
            var items: [ActionItem] = []

            for transaction in transactions {
                // Needs receipt
                if transaction.receiptCount == 0 && !transaction.isExcluded {
                    items.append(ActionItem(
                        id: "receipt-\(transaction.index)",
                        type: .needsReceipt,
                        title: transaction.displayMerchant,
                        subtitle: "\(transaction.formattedAmount) • \(transaction.formattedDate)",
                        transactionIndex: transaction.index,
                        priority: .high
                    ))
                }

                // Has AI suggestion
                if let suggestion = transaction.aiSuggestion, transaction.category == nil {
                    items.append(ActionItem(
                        id: "ai-\(transaction.index)",
                        type: .aiSuggestion,
                        title: transaction.displayMerchant,
                        subtitle: "AI suggests: \(suggestion.category ?? "Category")",
                        transactionIndex: transaction.index,
                        priority: .medium,
                        suggestion: suggestion
                    ))
                }
            }

            // Sort by priority and date
            actionItems = items.sorted { $0.priority.rawValue > $1.priority.rawValue }

            // Recent transactions
            recentTransactions = Array(transactions.prefix(10))

        } catch {
            print("Failed to load dashboard: \(error)")
        }
    }

    func autoCategorizePending() async {
        HapticService.shared.impact(.medium)
        for item in actionItems where item.type == .aiSuggestion {
            if let suggestion = item.suggestion, let category = suggestion.category {
                do {
                    try await APIClient.shared.updateTransaction(
                        index: item.transactionIndex,
                        category: category
                    )
                } catch {
                    print("Failed to categorize \(item.transactionIndex): \(error)")
                }
            }
        }
        HapticService.shared.notification(.success)
        await refresh()
    }

    func autoMatchReceipts() async {
        HapticService.shared.impact(.medium)
        do {
            try await APIClient.shared.runAutoMatch()
            HapticService.shared.notification(.success)
            await refresh()
        } catch {
            HapticService.shared.notification(.error)
            print("Auto-match failed: \(error)")
        }
    }

    func handleScannedImage(_ image: UIImage) async {
        guard let imageData = image.jpegData(compressionQuality: 0.85) else {
            HapticService.shared.notification(.error)
            return
        }
        do {
            _ = try await APIClient.shared.uploadReceipt(imageData: imageData)
            HapticService.shared.notification(.success)
        } catch {
            print("Upload failed: \(error)")
            HapticService.shared.notification(.error)
        }
        await refresh()
    }

    func getTransaction(for item: ActionItem) -> Transaction? {
        return allTransactions.first { $0.index == item.transactionIndex }
    }
}

// MARK: - Models

struct ActionItem: Identifiable {
    let id: String
    let type: ActionType
    let title: String
    let subtitle: String
    let transactionIndex: Int
    let priority: Priority
    var suggestion: APIClient.AISuggestion?

    enum ActionType {
        case needsReceipt
        case uncategorized
        case aiSuggestion
        case pendingMatch
    }

    enum Priority: Int {
        case low = 0
        case medium = 1
        case high = 2
    }
}

// MARK: - Supporting Views

struct DashboardSummaryCard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color
    let trend: String?

    private var accessibilityDescription: String {
        var parts = ["\(title): \(value)"]
        if let trend = trend {
            parts.append(trend)
        }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                Spacer()
            }

            Text(value)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundColor(.primary)

            Text(title)
                .font(.caption)
                .foregroundColor(.secondary)

            if let trend = trend {
                Text(trend)
                    .font(.caption2)
                    .foregroundColor(color)
            }
        }
        .frame(width: 120)
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
    }
}

struct DashboardQuickActionButton: View {
    let icon: String
    let label: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(color.opacity(0.15))
                        .frame(width: 48, height: 48)

                    Image(systemName: icon)
                        .font(.system(size: 20, weight: .semibold))
                        .foregroundColor(color)
                }

                Text(label)
                    .font(.caption)
                    .foregroundColor(.primary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 12)
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
        .accessibilityLabel(label)
        .accessibilityHint("Double tap to \(label.lowercased())")
    }
}

struct ActionItemCard: View {
    let item: ActionItem
    let onTap: () -> Void

    private var accessibilityDescription: String {
        let type: String
        switch item.type {
        case .needsReceipt: type = "Needs receipt"
        case .uncategorized: type = "Uncategorized"
        case .aiSuggestion: type = "AI suggestion available"
        case .pendingMatch: type = "Pending match"
        }
        return "\(type): \(item.title), \(item.subtitle)"
    }

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: 12) {
                // Icon
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.15))
                        .frame(width: 44, height: 44)

                    Image(systemName: iconName)
                        .foregroundColor(iconColor)
                        .font(.system(size: 18, weight: .semibold))
                }
                .accessibilityHidden(true)

                // Content
                VStack(alignment: .leading, spacing: 4) {
                    Text(item.title)
                        .font(.subheadline)
                        .fontWeight(.medium)
                        .foregroundColor(.primary)
                        .lineLimit(1)

                    Text(item.subtitle)
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .lineLimit(1)
                }

                Spacer()

                // Action indicator
                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundColor(.secondary)
                    .accessibilityHidden(true)
            }
            .padding()
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
        .buttonStyle(PlainButtonStyle())
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityHint("Double tap to take action")
    }

    private var iconName: String {
        switch item.type {
        case .needsReceipt: return "doc.badge.plus"
        case .uncategorized: return "tag.slash"
        case .aiSuggestion: return "sparkles"
        case .pendingMatch: return "link"
        }
    }

    private var iconColor: Color {
        switch item.type {
        case .needsReceipt: return .orange
        case .uncategorized: return .yellow
        case .aiSuggestion: return .purple
        case .pendingMatch: return .blue
        }
    }
}

struct RecentTransactionRow: View {
    let transaction: Transaction

    private var accessibilityDescription: String {
        var parts = [transaction.displayMerchant]
        parts.append(transaction.formattedAmount)
        parts.append(transaction.formattedDate)
        parts.append(transaction.receiptCount > 0 ? "Has receipt" : "No receipt")
        if let businessType = transaction.businessType {
            parts.append(businessType)
        }
        return parts.joined(separator: ", ")
    }

    var body: some View {
        HStack(spacing: 12) {
            // Receipt status indicator
            ZStack {
                Circle()
                    .fill(transaction.receiptCount > 0 ? Color.green.opacity(0.15) : Color.orange.opacity(0.15))
                    .frame(width: 40, height: 40)

                Image(systemName: transaction.receiptCount > 0 ? "checkmark" : "doc")
                    .font(.system(size: 16, weight: .medium))
                    .foregroundColor(transaction.receiptCount > 0 ? .green : .orange)
            }
            .accessibilityHidden(true)

            VStack(alignment: .leading, spacing: 2) {
                Text(transaction.displayMerchant)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .lineLimit(1)

                Text(transaction.formattedDate)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            VStack(alignment: .trailing, spacing: 2) {
                Text(transaction.formattedAmount)
                    .font(.subheadline)
                    .fontWeight(.semibold)

                if let businessType = transaction.businessType {
                    Text(businessType)
                        .font(.caption2)
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.tallyAccent.opacity(0.15))
                        .foregroundColor(.tallyAccent)
                        .cornerRadius(4)
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
        .accessibilityElement(children: .combine)
        .accessibilityLabel(accessibilityDescription)
        .accessibilityHint("Double tap to view details")
        .accessibilityAddTraits(.isButton)
    }
}

struct TransactionQuickActionSheet: View {
    let transaction: Transaction
    let onDismiss: () -> Void

    @State private var selectedBusinessType: String?
    @State private var isProcessing = false
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Transaction Info
                    VStack(spacing: 8) {
                        Text(transaction.displayMerchant)
                            .font(.title2)
                            .fontWeight(.bold)

                        Text(transaction.formattedAmount)
                            .font(.title)
                            .fontWeight(.bold)
                            .foregroundColor(.tallyAccent)

                        Text(transaction.formattedDate)
                            .foregroundColor(.secondary)
                    }
                    .padding()

                    Divider()

                    // AI Suggestion
                    if let suggestion = transaction.aiSuggestion {
                        VStack(alignment: .leading, spacing: 12) {
                            Label("AI Suggestion", systemImage: "sparkles")
                                .font(.headline)
                                .foregroundColor(.purple)

                            if let category = suggestion.category {
                                Button(action: {
                                    acceptSuggestion(category: category)
                                }) {
                                    HStack {
                                        Text("Apply: \(category)")
                                            .fontWeight(.medium)
                                        Spacer()
                                        Image(systemName: "checkmark.circle.fill")
                                    }
                                    .padding()
                                    .background(Color.purple.opacity(0.15))
                                    .foregroundColor(.purple)
                                    .cornerRadius(12)
                                }
                            }
                        }
                        .padding(.horizontal)
                    }

                    // Business Type Picker
                    VStack(alignment: .leading, spacing: 12) {
                        Text("Business Type")
                            .font(.headline)

                        LazyVGrid(columns: [
                            GridItem(.flexible()),
                            GridItem(.flexible())
                        ], spacing: 12) {
                            ForEach(["Personal", "Business", "Down Home", "Music City Rodeo"], id: \.self) { type in
                                BusinessTypeButton(
                                    name: type,
                                    isSelected: selectedBusinessType == type || transaction.businessType == type
                                ) {
                                    setBusinessType(type)
                                }
                            }
                        }
                    }
                    .padding(.horizontal)

                    // Quick Actions
                    VStack(spacing: 12) {
                        Button(action: { /* Match receipt */ }) {
                            Label("Match Receipt", systemImage: "doc.badge.plus")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.blue.opacity(0.15))
                                .foregroundColor(.blue)
                                .cornerRadius(12)
                        }

                        Button(action: { excludeTransaction() }) {
                            Label("Exclude Transaction", systemImage: "xmark.circle")
                                .frame(maxWidth: .infinity)
                                .padding()
                                .background(Color.red.opacity(0.15))
                                .foregroundColor(.red)
                                .cornerRadius(12)
                        }
                    }
                    .padding(.horizontal)
                }
                .padding(.vertical)
            }
            .navigationTitle("Quick Actions")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        onDismiss()
                        dismiss()
                    }
                }
            }
            .overlay {
                if isProcessing {
                    Color.black.opacity(0.3)
                        .ignoresSafeArea()
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .white))
                        .scaleEffect(1.5)
                }
            }
        }
    }

    private func acceptSuggestion(category: String) {
        isProcessing = true
        Task {
            do {
                try await APIClient.shared.updateTransaction(
                    index: transaction.index,
                    category: category
                )
                HapticService.shared.notification(.success)
                onDismiss()
                dismiss()
            } catch {
                HapticService.shared.notification(.error)
            }
            isProcessing = false
        }
    }

    private func setBusinessType(_ type: String) {
        isProcessing = true
        selectedBusinessType = type
        Task {
            do {
                try await APIClient.shared.updateTransaction(
                    index: transaction.index,
                    businessType: type
                )
                HapticService.shared.notification(.success)
            } catch {
                HapticService.shared.notification(.error)
            }
            isProcessing = false
        }
    }

    private func excludeTransaction() {
        isProcessing = true
        Task {
            do {
                _ = try await APIClient.shared.excludeTransaction(
                    transactionIndex: transaction.index,
                    reason: "Excluded from quick action"
                )
                HapticService.shared.notification(.success)
                onDismiss()
                dismiss()
            } catch {
                HapticService.shared.notification(.error)
            }
            isProcessing = false
        }
    }
}

struct BusinessTypeButton: View {
    let name: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(name)
                .font(.subheadline)
                .fontWeight(.medium)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(isSelected ? Color.tallyAccent : Color.tallyCard)
                .foregroundColor(isSelected ? .black : .primary)
                .cornerRadius(10)
                .overlay(
                    RoundedRectangle(cornerRadius: 10)
                        .strokeBorder(isSelected ? Color.clear : Color.gray.opacity(0.3), lineWidth: 1)
                )
        }
    }
}

struct AllActionsSheet: View {
    let items: [ActionItem]
    let onSelect: (ActionItem) -> Void
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            List(items) { item in
                Button(action: {
                    dismiss()
                    onSelect(item)
                }) {
                    ActionItemCard(item: item) {}
                }
                .listRowBackground(Color.clear)
                .listRowSeparator(.hidden)
            }
            .listStyle(.plain)
            .navigationTitle("All Items (\(items.count))")
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
    ActionCenterView()
}

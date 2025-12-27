import SwiftUI

/// QuickViewer - Fast receipt review workflow for expense reports
/// Swipe through transactions, attach receipts, and prepare for reports
struct QuickViewerView: View {
    @StateObject private var viewModel = QuickViewerViewModel()
    @Environment(\.dismiss) private var dismiss
    @State private var currentIndex = 0
    @State private var dragOffset: CGSize = .zero
    @State private var showingReceiptPicker = false
    @State private var showingReceiptPreview = false
    @State private var showingExporter = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Progress Header
                    progressHeader

                    // Main Card Area
                    if viewModel.isLoading {
                        loadingView
                    } else if viewModel.transactions.isEmpty {
                        emptyView
                    } else {
                        cardStackView
                    }

                    // Quick Actions Bar
                    quickActionsBar
                }
            }
            .navigationTitle("Quick Review")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Done") { dismiss() }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { showingExporter = true }) {
                        Image(systemName: "square.and.arrow.up")
                    }
                }
            }
            .sheet(isPresented: $showingReceiptPicker) {
                ReceiptPickerSheet(
                    transaction: currentTransaction,
                    onSelect: { receiptId in
                        Task { await viewModel.attachReceipt(to: currentIndex, receiptId: receiptId) }
                    }
                )
            }
            .sheet(isPresented: $showingReceiptPreview) {
                if let url = currentTransaction?.r2Url ?? currentTransaction?.receiptUrl {
                    ReceiptPreviewSheet(receiptUrl: url)
                }
            }
            .sheet(isPresented: $showingExporter) {
                ExpenseReportExporter()
            }
            .task {
                await viewModel.loadTransactions()
            }
        }
    }

    private var currentTransaction: Transaction? {
        guard currentIndex < viewModel.transactions.count else { return nil }
        return viewModel.transactions[currentIndex]
    }

    // MARK: - Progress Header

    private var progressHeader: some View {
        VStack(spacing: 12) {
            // Progress bar
            GeometryReader { geo in
                ZStack(alignment: .leading) {
                    Rectangle()
                        .fill(Color.gray.opacity(0.2))
                        .frame(height: 4)
                        .cornerRadius(2)

                    Rectangle()
                        .fill(
                            LinearGradient(
                                colors: [.green, .tallyAccent],
                                startPoint: .leading,
                                endPoint: .trailing
                            )
                        )
                        .frame(width: geo.size.width * progressPercentage, height: 4)
                        .cornerRadius(2)
                        .animation(.spring(), value: currentIndex)
                }
            }
            .frame(height: 4)

            // Stats row
            HStack(spacing: 24) {
                QuickStat(
                    icon: "checkmark.circle.fill",
                    value: "\(viewModel.reviewedCount)",
                    label: "Reviewed",
                    color: .green
                )
                QuickStat(
                    icon: "doc.text.fill",
                    value: "\(viewModel.withReceiptCount)",
                    label: "With Receipt",
                    color: .blue
                )
                QuickStat(
                    icon: "exclamationmark.triangle.fill",
                    value: "\(viewModel.missingCount)",
                    label: "Missing",
                    color: Color(red: 1.0, green: 0.45, blue: 0.0)
                )
                QuickStat(
                    icon: "dollarsign.circle.fill",
                    value: formatCurrency(viewModel.totalAmount),
                    label: "Total",
                    color: .tallyAccent
                )
            }
        }
        .padding()
        .background(Color.tallyCard)
    }

    private var progressPercentage: CGFloat {
        guard viewModel.transactions.count > 0 else { return 0 }
        return CGFloat(currentIndex + 1) / CGFloat(viewModel.transactions.count)
    }

    // MARK: - Card Stack View

    private var cardStackView: some View {
        ZStack {
            // Background cards (stacked effect)
            ForEach(Array(visibleCardIndices.enumerated()), id: \.offset) { offset, index in
                if offset > 0 { // Don't show background for top card
                    transactionCard(for: viewModel.transactions[index])
                        .scaleEffect(1.0 - CGFloat(offset) * 0.05)
                        .offset(y: CGFloat(offset) * 10)
                        .opacity(1.0 - Double(offset) * 0.3)
                        .allowsHitTesting(false)
                }
            }

            // Top card (interactive)
            if let transaction = currentTransaction {
                transactionCard(for: transaction)
                    .offset(x: dragOffset.width, y: dragOffset.height / 3)
                    .rotationEffect(.degrees(Double(dragOffset.width / 20)))
                    .gesture(
                        DragGesture()
                            .onChanged { gesture in
                                dragOffset = gesture.translation
                            }
                            .onEnded { gesture in
                                handleSwipe(gesture)
                            }
                    )
                    .overlay(swipeIndicatorOverlay)
            }
        }
        .padding()
    }

    private var visibleCardIndices: [Int] {
        let maxVisible = 3
        var indices: [Int] = []
        for i in 0..<maxVisible {
            let index = currentIndex + i
            if index < viewModel.transactions.count {
                indices.append(index)
            }
        }
        return indices
    }

    private var swipeIndicatorOverlay: some View {
        ZStack {
            // Left swipe indicator (Skip)
            HStack {
                VStack {
                    Image(systemName: "arrow.left.circle.fill")
                        .font(.system(size: 60))
                    Text("Skip")
                        .font(.headline.bold())
                }
                .foregroundColor(.orange)
                .opacity(dragOffset.width < -50 ? Double(min(1, abs(dragOffset.width) / 100)) : 0)
                .padding(.leading, 40)
                Spacer()
            }

            // Right swipe indicator (Done)
            HStack {
                Spacer()
                VStack {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 60))
                    Text("Done")
                        .font(.headline.bold())
                }
                .foregroundColor(.green)
                .opacity(dragOffset.width > 50 ? Double(min(1, dragOffset.width / 100)) : 0)
                .padding(.trailing, 40)
            }
        }
    }

    // MARK: - Transaction Card

    private func transactionCard(for transaction: Transaction) -> some View {
        VStack(spacing: 0) {
            // Receipt preview area with pinch-to-zoom
            if let url = transaction.r2Url ?? transaction.receiptUrl {
                ZoomableReceiptView(url: url) {
                    showingReceiptPreview = true
                }
            } else {
                receiptPlaceholder(hasReceipt: false)
                    .onTapGesture {
                        showingReceiptPicker = true
                    }
            }

            // Transaction info
            VStack(alignment: .leading, spacing: 16) {
                // Merchant & Amount
                HStack(alignment: .top) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text(transaction.merchant)
                            .font(.title2.bold())
                            .foregroundColor(.white)
                            .lineLimit(2)

                        Text(transaction.formattedDate)
                            .font(.subheadline)
                            .foregroundColor(.gray)
                    }

                    Spacer()

                    Text(transaction.formattedAmount)
                        .font(.title.bold())
                        .foregroundColor(.tallyAccent)
                }

                // Quick info chips
                HStack(spacing: 8) {
                    if let business = transaction.business {
                        InfoChip(icon: "briefcase.fill", text: business, color: .blue)
                    }

                    if let category = transaction.category {
                        InfoChip(icon: "tag.fill", text: category, color: .purple)
                    }

                    if !transaction.cardShortName.isEmpty {
                        InfoChip(icon: "creditcard", text: transaction.cardShortName, color: .gray)
                    }

                    Spacer()

                    // Receipt status indicator
                    if transaction.hasReceipt {
                        Image(systemName: "checkmark.seal.fill")
                            .foregroundColor(.green)
                            .font(.title2)
                    } else {
                        Image(systemName: "exclamationmark.triangle.fill")
                            .foregroundColor(.orange)
                            .font(.title2)
                    }
                }

                // Notes preview
                if let notes = transaction.notes, !notes.isEmpty {
                    Text(notes)
                        .font(.caption)
                        .foregroundColor(.gray)
                        .lineLimit(2)
                        .padding(8)
                        .background(Color.black.opacity(0.2))
                        .cornerRadius(8)
                }
            }
            .padding()
        }
        .background(Color.tallyCard)
        .cornerRadius(20)
        .shadow(color: .black.opacity(0.3), radius: 10, y: 5)
    }

    private func receiptPlaceholder(hasReceipt: Bool) -> some View {
        VStack(spacing: 12) {
            Image(systemName: hasReceipt ? "doc.text.magnifyingglass" : "plus.circle.dashed")
                .font(.system(size: 48))
                .foregroundColor(hasReceipt ? .blue : .orange)

            Text(hasReceipt ? "Loading receipt..." : "Tap to attach receipt")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .frame(height: 200)
        .frame(maxWidth: .infinity)
        .background(Color.black.opacity(0.2))
    }

    // MARK: - Quick Actions Bar

    private var quickActionsBar: some View {
        HStack(spacing: 20) {
            // Skip button
            QuickActionButton(
                icon: "arrow.left.circle.fill",
                label: "Skip",
                color: .orange
            ) {
                skipToNext()
            }

            // Attach receipt button
            QuickActionButton(
                icon: "paperclip.circle.fill",
                label: "Attach",
                color: .blue
            ) {
                showingReceiptPicker = true
            }

            // Mark done button
            QuickActionButton(
                icon: "checkmark.circle.fill",
                label: "Done",
                color: .green
            ) {
                markAsDone()
            }

            // View receipt button (if has receipt)
            if currentTransaction?.hasReceipt == true {
                QuickActionButton(
                    icon: "eye.circle.fill",
                    label: "View",
                    color: .purple
                ) {
                    showingReceiptPreview = true
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
    }

    // MARK: - Loading & Empty Views

    private var loadingView: some View {
        VStack(spacing: 20) {
            ProgressView()
                .scaleEffect(1.5)
            Text("Loading transactions...")
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyView: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.seal.fill")
                .font(.system(size: 60))
                .foregroundColor(.green)

            Text("All Done!")
                .font(.title.bold())
                .foregroundColor(.white)

            Text("No more transactions to review")
                .foregroundColor(.gray)

            Button(action: { showingExporter = true }) {
                Label("Export Report", systemImage: "square.and.arrow.up")
                    .font(.headline)
                    .foregroundColor(.black)
                    .padding()
                    .background(Color.tallyAccent)
                    .cornerRadius(12)
            }
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: - Actions

    private func handleSwipe(_ gesture: DragGesture.Value) {
        let threshold: CGFloat = 100

        if gesture.translation.width > threshold {
            // Right swipe - Mark done
            withAnimation(.spring()) {
                dragOffset = CGSize(width: 500, height: 0)
            }
            HapticService.shared.swipeComplete()
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                markAsDone()
                resetCard()
            }
        } else if gesture.translation.width < -threshold {
            // Left swipe - Skip
            withAnimation(.spring()) {
                dragOffset = CGSize(width: -500, height: 0)
            }
            HapticService.shared.impact(.light)
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.3) {
                skipToNext()
                resetCard()
            }
        } else {
            // Reset
            withAnimation(.spring()) {
                dragOffset = .zero
            }
        }
    }

    private func resetCard() {
        dragOffset = .zero
    }

    private func skipToNext() {
        if currentIndex < viewModel.transactions.count - 1 {
            withAnimation(.spring()) {
                currentIndex += 1
            }
        }
    }

    private func markAsDone() {
        Task {
            await viewModel.markAsReviewed(at: currentIndex)
        }
        skipToNext()
    }

    private func formatCurrency(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        formatter.maximumFractionDigits = 0
        return formatter.string(from: NSNumber(value: value)) ?? "$\(Int(value))"
    }
}

// MARK: - Quick Stat

struct QuickStat: View {
    let icon: String
    let value: String
    let label: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            HStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.caption)
                Text(value)
                    .font(.subheadline.bold())
            }
            .foregroundColor(color)

            Text(label)
                .font(.caption2)
                .foregroundColor(.gray)
        }
    }
}

// MARK: - Info Chip

struct InfoChip: View {
    let icon: String
    let text: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.caption2)
            Text(text)
                .font(.caption2)
        }
        .foregroundColor(.white)
        .padding(.horizontal, 8)
        .padding(.vertical, 4)
        .background(color.opacity(0.6))
        .cornerRadius(6)
    }
}

// MARK: - Quick Action Button

struct QuickActionButton: View {
    let icon: String
    let label: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 4) {
                Image(systemName: icon)
                    .font(.title)
                    .foregroundColor(color)
                Text(label)
                    .font(.caption2)
                    .foregroundColor(.gray)
            }
        }
        .frame(minWidth: 60)
    }
}

// MARK: - Quick Viewer View Model

@MainActor
class QuickViewerViewModel: ObservableObject {
    @Published var transactions: [Transaction] = []
    @Published var isLoading = false
    @Published var reviewedIndices: Set<Int> = []

    var reviewedCount: Int { reviewedIndices.count }

    var withReceiptCount: Int {
        transactions.filter { $0.hasReceipt }.count
    }

    var missingCount: Int {
        transactions.filter { !$0.hasReceipt }.count
    }

    var totalAmount: Double {
        transactions.reduce(0) { $0 + abs($1.amount) }
    }

    func loadTransactions() async {
        isLoading = true
        defer { isLoading = false }

        do {
            // Load transactions that need review (missing receipts or unreviewed)
            transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: 100,
                business: nil
            )
            // Sort by date descending, missing receipts first
            transactions.sort { t1, t2 in
                if t1.hasReceipt != t2.hasReceipt {
                    return !t1.hasReceipt // Missing receipts first
                }
                return t1.date > t2.date
            }
        } catch {
            print("Failed to load transactions: \(error)")
        }
    }

    func markAsReviewed(at index: Int) async {
        reviewedIndices.insert(index)
    }

    func attachReceipt(to index: Int, receiptId: String) async {
        guard index < transactions.count else { return }
        do {
            let success = try await APIClient.shared.linkReceiptToTransaction(
                transactionIndex: transactions[index].index,
                receiptId: receiptId
            )
            if success {
                transactions[index].hasReceipt = true
                transactions[index].receiptCount += 1
                HapticService.shared.notification(.success)
            }
        } catch {
            print("Failed to attach receipt: \(error)")
            HapticService.shared.notification(.error)
        }
    }
}

// MARK: - Receipt Picker Sheet

struct ReceiptPickerSheet: View {
    let transaction: Transaction?
    let onSelect: (String) -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var receipts: [IncomingReceipt] = []
    @State private var isLoading = true

    var body: some View {
        NavigationStack {
            Group {
                if isLoading {
                    ProgressView("Loading receipts...")
                } else if receipts.isEmpty {
                    VStack(spacing: 16) {
                        Image(systemName: "doc.text.magnifyingglass")
                            .font(.system(size: 48))
                            .foregroundColor(.gray)
                        Text("No pending receipts")
                            .foregroundColor(.gray)
                    }
                } else {
                    List(receipts) { receipt in
                        Button {
                            onSelect(receipt.id)
                            dismiss()
                        } label: {
                            HStack {
                                AsyncImage(url: URL(string: receipt.thumbnailURL ?? receipt.imageURL ?? "")) { phase in
                                    if case .success(let image) = phase {
                                        image
                                            .resizable()
                                            .scaledToFill()
                                    } else {
                                        Color.gray
                                    }
                                }
                                .frame(width: 60, height: 60)
                                .cornerRadius(8)

                                VStack(alignment: .leading) {
                                    Text(receipt.merchant ?? "Unknown")
                                        .foregroundColor(.white)
                                    if let amount = receipt.amount {
                                        Text("$\(String(format: "%.2f", amount))")
                                            .foregroundColor(.tallyAccent)
                                    }
                                }
                            }
                        }
                        .listRowBackground(Color.tallyCard)
                    }
                    .listStyle(.plain)
                }
            }
            .navigationTitle("Select Receipt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .task {
                do {
                    receipts = try await APIClient.shared.fetchIncomingReceipts(status: "pending")
                } catch {
                    print("Failed to load receipts: \(error)")
                }
                isLoading = false
            }
        }
    }
}

// MARK: - Receipt Preview Sheet with Pinch-to-Zoom

struct ReceiptPreviewSheet: View {
    let receiptUrl: String
    @Environment(\.dismiss) private var dismiss
    @State private var scale: CGFloat = 1.0
    @State private var lastScale: CGFloat = 1.0
    @State private var offset: CGSize = .zero
    @State private var lastOffset: CGSize = .zero
    @GestureState private var magnifyBy: CGFloat = 1.0

    var body: some View {
        NavigationStack {
            GeometryReader { geo in
                ZStack {
                    Color.black.ignoresSafeArea()

                    AsyncImage(url: URL(string: receiptUrl)) { phase in
                        switch phase {
                        case .success(let image):
                            image
                                .resizable()
                                .scaledToFit()
                                .scaleEffect(scale * magnifyBy)
                                .offset(offset)
                                .gesture(
                                    // Pinch to zoom
                                    MagnificationGesture()
                                        .updating($magnifyBy) { value, state, _ in
                                            state = value
                                        }
                                        .onEnded { value in
                                            scale = min(max(scale * value, 1.0), 5.0)
                                            HapticService.shared.impact(.light)
                                        }
                                )
                                .simultaneousGesture(
                                    // Drag to pan when zoomed
                                    DragGesture()
                                        .onChanged { value in
                                            if scale > 1.0 {
                                                offset = CGSize(
                                                    width: lastOffset.width + value.translation.width,
                                                    height: lastOffset.height + value.translation.height
                                                )
                                            }
                                        }
                                        .onEnded { _ in
                                            lastOffset = offset
                                        }
                                )
                                .simultaneousGesture(
                                    // Double tap to zoom in/out
                                    TapGesture(count: 2)
                                        .onEnded {
                                            withAnimation(.spring(response: 0.3)) {
                                                if scale > 1.0 {
                                                    scale = 1.0
                                                    offset = .zero
                                                    lastOffset = .zero
                                                } else {
                                                    scale = 2.5
                                                }
                                            }
                                            HapticService.shared.impact(.medium)
                                        }
                                )
                                .animation(.spring(response: 0.3), value: scale)
                        case .failure:
                            VStack {
                                Image(systemName: "exclamationmark.triangle")
                                    .font(.largeTitle)
                                Text("Failed to load image")
                            }
                            .foregroundColor(.gray)
                        case .empty:
                            ProgressView()
                        @unknown default:
                            EmptyView()
                        }
                    }
                }
            }
            .navigationTitle("Receipt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    // Zoom level indicator
                    if scale > 1.0 {
                        Text("\(Int(scale * 100))%")
                            .font(.caption.monospacedDigit())
                            .foregroundColor(.gray)
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Done") { dismiss() }
                }
            }
            .gesture(
                // Swipe down to dismiss
                DragGesture()
                    .onEnded { gesture in
                        if gesture.translation.height > 100 && scale <= 1.0 {
                            dismiss()
                        }
                    }
            )
        }
        .presentationDragIndicator(.visible)
    }
}

// MARK: - Zoomable Receipt View (for inline card preview)

struct ZoomableReceiptView: View {
    let url: String
    let onTap: () -> Void
    @State private var scale: CGFloat = 1.0
    @GestureState private var magnifyBy: CGFloat = 1.0

    var body: some View {
        AsyncImage(url: URL(string: url)) { phase in
            switch phase {
            case .success(let image):
                image
                    .resizable()
                    .scaledToFill()
                    .frame(height: 200)
                    .clipped()
                    .scaleEffect(scale * magnifyBy)
                    .gesture(
                        MagnificationGesture()
                            .updating($magnifyBy) { value, state, _ in
                                state = value
                            }
                            .onEnded { value in
                                withAnimation(.spring()) {
                                    scale = min(max(scale * value, 1.0), 3.0)
                                }
                                if scale > 1.5 {
                                    // Auto open fullscreen if zooming a lot
                                    onTap()
                                }
                            }
                    )
                    .simultaneousGesture(
                        TapGesture(count: 1)
                            .onEnded { onTap() }
                    )
                    .simultaneousGesture(
                        TapGesture(count: 2)
                            .onEnded {
                                withAnimation(.spring()) {
                                    scale = scale > 1.0 ? 1.0 : 2.0
                                }
                                HapticService.shared.impact(.light)
                            }
                    )
            case .failure, .empty:
                Rectangle()
                    .fill(Color.gray.opacity(0.2))
                    .frame(height: 200)
                    .overlay {
                        Image(systemName: "photo")
                            .foregroundColor(.gray)
                    }
            @unknown default:
                EmptyView()
            }
        }
    }
}

// MARK: - Preview

#Preview {
    QuickViewerView()
        .preferredColorScheme(.dark)
}

import SwiftUI

// MARK: - Receipt Inbox View (Award-Winning Design)

struct ReceiptInboxView: View {
    @StateObject private var viewModel = ReceiptInboxViewModel()
    @State private var selectedSource: ReceiptSource = .all
    @State private var selectedReceipt: IncomingReceipt?
    @State private var showMatchAnimation = false
    @State private var matchedMerchant = ""
    @State private var showExporter = false
    @State private var dragOffset: CGFloat = 0

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Hero Stats Card
                    heroStatsCard
                        .padding(.horizontal)
                        .padding(.top, 8)

                    // Source Filter Pills
                    sourceFilterPills
                        .padding(.vertical, 16)

                    // Receipt List
                    if viewModel.isLoading && viewModel.receipts.isEmpty {
                        loadingView
                    } else if viewModel.filteredReceipts.isEmpty {
                        emptyStateView
                    } else {
                        receiptsList
                    }
                }

                // Match Success Celebration Overlay
                if showMatchAnimation {
                    matchCelebrationOverlay
                }
            }
            .navigationTitle("Receipt Inbox")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button(action: { showExporter = true }) {
                        Image(systemName: "square.and.arrow.up")
                            .symbolRenderingMode(.hierarchical)
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(action: { Task { await viewModel.scanForReceipts() } }) {
                            Label("Scan Emails", systemImage: "envelope.arrow.triangle.branch")
                        }

                        Button(action: { Task { await viewModel.runAutoMatch() } }) {
                            Label("Auto-Match All", systemImage: "wand.and.stars")
                        }

                        Divider()

                        Button(action: { Task { await viewModel.refresh() } }) {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                    } label: {
                        Image(systemName: viewModel.isScanning ? "hourglass" : "ellipsis.circle")
                            .symbolRenderingMode(.hierarchical)
                            .rotationEffect(.degrees(viewModel.isScanning ? 360 : 0))
                            .animation(.linear(duration: 1).repeatForever(autoreverses: false), value: viewModel.isScanning)
                    }
                }
            }
            .refreshable {
                await viewModel.refresh()
            }
            .sheet(item: $selectedReceipt) { receipt in
                ReceiptMatchingSheet(
                    receipt: receipt,
                    onMatched: { merchant in
                        handleMatchSuccess(merchant: merchant)
                    },
                    onDismiss: {
                        Task { await viewModel.refresh() }
                    }
                )
            }
            .sheet(isPresented: $showExporter) {
                ExpenseReportExporter()
            }
            .task {
                await viewModel.loadReceipts()
            }
            .onChange(of: selectedSource) { _, newSource in
                HapticService.shared.impact(.light)
                viewModel.filterBySource(newSource)
            }
        }
    }

    // MARK: - Hero Stats Card

    private var heroStatsCard: some View {
        VStack(spacing: 16) {
            // Main stat - Matching Rate Ring
            HStack(spacing: 24) {
                // Matching Rate Circle
                ZStack {
                    // Background ring
                    Circle()
                        .stroke(Color.gray.opacity(0.2), lineWidth: 8)
                        .frame(width: 100, height: 100)

                    // Progress ring
                    Circle()
                        .trim(from: 0, to: viewModel.matchingRate)
                        .stroke(
                            AngularGradient(
                                colors: [.green, .tallyAccent, .green],
                                center: .center
                            ),
                            style: StrokeStyle(lineWidth: 8, lineCap: .round)
                        )
                        .frame(width: 100, height: 100)
                        .rotationEffect(.degrees(-90))
                        .animation(.spring(response: 1, dampingFraction: 0.7), value: viewModel.matchingRate)

                    // Center content
                    VStack(spacing: 0) {
                        Text("\(Int(viewModel.matchingRate * 100))%")
                            .font(.system(size: 24, weight: .bold, design: .rounded))
                            .foregroundColor(.white)
                        Text("Matched")
                            .font(.caption2)
                            .foregroundColor(.gray)
                    }
                }

                // Stats Grid
                VStack(alignment: .leading, spacing: 12) {
                    StatRow(
                        icon: "clock.fill",
                        value: viewModel.stats.pending,
                        label: "Pending",
                        color: .orange
                    )
                    StatRow(
                        icon: "checkmark.circle.fill",
                        value: viewModel.stats.matched,
                        label: "Matched",
                        color: .green
                    )
                    StatRow(
                        icon: "sparkles",
                        value: viewModel.stats.autoMatched,
                        label: "AI Matched",
                        color: .purple
                    )
                }
            }

            // Source Breakdown Bar
            if viewModel.stats.total > 0 {
                GeometryReader { geo in
                    HStack(spacing: 2) {
                        ForEach(viewModel.sourceBreakdown) { source in
                            Rectangle()
                                .fill(source.color)
                                .frame(width: geo.size.width * source.percentage)
                        }
                    }
                    .cornerRadius(4)
                }
                .frame(height: 6)

                // Source legend
                HStack(spacing: 16) {
                    ForEach(viewModel.sourceBreakdown) { source in
                        HStack(spacing: 4) {
                            Circle()
                                .fill(source.color)
                                .frame(width: 8, height: 8)
                            Text(source.name)
                                .font(.caption2)
                                .foregroundColor(.gray)
                        }
                    }
                }
            }
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color.tallyCard)
                .shadow(color: .black.opacity(0.3), radius: 10, y: 5)
        )
    }

    // MARK: - Source Filter Pills

    private var sourceFilterPills: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 10) {
                ForEach(ReceiptSource.allCases, id: \.self) { source in
                    SourcePill(
                        source: source,
                        count: viewModel.countForSource(source),
                        isSelected: selectedSource == source
                    ) {
                        selectedSource = source
                    }
                }
            }
            .padding(.horizontal)
        }
    }

    // MARK: - Receipts List

    private var receiptsList: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(viewModel.filteredReceipts) { receipt in
                    ReceiptInboxCard(receipt: receipt, isRejected: selectedSource == .rejected)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            HapticService.shared.impact(.light)
                            if selectedSource != .rejected {
                                selectedReceipt = receipt
                            }
                        }
                        .contextMenu {
                            contextMenuItems(for: receipt)
                        }
                        .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                            if selectedSource == .rejected {
                                // For rejected receipts, show unreject
                                Button {
                                    unrejectReceipt(receipt)
                                } label: {
                                    Label("Restore", systemImage: "arrow.uturn.backward.circle.fill")
                                }
                                .tint(.green)
                            } else {
                                // For pending receipts, show reject
                                Button(role: .destructive) {
                                    rejectReceipt(receipt)
                                } label: {
                                    Label("Reject", systemImage: "xmark.circle.fill")
                                }
                            }
                        }
                        .swipeActions(edge: .leading, allowsFullSwipe: true) {
                            if selectedSource == .rejected {
                                // For rejected, left swipe also restores
                                Button {
                                    unrejectReceipt(receipt)
                                } label: {
                                    Label("Restore", systemImage: "arrow.uturn.backward.circle.fill")
                                }
                                .tint(.green)
                            } else {
                                // For pending, left swipe matches
                                Button {
                                    quickMatch(receipt)
                                } label: {
                                    Label("Match", systemImage: "checkmark.circle.fill")
                                }
                                .tint(.green)
                            }
                        }
                        .transition(.asymmetric(
                            insertion: .move(edge: .trailing).combined(with: .opacity),
                            removal: .move(edge: .leading).combined(with: .opacity)
                        ))
                }
            }
            .padding()
            .animation(.spring(response: 0.4), value: viewModel.filteredReceipts.count)
        }
    }

    // MARK: - Context Menu

    @ViewBuilder
    private func contextMenuItems(for receipt: IncomingReceipt) -> some View {
        if selectedSource == .rejected {
            // Context menu for rejected receipts
            Button {
                unrejectReceipt(receipt)
            } label: {
                Label("Restore to Inbox", systemImage: "arrow.uturn.backward.circle")
            }

            Divider()

            Button(role: .destructive) {
                Task { await viewModel.permanentlyDelete(receipt) }
            } label: {
                Label("Delete Permanently", systemImage: "trash.fill")
            }
        } else {
            // Context menu for pending receipts
            Button {
                quickMatch(receipt)
            } label: {
                Label("Quick Match", systemImage: "bolt.fill")
            }

            Button {
                selectedReceipt = receipt
            } label: {
                Label("Review Details", systemImage: "doc.text.magnifyingglass")
            }

            Divider()

            Button {
                Task { await viewModel.autoMatch(receipt) }
            } label: {
                Label("AI Auto-Match", systemImage: "wand.and.stars")
            }

            Divider()

            Button(role: .destructive) {
                rejectReceipt(receipt)
            } label: {
                Label("Reject", systemImage: "trash")
            }
        }
    }

    // MARK: - Loading View

    private var loadingView: some View {
        VStack(spacing: 20) {
            // Animated receipt stack
            ZStack {
                ForEach(0..<3) { index in
                    RoundedRectangle(cornerRadius: 12)
                        .fill(Color.tallyCard)
                        .frame(width: 120 - CGFloat(index * 20), height: 80 - CGFloat(index * 10))
                        .offset(y: CGFloat(index * 8))
                        .opacity(1 - Double(index) * 0.2)
                }
            }
            .modifier(PulseAnimation())

            Text("Loading receipts...")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: - Empty State

    private var emptyStateView: some View {
        VStack(spacing: 24) {
            // Animated illustration
            ZStack {
                Circle()
                    .fill(Color.tallyAccent.opacity(0.1))
                    .frame(width: 120, height: 120)

                Image(systemName: "tray.fill")
                    .font(.system(size: 48))
                    .foregroundColor(.tallyAccent)
            }

            VStack(spacing: 8) {
                Text(emptyStateTitle)
                    .font(.title2.bold())
                    .foregroundColor(.white)

                Text(emptyStateSubtitle)
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 40)
            }

            // Action buttons
            VStack(spacing: 12) {
                Button(action: { Task { await viewModel.scanForReceipts() } }) {
                    Label("Scan for Receipts", systemImage: "envelope.arrow.triangle.branch")
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent)
                        .cornerRadius(14)
                }

                Button(action: openCamera) {
                    Label("Scan with Camera", systemImage: "camera.fill")
                        .font(.headline)
                        .foregroundColor(.tallyAccent)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent.opacity(0.15))
                        .cornerRadius(14)
                }
            }
            .padding(.horizontal, 40)
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyStateTitle: String {
        switch selectedSource {
        case .all: return "All Caught Up!"
        case .email: return "No Email Receipts"
        case .scanned: return "No Scanned Receipts"
        case .imported: return "No Imported Receipts"
        case .shared: return "No Shared Receipts"
        case .rejected: return "No Rejected Receipts"
        }
    }

    private var emptyStateSubtitle: String {
        switch selectedSource {
        case .all: return "You've matched all your receipts. Scan for new ones or take a photo."
        case .email: return "Connect your email to automatically import receipts."
        case .scanned: return "Use the camera to scan paper receipts."
        case .imported: return "Import receipts from your photo library."
        case .shared: return "Share receipts from other apps using the share sheet."
        case .rejected: return "Receipts you reject will appear here. You can restore them anytime."
        }
    }

    // MARK: - Match Celebration Overlay

    private var matchCelebrationOverlay: some View {
        ZStack {
            Color.black.opacity(0.6)
                .ignoresSafeArea()
                .onTapGesture {
                    withAnimation(.spring()) {
                        showMatchAnimation = false
                    }
                }

            VStack(spacing: 24) {
                // Success checkmark with particles
                ZStack {
                    // Particle burst
                    ForEach(0..<12) { i in
                        Circle()
                            .fill(Color.tallyAccent)
                            .frame(width: 8, height: 8)
                            .offset(y: showMatchAnimation ? -60 : 0)
                            .rotationEffect(.degrees(Double(i) * 30))
                            .opacity(showMatchAnimation ? 0 : 1)
                            .animation(
                                .spring(response: 0.6, dampingFraction: 0.6)
                                .delay(Double(i) * 0.02),
                                value: showMatchAnimation
                            )
                    }

                    // Checkmark circle
                    ZStack {
                        Circle()
                            .fill(Color.tallyAccent)
                            .frame(width: 100, height: 100)
                            .scaleEffect(showMatchAnimation ? 1 : 0.5)

                        Image(systemName: "checkmark")
                            .font(.system(size: 48, weight: .bold))
                            .foregroundColor(.black)
                    }
                    .animation(.spring(response: 0.4, dampingFraction: 0.6), value: showMatchAnimation)
                }

                Text("Receipt Matched!")
                    .font(.title.bold())
                    .foregroundColor(.white)

                Text(matchedMerchant)
                    .font(.headline)
                    .foregroundColor(.tallyAccent)
            }
            .scaleEffect(showMatchAnimation ? 1 : 0.8)
            .opacity(showMatchAnimation ? 1 : 0)
            .animation(.spring(response: 0.4, dampingFraction: 0.7), value: showMatchAnimation)
        }
    }

    // MARK: - Actions

    private func handleMatchSuccess(merchant: String) {
        matchedMerchant = merchant
        HapticService.shared.matchSuccess()

        withAnimation(.spring()) {
            showMatchAnimation = true
        }

        // Auto-dismiss after delay
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) {
            withAnimation(.spring()) {
                showMatchAnimation = false
            }
            Task { await viewModel.refresh() }
        }
    }

    private func quickMatch(_ receipt: IncomingReceipt) {
        HapticService.shared.impact(.medium)
        Task {
            let success = await viewModel.quickMatch(receipt)
            if success {
                handleMatchSuccess(merchant: receipt.merchant ?? "Receipt")
            }
        }
    }

    private func rejectReceipt(_ receipt: IncomingReceipt) {
        HapticService.shared.swipeComplete()
        Task {
            await viewModel.reject(receipt)
        }
    }

    private func unrejectReceipt(_ receipt: IncomingReceipt) {
        HapticService.shared.impact(.medium)
        Task {
            let success = await viewModel.unreject(receipt)
            if success {
                HapticService.shared.notification(.success)
            }
        }
    }

    private func openCamera() {
        NotificationCenter.default.post(name: .navigateToScanner, object: nil)
    }
}

// MARK: - Receipt Source Enum

enum ReceiptSource: String, CaseIterable {
    case all = "All"
    case email = "Email"
    case scanned = "Scanned"
    case imported = "Imported"
    case shared = "Shared"
    case rejected = "Rejected"

    var icon: String {
        switch self {
        case .all: return "tray.full.fill"
        case .email: return "envelope.fill"
        case .scanned: return "camera.fill"
        case .imported: return "photo.fill"
        case .shared: return "square.and.arrow.down.fill"
        case .rejected: return "xmark.circle.fill"
        }
    }

    var color: Color {
        switch self {
        case .all: return .tallyAccent
        case .email: return .blue
        case .scanned: return .orange
        case .imported: return .purple
        case .shared: return .pink
        case .rejected: return .red
        }
    }
}

// MARK: - Source Pill

struct SourcePill: View {
    let source: ReceiptSource
    let count: Int
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                Image(systemName: source.icon)
                    .font(.caption)
                Text(source.rawValue)
                    .font(.subheadline.weight(isSelected ? .semibold : .regular))
                if count > 0 && !isSelected {
                    Text("\(count)")
                        .font(.caption2.bold())
                        .padding(.horizontal, 6)
                        .padding(.vertical, 2)
                        .background(Color.white.opacity(0.2))
                        .cornerRadius(10)
                }
            }
            .foregroundColor(isSelected ? .black : .white)
            .padding(.horizontal, 16)
            .padding(.vertical, 10)
            .background(
                Capsule()
                    .fill(isSelected ? source.color : Color.tallyCard)
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Stat Row

struct StatRow: View {
    let icon: String
    let value: Int
    let label: String
    let color: Color

    var body: some View {
        HStack(spacing: 8) {
            Image(systemName: icon)
                .foregroundColor(color)
                .frame(width: 20)

            Text("\(value)")
                .font(.headline)
                .foregroundColor(.white)

            Text(label)
                .font(.caption)
                .foregroundColor(.gray)
        }
    }
}

// MARK: - Receipt Inbox Card

struct ReceiptInboxCard: View {
    let receipt: IncomingReceipt
    var isRejected: Bool = false

    var body: some View {
        HStack(spacing: 14) {
            // Thumbnail with source badge
            ZStack(alignment: .bottomTrailing) {
                AsyncImage(url: URL(string: receipt.thumbnailURL ?? receipt.imageURL ?? "")) { phase in
                    switch phase {
                    case .success(let image):
                        image
                            .resizable()
                            .scaledToFill()
                            .saturation(isRejected ? 0.3 : 1.0)
                    case .failure, .empty:
                        Rectangle()
                            .fill(Color.tallyCard)
                            .overlay {
                                Image(systemName: sourceIcon)
                                    .foregroundColor(.gray)
                            }
                    @unknown default:
                        EmptyView()
                    }
                }
                .frame(width: 70, height: 70)
                .cornerRadius(12)
                .clipped()
                .overlay(
                    isRejected ?
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.red.opacity(0.5), lineWidth: 2)
                    : nil
                )

                // Source badge or rejected indicator
                if isRejected {
                    Image(systemName: "xmark.circle.fill")
                        .font(.caption)
                        .foregroundColor(.white)
                        .padding(3)
                        .background(Color.red)
                        .clipShape(Circle())
                        .offset(x: 4, y: 4)
                } else {
                    Image(systemName: sourceIcon)
                        .font(.caption2)
                        .foregroundColor(.white)
                        .padding(4)
                        .background(sourceColor)
                        .clipShape(Circle())
                        .offset(x: 4, y: 4)
                }
            }

            // Content
            VStack(alignment: .leading, spacing: 6) {
                // Merchant & confidence
                HStack {
                    Text(receipt.merchant ?? receipt.sender ?? "Unknown")
                        .font(.headline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Spacer()

                    // AI confidence indicator
                    if let confidence = receipt.confidenceScore {
                        ConfidenceBadge(confidence: confidence)
                    }
                }

                // Amount & date
                HStack {
                    if let amount = receipt.amount {
                        Text(formatCurrency(amount))
                            .font(.subheadline.bold())
                            .foregroundColor(.tallyAccent)
                    }

                    if let date = receipt.receiptDate {
                        Text("•")
                            .foregroundColor(.gray)
                        Text(formatDate(date))
                            .font(.caption)
                            .foregroundColor(.gray)
                    }

                    Spacer()
                }

                // Email subject or AI notes
                if let subject = receipt.subject ?? receipt.aiNotes {
                    Text(subject)
                        .font(.caption)
                        .foregroundColor(.gray)
                        .lineLimit(1)
                }

                // Match suggestion indicator
                if receipt.suggestedMatch != nil {
                    HStack(spacing: 4) {
                        Image(systemName: "sparkles")
                            .font(.caption2)
                        Text("Match found")
                            .font(.caption2)
                    }
                    .foregroundColor(.purple)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 4)
                    .background(Color.purple.opacity(0.2))
                    .cornerRadius(6)
                }
            }

            // Chevron
            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.gray.opacity(0.5))
        }
        .padding(14)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.tallyCard)
        )
    }

    private var sourceIcon: String {
        guard let source = receipt.source?.lowercased() else { return "doc.fill" }
        if source.contains("email") || source.contains("gmail") { return "envelope.fill" }
        if source.contains("scan") || source.contains("camera") { return "camera.fill" }
        if source.contains("photo") || source.contains("import") { return "photo.fill" }
        if source.contains("share") { return "square.and.arrow.down.fill" }
        return "doc.fill"
    }

    private var sourceColor: Color {
        guard let source = receipt.source?.lowercased() else { return .gray }
        if source.contains("email") || source.contains("gmail") { return .blue }
        if source.contains("scan") || source.contains("camera") { return .orange }
        if source.contains("photo") || source.contains("import") { return .purple }
        if source.contains("share") { return .pink }
        return .gray
    }

    private func formatCurrency(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$\(amount)"
    }

    private func formatDate(_ dateString: String) -> String {
        // Simple date formatting
        if let date = ISO8601DateFormatter().date(from: dateString) {
            let formatter = DateFormatter()
            formatter.dateStyle = .short
            return formatter.string(from: date)
        }
        return dateString
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        return formatter.string(from: date)
    }
}

// MARK: - Confidence Badge

struct ConfidenceBadge: View {
    let confidence: Double

    var body: some View {
        HStack(spacing: 2) {
            Image(systemName: icon)
                .font(.caption2)
            Text("\(Int(confidence * 100))")
                .font(.caption2.bold())
        }
        .foregroundColor(color)
        .padding(.horizontal, 6)
        .padding(.vertical, 3)
        .background(color.opacity(0.2))
        .cornerRadius(6)
    }

    private var icon: String {
        if confidence >= 0.8 { return "checkmark.seal.fill" }
        if confidence >= 0.5 { return "exclamationmark.triangle.fill" }
        return "questionmark.circle.fill"
    }

    private var color: Color {
        if confidence >= 0.8 { return .green }
        if confidence >= 0.5 { return .orange }
        return .red
    }
}

// MARK: - Pulse Animation Modifier

struct PulseAnimation: ViewModifier {
    @State private var isPulsing = false

    func body(content: Content) -> some View {
        content
            .scaleEffect(isPulsing ? 1.05 : 0.95)
            .opacity(isPulsing ? 1 : 0.8)
            .animation(
                .easeInOut(duration: 1)
                .repeatForever(autoreverses: true),
                value: isPulsing
            )
            .onAppear {
                isPulsing = true
            }
    }
}

// MARK: - Receipt Inbox View Model

@MainActor
class ReceiptInboxViewModel: ObservableObject {
    @Published var receipts: [IncomingReceipt] = []
    @Published var rejectedReceipts: [IncomingReceipt] = []
    @Published var filteredReceipts: [IncomingReceipt] = []
    @Published var stats = InboxStatistics()
    @Published var sourceBreakdown: [SourceBreakdownItem] = []
    @Published var isLoading = false
    @Published var isScanning = false
    @Published var currentSource: ReceiptSource = .all

    var matchingRate: Double {
        guard stats.total > 0 else { return 0 }
        return Double(stats.matched) / Double(stats.total)
    }

    struct InboxStatistics {
        var pending: Int = 0
        var matched: Int = 0
        var autoMatched: Int = 0
        var rejected: Int = 0
        var total: Int { pending + matched + rejected }
    }

    struct SourceBreakdownItem: Identifiable {
        let id = UUID()
        let name: String
        let count: Int
        let percentage: CGFloat
        let color: Color
    }

    func loadReceipts() async {
        isLoading = true
        defer { isLoading = false }

        do {
            receipts = try await APIClient.shared.fetchIncomingReceipts(status: "pending")
            // Also load rejected for the count
            rejectedReceipts = try await APIClient.shared.fetchIncomingReceipts(status: "rejected")
            filteredReceipts = receipts
            await loadStats()
            calculateSourceBreakdown()
        } catch {
            print("Failed to load receipts: \(error)")
        }
    }

    func refresh() async {
        await loadReceipts()
    }

    func filterBySource(_ source: ReceiptSource) {
        currentSource = source

        // Handle rejected filter specially
        if source == .rejected {
            filteredReceipts = rejectedReceipts
            return
        }

        if source == .all {
            filteredReceipts = receipts
        } else {
            filteredReceipts = receipts.filter { receipt in
                guard let receiptSource = receipt.source?.lowercased() else { return false }

                switch source {
                case .email: return receiptSource.contains("email") || receiptSource.contains("gmail")
                case .scanned: return receiptSource.contains("scan") || receiptSource.contains("camera")
                case .imported: return receiptSource.contains("photo") || receiptSource.contains("import")
                case .shared: return receiptSource.contains("share")
                case .all, .rejected: return true
                }
            }
        }
    }

    func countForSource(_ source: ReceiptSource) -> Int {
        if source == .all { return receipts.count }
        if source == .rejected { return rejectedReceipts.count }

        return receipts.filter { receipt in
            guard let receiptSource = receipt.source?.lowercased() else { return false }

            switch source {
            case .email: return receiptSource.contains("email") || receiptSource.contains("gmail")
            case .scanned: return receiptSource.contains("scan") || receiptSource.contains("camera")
            case .imported: return receiptSource.contains("photo") || receiptSource.contains("import")
            case .shared: return receiptSource.contains("share")
            case .all, .rejected: return true
            }
        }.count
    }

    func loadStats() async {
        do {
            let apiStats = try await APIClient.shared.fetchInboxStats()
            stats.pending = apiStats.pending
            stats.matched = apiStats.accepted
            stats.rejected = apiStats.rejected
            // Auto-matched would come from a different source
        } catch {
            print("Failed to load stats: \(error)")
        }
    }

    func calculateSourceBreakdown() {
        var sourceCounts: [String: Int] = [:]

        for receipt in receipts {
            let source = categorizeSource(receipt.source)
            sourceCounts[source, default: 0] += 1
        }

        let total = max(receipts.count, 1)

        sourceBreakdown = sourceCounts.map { key, count in
            SourceBreakdownItem(
                name: key,
                count: count,
                percentage: CGFloat(count) / CGFloat(total),
                color: colorForSource(key)
            )
        }.sorted { $0.count > $1.count }
    }

    private func categorizeSource(_ source: String?) -> String {
        guard let s = source?.lowercased() else { return "Other" }
        if s.contains("email") || s.contains("gmail") { return "Email" }
        if s.contains("scan") || s.contains("camera") { return "Scanned" }
        if s.contains("photo") || s.contains("import") { return "Imported" }
        if s.contains("share") { return "Shared" }
        return "Other"
    }

    private func colorForSource(_ source: String) -> Color {
        switch source {
        case "Email": return .blue
        case "Scanned": return .orange
        case "Imported": return .purple
        case "Shared": return .pink
        default: return .gray
        }
    }

    func scanForReceipts() async {
        isScanning = true
        defer { isScanning = false }

        do {
            try await APIClient.shared.triggerGmailScan()
            await refresh()
            HapticService.shared.notification(.success)
        } catch {
            print("Scan failed: \(error)")
            HapticService.shared.notification(.error)
        }
    }

    func runAutoMatch() async {
        isScanning = true
        defer { isScanning = false }

        // Run auto-match for all pending receipts
        for receipt in receipts {
            await autoMatch(receipt)
        }

        await refresh()
    }

    func autoMatch(_ receipt: IncomingReceipt) async {
        do {
            try await APIClient.shared.autoMatchReceipt(id: receipt.id)
        } catch {
            print("Auto-match failed for \(receipt.id): \(error)")
        }
    }

    func quickMatch(_ receipt: IncomingReceipt) async -> Bool {
        do {
            try await APIClient.shared.acceptReceipt(
                id: receipt.id,
                merchant: receipt.merchant,
                amount: receipt.amount,
                date: nil,
                business: "Personal"
            )
            return true
        } catch {
            print("Quick match failed: \(error)")
            return false
        }
    }

    func reject(_ receipt: IncomingReceipt) async {
        do {
            try await APIClient.shared.rejectReceipt(id: receipt.id)
            withAnimation {
                receipts.removeAll { $0.id == receipt.id }
                rejectedReceipts.append(receipt) // Add to rejected list
                filterBySource(currentSource)
            }
            await loadStats()
            HapticService.shared.notification(.success)
        } catch {
            print("Reject failed: \(error)")
            HapticService.shared.notification(.error)
        }
    }

    func unreject(_ receipt: IncomingReceipt) async -> Bool {
        do {
            try await APIClient.shared.unrejectReceipt(id: receipt.id)
            withAnimation {
                rejectedReceipts.removeAll { $0.id == receipt.id }
                receipts.append(receipt) // Add back to pending list
                filterBySource(currentSource)
            }
            await loadStats()
            return true
        } catch {
            print("Unreject failed: \(error)")
            HapticService.shared.notification(.error)
            return false
        }
    }

    func permanentlyDelete(_ receipt: IncomingReceipt) async {
        // This would call a permanent delete API if available
        // For now, just remove from local list
        withAnimation {
            rejectedReceipts.removeAll { $0.id == receipt.id }
            filterBySource(currentSource)
        }
        HapticService.shared.notification(.success)
    }
}

// MARK: - Receipt Matching Sheet

struct ReceiptMatchingSheet: View {
    let receipt: IncomingReceipt
    let onMatched: (String) -> Void
    let onDismiss: () -> Void

    @Environment(\.dismiss) private var dismiss
    @State private var selectedTransaction: Transaction?
    @State private var suggestedTransactions: [Transaction] = []
    @State private var isLoading = true

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Receipt preview
                    receiptPreview

                    // AI-suggested matches
                    if !suggestedTransactions.isEmpty {
                        suggestedMatchesSection
                    }

                    // Manual matching option
                    manualMatchSection
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Match Receipt")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                        onDismiss()
                    }
                }
            }
            .task {
                await loadSuggestedMatches()
            }
        }
    }

    private var receiptPreview: some View {
        VStack(spacing: 12) {
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
                        .frame(height: 150)
                        .cornerRadius(12)
                        .overlay {
                            Image(systemName: "doc.fill")
                                .font(.largeTitle)
                                .foregroundColor(.gray)
                        }
                @unknown default:
                    EmptyView()
                }
            }
            .frame(maxHeight: 200)

            // Extracted data
            HStack(spacing: 16) {
                VStack(alignment: .leading) {
                    Text(receipt.merchant ?? "Unknown Merchant")
                        .font(.headline)
                        .foregroundColor(.white)
                    if let amount = receipt.amount {
                        Text("$\(String(format: "%.2f", amount))")
                            .font(.title2.bold())
                            .foregroundColor(.tallyAccent)
                    }
                }
                Spacer()
                if let confidence = receipt.confidenceScore {
                    ConfidenceBadge(confidence: confidence)
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    private var suggestedMatchesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "sparkles")
                    .foregroundColor(.purple)
                Text("Suggested Matches")
                    .font(.headline)
                    .foregroundColor(.white)
            }

            ForEach(suggestedTransactions.prefix(5)) { transaction in
                SuggestedMatchCard(
                    transaction: transaction,
                    isSelected: selectedTransaction?.index == transaction.index
                ) {
                    selectedTransaction = transaction
                    matchToTransaction(transaction)
                }
            }
        }
    }

    private var manualMatchSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Or search for a transaction...")
                .font(.subheadline)
                .foregroundColor(.gray)

            NavigationLink {
                TransactionSearchView { transaction in
                    matchToTransaction(transaction)
                }
            } label: {
                HStack {
                    Image(systemName: "magnifyingglass")
                    Text("Search Transactions")
                    Spacer()
                    Image(systemName: "chevron.right")
                }
                .foregroundColor(.white)
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(12)
            }
        }
    }

    private func loadSuggestedMatches() async {
        isLoading = true
        defer { isLoading = false }

        // In production, this would call an API to get AI-suggested matches
        // For now, we'll simulate with recent transactions
        do {
            let transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: 10,
                business: nil
            )
            suggestedTransactions = transactions.filter { !$0.hasReceipt }
        } catch {
            print("Failed to load suggestions: \(error)")
        }
    }

    private func matchToTransaction(_ transaction: Transaction) {
        Task {
            do {
                try await APIClient.shared.acceptReceipt(
                    id: receipt.id,
                    merchant: receipt.merchant,
                    amount: receipt.amount,
                    date: nil,
                    business: transaction.business
                )

                // Also link to specific transaction
                _ = try await APIClient.shared.linkReceiptToTransaction(
                    transactionIndex: transaction.index,
                    receiptId: receipt.id
                )

                dismiss()
                onMatched(transaction.merchant)
            } catch {
                print("Match failed: \(error)")
            }
        }
    }
}

// MARK: - Suggested Match Card

struct SuggestedMatchCard: View {
    let transaction: Transaction
    let isSelected: Bool
    let onSelect: () -> Void

    var body: some View {
        Button(action: onSelect) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(transaction.merchant)
                        .font(.subheadline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Text(transaction.formattedDate)
                        .font(.caption)
                        .foregroundColor(.gray)
                }

                Spacer()

                Text(transaction.formattedAmount)
                    .font(.headline)
                    .foregroundColor(.tallyAccent)

                Image(systemName: isSelected ? "checkmark.circle.fill" : "circle")
                    .foregroundColor(isSelected ? .green : .gray)
            }
            .padding()
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.tallyCard)
                    .overlay(
                        RoundedRectangle(cornerRadius: 12)
                            .stroke(isSelected ? Color.green : Color.clear, lineWidth: 2)
                    )
            )
        }
        .buttonStyle(.plain)
    }
}

// MARK: - Transaction Search View

struct TransactionSearchView: View {
    let onSelect: (Transaction) -> Void

    @State private var searchText = ""
    @State private var transactions: [Transaction] = []

    var body: some View {
        List(filteredTransactions) { transaction in
            Button {
                onSelect(transaction)
            } label: {
                HStack {
                    VStack(alignment: .leading) {
                        Text(transaction.merchant)
                            .foregroundColor(.white)
                        Text(transaction.formattedDate)
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                    Spacer()
                    Text(transaction.formattedAmount)
                        .foregroundColor(.tallyAccent)
                }
            }
            .listRowBackground(Color.tallyCard)
        }
        .listStyle(.plain)
        .searchable(text: $searchText, prompt: "Search by merchant or amount")
        .navigationTitle("Find Transaction")
        .task {
            await loadTransactions()
        }
    }

    private var filteredTransactions: [Transaction] {
        if searchText.isEmpty { return transactions }
        return transactions.filter {
            $0.merchant.localizedCaseInsensitiveContains(searchText) ||
            $0.formattedAmount.contains(searchText)
        }
    }

    private func loadTransactions() async {
        do {
            transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: 100,
                business: nil
            )
        } catch {
            print("Failed to load transactions: \(error)")
        }
    }
}

#Preview {
    ReceiptInboxView()
        .preferredColorScheme(.dark)
}

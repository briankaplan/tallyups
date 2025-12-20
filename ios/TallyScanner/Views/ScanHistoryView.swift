import SwiftUI

struct ScanHistoryView: View {
    @StateObject private var historyService = ScanHistoryService.shared
    @State private var selectedFilter = "all"
    @State private var showingClearConfirm = false
    @State private var clearType = ClearType.all

    enum ClearType {
        case all, completed, failed
    }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Stats Header
                    statsHeader

                    // Filter Picker
                    filterPicker

                    // History List
                    if filteredHistory.isEmpty {
                        emptyView
                    } else {
                        historyList
                    }
                }
            }
            .navigationTitle("Scan History")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(role: .destructive) {
                            clearType = .all
                            showingClearConfirm = true
                        } label: {
                            Label("Clear All History", systemImage: "trash")
                        }

                        Button {
                            clearType = .completed
                            showingClearConfirm = true
                        } label: {
                            Label("Clear Completed", systemImage: "checkmark.circle")
                        }

                        Button {
                            clearType = .failed
                            showingClearConfirm = true
                        } label: {
                            Label("Clear Failed", systemImage: "xmark.circle")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                    .disabled(historyService.history.isEmpty)
                }
            }
            .alert("Clear History", isPresented: $showingClearConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Clear", role: .destructive) {
                    performClear()
                }
            } message: {
                Text(clearMessage)
            }
        }
    }

    // MARK: - Stats Header

    private var statsHeader: some View {
        HStack(spacing: 20) {
            StatColumn(
                value: "\(historyService.totalScansToday)",
                label: "Today",
                color: .tallyAccent
            )

            Divider()
                .frame(height: 40)

            StatColumn(
                value: "\(historyService.totalScansThisWeek)",
                label: "This Week",
                color: .blue
            )

            Divider()
                .frame(height: 40)

            StatColumn(
                value: formatCurrency(historyService.totalAmountToday),
                label: "Today's Total",
                color: .green
            )
        }
        .padding()
        .background(Color.tallyCard)
    }

    // MARK: - Filter Picker

    private var filterPicker: some View {
        Picker("Filter", selection: $selectedFilter) {
            Text("All (\(historyService.history.count))").tag("all")
            Text("Pending (\(historyService.pendingCount))").tag("pending")
            Text("Completed (\(historyService.completedScans.count))").tag("completed")
            Text("Failed (\(historyService.failedCount))").tag("failed")
        }
        .pickerStyle(.segmented)
        .padding()
    }

    // MARK: - History List

    private var historyList: some View {
        List {
            ForEach(filteredHistory) { item in
                HistoryItemRow(item: item)
            }
            .onDelete { indexSet in
                for index in indexSet {
                    let item = filteredHistory[index]
                    historyService.deleteScan(id: item.id)
                }
            }
        }
        .listStyle(.plain)
    }

    // MARK: - Empty View

    private var emptyView: some View {
        VStack(spacing: 16) {
            Image(systemName: "clock.arrow.circlepath")
                .font(.system(size: 60))
                .foregroundColor(.gray)
            Text("No scan history")
                .font(.headline)
                .foregroundColor(.white)
            Text("Your scanned receipts will appear here")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    // MARK: - Helpers

    private var filteredHistory: [ScanHistoryItem] {
        switch selectedFilter {
        case "pending": return historyService.pendingScans
        case "completed": return historyService.completedScans
        case "failed": return historyService.failedScans
        default: return historyService.history
        }
    }

    private var clearMessage: String {
        switch clearType {
        case .all: return "This will remove all scan history. This cannot be undone."
        case .completed: return "This will remove all completed scans from history."
        case .failed: return "This will remove all failed scans from history."
        }
    }

    private func performClear() {
        switch clearType {
        case .all: historyService.clearHistory()
        case .completed: historyService.clearCompletedScans()
        case .failed: historyService.clearFailedScans()
        }
    }

    private func formatCurrency(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: value)) ?? "$\(value)"
    }
}

// MARK: - Stat Column

struct StatColumn: View {
    let value: String
    let label: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.title2.bold())
                .foregroundColor(color)
            Text(label)
                .font(.caption)
                .foregroundColor(.gray)
        }
    }
}

// MARK: - History Item Row

struct HistoryItemRow: View {
    let item: ScanHistoryItem

    var body: some View {
        HStack(spacing: 12) {
            // Status Icon
            statusIcon

            // Details
            VStack(alignment: .leading, spacing: 4) {
                Text(item.merchant ?? "Unknown Merchant")
                    .font(.headline)
                    .foregroundColor(.white)

                HStack {
                    if let amount = item.amount {
                        Text(item.formattedAmount)
                            .font(.subheadline)
                            .foregroundColor(.tallyAccent)
                    }

                    Text(formattedTime)
                        .font(.caption)
                        .foregroundColor(.gray)
                }
            }

            Spacer()

            // R2 indicator
            if item.r2Url != nil {
                Image(systemName: "cloud.fill")
                    .foregroundColor(.blue)
                    .font(.caption)
            }
        }
        .padding(.vertical, 4)
    }

    private var statusIcon: some View {
        ZStack {
            Circle()
                .fill(statusColor.opacity(0.2))
                .frame(width: 40, height: 40)

            Image(systemName: item.status.icon)
                .foregroundColor(statusColor)
        }
    }

    private var statusColor: Color {
        switch item.status {
        case .pending: return .orange
        case .uploading: return .blue
        case .uploaded: return .green
        case .failed: return .red
        }
    }

    private var formattedTime: String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: item.scannedAt, relativeTo: Date())
    }
}

#Preview {
    ScanHistoryView()
}

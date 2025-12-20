import SwiftUI

struct LibraryView: View {
    @StateObject private var viewModel = LibraryViewModel()
    @State private var searchText = ""
    @State private var selectedReceipt: Receipt?
    @State private var showingFilters = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Stats Bar
                    statsBar

                    // Search
                    searchBar

                    // Receipt List
                    if viewModel.isLoading && viewModel.receipts.isEmpty {
                        loadingView
                    } else if viewModel.receipts.isEmpty {
                        emptyView
                    } else {
                        receiptList
                    }
                }
            }
            .navigationTitle("Receipt Library")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { showingFilters = true }) {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { Task { await viewModel.refresh() } }) {
                        Image(systemName: "arrow.clockwise")
                    }
                }
            }
            .refreshable {
                await viewModel.refresh()
            }
            .sheet(item: $selectedReceipt) { receipt in
                ReceiptDetailView(receipt: receipt)
            }
            .sheet(isPresented: $showingFilters) {
                FilterView(viewModel: viewModel)
            }
            .task {
                await viewModel.loadReceipts()
            }
            .onChange(of: searchText) { oldValue, newValue in
                viewModel.searchQuery = newValue
                Task {
                    await viewModel.search()
                }
            }
        }
    }

    // MARK: - Stats Bar

    private var statsBar: some View {
        ScrollView(.horizontal, showsIndicators: false) {
            HStack(spacing: 16) {
                StatPill(
                    title: "Total",
                    value: "\(viewModel.stats?.totalReceipts ?? 0)",
                    color: .tallyAccent
                )
                StatPill(
                    title: "Matched",
                    value: "\(viewModel.stats?.matchedReceipts ?? 0)",
                    color: .green
                )
                StatPill(
                    title: "Unmatched",
                    value: "\(viewModel.stats?.unmatchedReceipts ?? 0)",
                    color: .orange
                )
                StatPill(
                    title: "Total Amount",
                    value: formatCurrency(viewModel.stats?.totalAmount ?? 0),
                    color: .blue
                )
            }
            .padding(.horizontal)
            .padding(.vertical, 12)
        }
        .background(Color.tallyCard)
    }

    // MARK: - Search Bar

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass")
                .foregroundColor(.gray)
            TextField("Search receipts...", text: $searchText)
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
        .padding()
    }

    // MARK: - Receipt List

    private var receiptList: some View {
        ScrollView {
            LazyVStack(spacing: 12) {
                ForEach(viewModel.receipts) { receipt in
                    ReceiptCardView(receipt: receipt)
                        .onTapGesture {
                            selectedReceipt = receipt
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
            Text("Loading receipts...")
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
    }

    private var emptyView: some View {
        VStack(spacing: 16) {
            Image(systemName: "doc.text.magnifyingglass")
                .font(.system(size: 60))
                .foregroundColor(.gray)
            Text("No receipts found")
                .font(.headline)
                .foregroundColor(.white)
            Text("Scan a receipt to get started")
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

// MARK: - Stat Pill

struct StatPill: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.headline)
                .foregroundColor(.white)
            Text(title)
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(color.opacity(0.2))
        .cornerRadius(20)
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(color.opacity(0.5), lineWidth: 1)
        )
    }
}

// MARK: - Filter View

struct FilterView: View {
    @ObservedObject var viewModel: LibraryViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var status = "all"
    @State private var business = "all"
    @State private var startDate = Date().addingTimeInterval(-30 * 24 * 60 * 60)
    @State private var endDate = Date()
    @State private var useDateFilter = false

    var body: some View {
        NavigationStack {
            Form {
                Section("Status") {
                    Picker("Status", selection: $status) {
                        Text("All").tag("all")
                        Text("Matched").tag("matched")
                        Text("Unmatched").tag("unmatched")
                        Text("Pending").tag("pending")
                    }
                    .pickerStyle(.segmented)
                }

                Section("Business") {
                    Picker("Business", selection: $business) {
                        Text("All").tag("all")
                        Text("Personal").tag("personal")
                        Text("Down Home").tag("downhome")
                        Text("MCR").tag("mcr")
                    }
                    .pickerStyle(.segmented)
                }

                Section("Date Range") {
                    Toggle("Filter by date", isOn: $useDateFilter)

                    if useDateFilter {
                        DatePicker("Start", selection: $startDate, displayedComponents: .date)
                        DatePicker("End", selection: $endDate, displayedComponents: .date)
                    }
                }
            }
            .navigationTitle("Filters")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Reset") {
                        status = "all"
                        business = "all"
                        useDateFilter = false
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Apply") {
                        applyFilters()
                        dismiss()
                    }
                    .bold()
                }
            }
        }
    }

    private func applyFilters() {
        viewModel.filterStatus = status
        viewModel.filterBusiness = business
        if useDateFilter {
            viewModel.filterStartDate = startDate
            viewModel.filterEndDate = endDate
        } else {
            viewModel.filterStartDate = nil
            viewModel.filterEndDate = nil
        }
        Task {
            await viewModel.refresh()
        }
    }
}

#Preview {
    LibraryView()
}

import SwiftUI

struct LibraryView: View {
    @StateObject private var viewModel = LibraryViewModel()
    @State private var searchText = ""
    @State private var selectedReceipt: Receipt?
    @State private var showingFilters = false
    @State private var showingScanHistory = false
    @State private var selectedTab = 0

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 0) {
                    // Segmented Control for Receipts / Scan History
                    Picker("View", selection: $selectedTab) {
                        Text("Receipts").tag(0)
                        Text("Scan History").tag(1)
                    }
                    .pickerStyle(.segmented)
                    .padding(.horizontal)
                    .padding(.top, 8)
                    .accessibilityLabel("Library view selector")
                    .accessibilityHint("Switch between receipts and scan history")

                    if selectedTab == 0 {
                        // Receipts Tab
                        VStack(spacing: 0) {
                            // Stats Bar
                            statsBar

                            // Search
                            searchBar

                            // Receipt List
                            if viewModel.isLoading {
                                loadingView
                            } else if viewModel.receipts.isEmpty && viewModel.hasLoaded {
                                emptyView
                                    .transition(.opacity.animation(.easeIn(duration: 0.3)))
                            } else {
                                receiptList
                            }
                        }
                    } else {
                        // Scan History Tab
                        ScanHistoryView()
                    }
                }
            }
            .navigationTitle("Library")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { showingFilters = true }) {
                        Image(systemName: "line.3.horizontal.decrease.circle")
                    }
                    .accessibilityLabel("Filter receipts")
                    .accessibilityHint("Opens filter options for status, business type, and date range")
                }
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { Task { await viewModel.refresh() } }) {
                        Image(systemName: "arrow.clockwise")
                    }
                    .accessibilityLabel("Refresh")
                    .accessibilityHint("Reloads receipt list from server")
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
                LibraryStatPill(
                    title: "Total",
                    value: "\(viewModel.stats?.totalReceipts ?? 0)",
                    color: .tallyAccent
                )
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Total receipts: \(viewModel.stats?.totalReceipts ?? 0)")

                LibraryStatPill(
                    title: "Matched",
                    value: "\(viewModel.stats?.matchedReceipts ?? 0)",
                    color: .green
                )
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Matched receipts: \(viewModel.stats?.matchedReceipts ?? 0)")

                LibraryStatPill(
                    title: "Unmatched",
                    value: "\(viewModel.stats?.unmatchedReceipts ?? 0)",
                    color: .orange
                )
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Unmatched receipts: \(viewModel.stats?.unmatchedReceipts ?? 0)")

                LibraryStatPill(
                    title: "Total Amount",
                    value: formatCurrency(viewModel.stats?.totalAmount ?? 0),
                    color: .blue
                )
                .accessibilityElement(children: .combine)
                .accessibilityLabel("Total amount: \(formatCurrency(viewModel.stats?.totalAmount ?? 0))")
            }
            .padding(.horizontal)
            .padding(.vertical, 12)
        }
        .background(Color.tallyCard)
        .accessibilityElement(children: .contain)
        .accessibilityLabel("Receipt statistics")
    }

    // MARK: - Search Bar

    private var searchBar: some View {
        HStack {
            Image(systemName: "magnifyingglass")
                .foregroundColor(.gray)
                .accessibilityHidden(true)
            TextField("Search receipts...", text: $searchText)
                .textFieldStyle(.plain)
                .accessibilityLabel("Search receipts")
                .accessibilityHint("Enter merchant name, amount, or date to search")
            if !searchText.isEmpty {
                Button(action: { searchText = "" }) {
                    Image(systemName: "xmark.circle.fill")
                        .foregroundColor(.gray)
                }
                .accessibilityLabel("Clear search")
                .accessibilityHint("Clears the current search text")
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
                .font(.system(size: 44))
                .foregroundColor(.gray.opacity(0.6))
                .accessibilityHidden(true)
            Text("No receipts found")
                .font(.headline)
                .foregroundColor(.white)
            Text("Scan a receipt to get started")
                .font(.subheadline)
                .foregroundColor(.gray)
        }
        .frame(maxHeight: .infinity)
        .accessibilityElement(children: .combine)
        .accessibilityLabel("No receipts found. Scan a receipt to get started.")
    }

    private func formatCurrency(_ value: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: value)) ?? "$\(value)"
    }
}

// MARK: - Library Stat Pill

private struct LibraryStatPill: View {
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
    @ObservedObject private var businessTypeService = BusinessTypeService.shared
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
                    if businessTypeService.isLoading {
                        HStack {
                            Text("Loading...")
                                .foregroundColor(.gray)
                            Spacer()
                            ProgressView()
                        }
                    } else {
                        Picker("Business", selection: $business) {
                            Text("All").tag("all")
                            ForEach(businessTypeService.businessTypes) { type in
                                HStack {
                                    Image(systemName: type.icon)
                                        .foregroundColor(type.swiftUIColor)
                                    Text(type.displayName)
                                }
                                .tag(type.name)
                            }
                        }
                        .pickerStyle(.menu)
                    }
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
            .task {
                await businessTypeService.loadIfNeeded()
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

import SwiftUI

/// View for generating and viewing expense reports
struct ReportsView: View {
    @StateObject private var viewModel = ReportsViewModel()
    @ObservedObject private var businessTypeService = BusinessTypeService.shared

    @State private var selectedReportType: ReportType = .monthly
    @State private var selectedBusiness: String? = nil
    @State private var startDate = Calendar.current.date(byAdding: .month, value: -1, to: Date())!
    @State private var endDate = Date()
    @State private var showingExportSheet = false
    @State private var showingFilterSheet = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                if viewModel.isLoading {
                    ProgressView("Loading reports...")
                        .progressViewStyle(CircularProgressViewStyle(tint: .tallyAccent))
                } else {
                    ScrollView {
                        VStack(spacing: 24) {
                            // Report Type Picker
                            reportTypePicker

                            // Date Range
                            dateRangeSection

                            // Business Filter
                            businessFilterSection

                            // Summary Cards
                            summarySection

                            // Charts
                            if !viewModel.categoryBreakdown.isEmpty {
                                categoryChartSection
                            }

                            // Recent Reports
                            recentReportsSection
                        }
                        .padding()
                    }
                }
            }
            .navigationTitle("Reports")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button(action: { showingExportSheet = true }) {
                            Label("Export Report", systemImage: "square.and.arrow.up")
                        }

                        Button(action: { Task { await viewModel.generateReport(type: selectedReportType, business: selectedBusiness, startDate: startDate, endDate: endDate) } }) {
                            Label("Refresh", systemImage: "arrow.clockwise")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .sheet(isPresented: $showingExportSheet) {
                ExportReportSheet(
                    reportType: selectedReportType,
                    business: selectedBusiness,
                    startDate: startDate,
                    endDate: endDate
                )
            }
            .task {
                await businessTypeService.loadIfNeeded()
                await viewModel.generateReport(type: selectedReportType, business: selectedBusiness, startDate: startDate, endDate: endDate)
            }
            .onChange(of: selectedReportType) { _, _ in
                updateDateRange()
                Task { await viewModel.generateReport(type: selectedReportType, business: selectedBusiness, startDate: startDate, endDate: endDate) }
            }
            .onChange(of: selectedBusiness) { _, _ in
                Task { await viewModel.generateReport(type: selectedReportType, business: selectedBusiness, startDate: startDate, endDate: endDate) }
            }
        }
    }

    // MARK: - Report Type Picker

    private var reportTypePicker: some View {
        Picker("Report Type", selection: $selectedReportType) {
            ForEach(ReportType.allCases, id: \.self) { type in
                Text(type.displayName).tag(type)
            }
        }
        .pickerStyle(.segmented)
    }

    // MARK: - Date Range Section

    private var dateRangeSection: some View {
        VStack(spacing: 12) {
            HStack {
                Text("Date Range")
                    .font(.headline)
                Spacer()
                Text(dateRangeText)
                    .font(.subheadline)
                    .foregroundColor(.gray)
            }

            HStack(spacing: 16) {
                VStack(alignment: .leading) {
                    Text("From")
                        .font(.caption)
                        .foregroundColor(.gray)
                    DatePicker("", selection: $startDate, displayedComponents: .date)
                        .labelsHidden()
                }

                VStack(alignment: .leading) {
                    Text("To")
                        .font(.caption)
                        .foregroundColor(.gray)
                    DatePicker("", selection: $endDate, displayedComponents: .date)
                        .labelsHidden()
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    private var dateRangeText: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .short
        return "\(formatter.string(from: startDate)) - \(formatter.string(from: endDate))"
    }

    // MARK: - Business Filter Section

    private var businessFilterSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Business")
                .font(.headline)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ReportFilterChip(
                        title: "All",
                        isSelected: selectedBusiness == nil,
                        action: { selectedBusiness = nil }
                    )

                    ForEach(businessTypeService.businessTypes) { type in
                        ReportFilterChip(
                            title: type.displayName,
                            icon: type.icon,
                            color: type.swiftUIColor,
                            isSelected: selectedBusiness == type.name,
                            action: { selectedBusiness = type.name }
                        )
                    }
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Summary Section

    private var summarySection: some View {
        VStack(spacing: 16) {
            HStack {
                Text("Summary")
                    .font(.headline)
                Spacer()
            }

            LazyVGrid(columns: [
                GridItem(.flexible()),
                GridItem(.flexible())
            ], spacing: 16) {
                ReportSummaryCard(
                    title: "Total Spent",
                    value: viewModel.formattedTotalSpent,
                    icon: "dollarsign.circle.fill",
                    color: .tallyAccent
                )

                ReportSummaryCard(
                    title: "Transactions",
                    value: "\(viewModel.transactionCount)",
                    icon: "creditcard.fill",
                    color: .blue
                )

                ReportSummaryCard(
                    title: "Receipts",
                    value: "\(viewModel.receiptCount)",
                    icon: "doc.fill",
                    color: .green
                )

                ReportSummaryCard(
                    title: "Avg per Day",
                    value: viewModel.formattedDailyAverage,
                    icon: "chart.line.uptrend.xyaxis",
                    color: .orange
                )
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Category Chart Section

    private var categoryChartSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("By Category")
                .font(.headline)

            ForEach(viewModel.categoryBreakdown.prefix(5), id: \.category) { item in
                CategoryBar(
                    category: item.category,
                    amount: item.amount,
                    percentage: item.percentage,
                    color: categoryColor(for: item.category)
                )
            }

            if viewModel.categoryBreakdown.count > 5 {
                NavigationLink {
                    AllCategoriesView(categories: viewModel.categoryBreakdown)
                } label: {
                    Text("View all \(viewModel.categoryBreakdown.count) categories")
                        .font(.subheadline)
                        .foregroundColor(.tallyAccent)
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Recent Reports Section

    private var recentReportsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Quick Reports")
                .font(.headline)

            VStack(spacing: 12) {
                QuickReportRow(
                    title: "This Month",
                    subtitle: currentMonthRange,
                    icon: "calendar",
                    action: {
                        selectedReportType = .monthly
                        setToCurrentMonth()
                    }
                )

                QuickReportRow(
                    title: "Last 30 Days",
                    subtitle: "Rolling period",
                    icon: "clock",
                    action: {
                        selectedReportType = .custom
                        startDate = Calendar.current.date(byAdding: .day, value: -30, to: Date())!
                        endDate = Date()
                    }
                )

                QuickReportRow(
                    title: "This Quarter",
                    subtitle: currentQuarterRange,
                    icon: "chart.bar.fill",
                    action: {
                        selectedReportType = .quarterly
                        setToCurrentQuarter()
                    }
                )

                QuickReportRow(
                    title: "Year to Date",
                    subtitle: "\(Calendar.current.component(.year, from: Date()))",
                    icon: "calendar.badge.clock",
                    action: {
                        selectedReportType = .yearly
                        setToYearToDate()
                    }
                )
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Helpers

    private func updateDateRange() {
        switch selectedReportType {
        case .weekly:
            startDate = Calendar.current.date(byAdding: .day, value: -7, to: Date())!
            endDate = Date()
        case .monthly:
            setToCurrentMonth()
        case .quarterly:
            setToCurrentQuarter()
        case .yearly:
            setToYearToDate()
        case .custom:
            break
        }
    }

    private func setToCurrentMonth() {
        let calendar = Calendar.current
        let components = calendar.dateComponents([.year, .month], from: Date())
        startDate = calendar.date(from: components)!
        endDate = Date()
    }

    private func setToCurrentQuarter() {
        let calendar = Calendar.current
        let month = calendar.component(.month, from: Date())
        let quarterStartMonth = ((month - 1) / 3) * 3 + 1
        var components = calendar.dateComponents([.year], from: Date())
        components.month = quarterStartMonth
        components.day = 1
        startDate = calendar.date(from: components)!
        endDate = Date()
    }

    private func setToYearToDate() {
        let calendar = Calendar.current
        var components = calendar.dateComponents([.year], from: Date())
        components.month = 1
        components.day = 1
        startDate = calendar.date(from: components)!
        endDate = Date()
    }

    private var currentMonthRange: String {
        let formatter = DateFormatter()
        formatter.dateFormat = "MMMM yyyy"
        return formatter.string(from: Date())
    }

    private var currentQuarterRange: String {
        let month = Calendar.current.component(.month, from: Date())
        let quarter = (month - 1) / 3 + 1
        return "Q\(quarter) \(Calendar.current.component(.year, from: Date()))"
    }

    private func categoryColor(for category: String) -> Color {
        switch category.lowercased() {
        case "food & dining": return .orange
        case "transportation": return .blue
        case "shopping": return .purple
        case "entertainment": return .pink
        case "travel": return .cyan
        case "subscription": return .indigo
        case "utilities": return .yellow
        case "business": return .green
        default: return .gray
        }
    }
}

// MARK: - Report Type

enum ReportType: String, CaseIterable {
    case weekly, monthly, quarterly, yearly, custom

    var displayName: String {
        switch self {
        case .weekly: return "Week"
        case .monthly: return "Month"
        case .quarterly: return "Quarter"
        case .yearly: return "Year"
        case .custom: return "Custom"
        }
    }
}

// MARK: - Reports View Model

@MainActor
class ReportsViewModel: ObservableObject {
    @Published var isLoading = false
    @Published var totalSpent: Double = 0
    @Published var transactionCount: Int = 0
    @Published var receiptCount: Int = 0
    @Published var dailyAverage: Double = 0
    @Published var categoryBreakdown: [CategoryAmount] = []

    struct CategoryAmount {
        let category: String
        let amount: Double
        let percentage: Double
    }

    var formattedTotalSpent: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: totalSpent)) ?? "$0.00"
    }

    var formattedDailyAverage: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: dailyAverage)) ?? "$0.00"
    }

    func generateReport(type: ReportType, business: String?, startDate: Date, endDate: Date) async {
        isLoading = true

        do {
            let report = try await APIClient.shared.fetchExpenseReport(
                startDate: startDate,
                endDate: endDate,
                businessType: business
            )

            totalSpent = report.totalSpent
            transactionCount = report.transactionCount
            receiptCount = report.receiptCount

            let days = max(1, Calendar.current.dateComponents([.day], from: startDate, to: endDate).day ?? 1)
            dailyAverage = totalSpent / Double(days)

            categoryBreakdown = report.categories.map { cat in
                CategoryAmount(
                    category: cat.name,
                    amount: cat.amount,
                    percentage: totalSpent > 0 ? (cat.amount / totalSpent) * 100 : 0
                )
            }.sorted { $0.amount > $1.amount }

        } catch {
            print("Failed to generate report: \(error)")
            // Set some defaults on error
            totalSpent = 0
            transactionCount = 0
            receiptCount = 0
            dailyAverage = 0
            categoryBreakdown = []
        }

        isLoading = false
    }
}

// MARK: - Supporting Views

private struct ReportFilterChip: View {
    let title: String
    var icon: String? = nil
    var color: Color = .tallyAccent
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 6) {
                if let icon = icon {
                    Image(systemName: icon)
                        .font(.caption)
                }
                Text(title)
                    .font(.subheadline)
            }
            .padding(.horizontal, 16)
            .padding(.vertical, 8)
            .background(isSelected ? color.opacity(0.3) : Color.white.opacity(0.1))
            .foregroundColor(isSelected ? color : .gray)
            .cornerRadius(20)
            .overlay(
                RoundedRectangle(cornerRadius: 20)
                    .strokeBorder(isSelected ? color : Color.clear, lineWidth: 1)
            )
        }
    }
}

private struct ReportSummaryCard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(spacing: 12) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                Spacer()
            }

            VStack(alignment: .leading, spacing: 4) {
                Text(value)
                    .font(.title2.bold())
                    .foregroundColor(.white)

                Text(title)
                    .font(.caption)
                    .foregroundColor(.gray)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
        }
        .padding()
        .background(Color.white.opacity(0.05))
        .cornerRadius(12)
    }
}

private struct CategoryBar: View {
    let category: String
    let amount: Double
    let percentage: Double
    let color: Color

    var body: some View {
        VStack(spacing: 8) {
            HStack {
                Text(category)
                    .font(.subheadline)
                    .foregroundColor(.white)

                Spacer()

                Text(formattedAmount)
                    .font(.subheadline.bold())
                    .foregroundColor(.white)

                Text("(\(Int(percentage))%)")
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            GeometryReader { geometry in
                ZStack(alignment: .leading) {
                    Rectangle()
                        .fill(Color.white.opacity(0.1))
                        .frame(height: 8)
                        .cornerRadius(4)

                    Rectangle()
                        .fill(color)
                        .frame(width: geometry.size.width * CGFloat(percentage / 100), height: 8)
                        .cornerRadius(4)
                }
            }
            .frame(height: 8)
        }
    }

    private var formattedAmount: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$0"
    }
}

private struct QuickReportRow: View {
    let title: String
    let subtitle: String
    let icon: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            HStack(spacing: 16) {
                Image(systemName: icon)
                    .font(.title2)
                    .foregroundColor(.tallyAccent)
                    .frame(width: 32)

                VStack(alignment: .leading, spacing: 2) {
                    Text(title)
                        .font(.subheadline.weight(.medium))
                        .foregroundColor(.white)

                    Text(subtitle)
                        .font(.caption)
                        .foregroundColor(.gray)
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.caption)
                    .foregroundColor(.gray)
            }
            .padding(.vertical, 8)
        }
    }
}

// MARK: - All Categories View

struct AllCategoriesView: View {
    let categories: [ReportsViewModel.CategoryAmount]

    var body: some View {
        List {
            ForEach(categories, id: \.category) { item in
                HStack {
                    Text(item.category)
                        .foregroundColor(.white)

                    Spacer()

                    VStack(alignment: .trailing) {
                        Text(formattedAmount(item.amount))
                            .font(.subheadline.bold())

                        Text("\(Int(item.percentage))%")
                            .font(.caption)
                            .foregroundColor(.gray)
                    }
                }
                .listRowBackground(Color.tallyCard)
            }
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
        .background(Color.tallyBackground)
        .navigationTitle("All Categories")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func formattedAmount(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: amount)) ?? "$0"
    }
}

// MARK: - Export Report Sheet

struct ExportReportSheet: View {
    @Environment(\.dismiss) private var dismiss

    let reportType: ReportType
    let business: String?
    let startDate: Date
    let endDate: Date

    @State private var exportFormat: ExportFormat = .pdf
    @State private var includeReceipts = true
    @State private var isExporting = false
    @State private var exportSuccess = false

    enum ExportFormat: String, CaseIterable {
        case pdf = "PDF"
        case csv = "CSV"
        case excel = "Excel"
    }

    var body: some View {
        NavigationStack {
            Form {
                Section("Format") {
                    Picker("Export Format", selection: $exportFormat) {
                        ForEach(ExportFormat.allCases, id: \.self) { format in
                            Text(format.rawValue).tag(format)
                        }
                    }
                    .pickerStyle(.segmented)
                }

                Section("Options") {
                    Toggle("Include Receipt Images", isOn: $includeReceipts)
                }

                Section {
                    HStack {
                        Text("Date Range")
                        Spacer()
                        Text(dateRangeText)
                            .foregroundColor(.gray)
                    }

                    if let business = business {
                        HStack {
                            Text("Business")
                            Spacer()
                            Text(business)
                                .foregroundColor(.gray)
                        }
                    }
                }

                Section {
                    Button(action: exportReport) {
                        HStack {
                            Spacer()
                            if isExporting {
                                ProgressView()
                            } else if exportSuccess {
                                Label("Exported!", systemImage: "checkmark.circle.fill")
                                    .foregroundColor(.green)
                            } else {
                                Label("Export Report", systemImage: "square.and.arrow.up")
                            }
                            Spacer()
                        }
                    }
                    .disabled(isExporting)
                }
            }
            .navigationTitle("Export Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private var dateRangeText: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium
        return "\(formatter.string(from: startDate)) - \(formatter.string(from: endDate))"
    }

    private func exportReport() {
        isExporting = true

        Task {
            do {
                _ = try await APIClient.shared.exportReport(
                    startDate: startDate,
                    endDate: endDate,
                    businessType: business,
                    format: exportFormat.rawValue.lowercased()
                )

                await MainActor.run {
                    exportSuccess = true
                    isExporting = false

                    DispatchQueue.main.asyncAfter(deadline: .now() + 1.5) {
                        dismiss()
                    }
                }
            } catch {
                print("Export failed: \(error)")
                isExporting = false
            }
        }
    }
}

#Preview {
    ReportsView()
}

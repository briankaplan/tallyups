import SwiftUI
import PDFKit
import UniformTypeIdentifiers

// MARK: - Expense Report Exporter

struct ExpenseReportExporter: View {
    @Environment(\.dismiss) private var dismiss
    @StateObject private var viewModel = ExpenseReportViewModel()

    @State private var selectedFormat: ExportFormat = .pdf
    @State private var selectedDateRange: DateRangeOption = .thisMonth
    @State private var customStartDate = Date()
    @State private var customEndDate = Date()
    @State private var selectedBusinessTypes: Set<String> = ["Personal", "Business"]
    @State private var selectedCategories: Set<String> = []
    @State private var includeReceipts = true
    @State private var includeCharts = true
    @State private var includeSummary = true
    @State private var showShareSheet = false
    @State private var exportedFileURL: URL?
    @State private var isExporting = false
    @State private var exportProgress: Double = 0

    let allBusinessTypes = ["Personal", "Business", "Business", "Secondary"]
    let allCategories = ["Food & Dining", "Transportation", "Shopping", "Entertainment", "Travel", "Business", "Subscription", "Utilities", "Other"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Preview Card
                    reportPreviewCard

                    // Format Selection
                    formatSelectionSection

                    // Date Range
                    dateRangeSection

                    // Business Type Filter
                    businessTypeSection

                    // Category Filter
                    categorySection

                    // Include Options
                    includeOptionsSection

                    // Export Button
                    exportButton
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Export Report")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
            .sheet(isPresented: $showShareSheet) {
                if let url = exportedFileURL {
                    ShareSheet(items: [url])
                }
            }
            .task {
                await viewModel.loadPreviewData(
                    dateRange: dateRangeForSelection,
                    businessTypes: Array(selectedBusinessTypes)
                )
            }
        }
    }

    // MARK: - Preview Card

    private var reportPreviewCard: some View {
        VStack(spacing: 16) {
            // Header
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text("Expense Report")
                        .font(.title2.bold())
                        .foregroundColor(.white)
                    Text(dateRangeDescription)
                        .font(.subheadline)
                        .foregroundColor(.gray)
                }
                Spacer()

                // Mini chart preview
                ZStack {
                    Circle()
                        .stroke(Color.gray.opacity(0.2), lineWidth: 4)
                        .frame(width: 50, height: 50)

                    Circle()
                        .trim(from: 0, to: 0.75)
                        .stroke(
                            LinearGradient(colors: [.tallyAccent, .blue], startPoint: .topLeading, endPoint: .bottomTrailing),
                            style: StrokeStyle(lineWidth: 4, lineCap: .round)
                        )
                        .frame(width: 50, height: 50)
                        .rotationEffect(.degrees(-90))
                }
            }

            Divider().background(Color.gray.opacity(0.3))

            // Quick stats
            HStack(spacing: 20) {
                PreviewStat(
                    title: "Total",
                    value: viewModel.totalAmount.currencyFormatted,
                    color: .white
                )
                PreviewStat(
                    title: "Transactions",
                    value: "\(viewModel.transactionCount)",
                    color: .blue
                )
                PreviewStat(
                    title: "Receipts",
                    value: "\(viewModel.receiptCount)",
                    color: .green
                )
            }

            // Category breakdown preview
            if !viewModel.categoryBreakdown.isEmpty {
                VStack(alignment: .leading, spacing: 8) {
                    Text("Top Categories")
                        .font(.caption)
                        .foregroundColor(.gray)

                    ForEach(viewModel.categoryBreakdown.prefix(3), id: \.category) { item in
                        HStack {
                            Text(item.category)
                                .font(.caption)
                                .foregroundColor(.white)
                            Spacer()
                            Text(item.amount.currencyFormatted)
                                .font(.caption.bold())
                                .foregroundColor(.tallyAccent)
                        }
                    }
                }
            }
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(
                    LinearGradient(
                        colors: [Color.tallyCard, Color.tallyCard.opacity(0.8)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    )
                )
                .shadow(color: .black.opacity(0.3), radius: 15, y: 5)
        )
    }

    // MARK: - Format Selection

    private var formatSelectionSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Export Format")
                .font(.headline)
                .foregroundColor(.white)

            HStack(spacing: 12) {
                ForEach(ExportFormat.allCases, id: \.self) { format in
                    FormatOptionCard(
                        format: format,
                        isSelected: selectedFormat == format
                    ) {
                        HapticService.shared.impact(.light)
                        selectedFormat = format
                    }
                }
            }
        }
    }

    // MARK: - Date Range

    private var dateRangeSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Date Range")
                .font(.headline)
                .foregroundColor(.white)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
                ForEach(DateRangeOption.allCases, id: \.self) { option in
                    DateRangeOptionButton(
                        option: option,
                        isSelected: selectedDateRange == option
                    ) {
                        HapticService.shared.impact(.light)
                        selectedDateRange = option
                        Task {
                            await viewModel.loadPreviewData(
                                dateRange: dateRangeForSelection,
                                businessTypes: Array(selectedBusinessTypes)
                            )
                        }
                    }
                }
            }

            // Custom date pickers
            if selectedDateRange == .custom {
                HStack(spacing: 16) {
                    VStack(alignment: .leading, spacing: 4) {
                        Text("From")
                            .font(.caption)
                            .foregroundColor(.gray)
                        DatePicker("", selection: $customStartDate, displayedComponents: .date)
                            .labelsHidden()
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("To")
                            .font(.caption)
                            .foregroundColor(.gray)
                        DatePicker("", selection: $customEndDate, displayedComponents: .date)
                            .labelsHidden()
                    }
                }
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(12)
            }
        }
    }

    // MARK: - Business Type

    private var businessTypeSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Business Type")
                .font(.headline)
                .foregroundColor(.white)

            FlowLayout(spacing: 10) {
                ForEach(allBusinessTypes, id: \.self) { type in
                    FilterChip(
                        title: type,
                        isSelected: selectedBusinessTypes.contains(type)
                    ) {
                        HapticService.shared.impact(.light)
                        if selectedBusinessTypes.contains(type) {
                            selectedBusinessTypes.remove(type)
                        } else {
                            selectedBusinessTypes.insert(type)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Category

    private var categorySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Categories")
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                Button(selectedCategories.isEmpty ? "Select All" : "Clear") {
                    HapticService.shared.impact(.light)
                    if selectedCategories.isEmpty {
                        selectedCategories = Set(allCategories)
                    } else {
                        selectedCategories.removeAll()
                    }
                }
                .font(.caption)
                .foregroundColor(.tallyAccent)
            }

            FlowLayout(spacing: 8) {
                ForEach(allCategories, id: \.self) { category in
                    FilterChip(
                        title: category,
                        isSelected: selectedCategories.isEmpty || selectedCategories.contains(category)
                    ) {
                        HapticService.shared.impact(.light)
                        if selectedCategories.contains(category) {
                            selectedCategories.remove(category)
                        } else {
                            selectedCategories.insert(category)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Include Options

    private var includeOptionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Include in Report")
                .font(.headline)
                .foregroundColor(.white)

            VStack(spacing: 0) {
                IncludeOptionRow(
                    title: "Receipt Images",
                    subtitle: "Attach scanned receipt images",
                    icon: "photo.stack.fill",
                    isOn: $includeReceipts
                )

                Divider().background(Color.gray.opacity(0.3))

                IncludeOptionRow(
                    title: "Charts & Graphs",
                    subtitle: "Visual spending breakdown",
                    icon: "chart.pie.fill",
                    isOn: $includeCharts
                )

                Divider().background(Color.gray.opacity(0.3))

                IncludeOptionRow(
                    title: "Executive Summary",
                    subtitle: "Key insights and totals",
                    icon: "doc.text.fill",
                    isOn: $includeSummary
                )
            }
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
    }

    // MARK: - Export Button

    private var exportButton: some View {
        Button(action: exportReport) {
            ZStack {
                if isExporting {
                    HStack(spacing: 12) {
                        ProgressView()
                            .progressViewStyle(CircularProgressViewStyle(tint: .black))
                        Text("Generating Report...")
                    }
                } else {
                    HStack(spacing: 8) {
                        Image(systemName: selectedFormat.icon)
                        Text("Generate \(selectedFormat.rawValue) Report")
                            .fontWeight(.semibold)
                    }
                }
            }
            .foregroundColor(.black)
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(
                LinearGradient(
                    colors: [.tallyAccent, .tallyAccent.opacity(0.8)],
                    startPoint: .leading,
                    endPoint: .trailing
                )
            )
            .cornerRadius(14)
            .shadow(color: .tallyAccent.opacity(0.3), radius: 10, y: 5)
        }
        .disabled(isExporting)
    }

    // MARK: - Helpers

    private var dateRangeDescription: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .medium

        let range = dateRangeForSelection
        return "\(formatter.string(from: range.start)) - \(formatter.string(from: range.end))"
    }

    private var dateRangeForSelection: (start: Date, end: Date) {
        let calendar = Calendar.current
        let now = Date()

        switch selectedDateRange {
        case .thisWeek:
            let start = calendar.date(from: calendar.dateComponents([.yearForWeekOfYear, .weekOfYear], from: now)) ?? now
            return (start, now)
        case .thisMonth:
            let start = calendar.date(from: calendar.dateComponents([.year, .month], from: now)) ?? now
            return (start, now)
        case .lastMonth:
            let lastMonth = calendar.date(byAdding: .month, value: -1, to: now) ?? now
            let start = calendar.date(from: calendar.dateComponents([.year, .month], from: lastMonth)) ?? lastMonth
            let end = calendar.date(byAdding: .day, value: -1, to: calendar.date(from: calendar.dateComponents([.year, .month], from: now)) ?? now) ?? now
            return (start, end)
        case .thisQuarter:
            let month = calendar.component(.month, from: now)
            let quarterStart = ((month - 1) / 3) * 3 + 1
            let start = calendar.date(from: DateComponents(year: calendar.component(.year, from: now), month: quarterStart)) ?? now
            return (start, now)
        case .thisYear:
            let start = calendar.date(from: DateComponents(year: calendar.component(.year, from: now))) ?? now
            return (start, now)
        case .custom:
            return (customStartDate, customEndDate)
        }
    }

    private func exportReport() {
        isExporting = true
        HapticService.shared.impact(.medium)

        Task {
            do {
                let url = try await viewModel.generateReport(
                    format: selectedFormat,
                    dateRange: dateRangeForSelection,
                    businessTypes: Array(selectedBusinessTypes),
                    categories: selectedCategories.isEmpty ? nil : Array(selectedCategories),
                    includeReceipts: includeReceipts,
                    includeCharts: includeCharts,
                    includeSummary: includeSummary
                )

                exportedFileURL = url
                isExporting = false
                HapticService.shared.notification(.success)
                showShareSheet = true
            } catch {
                print("Export failed: \(error)")
                isExporting = false
                HapticService.shared.notification(.error)
            }
        }
    }
}

// MARK: - Export Format

enum ExportFormat: String, CaseIterable {
    case pdf = "PDF"
    case csv = "CSV"
    case excel = "Excel"

    var icon: String {
        switch self {
        case .pdf: return "doc.richtext.fill"
        case .csv: return "tablecells.fill"
        case .excel: return "chart.bar.doc.horizontal.fill"
        }
    }

    var color: Color {
        switch self {
        case .pdf: return .red
        case .csv: return .green
        case .excel: return .blue
        }
    }

    var fileExtension: String {
        switch self {
        case .pdf: return "pdf"
        case .csv: return "csv"
        case .excel: return "xlsx"
        }
    }
}

// MARK: - Date Range Option

enum DateRangeOption: String, CaseIterable {
    case thisWeek = "This Week"
    case thisMonth = "This Month"
    case lastMonth = "Last Month"
    case thisQuarter = "This Quarter"
    case thisYear = "This Year"
    case custom = "Custom"
}

// MARK: - Supporting Views

struct PreviewStat: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 4) {
            Text(value)
                .font(.headline)
                .foregroundColor(color)
            Text(title)
                .font(.caption2)
                .foregroundColor(.gray)
        }
        .frame(maxWidth: .infinity)
    }
}

struct FormatOptionCard: View {
    let format: ExportFormat
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                Image(systemName: format.icon)
                    .font(.title2)
                    .foregroundColor(isSelected ? .white : format.color)

                Text(format.rawValue)
                    .font(.caption.bold())
                    .foregroundColor(isSelected ? .white : .gray)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, 16)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? format.color : Color.tallyCard)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(isSelected ? Color.clear : Color.gray.opacity(0.3), lineWidth: 1)
            )
        }
        .buttonStyle(.plain)
    }
}

struct DateRangeOptionButton: View {
    let option: DateRangeOption
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(option.rawValue)
                .font(.subheadline)
                .foregroundColor(isSelected ? .black : .white)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
                .background(
                    RoundedRectangle(cornerRadius: 10)
                        .fill(isSelected ? Color.tallyAccent : Color.tallyCard)
                )
        }
        .buttonStyle(.plain)
    }
}

struct FilterChip: View {
    let title: String
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(title)
                .font(.caption)
                .foregroundColor(isSelected ? .black : .gray)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(
                    Capsule()
                        .fill(isSelected ? Color.tallyAccent : Color.tallyCard)
                )
        }
        .buttonStyle(.plain)
    }
}

struct IncludeOptionRow: View {
    let title: String
    let subtitle: String
    let icon: String
    @Binding var isOn: Bool

    var body: some View {
        HStack(spacing: 14) {
            Image(systemName: icon)
                .font(.title3)
                .foregroundColor(.tallyAccent)
                .frame(width: 30)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline)
                    .foregroundColor(.white)
                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Spacer()

            Toggle("", isOn: $isOn)
                .tint(.tallyAccent)
        }
        .padding()
    }
}

// MARK: - Flow Layout

struct FlowLayout: Layout {
    var spacing: CGFloat = 8

    func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
        let result = layout(proposal: proposal, subviews: subviews)
        return result.size
    }

    func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
        let result = layout(proposal: proposal, subviews: subviews)

        for (index, frame) in result.frames.enumerated() {
            subviews[index].place(
                at: CGPoint(x: bounds.minX + frame.origin.x, y: bounds.minY + frame.origin.y),
                proposal: ProposedViewSize(frame.size)
            )
        }
    }

    private func layout(proposal: ProposedViewSize, subviews: Subviews) -> (size: CGSize, frames: [CGRect]) {
        let maxWidth = proposal.width ?? .infinity
        var frames: [CGRect] = []
        var x: CGFloat = 0
        var y: CGFloat = 0
        var rowHeight: CGFloat = 0

        for subview in subviews {
            let size = subview.sizeThatFits(.unspecified)

            if x + size.width > maxWidth && x > 0 {
                x = 0
                y += rowHeight + spacing
                rowHeight = 0
            }

            frames.append(CGRect(origin: CGPoint(x: x, y: y), size: size))
            rowHeight = max(rowHeight, size.height)
            x += size.width + spacing
        }

        return (CGSize(width: maxWidth, height: y + rowHeight), frames)
    }
}

// MARK: - Share Sheet

struct ShareSheet: UIViewControllerRepresentable {
    let items: [Any]

    func makeUIViewController(context: Context) -> UIActivityViewController {
        UIActivityViewController(activityItems: items, applicationActivities: nil)
    }

    func updateUIViewController(_ uiViewController: UIActivityViewController, context: Context) {}
}

// MARK: - Expense Report View Model

@MainActor
class ExpenseReportViewModel: ObservableObject {
    @Published var totalAmount: Double = 0
    @Published var transactionCount: Int = 0
    @Published var receiptCount: Int = 0
    @Published var categoryBreakdown: [(category: String, amount: Double)] = []

    func loadPreviewData(dateRange: (start: Date, end: Date), businessTypes: [String]) async {
        do {
            let transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: 500,
                business: nil
            )

            let filtered = transactions.filter { transaction in
                transaction.date >= dateRange.start &&
                transaction.date <= dateRange.end &&
                (businessTypes.isEmpty || businessTypes.contains(transaction.business ?? "Personal"))
            }

            totalAmount = filtered.reduce(0) { $0 + abs($1.amount) }
            transactionCount = filtered.count
            receiptCount = filtered.filter { $0.hasReceipt }.count

            // Category breakdown
            var categoryTotals: [String: Double] = [:]
            for transaction in filtered {
                let category = transaction.category ?? "Other"
                categoryTotals[category, default: 0] += abs(transaction.amount)
            }

            categoryBreakdown = categoryTotals
                .map { ($0.key, $0.value) }
                .sorted { $0.1 > $1.1 }

        } catch {
            print("Failed to load preview data: \(error)")
        }
    }

    func generateReport(
        format: ExportFormat,
        dateRange: (start: Date, end: Date),
        businessTypes: [String],
        categories: [String]?,
        includeReceipts: Bool,
        includeCharts: Bool,
        includeSummary: Bool
    ) async throws -> URL {
        // Fetch data
        let transactions = try await APIClient.shared.fetchTransactions(
            offset: 0,
            limit: 1000,
            business: nil
        )

        let filtered = transactions.filter { transaction in
            let inDateRange = transaction.date >= dateRange.start && transaction.date <= dateRange.end
            let inBusinessType = businessTypes.isEmpty || businessTypes.contains(transaction.business ?? "Personal")
            let inCategory = categories == nil || categories!.isEmpty || categories!.contains(transaction.category ?? "Other")
            return inDateRange && inBusinessType && inCategory
        }

        switch format {
        case .pdf:
            return try generatePDFReport(
                transactions: filtered,
                dateRange: dateRange,
                includeCharts: includeCharts,
                includeSummary: includeSummary
            )
        case .csv:
            return try generateCSVReport(transactions: filtered)
        case .excel:
            return try generateCSVReport(transactions: filtered) // CSV for now, Excel requires additional framework
        }
    }

    private func generatePDFReport(
        transactions: [Transaction],
        dateRange: (start: Date, end: Date),
        includeCharts: Bool,
        includeSummary: Bool
    ) throws -> URL {
        let renderer = UIGraphicsPDFRenderer(bounds: CGRect(x: 0, y: 0, width: 612, height: 792)) // Letter size

        let dateFormatter = DateFormatter()
        dateFormatter.dateStyle = .medium

        let data = renderer.pdfData { context in
            context.beginPage()

            // Title
            let titleFont = UIFont.systemFont(ofSize: 24, weight: .bold)
            let title = "Expense Report"
            let titleRect = CGRect(x: 50, y: 50, width: 512, height: 30)
            title.draw(in: titleRect, withAttributes: [.font: titleFont, .foregroundColor: UIColor.black])

            // Date range
            let subtitleFont = UIFont.systemFont(ofSize: 14)
            let subtitle = "\(dateFormatter.string(from: dateRange.start)) - \(dateFormatter.string(from: dateRange.end))"
            let subtitleRect = CGRect(x: 50, y: 85, width: 512, height: 20)
            subtitle.draw(in: subtitleRect, withAttributes: [.font: subtitleFont, .foregroundColor: UIColor.gray])

            var yPosition: CGFloat = 130

            // Summary section
            if includeSummary {
                let total = transactions.reduce(0) { $0 + abs($1.amount) }
                let receiptCount = transactions.filter { $0.hasReceipt }.count

                let summaryFont = UIFont.systemFont(ofSize: 16, weight: .semibold)
                let summaryText = "Total: \(formatCurrency(total)) | Transactions: \(transactions.count) | Receipts: \(receiptCount)"
                let summaryRect = CGRect(x: 50, y: yPosition, width: 512, height: 25)
                summaryText.draw(in: summaryRect, withAttributes: [.font: summaryFont, .foregroundColor: UIColor.black])

                yPosition += 50
            }

            // Table header
            let headerFont = UIFont.systemFont(ofSize: 12, weight: .bold)
            let headers = ["Date", "Merchant", "Amount", "Category", "Receipt"]
            let columnWidths: [CGFloat] = [80, 180, 80, 100, 60]
            var xPosition: CGFloat = 50

            for (index, header) in headers.enumerated() {
                let headerRect = CGRect(x: xPosition, y: yPosition, width: columnWidths[index], height: 20)
                header.draw(in: headerRect, withAttributes: [.font: headerFont, .foregroundColor: UIColor.darkGray])
                xPosition += columnWidths[index]
            }

            yPosition += 25

            // Draw separator
            let separatorPath = UIBezierPath()
            separatorPath.move(to: CGPoint(x: 50, y: yPosition))
            separatorPath.addLine(to: CGPoint(x: 562, y: yPosition))
            UIColor.lightGray.setStroke()
            separatorPath.stroke()

            yPosition += 10

            // Transaction rows
            let rowFont = UIFont.systemFont(ofSize: 11)
            let currencyFormatter = NumberFormatter()
            currencyFormatter.numberStyle = .currency

            for transaction in transactions.prefix(40) { // Limit for first page
                if yPosition > 720 {
                    context.beginPage()
                    yPosition = 50
                }

                xPosition = 50

                // Date
                let dateText = dateFormatter.string(from: transaction.date)
                dateText.draw(in: CGRect(x: xPosition, y: yPosition, width: 80, height: 20),
                             withAttributes: [.font: rowFont])
                xPosition += 80

                // Merchant
                let merchantText = String(transaction.merchant.prefix(30))
                merchantText.draw(in: CGRect(x: xPosition, y: yPosition, width: 180, height: 20),
                                 withAttributes: [.font: rowFont])
                xPosition += 180

                // Amount
                let amountText = formatCurrency(transaction.amount)
                amountText.draw(in: CGRect(x: xPosition, y: yPosition, width: 80, height: 20),
                               withAttributes: [.font: rowFont, .foregroundColor: transaction.amount < 0 ? UIColor.red : UIColor.systemGreen])
                xPosition += 80

                // Category
                let categoryText = transaction.category ?? "—"
                categoryText.draw(in: CGRect(x: xPosition, y: yPosition, width: 100, height: 20),
                                 withAttributes: [.font: rowFont])
                xPosition += 100

                // Receipt indicator
                let receiptText = transaction.hasReceipt ? "✓" : "—"
                receiptText.draw(in: CGRect(x: xPosition, y: yPosition, width: 60, height: 20),
                                withAttributes: [.font: rowFont, .foregroundColor: transaction.hasReceipt ? UIColor.systemGreen : UIColor.lightGray])

                yPosition += 22
            }

            // Footer
            let footerFont = UIFont.systemFont(ofSize: 10)
            let footerText = "Generated by TallyUps on \(dateFormatter.string(from: Date()))"
            footerText.draw(in: CGRect(x: 50, y: 760, width: 512, height: 15),
                           withAttributes: [.font: footerFont, .foregroundColor: UIColor.gray])
        }

        // Save to temp file
        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("TallyUps_Report_\(Date().timeIntervalSince1970).pdf")
        try data.write(to: tempURL)

        return tempURL
    }

    private func generateCSVReport(transactions: [Transaction]) throws -> URL {
        var csv = "Date,Merchant,Amount,Category,Business,Has Receipt,Notes\n"

        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = "yyyy-MM-dd"

        for transaction in transactions {
            let row = [
                dateFormatter.string(from: transaction.date),
                "\"\(transaction.merchant.replacingOccurrences(of: "\"", with: "\"\""))\"",
                String(format: "%.2f", transaction.amount),
                transaction.category ?? "",
                transaction.business ?? "",
                transaction.hasReceipt ? "Yes" : "No",
                "\"\(transaction.notes?.replacingOccurrences(of: "\"", with: "\"\"") ?? "")\""
            ].joined(separator: ",")

            csv += row + "\n"
        }

        let tempURL = FileManager.default.temporaryDirectory
            .appendingPathComponent("TallyUps_Report_\(Date().timeIntervalSince1970).csv")
        try csv.write(to: tempURL, atomically: true, encoding: .utf8)

        return tempURL
    }

    private func formatCurrency(_ amount: Double) -> String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: abs(amount))) ?? "$\(abs(amount))"
    }
}

#Preview {
    ExpenseReportExporter()
        .preferredColorScheme(.dark)
}

import SwiftUI
import Charts

// MARK: - Analytics Dashboard View

struct AnalyticsDashboardView: View {
    @StateObject private var viewModel = AnalyticsViewModel()
    @State private var selectedPeriod: TimePeriod = .month
    @State private var selectedCategory: String?

    var body: some View {
        ScrollView {
            VStack(spacing: 20) {
                // Period Selector
                periodSelector

                // Spending Summary Cards
                spendingSummaryCards

                // Spending Chart
                if !viewModel.chartData.isEmpty {
                    spendingChart
                }

                // Category Breakdown
                if !viewModel.categoryBreakdown.isEmpty {
                    categoryBreakdown
                }

                // Top Merchants
                if !viewModel.topMerchants.isEmpty {
                    topMerchantsSection
                }

                // Recent Activity
                recentActivitySection
            }
            .padding()
        }
        .background(Color.tallyBackground)
        .navigationTitle("Analytics")
        .task {
            await viewModel.loadAnalytics(period: selectedPeriod)
        }
        .onChange(of: selectedPeriod) { _, newPeriod in
            Task {
                await viewModel.loadAnalytics(period: newPeriod)
            }
        }
        .refreshable {
            await viewModel.loadAnalytics(period: selectedPeriod)
        }
    }

    // MARK: - Period Selector

    private var periodSelector: some View {
        HStack(spacing: 0) {
            ForEach(TimePeriod.allCases, id: \.self) { period in
                Button(action: {
                    HapticService.shared.impact(.light)
                    withAnimation(.spring(response: 0.3)) {
                        selectedPeriod = period
                    }
                }) {
                    Text(period.title)
                        .font(.subheadline.weight(selectedPeriod == period ? .semibold : .regular))
                        .foregroundColor(selectedPeriod == period ? .black : .gray)
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 10)
                        .background(
                            selectedPeriod == period ?
                            Color.tallyAccent : Color.clear
                        )
                }
            }
        }
        .background(Color.tallyCard)
        .cornerRadius(10)
    }

    // MARK: - Spending Summary Cards

    private var spendingSummaryCards: some View {
        HStack(spacing: 12) {
            SummaryCard(
                title: "Total Spent",
                value: viewModel.totalSpent.currencyFormatted,
                icon: "dollarsign.circle.fill",
                color: .red
            )

            SummaryCard(
                title: "Avg Daily",
                value: viewModel.avgDaily.currencyFormatted,
                icon: "chart.bar.fill",
                color: .blue
            )

            SummaryCard(
                title: "Receipts",
                value: "\(viewModel.receiptCount)",
                icon: "doc.text.fill",
                color: .green
            )
        }
    }

    // MARK: - Spending Chart

    private var spendingChart: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Spending Trend")
                .font(.headline)
                .foregroundColor(.white)

            Chart(viewModel.chartData) { item in
                BarMark(
                    x: .value("Date", item.label),
                    y: .value("Amount", item.amount)
                )
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.tallyAccent, Color.tallyAccent.opacity(0.5)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
                .cornerRadius(4)
            }
            .chartYAxis {
                AxisMarks(position: .leading) { value in
                    AxisValueLabel {
                        if let amount = value.as(Double.self) {
                            Text(amount.shortCurrencyFormatted)
                                .font(.caption2)
                                .foregroundColor(.gray)
                        }
                    }
                }
            }
            .chartXAxis {
                AxisMarks { value in
                    AxisValueLabel {
                        if let label = value.as(String.self) {
                            Text(label)
                                .font(.caption2)
                                .foregroundColor(.gray)
                        }
                    }
                }
            }
            .frame(height: 200)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    // MARK: - Category Breakdown

    private var categoryBreakdown: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("By Category")
                .font(.headline)
                .foregroundColor(.white)

            // Pie chart visualization
            HStack(spacing: 16) {
                // Mini donut chart
                ZStack {
                    ForEach(viewModel.categoryBreakdown.indices, id: \.self) { index in
                        let item = viewModel.categoryBreakdown[index]
                        let startAngle = viewModel.startAngle(for: index)
                        let endAngle = viewModel.endAngle(for: index)

                        Circle()
                            .trim(from: startAngle, to: endAngle)
                            .stroke(
                                categoryColor(for: item.category),
                                style: StrokeStyle(lineWidth: 24, lineCap: .round)
                            )
                            .frame(width: 100, height: 100)
                            .rotationEffect(.degrees(-90))
                    }

                    // Center total
                    VStack(spacing: 0) {
                        Text(viewModel.totalSpent.shortCurrencyFormatted)
                            .font(.system(size: 14, weight: .bold, design: .rounded))
                            .foregroundColor(.white)
                        Text("Total")
                            .font(.caption2)
                            .foregroundColor(.gray)
                    }
                }
                .frame(width: 120)

                // Legend
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(viewModel.categoryBreakdown.prefix(5)) { item in
                        HStack(spacing: 8) {
                            Circle()
                                .fill(categoryColor(for: item.category))
                                .frame(width: 10, height: 10)

                            Text(item.category)
                                .font(.caption)
                                .foregroundColor(.white)
                                .lineLimit(1)

                            Spacer()

                            Text(item.amount.shortCurrencyFormatted)
                                .font(.caption.bold())
                                .foregroundColor(.gray)
                        }
                    }
                }
            }
            .padding(.vertical, 8)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    // MARK: - Top Merchants

    private var topMerchantsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Top Merchants")
                .font(.headline)
                .foregroundColor(.white)

            ForEach(viewModel.topMerchants.prefix(5)) { merchant in
                HStack {
                    // Rank
                    Text("#\(merchant.rank)")
                        .font(.caption.bold())
                        .foregroundColor(.gray)
                        .frame(width: 24)

                    // Merchant name
                    Text(merchant.name)
                        .font(.subheadline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Spacer()

                    // Amount & count
                    VStack(alignment: .trailing, spacing: 2) {
                        Text(merchant.totalAmount.currencyFormatted)
                            .font(.subheadline.bold())
                            .foregroundColor(.white)
                        Text("\(merchant.transactionCount) transactions")
                            .font(.caption2)
                            .foregroundColor(.gray)
                    }
                }
                .padding(.vertical, 8)

                if merchant.rank < 5 {
                    Divider().background(Color.gray.opacity(0.3))
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    // MARK: - Recent Activity

    private var recentActivitySection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("Recent Activity")
                    .font(.headline)
                    .foregroundColor(.white)
                Spacer()
                NavigationLink(destination: TransactionsView()) {
                    Text("See All")
                        .font(.caption)
                        .foregroundColor(.tallyAccent)
                }
            }

            ForEach(viewModel.recentTransactions.prefix(5)) { transaction in
                HStack {
                    // Receipt indicator
                    Circle()
                        .fill(transaction.hasReceipt ? Color.green : Color.orange)
                        .frame(width: 8, height: 8)

                    // Merchant
                    Text(transaction.merchant.prefix(25))
                        .font(.subheadline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Spacer()

                    // Amount
                    Text(transaction.formattedAmount)
                        .font(.subheadline.bold())
                        .foregroundColor(transaction.amount < 0 ? .white : .green)
                }
                .padding(.vertical, 6)
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    // MARK: - Helpers

    private func categoryColor(for category: String) -> Color {
        let colors: [Color] = [.blue, .purple, .orange, .pink, .green, .yellow, .red, .cyan]
        let hash = abs(category.hashValue)
        return colors[hash % colors.count]
    }
}

// MARK: - Summary Card

struct SummaryCard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            HStack {
                Image(systemName: icon)
                    .foregroundColor(color)
                Spacer()
            }

            Text(value)
                .font(.system(size: 18, weight: .bold, design: .rounded))
                .foregroundColor(.white)
                .minimumScaleFactor(0.7)
                .lineLimit(1)

            Text(title)
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding(12)
        .frame(maxWidth: .infinity)
        .background(Color.tallyCard)
        .cornerRadius(12)
    }
}

// MARK: - Time Period Enum

enum TimePeriod: String, CaseIterable {
    case week
    case month
    case quarter
    case year

    var title: String {
        switch self {
        case .week: return "Week"
        case .month: return "Month"
        case .quarter: return "Quarter"
        case .year: return "Year"
        }
    }

    var days: Int {
        switch self {
        case .week: return 7
        case .month: return 30
        case .quarter: return 90
        case .year: return 365
        }
    }
}

// MARK: - Analytics View Model

@MainActor
class AnalyticsViewModel: ObservableObject {
    @Published var totalSpent: Double = 0
    @Published var avgDaily: Double = 0
    @Published var receiptCount: Int = 0
    @Published var chartData: [ChartDataPoint] = []
    @Published var categoryBreakdown: [CategoryData] = []
    @Published var topMerchants: [MerchantData] = []
    @Published var recentTransactions: [Transaction] = []
    @Published var isLoading = false

    struct ChartDataPoint: Identifiable {
        let id = UUID()
        let date: Date
        let label: String
        let amount: Double
    }

    struct CategoryData: Identifiable {
        let id = UUID()
        let category: String
        let amount: Double
        let percentage: Double
    }

    struct MerchantData: Identifiable {
        let id = UUID()
        let rank: Int
        let name: String
        let totalAmount: Double
        let transactionCount: Int
    }

    func loadAnalytics(period: TimePeriod) async {
        isLoading = true

        do {
            // Fetch transactions for the period
            let transactions = try await APIClient.shared.fetchTransactions(
                offset: 0,
                limit: 500,
                business: nil
            )

            let calendar = Calendar.current
            let now = Date()
            let startDate = calendar.date(byAdding: .day, value: -period.days, to: now) ?? now

            let filteredTransactions = transactions.filter { $0.date >= startDate }

            // Calculate totals
            totalSpent = filteredTransactions.reduce(0) { $0 + abs($1.amount) }
            avgDaily = totalSpent / Double(period.days)
            receiptCount = filteredTransactions.filter { $0.hasReceipt }.count

            // Chart data
            chartData = generateChartData(transactions: filteredTransactions, period: period)

            // Category breakdown
            categoryBreakdown = generateCategoryBreakdown(transactions: filteredTransactions)

            // Top merchants
            topMerchants = generateTopMerchants(transactions: filteredTransactions)

            // Recent transactions
            recentTransactions = Array(filteredTransactions.sorted { $0.date > $1.date }.prefix(10))

        } catch {
            print("AnalyticsViewModel: Failed to load: \(error)")
        }

        isLoading = false
    }

    private func generateChartData(transactions: [Transaction], period: TimePeriod) -> [ChartDataPoint] {
        let calendar = Calendar.current
        var groupedData: [String: Double] = [:]

        let dateFormatter = DateFormatter()
        dateFormatter.dateFormat = period == .week ? "EEE" : (period == .month ? "d" : "MMM")

        for transaction in transactions {
            let key = dateFormatter.string(from: transaction.date)
            groupedData[key, default: 0] += abs(transaction.amount)
        }

        return groupedData.map { ChartDataPoint(date: Date(), label: $0.key, amount: $0.value) }
            .sorted { $0.label < $1.label }
    }

    private func generateCategoryBreakdown(transactions: [Transaction]) -> [CategoryData] {
        var categoryTotals: [String: Double] = [:]

        for transaction in transactions {
            let category = transaction.category ?? "Uncategorized"
            categoryTotals[category, default: 0] += abs(transaction.amount)
        }

        let total = categoryTotals.values.reduce(0, +)

        return categoryTotals
            .map { CategoryData(
                category: $0.key,
                amount: $0.value,
                percentage: total > 0 ? ($0.value / total) : 0
            )}
            .sorted { $0.amount > $1.amount }
    }

    private func generateTopMerchants(transactions: [Transaction]) -> [MerchantData] {
        var merchantData: [String: (total: Double, count: Int)] = [:]

        for transaction in transactions {
            let merchant = cleanMerchantName(transaction.merchant)
            let existing = merchantData[merchant] ?? (total: 0, count: 0)
            merchantData[merchant] = (total: existing.total + abs(transaction.amount), count: existing.count + 1)
        }

        return merchantData
            .sorted { $0.value.total > $1.value.total }
            .prefix(10)
            .enumerated()
            .map { MerchantData(
                rank: $0.offset + 1,
                name: $0.element.key,
                totalAmount: $0.element.value.total,
                transactionCount: $0.element.value.count
            )}
    }

    private func cleanMerchantName(_ merchant: String) -> String {
        merchant
            .replacingOccurrences(of: "PURCHASE AUTHORIZED ON", with: "")
            .replacingOccurrences(of: "CHECKCARD", with: "")
            .trimmingCharacters(in: .whitespaces)
            .components(separatedBy: " ")
            .prefix(3)
            .joined(separator: " ")
    }

    // Pie chart helpers
    func startAngle(for index: Int) -> CGFloat {
        let precedingAngles = categoryBreakdown.prefix(index).reduce(0) { $0 + $1.percentage }
        return CGFloat(precedingAngles)
    }

    func endAngle(for index: Int) -> CGFloat {
        startAngle(for: index) + CGFloat(categoryBreakdown[index].percentage)
    }
}

// MARK: - Formatting Extensions

extension Double {
    var currencyFormatted: String {
        let formatter = NumberFormatter()
        formatter.numberStyle = .currency
        formatter.currencyCode = "USD"
        return formatter.string(from: NSNumber(value: abs(self))) ?? "$\(Int(abs(self)))"
    }

    var shortCurrencyFormatted: String {
        let absValue = abs(self)
        if absValue >= 1000 {
            let formatter = NumberFormatter()
            formatter.numberStyle = .decimal
            formatter.maximumFractionDigits = 1
            return "$\(formatter.string(from: NSNumber(value: absValue / 1000)) ?? "0")K"
        }
        return currencyFormatted
    }
}

// MARK: - Preview

#Preview {
    NavigationStack {
        AnalyticsDashboardView()
    }
    .preferredColorScheme(.dark)
}

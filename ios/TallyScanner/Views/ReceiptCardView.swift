import SwiftUI

struct ReceiptCardView: View {
    let receipt: Receipt

    var body: some View {
        HStack(spacing: 12) {
            // Thumbnail
            AsyncImage(url: URL(string: receipt.thumbnailURL ?? receipt.imageURL ?? "")) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFill()
                case .failure:
                    Image(systemName: "doc.text.fill")
                        .font(.title)
                        .foregroundColor(.gray)
                case .empty:
                    ProgressView()
                @unknown default:
                    EmptyView()
                }
            }
            .frame(width: 60, height: 80)
            .background(Color.tallyBackground)
            .cornerRadius(8)
            .clipped()

            // Details
            VStack(alignment: .leading, spacing: 6) {
                HStack {
                    Text(receipt.merchant ?? "Unknown Merchant")
                        .font(.headline)
                        .foregroundColor(.white)
                        .lineLimit(1)

                    Spacer()

                    Text(receipt.formattedAmount)
                        .font(.headline)
                        .foregroundColor(.tallyAccent)
                }

                HStack {
                    Text(receipt.formattedDate)
                        .font(.subheadline)
                        .foregroundColor(.gray)

                    Spacer()

                    StatusBadge(status: receipt.status)
                }

                if let category = receipt.category {
                    HStack(spacing: 4) {
                        Image(systemName: categoryIcon(category))
                            .font(.caption)
                        Text(category)
                            .font(.caption)
                    }
                    .foregroundColor(.gray)
                }
            }

            Image(systemName: "chevron.right")
                .foregroundColor(.gray)
                .font(.caption)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    private func categoryIcon(_ category: String) -> String {
        switch category.lowercased() {
        case "food", "dining", "food & dining": return "fork.knife"
        case "transportation", "transport": return "car.fill"
        case "shopping": return "bag.fill"
        case "entertainment": return "ticket.fill"
        case "travel": return "airplane"
        case "business": return "briefcase.fill"
        default: return "tag.fill"
        }
    }
}

// MARK: - Status Badge

struct StatusBadge: View {
    let status: Receipt.ReceiptStatus

    var body: some View {
        Text(status.displayName)
            .font(.caption2.bold())
            .foregroundColor(.white)
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(statusColor)
            .cornerRadius(10)
    }

    private var statusColor: Color {
        switch status {
        case .pending: return .yellow.opacity(0.8)
        case .processing: return .blue.opacity(0.8)
        case .matched, .accepted: return .green.opacity(0.8)
        case .unmatched: return .orange.opacity(0.8)
        case .rejected: return .red.opacity(0.8)
        }
    }
}

#Preview {
    VStack {
        ReceiptCardView(receipt: Receipt(
            id: "1",
            merchant: "Starbucks",
            amount: 12.50,
            date: Date(),
            category: "Food & Dining",
            status: .matched,
            createdAt: Date()
        ))

        ReceiptCardView(receipt: Receipt(
            id: "2",
            merchant: "Amazon",
            amount: 156.99,
            date: Date(),
            category: "Shopping",
            status: .unmatched,
            createdAt: Date()
        ))
    }
    .padding()
    .background(Color.tallyBackground)
}

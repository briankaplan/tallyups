import SwiftUI

// MARK: - Connected Services View

struct ConnectedServicesView: View {
    @StateObject private var viewModel = ConnectedServicesViewModel()
    @State private var showingGmailSetup = false
    @State private var showingCalendarSetup = false
    @State private var showingBankSetup = false
    @State private var animateCards = false

    var body: some View {
        NavigationStack {
            ZStack {
                // Background gradient
                LinearGradient(
                    colors: [
                        Color(.systemBackground),
                        Color.tallyAccent.opacity(0.02)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // Header
                        headerSection

                        // Service Cards
                        VStack(spacing: 16) {
                            // Gmail Card
                            ServiceConnectionCard(
                                service: .gmail,
                                isConnected: viewModel.gmailConnected,
                                accounts: viewModel.gmailAccounts,
                                lastSync: viewModel.gmailLastSync,
                                isLoading: viewModel.isConnectingGmail,
                                onConnect: { showingGmailSetup = true },
                                onDisconnect: { account in
                                    Task {
                                        await viewModel.disconnectGmail(account: account)
                                    }
                                }
                            )
                            .offset(x: animateCards ? 0 : -100)
                            .opacity(animateCards ? 1 : 0)

                            // Calendar Card
                            ServiceConnectionCard(
                                service: .calendar,
                                isConnected: viewModel.calendarConnected,
                                accounts: viewModel.calendarAccounts,
                                lastSync: viewModel.calendarLastSync,
                                isLoading: viewModel.isConnectingCalendar,
                                onConnect: { showingCalendarSetup = true },
                                onDisconnect: { account in
                                    Task {
                                        await viewModel.disconnectCalendar(account: account)
                                    }
                                }
                            )
                            .offset(x: animateCards ? 0 : -100)
                            .opacity(animateCards ? 1 : 0)
                            .animation(.spring(response: 0.6, dampingFraction: 0.8).delay(0.1), value: animateCards)

                            // Bank/Plaid Card
                            ServiceConnectionCard(
                                service: .bank,
                                isConnected: viewModel.bankConnected,
                                accounts: viewModel.bankAccounts,
                                lastSync: viewModel.bankLastSync,
                                isLoading: viewModel.isConnectingBank,
                                onConnect: { showingBankSetup = true },
                                onDisconnect: { account in
                                    Task {
                                        await viewModel.disconnectBank(account: account)
                                    }
                                }
                            )
                            .offset(x: animateCards ? 0 : -100)
                            .opacity(animateCards ? 1 : 0)
                            .animation(.spring(response: 0.6, dampingFraction: 0.8).delay(0.2), value: animateCards)
                        }

                        // Benefits section
                        benefitsSection
                            .opacity(animateCards ? 1 : 0)
                            .animation(.easeIn.delay(0.4), value: animateCards)
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 40)
                }
            }
            .navigationTitle("Connected Services")
            .navigationBarTitleDisplayMode(.large)
            .onAppear {
                Task {
                    await viewModel.loadServices()
                }
                withAnimation(.spring(response: 0.6, dampingFraction: 0.8)) {
                    animateCards = true
                }
            }
            .refreshable {
                await viewModel.loadServices()
            }
            .sheet(isPresented: $showingGmailSetup) {
                GmailSetupSheet(viewModel: viewModel)
            }
            .sheet(isPresented: $showingCalendarSetup) {
                CalendarSetupSheet(viewModel: viewModel)
            }
            .sheet(isPresented: $showingBankSetup) {
                BankSetupSheet(viewModel: viewModel)
            }
            .alert("Error", isPresented: .constant(viewModel.errorMessage != nil)) {
                Button("OK") {
                    viewModel.errorMessage = nil
                }
            } message: {
                Text(viewModel.errorMessage ?? "")
            }
        }
    }

    private var headerSection: some View {
        VStack(spacing: 12) {
            // Animated connection icon
            ZStack {
                // Pulse animation
                Circle()
                    .fill(Color.tallyAccent.opacity(0.1))
                    .frame(width: 120, height: 120)
                    .scaleEffect(animateCards ? 1.2 : 1)
                    .opacity(animateCards ? 0 : 0.5)
                    .animation(.easeOut(duration: 1.5).repeatForever(autoreverses: false), value: animateCards)

                Circle()
                    .fill(
                        LinearGradient(
                            colors: [.tallyAccent.opacity(0.2), .tallyAccent.opacity(0.05)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 90, height: 90)

                Image(systemName: "link.circle.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [.tallyAccent, .tallyAccent.opacity(0.7)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            }

            Text("Connect Your Services")
                .font(.title2)
                .fontWeight(.bold)

            Text("Link your accounts to automatically import receipts and match transactions")
                .font(.subheadline)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .padding(.vertical, 20)
    }

    private var benefitsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Why Connect?")
                .font(.headline)
                .foregroundColor(.primary)

            VStack(spacing: 12) {
                BenefitRow(
                    icon: "envelope.open.fill",
                    title: "Automatic Receipt Import",
                    description: "Receipts from email are automatically extracted and organized"
                )

                BenefitRow(
                    icon: "arrow.triangle.2.circlepath.circle.fill",
                    title: "Smart Matching",
                    description: "Match receipts to bank transactions automatically"
                )

                BenefitRow(
                    icon: "calendar.badge.clock",
                    title: "Meeting Context",
                    description: "Add attendee information from your calendar events"
                )

                BenefitRow(
                    icon: "lock.shield.fill",
                    title: "Secure Connection",
                    description: "We use industry-standard OAuth - we never see your passwords"
                )
            }
        }
        .padding(20)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color(.secondarySystemBackground))
        )
    }
}

// MARK: - Service Types

enum ServiceType {
    case gmail
    case calendar
    case bank

    var name: String {
        switch self {
        case .gmail: return "Gmail"
        case .calendar: return "Google Calendar"
        case .bank: return "Bank Accounts"
        }
    }

    var icon: String {
        switch self {
        case .gmail: return "envelope.fill"
        case .calendar: return "calendar"
        case .bank: return "building.columns.fill"
        }
    }

    var color: Color {
        switch self {
        case .gmail: return .red
        case .calendar: return .blue
        case .bank: return .green
        }
    }

    var description: String {
        switch self {
        case .gmail: return "Import receipts from your email automatically"
        case .calendar: return "Add meeting context to your expenses"
        case .bank: return "Sync transactions from your bank accounts"
        }
    }
}

// MARK: - Service Connection Card

struct ServiceConnectionCard: View {
    let service: ServiceType
    let isConnected: Bool
    let accounts: [String]
    let lastSync: Date?
    let isLoading: Bool
    let onConnect: () -> Void
    let onDisconnect: (String?) -> Void

    @State private var isExpanded = false

    var body: some View {
        VStack(spacing: 0) {
            // Main card
            Button(action: {
                if isConnected && accounts.count > 0 {
                    withAnimation(.spring(response: 0.3)) {
                        isExpanded.toggle()
                    }
                } else {
                    onConnect()
                }
            }) {
                HStack(spacing: 16) {
                    // Service icon
                    ZStack {
                        Circle()
                            .fill(service.color.opacity(0.15))
                            .frame(width: 56, height: 56)

                        if isLoading {
                            ProgressView()
                                .scaleEffect(0.8)
                        } else {
                            Image(systemName: service.icon)
                                .font(.system(size: 24))
                                .foregroundColor(service.color)
                        }
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text(service.name)
                            .font(.headline)
                            .foregroundColor(.primary)

                        if isConnected {
                            HStack(spacing: 4) {
                                Image(systemName: "checkmark.circle.fill")
                                    .font(.caption)
                                    .foregroundColor(.green)

                                Text(accounts.count == 1 ? accounts.first ?? "Connected" : "\(accounts.count) accounts")
                                    .font(.caption)
                                    .foregroundColor(.secondary)
                            }

                            if let lastSync = lastSync {
                                Text("Last sync: \(formatDate(lastSync))")
                                    .font(.caption2)
                                    .foregroundColor(.secondary)
                            }
                        } else {
                            Text(service.description)
                                .font(.caption)
                                .foregroundColor(.secondary)
                        }
                    }

                    Spacer()

                    if isConnected {
                        Image(systemName: isExpanded ? "chevron.up" : "chevron.down")
                            .font(.caption)
                            .foregroundColor(.secondary)
                    } else {
                        Text("Connect")
                            .font(.subheadline)
                            .fontWeight(.semibold)
                            .foregroundColor(.white)
                            .padding(.horizontal, 16)
                            .padding(.vertical, 8)
                            .background(
                                LinearGradient(
                                    colors: [service.color, service.color.opacity(0.8)],
                                    startPoint: .leading,
                                    endPoint: .trailing
                                )
                            )
                            .clipShape(Capsule())
                    }
                }
                .padding(16)
            }
            .buttonStyle(.plain)

            // Expanded accounts list
            if isExpanded && isConnected {
                VStack(spacing: 0) {
                    Divider()
                        .padding(.horizontal, 16)

                    ForEach(accounts, id: \.self) { account in
                        HStack {
                            Image(systemName: "person.circle.fill")
                                .foregroundColor(.secondary)

                            Text(account)
                                .font(.subheadline)
                                .foregroundColor(.primary)

                            Spacer()

                            Button(action: {
                                onDisconnect(account)
                            }) {
                                Image(systemName: "xmark.circle.fill")
                                    .foregroundColor(.red.opacity(0.7))
                            }
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)

                        if account != accounts.last {
                            Divider()
                                .padding(.leading, 56)
                        }
                    }

                    // Add another account button
                    Button(action: onConnect) {
                        HStack {
                            Image(systemName: "plus.circle.fill")
                                .foregroundColor(service.color)

                            Text("Add another account")
                                .font(.subheadline)
                                .foregroundColor(service.color)
                        }
                        .padding(.horizontal, 16)
                        .padding(.vertical, 12)
                    }
                }
                .transition(.opacity.combined(with: .move(edge: .top)))
            }
        }
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color(.secondarySystemBackground))
                .shadow(color: isConnected ? service.color.opacity(0.1) : .clear, radius: 10, x: 0, y: 5)
        )
        .overlay(
            RoundedRectangle(cornerRadius: 20)
                .strokeBorder(
                    isConnected ? service.color.opacity(0.3) : Color.clear,
                    lineWidth: 1
                )
        )
    }

    private func formatDate(_ date: Date) -> String {
        let formatter = RelativeDateTimeFormatter()
        formatter.unitsStyle = .abbreviated
        return formatter.localizedString(for: date, relativeTo: Date())
    }
}

// MARK: - Benefit Row

struct BenefitRow: View {
    let icon: String
    let title: String
    let description: String

    var body: some View {
        HStack(alignment: .top, spacing: 12) {
            ZStack {
                Circle()
                    .fill(Color.tallyAccent.opacity(0.15))
                    .frame(width: 40, height: 40)

                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(.tallyAccent)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.semibold)
                    .foregroundColor(.primary)

                Text(description)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()
        }
    }
}

// MARK: - Gmail Setup Sheet

struct GmailSetupSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: ConnectedServicesViewModel
    @State private var isConnecting = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                // Icon
                ZStack {
                    Circle()
                        .fill(Color.red.opacity(0.15))
                        .frame(width: 100, height: 100)

                    Image(systemName: "envelope.fill")
                        .font(.system(size: 44))
                        .foregroundColor(.red)
                }
                .padding(.top, 40)

                Text("Connect Gmail")
                    .font(.title2)
                    .fontWeight(.bold)

                Text("Allow TallyUps to scan your emails for receipts. We only read emails from known receipt senders.")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)

                // Permissions list
                VStack(alignment: .leading, spacing: 12) {
                    PermissionRow(icon: "envelope.open", text: "Read emails from receipt senders")
                    PermissionRow(icon: "tag", text: "Create labels to organize receipts")
                    PermissionRow(icon: "eye.slash", text: "We never read personal emails")
                }
                .padding(.horizontal, 32)
                .padding(.vertical, 20)

                Spacer()

                // Connect button
                Button(action: {
                    isConnecting = true
                    Task {
                        await viewModel.connectGmail()
                        dismiss()
                    }
                }) {
                    HStack {
                        if isConnecting {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "link")
                        }
                        Text(isConnecting ? "Connecting..." : "Connect with Google")
                            .fontWeight(.semibold)
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(
                        LinearGradient(
                            colors: [.red, .red.opacity(0.8)],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .foregroundColor(.white)
                    .cornerRadius(16)
                }
                .disabled(isConnecting)
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
            }
            .navigationTitle("Gmail Setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
            }
        }
    }
}

// MARK: - Calendar Setup Sheet

struct CalendarSetupSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: ConnectedServicesViewModel
    @State private var isConnecting = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                // Icon
                ZStack {
                    Circle()
                        .fill(Color.blue.opacity(0.15))
                        .frame(width: 100, height: 100)

                    Image(systemName: "calendar")
                        .font(.system(size: 44))
                        .foregroundColor(.blue)
                }
                .padding(.top, 40)

                Text("Connect Calendar")
                    .font(.title2)
                    .fontWeight(.bold)

                Text("Access your calendar events to add meeting context to your expenses.")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)

                // Permissions list
                VStack(alignment: .leading, spacing: 12) {
                    PermissionRow(icon: "calendar.badge.clock", text: "Read your calendar events")
                    PermissionRow(icon: "person.2", text: "See meeting attendees")
                    PermissionRow(icon: "pencil.slash", text: "We never modify your calendar")
                }
                .padding(.horizontal, 32)
                .padding(.vertical, 20)

                Spacer()

                // Connect button
                Button(action: {
                    isConnecting = true
                    Task {
                        await viewModel.connectCalendar()
                        dismiss()
                    }
                }) {
                    HStack {
                        if isConnecting {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "link")
                        }
                        Text(isConnecting ? "Connecting..." : "Connect with Google")
                            .fontWeight(.semibold)
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(
                        LinearGradient(
                            colors: [.blue, .blue.opacity(0.8)],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .foregroundColor(.white)
                    .cornerRadius(16)
                }
                .disabled(isConnecting)
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
            }
            .navigationTitle("Calendar Setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
            }
        }
    }
}

// MARK: - Bank Setup Sheet

struct BankSetupSheet: View {
    @Environment(\.dismiss) private var dismiss
    @ObservedObject var viewModel: ConnectedServicesViewModel
    @State private var isConnecting = false

    var body: some View {
        NavigationStack {
            VStack(spacing: 24) {
                // Icon
                ZStack {
                    Circle()
                        .fill(Color.green.opacity(0.15))
                        .frame(width: 100, height: 100)

                    Image(systemName: "building.columns.fill")
                        .font(.system(size: 44))
                        .foregroundColor(.green)
                }
                .padding(.top, 40)

                Text("Connect Bank Account")
                    .font(.title2)
                    .fontWeight(.bold)

                Text("Securely link your bank accounts to automatically import transactions and match receipts.")
                    .font(.subheadline)
                    .foregroundColor(.secondary)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)

                // Security info
                VStack(spacing: 16) {
                    HStack {
                        Image(systemName: "lock.shield.fill")
                            .font(.title2)
                            .foregroundColor(.green)

                        Text("Powered by Plaid")
                            .font(.headline)
                    }

                    Text("Plaid is trusted by millions of users and thousands of financial institutions. Your bank credentials are never shared with TallyUps.")
                        .font(.caption)
                        .foregroundColor(.secondary)
                        .multilineTextAlignment(.center)
                }
                .padding(.horizontal, 32)
                .padding(.vertical, 20)
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(Color.green.opacity(0.1))
                )
                .padding(.horizontal, 20)

                // Permissions list
                VStack(alignment: .leading, spacing: 12) {
                    PermissionRow(icon: "list.bullet.rectangle", text: "Read transaction history")
                    PermissionRow(icon: "creditcard", text: "See account balances")
                    PermissionRow(icon: "arrow.left.arrow.right.circle", text: "No transfers or payments")
                }
                .padding(.horizontal, 32)

                Spacer()

                // Connect button
                Button(action: {
                    isConnecting = true
                    Task {
                        await viewModel.connectBank()
                        dismiss()
                    }
                }) {
                    HStack {
                        if isConnecting {
                            ProgressView()
                                .tint(.white)
                        } else {
                            Image(systemName: "link")
                        }
                        Text(isConnecting ? "Connecting..." : "Connect Bank Account")
                            .fontWeight(.semibold)
                    }
                    .frame(maxWidth: .infinity)
                    .padding()
                    .background(
                        LinearGradient(
                            colors: [.green, .green.opacity(0.8)],
                            startPoint: .leading,
                            endPoint: .trailing
                        )
                    )
                    .foregroundColor(.white)
                    .cornerRadius(16)
                }
                .disabled(isConnecting)
                .padding(.horizontal, 20)
                .padding(.bottom, 40)
            }
            .navigationTitle("Bank Setup")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
            }
        }
    }
}

// MARK: - Permission Row

struct PermissionRow: View {
    let icon: String
    let text: String

    var body: some View {
        HStack(spacing: 12) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundColor(.tallyAccent)
                .frame(width: 24)

            Text(text)
                .font(.subheadline)
                .foregroundColor(.primary)
        }
    }
}

// MARK: - View Model

@MainActor
class ConnectedServicesViewModel: ObservableObject {
    @Published var gmailConnected = false
    @Published var gmailAccounts: [String] = []
    @Published var gmailLastSync: Date?

    @Published var calendarConnected = false
    @Published var calendarAccounts: [String] = []
    @Published var calendarLastSync: Date?

    @Published var bankConnected = false
    @Published var bankAccounts: [String] = []
    @Published var bankLastSync: Date?

    @Published var isConnectingGmail = false
    @Published var isConnectingCalendar = false
    @Published var isConnectingBank = false

    @Published var errorMessage: String?

    func loadServices() async {
        do {
            let services = try await APIClient.shared.fetchConnectedServices()

            for service in services {
                switch service.type {
                case "gmail":
                    gmailConnected = service.isConnected
                    if let email = service.email {
                        if !gmailAccounts.contains(email) {
                            gmailAccounts.append(email)
                        }
                    }
                    gmailLastSync = service.lastSync

                case "calendar":
                    calendarConnected = service.isConnected
                    if let email = service.email {
                        if !calendarAccounts.contains(email) {
                            calendarAccounts.append(email)
                        }
                    }
                    calendarLastSync = service.lastSync

                case "plaid", "bank":
                    bankConnected = service.isConnected
                    if let email = service.email {
                        if !bankAccounts.contains(email) {
                            bankAccounts.append(email)
                        }
                    }
                    bankLastSync = service.lastSync

                default:
                    break
                }
            }
        } catch {
            print("Failed to load services: \(error)")
        }
    }

    func connectGmail() async {
        isConnectingGmail = true
        defer { isConnectingGmail = false }

        do {
            let authURL = try await APIClient.shared.getGmailOAuthURL()
            // In a real app, this would open Safari or ASWebAuthenticationSession
            await MainActor.run {
                UIApplication.shared.open(authURL)
            }
        } catch {
            errorMessage = "Failed to connect Gmail: \(error.localizedDescription)"
        }
    }

    func disconnectGmail(account: String?) async {
        do {
            try await APIClient.shared.disconnectService(type: "gmail", accountId: account)
            if let account = account {
                gmailAccounts.removeAll { $0 == account }
            } else {
                gmailAccounts.removeAll()
            }
            gmailConnected = !gmailAccounts.isEmpty
        } catch {
            errorMessage = "Failed to disconnect Gmail: \(error.localizedDescription)"
        }
    }

    func connectCalendar() async {
        isConnectingCalendar = true
        defer { isConnectingCalendar = false }

        do {
            let authURL = try await APIClient.shared.getCalendarOAuthURL()
            await MainActor.run {
                UIApplication.shared.open(authURL)
            }
        } catch {
            errorMessage = "Failed to connect Calendar: \(error.localizedDescription)"
        }
    }

    func disconnectCalendar(account: String?) async {
        do {
            try await APIClient.shared.disconnectService(type: "calendar", accountId: account)
            if let account = account {
                calendarAccounts.removeAll { $0 == account }
            } else {
                calendarAccounts.removeAll()
            }
            calendarConnected = !calendarAccounts.isEmpty
        } catch {
            errorMessage = "Failed to disconnect Calendar: \(error.localizedDescription)"
        }
    }

    func connectBank() async {
        isConnectingBank = true
        defer { isConnectingBank = false }

        do {
            _ = try await APIClient.shared.getPlaidLinkToken()
            // In a real app, this would open Plaid Link SDK
            // For now, show a message
            errorMessage = "Plaid Link integration requires the Plaid SDK. Please use the web interface to connect bank accounts."
        } catch {
            errorMessage = "Failed to connect bank: \(error.localizedDescription)"
        }
    }

    func disconnectBank(account: String?) async {
        do {
            try await APIClient.shared.disconnectService(type: "plaid", accountId: account)
            if let account = account {
                bankAccounts.removeAll { $0 == account }
            } else {
                bankAccounts.removeAll()
            }
            bankConnected = !bankAccounts.isEmpty
        } catch {
            errorMessage = "Failed to disconnect bank: \(error.localizedDescription)"
        }
    }
}

// MARK: - Previews

#Preview {
    ConnectedServicesView()
}

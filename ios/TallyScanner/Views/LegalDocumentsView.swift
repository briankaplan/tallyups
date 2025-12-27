import SwiftUI

// MARK: - Terms of Service View

struct TermsOfServiceView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var scrollOffset: CGFloat = 0
    @State private var hasScrolledToBottom = false
    @State private var showingAcceptButton = false
    @State private var acceptedDate: Date?

    var showAcceptButton: Bool = false
    var onAccept: (() -> Void)?

    var body: some View {
        NavigationStack {
            ZStack {
                // Animated gradient background
                AnimatedGradientBackground()

                ScrollViewReader { proxy in
                    ScrollView {
                        VStack(alignment: .leading, spacing: 24) {
                            // Hero Section
                            termsHeroSection

                            // Terms Content
                            termsContent

                            // Bottom marker for scroll detection
                            Color.clear
                                .frame(height: 1)
                                .id("bottom")
                                .onAppear {
                                    withAnimation(.spring(response: 0.5)) {
                                        hasScrolledToBottom = true
                                    }
                                }

                            // Accept Button (if needed)
                            if showAcceptButton {
                                acceptSection
                            }
                        }
                        .padding(.horizontal, 20)
                        .padding(.bottom, 40)
                    }
                }
            }
            .navigationTitle("Terms of Service")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
            }
        }
    }

    private var termsHeroSection: some View {
        VStack(spacing: 16) {
            // Animated icon
            ZStack {
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [.tallyAccent.opacity(0.3), .tallyAccent.opacity(0.1)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 100, height: 100)

                Image(systemName: "doc.text.fill")
                    .font(.system(size: 40))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [.tallyAccent, .tallyAccent.opacity(0.7)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            }
            .shadow(color: .tallyAccent.opacity(0.3), radius: 20, x: 0, y: 10)

            Text("Terms of Service")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundColor(.primary)

            Text("Last updated: \(formattedDate)")
                .font(.subheadline)
                .foregroundColor(.secondary)

            Text("Please read these terms carefully before using TallyUps.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 30)
    }

    private var termsContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            LegalSection(
                number: "1",
                title: "Acceptance of Terms",
                icon: "checkmark.seal.fill",
                iconColor: .green
            ) {
                Text("By accessing or using TallyUps (the \"Service\"), you agree to be bound by these Terms of Service. If you disagree with any part of the terms, you may not access the Service.")
                    .legalBodyStyle()

                Text("These terms apply to all visitors, users, and others who access or use the Service.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "2",
                title: "Description of Service",
                icon: "app.fill",
                iconColor: .blue
            ) {
                Text("TallyUps is a receipt management and expense tracking application that provides:")
                    .legalBodyStyle()

                BulletList(items: [
                    "Receipt scanning and optical character recognition (OCR)",
                    "Expense categorization and organization",
                    "Bank transaction synchronization via Plaid",
                    "Email receipt extraction via Gmail integration",
                    "Calendar integration for expense context",
                    "Expense reporting and export functionality",
                    "Cloud storage and synchronization"
                ])
            }

            LegalSection(
                number: "3",
                title: "User Accounts",
                icon: "person.fill",
                iconColor: .purple
            ) {
                Text("When you create an account with us, you must provide accurate, complete, and current information. Failure to do so constitutes a breach of the Terms.")
                    .legalBodyStyle()

                Text("You are responsible for safeguarding the password and for all activities that occur under your account. You agree not to disclose your password to any third party.")
                    .legalBodyStyle()

                Text("You must notify us immediately upon becoming aware of any breach of security or unauthorized use of your account.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "4",
                title: "User Data and Privacy",
                icon: "lock.shield.fill",
                iconColor: .tallyAccent
            ) {
                Text("Your privacy is important to us. Our collection and use of personal information is governed by our Privacy Policy, which is incorporated into these Terms by reference.")
                    .legalBodyStyle()

                Text("By using the Service, you consent to the collection and use of information as described in our Privacy Policy.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "5",
                title: "Acceptable Use",
                icon: "hand.raised.fill",
                iconColor: .orange
            ) {
                Text("You agree not to use the Service:")
                    .legalBodyStyle()

                BulletList(items: [
                    "In any way that violates any applicable law or regulation",
                    "To transmit any unauthorized advertising or promotional material",
                    "To impersonate any person or entity",
                    "To interfere with or disrupt the Service or servers",
                    "To attempt to gain unauthorized access to any portion of the Service",
                    "To upload false, misleading, or fraudulent information"
                ])
            }

            LegalSection(
                number: "6",
                title: "Intellectual Property",
                icon: "c.circle.fill",
                iconColor: .indigo
            ) {
                Text("The Service and its original content, features, and functionality are and will remain the exclusive property of TallyUps and its licensors.")
                    .legalBodyStyle()

                Text("Our trademarks and trade dress may not be used in connection with any product or service without prior written consent.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "7",
                title: "Third-Party Services",
                icon: "link.circle.fill",
                iconColor: .cyan
            ) {
                Text("The Service may contain links to or integrations with third-party services including but not limited to:")
                    .legalBodyStyle()

                BulletList(items: [
                    "Plaid Technologies (bank account linking)",
                    "Google (Gmail and Calendar integration)",
                    "Apple (Sign in with Apple)",
                    "Cloud storage providers"
                ])

                Text("We are not responsible for the content, privacy policies, or practices of any third-party services. You acknowledge and agree that we shall not be liable for any damage or loss caused by the use of such third-party services.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "8",
                title: "Payment Terms",
                icon: "creditcard.fill",
                iconColor: .green
            ) {
                Text("Some features of the Service may require payment. By using paid features, you agree to pay all applicable fees.")
                    .legalBodyStyle()

                Text("Subscription fees are billed in advance on a recurring basis. You can cancel your subscription at any time through your account settings.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "9",
                title: "Disclaimer of Warranties",
                icon: "exclamationmark.triangle.fill",
                iconColor: .yellow
            ) {
                Text("THE SERVICE IS PROVIDED \"AS IS\" AND \"AS AVAILABLE\" WITHOUT ANY WARRANTIES OF ANY KIND, EXPRESS OR IMPLIED.")
                    .legalBodyStyle()
                    .fontWeight(.medium)

                Text("We do not warrant that the Service will be uninterrupted, timely, secure, or error-free. OCR results and automatic categorizations may not be 100% accurate and should be verified by users.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "10",
                title: "Limitation of Liability",
                icon: "shield.fill",
                iconColor: .red
            ) {
                Text("IN NO EVENT SHALL TALLYUPS, ITS DIRECTORS, EMPLOYEES, PARTNERS, OR AFFILIATES BE LIABLE FOR ANY INDIRECT, INCIDENTAL, SPECIAL, CONSEQUENTIAL, OR PUNITIVE DAMAGES.")
                    .legalBodyStyle()
                    .fontWeight(.medium)

                Text("This includes, without limitation, loss of profits, data, use, goodwill, or other intangible losses resulting from your use of the Service.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "11",
                title: "Indemnification",
                icon: "person.badge.shield.checkmark.fill",
                iconColor: .blue
            ) {
                Text("You agree to defend, indemnify, and hold harmless TallyUps from and against any claims, liabilities, damages, judgments, awards, losses, costs, expenses, or fees arising out of or relating to your violation of these Terms or your use of the Service.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "12",
                title: "Termination",
                icon: "xmark.circle.fill",
                iconColor: .red
            ) {
                Text("We may terminate or suspend your account immediately, without prior notice or liability, for any reason, including breach of these Terms.")
                    .legalBodyStyle()

                Text("Upon termination, your right to use the Service will cease immediately. You may request deletion of your data in accordance with our Privacy Policy.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "13",
                title: "Changes to Terms",
                icon: "arrow.triangle.2.circlepath",
                iconColor: .purple
            ) {
                Text("We reserve the right to modify these Terms at any time. We will notify you of any changes by posting the new Terms on this page and updating the \"Last updated\" date.")
                    .legalBodyStyle()

                Text("Your continued use of the Service after any changes constitutes acceptance of the new Terms.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "14",
                title: "Contact Us",
                icon: "envelope.fill",
                iconColor: .tallyAccent
            ) {
                Text("If you have any questions about these Terms, please contact us:")
                    .legalBodyStyle()

                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Image(systemName: "envelope")
                            .foregroundColor(.tallyAccent)
                        Text("legal@tallyups.com")
                            .foregroundColor(.primary)
                    }
                    HStack {
                        Image(systemName: "globe")
                            .foregroundColor(.tallyAccent)
                        Text("https://tallyups.com/terms")
                            .foregroundColor(.primary)
                    }
                }
                .font(.subheadline)
                .padding(.top, 8)
            }
        }
    }

    private var acceptSection: some View {
        VStack(spacing: 16) {
            if !hasScrolledToBottom {
                Text("Please scroll to read all terms")
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Button(action: {
                acceptedDate = Date()
                onAccept?()
            }) {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                    Text("I Accept the Terms of Service")
                        .fontWeight(.semibold)
                }
                .frame(maxWidth: .infinity)
                .padding()
                .background(
                    hasScrolledToBottom ?
                    LinearGradient(
                        colors: [.tallyAccent, .tallyAccent.opacity(0.8)],
                        startPoint: .leading,
                        endPoint: .trailing
                    ) :
                    LinearGradient(
                        colors: [.gray.opacity(0.5), .gray.opacity(0.3)],
                        startPoint: .leading,
                        endPoint: .trailing
                    )
                )
                .foregroundColor(.white)
                .cornerRadius(16)
                .shadow(color: hasScrolledToBottom ? .tallyAccent.opacity(0.3) : .clear, radius: 10, x: 0, y: 5)
            }
            .disabled(!hasScrolledToBottom)
            .animation(.spring(response: 0.3), value: hasScrolledToBottom)
        }
        .padding(.top, 20)
    }

    private var formattedDate: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .long
        return formatter.string(from: Date())
    }
}

// MARK: - Privacy Policy View

struct PrivacyPolicyView: View {
    @Environment(\.dismiss) private var dismiss
    @State private var expandedSections: Set<String> = []

    var body: some View {
        NavigationStack {
            ZStack {
                // Animated gradient background
                AnimatedGradientBackground()

                ScrollView {
                    VStack(alignment: .leading, spacing: 24) {
                        // Hero Section
                        privacyHeroSection

                        // Quick Summary Cards
                        quickSummarySection

                        // Full Policy Content
                        privacyContent

                        // Data Rights Section
                        dataRightsSection
                    }
                    .padding(.horizontal, 20)
                    .padding(.bottom, 40)
                }
            }
            .navigationTitle("Privacy Policy")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .navigationBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .fontWeight(.semibold)
                }
            }
        }
    }

    private var privacyHeroSection: some View {
        VStack(spacing: 16) {
            // Animated privacy shield
            ZStack {
                // Outer glow
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [.tallyAccent.opacity(0.3), .clear],
                            center: .center,
                            startRadius: 30,
                            endRadius: 70
                        )
                    )
                    .frame(width: 140, height: 140)

                // Shield background
                Circle()
                    .fill(
                        LinearGradient(
                            colors: [.tallyAccent.opacity(0.2), .tallyAccent.opacity(0.05)],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
                    .frame(width: 100, height: 100)

                // Shield icon
                Image(systemName: "lock.shield.fill")
                    .font(.system(size: 44))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [.tallyAccent, .tallyAccent.opacity(0.7)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            }
            .shadow(color: .tallyAccent.opacity(0.3), radius: 20, x: 0, y: 10)

            Text("Privacy Policy")
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundColor(.primary)

            Text("Last updated: \(formattedDate)")
                .font(.subheadline)
                .foregroundColor(.secondary)

            Text("Your privacy is our priority. Here's how we protect your data.")
                .font(.body)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .padding(.horizontal)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 30)
    }

    private var quickSummarySection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Quick Summary")
                .font(.headline)
                .foregroundColor(.primary)

            LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 12) {
                PrivacySummaryCard(
                    icon: "lock.fill",
                    title: "Encrypted",
                    description: "Your data is encrypted at rest and in transit",
                    color: .green
                )

                PrivacySummaryCard(
                    icon: "person.crop.circle.badge.xmark",
                    title: "No Selling",
                    description: "We never sell your personal data",
                    color: .blue
                )

                PrivacySummaryCard(
                    icon: "trash.fill",
                    title: "Deletable",
                    description: "Delete your data anytime",
                    color: .orange
                )

                PrivacySummaryCard(
                    icon: "eye.slash.fill",
                    title: "Minimal",
                    description: "We collect only what's needed",
                    color: .purple
                )
            }
        }
    }

    private var privacyContent: some View {
        VStack(alignment: .leading, spacing: 24) {
            LegalSection(
                number: "1",
                title: "Information We Collect",
                icon: "tray.full.fill",
                iconColor: .blue
            ) {
                Text("We collect information you provide directly and information collected automatically:")
                    .legalBodyStyle()

                PrivacySubsection(title: "Information You Provide") {
                    BulletList(items: [
                        "Account information (name, email via Sign in with Apple)",
                        "Receipt images and scanned documents",
                        "Transaction data and expense categories",
                        "Notes and descriptions you add",
                        "Contact information for expense attendees"
                    ])
                }

                PrivacySubsection(title: "Automatically Collected") {
                    BulletList(items: [
                        "Device information (model, OS version)",
                        "App usage analytics",
                        "Crash reports and diagnostics",
                        "Location data (only when scanning, if permitted)"
                    ])
                }

                PrivacySubsection(title: "Third-Party Integrations") {
                    BulletList(items: [
                        "Gmail: Email content for receipt extraction (read-only)",
                        "Google Calendar: Event data for expense context",
                        "Plaid: Bank transaction data (read-only, no credentials stored)",
                        "Sign in with Apple: Authentication only, minimal data"
                    ])
                }
            }

            LegalSection(
                number: "2",
                title: "How We Use Your Information",
                icon: "gearshape.fill",
                iconColor: .purple
            ) {
                Text("We use your information to:")
                    .legalBodyStyle()

                BulletList(items: [
                    "Provide and maintain the TallyUps service",
                    "Process and categorize your receipts and expenses",
                    "Match receipts to bank transactions",
                    "Generate expense reports",
                    "Improve our OCR and categorization accuracy",
                    "Send you service-related notifications",
                    "Respond to your support requests",
                    "Detect and prevent fraud or abuse"
                ])

                Text("We do NOT use your data for advertising purposes or share it with advertisers.")
                    .legalBodyStyle()
                    .fontWeight(.medium)
                    .padding(.top, 8)
            }

            LegalSection(
                number: "3",
                title: "Data Storage and Security",
                icon: "server.rack",
                iconColor: .green
            ) {
                Text("Your data is protected with industry-standard security measures:")
                    .legalBodyStyle()

                BulletList(items: [
                    "AES-256 encryption for data at rest",
                    "TLS 1.3 encryption for data in transit",
                    "Secure cloud storage on Cloudflare R2",
                    "Regular security audits and penetration testing",
                    "Access controls and authentication",
                    "Automated backups with encryption"
                ])

                PrivacySubsection(title: "Data Retention") {
                    Text("We retain your data for as long as your account is active. Upon account deletion, your data is permanently removed within 30 days.")
                        .legalBodyStyle()
                }
            }

            LegalSection(
                number: "4",
                title: "Data Sharing",
                icon: "arrow.left.arrow.right",
                iconColor: .orange
            ) {
                Text("We share your information only in these circumstances:")
                    .legalBodyStyle()

                BulletList(items: [
                    "With your consent or at your direction",
                    "With service providers who assist our operations (under strict confidentiality)",
                    "To comply with legal obligations",
                    "To protect our rights, privacy, safety, or property",
                    "In connection with a merger, acquisition, or sale of assets"
                ])

                Text("We never sell your personal information to third parties.")
                    .legalBodyStyle()
                    .fontWeight(.semibold)
                    .foregroundColor(.tallyAccent)
                    .padding(.top, 8)
            }

            LegalSection(
                number: "5",
                title: "Third-Party Services",
                icon: "link.circle.fill",
                iconColor: .cyan
            ) {
                Text("When you connect third-party services, their privacy policies also apply:")
                    .legalBodyStyle()

                VStack(alignment: .leading, spacing: 12) {
                    ThirdPartyServiceRow(
                        name: "Plaid",
                        description: "Bank data aggregation",
                        url: "https://plaid.com/legal"
                    )
                    ThirdPartyServiceRow(
                        name: "Google",
                        description: "Gmail & Calendar integration",
                        url: "https://policies.google.com/privacy"
                    )
                    ThirdPartyServiceRow(
                        name: "Apple",
                        description: "Sign in with Apple",
                        url: "https://apple.com/legal/privacy"
                    )
                    ThirdPartyServiceRow(
                        name: "Cloudflare",
                        description: "Cloud storage (R2)",
                        url: "https://cloudflare.com/privacypolicy"
                    )
                }
                .padding(.top, 8)
            }

            LegalSection(
                number: "6",
                title: "Cookies and Tracking",
                icon: "chart.bar.fill",
                iconColor: .indigo
            ) {
                Text("Our mobile app does not use cookies. Our web interface may use:")
                    .legalBodyStyle()

                BulletList(items: [
                    "Session cookies for authentication (essential)",
                    "Preference cookies for your settings",
                    "Analytics to improve service quality"
                ])

                Text("We do not use advertising trackers or share data with ad networks.")
                    .legalBodyStyle()
                    .padding(.top, 8)
            }

            LegalSection(
                number: "7",
                title: "Children's Privacy",
                icon: "figure.child",
                iconColor: .pink
            ) {
                Text("TallyUps is not intended for users under 13 years of age. We do not knowingly collect personal information from children under 13.")
                    .legalBodyStyle()

                Text("If you become aware that a child has provided us with personal information, please contact us and we will take steps to delete such information.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "8",
                title: "International Data Transfers",
                icon: "globe",
                iconColor: .blue
            ) {
                Text("Your information may be transferred to and processed in countries other than your own. We ensure appropriate safeguards are in place for such transfers.")
                    .legalBodyStyle()

                Text("For EU/EEA residents, transfers are made in compliance with GDPR requirements using Standard Contractual Clauses where applicable.")
                    .legalBodyStyle()
            }

            LegalSection(
                number: "9",
                title: "Changes to Privacy Policy",
                icon: "arrow.triangle.2.circlepath",
                iconColor: .purple
            ) {
                Text("We may update this Privacy Policy from time to time. We will notify you of material changes by:")
                    .legalBodyStyle()

                BulletList(items: [
                    "Updating the \"Last updated\" date",
                    "Sending an in-app notification",
                    "Emailing you (for significant changes)"
                ])
            }

            LegalSection(
                number: "10",
                title: "Contact Us",
                icon: "envelope.fill",
                iconColor: .tallyAccent
            ) {
                Text("For privacy-related questions or to exercise your data rights:")
                    .legalBodyStyle()

                VStack(alignment: .leading, spacing: 8) {
                    HStack {
                        Image(systemName: "envelope")
                            .foregroundColor(.tallyAccent)
                        Text("privacy@tallyups.com")
                            .foregroundColor(.primary)
                    }
                    HStack {
                        Image(systemName: "globe")
                            .foregroundColor(.tallyAccent)
                        Text("https://tallyups.com/privacy")
                            .foregroundColor(.primary)
                    }
                }
                .font(.subheadline)
                .padding(.top, 8)
            }
        }
    }

    private var dataRightsSection: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text("Your Data Rights")
                .font(.title2)
                .fontWeight(.bold)
                .foregroundColor(.primary)

            Text("You have the right to:")
                .legalBodyStyle()

            VStack(spacing: 12) {
                DataRightRow(
                    icon: "eye",
                    title: "Access",
                    description: "Request a copy of your data"
                )
                DataRightRow(
                    icon: "pencil",
                    title: "Correction",
                    description: "Update inaccurate information"
                )
                DataRightRow(
                    icon: "trash",
                    title: "Deletion",
                    description: "Delete your account and data"
                )
                DataRightRow(
                    icon: "square.and.arrow.up",
                    title: "Portability",
                    description: "Export your data in standard formats"
                )
                DataRightRow(
                    icon: "hand.raised",
                    title: "Objection",
                    description: "Object to certain data processing"
                )
            }

            Text("To exercise these rights, use the Settings menu in the app or contact privacy@tallyups.com")
                .font(.caption)
                .foregroundColor(.secondary)
                .padding(.top, 8)
        }
        .padding(.vertical, 20)
        .padding(.horizontal, 16)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color(.systemBackground))
                .shadow(color: .black.opacity(0.05), radius: 10, x: 0, y: 5)
        )
    }

    private var formattedDate: String {
        let formatter = DateFormatter()
        formatter.dateStyle = .long
        return formatter.string(from: Date())
    }
}

// MARK: - Supporting Views

struct AnimatedGradientBackground: View {
    @State private var animateGradient = false

    var body: some View {
        LinearGradient(
            colors: [
                Color(.systemBackground),
                Color.tallyAccent.opacity(0.03),
                Color(.systemBackground)
            ],
            startPoint: animateGradient ? .topLeading : .bottomTrailing,
            endPoint: animateGradient ? .bottomTrailing : .topLeading
        )
        .ignoresSafeArea()
        .onAppear {
            withAnimation(.easeInOut(duration: 5).repeatForever(autoreverses: true)) {
                animateGradient.toggle()
            }
        }
    }
}

struct LegalSection<Content: View>: View {
    let number: String
    let title: String
    let icon: String
    let iconColor: Color
    @ViewBuilder let content: Content

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            HStack(spacing: 12) {
                ZStack {
                    Circle()
                        .fill(iconColor.opacity(0.15))
                        .frame(width: 44, height: 44)

                    Image(systemName: icon)
                        .font(.system(size: 18, weight: .semibold))
                        .foregroundColor(iconColor)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text("Section \(number)")
                        .font(.caption)
                        .foregroundColor(.secondary)

                    Text(title)
                        .font(.headline)
                        .foregroundColor(.primary)
                }
            }

            VStack(alignment: .leading, spacing: 12) {
                content
            }
            .padding(.leading, 56)
        }
        .padding(.vertical, 16)
        .padding(.horizontal, 16)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color(.secondarySystemBackground))
        )
    }
}

struct BulletList: View {
    let items: [String]

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            ForEach(items, id: \.self) { item in
                HStack(alignment: .top, spacing: 10) {
                    Circle()
                        .fill(Color.tallyAccent)
                        .frame(width: 6, height: 6)
                        .padding(.top, 6)

                    Text(item)
                        .font(.subheadline)
                        .foregroundColor(.secondary)
                }
            }
        }
    }
}

struct PrivacySummaryCard: View {
    let icon: String
    let title: String
    let description: String
    let color: Color

    var body: some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(color.opacity(0.15))
                    .frame(width: 50, height: 50)

                Image(systemName: icon)
                    .font(.system(size: 20, weight: .semibold))
                    .foregroundColor(color)
            }

            Text(title)
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundColor(.primary)

            Text(description)
                .font(.caption)
                .foregroundColor(.secondary)
                .multilineTextAlignment(.center)
                .lineLimit(2)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .padding(.horizontal, 12)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color(.secondarySystemBackground))
        )
    }
}

struct PrivacySubsection: View {
    let title: String
    @ViewBuilder var content: () -> AnyView

    init(title: String, @ViewBuilder content: @escaping () -> some View) {
        self.title = title
        self.content = { AnyView(content()) }
    }

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline)
                .fontWeight(.semibold)
                .foregroundColor(.primary)

            content()
        }
        .padding(.top, 8)
    }
}

struct ThirdPartyServiceRow: View {
    let name: String
    let description: String
    let url: String

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text(name)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.primary)

                Text(description)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }

            Spacer()

            if let link = URL(string: url) {
                Link(destination: link) {
                    Image(systemName: "arrow.up.right.circle.fill")
                        .foregroundColor(.tallyAccent)
                }
            }
        }
        .padding(.vertical, 8)
        .padding(.horizontal, 12)
        .background(
            RoundedRectangle(cornerRadius: 10)
                .fill(Color(.tertiarySystemBackground))
        )
    }
}

struct DataRightRow: View {
    let icon: String
    let title: String
    let description: String

    var body: some View {
        HStack(spacing: 12) {
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

            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.secondary)
        }
        .padding(.vertical, 8)
    }
}

// MARK: - Text Style Extension

extension Text {
    func legalBodyStyle() -> some View {
        self
            .font(.subheadline)
            .foregroundColor(.secondary)
            .fixedSize(horizontal: false, vertical: true)
    }
}

// MARK: - Previews

#Preview("Terms of Service") {
    TermsOfServiceView()
}

#Preview("Terms with Accept") {
    TermsOfServiceView(showAcceptButton: true, onAccept: {
        print("Accepted!")
    })
}

#Preview("Privacy Policy") {
    PrivacyPolicyView()
}

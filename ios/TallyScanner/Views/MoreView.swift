import SwiftUI

struct MoreView: View {
    @EnvironmentObject var authService: AuthService

    var body: some View {
        NavigationStack {
            List {
                // Quick Stats Section
                quickStatsSection

                // Features Section
                featuresSection

                // Tools Section
                toolsSection

                // Settings Section
                settingsSection
            }
            .navigationTitle("More")
            .navigationBarTitleDisplayMode(.large)
        }
    }

    // MARK: - Quick Stats Section

    private var quickStatsSection: some View {
        Section {
            NavigationLink {
                AnalyticsDashboardView()
            } label: {
                HStack(spacing: 16) {
                    ZStack {
                        RoundedRectangle(cornerRadius: 12)
                            .fill(
                                LinearGradient(
                                    colors: [Color.tallyAccent, Color.tallyAccent.opacity(0.7)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                )
                            )
                            .frame(width: 56, height: 56)

                        Image(systemName: "chart.bar.fill")
                            .font(.system(size: 24, weight: .semibold))
                            .foregroundColor(.white)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Analytics Dashboard")
                            .font(.headline)
                            .foregroundColor(.primary)

                        Text("Spending trends & insights")
                            .font(.subheadline)
                            .foregroundColor(.secondary)
                    }

                    Spacer()
                }
                .padding(.vertical, 8)
            }
        } header: {
            Text("Insights")
        }
    }

    // MARK: - Features Section

    private var featuresSection: some View {
        Section {
            // Contacts
            NavigationLink {
                ContactsView()
            } label: {
                FeatureRow(
                    icon: "person.2.fill",
                    iconColor: .blue,
                    title: "Contacts",
                    subtitle: "Manage your contacts"
                )
            }

            // Smart Contacts
            NavigationLink {
                SmartContactsView()
            } label: {
                FeatureRow(
                    icon: "person.crop.circle.badge.checkmark",
                    iconColor: .green,
                    title: "Smart Contacts",
                    subtitle: "AI-powered contact matching"
                )
            }

            // Projects
            NavigationLink {
                ProjectsView()
            } label: {
                FeatureRow(
                    icon: "folder.fill",
                    iconColor: .orange,
                    title: "Projects",
                    subtitle: "Organize expenses by project"
                )
            }

            // Reports
            NavigationLink {
                ReportsView()
            } label: {
                FeatureRow(
                    icon: "chart.bar.doc.horizontal.fill",
                    iconColor: .purple,
                    title: "Reports",
                    subtitle: "Generate expense reports"
                )
            }
        } header: {
            Text("Features")
        }
    }

    // MARK: - Tools Section

    private var toolsSection: some View {
        Section {
            // Email Rules
            NavigationLink {
                EmailMappingView()
            } label: {
                FeatureRow(
                    icon: "envelope.badge.fill",
                    iconColor: .red,
                    title: "Email Rules",
                    subtitle: "Auto-categorize by sender"
                )
            }

            // Connected Services
            NavigationLink {
                ConnectedServicesView()
            } label: {
                FeatureRow(
                    icon: "link.circle.fill",
                    iconColor: .cyan,
                    title: "Connected Services",
                    subtitle: "Gmail, Calendar, Banks"
                )
            }
        } header: {
            Text("Tools")
        }
    }

    // MARK: - Settings Section

    private var settingsSection: some View {
        Section {
            NavigationLink {
                SettingsView()
            } label: {
                HStack(spacing: 12) {
                    ZStack {
                        Circle()
                            .fill(Color.gray.opacity(0.2))
                            .frame(width: 36, height: 36)

                        Image(systemName: "gearshape.fill")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundColor(.gray)
                    }

                    Text("Settings")
                        .font(.subheadline)
                        .fontWeight(.medium)
                }
                .padding(.vertical, 4)
            }
        }
    }
}

// MARK: - Feature Row

private struct FeatureRow: View {
    let icon: String
    let iconColor: Color
    let title: String
    let subtitle: String

    var body: some View {
        HStack(spacing: 12) {
            ZStack {
                Circle()
                    .fill(iconColor.opacity(0.15))
                    .frame(width: 36, height: 36)

                Image(systemName: icon)
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundColor(iconColor)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.subheadline)
                    .fontWeight(.medium)
                    .foregroundColor(.primary)

                Text(subtitle)
                    .font(.caption)
                    .foregroundColor(.secondary)
            }
        }
        .padding(.vertical, 4)
    }
}

#Preview {
    MoreView()
        .environmentObject(AuthService.shared)
}

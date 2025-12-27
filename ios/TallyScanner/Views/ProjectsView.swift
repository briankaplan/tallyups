import SwiftUI

/// View for managing expense projects
struct ProjectsView: View {
    @StateObject private var projectService = ProjectService.shared
    @State private var showingCreateProject = false
    @State private var selectedProject: Project?
    @State private var searchText = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                if projectService.isLoading && projectService.projects.isEmpty {
                    ProgressView()
                        .progressViewStyle(CircularProgressViewStyle(tint: .tallyAccent))
                } else if projectService.projects.isEmpty {
                    emptyState
                } else {
                    projectsList
                }
            }
            .navigationTitle("Projects")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .primaryAction) {
                    Button(action: { showingCreateProject = true }) {
                        Image(systemName: "plus.circle.fill")
                            .foregroundColor(.tallyAccent)
                    }
                }
            }
            .searchable(text: $searchText, prompt: "Search projects")
            .sheet(isPresented: $showingCreateProject) {
                CreateProjectView()
                    .environmentObject(projectService)
            }
            .sheet(item: $selectedProject) { project in
                ProjectDetailView(project: project)
                    .environmentObject(projectService)
            }
            .refreshable {
                await projectService.loadProjects()
            }
            .task {
                await projectService.loadIfNeeded()
            }
        }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: 24) {
            Image(systemName: "folder.fill.badge.plus")
                .font(.system(size: 64))
                .foregroundColor(.gray)

            VStack(spacing: 8) {
                Text("No Projects Yet")
                    .font(.title2.bold())
                    .foregroundColor(.white)

                Text("Create projects to organize expenses\nfor clients, trips, or business purposes.")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
            }

            Button(action: { showingCreateProject = true }) {
                HStack {
                    Image(systemName: "plus.circle.fill")
                    Text("Create Project")
                }
                .font(.headline)
                .foregroundColor(.black)
                .padding(.horizontal, 24)
                .padding(.vertical, 14)
                .background(Color.tallyAccent)
                .cornerRadius(12)
            }
        }
        .padding()
    }

    // MARK: - Projects List

    private var projectsList: some View {
        List {
            // Active Projects
            if !activeProjects.isEmpty {
                Section("Active Projects") {
                    ForEach(activeProjects) { project in
                        ProjectRow(project: project)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                selectedProject = project
                            }
                    }
                }
                .listRowBackground(Color.tallyCard)
            }

            // Archived Projects
            if !archivedProjects.isEmpty {
                Section("Archived") {
                    ForEach(archivedProjects) { project in
                        ProjectRow(project: project)
                            .opacity(0.6)
                            .contentShape(Rectangle())
                            .onTapGesture {
                                selectedProject = project
                            }
                    }
                }
                .listRowBackground(Color.tallyCard)
            }

            // Quick Templates
            Section("Quick Create") {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 12) {
                        ForEach(Project.templates, id: \.name) { template in
                            TemplateButton(template: template) {
                                Task {
                                    await projectService.createProject(
                                        name: template.name,
                                        description: template.description,
                                        color: template.color,
                                        icon: template.icon
                                    )
                                }
                            }
                        }
                    }
                    .padding(.horizontal, 4)
                    .padding(.vertical, 8)
                }
            }
            .listRowBackground(Color.clear)
            .listRowInsets(EdgeInsets())
        }
        .listStyle(.insetGrouped)
        .scrollContentBackground(.hidden)
    }

    // MARK: - Filtered Projects

    private var filteredProjects: [Project] {
        if searchText.isEmpty {
            return projectService.projects
        }
        return projectService.projects.filter {
            $0.name.localizedCaseInsensitiveContains(searchText) ||
            ($0.description?.localizedCaseInsensitiveContains(searchText) ?? false)
        }
    }

    private var activeProjects: [Project] {
        filteredProjects.filter { $0.isActive }
    }

    private var archivedProjects: [Project] {
        filteredProjects.filter { !$0.isActive }
    }
}

// MARK: - Project Row

struct ProjectRow: View {
    let project: Project

    var body: some View {
        HStack(spacing: 16) {
            // Icon
            ZStack {
                Circle()
                    .fill(project.swiftUIColor.opacity(0.2))
                    .frame(width: 44, height: 44)

                Image(systemName: project.icon)
                    .foregroundColor(project.swiftUIColor)
            }

            // Info
            VStack(alignment: .leading, spacing: 4) {
                Text(project.name)
                    .font(.headline)
                    .foregroundColor(.white)

                HStack(spacing: 8) {
                    Label("\(project.transactionCount)", systemImage: "doc.text")
                        .font(.caption)
                        .foregroundColor(.gray)

                    Text(project.formattedTotalSpent)
                        .font(.caption.bold())
                        .foregroundColor(.gray)
                }
            }

            Spacer()

            // Budget Progress
            if let progress = project.budgetProgress {
                CircularProgressView(
                    progress: progress,
                    color: project.isOverBudget ? .red : project.swiftUIColor
                )
                .frame(width: 36, height: 36)
            }

            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding(.vertical, 4)
    }
}

// MARK: - Circular Progress View

struct CircularProgressView: View {
    let progress: Double
    let color: Color

    var body: some View {
        ZStack {
            Circle()
                .stroke(color.opacity(0.2), lineWidth: 3)

            Circle()
                .trim(from: 0, to: progress)
                .stroke(color, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                .rotationEffect(.degrees(-90))

            Text("\(Int(progress * 100))%")
                .font(.system(size: 10, weight: .bold))
                .foregroundColor(color)
        }
    }
}

// MARK: - Template Button

struct TemplateButton: View {
    let template: Project
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(Color(hex: template.color)?.opacity(0.2) ?? Color.gray.opacity(0.2))
                        .frame(width: 48, height: 48)

                    Image(systemName: template.icon)
                        .foregroundColor(Color(hex: template.color) ?? .gray)
                }

                Text(template.name)
                    .font(.caption)
                    .foregroundColor(.white)
                    .lineLimit(1)
            }
            .frame(width: 80)
            .padding(.vertical, 12)
            .background(Color.tallyCard)
            .cornerRadius(12)
        }
    }
}

// MARK: - Create Project View

struct CreateProjectView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var projectService: ProjectService

    @State private var name = ""
    @State private var description = ""
    @State private var selectedColor = "#00FF88"
    @State private var selectedIcon = "folder.fill"
    @State private var hasBudget = false
    @State private var budget = ""
    @State private var hasDateRange = false
    @State private var startDate = Date()
    @State private var endDate = Date().addingTimeInterval(30 * 24 * 60 * 60)
    @State private var isCreating = false

    var body: some View {
        NavigationStack {
            Form {
                // Basic Info
                Section("Project Details") {
                    TextField("Project Name", text: $name)

                    TextField("Description (optional)", text: $description)
                }
                .listRowBackground(Color.tallyCard)

                // Icon Selection
                Section("Icon") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 12) {
                        ForEach(Project.availableIcons, id: \.self) { icon in
                            Button(action: { selectedIcon = icon }) {
                                ZStack {
                                    Circle()
                                        .fill(selectedIcon == icon ? Color(hex: selectedColor)?.opacity(0.3) ?? Color.gray.opacity(0.3) : Color.gray.opacity(0.1))
                                        .frame(width: 44, height: 44)

                                    Image(systemName: icon)
                                        .foregroundColor(selectedIcon == icon ? (Color(hex: selectedColor) ?? .tallyAccent) : .gray)
                                }
                            }
                        }
                    }
                    .padding(.vertical, 8)
                }
                .listRowBackground(Color.tallyCard)

                // Color Selection
                Section("Color") {
                    LazyVGrid(columns: Array(repeating: GridItem(.flexible()), count: 6), spacing: 12) {
                        ForEach(Project.availableColors, id: \.self) { color in
                            Button(action: { selectedColor = color }) {
                                ZStack {
                                    Circle()
                                        .fill(Color(hex: color) ?? .gray)
                                        .frame(width: 32, height: 32)

                                    if selectedColor == color {
                                        Image(systemName: "checkmark")
                                            .font(.caption.bold())
                                            .foregroundColor(.white)
                                    }
                                }
                            }
                        }
                    }
                    .padding(.vertical, 8)
                }
                .listRowBackground(Color.tallyCard)

                // Budget
                Section {
                    Toggle("Set Budget", isOn: $hasBudget)

                    if hasBudget {
                        HStack {
                            Text("$")
                                .foregroundColor(.gray)
                            TextField("Amount", text: $budget)
                                .keyboardType(.decimalPad)
                        }
                    }
                }
                .listRowBackground(Color.tallyCard)

                // Date Range
                Section {
                    Toggle("Set Date Range", isOn: $hasDateRange)

                    if hasDateRange {
                        DatePicker("Start", selection: $startDate, displayedComponents: .date)
                        DatePicker("End", selection: $endDate, displayedComponents: .date)
                    }
                }
                .listRowBackground(Color.tallyCard)
            }
            .scrollContentBackground(.hidden)
            .background(Color.tallyBackground)
            .navigationTitle("New Project")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }

                ToolbarItem(placement: .confirmationAction) {
                    Button("Create") {
                        createProject()
                    }
                    .disabled(name.isEmpty || isCreating)
                }
            }
        }
    }

    private func createProject() {
        isCreating = true

        Task {
            _ = await projectService.createProject(
                name: name,
                description: description.isEmpty ? nil : description,
                color: selectedColor,
                icon: selectedIcon,
                budget: hasBudget ? Double(budget) : nil,
                startDate: hasDateRange ? startDate : nil,
                endDate: hasDateRange ? endDate : nil
            )

            dismiss()
        }
    }
}

// MARK: - Project Detail View

struct ProjectDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var projectService: ProjectService

    let project: Project
    @State private var transactions: [Transaction] = []
    @State private var isLoading = true
    @State private var showingEditSheet = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 24) {
                        // Header
                        projectHeader

                        // Stats
                        statsSection

                        // Transactions
                        transactionsSection
                    }
                    .padding()
                }
            }
            .navigationTitle(project.name)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Done") { dismiss() }
                }

                ToolbarItem(placement: .primaryAction) {
                    Menu {
                        Button(action: { showingEditSheet = true }) {
                            Label("Edit", systemImage: "pencil")
                        }

                        if project.isActive {
                            Button(action: archiveProject) {
                                Label("Archive", systemImage: "archivebox")
                            }
                        }

                        Button(role: .destructive, action: deleteProject) {
                            Label("Delete", systemImage: "trash")
                        }
                    } label: {
                        Image(systemName: "ellipsis.circle")
                    }
                }
            }
            .task {
                await loadTransactions()
            }
        }
    }

    private var projectHeader: some View {
        VStack(spacing: 16) {
            ZStack {
                Circle()
                    .fill(project.swiftUIColor.opacity(0.2))
                    .frame(width: 80, height: 80)

                Image(systemName: project.icon)
                    .font(.system(size: 36))
                    .foregroundColor(project.swiftUIColor)
            }

            if let description = project.description {
                Text(description)
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
            }

            if let dateRange = project.dateRangeText {
                HStack {
                    Image(systemName: "calendar")
                    Text(dateRange)
                }
                .font(.caption)
                .foregroundColor(.gray)
            }
        }
    }

    private var statsSection: some View {
        VStack(spacing: 16) {
            HStack(spacing: 16) {
                ProjectStatCard(
                    title: "Total Spent",
                    value: project.formattedTotalSpent,
                    color: project.swiftUIColor
                )

                ProjectStatCard(
                    title: "Transactions",
                    value: "\(project.transactionCount)",
                    color: .blue
                )
            }

            if let budget = project.budget, let remaining = project.budgetRemaining {
                VStack(spacing: 8) {
                    HStack {
                        Text("Budget")
                            .font(.subheadline)
                            .foregroundColor(.gray)
                        Spacer()
                        Text(project.formattedBudget ?? "")
                            .font(.subheadline.bold())
                            .foregroundColor(.white)
                    }

                    ProgressView(value: project.budgetProgress ?? 0)
                        .tint(project.isOverBudget ? .red : project.swiftUIColor)

                    HStack {
                        Text(project.isOverBudget ? "Over budget" : "Remaining")
                            .font(.caption)
                            .foregroundColor(project.isOverBudget ? .red : .gray)
                        Spacer()
                        Text("$\(String(format: "%.2f", remaining))")
                            .font(.caption.bold())
                            .foregroundColor(project.isOverBudget ? .red : project.swiftUIColor)
                    }
                }
                .padding()
                .background(Color.tallyCard)
                .cornerRadius(12)
            }
        }
    }

    private var transactionsSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            Text("Transactions")
                .font(.headline)
                .foregroundColor(.white)

            if isLoading {
                HStack {
                    Spacer()
                    ProgressView()
                    Spacer()
                }
                .padding()
            } else if transactions.isEmpty {
                Text("No transactions yet")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .padding()
            } else {
                ForEach(transactions) { transaction in
                    TransactionRow(transaction: transaction)
                }
            }
        }
    }

    private func loadTransactions() async {
        isLoading = true
        do {
            transactions = try await APIClient.shared.fetchProjectTransactions(projectId: project.id)
        } catch {
            print("Failed to load project transactions: \(error)")
        }
        isLoading = false
    }

    private func archiveProject() {
        Task {
            _ = await projectService.archiveProject(id: project.id)
            dismiss()
        }
    }

    private func deleteProject() {
        Task {
            _ = await projectService.deleteProject(id: project.id)
            dismiss()
        }
    }
}

// MARK: - Project Stat Card

private struct ProjectStatCard: View {
    let title: String
    let value: String
    let color: Color

    var body: some View {
        VStack(spacing: 8) {
            Text(title)
                .font(.caption)
                .foregroundColor(.gray)

            Text(value)
                .font(.title2.bold())
                .foregroundColor(color)
        }
        .frame(maxWidth: .infinity)
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }
}

// MARK: - Transaction Row

private struct TransactionRow: View {
    let transaction: Transaction

    var body: some View {
        HStack {
            VStack(alignment: .leading, spacing: 4) {
                Text(transaction.merchant)
                    .font(.subheadline)
                    .foregroundColor(.white)
                    .lineLimit(1)

                Text(transaction.formattedDate)
                    .font(.caption)
                    .foregroundColor(.gray)
            }

            Spacer()

            Text(transaction.formattedAmount)
                .font(.subheadline.bold())
                .foregroundColor(.white)
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }
}

#Preview {
    ProjectsView()
}

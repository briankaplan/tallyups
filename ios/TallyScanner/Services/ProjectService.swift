import Foundation
import SwiftUI

/// Service for managing expense projects
@MainActor
class ProjectService: ObservableObject {
    static let shared = ProjectService()

    @Published var projects: [Project] = []
    @Published var activeProjects: [Project] = []
    @Published var isLoading = false
    @Published var error: String?

    private init() {}

    // MARK: - Load Projects

    func loadProjects() async {
        guard !isLoading else { return }

        isLoading = true
        error = nil

        do {
            projects = try await APIClient.shared.fetchProjects()
            activeProjects = projects.filter { $0.isActive }
            print("📁 ProjectService: Loaded \(projects.count) projects")
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to load projects: \(error)")
        }

        isLoading = false
    }

    func loadIfNeeded() async {
        if projects.isEmpty {
            await loadProjects()
        }
    }

    // MARK: - CRUD Operations

    func createProject(
        name: String,
        description: String? = nil,
        color: String = "#00FF88",
        icon: String = "folder.fill",
        budget: Double? = nil,
        startDate: Date? = nil,
        endDate: Date? = nil
    ) async -> Project? {
        do {
            let project = try await APIClient.shared.createProject(
                name: name,
                description: description,
                color: color,
                icon: icon,
                budget: budget,
                startDate: startDate,
                endDate: endDate
            )

            projects.append(project)
            if project.isActive {
                activeProjects.append(project)
            }

            print("📁 ProjectService: Created project '\(name)'")
            return project
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to create project: \(error)")
            return nil
        }
    }

    func updateProject(_ project: Project) async -> Bool {
        do {
            let updated = try await APIClient.shared.updateProject(project)

            if let index = projects.firstIndex(where: { $0.id == project.id }) {
                projects[index] = updated
            }

            activeProjects = projects.filter { $0.isActive }
            print("📁 ProjectService: Updated project '\(project.name)'")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to update project: \(error)")
            return false
        }
    }

    func deleteProject(id: String) async -> Bool {
        do {
            try await APIClient.shared.deleteProject(id: id)

            projects.removeAll { $0.id == id }
            activeProjects.removeAll { $0.id == id }

            print("📁 ProjectService: Deleted project \(id)")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to delete project: \(error)")
            return false
        }
    }

    func archiveProject(id: String) async -> Bool {
        guard var project = projects.first(where: { $0.id == id }) else {
            return false
        }

        project.isActive = false
        return await updateProject(project)
    }

    // MARK: - Transaction Assignment

    func assignTransaction(transactionIndex: Int, toProject projectId: String?) async -> Bool {
        do {
            try await APIClient.shared.assignTransactionToProject(
                transactionIndex: transactionIndex,
                projectId: projectId
            )

            // Refresh project stats
            await loadProjects()

            print("📁 ProjectService: Assigned transaction \(transactionIndex) to project \(projectId ?? "none")")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to assign transaction: \(error)")
            return false
        }
    }

    func bulkAssignTransactions(transactionIndexes: [Int], toProject projectId: String) async -> Bool {
        do {
            try await APIClient.shared.bulkAssignTransactionsToProject(
                transactionIndexes: transactionIndexes,
                projectId: projectId
            )

            await loadProjects()

            print("📁 ProjectService: Bulk assigned \(transactionIndexes.count) transactions to project \(projectId)")
            return true
        } catch {
            self.error = error.localizedDescription
            print("📁 ProjectService: Failed to bulk assign: \(error)")
            return false
        }
    }

    // MARK: - Helpers

    func project(withId id: String) -> Project? {
        projects.first { $0.id == id }
    }

    func projectColor(forId id: String?) -> Color {
        guard let id = id, let project = project(withId: id) else {
            return .gray
        }
        return project.swiftUIColor
    }
}

import Foundation
import Contacts
import ContactsUI

/// Service for managing contacts with native iOS Contacts integration
@MainActor
class ContactsService: NSObject, ObservableObject {
    static let shared = ContactsService()

    @Published var contacts: [AppContact] = []
    @Published var recentContacts: [AppContact] = []
    @Published var isLoading = false
    @Published var authorizationStatus: CNAuthorizationStatus = .notDetermined
    @Published var error: String?

    private let contactStore = CNContactStore()

    private override init() {
        super.init()
        checkAuthorizationStatus()
    }

    // MARK: - Authorization

    func checkAuthorizationStatus() {
        authorizationStatus = CNContactStore.authorizationStatus(for: .contacts)
    }

    func requestAccess() async -> Bool {
        do {
            let granted = try await contactStore.requestAccess(for: .contacts)
            await MainActor.run {
                checkAuthorizationStatus()
            }
            return granted
        } catch {
            await MainActor.run {
                self.error = error.localizedDescription
            }
            return false
        }
    }

    // MARK: - Fetch Contacts

    /// Fetch all contacts from device
    func fetchDeviceContacts() async -> [CNContact] {
        guard authorizationStatus == .authorized else { return [] }

        let keysToFetch: [CNKeyDescriptor] = [
            CNContactIdentifierKey as CNKeyDescriptor,
            CNContactGivenNameKey as CNKeyDescriptor,
            CNContactFamilyNameKey as CNKeyDescriptor,
            CNContactOrganizationNameKey as CNKeyDescriptor,
            CNContactJobTitleKey as CNKeyDescriptor,
            CNContactEmailAddressesKey as CNKeyDescriptor,
            CNContactPhoneNumbersKey as CNKeyDescriptor,
            CNContactImageDataKey as CNKeyDescriptor,
            CNContactThumbnailImageDataKey as CNKeyDescriptor,
            CNContactPostalAddressesKey as CNKeyDescriptor,
            CNContactNoteKey as CNKeyDescriptor
        ]

        var results: [CNContact] = []

        do {
            let request = CNContactFetchRequest(keysToFetch: keysToFetch)
            request.sortOrder = .userDefault

            try contactStore.enumerateContacts(with: request) { contact, _ in
                results.append(contact)
            }
        } catch {
            await MainActor.run {
                self.error = "Failed to fetch contacts: \(error.localizedDescription)"
            }
        }

        return results
    }

    /// Sync device contacts with server
    func syncContacts() async {
        await MainActor.run {
            isLoading = true
            error = nil
        }

        // Fetch from device
        let deviceContacts = await fetchDeviceContacts()

        // Fetch from server
        let serverContacts = await fetchServerContacts()

        // Merge and deduplicate
        let merged = mergeContacts(device: deviceContacts, server: serverContacts)

        await MainActor.run {
            contacts = merged
            recentContacts = Array(merged.prefix(10))
            isLoading = false
        }

        // Upload new contacts to server
        await uploadNewContacts(deviceContacts: deviceContacts, serverContacts: serverContacts)
    }

    /// Fetch contacts from server
    func fetchServerContacts() async -> [AppContact] {
        do {
            let serverContacts = try await APIClient.shared.fetchContacts()
            // Convert Contact to AppContact
            return serverContacts.map { contact in
                AppContact(
                    id: contact.id.hashValue,
                    name: contact.name,
                    email: contact.email,
                    phone: contact.phone,
                    company: contact.company,
                    tags: contact.tags ?? []
                )
            }
        } catch {
            await MainActor.run {
                self.error = "Failed to fetch server contacts: \(error.localizedDescription)"
            }
            return []
        }
    }

    /// Search contacts
    func searchContacts(query: String) async -> [AppContact] {
        guard !query.isEmpty else { return contacts }

        let lowercaseQuery = query.lowercased()
        return contacts.filter { contact in
            contact.name.lowercased().contains(lowercaseQuery) ||
            (contact.email?.lowercased().contains(lowercaseQuery) ?? false) ||
            (contact.company?.lowercased().contains(lowercaseQuery) ?? false)
        }
    }

    /// Get suggested contacts for a merchant/transaction
    func suggestContacts(merchant: String, date: Date) async -> [AppContact] {
        do {
            return try await APIClient.shared.suggestContacts(merchant: merchant, date: date)
        } catch {
            return []
        }
    }

    // MARK: - Contact Operations

    /// Create a new contact
    func createContact(_ contact: AppContact) async -> Bool {
        do {
            try await APIClient.shared.createContact(contact)
            await syncContacts()
            return true
        } catch {
            await MainActor.run {
                self.error = "Failed to create contact: \(error.localizedDescription)"
            }
            return false
        }
    }

    /// Update an existing contact
    func updateContact(_ contact: AppContact) async -> Bool {
        do {
            try await APIClient.shared.updateContact(contact)
            await syncContacts()
            return true
        } catch {
            await MainActor.run {
                self.error = "Failed to update contact: \(error.localizedDescription)"
            }
            return false
        }
    }

    /// Delete a contact
    func deleteContact(_ contact: AppContact) async -> Bool {
        do {
            try await APIClient.shared.deleteContact(id: contact.id)
            await MainActor.run {
                contacts.removeAll { $0.id == contact.id }
            }
            return true
        } catch {
            await MainActor.run {
                self.error = "Failed to delete contact: \(error.localizedDescription)"
            }
            return false
        }
    }

    // MARK: - Private Helpers

    private func mergeContacts(device: [CNContact], server: [AppContact]) -> [AppContact] {
        var merged: [AppContact] = server
        let serverEmails = Set(server.compactMap { $0.email?.lowercased() })

        for cnContact in device {
            let email = cnContact.emailAddresses.first?.value as String?

            // Skip if already on server
            if let email = email?.lowercased(), serverEmails.contains(email) {
                continue
            }

            // Convert to AppContact
            let appContact = AppContact(
                id: cnContact.identifier.hashValue,
                name: "\(cnContact.givenName) \(cnContact.familyName)".trimmingCharacters(in: .whitespaces),
                email: email,
                phone: cnContact.phoneNumbers.first?.value.stringValue,
                company: cnContact.organizationName.isEmpty ? nil : cnContact.organizationName,
                tags: ["device"]
            )

            if !appContact.name.isEmpty {
                merged.append(appContact)
            }
        }

        return merged.sorted { $0.name < $1.name }
    }

    private func uploadNewContacts(deviceContacts: [CNContact], serverContacts: [AppContact]) async {
        let serverEmails = Set(serverContacts.compactMap { $0.email?.lowercased() })

        for cnContact in deviceContacts {
            guard let email = cnContact.emailAddresses.first?.value as String?,
                  !serverEmails.contains(email.lowercased()) else {
                continue
            }

            let name = "\(cnContact.givenName) \(cnContact.familyName)".trimmingCharacters(in: .whitespaces)
            guard !name.isEmpty else { continue }

            let appContact = AppContact(
                id: 0,
                name: name,
                email: email,
                phone: cnContact.phoneNumbers.first?.value.stringValue,
                company: cnContact.organizationName.isEmpty ? nil : cnContact.organizationName,
                tags: ["device", "auto-sync"]
            )

            do {
                try await APIClient.shared.createContact(appContact)
            } catch {
                // Silently fail for individual contacts
                continue
            }
        }
    }
}

// MARK: - Contact Picker Delegate

extension ContactsService: CNContactPickerDelegate {
    nonisolated func contactPicker(_ picker: CNContactPickerViewController, didSelect contact: CNContact) {
        Task { @MainActor in
            let appContact = AppContact(
                id: contact.identifier.hashValue,
                name: "\(contact.givenName) \(contact.familyName)".trimmingCharacters(in: .whitespaces),
                email: contact.emailAddresses.first?.value as String?,
                phone: contact.phoneNumbers.first?.value.stringValue,
                company: contact.organizationName.isEmpty ? nil : contact.organizationName,
                tags: ["selected"]
            )

            _ = await createContact(appContact)
        }
    }
}

// MARK: - App Contact Model

struct AppContact: Identifiable, Codable, Hashable {
    let id: Int
    var name: String
    var email: String?
    var phone: String?
    var company: String?
    var tags: [String]

    var displayName: String {
        if !name.isEmpty {
            return name
        } else if let company = company, !company.isEmpty {
            return company
        } else if let email = email {
            return email
        }
        return "Unknown"
    }

    var initials: String {
        let components = name.split(separator: " ")
        if components.count >= 2 {
            return "\(components[0].prefix(1))\(components[1].prefix(1))".uppercased()
        } else if let first = components.first {
            return String(first.prefix(2)).uppercased()
        }
        return "?"
    }

    var avatarColor: String {
        // Generate consistent color based on name
        let colors = ["#FF6B6B", "#4ECDC4", "#45B7D1", "#96CEB4", "#FFEAA7", "#DDA0DD", "#98D8C8", "#F7DC6F"]
        let hash = abs(name.hashValue)
        return colors[hash % colors.count]
    }
}

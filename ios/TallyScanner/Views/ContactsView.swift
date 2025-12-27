import SwiftUI
import Contacts
import ContactsUI

struct ContactsView: View {
    @StateObject private var viewModel = ContactsViewModel()
    @State private var searchText = ""
    @State private var showingAddContact = false
    @State private var showingContactPicker = false
    @State private var selectedContact: AppContact?
    @State private var showingContactDetail = false

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                if viewModel.isLoading && viewModel.contacts.isEmpty {
                    loadingView
                } else if viewModel.contacts.isEmpty && !viewModel.isLoading {
                    emptyStateView
                } else {
                    contactsList
                }
            }
            .navigationTitle("Contacts")
            .searchable(text: $searchText, prompt: "Search contacts")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Menu {
                        Button(action: { showingAddContact = true }) {
                            Label("New Contact", systemImage: "plus")
                        }

                        Button(action: { showingContactPicker = true }) {
                            Label("Import from Contacts", systemImage: "person.crop.circle.badge.plus")
                        }

                        Button(action: { Task { await viewModel.syncContacts() } }) {
                            Label("Sync Contacts", systemImage: "arrow.triangle.2.circlepath")
                        }
                    } label: {
                        Image(systemName: "plus")
                            .font(.title3)
                    }
                }
            }
            .refreshable {
                await viewModel.syncContacts()
            }
            .sheet(isPresented: $showingAddContact) {
                AddContactSheet(viewModel: viewModel)
            }
            .sheet(isPresented: $showingContactPicker) {
                ContactPickerView()
            }
            .sheet(item: $selectedContact) { contact in
                ContactsDetailSheet(contact: contact, viewModel: viewModel)
            }
            .task {
                await viewModel.loadContacts()
            }
            .onChange(of: searchText) { _, newValue in
                Task {
                    await viewModel.search(query: newValue)
                }
            }
        }
    }

    // MARK: - Subviews

    private var loadingView: some View {
        VStack(spacing: 16) {
            ProgressView()
                .scaleEffect(1.5)
            Text("Loading contacts...")
                .foregroundColor(.gray)
        }
    }

    private var emptyStateView: some View {
        VStack(spacing: 24) {
            Image(systemName: "person.2.circle")
                .font(.system(size: 80))
                .foregroundColor(.gray.opacity(0.5))

            VStack(spacing: 8) {
                Text("No Contacts Yet")
                    .font(.title2.bold())
                    .foregroundColor(.white)

                Text("Add contacts to track expense attendees and improve receipt matching.")
                    .font(.subheadline)
                    .foregroundColor(.gray)
                    .multilineTextAlignment(.center)
                    .padding(.horizontal, 32)
            }

            VStack(spacing: 12) {
                Button(action: { showingContactPicker = true }) {
                    Label("Import from Contacts", systemImage: "person.crop.circle.badge.plus")
                        .font(.headline)
                        .foregroundColor(.black)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyAccent)
                        .cornerRadius(12)
                }

                Button(action: { showingAddContact = true }) {
                    Label("Add Manually", systemImage: "plus.circle")
                        .font(.headline)
                        .foregroundColor(.tallyAccent)
                        .frame(maxWidth: .infinity)
                        .padding()
                        .background(Color.tallyCard)
                        .cornerRadius(12)
                }
            }
            .padding(.horizontal, 40)
        }
    }

    private var contactsList: some View {
        ScrollView {
            LazyVStack(spacing: 1) {
                // Recent Section
                if !viewModel.recentContacts.isEmpty && searchText.isEmpty {
                    sectionHeader("Recent")

                    ScrollView(.horizontal, showsIndicators: false) {
                        HStack(spacing: 16) {
                            ForEach(viewModel.recentContacts) { contact in
                                recentContactCard(contact)
                            }
                        }
                        .padding(.horizontal)
                    }
                    .padding(.bottom, 16)
                }

                // All Contacts
                sectionHeader("All Contacts (\(viewModel.filteredContacts.count))")

                ForEach(viewModel.filteredContacts) { contact in
                    ContactRow(contact: contact)
                        .contentShape(Rectangle())
                        .onTapGesture {
                            HapticService.shared.impact(.light)
                            selectedContact = contact
                        }
                }
            }
            .padding(.top)
        }
    }

    private func sectionHeader(_ title: String) -> some View {
        HStack {
            Text(title)
                .font(.headline)
                .foregroundColor(.gray)
            Spacer()
        }
        .padding(.horizontal)
        .padding(.vertical, 8)
    }

    private func recentContactCard(_ contact: AppContact) -> some View {
        VStack(spacing: 8) {
            ZStack {
                Circle()
                    .fill(Color(hex: contact.avatarColor) ?? .tallyAccent)
                    .frame(width: 56, height: 56)

                Text(contact.initials)
                    .font(.title3.bold())
                    .foregroundColor(.white)
            }

            Text(contact.name.split(separator: " ").first.map(String.init) ?? contact.name)
                .font(.caption)
                .foregroundColor(.white)
                .lineLimit(1)
        }
        .frame(width: 70)
        .onTapGesture {
            HapticService.shared.impact(.light)
            selectedContact = contact
        }
    }
}

// MARK: - Contact Row

struct ContactRow: View {
    let contact: AppContact

    var body: some View {
        HStack(spacing: 12) {
            // Avatar
            ZStack {
                Circle()
                    .fill(Color(hex: contact.avatarColor) ?? .tallyAccent)
                    .frame(width: 44, height: 44)

                Text(contact.initials)
                    .font(.headline)
                    .foregroundColor(.white)
            }

            // Info
            VStack(alignment: .leading, spacing: 2) {
                Text(contact.name)
                    .font(.headline)
                    .foregroundColor(.white)

                if let company = contact.company {
                    Text(company)
                        .font(.subheadline)
                        .foregroundColor(.gray)
                } else if let email = contact.email {
                    Text(email)
                        .font(.subheadline)
                        .foregroundColor(.gray)
                }
            }

            Spacer()

            // Tags
            if contact.tags.contains("vip") {
                Image(systemName: "star.fill")
                    .foregroundColor(.yellow)
            }

            Image(systemName: "chevron.right")
                .font(.caption)
                .foregroundColor(.gray)
        }
        .padding()
        .background(Color.tallyCard)
    }
}

// MARK: - Add Contact Sheet

struct AddContactSheet: View {
    @ObservedObject var viewModel: ContactsViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var name = ""
    @State private var email = ""
    @State private var phone = ""
    @State private var company = ""
    @State private var isSaving = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    TextField("Name", text: $name)
                        .textContentType(.name)

                    TextField("Email", text: $email)
                        .textContentType(.emailAddress)
                        .keyboardType(.emailAddress)
                        .autocapitalization(.none)

                    TextField("Phone", text: $phone)
                        .textContentType(.telephoneNumber)
                        .keyboardType(.phonePad)

                    TextField("Company", text: $company)
                        .textContentType(.organizationName)
                }

                Section {
                    Button(action: saveContact) {
                        HStack {
                            Spacer()
                            if isSaving {
                                ProgressView()
                            } else {
                                Text("Save Contact")
                                    .fontWeight(.semibold)
                            }
                            Spacer()
                        }
                    }
                    .disabled(name.isEmpty || isSaving)
                }
            }
            .navigationTitle("New Contact")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                }
            }
        }
    }

    private func saveContact() {
        isSaving = true
        HapticService.shared.impact(.medium)

        Task {
            let contact = AppContact(
                id: 0,
                name: name,
                email: email.isEmpty ? nil : email,
                phone: phone.isEmpty ? nil : phone,
                company: company.isEmpty ? nil : company,
                tags: []
            )

            let success = await viewModel.createContact(contact)

            await MainActor.run {
                isSaving = false
                if success {
                    HapticService.shared.notification(.success)
                    dismiss()
                } else {
                    HapticService.shared.notification(.error)
                }
            }
        }
    }
}

// MARK: - Contacts Detail Sheet

private struct ContactsDetailSheet: View {
    let contact: AppContact
    @ObservedObject var viewModel: ContactsViewModel
    @Environment(\.dismiss) private var dismiss

    @State private var showingDeleteConfirm = false

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Avatar
                    ZStack {
                        Circle()
                            .fill(Color(hex: contact.avatarColor) ?? .tallyAccent)
                            .frame(width: 100, height: 100)

                        Text(contact.initials)
                            .font(.largeTitle.bold())
                            .foregroundColor(.white)
                    }
                    .padding(.top, 20)

                    // Name
                    Text(contact.name)
                        .font(.title.bold())
                        .foregroundColor(.white)

                    if let company = contact.company {
                        Text(company)
                            .foregroundColor(.gray)
                    }

                    // Actions
                    HStack(spacing: 24) {
                        if let email = contact.email {
                            actionButton(icon: "envelope.fill", label: "Email") {
                                if let url = URL(string: "mailto:\(email)") {
                                    UIApplication.shared.open(url)
                                }
                            }
                        }

                        if let phone = contact.phone {
                            actionButton(icon: "phone.fill", label: "Call") {
                                if let url = URL(string: "tel:\(phone)") {
                                    UIApplication.shared.open(url)
                                }
                            }

                            actionButton(icon: "message.fill", label: "Message") {
                                if let url = URL(string: "sms:\(phone)") {
                                    UIApplication.shared.open(url)
                                }
                            }
                        }
                    }
                    .padding(.vertical)

                    // Info Cards
                    VStack(spacing: 12) {
                        if let email = contact.email {
                            infoCard(icon: "envelope", title: "Email", value: email)
                        }

                        if let phone = contact.phone {
                            infoCard(icon: "phone", title: "Phone", value: phone)
                        }

                        if let company = contact.company {
                            infoCard(icon: "building.2", title: "Company", value: company)
                        }
                    }
                    .padding(.horizontal)

                    Spacer()

                    // Delete Button
                    Button(role: .destructive, action: { showingDeleteConfirm = true }) {
                        Label("Delete Contact", systemImage: "trash")
                            .frame(maxWidth: .infinity)
                            .padding()
                    }
                    .padding(.horizontal)
                }
            }
            .background(Color.tallyBackground)
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .alert("Delete Contact?", isPresented: $showingDeleteConfirm) {
                Button("Cancel", role: .cancel) {}
                Button("Delete", role: .destructive) {
                    Task {
                        await viewModel.deleteContact(contact)
                        dismiss()
                    }
                }
            } message: {
                Text("This will permanently delete \(contact.name).")
            }
        }
    }

    private func actionButton(icon: String, label: String, action: @escaping () -> Void) -> some View {
        Button(action: {
            HapticService.shared.impact(.medium)
            action()
        }) {
            VStack(spacing: 8) {
                ZStack {
                    Circle()
                        .fill(Color.tallyAccent.opacity(0.2))
                        .frame(width: 50, height: 50)

                    Image(systemName: icon)
                        .font(.title3)
                        .foregroundColor(.tallyAccent)
                }

                Text(label)
                    .font(.caption)
                    .foregroundColor(.gray)
            }
        }
    }

    private func infoCard(icon: String, title: String, value: String) -> some View {
        HStack {
            Image(systemName: icon)
                .foregroundColor(.tallyAccent)
                .frame(width: 30)

            VStack(alignment: .leading, spacing: 2) {
                Text(title)
                    .font(.caption)
                    .foregroundColor(.gray)

                Text(value)
                    .foregroundColor(.white)
            }

            Spacer()

            Button(action: {
                UIPasteboard.general.string = value
                HapticService.shared.notification(.success)
            }) {
                Image(systemName: "doc.on.doc")
                    .foregroundColor(.gray)
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }
}

// MARK: - Contact Picker View

struct ContactPickerView: UIViewControllerRepresentable {
    @Environment(\.dismiss) private var dismiss

    func makeUIViewController(context: Context) -> CNContactPickerViewController {
        let picker = CNContactPickerViewController()
        picker.delegate = context.coordinator
        return picker
    }

    func updateUIViewController(_ uiViewController: CNContactPickerViewController, context: Context) {}

    func makeCoordinator() -> Coordinator {
        Coordinator(self)
    }

    class Coordinator: NSObject, CNContactPickerDelegate {
        let parent: ContactPickerView

        init(_ parent: ContactPickerView) {
            self.parent = parent
        }

        func contactPickerDidCancel(_ picker: CNContactPickerViewController) {
            parent.dismiss()
        }

        func contactPicker(_ picker: CNContactPickerViewController, didSelect contacts: [CNContact]) {
            Task {
                for contact in contacts {
                    let appContact = AppContact(
                        id: 0,
                        name: "\(contact.givenName) \(contact.familyName)".trimmingCharacters(in: .whitespaces),
                        email: contact.emailAddresses.first?.value as String?,
                        phone: contact.phoneNumbers.first?.value.stringValue,
                        company: contact.organizationName.isEmpty ? nil : contact.organizationName,
                        tags: ["imported"]
                    )

                    _ = await ContactsService.shared.createContact(appContact)
                }

                await MainActor.run {
                    HapticService.shared.notification(.success)
                    parent.dismiss()
                }
            }
        }
    }
}

// MARK: - View Model

@MainActor
class ContactsViewModel: ObservableObject {
    @Published var contacts: [AppContact] = []
    @Published var recentContacts: [AppContact] = []
    @Published var filteredContacts: [AppContact] = []
    @Published var isLoading = false
    @Published var error: String?

    private let service = ContactsService.shared

    func loadContacts() async {
        isLoading = true
        contacts = await service.fetchServerContacts()
        filteredContacts = contacts
        recentContacts = Array(contacts.prefix(5))
        isLoading = false
    }

    func syncContacts() async {
        isLoading = true
        await service.syncContacts()
        contacts = service.contacts
        filteredContacts = contacts
        recentContacts = service.recentContacts
        isLoading = false
    }

    func search(query: String) async {
        if query.isEmpty {
            filteredContacts = contacts
        } else {
            filteredContacts = await service.searchContacts(query: query)
        }
    }

    func createContact(_ contact: AppContact) async -> Bool {
        let success = await service.createContact(contact)
        if success {
            await loadContacts()
        }
        return success
    }

    func deleteContact(_ contact: AppContact) async {
        _ = await service.deleteContact(contact)
        await loadContacts()
    }
}

#Preview {
    ContactsView()
}

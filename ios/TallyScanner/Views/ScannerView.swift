import SwiftUI
import PhotosUI

struct ScannerView: View {
    @StateObject private var viewModel = ScannerViewModel()
    @StateObject private var historyService = ScanHistoryService.shared
    @EnvironmentObject var uploadQueue: UploadQueue

    @State private var showingDocumentScanner = false
    @State private var showingCamera = false
    @State private var showingPhotosPicker = false
    @State private var selectedPhotos: [PhotosPickerItem] = []
    @State private var showingReceiptEditor = false
    @State private var showingHistory = false
    @State private var capturedImage: UIImage?

    var body: some View {
        NavigationStack {
            ZStack {
                Color.tallyBackground.ignoresSafeArea()

                VStack(spacing: 24) {
                    // Header Stats
                    statsHeader

                    Spacer()

                    // Main Scan Options
                    scanOptionsGrid

                    Spacer()

                    // Quick Actions
                    quickActions

                    // Pending Queue Info
                    if uploadQueue.pendingCount > 0 {
                        pendingQueueBanner
                    }
                }
                .padding()
            }
            .navigationTitle("Scan Receipt")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button(action: { showingHistory = true }) {
                        Image(systemName: "clock.arrow.circlepath")
                    }
                }
            }
            .sheet(isPresented: $showingHistory) {
                ScanHistoryView()
            }
            .sheet(isPresented: $showingDocumentScanner) {
                DocumentScannerView { images in
                    handleScannedImages(images)
                }
            }
            .sheet(isPresented: $showingCamera) {
                CameraView { image in
                    handleCapturedImage(image)
                }
            }
            .photosPicker(
                isPresented: $showingPhotosPicker,
                selection: $selectedPhotos,
                maxSelectionCount: 10,
                matching: .images
            )
            .onChange(of: selectedPhotos) { oldValue, newValue in
                Task {
                    await handleSelectedPhotos(newValue)
                }
            }
            .sheet(isPresented: $showingReceiptEditor) {
                if let image = capturedImage {
                    ReceiptEditorView(image: image) { editedReceipt in
                        enqueueReceipt(editedReceipt)
                    }
                }
            }
        }
    }

    // MARK: - Stats Header

    private var statsHeader: some View {
        HStack(spacing: 16) {
            StatCard(
                title: "Today",
                value: "\(historyService.totalScansToday)",
                icon: "doc.text.fill",
                color: .tallyAccent
            )

            StatCard(
                title: "This Week",
                value: "\(historyService.totalScansThisWeek)",
                icon: "calendar",
                color: .blue
            )

            StatCard(
                title: "Pending",
                value: "\(uploadQueue.pendingCount)",
                icon: "clock.fill",
                color: .orange
            )
        }
    }

    // MARK: - Scan Options

    private var scanOptionsGrid: some View {
        VStack(spacing: 20) {
            // Primary: Document Scanner
            Button(action: { showingDocumentScanner = true }) {
                HStack(spacing: 16) {
                    Image(systemName: "doc.viewfinder.fill")
                        .font(.system(size: 40))

                    VStack(alignment: .leading, spacing: 4) {
                        Text("Scan Document")
                            .font(.title2.bold())
                        Text("Auto-detect receipt edges")
                            .font(.subheadline)
                            .foregroundColor(.gray)
                    }

                    Spacer()

                    Image(systemName: "chevron.right")
                        .foregroundColor(.gray)
                }
                .foregroundColor(.white)
                .padding(20)
                .background(Color.tallyCard)
                .cornerRadius(16)
            }

            HStack(spacing: 16) {
                // Quick Photo
                Button(action: { showingCamera = true }) {
                    VStack(spacing: 12) {
                        Image(systemName: "camera.fill")
                            .font(.system(size: 32))
                        Text("Quick Photo")
                            .font(.subheadline.bold())
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
                    .background(Color.tallyCard)
                    .cornerRadius(16)
                }

                // From Library
                Button(action: { showingPhotosPicker = true }) {
                    VStack(spacing: 12) {
                        Image(systemName: "photo.on.rectangle.fill")
                            .font(.system(size: 32))
                        Text("From Photos")
                            .font(.subheadline.bold())
                    }
                    .foregroundColor(.white)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 24)
                    .background(Color.tallyCard)
                    .cornerRadius(16)
                }
            }
        }
    }

    // MARK: - Quick Actions

    private var quickActions: some View {
        VStack(spacing: 12) {
            Text("Recent Merchants")
                .font(.headline)
                .foregroundColor(.gray)
                .frame(maxWidth: .infinity, alignment: .leading)

            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: 12) {
                    ForEach(viewModel.recentMerchants, id: \.self) { merchant in
                        Button(action: {
                            viewModel.presetMerchant = merchant
                            showingCamera = true
                        }) {
                            Text(merchant)
                                .font(.subheadline)
                                .foregroundColor(.white)
                                .padding(.horizontal, 16)
                                .padding(.vertical, 10)
                                .background(Color.tallyCard)
                                .cornerRadius(20)
                        }
                    }
                }
            }
        }
    }

    // MARK: - Pending Queue Banner

    private var pendingQueueBanner: some View {
        HStack {
            if uploadQueue.isUploading {
                ProgressView()
                    .progressViewStyle(CircularProgressViewStyle(tint: .tallyAccent))
            } else {
                Image(systemName: "arrow.up.circle.fill")
                    .foregroundColor(.orange)
            }

            VStack(alignment: .leading, spacing: 2) {
                Text("\(uploadQueue.pendingCount) receipt\(uploadQueue.pendingCount == 1 ? "" : "s") pending upload")
                    .font(.subheadline.bold())

                if !NetworkMonitor.shared.isConnected {
                    Text("Waiting for network connection...")
                        .font(.caption)
                        .foregroundColor(.orange)
                }
            }

            Spacer()

            if let progress = uploadQueue.currentProgress {
                Text("\(Int(progress * 100))%")
                    .font(.caption.bold())
                    .foregroundColor(.tallyAccent)
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(12)
    }

    // MARK: - Image Handling

    private func handleScannedImages(_ images: [UIImage]) {
        showingDocumentScanner = false

        if images.count == 1 {
            capturedImage = images.first
            showingReceiptEditor = true
        } else {
            // Batch upload
            for image in images {
                if let data = ScannerService.shared.compressImage(image) {
                    uploadQueue.enqueueReceipt(
                        imageData: data,
                        merchant: viewModel.presetMerchant
                    )
                }
            }
        }
        viewModel.presetMerchant = nil
    }

    private func handleCapturedImage(_ image: UIImage) {
        showingCamera = false
        capturedImage = image
        showingReceiptEditor = true
    }

    private func handleSelectedPhotos(_ items: [PhotosPickerItem]) async {
        for item in items {
            if let data = try? await item.loadTransferable(type: Data.self),
               let image = UIImage(data: data) {
                await MainActor.run {
                    if items.count == 1 {
                        capturedImage = image
                        showingReceiptEditor = true
                    } else {
                        if let compressedData = ScannerService.shared.compressImage(image) {
                            uploadQueue.enqueueReceipt(imageData: compressedData)
                        }
                    }
                }
            }
        }
        selectedPhotos = []
    }

    private func enqueueReceipt(_ receipt: EditedReceipt) {
        // Add to scan history
        _ = historyService.addScan(
            imageData: receipt.imageData,
            merchant: receipt.merchant,
            amount: receipt.amount,
            date: receipt.date ?? Date()
        )

        // Add to upload queue
        uploadQueue.enqueueReceipt(
            imageData: receipt.imageData,
            merchant: receipt.merchant,
            amount: receipt.amount,
            date: receipt.date,
            category: receipt.category,
            notes: receipt.notes,
            business: receipt.business,
            latitude: ScannerService.shared.currentLocation?.latitude,
            longitude: ScannerService.shared.currentLocation?.longitude
        )
        capturedImage = nil
        showingReceiptEditor = false
    }
}

// MARK: - Stat Card

struct StatCard: View {
    let title: String
    let value: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(spacing: 8) {
            Image(systemName: icon)
                .font(.title2)
                .foregroundColor(color)

            Text(value)
                .font(.title.bold())
                .foregroundColor(.white)

            Text(title)
                .font(.caption)
                .foregroundColor(.gray)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, 16)
        .background(Color.tallyCard)
        .cornerRadius(12)
    }
}

// MARK: - Edited Receipt

struct EditedReceipt {
    let imageData: Data
    var merchant: String?
    var amount: Double?
    var date: Date?
    var category: String?
    var notes: String?
    var business: String?
}

// MARK: - Receipt Editor View

struct ReceiptEditorView: View {
    let image: UIImage
    let onSave: (EditedReceipt) -> Void

    @Environment(\.dismiss) private var dismiss

    @State private var merchant = ""
    @State private var amount = ""
    @State private var date = Date()
    @State private var category = ""
    @State private var notes = ""
    @State private var business = "personal"
    @State private var isProcessingOCR = false
    @State private var ocrResult: OCRResult?

    // Calendar & Contacts
    @State private var calendarEvents: [CalendarEvent] = []
    @State private var suggestedContacts: [Contact] = []
    @State private var selectedAttendees: [Contact] = []
    @State private var isLoadingContext = false
    @State private var showingContactPicker = false

    let categories = ["Food & Dining", "Transportation", "Shopping", "Entertainment", "Travel", "Business", "Other"]
    let businesses = ["personal", "downhome", "mcr"]

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 20) {
                    // Receipt Preview
                    Image(uiImage: image)
                        .resizable()
                        .scaledToFit()
                        .frame(maxHeight: 250)
                        .cornerRadius(12)
                        .overlay {
                            if isProcessingOCR {
                                ZStack {
                                    Color.black.opacity(0.6)
                                    VStack(spacing: 12) {
                                        ProgressView()
                                            .progressViewStyle(CircularProgressViewStyle(tint: .tallyAccent))
                                        Text("Extracting details...")
                                            .font(.subheadline)
                                            .foregroundColor(.white)
                                    }
                                }
                                .cornerRadius(12)
                            }
                        }

                    // Form Fields
                    VStack(spacing: 16) {
                        FormField(title: "Merchant", text: $merchant, placeholder: "Store name")

                        FormField(title: "Amount", text: $amount, placeholder: "0.00", keyboardType: .decimalPad)

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Date")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                            DatePicker("", selection: $date, displayedComponents: .date)
                                .datePickerStyle(.compact)
                                .labelsHidden()
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Category")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                            Picker("Category", selection: $category) {
                                Text("Select...").tag("")
                                ForEach(categories, id: \.self) { cat in
                                    Text(cat).tag(cat)
                                }
                            }
                            .pickerStyle(.menu)
                            .tint(.tallyAccent)
                        }

                        VStack(alignment: .leading, spacing: 8) {
                            Text("Business")
                                .font(.subheadline)
                                .foregroundColor(.gray)
                            Picker("Business", selection: $business) {
                                Text("Personal").tag("personal")
                                Text("Down Home").tag("downhome")
                                Text("MCR").tag("mcr")
                            }
                            .pickerStyle(.segmented)
                        }

                        FormField(title: "Notes", text: $notes, placeholder: "Optional notes")
                    }
                    .padding()
                    .background(Color.tallyCard)
                    .cornerRadius(16)

                    // Calendar Context Section
                    if !calendarEvents.isEmpty {
                        calendarSection
                    }

                    // Attendees Section
                    attendeesSection
                }
                .padding()
            }
            .background(Color.tallyBackground)
            .navigationTitle("Receipt Details")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") {
                        dismiss()
                    }
                }
                ToolbarItem(placement: .confirmationAction) {
                    Button("Save") {
                        saveReceipt()
                    }
                    .bold()
                    .foregroundColor(.tallyAccent)
                }
            }
            .task {
                await performOCR()
                await loadContext()
            }
            .onChange(of: date) { oldValue, newValue in
                Task { await loadContext() }
            }
            .onChange(of: merchant) { oldValue, newValue in
                Task { await loadContactSuggestions() }
            }
        }
    }

    // MARK: - Calendar Section

    private var calendarSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "calendar")
                    .foregroundColor(.tallyAccent)
                Text("Events on this date")
                    .font(.headline)
                Spacer()
            }

            ForEach(calendarEvents.prefix(3)) { event in
                HStack {
                    VStack(alignment: .leading, spacing: 2) {
                        Text(event.title)
                            .font(.subheadline)
                            .foregroundColor(.white)
                        if let location = event.location {
                            Text(location)
                                .font(.caption)
                                .foregroundColor(.gray)
                        }
                    }
                    Spacer()
                    Text(event.formattedTime)
                        .font(.caption)
                        .foregroundColor(.tallyAccent)
                }
                .padding(.vertical, 4)
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    // MARK: - Attendees Section

    private var attendeesSection: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Image(systemName: "person.2.fill")
                    .foregroundColor(.tallyAccent)
                Text("Attendees")
                    .font(.headline)
                Spacer()
                Button(action: { showingContactPicker = true }) {
                    Image(systemName: "plus.circle.fill")
                        .foregroundColor(.tallyAccent)
                }
            }

            // Selected attendees
            if !selectedAttendees.isEmpty {
                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(selectedAttendees) { contact in
                            HStack(spacing: 4) {
                                Text(contact.name)
                                    .font(.caption)
                                Button(action: {
                                    selectedAttendees.removeAll { $0.id == contact.id }
                                }) {
                                    Image(systemName: "xmark.circle.fill")
                                        .font(.caption)
                                }
                            }
                            .padding(.horizontal, 10)
                            .padding(.vertical, 6)
                            .background(Color.tallyAccent.opacity(0.2))
                            .foregroundColor(.tallyAccent)
                            .cornerRadius(15)
                        }
                    }
                }
            }

            // Suggested contacts
            if !suggestedContacts.isEmpty {
                Text("Suggested")
                    .font(.caption)
                    .foregroundColor(.gray)

                ScrollView(.horizontal, showsIndicators: false) {
                    HStack(spacing: 8) {
                        ForEach(suggestedContacts.filter { suggested in
                            !selectedAttendees.contains { $0.id == suggested.id }
                        }.prefix(5)) { contact in
                            Button(action: {
                                selectedAttendees.append(contact)
                            }) {
                                Text(contact.name)
                                    .font(.caption)
                                    .padding(.horizontal, 10)
                                    .padding(.vertical, 6)
                                    .background(Color.tallyBackground)
                                    .foregroundColor(.white)
                                    .cornerRadius(15)
                            }
                        }
                    }
                }
            }
        }
        .padding()
        .background(Color.tallyCard)
        .cornerRadius(16)
    }

    private func performOCR() async {
        isProcessingOCR = true
        defer { isProcessingOCR = false }

        guard let imageData = ScannerService.shared.compressImage(image) else { return }

        do {
            let result = try await APIClient.shared.performOCR(imageData: imageData)
            await MainActor.run {
                ocrResult = result
                if let m = result.merchant, merchant.isEmpty { merchant = m }
                if let a = result.amount { amount = String(format: "%.2f", a) }
                if let d = result.date, let parsedDate = parseDate(d) { date = parsedDate }
            }
        } catch {
            print("OCR failed: \(error)")
        }
    }

    private func parseDate(_ string: String) -> Date? {
        let formatters = ["yyyy-MM-dd", "MM/dd/yyyy", "MM-dd-yyyy", "MMM dd, yyyy"]
        for format in formatters {
            let formatter = DateFormatter()
            formatter.dateFormat = format
            if let date = formatter.date(from: string) {
                return date
            }
        }
        return nil
    }

    private func loadContext() async {
        isLoadingContext = true
        defer { isLoadingContext = false }

        // Load calendar events for this date
        do {
            calendarEvents = try await APIClient.shared.fetchCalendarEvents(date: date)
        } catch {
            print("Failed to load calendar events: \(error)")
        }

        // Load contact suggestions
        await loadContactSuggestions()
    }

    private func loadContactSuggestions() async {
        guard !merchant.isEmpty else { return }

        do {
            suggestedContacts = try await APIClient.shared.suggestContacts(merchant: merchant, date: date)
        } catch {
            print("Failed to load contact suggestions: \(error)")
        }
    }

    private func saveReceipt() {
        guard let imageData = ScannerService.shared.compressImage(image) else { return }

        let receipt = EditedReceipt(
            imageData: imageData,
            merchant: merchant.isEmpty ? nil : merchant,
            amount: Double(amount),
            date: date,
            category: category.isEmpty ? nil : category,
            notes: notes.isEmpty ? nil : notes,
            business: business
        )

        onSave(receipt)
    }
}

// MARK: - Form Field

struct FormField: View {
    let title: String
    @Binding var text: String
    var placeholder: String = ""
    var keyboardType: UIKeyboardType = .default

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.subheadline)
                .foregroundColor(.gray)
            TextField(placeholder, text: $text)
                .keyboardType(keyboardType)
                .padding()
                .background(Color.tallyBackground)
                .cornerRadius(8)
        }
    }
}

#Preview {
    ScannerView()
        .environmentObject(UploadQueue.shared)
        .environmentObject(NetworkMonitor.shared)
}

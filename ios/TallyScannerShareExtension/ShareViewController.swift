import UIKit
import Social
import UniformTypeIdentifiers
import MobileCoreServices

/// Share Extension for importing receipts from other apps
class ShareViewController: UIViewController {

    private let appGroupIdentifier = "group.com.tallyups.scanner"

    private var sharedImages: [UIImage] = []
    private var sharedPDFs: [Data] = []
    private var isProcessing = false

    // MARK: - UI Components

    private lazy var containerView: UIView = {
        let view = UIView()
        view.backgroundColor = UIColor(red: 0.05, green: 0.05, blue: 0.05, alpha: 1)
        view.layer.cornerRadius = 16
        view.layer.masksToBounds = true
        view.translatesAutoresizingMaskIntoConstraints = false
        return view
    }()

    private lazy var headerStack: UIStackView = {
        let stack = UIStackView()
        stack.axis = .horizontal
        stack.alignment = .center
        stack.spacing = 12
        stack.translatesAutoresizingMaskIntoConstraints = false
        return stack
    }()

    private lazy var iconView: UIImageView = {
        let imageView = UIImageView()
        imageView.image = UIImage(systemName: "doc.text.viewfinder")
        imageView.tintColor = UIColor(red: 0, green: 1, blue: 0.53, alpha: 1)
        imageView.contentMode = .scaleAspectFit
        imageView.translatesAutoresizingMaskIntoConstraints = false
        return imageView
    }()

    private lazy var titleLabel: UILabel = {
        let label = UILabel()
        label.text = "TallyUps"
        label.font = .systemFont(ofSize: 20, weight: .bold)
        label.textColor = .white
        label.translatesAutoresizingMaskIntoConstraints = false
        return label
    }()

    private lazy var cancelButton: UIButton = {
        let button = UIButton(type: .system)
        button.setImage(UIImage(systemName: "xmark.circle.fill"), for: .normal)
        button.tintColor = .gray
        button.addTarget(self, action: #selector(cancelTapped), for: .touchUpInside)
        button.translatesAutoresizingMaskIntoConstraints = false
        return button
    }()

    private lazy var statusLabel: UILabel = {
        let label = UILabel()
        label.text = "Processing receipt..."
        label.font = .systemFont(ofSize: 15)
        label.textColor = .lightGray
        label.textAlignment = .center
        label.numberOfLines = 0
        label.translatesAutoresizingMaskIntoConstraints = false
        return label
    }()

    private lazy var previewImageView: UIImageView = {
        let imageView = UIImageView()
        imageView.contentMode = .scaleAspectFit
        imageView.backgroundColor = UIColor(white: 0.1, alpha: 1)
        imageView.layer.cornerRadius = 8
        imageView.layer.masksToBounds = true
        imageView.translatesAutoresizingMaskIntoConstraints = false
        return imageView
    }()

    private lazy var progressView: UIProgressView = {
        let progress = UIProgressView(progressViewStyle: .default)
        progress.progressTintColor = UIColor(red: 0, green: 1, blue: 0.53, alpha: 1)
        progress.trackTintColor = UIColor(white: 0.2, alpha: 1)
        progress.translatesAutoresizingMaskIntoConstraints = false
        return progress
    }()

    private lazy var saveButton: UIButton = {
        let button = UIButton(type: .system)
        button.setTitle("Save Receipt", for: .normal)
        button.setTitleColor(.black, for: .normal)
        button.titleLabel?.font = .systemFont(ofSize: 17, weight: .semibold)
        button.backgroundColor = UIColor(red: 0, green: 1, blue: 0.53, alpha: 1)
        button.layer.cornerRadius = 12
        button.addTarget(self, action: #selector(saveTapped), for: .touchUpInside)
        button.translatesAutoresizingMaskIntoConstraints = false
        return button
    }()

    private lazy var activityIndicator: UIActivityIndicatorView = {
        let indicator = UIActivityIndicatorView(style: .medium)
        indicator.color = .white
        indicator.hidesWhenStopped = true
        indicator.translatesAutoresizingMaskIntoConstraints = false
        return indicator
    }()

    // MARK: - Lifecycle

    override func viewDidLoad() {
        super.viewDidLoad()
        setupUI()
        processSharedItems()
    }

    // MARK: - UI Setup

    private func setupUI() {
        view.backgroundColor = UIColor.black.withAlphaComponent(0.5)

        // Container
        view.addSubview(containerView)
        NSLayoutConstraint.activate([
            containerView.centerXAnchor.constraint(equalTo: view.centerXAnchor),
            containerView.centerYAnchor.constraint(equalTo: view.centerYAnchor),
            containerView.widthAnchor.constraint(equalTo: view.widthAnchor, multiplier: 0.9),
            containerView.heightAnchor.constraint(lessThanOrEqualTo: view.heightAnchor, multiplier: 0.7)
        ])

        // Header
        containerView.addSubview(headerStack)
        headerStack.addArrangedSubview(iconView)
        headerStack.addArrangedSubview(titleLabel)
        headerStack.addArrangedSubview(UIView()) // Spacer
        headerStack.addArrangedSubview(cancelButton)

        NSLayoutConstraint.activate([
            headerStack.topAnchor.constraint(equalTo: containerView.topAnchor, constant: 16),
            headerStack.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            headerStack.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -16),
            iconView.widthAnchor.constraint(equalToConstant: 32),
            iconView.heightAnchor.constraint(equalToConstant: 32),
            cancelButton.widthAnchor.constraint(equalToConstant: 28),
            cancelButton.heightAnchor.constraint(equalToConstant: 28)
        ])

        // Preview
        containerView.addSubview(previewImageView)
        NSLayoutConstraint.activate([
            previewImageView.topAnchor.constraint(equalTo: headerStack.bottomAnchor, constant: 16),
            previewImageView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            previewImageView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -16),
            previewImageView.heightAnchor.constraint(equalToConstant: 200)
        ])

        // Status
        containerView.addSubview(statusLabel)
        containerView.addSubview(activityIndicator)
        NSLayoutConstraint.activate([
            statusLabel.topAnchor.constraint(equalTo: previewImageView.bottomAnchor, constant: 16),
            statusLabel.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            statusLabel.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -16),
            activityIndicator.centerYAnchor.constraint(equalTo: statusLabel.centerYAnchor),
            activityIndicator.trailingAnchor.constraint(equalTo: statusLabel.leadingAnchor, constant: -8)
        ])

        // Progress
        containerView.addSubview(progressView)
        NSLayoutConstraint.activate([
            progressView.topAnchor.constraint(equalTo: statusLabel.bottomAnchor, constant: 12),
            progressView.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            progressView.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -16)
        ])

        // Save Button
        containerView.addSubview(saveButton)
        NSLayoutConstraint.activate([
            saveButton.topAnchor.constraint(equalTo: progressView.bottomAnchor, constant: 20),
            saveButton.leadingAnchor.constraint(equalTo: containerView.leadingAnchor, constant: 16),
            saveButton.trailingAnchor.constraint(equalTo: containerView.trailingAnchor, constant: -16),
            saveButton.heightAnchor.constraint(equalToConstant: 50),
            saveButton.bottomAnchor.constraint(equalTo: containerView.bottomAnchor, constant: -16)
        ])

        // Initial state
        saveButton.isHidden = true
        progressView.isHidden = true
        activityIndicator.startAnimating()
    }

    // MARK: - Process Shared Items

    private func processSharedItems() {
        guard let extensionItems = extensionContext?.inputItems as? [NSExtensionItem] else {
            showError("No items to share")
            return
        }

        let group = DispatchGroup()

        for item in extensionItems {
            guard let attachments = item.attachments else { continue }

            for attachment in attachments {
                // Handle images
                if attachment.hasItemConformingToTypeIdentifier(UTType.image.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.image.identifier, options: nil) { [weak self] item, error in
                        defer { group.leave() }

                        if let url = item as? URL, let data = try? Data(contentsOf: url), let image = UIImage(data: data) {
                            self?.sharedImages.append(image)
                        } else if let image = item as? UIImage {
                            self?.sharedImages.append(image)
                        } else if let data = item as? Data, let image = UIImage(data: data) {
                            self?.sharedImages.append(image)
                        }
                    }
                }

                // Handle PDFs
                if attachment.hasItemConformingToTypeIdentifier(UTType.pdf.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.pdf.identifier, options: nil) { [weak self] item, error in
                        defer { group.leave() }

                        if let url = item as? URL, let data = try? Data(contentsOf: url) {
                            self?.sharedPDFs.append(data)
                        } else if let data = item as? Data {
                            self?.sharedPDFs.append(data)
                        }
                    }
                }

                // Handle URLs (could be image URLs)
                if attachment.hasItemConformingToTypeIdentifier(UTType.url.identifier) {
                    group.enter()
                    attachment.loadItem(forTypeIdentifier: UTType.url.identifier, options: nil) { [weak self] item, error in
                        defer { group.leave() }

                        if let url = item as? URL, url.isFileURL {
                            if let data = try? Data(contentsOf: url), let image = UIImage(data: data) {
                                self?.sharedImages.append(image)
                            }
                        }
                    }
                }
            }
        }

        group.notify(queue: .main) { [weak self] in
            self?.finishProcessing()
        }
    }

    private func finishProcessing() {
        activityIndicator.stopAnimating()

        if !sharedImages.isEmpty {
            // Show preview of first image
            previewImageView.image = sharedImages.first
            let count = sharedImages.count
            statusLabel.text = count == 1 ? "Ready to save 1 receipt" : "Ready to save \(count) receipts"
            saveButton.isHidden = false
            saveButton.setTitle(count == 1 ? "Save Receipt" : "Save \(count) Receipts", for: .normal)
        } else if !sharedPDFs.isEmpty {
            previewImageView.image = UIImage(systemName: "doc.fill")
            previewImageView.tintColor = .lightGray
            let count = sharedPDFs.count
            statusLabel.text = count == 1 ? "Ready to save 1 PDF receipt" : "Ready to save \(count) PDF receipts"
            saveButton.isHidden = false
            saveButton.setTitle(count == 1 ? "Save PDF" : "Save \(count) PDFs", for: .normal)
        } else {
            showError("No supported files found.\nShare images or PDFs of receipts.")
        }
    }

    // MARK: - Actions

    @objc private func cancelTapped() {
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }

    @objc private func saveTapped() {
        guard !isProcessing else { return }
        isProcessing = true

        saveButton.isEnabled = false
        saveButton.setTitle("Saving...", for: .normal)
        progressView.isHidden = false
        statusLabel.text = "Saving to TallyUps..."

        // Save to shared container for main app to process
        saveToSharedContainer()
    }

    private func saveToSharedContainer() {
        guard let containerURL = FileManager.default.containerURL(forSecurityApplicationGroupIdentifier: appGroupIdentifier) else {
            showError("Failed to access shared container")
            return
        }

        let inboxURL = containerURL.appendingPathComponent("SharedReceipts", isDirectory: true)

        do {
            try FileManager.default.createDirectory(at: inboxURL, withIntermediateDirectories: true)
        } catch {
            showError("Failed to create inbox folder")
            return
        }

        let totalItems = sharedImages.count + sharedPDFs.count
        var savedCount = 0

        // Save images
        for (index, image) in sharedImages.enumerated() {
            let filename = "receipt_\(Date().timeIntervalSince1970)_\(index).jpg"
            let fileURL = inboxURL.appendingPathComponent(filename)

            if let data = image.jpegData(compressionQuality: 0.85) {
                do {
                    try data.write(to: fileURL)
                    savedCount += 1
                    updateProgress(Float(savedCount) / Float(totalItems))
                } catch {
                    print("Failed to save image: \(error)")
                }
            }
        }

        // Save PDFs
        for (index, pdfData) in sharedPDFs.enumerated() {
            let filename = "receipt_\(Date().timeIntervalSince1970)_\(index).pdf"
            let fileURL = inboxURL.appendingPathComponent(filename)

            do {
                try pdfData.write(to: fileURL)
                savedCount += 1
                updateProgress(Float(savedCount) / Float(totalItems))
            } catch {
                print("Failed to save PDF: \(error)")
            }
        }

        // Notify main app via UserDefaults
        if let userDefaults = UserDefaults(suiteName: appGroupIdentifier) {
            let pendingCount = userDefaults.integer(forKey: "shared_receipts_pending")
            userDefaults.set(pendingCount + savedCount, forKey: "shared_receipts_pending")
            userDefaults.synchronize()
        }

        // Complete
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) { [weak self] in
            self?.showSuccess(count: savedCount)
        }
    }

    private func updateProgress(_ value: Float) {
        DispatchQueue.main.async { [weak self] in
            self?.progressView.setProgress(value, animated: true)
        }
    }

    private func showSuccess(count: Int) {
        statusLabel.text = count == 1 ? "Receipt saved!" : "\(count) receipts saved!"
        statusLabel.textColor = UIColor(red: 0, green: 1, blue: 0.53, alpha: 1)
        saveButton.setTitle("Done", for: .normal)
        saveButton.isEnabled = true
        saveButton.removeTarget(self, action: #selector(saveTapped), for: .touchUpInside)
        saveButton.addTarget(self, action: #selector(doneTapped), for: .touchUpInside)

        // Haptic
        UINotificationFeedbackGenerator().notificationOccurred(.success)
    }

    @objc private func doneTapped() {
        extensionContext?.completeRequest(returningItems: nil, completionHandler: nil)
    }

    private func showError(_ message: String) {
        statusLabel.text = message
        statusLabel.textColor = .systemRed
        saveButton.isHidden = true
        activityIndicator.stopAnimating()

        // Add a close button after delay
        DispatchQueue.main.asyncAfter(deadline: .now() + 2) { [weak self] in
            self?.cancelTapped()
        }
    }
}

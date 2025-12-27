# TallyScanner iOS App

Native iOS app for receipt scanning that connects to your TallyUps MySQL backend via Flask API.

## Features

- **Document Scanner**: Uses VisionKit for automatic edge detection and document scanning
- **Quick Photo**: Simple camera capture for receipts
- **Photo Import**: Import from photo library (supports batch import)
- **Offline Queue**: Receipts are queued locally and uploaded when network is available
- **Auto OCR**: Automatic text extraction using your server's OCR pipeline (GPT-4o, Gemini, or Ollama)
- **Biometric Auth**: Face ID / Touch ID support for quick unlock
- **Receipt Library**: Browse and manage all your receipts
- **Gmail Inbox**: Review and accept/reject receipts from email
- **Background Upload**: Uploads continue even when app is backgrounded

## Requirements

- iOS 16.0+
- Xcode 15.0+
- Your TallyUps server running (Railway, etc.)

## Setup

1. **Open in Xcode**
   ```bash
   open ios/TallyScanner.xcodeproj
   ```

2. **Configure Server URL**
   - On first launch, tap "Server Settings"
   - Enter your TallyUps server URL (e.g., `https://your-app.railway.app`)
   - Test the connection

3. **Sign In**
   - Use your password, PIN, or API key
   - Enable Face ID/Touch ID for quick access

4. **Start Scanning**
   - Tap "Scan Document" for auto-edge detection
   - Or use "Quick Photo" for simple captures

## Project Structure

```
ios/
├── TallyScanner.xcodeproj/
│   └── project.pbxproj
└── TallyScanner/
    ├── App/
    │   ├── TallyScannerApp.swift      # App entry point
    │   └── ContentView.swift           # Main tab view
    ├── Views/
    │   ├── ScannerView.swift           # Main scanner interface
    │   ├── DocumentScannerView.swift   # VisionKit document scanner
    │   ├── CameraView.swift            # Quick photo capture
    │   ├── LibraryView.swift           # Receipt library browser
    │   ├── InboxView.swift             # Gmail inbox review
    │   ├── LoginView.swift             # Authentication
    │   ├── SettingsView.swift          # App settings
    │   ├── ReceiptDetailView.swift     # Receipt details/edit
    │   ├── ReceiptCardView.swift       # Receipt list item
    │   └── UploadProgressView.swift    # Upload queue indicator
    ├── ViewModels/
    │   ├── ScannerViewModel.swift
    │   └── LibraryViewModel.swift
    ├── Services/
    │   ├── APIClient.swift             # Server communication
    │   ├── AuthService.swift           # Authentication management
    │   ├── ScannerService.swift        # Camera & image processing
    │   ├── UploadQueue.swift           # Offline-first upload queue
    │   ├── KeychainService.swift       # Secure credential storage
    │   └── NetworkMonitor.swift        # Connectivity monitoring
    ├── Models/
    │   ├── Receipt.swift               # Receipt data models
    │   └── Transaction.swift           # Transaction models
    ├── Resources/
    │   └── Assets.xcassets/
    ├── Info.plist
    └── TallyScanner.entitlements
```

## API Endpoints Used

The app communicates with these Flask endpoints:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/mobile-upload` | POST | Upload receipt with auto OCR |
| `/ocr` | POST | Manual OCR extraction |
| `/api/library/receipts` | GET | Fetch receipt library |
| `/api/library/receipts/:id` | PATCH | Update receipt |
| `/api/library/receipts/:id` | DELETE | Delete receipt |
| `/api/incoming/receipts` | GET | Fetch Gmail inbox |
| `/api/incoming/accept` | POST | Accept incoming receipt |
| `/api/incoming/reject` | POST | Reject incoming receipt |
| `/api/incoming/scan` | POST | Trigger Gmail scan |
| `/api/health/pool-status` | GET | Server health check |
| `/login` | POST | Password authentication |
| `/login/pin` | POST | PIN authentication |

## Authentication

The app supports multiple authentication methods:

1. **Password**: Standard password login
2. **PIN**: 4-6 digit PIN for quick access
3. **API Key**: Direct API key in `X-Admin-Key` header
4. **Biometrics**: Face ID / Touch ID (requires initial login)

## Offline Support

Receipts scanned while offline are:
1. Stored in a local queue (UserDefaults)
2. Automatically uploaded when network is restored
3. Retried up to 3 times on failure
4. Preserved across app restarts

## Building for Distribution

1. **Set Team**: In Xcode, select your development team
2. **Configure Bundle ID**: Update `com.tallyups.scanner` if needed
3. **Add App Icon**: Replace placeholder icon in Assets.xcassets
4. **Archive**: Product > Archive
5. **Distribute**: Via App Store Connect or Ad Hoc

## Customization

### Colors
Edit `TallyScannerApp.swift`:
```swift
extension Color {
    static let tallyBackground = Color(red: 0.05, green: 0.05, blue: 0.05)
    static let tallyAccent = Color(red: 0, green: 1, blue: 0.53) // #00ff88
}
```

### Default Business Types
Edit `ReceiptEditorView` in `ScannerView.swift`:
```swift
let businesses = ["personal", "business", "sec"]
```

### Categories
Edit `ReceiptEditorView`:
```swift
let categories = ["Food & Dining", "Transportation", "Shopping", ...]
```

## Troubleshooting

### "Invalid URL" error
- Ensure server URL includes `https://`
- Check server is running and accessible

### Camera not working
- Grant camera permission in Settings > TallyScanner > Camera
- Ensure device has a camera (simulator may have issues)

### Uploads stuck
- Check network connectivity
- Verify server URL is correct
- Check server logs for errors

### OCR not extracting data
- Ensure OpenAI/Gemini API keys are configured on server
- Check image quality (blur, lighting)
- Verify OCR endpoint is responding

## License

Part of the TallyUps expense management system.

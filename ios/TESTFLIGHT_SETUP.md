# TallyScanner TestFlight Setup Guide

## Prerequisites

1. **Apple Developer Account** ($99/year) - https://developer.apple.com
2. **Xcode 15+** installed on Mac
3. **App Store Connect** access - https://appstoreconnect.apple.com

---

## Step 1: Create App ID in Developer Portal

1. Go to https://developer.apple.com/account/resources/identifiers
2. Click **+** to create new Identifier
3. Select **App IDs** → Continue
4. Select **App** → Continue
5. Fill in:
   - **Description**: TallyScanner
   - **Bundle ID**: Explicit → `com.tallyups.scanner`
6. Enable capabilities:
   - ✅ Sign in with Apple
   - ✅ Associated Domains (if using universal links)
   - ✅ Push Notifications (future feature)
7. Click **Continue** → **Register**

---

## Step 2: Create App in App Store Connect

1. Go to https://appstoreconnect.apple.com/apps
2. Click **+** → **New App**
3. Fill in:
   - **Platform**: iOS
   - **Name**: TallyScanner
   - **Primary Language**: English (U.S.)
   - **Bundle ID**: Select `com.tallyups.scanner`
   - **SKU**: `tallyscanner-001`
   - **User Access**: Full Access
4. Click **Create**

---

## Step 3: Create App Icon (1024x1024)

You need a 1024x1024 PNG app icon. Create one with these specs:

```
- Size: 1024x1024 pixels
- Format: PNG (no transparency for App Store)
- Design suggestions:
  - Background: #0D1117 (dark)
  - Icon: Receipt/scanner symbol in #00FF88 (tally green)
  - Rounded corners are applied automatically
```

### Using Figma/Sketch:
1. Create 1024x1024 artboard
2. Design icon with receipt/scan motif
3. Export as PNG
4. Save as: `ios/TallyScanner/Resources/Assets.xcassets/AppIcon.appiconset/AppIcon.png`

### Update Contents.json:
```json
{
  "images" : [
    {
      "filename" : "AppIcon.png",
      "idiom" : "universal",
      "platform" : "ios",
      "size" : "1024x1024"
    }
  ],
  "info" : {
    "author" : "xcode",
    "version" : 1
  }
}
```

---

## Step 4: Configure Xcode Project

### Open in Xcode:
```bash
cd ios
open TallyScanner.xcodeproj
```

### Configure Signing:
1. Select **TallyScanner** project in navigator
2. Select **TallyScanner** target
3. Go to **Signing & Capabilities** tab
4. Check **Automatically manage signing**
5. Select your **Team** from dropdown
6. Xcode will create provisioning profile

### Verify Bundle ID:
- Should be: `com.tallyups.scanner`
- Must match App Store Connect

### Set Version:
- **Version**: 1.0.0
- **Build**: 1

---

## Step 5: Archive and Upload

### Option A: Xcode (Manual)

1. Select **Any iOS Device (arm64)** as destination
2. Menu: **Product** → **Archive**
3. Wait for archive to complete
4. In Organizer, select archive → **Distribute App**
5. Select **App Store Connect** → **Upload**
6. Follow prompts (automatic signing recommended)

### Option B: Fastlane (Automated)

```bash
# Install fastlane
brew install fastlane

# Navigate to iOS folder
cd ios

# First time: Set up match for code signing
fastlane match init

# Upload to TestFlight
fastlane beta
```

### Option C: Command Line (xcodebuild)

```bash
cd ios

# Archive
xcodebuild archive \
  -scheme TallyScanner \
  -archivePath ./build/TallyScanner.xcarchive \
  -destination "generic/platform=iOS"

# Export IPA
xcodebuild -exportArchive \
  -archivePath ./build/TallyScanner.xcarchive \
  -exportPath ./build \
  -exportOptionsPlist ExportOptions.plist

# Upload with altool (deprecated) or use Transporter app
xcrun altool --upload-app \
  -f ./build/TallyScanner.ipa \
  -u YOUR_APPLE_ID \
  -p YOUR_APP_SPECIFIC_PASSWORD
```

---

## Step 6: Configure TestFlight

1. Go to App Store Connect → Your App → **TestFlight** tab
2. Wait for build processing (5-30 minutes)
3. Once processed, click on the build
4. Fill in **What to Test** description
5. Add **Test Information**:
   - Beta App Description
   - Feedback Email
   - Privacy Policy URL (required)

---

## Step 7: Add Testers

### Internal Testers (up to 100):
1. TestFlight → **Internal Testing**
2. Click **+** next to App Store Connect Users
3. Add team members with App Store Connect access

### External Testers (up to 10,000):
1. TestFlight → **External Testing**
2. Create a **New Group**
3. Add build to group
4. Add testers by email
5. Submit for **Beta App Review** (first time only)

---

## Step 8: Install on Device

Testers will:
1. Receive email invitation
2. Download **TestFlight** app from App Store
3. Open invitation link or enter code
4. Install TallyScanner

---

## Required App Store Metadata

Before submitting for review, prepare:

### App Information
- **Name**: TallyScanner
- **Subtitle**: Smart Receipt Scanner
- **Category**: Finance
- **Secondary Category**: Productivity

### Description
```
TallyScanner is the ultimate receipt scanning app with AI-powered
text extraction, automatic edge detection, and seamless expense tracking.

Features:
• Real-time edge detection with auto-capture
• AI-powered OCR for instant data extraction
• Offline mode with automatic sync
• Batch scanning for multiple receipts
• Smart categorization and merchant recognition
• Secure cloud backup to your TallyUps account

Perfect for freelancers, small businesses, and anyone who needs
to track expenses effortlessly.
```

### Keywords
```
receipt, scanner, expense, OCR, finance, tracking, tax, business, invoice
```

### Privacy Policy URL
You need a privacy policy. Create one at:
- https://www.privacypolicygenerator.info
- Host at: `https://tallyups.com/privacy`

### Screenshots (Required)
- 6.7" (iPhone 15 Pro Max): 1290 x 2796
- 6.5" (iPhone 11 Pro Max): 1284 x 2778
- 5.5" (iPhone 8 Plus): 1242 x 2208
- iPad Pro 12.9": 2048 x 2732

---

## Troubleshooting

### "No accounts with App Store Connect access"
- Ensure Apple ID is added to Xcode preferences
- Verify you have Admin/Developer role in App Store Connect

### "Profile doesn't match bundle identifier"
- Check bundle ID matches exactly: `com.tallyups.scanner`
- Delete derived data: `rm -rf ~/Library/Developer/Xcode/DerivedData`

### "Missing compliance information"
- Already set `ITSAppUsesNonExemptEncryption` = false in Info.plist

### Build processing stuck
- Usually takes 5-30 minutes
- Check App Store Connect status page

---

## Quick Reference

| Item | Value |
|------|-------|
| Bundle ID | `com.tallyups.scanner` |
| App Name | TallyScanner |
| Min iOS | 16.0 |
| Category | Finance |
| SKU | tallyscanner-001 |

---

## Next Steps After TestFlight

1. Gather tester feedback
2. Fix any reported issues
3. Submit for App Store review
4. Launch! 🚀

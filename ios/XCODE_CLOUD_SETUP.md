# Deploy TallyScanner from Your Phone 📱

**No Mac. No certificates. No Terminal.**

Xcode Cloud handles everything automatically.

---

## Setup (One Time - 5 minutes from phone)

### Step 1: Open App Store Connect

On your phone, go to:
**[appstoreconnect.apple.com](https://appstoreconnect.apple.com)**

Login with: `Kaplan.brian@gmail.com`

---

### Step 2: Create the App (if not done)

1. Tap **Apps** → **+** → **New App**
2. Fill in:
   - **Name**: TallyScanner
   - **Bundle ID**: `com.tallyups.scanner` (register new if needed)
   - **SKU**: `tallyscanner`
3. Tap **Create**

---

### Step 3: Enable Xcode Cloud

1. In your app, tap **Xcode Cloud** in sidebar
2. Tap **Get Started**
3. **Connect your GitHub repo**:
   - Authorize Apple to access GitHub
   - Select the `tallyups` repository
4. **Configure workflow**:
   - Product: `TallyScanner`
   - Start condition: Manual or on push
   - Action: **Archive → TestFlight (Internal)**
5. Tap **Save**

---

### Step 4: Grant Repository Access

When prompted:
1. Tap **Grant Access**
2. Apple creates signing certificates automatically
3. No downloads, no exports, nothing to manage

---

## Deploy 🚀

### From App Store Connect (Phone)

1. Open [appstoreconnect.apple.com](https://appstoreconnect.apple.com)
2. Go to **your app** → **Xcode Cloud**
3. Tap **Start Build**
4. Wait ~15 minutes
5. Build appears in TestFlight ✅

### From GitHub (Phone)

Just push to main - Xcode Cloud auto-builds.

---

## That's It!

| What | Who handles it |
|------|----------------|
| Code signing | Apple (automatic) |
| Certificates | Apple (automatic) |
| Provisioning | Apple (automatic) |
| Building | Apple (Xcode Cloud) |
| TestFlight upload | Apple (automatic) |

**You just tap "Start Build"** 📱

---

## Troubleshooting

### "Grant access to repository"
- Make sure GitHub is connected to App Store Connect
- Settings → Users and Access → Integrations

### "No products found"
- The Xcode project needs a scheme
- Already configured ✅

### Build fails
- Check Xcode Cloud logs in App Store Connect
- Usually shows exactly what's wrong

---

## Your Config

| Setting | Value |
|---------|-------|
| Apple ID | Kaplan.brian@gmail.com |
| Team ID | R2LSUCXR5J |
| Bundle ID | com.tallyups.scanner |
| App Name | TallyScanner |

# iOS GitHub Actions Deploy Setup

Deploy TallyScanner to TestFlight directly from your phone using GitHub Actions.

## Quick Start (5 minutes on Mac, then phone forever)

### Step 1: Create App Store Connect API Key

1. Go to [App Store Connect → Users and Access → Keys](https://appstoreconnect.apple.com/access/api)
2. Click **+** to create new key
3. Name: `GitHub Actions`
4. Access: `App Manager`
5. Click **Generate**
6. **Download the .p8 file** (you can only download once!)
7. Note the **Key ID** and **Issuer ID**

### Step 2: Export Your Signing Certificate

On your Mac:

```bash
# Open Keychain Access
open -a "Keychain Access"
```

1. Find your **Apple Distribution** certificate
2. Right-click → **Export**
3. Save as `certificate.p12`
4. Set a password (remember it!)

### Step 3: Download Provisioning Profile

1. Go to [Apple Developer → Profiles](https://developer.apple.com/account/resources/profiles)
2. Find or create an **App Store** profile for `com.tallyups.scanner`
3. Download the `.mobileprovision` file

### Step 4: Encode Files to Base64

```bash
# Certificate
base64 -i certificate.p12 | pbcopy
# Paste this as BUILD_CERTIFICATE_BASE64 secret

# Provisioning Profile
base64 -i profile.mobileprovision | pbcopy
# Paste this as BUILD_PROVISION_PROFILE_BASE64 secret

# App Store Connect API Key
base64 -i AuthKey_XXXXXX.p8 | pbcopy
# Paste this as APP_STORE_CONNECT_API_KEY_BASE64 secret
```

### Step 5: Add GitHub Secrets

Go to your repo → **Settings** → **Secrets and variables** → **Actions**

Add these secrets:

| Secret Name | Value |
|-------------|-------|
| `BUILD_CERTIFICATE_BASE64` | Base64 of your .p12 certificate |
| `P12_PASSWORD` | Password you set when exporting |
| `BUILD_PROVISION_PROFILE_BASE64` | Base64 of .mobileprovision |
| `KEYCHAIN_PASSWORD` | Any random password (e.g., `temp123`) |
| `TEAM_ID` | Your Apple Team ID (10 characters) |
| `PROVISIONING_PROFILE_NAME` | Name of your provisioning profile |
| `APP_STORE_CONNECT_API_KEY_ID` | Key ID from Step 1 |
| `APP_STORE_CONNECT_API_ISSUER_ID` | Issuer ID from Step 1 |
| `APP_STORE_CONNECT_API_KEY_BASE64` | Base64 of the .p8 file |

---

## Deploy from Your Phone 📱

### Using GitHub Mobile App

1. Download **GitHub** app from App Store
2. Open your repository
3. Tap **Actions** tab
4. Tap **iOS TestFlight Deploy**
5. Tap **Run workflow**
6. Optionally enter version number
7. Tap **Run workflow** ✅

### Using Safari

1. Go to `github.com/YOUR_USER/tallyups`
2. Click **Actions** tab
3. Click **iOS TestFlight Deploy**
4. Click **Run workflow** dropdown
5. Click green **Run workflow** button

---

## What Happens Next

1. ⏱️ Build takes ~10-15 minutes
2. 📤 Automatically uploads to TestFlight
3. 🔄 Apple processes build (5-30 min)
4. 📱 Testers get notified in TestFlight app

---

## Finding Your Team ID

```bash
# Option 1: From Keychain
security find-identity -v -p codesigning

# Option 2: From Developer Portal
# Go to developer.apple.com → Membership → Team ID
```

---

## Troubleshooting

### "No signing certificate found"
- Re-export certificate from Keychain Access
- Make sure it's the **Distribution** certificate, not Development

### "Provisioning profile doesn't match"
- Create new profile at developer.apple.com
- Bundle ID must be exactly: `com.tallyups.scanner`

### "API key invalid"
- Re-download .p8 file (can only download once!)
- Check Key ID and Issuer ID match

### Build succeeds but not in TestFlight
- Check App Store Connect → TestFlight → Processing
- May take up to 30 minutes

---

## Security Notes

- Secrets are encrypted by GitHub
- Never commit .p12, .p8, or .mobileprovision files
- Rotate keys periodically
- API keys can be revoked in App Store Connect

---

## Workflow Files

| File | Purpose |
|------|---------|
| `.github/workflows/ios-testflight.yml` | Deploy to TestFlight |
| `.github/workflows/ios-build.yml` | Test builds on PRs |

---

## One-Time Mac Setup Checklist

- [ ] Apple Developer account ($99/year)
- [ ] App created in App Store Connect
- [ ] App ID created in Developer Portal
- [ ] Distribution certificate created
- [ ] Provisioning profile created
- [ ] App Store Connect API key created
- [ ] All secrets added to GitHub

After this, deploy from anywhere! 🌍📱

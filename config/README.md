# Configuration Directory

## Gmail OAuth Setup

### Step 1: Create Google Cloud Project

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable the **Gmail API**

### Step 2: Create OAuth Credentials

1. Go to **APIs & Services** → **Credentials**
2. Click **+ CREATE CREDENTIALS** → **OAuth client ID**
3. Application type: **Desktop app**
4. Name it: "Receipt Matcher Gmail Access"
5. Click **CREATE**
6. Download the credentials JSON file
7. Save it as: `credentials.json` in this directory

### Step 3: Authenticate Your Accounts

Run the authentication script:

```bash
python3 authenticate_gmail.py
```

This will:
- Open a browser for each Gmail account
- Request permission to read Gmail
- Save authentication tokens in `gmail_tokens/`

### Your Gmail Accounts

The system is configured for these accounts:
- kaplan.brian@gmail.com
- brian@business.com
- brian@secondary.com

### Files

- `credentials.json` - OAuth client credentials (you provide this)
- `../gmail_tokens/` - Authenticated tokens (auto-generated)
- `../gmail_cache/` - Search cache (auto-generated)

### Security Notes

⚠️ **Never commit credentials.json or tokens to git!**

These files contain sensitive authentication data.

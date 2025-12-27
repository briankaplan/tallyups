# Contact Hub - Personal CRM with Relationship Tracking

A self-hosted personal CRM that tracks every interaction with your contacts - emails, calls, meetings, messages, and in-person conversations. Syncs with Google Contacts, Gmail, and Google Calendar.

## Features

### Contact Management
- Full contact profiles (name, company, job title, multiple emails/phones/addresses)
- Tags and categorization
- Smart deduplication with fuzzy matching
- Import from CSV and vCard
- Export to CSV and vCard

### Interaction Tracking
- **Emails** - Syncs from Gmail, shows full conversation history
- **Phone Calls** - Log incoming/outgoing calls with duration and notes
- **Meetings** - In-person and video (Zoom, Meet, Teams) with location
- **Messages** - SMS, iMessage, WhatsApp tracking
- **Notes** - Add notes about any contact

### Relationship Intelligence
- Last interaction tracking for every contact
- Contact frequency goals (e.g., "contact every 30 days")
- "Needs attention" alerts when you're out of touch
- Interaction statistics and analytics
- Activity timeline for each contact

### Calendar Integration
- Sync with Google Calendar
- See upcoming meetings with contacts
- Past meeting history
- Birthday and anniversary reminders

### Reminders System
- Follow-up reminders
- Recurring reminders
- Snooze capability
- Priority levels (normal, high, urgent)

### Claude Integration (MCP Server)
Full integration with Claude via MCP protocol:
- Search and manage contacts
- Log calls, meetings, messages
- Create reminders
- View activity timelines
- Get relationship insights

## Quick Start

### Deploy to Railway

1. Create a new project:
```bash
railway init
```

2. Add MySQL database:
- In Railway dashboard, add MySQL service
- DATABASE_URL will be auto-configured

3. Set environment variables:
```bash
railway variables set GOOGLE_CLIENT_ID=your_client_id
railway variables set GOOGLE_CLIENT_SECRET=your_client_secret
```

4. Deploy:
```bash
railway up
```

### Google OAuth Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable these APIs:
   - Google People API
   - Google Calendar API
   - Gmail API
4. Configure OAuth consent screen
5. Create OAuth 2.0 credentials (Web application)
6. Add redirect URI: `https://your-app.railway.app/auth/google/callback`

### Connect Google Account

Visit: `https://your-app.railway.app/auth/google`

This connects:
- Google Contacts (bidirectional sync)
- Google Calendar (read-only)
- Gmail (read-only)

## API Endpoints

### Contacts
- `GET /contacts` - List contacts (with search, tag filter, pagination)
- `POST /contacts` - Create contact
- `GET /contacts/{id}` - Get contact details
- `PUT /contacts/{id}` - Update contact
- `DELETE /contacts/{id}` - Delete contact
- `GET /search?q=...` - Quick search

### Interactions
- `POST /interactions` - Log any interaction
- `POST /interactions/call` - Log a phone call
- `POST /interactions/meeting` - Log a meeting
- `POST /interactions/message` - Log a text message
- `POST /interactions/note` - Add a note
- `GET /contacts/{id}/interactions` - Get contact's interactions
- `GET /contacts/{id}/timeline` - Get activity timeline
- `GET /contacts/{id}/stats` - Get interaction statistics
- `GET /contacts/needing-attention` - Get contacts to reach out to
- `PUT /contacts/{id}/frequency` - Set contact frequency goal

### Reminders
- `GET /reminders` - List reminders
- `POST /reminders` - Create reminder
- `GET /reminders/due` - Get due/overdue reminders
- `POST /reminders/{id}/complete` - Complete reminder
- `POST /reminders/{id}/snooze` - Snooze reminder
- `POST /reminders/follow-up` - Quick follow-up reminder

### Calendar
- `GET /calendar/events` - Get upcoming events
- `GET /contacts/{id}/meetings` - Get past meetings with contact
- `GET /upcoming/birthdays` - Get upcoming birthdays
- `GET /upcoming/anniversaries` - Get upcoming anniversaries

### Email
- `GET /contacts/{id}/emails` - Get email threads with contact

### Sync
- `POST /sync/full` - Run full sync (contacts, calendar, email)
- `GET /sync/status` - Get sync status
- `GET /sync/accounts` - List connected accounts

### Tags
- `GET /tags` - List tags
- `POST /tags` - Create tag
- `POST /contacts/{id}/tags/{tag_id}` - Add tag to contact

### Import/Export
- `POST /contacts/import/csv` - Import from CSV
- `POST /contacts/import/vcard` - Import from vCard
- `GET /export/csv` - Export to CSV
- `GET /export/vcard` - Export to vCard

### Deduplication
- `GET /contacts/duplicates` - Find potential duplicates
- `POST /contacts/merge` - Merge contacts

## MCP Server Setup

Add to your Claude config (`~/.config/claude/config.json`):

```json
{
  "mcpServers": {
    "contact-hub": {
      "command": "python",
      "args": ["-m", "app.mcp_server"],
      "cwd": "/path/to/contact-hub",
      "env": {
        "CONTACT_HUB_API": "https://your-app.railway.app"
      }
    }
  }
}
```

### MCP Tools Available

**Contact Management:**
- `search_contacts` - Search by name, email, phone, company
- `get_contact` - Get contact details
- `list_contacts` - List with filters (tags, starred, needs attention)
- `create_contact` - Create new contact
- `update_contact` - Update contact

**Interaction Tracking:**
- `log_call` - Log phone call
- `log_meeting` - Log meeting (in-person or video)
- `log_message` - Log text message
- `add_note` - Add note about contact
- `get_contact_timeline` - Get activity timeline
- `get_contact_stats` - Get interaction statistics
- `get_contacts_needing_attention` - Get contacts to reach out to
- `set_contact_frequency` - Set contact frequency goal

**Reminders:**
- `create_reminder` - Create reminder
- `create_follow_up` - Quick follow-up reminder
- `get_due_reminders` - Get due reminders
- `complete_reminder` - Mark complete
- `snooze_reminder` - Snooze

**Calendar & Events:**
- `get_upcoming_events` - Get upcoming calendar events
- `get_contact_meetings` - Get past meetings
- `get_upcoming_birthdays` - Get upcoming birthdays

**Email:**
- `get_contact_emails` - Get email threads

**Tags & Organization:**
- `list_tags` - List all tags
- `create_tag` - Create tag
- `tag_contact` - Add tag to contact

**Maintenance:**
- `find_duplicates` - Find duplicate contacts
- `merge_contacts` - Merge contacts
- `sync_google` - Run sync
- `get_sync_status` - Get sync status

## Example Claude Conversations

**"Who should I follow up with?"**
```
Claude will use get_contacts_needing_attention to show contacts you haven't 
reached out to recently based on your frequency goals.
```

**"Log a 30-minute call with John Smith about the partnership"**
```
Claude will search for John Smith, log the call with duration and notes,
and update John's last interaction timestamp.
```

**"What's my history with Sarah at Acme Corp?"**
```
Claude will search for Sarah, get her timeline showing all emails, calls,
meetings, and notes, plus statistics on your communication patterns.
```

**"Remind me to follow up with Tim McGraw in a week"**
```
Claude will create a follow-up reminder for Tim, due in 7 days.
```

## Environment Variables

| Variable | Description | Required |
|----------|-------------|----------|
| `DATABASE_URL` | MySQL connection string | Yes |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID | Yes |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret | Yes |
| `CONTACT_HUB_API` | API URL (for MCP server) | For MCP |

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                     Contact Hub                              │
├─────────────────────────────────────────────────────────────┤
│  FastAPI Application                                         │
│  ├── Contact CRUD                                           │
│  ├── Interaction Tracking                                   │
│  ├── Reminder System                                        │
│  └── Sync Engines                                           │
│       ├── Google Contacts (bidirectional)                   │
│       ├── Google Calendar (read)                            │
│       └── Gmail (read)                                      │
├─────────────────────────────────────────────────────────────┤
│  MySQL Database                                              │
│  ├── contacts, emails, phones, addresses                    │
│  ├── interactions, activity_feed                            │
│  ├── calendar_events                                        │
│  ├── email_threads, email_messages                          │
│  ├── reminders                                              │
│  └── sync_accounts, sync_logs                               │
├─────────────────────────────────────────────────────────────┤
│  MCP Server                                                  │
│  └── 30+ tools for Claude integration                       │
└─────────────────────────────────────────────────────────────┘
```

## License

MIT

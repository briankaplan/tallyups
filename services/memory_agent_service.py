"""
Memory Agent - Intelligence & Knowledge Management System

This agent is the intelligence layer that:
1. Ingests all information (email, calendar, tasks, documents)
2. Extracts entities (people, projects, decisions, tasks)
3. Creates/updates notes in Obsidian vault
4. Builds knowledge graph with automatic linking
5. Provides context and insights

Based on: /Users/briankaplan/Library/Mobile Documents/iCloud~md~obsidian/Documents/Brian Kaplan/Briank/agents/Memory_Agent_Specification.md
"""

import os
import re
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import anthropic
from dataclasses import dataclass, asdict

# Obsidian vault path - use environment variable or default to iCloud (local) or /tmp (Railway)
DEFAULT_LOCAL_PATH = "/Users/briankaplan/Library/Mobile Documents/iCloud~md~obsidian/Documents/Brian Kaplan/Briank"
DEFAULT_REMOTE_PATH = "/tmp/obsidian_vault"
vault_path_str = os.getenv('OBSIDIAN_VAULT_PATH', DEFAULT_LOCAL_PATH if Path(DEFAULT_LOCAL_PATH).exists() else DEFAULT_REMOTE_PATH)
VAULT_PATH = Path(vault_path_str)

# Entity types and their folders
ENTITY_FOLDERS = {
    'person': '4_People',
    'project': '1_Projects',
    'email_thread': '8_Email_Threads',
    'meeting': '6_Meetings',
    'receipt': '7_Receipts',
    'daily': '9_Daily',
    'literature': '3_Resources/Literature_Notes'
}

@dataclass
class Entity:
    """Represents an extracted entity"""
    type: str  # person, project, decision, task, date, money
    value: str
    canonical_id: Optional[str] = None
    metadata: Optional[Dict] = None


@dataclass
class EmailIntelligence:
    """Intelligence extracted from email"""
    message_id: str
    subject: str
    from_email: str
    from_name: str
    date: str
    summary: str
    people: List[str]  # Canonical IDs
    projects: List[str]  # Canonical IDs
    decisions: List[Dict]
    tasks: List[Dict]
    sentiment: Dict
    priority: str  # LOW, MEDIUM, HIGH, URGENT
    category: str  # receipt, important, financial, personal, etc.


class MemoryAgent:
    """
    Memory Agent - The intelligence layer for Life OS

    Responsibilities:
    - Process all incoming information
    - Extract entities and relationships
    - Create/update Obsidian notes
    - Build knowledge graph
    - Provide context and insights
    """

    def __init__(self, anthropic_api_key: str = None):
        """Initialize Memory Agent"""
        self.api_key = anthropic_api_key or os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY required for Memory Agent")

        self.client = anthropic.Anthropic(api_key=self.api_key)
        self.vault_path = VAULT_PATH

        # Ensure vault folders exist
        self._ensure_vault_structure()

    def _ensure_vault_structure(self):
        """Ensure all required vault folders exist"""
        required_folders = [
            '0_Dashboard',
            '1_Projects',
            '2_Areas',
            '3_Resources',
            '3_Resources/Literature_Notes',
            '4_People',
            '5_Archives',
            '6_Meetings',
            '7_Receipts',
            '8_Email_Threads',
            '9_Daily',
            '_Templates'
        ]

        for folder in required_folders:
            folder_path = self.vault_path / folder
            folder_path.mkdir(parents=True, exist_ok=True)

    # ====================
    # EMAIL INTELLIGENCE
    # ====================

    def process_email(self, email_data: Dict) -> EmailIntelligence:
        """
        Process an email and extract intelligence

        Args:
            email_data: Dict with keys: id, subject, from, body, date, etc.

        Returns:
            EmailIntelligence object with extracted entities and insights
        """

        prompt = f"""Analyze this email and extract intelligence:

**From:** {email_data.get('from', '')}
**Subject:** {email_data.get('subject', '')}
**Date:** {email_data.get('date', '')}
**Body:**
{email_data.get('body', '')[:2000]}

Extract and return JSON with:
1. **summary** (2-3 sentences)
2. **people** (array of names mentioned)
3. **projects** (array of projects/initiatives mentioned)
4. **decisions** (array of objects with: decision, rationale, impact)
5. **tasks** (array of objects with: task, deadline, owner)
6. **sentiment** (object with: tone, urgency, relationship_health)
7. **priority** (LOW, MEDIUM, HIGH, URGENT)
8. **category** (receipt, important, financial, personal, newsletter, spam, archive)

Return only valid JSON, no markdown."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=2000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            intelligence_json = response.content[0].text
            intelligence = json.loads(intelligence_json)

            return EmailIntelligence(
                message_id=email_data.get('id', ''),
                subject=email_data.get('subject', ''),
                from_email=email_data.get('from', ''),
                from_name=intelligence.get('from_name', email_data.get('from', '')),
                date=email_data.get('date', ''),
                summary=intelligence.get('summary', ''),
                people=intelligence.get('people', []),
                projects=intelligence.get('projects', []),
                decisions=intelligence.get('decisions', []),
                tasks=intelligence.get('tasks', []),
                sentiment=intelligence.get('sentiment', {}),
                priority=intelligence.get('priority', 'MEDIUM'),
                category=intelligence.get('category', 'archive')
            )

        except Exception as e:
            print(f"Error processing email intelligence: {e}")
            # Return basic intelligence
            return EmailIntelligence(
                message_id=email_data.get('id', ''),
                subject=email_data.get('subject', ''),
                from_email=email_data.get('from', ''),
                from_name=email_data.get('from', ''),
                date=email_data.get('date', ''),
                summary='',
                people=[],
                projects=[],
                decisions=[],
                tasks=[],
                sentiment={},
                priority='MEDIUM',
                category='archive'
            )

    def create_email_thread_note(self, intelligence: EmailIntelligence, email_body: str = '') -> str:
        """
        Create an Email Thread note in Obsidian

        Args:
            intelligence: EmailIntelligence object
            email_body: Full email body

        Returns:
            Path to created note
        """

        # Create note filename: "Email YYYY-MM-DD Subject thread-{id}"
        date_str = datetime.now().strftime('%Y-%m-%d')
        subject_slug = self._slugify(intelligence.subject[:50])
        thread_id = intelligence.message_id[:8]
        filename = f"Email {date_str} {subject_slug} thread-{thread_id}.md"

        # Build note content
        people_links = ' '.join([f"[[{p}]]" for p in intelligence.people])
        project_links = ' '.join([f"[[{p}]]" for p in intelligence.projects])

        content = f"""---
type: email_thread
date: {intelligence.date}
from: {intelligence.from_email}
subject: {intelligence.subject}
priority: {intelligence.priority}
category: {intelligence.category}
people: [{', '.join(intelligence.people)}]
projects: [{', '.join(intelligence.projects)}]
sentiment: {json.dumps(intelligence.sentiment)}
tags: [email, {intelligence.category}]
---

# {intelligence.subject}

**From:** {intelligence.from_name} ({intelligence.from_email})
**Date:** {intelligence.date}
**Priority:** {intelligence.priority}

## Summary

{intelligence.summary}

## People Involved
{people_links if people_links else 'None identified'}

## Related Projects
{project_links if project_links else 'None identified'}

## Decisions Made

{''.join([f"- **Decision:** {d.get('decision', '')}\n  - Rationale: {d.get('rationale', '')}\n  - Impact: {d.get('impact', '')}\n" for d in intelligence.decisions]) if intelligence.decisions else 'No decisions identified'}

## Action Items

{''.join([f"- [ ] {t.get('task', '')} {f"(due: {t.get('deadline', '')})" if t.get('deadline') else ''} {f"(@{t.get('owner', '')})" if t.get('owner') else ''}\n" for t in intelligence.tasks]) if intelligence.tasks else 'No action items'}

## Sentiment Analysis

- **Tone:** {intelligence.sentiment.get('tone', 'neutral')}
- **Urgency:** {intelligence.sentiment.get('urgency', 'normal')}
- **Relationship Health:** {intelligence.sentiment.get('relationship_health', 'neutral')}

## Full Email

```
{email_body[:1000] if email_body else 'Body not available'}
```

---

*Processed by Memory Agent on {datetime.now().strftime('%Y-%m-%d %H:%M')}*
"""

        # Write note
        note_path = self.vault_path / '8_Email_Threads' / filename
        note_path.write_text(content, encoding='utf-8')

        return str(note_path)

    # ====================
    # PERSON NOTES
    # ====================

    def get_or_create_person_note(self, name: str, email: str = '', metadata: Dict = None) -> str:
        """
        Get existing person note or create new one

        Args:
            name: Person's full name
            email: Email address
            metadata: Additional person data

        Returns:
            Path to person note
        """

        # Create canonical ID: "Last, First (Company)"
        canonical_id = self._create_person_canonical_id(name, metadata)
        filename = f"{canonical_id}.md"
        note_path = self.vault_path / '4_People' / filename

        # If note exists, return path
        if note_path.exists():
            return str(note_path)

        # Create new person note
        content = f"""---
type: person
canonical_id: person-{self._slugify(canonical_id)}
name: {name}
email: {email}
company: {metadata.get('company', '') if metadata else ''}
role: {metadata.get('role', '') if metadata else ''}
tags: [person]
created: {datetime.now().strftime('%Y-%m-%d')}
---

# {name}

**Email:** {email}
**Company:** {metadata.get('company', '') if metadata else ''}
**Role:** {metadata.get('role', '') if metadata else ''}

## About

## Last 5 Touches

1.

## Communication Preferences

- **Preferred method:**
- **Response time:**
- **Best time to contact:**

## Working Together

### Strengths

### Communication Style

### Current Projects Together

## Notes

---

*Person note created by Memory Agent on {datetime.now().strftime('%Y-%m-%d')}*
"""

        note_path.write_text(content, encoding='utf-8')
        return str(note_path)

    def update_person_last_touch(self, person_canonical_id: str, touch_note: str):
        """
        Update person's "Last 5 Touches" section

        Args:
            person_canonical_id: Person's canonical ID
            touch_note: Note about the interaction (with link)
        """

        # Find person note
        person_note_path = self._find_person_note(person_canonical_id)
        if not person_note_path:
            return

        content = person_note_path.read_text(encoding='utf-8')

        # Add to Last 5 Touches
        today = datetime.now().strftime('%Y-%m-%d')
        new_touch = f"1. [[{today}]] - {touch_note}"

        # Insert after "## Last 5 Touches"
        content = re.sub(
            r'(## Last 5 Touches\n\n)(1\. )',
            f'\\1{new_touch}\n2. ',
            content
        )

        person_note_path.write_text(content, encoding='utf-8')

    # ====================
    # DAILY NOTES
    # ====================

    def get_or_create_daily_note(self, date: datetime = None) -> str:
        """
        Get or create daily note for a specific date

        Args:
            date: Date for daily note (default: today)

        Returns:
            Path to daily note
        """

        if date is None:
            date = datetime.now()

        date_str = date.strftime('%Y-%m-%d')
        filename = f"{date_str}.md"
        note_path = self.vault_path / '9_Daily' / filename

        # If note exists, return path
        if note_path.exists():
            return str(note_path)

        # Load template
        template_path = self.vault_path / '_Templates' / 'Daily_Note.md'
        if template_path.exists():
            template = template_path.read_text(encoding='utf-8')
            # Replace template variables
            template = template.replace('{{date:YYYY-MM-DD}}', date_str)
            template = template.replace('{{date:dddd, MMMM DD, YYYY}}', date.strftime('%A, %B %d, %Y'))
        else:
            # Basic template if none exists
            template = f"""---
type: daily
date: {date_str}
tags: [daily]
---

# {date.strftime('%A, %B %d, %Y')}

## 🎯 Top 3 Priorities

1.
2.
3.

## 📋 Tasks from Taskade

## 🗓️ Calendar

## 📝 Notes & Captures

## 💭 Reflections

### Wins

### Blockers

---

*Created by Memory Agent*
"""

        note_path.write_text(template, encoding='utf-8')
        return str(note_path)

    def add_to_daily_note(self, section: str, content: str, date: datetime = None):
        """
        Add content to a section of the daily note

        Args:
            section: Section name (e.g., "Notes & Captures", "Tasks from Taskade")
            content: Content to add
            date: Date (default: today)
        """

        note_path = Path(self.get_or_create_daily_note(date))
        note_content = note_path.read_text(encoding='utf-8')

        # Find section and add content
        section_pattern = f"## {section}"
        if section_pattern in note_content:
            # Add content after section header
            note_content = re.sub(
                f"({section_pattern}\n\n)",
                f"\\1{content}\n\n",
                note_content,
                count=1
            )

            note_path.write_text(note_content, encoding='utf-8')

    # ====================
    # ENTITY EXTRACTION
    # ====================

    def extract_entities(self, text: str) -> List[Entity]:
        """
        Extract entities from text (people, projects, dates, money, etc.)

        Args:
            text: Text to analyze

        Returns:
            List of Entity objects
        """

        prompt = f"""Extract entities from this text:

{text}

Find and return JSON array of entities with:
- type: person, project, date, money, task, decision
- value: the entity text
- metadata: any relevant additional info

Return only valid JSON array."""

        try:
            response = self.client.messages.create(
                model="claude-sonnet-4-5-20250929",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": prompt
                }]
            )

            entities_json = response.content[0].text
            entities_data = json.loads(entities_json)

            return [Entity(**e) for e in entities_data]

        except Exception as e:
            print(f"Error extracting entities: {e}")
            return []

    # ====================
    # HELPER METHODS
    # ====================

    def _slugify(self, text: str) -> str:
        """Convert text to slug (lowercase, hyphenated)"""
        text = re.sub(r'[^\w\s-]', '', text.lower())
        text = re.sub(r'[-\s]+', '-', text)
        return text.strip('-')

    def _create_person_canonical_id(self, name: str, metadata: Dict = None) -> str:
        """
        Create canonical person ID: "Last, First (Company)"

        Args:
            name: Full name
            metadata: Dict with optional 'company' key

        Returns:
            Canonical ID string
        """

        # Try to parse name
        parts = name.strip().split()
        if len(parts) >= 2:
            first = parts[0]
            last = parts[-1]
            canonical = f"{last}, {first}"
        else:
            canonical = name

        # Add company if available
        if metadata and metadata.get('company'):
            canonical = f"{canonical} ({metadata['company']})"

        return canonical

    def _find_person_note(self, canonical_id: str) -> Optional[Path]:
        """Find person note by canonical ID"""
        people_dir = self.vault_path / '4_People'

        # Try exact match
        note_path = people_dir / f"{canonical_id}.md"
        if note_path.exists():
            return note_path

        # Try fuzzy match
        for note in people_dir.glob('*.md'):
            if canonical_id.lower() in note.stem.lower():
                return note

        return None

    # ====================
    # CONTEXT & INSIGHTS
    # ====================

    def get_context_for_meeting(self, attendees: List[str], project: str = None) -> Dict:
        """
        Get context before a meeting

        Args:
            attendees: List of attendee names/emails
            project: Optional project name

        Returns:
            Dict with context: last meetings, recent communications, person profiles, etc.
        """

        context = {
            'attendees': [],
            'last_meetings': [],
            'recent_communications': [],
            'project_status': None,
            'open_items': []
        }

        # Get context for each attendee
        for attendee in attendees:
            person_note = self._find_person_note(attendee)
            if person_note:
                # Read person note and extract relevant info
                content = person_note.read_text(encoding='utf-8')
                context['attendees'].append({
                    'name': attendee,
                    'note_path': str(person_note),
                    'profile_summary': content[:500]  # First 500 chars
                })

        return context

    def generate_daily_intelligence(self, date: datetime = None) -> Dict:
        """
        Generate daily intelligence briefing

        Args:
            date: Date for briefing (default: today)

        Returns:
            Dict with: priority emails, meetings, tasks, insights
        """

        if date is None:
            date = datetime.now()

        briefing = {
            'date': date.strftime('%Y-%m-%d'),
            'high_priority_emails': [],
            'meetings_today': [],
            'urgent_tasks': [],
            'relationship_alerts': [],
            'insights': []
        }

        # This would query various sources and compile intelligence
        # For now, return structure

        return briefing


def create_memory_agent() -> MemoryAgent:
    """Factory function to create Memory Agent instance"""
    return MemoryAgent()


if __name__ == '__main__':
    # Test Memory Agent
    agent = create_memory_agent()
    print("✅ Memory Agent initialized")
    print(f"✅ Vault path: {agent.vault_path}")

    # Test daily note creation
    daily_note = agent.get_or_create_daily_note()
    print(f"✅ Daily note: {daily_note}")

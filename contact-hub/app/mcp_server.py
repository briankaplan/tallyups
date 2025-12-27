#!/usr/bin/env python3
"""
Contact Hub MCP Server
Provides tools for Claude to manage contacts, interactions, reminders, and calendar
"""

import os
import json
import httpx
from datetime import datetime, timedelta
from mcp.server import Server
from mcp.types import Tool, TextContent
from mcp.server.stdio import stdio_server

# API base URL
API_BASE = os.getenv("CONTACT_HUB_API", "http://localhost:8000")

server = Server("contact-hub")


async def api_call(method: str, endpoint: str, data: dict = None) -> dict:
    """Make API call to Contact Hub"""
    url = f"{API_BASE}{endpoint}"
    
    async with httpx.AsyncClient(timeout=30.0) as client:
        if method == "GET":
            response = await client.get(url, params=data)
        elif method == "POST":
            response = await client.post(url, json=data)
        elif method == "PUT":
            response = await client.put(url, json=data)
        elif method == "DELETE":
            response = await client.delete(url)
        else:
            raise ValueError(f"Unknown method: {method}")
        
        if response.status_code >= 400:
            return {"error": response.text}
        
        return response.json()


@server.list_tools()
async def list_tools():
    """List available tools"""
    return [
        # Contact Management
        Tool(
            name="search_contacts",
            description="Search for contacts by name, email, phone, or company",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["query"],
            },
        ),
        Tool(
            name="get_contact",
            description="Get detailed information about a specific contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "description": "Contact ID"},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="list_contacts",
            description="List contacts with optional filtering",
            inputSchema={
                "type": "object",
                "properties": {
                    "tag": {"type": "string", "description": "Filter by tag name"},
                    "needs_attention": {"type": "boolean", "description": "Only show contacts needing attention"},
                    "starred": {"type": "boolean", "description": "Only show starred contacts"},
                    "limit": {"type": "integer", "default": 20},
                },
            },
        ),
        Tool(
            name="create_contact",
            description="Create a new contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"},
                    "job_title": {"type": "string"},
                    "notes": {"type": "string"},
                },
            },
        ),
        Tool(
            name="update_contact",
            description="Update an existing contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "first_name": {"type": "string"},
                    "last_name": {"type": "string"},
                    "email": {"type": "string"},
                    "phone": {"type": "string"},
                    "company": {"type": "string"},
                    "job_title": {"type": "string"},
                    "notes": {"type": "string"},
                    "is_starred": {"type": "boolean"},
                },
                "required": ["contact_id"],
            },
        ),
        
        # Interaction Tracking
        Tool(
            name="log_call",
            description="Log a phone call with a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "duration_minutes": {"type": "integer"},
                    "is_outgoing": {"type": "boolean", "default": True},
                    "summary": {"type": "string"},
                    "was_missed": {"type": "boolean", "default": False},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="log_meeting",
            description="Log a meeting (in-person or video call)",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_ids": {"type": "array", "items": {"type": "integer"}},
                    "subject": {"type": "string"},
                    "duration_minutes": {"type": "integer"},
                    "location": {"type": "string"},
                    "summary": {"type": "string"},
                    "notes": {"type": "string"},
                    "is_video": {"type": "boolean", "default": False},
                    "video_platform": {"type": "string"},
                },
                "required": ["contact_ids", "subject"],
            },
        ),
        Tool(
            name="log_message",
            description="Log a text message (SMS, iMessage, WhatsApp)",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "content": {"type": "string"},
                    "is_outgoing": {"type": "boolean", "default": True},
                    "channel": {"type": "string", "enum": ["sms", "imessage", "whatsapp"]},
                },
                "required": ["contact_id", "content"],
            },
        ),
        Tool(
            name="add_note",
            description="Add a note about a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "content": {"type": "string"},
                    "subject": {"type": "string"},
                },
                "required": ["contact_id", "content"],
            },
        ),
        Tool(
            name="get_contact_timeline",
            description="Get activity timeline for a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="get_contact_stats",
            description="Get interaction statistics for a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="get_contacts_needing_attention",
            description="Get contacts that need attention based on contact frequency goals",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {"type": "integer", "default": 10},
                },
            },
        ),
        Tool(
            name="set_contact_frequency",
            description="Set how often you want to contact someone (days between contacts)",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "frequency_days": {"type": "integer"},
                },
                "required": ["contact_id", "frequency_days"],
            },
        ),
        
        # Reminders
        Tool(
            name="create_reminder",
            description="Create a reminder for a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "due_in_days": {"type": "integer", "default": 7},
                    "priority": {"type": "integer", "default": 0, "description": "0=normal, 1=high, 2=urgent"},
                },
                "required": ["contact_id", "title"],
            },
        ),
        Tool(
            name="create_follow_up",
            description="Quick way to create a follow-up reminder",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "days_from_now": {"type": "integer", "default": 7},
                    "title": {"type": "string"},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="get_due_reminders",
            description="Get reminders that are due now or overdue",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="complete_reminder",
            description="Mark a reminder as completed",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer"},
                },
                "required": ["reminder_id"],
            },
        ),
        Tool(
            name="snooze_reminder",
            description="Snooze a reminder",
            inputSchema={
                "type": "object",
                "properties": {
                    "reminder_id": {"type": "integer"},
                    "hours": {"type": "integer", "default": 0},
                    "days": {"type": "integer", "default": 1},
                },
                "required": ["reminder_id"],
            },
        ),
        
        # Calendar & Upcoming
        Tool(
            name="get_upcoming_events",
            description="Get upcoming calendar events",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer", "description": "Filter by contact"},
                    "days": {"type": "integer", "default": 30},
                },
            },
        ),
        Tool(
            name="get_contact_meetings",
            description="Get past meetings with a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "limit": {"type": "integer", "default": 10},
                },
                "required": ["contact_id"],
            },
        ),
        Tool(
            name="get_upcoming_birthdays",
            description="Get contacts with upcoming birthdays",
            inputSchema={
                "type": "object",
                "properties": {
                    "days_ahead": {"type": "integer", "default": 30},
                },
            },
        ),
        
        # Email
        Tool(
            name="get_contact_emails",
            description="Get email threads with a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "limit": {"type": "integer", "default": 20},
                },
                "required": ["contact_id"],
            },
        ),
        
        # Tags
        Tool(
            name="list_tags",
            description="List all tags",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="create_tag",
            description="Create a new tag",
            inputSchema={
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string", "description": "Hex color like #FF5733"},
                    "description": {"type": "string"},
                },
                "required": ["name"],
            },
        ),
        Tool(
            name="tag_contact",
            description="Add a tag to a contact",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_id": {"type": "integer"},
                    "tag_id": {"type": "integer"},
                },
                "required": ["contact_id", "tag_id"],
            },
        ),
        
        # Deduplication
        Tool(
            name="find_duplicates",
            description="Find potential duplicate contacts",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
        Tool(
            name="merge_contacts",
            description="Merge multiple contacts into one",
            inputSchema={
                "type": "object",
                "properties": {
                    "contact_ids": {"type": "array", "items": {"type": "integer"}},
                    "primary_id": {"type": "integer", "description": "The contact to keep"},
                },
                "required": ["contact_ids", "primary_id"],
            },
        ),
        
        # Sync
        Tool(
            name="sync_google",
            description="Sync contacts, calendar, and email from Google",
            inputSchema={
                "type": "object",
                "properties": {
                    "account_id": {"type": "integer"},
                    "sync_contacts": {"type": "boolean", "default": True},
                    "sync_calendar": {"type": "boolean", "default": True},
                    "sync_email": {"type": "boolean", "default": True},
                },
                "required": ["account_id"],
            },
        ),
        Tool(
            name="get_sync_status",
            description="Get overall sync status",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    """Execute a tool"""
    
    try:
        # Contact Management
        if name == "search_contacts":
            result = await api_call("GET", "/search", {"q": arguments["query"], "limit": arguments.get("limit", 10)})
        
        elif name == "get_contact":
            result = await api_call("GET", f"/contacts/{arguments['contact_id']}")
        
        elif name == "list_contacts":
            params = {"page_size": arguments.get("limit", 20)}
            if arguments.get("needs_attention"):
                result = await api_call("GET", "/contacts/needing-attention", {"limit": params["page_size"]})
            else:
                if arguments.get("starred"):
                    params["is_starred"] = True
                result = await api_call("GET", "/contacts", params)
                result = result.get("items", result)
        
        elif name == "create_contact":
            data = {
                "first_name": arguments.get("first_name"),
                "last_name": arguments.get("last_name"),
                "company": arguments.get("company"),
                "job_title": arguments.get("job_title"),
                "notes": arguments.get("notes"),
                "emails": [],
                "phones": [],
            }
            if arguments.get("email"):
                data["emails"] = [{"email": arguments["email"], "type": "work", "is_primary": True}]
            if arguments.get("phone"):
                data["phones"] = [{"number": arguments["phone"], "type": "mobile", "is_primary": True}]
            result = await api_call("POST", "/contacts", data)
        
        elif name == "update_contact":
            contact_id = arguments.pop("contact_id")
            data = {k: v for k, v in arguments.items() if v is not None}
            result = await api_call("PUT", f"/contacts/{contact_id}", data)
        
        # Interaction Tracking
        elif name == "log_call":
            data = {
                "contact_id": arguments["contact_id"],
                "occurred_at": datetime.utcnow().isoformat(),
                "duration_minutes": arguments.get("duration_minutes"),
                "is_outgoing": arguments.get("is_outgoing", True),
                "summary": arguments.get("summary"),
                "was_missed": arguments.get("was_missed", False),
            }
            result = await api_call("POST", "/interactions/call", data)
        
        elif name == "log_meeting":
            data = {
                "contact_ids": arguments["contact_ids"],
                "occurred_at": datetime.utcnow().isoformat(),
                "subject": arguments["subject"],
                "duration_minutes": arguments.get("duration_minutes"),
                "location": arguments.get("location"),
                "summary": arguments.get("summary"),
                "notes": arguments.get("notes"),
                "is_video": arguments.get("is_video", False),
                "video_platform": arguments.get("video_platform"),
            }
            result = await api_call("POST", "/interactions/meeting", data)
        
        elif name == "log_message":
            data = {
                "contact_id": arguments["contact_id"],
                "occurred_at": datetime.utcnow().isoformat(),
                "content": arguments["content"],
                "is_outgoing": arguments.get("is_outgoing", True),
                "channel": arguments.get("channel", "sms"),
            }
            result = await api_call("POST", "/interactions/message", data)
        
        elif name == "add_note":
            data = {
                "contact_id": arguments["contact_id"],
                "content": arguments["content"],
                "subject": arguments.get("subject"),
            }
            result = await api_call("POST", "/interactions/note", data)
        
        elif name == "get_contact_timeline":
            result = await api_call("GET", f"/contacts/{arguments['contact_id']}/timeline", 
                                   {"limit": arguments.get("limit", 20)})
        
        elif name == "get_contact_stats":
            result = await api_call("GET", f"/contacts/{arguments['contact_id']}/stats")
        
        elif name == "get_contacts_needing_attention":
            result = await api_call("GET", "/contacts/needing-attention", 
                                   {"limit": arguments.get("limit", 10)})
        
        elif name == "set_contact_frequency":
            result = await api_call("PUT", f"/contacts/{arguments['contact_id']}/frequency",
                                   {"frequency_days": arguments["frequency_days"]})
        
        # Reminders
        elif name == "create_reminder":
            due_date = datetime.utcnow() + timedelta(days=arguments.get("due_in_days", 7))
            data = {
                "contact_id": arguments["contact_id"],
                "title": arguments["title"],
                "description": arguments.get("description"),
                "due_at": due_date.isoformat(),
                "priority": arguments.get("priority", 0),
            }
            result = await api_call("POST", "/reminders", data)
        
        elif name == "create_follow_up":
            data = {
                "contact_id": arguments["contact_id"],
                "days_from_now": arguments.get("days_from_now", 7),
                "title": arguments.get("title"),
            }
            result = await api_call("POST", "/reminders/follow-up", data)
        
        elif name == "get_due_reminders":
            result = await api_call("GET", "/reminders/due")
        
        elif name == "complete_reminder":
            result = await api_call("POST", f"/reminders/{arguments['reminder_id']}/complete")
        
        elif name == "snooze_reminder":
            data = {
                "hours": arguments.get("hours", 0),
                "days": arguments.get("days", 1),
            }
            result = await api_call("POST", f"/reminders/{arguments['reminder_id']}/snooze", data)
        
        # Calendar
        elif name == "get_upcoming_events":
            params = {"days": arguments.get("days", 30)}
            if arguments.get("contact_id"):
                params["contact_id"] = arguments["contact_id"]
            result = await api_call("GET", "/calendar/events", params)
        
        elif name == "get_contact_meetings":
            result = await api_call("GET", f"/contacts/{arguments['contact_id']}/meetings",
                                   {"limit": arguments.get("limit", 10)})
        
        elif name == "get_upcoming_birthdays":
            result = await api_call("GET", "/upcoming/birthdays",
                                   {"days_ahead": arguments.get("days_ahead", 30)})
        
        # Email
        elif name == "get_contact_emails":
            result = await api_call("GET", f"/contacts/{arguments['contact_id']}/emails",
                                   {"limit": arguments.get("limit", 20)})
        
        # Tags
        elif name == "list_tags":
            result = await api_call("GET", "/tags")
        
        elif name == "create_tag":
            data = {
                "name": arguments["name"],
                "color": arguments.get("color"),
                "description": arguments.get("description"),
            }
            result = await api_call("POST", "/tags", data)
        
        elif name == "tag_contact":
            result = await api_call("POST", 
                                   f"/contacts/{arguments['contact_id']}/tags/{arguments['tag_id']}")
        
        # Deduplication
        elif name == "find_duplicates":
            result = await api_call("GET", "/contacts/duplicates")
        
        elif name == "merge_contacts":
            data = {
                "contact_ids": arguments["contact_ids"],
                "primary_contact_id": arguments["primary_id"],
            }
            result = await api_call("POST", "/contacts/merge", data)
        
        # Sync
        elif name == "sync_google":
            data = {
                "account_id": arguments["account_id"],
                "sync_contacts": arguments.get("sync_contacts", True),
                "sync_calendar": arguments.get("sync_calendar", True),
                "sync_email": arguments.get("sync_email", True),
            }
            result = await api_call("POST", "/sync/full", data)
        
        elif name == "get_sync_status":
            result = await api_call("GET", "/sync/status")
        
        else:
            result = {"error": f"Unknown tool: {name}"}
        
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]
    
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]


async def main():
    """Run the MCP server"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())

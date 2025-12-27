#!/usr/bin/env python3
"""
Shared Taskade Client
=====================

Unified Taskade API client for all brian-system apps.
Supports smart task routing based on keywords including payments, receipts,
parking, and all major payment platforms.

Usage:
    from packages.shared import TaskadeClient, PAYMENT_KEYWORDS

    client = TaskadeClient()
    client.create_smart_task("Square receipt $45.00 lunch")  # Routes to finance

Environment Variables:
    TASKADE_API_KEY - Required API key
    TASKADE_WORKSPACE_ID - Workspace ID (default: lrehjdiszlbcf1ur)
"""

import os
import requests
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from dataclasses import dataclass
from enum import Enum

# Logging
logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

TASKADE_API_KEY = os.environ.get('TASKADE_API_KEY')
TASKADE_BASE_URL = 'https://www.taskade.com/api/v1'
WORKSPACE_ID = os.environ.get('TASKADE_WORKSPACE_ID', 'lrehjdiszlbcf1ur')

if not TASKADE_API_KEY:
    logger.warning("TASKADE_API_KEY not set - Taskade integration will not work")

# =============================================================================
# PROJECT MAPPING
# =============================================================================

PROJECTS = {
    'inbox': 'uuraogs1KouKjfVa',       # Input Processing Center
    'today': 'KaQUiX8RDjs45aS3',       # Daily Command Center
    'finance': 'Y7pcw5ZkbWPHqQ7o',     # Money Management
    'family': 'hyY8yA7L3NqmXbno',      # Kids, School, Home
    'work': 'BNK1KykggEEsPmCs',        # MCR & Business
    'personal': '591XcLXTFf2LrmKA',    # Life Admin
    'creative': 'r5pd54kVd8GciDNd',    # Content Pipeline
    'health': '4v5uBsAzbkTrVRy2',      # Wellness Tracking
    'knowledge': 'hmGChssMPfHB1AtB',   # System Brain
}

# =============================================================================
# PAYMENT PLATFORM KEYWORDS
# =============================================================================

PAYMENT_KEYWORDS = {
    # Point of Sale Systems
    'square': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},
    'toast': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},
    'toasttab': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},
    'clover': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},
    'shopify': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},
    'lightspeed': {'category': 'finance', 'type': 'pos', 'priority': 'normal'},

    # Payment Processors
    'stripe': {'category': 'finance', 'type': 'processor', 'priority': 'normal'},
    'paypal': {'category': 'finance', 'type': 'processor', 'priority': 'normal'},
    'venmo': {'category': 'finance', 'type': 'p2p', 'priority': 'normal'},
    'zelle': {'category': 'finance', 'type': 'p2p', 'priority': 'normal'},
    'cashapp': {'category': 'finance', 'type': 'p2p', 'priority': 'normal'},
    'cash app': {'category': 'finance', 'type': 'p2p', 'priority': 'normal'},
    'apple pay': {'category': 'finance', 'type': 'digital_wallet', 'priority': 'normal'},
    'google pay': {'category': 'finance', 'type': 'digital_wallet', 'priority': 'normal'},

    # Parking Services
    'pmc': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'parkmobile': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'parkwhiz': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'spothero': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'metropolis': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'mpolis': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'parkingpanda': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'parking': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},
    'garage': {'category': 'finance', 'type': 'parking', 'priority': 'normal'},

    # Rideshare/Transportation
    'uber': {'category': 'finance', 'type': 'rideshare', 'priority': 'normal'},
    'lyft': {'category': 'finance', 'type': 'rideshare', 'priority': 'normal'},
    'taxi': {'category': 'finance', 'type': 'rideshare', 'priority': 'normal'},

    # Food Delivery
    'doordash': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},
    'ubereats': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},
    'uber eats': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},
    'grubhub': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},
    'postmates': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},
    'instacart': {'category': 'finance', 'type': 'food_delivery', 'priority': 'normal'},

    # General Finance Terms
    'receipt': {'category': 'finance', 'type': 'receipt', 'priority': 'normal'},
    'expense': {'category': 'finance', 'type': 'expense', 'priority': 'normal'},
    'invoice': {'category': 'finance', 'type': 'invoice', 'priority': 'normal'},
    'payment': {'category': 'finance', 'type': 'payment', 'priority': 'normal'},
    'refund': {'category': 'finance', 'type': 'refund', 'priority': 'normal'},
    'reimburse': {'category': 'finance', 'type': 'reimbursement', 'priority': 'normal'},
    'budget': {'category': 'finance', 'type': 'budget', 'priority': 'normal'},
    '$': {'category': 'finance', 'type': 'amount', 'priority': 'normal'},

    # Subscriptions
    'subscription': {'category': 'finance', 'type': 'subscription', 'priority': 'normal'},
    'renew': {'category': 'finance', 'type': 'subscription', 'priority': 'normal'},
    'recurring': {'category': 'finance', 'type': 'subscription', 'priority': 'normal'},
}

# =============================================================================
# TASK ROUTING RULES
# =============================================================================

TASK_ROUTING_RULES = {
    # Finance - all payment keywords route here
    'finance': {
        'keywords': list(PAYMENT_KEYWORDS.keys()) + ['bank', 'tax', 'accountant', 'cpa'],
        'patterns': [r'\$\d+', r'pay\s+\$', r'charge\s+\$', r'cost\s+\$'],
    },

    # Family
    'family': {
        'keywords': ['kids', 'school', 'miranda', 'luna', 'family', 'pediatr', 'dentist'],
        'patterns': [r'pick\s+up', r'drop\s+off'],
    },

    # Work
    'work': {
        'keywords': ['meeting', 'call', 'business', 'sec', 'music city', 'rodeo',
                     'client', 'partner', 'contract', 'sponsor', 'venue', 'artist'],
        'patterns': [r'zoom\s+call', r'teams\s+meet'],
    },

    # Creative
    'creative': {
        'keywords': ['content', 'video', 'post', 'create', 'design', 'photo',
                     'instagram', 'tiktok', 'youtube', 'edit', 'shoot'],
        'patterns': [r'create\s+\w+', r'design\s+\w+'],
    },

    # Health
    'health': {
        'keywords': ['workout', 'gym', 'health', 'doctor', 'exercise', 'run',
                     'weight', 'diet', 'sleep', 'meditation', 'therapy'],
        'patterns': [r'\d+\s*miles?', r'\d+\s*steps'],
    },

    # Today (urgent)
    'today': {
        'keywords': ['urgent', 'asap', 'today', 'now', 'immediately', 'critical',
                     'deadline', 'due today'],
        'patterns': [r'due\s+today', r'need\s+now'],
    },

    # Personal (default)
    'personal': {
        'keywords': ['home', 'errand', 'grocery', 'clean', 'organize'],
        'patterns': [],
    },
}

# =============================================================================
# DATA CLASSES
# =============================================================================

class TaskPriority(Enum):
    URGENT = 'urgent'
    HIGH = 'high'
    NORMAL = 'normal'
    LOW = 'low'


@dataclass
class TaskResult:
    """Result of task operation"""
    success: bool
    task_id: Optional[str] = None
    project_key: Optional[str] = None
    error: Optional[str] = None
    data: Optional[Dict] = None


# =============================================================================
# TASKADE CLIENT
# =============================================================================

class TaskadeClient:
    """
    Unified Taskade API client with smart routing.

    Features:
    - CRUD operations for tasks
    - Smart routing based on keywords
    - Payment platform recognition
    - Bulk operations
    - Template support
    """

    def __init__(self, api_key: str = None, workspace_id: str = None):
        self.api_key = api_key or TASKADE_API_KEY
        self.workspace_id = workspace_id or WORKSPACE_ID
        self.base_url = TASKADE_BASE_URL
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        if not self.api_key:
            logger.error("Taskade API key not configured")

    def _request(self, method: str, endpoint: str, data: Dict = None) -> Dict:
        """Make API request to Taskade"""
        url = f"{self.base_url}{endpoint}"

        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers, timeout=30)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, json=data, timeout=30)
            elif method == 'PUT':
                response = requests.put(url, headers=self.headers, json=data, timeout=30)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers, timeout=30)
            else:
                return {'success': False, 'error': f'Invalid method: {method}'}

            response.raise_for_status()
            return response.json() if response.text else {'success': True}

        except requests.exceptions.RequestException as e:
            logger.error(f"Taskade API error: {e}")
            return {'success': False, 'error': str(e)}

    # =========================================================================
    # SMART ROUTING
    # =========================================================================

    def detect_category(self, text: str) -> str:
        """
        Detect task category from text using keywords and patterns.
        Returns project key (e.g., 'finance', 'work', 'today')
        """
        import re
        text_lower = text.lower()

        # Check payment keywords first (highest priority for finance)
        for keyword, config in PAYMENT_KEYWORDS.items():
            if keyword in text_lower:
                return config['category']

        # Check routing rules
        for category, rules in TASK_ROUTING_RULES.items():
            # Keyword match
            for keyword in rules.get('keywords', []):
                if keyword in text_lower:
                    return category

            # Pattern match
            for pattern in rules.get('patterns', []):
                if re.search(pattern, text_lower, re.IGNORECASE):
                    return category

        # Default to inbox
        return 'inbox'

    def detect_priority(self, text: str) -> TaskPriority:
        """Detect task priority from text"""
        text_lower = text.lower()

        if any(w in text_lower for w in ['urgent', 'asap', 'critical', 'emergency']):
            return TaskPriority.URGENT
        elif any(w in text_lower for w in ['important', 'high priority', 'priority']):
            return TaskPriority.HIGH
        elif any(w in text_lower for w in ['low priority', 'whenever', 'someday']):
            return TaskPriority.LOW

        return TaskPriority.NORMAL

    def detect_payment_type(self, text: str) -> Optional[Dict]:
        """Detect payment platform/type from text"""
        text_lower = text.lower()

        for keyword, config in PAYMENT_KEYWORDS.items():
            if keyword in text_lower:
                return {
                    'keyword': keyword,
                    'type': config['type'],
                    'category': config['category']
                }

        return None

    # =========================================================================
    # TASK CRUD
    # =========================================================================

    def create_task(
        self,
        project_id: str,
        content: str,
        parent_id: str = None,
        note: str = None
    ) -> TaskResult:
        """Create a task in a specific project"""
        task_data = {
            'content': content,
            'contentType': 'text/plain',
            'placement': 'afterbegin'
        }

        if parent_id:
            task_data['taskId'] = parent_id

        result = self._request('POST', f'/projects/{project_id}/tasks', {'tasks': [task_data]})

        if result.get('success', True) and 'error' not in result:
            task_id = None
            if 'items' in result and result['items']:
                task_id = result['items'][0].get('id')

            # Add note if provided
            if note and task_id:
                self.add_task_note(project_id, task_id, note)

            return TaskResult(success=True, task_id=task_id, data=result)

        return TaskResult(success=False, error=result.get('error', 'Unknown error'))

    def create_smart_task(
        self,
        content: str,
        force_project: str = None,
        note: str = None,
        source: str = None
    ) -> TaskResult:
        """
        Create task with smart routing based on content.

        Args:
            content: Task text (analyzed for keywords)
            force_project: Override auto-detection
            note: Additional note for the task
            source: Source of task (e.g., 'email', 'imessage', 'api')
        """
        # Detect category
        project_key = force_project or self.detect_category(content)
        project_id = PROJECTS.get(project_key)

        if not project_id:
            logger.error(f"Unknown project: {project_key}")
            return TaskResult(success=False, error=f"Unknown project: {project_key}")

        # Detect payment type for enhanced note
        payment_info = self.detect_payment_type(content)

        # Build note with metadata
        full_note = ""
        if source:
            full_note += f"Source: {source}\n"
        if payment_info:
            full_note += f"Payment Type: {payment_info['type']}\n"
        if note:
            full_note += f"\n{note}"

        result = self.create_task(project_id, content, note=full_note.strip() if full_note else None)
        result.project_key = project_key

        logger.info(f"Created task in {project_key}: {content[:50]}...")
        return result

    def get_task(self, project_id: str, task_id: str) -> Dict:
        """Get a specific task"""
        return self._request('GET', f'/projects/{project_id}/tasks/{task_id}')

    def get_all_tasks(self, project_id: str, limit: int = 100) -> Dict:
        """Get all tasks in a project"""
        return self._request('GET', f'/projects/{project_id}/tasks?limit={limit}')

    def update_task(self, project_id: str, task_id: str, content: str) -> Dict:
        """Update task content"""
        data = {'content': content, 'contentType': 'text/plain'}
        return self._request('PUT', f'/projects/{project_id}/tasks/{task_id}', data)

    def complete_task(self, project_id: str, task_id: str) -> Dict:
        """Mark task as complete"""
        return self._request('POST', f'/projects/{project_id}/tasks/{task_id}/complete')

    def delete_task(self, project_id: str, task_id: str) -> Dict:
        """Delete a task"""
        return self._request('DELETE', f'/projects/{project_id}/tasks/{task_id}')

    def add_task_note(self, project_id: str, task_id: str, note: str) -> Dict:
        """Add note to a task"""
        data = {'value': note, 'type': 'text/plain'}
        return self._request('PUT', f'/projects/{project_id}/tasks/{task_id}/note', data)

    def set_task_date(self, project_id: str, task_id: str, date: str) -> Dict:
        """Set task due date (YYYY-MM-DD format)"""
        data = {'start': {'date': date}}
        return self._request('PUT', f'/projects/{project_id}/tasks/{task_id}/date', data)

    # =========================================================================
    # BULK OPERATIONS
    # =========================================================================

    def create_tasks_bulk(self, project_id: str, tasks: List[str]) -> Dict:
        """Create multiple tasks at once"""
        task_data = [
            {'content': t, 'contentType': 'text/plain', 'placement': 'beforeend'}
            for t in tasks
        ]
        return self._request('POST', f'/projects/{project_id}/tasks', {'tasks': task_data})

    def get_all_projects_tasks(self, project_keys: List[str] = None) -> Dict[str, List]:
        """Get tasks from multiple projects"""
        if project_keys is None:
            project_keys = list(PROJECTS.keys())

        all_tasks = {}
        for key in project_keys:
            project_id = PROJECTS.get(key)
            if project_id:
                result = self.get_all_tasks(project_id)
                all_tasks[key] = result.get('items', [])

        return all_tasks

    # =========================================================================
    # SPECIAL TASK TYPES
    # =========================================================================

    def create_receipt_task(
        self,
        merchant: str,
        amount: float,
        date: str = None,
        platform: str = None,
        note: str = None
    ) -> TaskResult:
        """Create a task for a receipt that needs processing"""
        content = f"Process receipt: {merchant} ${amount:.2f}"
        if platform:
            content += f" ({platform})"

        full_note = f"Amount: ${amount:.2f}\nMerchant: {merchant}"
        if date:
            full_note += f"\nDate: {date}"
        if platform:
            full_note += f"\nPlatform: {platform}"
        if note:
            full_note += f"\n\n{note}"

        return self.create_smart_task(content, note=full_note, source='receipt')

    def create_payment_task(
        self,
        description: str,
        amount: float,
        platform: str,
        action: str = 'Review'
    ) -> TaskResult:
        """Create task for payment-related action"""
        content = f"{action}: {platform} ${amount:.2f} - {description}"
        return self.create_smart_task(content, source=f'payment_{platform.lower()}')

    def create_email_task(
        self,
        subject: str,
        sender: str,
        action: str = 'Review',
        project: str = None
    ) -> TaskResult:
        """Create task from email"""
        content = f"{action}: {subject}"
        note = f"From: {sender}"
        return self.create_smart_task(content, force_project=project, note=note, source='email')

    def create_imessage_task(
        self,
        message: str,
        sender: str,
        has_receipt_url: bool = False
    ) -> TaskResult:
        """Create task from iMessage"""
        if has_receipt_url:
            content = f"Process iMessage receipt from {sender}"
            note = f"Message: {message[:200]}"
            return self.create_smart_task(content, force_project='finance', note=note, source='imessage')
        else:
            content = f"Reply to {sender}: {message[:100]}"
            return self.create_smart_task(content, source='imessage')


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

_client: TaskadeClient = None

def get_taskade_client() -> TaskadeClient:
    """Get singleton Taskade client"""
    global _client
    if _client is None:
        _client = TaskadeClient()
    return _client


def create_smart_task(content: str, **kwargs) -> TaskResult:
    """Quick function to create a smart task"""
    return get_taskade_client().create_smart_task(content, **kwargs)


def create_receipt_task(merchant: str, amount: float, **kwargs) -> TaskResult:
    """Quick function to create receipt task"""
    return get_taskade_client().create_receipt_task(merchant, amount, **kwargs)


# =============================================================================
# CLI
# =============================================================================

if __name__ == '__main__':
    import sys

    client = TaskadeClient()

    if not client.api_key:
        print("Error: TASKADE_API_KEY not set")
        sys.exit(1)

    # Test detection
    test_cases = [
        "Square receipt $45.00 lunch meeting",
        "Toast payment for team dinner",
        "PMC parking downtown $12",
        "Uber ride to airport $35",
        "Pay Miranda's piano lessons",
        "Urgent: deadline tomorrow",
        "Call with MCR sponsor",
        "Edit video for Instagram",
    ]

    print("Task Routing Test")
    print("=" * 60)

    for text in test_cases:
        category = client.detect_category(text)
        payment = client.detect_payment_type(text)
        priority = client.detect_priority(text)

        print(f"\n'{text}'")
        print(f"  -> Category: {category}")
        print(f"  -> Priority: {priority.value}")
        if payment:
            print(f"  -> Payment: {payment}")

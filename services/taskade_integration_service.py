"""
Enhanced Taskade Integration Service

Full CRUD operations for Taskade API:
- Create, Read, Update, Delete tasks
- Complete/uncomplete tasks
- Move tasks between projects
- Real-time sync
- Bulk operations

Integrated with Motion-style auto-scheduling

Updated: 2025-10-30 - Fixed project IDs to correct values from Taskade API
"""

import os
import requests
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional

# Taskade API Configuration
# SECURITY: Never hardcode API keys - always use environment variables
TASKADE_API_KEY = os.environ.get('TASKADE_API_KEY')
TASKADE_BASE_URL = 'https://www.taskade.com/api/v1'
WORKSPACE_ID = os.environ.get('TASKADE_WORKSPACE_ID', 'lrehjdiszlbcf1ur')

if not TASKADE_API_KEY:
    import logging
    logging.warning("TASKADE_API_KEY not set in environment - Taskade integration will fail")

# Your 12 Core Projects (Correct IDs from API)
PROJECTS = {
    'inbox': 'uuraogs1KouKjfVa',       # 📥 INBOX - Input Processing Center
    'today': 'KaQUiX8RDjs45aS3',       # 🗓️ TODAY - Daily Command Center
    'finance': 'Y7pcw5ZkbWPHqQ7o',     # 💰 FINANCE - Money Management
    'family': 'hyY8yA7L3NqmXbno',      # 👨‍👩‍👧 FAMILY - Kids, School, Home
    'work': 'BNK1KykggEEsPmCs',        # 💼 WORK - MCR & Down Home
    'personal': '591XcLXTFf2LrmKA',    # 🏠 PERSONAL - Life Admin
    'creative': 'r5pd54kVd8GciDNd',    # 🎨 CREATIVE - Content Pipeline
    'health': '4v5uBsAzbkTrVRy2',      # ❤️ HEALTH - Wellness Tracking
    'knowledge': 'hmGChssMPfHB1AtB',   # 🧠 KNOWLEDGE - System Brain
    # Note: routines, journal, archive projects not found in current workspace
    # These may need to be created or have different names
}


class TaskadeIntegration:
    """
    Enhanced Taskade integration with full CRUD operations.
    Supports both global API key and per-user credentials for multi-tenant mode.
    """

    def __init__(self, api_key=None, workspace_id=None, user_id=None):
        """
        Initialize Taskade integration.

        Args:
            api_key: Taskade API key (defaults to env var)
            workspace_id: Taskade workspace ID (defaults to env var)
            user_id: Optional user ID for per-user credentials (multi-tenant mode)
        """
        self.user_id = user_id
        self._user_credentials_service = None

        # If user_id provided, try to get per-user credentials
        if user_id:
            user_creds = self._get_user_taskade_credentials(user_id)
            if user_creds:
                self.api_key = user_creds.get('api_key')
                self.workspace_id = user_creds.get('workspace_id') or WORKSPACE_ID
            else:
                self.api_key = api_key or TASKADE_API_KEY
                self.workspace_id = workspace_id or WORKSPACE_ID
        else:
            self.api_key = api_key or TASKADE_API_KEY
            self.workspace_id = workspace_id or WORKSPACE_ID

        self.base_url = TASKADE_BASE_URL
        self.headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

    def _get_user_credentials_service(self):
        """Lazy-load user credentials service for multi-tenant mode."""
        if self._user_credentials_service is None:
            try:
                from services.user_credentials_service import get_user_credentials_service
                self._user_credentials_service = get_user_credentials_service()
            except ImportError:
                pass
        return self._user_credentials_service

    def _get_user_taskade_credentials(self, user_id: str) -> Optional[Dict]:
        """
        Get Taskade credentials for a specific user.

        Args:
            user_id: User's UUID

        Returns:
            Dict with api_key and workspace_id, or None
        """
        creds_service = self._get_user_credentials_service()
        if not creds_service:
            return None

        creds = creds_service.get_credential(user_id, 'taskade')
        if creds:
            return {
                'api_key': creds.get('api_key'),
                'workspace_id': creds.get('workspace_id')
            }
        return None

    @classmethod
    def for_user(cls, user_id: str) -> 'TaskadeIntegration':
        """
        Create a TaskadeIntegration instance for a specific user.

        Args:
            user_id: User's UUID

        Returns:
            TaskadeIntegration instance configured for the user
        """
        return cls(user_id=user_id)

    def get_user_projects(self) -> List[Dict]:
        """
        Get all projects in the user's workspace.

        Returns:
            List of project dicts
        """
        endpoint = f'/workspaces/{self.workspace_id}/projects'
        result = self._request('GET', endpoint)
        return result.get('items', []) if result else []

    def get_user_workspace_id(self) -> str:
        """Get the workspace ID for this instance."""
        return self.workspace_id

    def _request(self, method, endpoint, data=None):
        """Make API request to Taskade"""
        url = f"{self.base_url}{endpoint}"

        try:
            if method == 'GET':
                response = requests.get(url, headers=self.headers)
            elif method == 'POST':
                response = requests.post(url, headers=self.headers, json=data)
            elif method == 'PUT':
                response = requests.put(url, headers=self.headers, json=data)
            elif method == 'DELETE':
                response = requests.delete(url, headers=self.headers)

            response.raise_for_status()
            return response.json() if response.text else {'success': True}

        except requests.exceptions.RequestException as e:
            return {'error': str(e), 'success': False}

    # ==================== TASK CRUD OPERATIONS ====================

    def create_task(self, project_id, content, parent_id=None, metadata=None):
        """
        Create a new task in a project

        Args:
            project_id: Project ID
            content: Task content/title
            parent_id: Optional parent task ID (for subtasks)
            metadata: Optional dict with priority, deadline, tags, etc.
        """
        task_data = {
            'content': content,
            'contentType': 'text/plain',
            'placement': 'afterbegin'  # Add at top of list
        }

        # Add parent task ID if creating a subtask
        if parent_id:
            task_data['taskId'] = parent_id

        endpoint = f'/projects/{project_id}/tasks'
        result = self._request('POST', endpoint, {'tasks': [task_data]})

        if result.get('success') and metadata:
            # Add metadata (tags, priority, etc.) if task was created
            task_id = result.get('items', [{}])[0].get('id')
            if task_id:
                self._update_task_metadata(project_id, task_id, metadata)

        return result

    def get_task(self, project_id, task_id):
        """Get a specific task by ID"""
        endpoint = f'/projects/{project_id}/tasks/{task_id}'
        return self._request('GET', endpoint)

    def get_all_tasks(self, project_id, limit=100):
        """Get all tasks in a project"""
        endpoint = f'/projects/{project_id}/tasks?limit={limit}'
        return self._request('GET', endpoint)

    def update_task(self, project_id, task_id, content=None, metadata=None):
        """
        Update task content and/or metadata

        Args:
            content: New task content
            metadata: Dict with priority, deadline, tags, assignees
        """
        if content:
            data = {
                'content': content,
                'contentType': 'text/plain'
            }
            endpoint = f'/projects/{project_id}/tasks/{task_id}'
            result = self._request('PUT', endpoint, data)

            if not result.get('success'):
                return result

        if metadata:
            self._update_task_metadata(project_id, task_id, metadata)

        return {'success': True, 'task_id': task_id}

    def delete_task(self, project_id, task_id):
        """Delete a task"""
        endpoint = f'/projects/{project_id}/tasks/{task_id}'
        return self._request('DELETE', endpoint)

    def complete_task(self, project_id, task_id):
        """Mark task as complete"""
        endpoint = f'/projects/{project_id}/tasks/{task_id}/complete'
        return self._request('POST', endpoint)

    def uncomplete_task(self, project_id, task_id):
        """Mark task as incomplete"""
        # Taskade doesn't have direct uncomplete endpoint
        # We update the task to reset completion
        return self.update_task(project_id, task_id, metadata={'completed': False})

    def move_task(self, project_id, task_id, target_task_id, position='afterend'):
        """
        Move task to new position

        Args:
            position: beforebegin, afterbegin, beforeend, afterend
        """
        data = {
            'target': {
                'taskId': target_task_id,
                'position': position
            }
        }
        endpoint = f'/projects/{project_id}/tasks/{task_id}/move'
        return self._request('POST', endpoint, data)

    # ==================== TASK METADATA ====================

    def _update_task_metadata(self, project_id, task_id, metadata):
        """Update task metadata (priority, deadline, tags, assignees)"""
        # Priority (if provided)
        if 'priority' in metadata:
            self._set_task_priority(project_id, task_id, metadata['priority'])

        # Deadline (if provided)
        if 'deadline' in metadata:
            self._set_task_deadline(project_id, task_id, metadata['deadline'])

        # Tags (if provided)
        if 'tags' in metadata:
            self._set_task_tags(project_id, task_id, metadata['tags'])

        # Assignees (if provided)
        if 'assignees' in metadata:
            self._set_task_assignees(project_id, task_id, metadata['assignees'])

        # Note (if provided)
        if 'note' in metadata:
            self._set_task_note(project_id, task_id, metadata['note'])

    def _set_task_priority(self, project_id, task_id, priority):
        """
        Set task priority (urgent, high, normal, low)

        Taskade represents priority via the 'priority' field on tasks.
        Values: 1 (urgent), 2 (high), 3 (normal/default), 4 (low)
        """
        priority_map = {
            'urgent': 1,
            'high': 2,
            'normal': 3,
            'low': 4
        }
        priority_value = priority_map.get(priority.lower(), 3)

        data = {'priority': priority_value}
        endpoint = f'/projects/{project_id}/tasks/{task_id}'
        return self._request('PATCH', endpoint, data)

    def _set_task_deadline(self, project_id, task_id, deadline):
        """
        Set task deadline

        Args:
            deadline: datetime object or ISO string
        """
        if isinstance(deadline, datetime):
            deadline_str = deadline.strftime('%Y-%m-%d')
        else:
            deadline_str = deadline

        data = {
            'start': {
                'date': deadline_str
            }
        }
        endpoint = f'/projects/{project_id}/tasks/{task_id}/date'
        return self._request('PUT', endpoint, data)

    def _set_task_tags(self, project_id, task_id, tags):
        """
        Set task tags by appending hashtags to task content.

        Taskade uses #hashtags in the task content for tagging.
        This fetches the current task, appends tags if not present,
        and updates the content.

        Args:
            tags: List of tag names (without # prefix)
        """
        if not tags:
            return

        try:
            # Get current task content
            endpoint = f'/projects/{project_id}/tasks/{task_id}'
            task = self._request('GET', endpoint)

            if not task or 'content' not in task:
                return

            current_content = task.get('content', '')

            # Format tags as hashtags
            tag_string = ' '.join(f'#{tag.replace(" ", "_")}' for tag in tags)

            # Check if tags already exist in content
            if tag_string not in current_content:
                # Append tags to content
                new_content = f"{current_content} {tag_string}".strip()
                data = {'content': new_content}
                return self._request('PATCH', endpoint, data)

        except Exception as e:
            # Log but don't fail - tags are optional
            print(f"Warning: Could not set tags on task {task_id}: {e}")

    def _set_task_assignees(self, project_id, task_id, assignees):
        """
        Assign users to task

        Args:
            assignees: List of user handles
        """
        data = {
            'handles': assignees
        }
        endpoint = f'/projects/{project_id}/tasks/{task_id}/assignees'
        return self._request('PUT', endpoint, data)

    def _set_task_note(self, project_id, task_id, note):
        """Add note to task"""
        data = {
            'value': note,
            'type': 'text/plain'
        }
        endpoint = f'/projects/{project_id}/tasks/{task_id}/note'
        return self._request('PUT', endpoint, data)

    # ==================== BULK OPERATIONS ====================

    def create_tasks_bulk(self, project_id, tasks):
        """
        Create multiple tasks at once

        Args:
            tasks: List of task dicts with content, metadata, etc.
        """
        task_data = []
        for task in tasks:
            task_data.append({
                'content': task['content'],
                'contentType': 'text/plain',
                'placement': 'beforeend'
            })

        endpoint = f'/projects/{project_id}/tasks'
        return self._request('POST', endpoint, {'tasks': task_data})

    def get_all_projects_tasks(self, project_keys=None):
        """
        Get tasks from multiple projects

        Args:
            project_keys: List of project keys (e.g., ['inbox', 'today'])
                         If None, gets all projects
        """
        if project_keys is None:
            project_keys = PROJECTS.keys()

        all_tasks = {}
        for key in project_keys:
            project_id = PROJECTS.get(key)
            if project_id:
                tasks = self.get_all_tasks(project_id)
                all_tasks[key] = tasks.get('items', [])

        return all_tasks

    # ==================== SMART TASK ROUTING ====================

    def route_task_to_project(self, content, context=None):
        """
        Intelligently route task to correct project

        Uses keywords and context to determine best project
        """
        content_lower = content.lower()

        # Finance-related
        if any(word in content_lower for word in ['expense', 'receipt', 'budget', 'invoice', '$', 'payment']):
            return 'finance'

        # Family-related
        if any(word in content_lower for word in ['kids', 'school', 'miranda', 'luna', 'family']):
            return 'family'

        # Work-related
        if any(word in content_lower for word in ['meeting', 'call', 'down home', 'mcr', 'client', 'partner']):
            return 'work'

        # Creative-related
        if any(word in content_lower for word in ['content', 'video', 'post', 'create', 'design']):
            return 'creative'

        # Health-related
        if any(word in content_lower for word in ['workout', 'gym', 'health', 'doctor', 'exercise']):
            return 'health'

        # Urgent/Today markers
        if any(word in content_lower for word in ['urgent', 'asap', 'today', 'now']):
            return 'today'

        # Default to inbox
        return 'inbox'

    def create_smart_task(self, content, metadata=None, auto_route=True):
        """
        Create task with smart routing

        Args:
            content: Task content
            metadata: Optional metadata
            auto_route: If True, automatically route to best project
        """
        if auto_route:
            project_key = self.route_task_to_project(content)
        else:
            project_key = metadata.get('project', 'inbox')

        project_id = PROJECTS[project_key]

        return self.create_task(project_id, content, metadata=metadata)

    # ==================== TASK FILTERING & SEARCH ====================

    def get_tasks_by_criteria(self, criteria):
        """
        Get tasks matching specific criteria

        Args:
            criteria: Dict with filters
                - projects: List of project keys
                - completed: True/False/None (all)
                - priority: urgent/high/normal/low
                - has_deadline: True/False
                - search: Search term
        """
        project_keys = criteria.get('projects', PROJECTS.keys())
        all_tasks = self.get_all_projects_tasks(project_keys)

        # Flatten tasks from all projects
        filtered_tasks = []
        for project_key, tasks in all_tasks.items():
            for task in tasks:
                # Add project info
                task['project_key'] = project_key
                task['project_id'] = PROJECTS[project_key]

                # Apply filters
                if self._task_matches_criteria(task, criteria):
                    filtered_tasks.append(task)

        return filtered_tasks

    def _task_matches_criteria(self, task, criteria):
        """Check if task matches filter criteria"""
        # Completion filter
        if 'completed' in criteria:
            if criteria['completed'] != task.get('completed', False):
                return False

        # Search filter
        if 'search' in criteria:
            search_term = criteria['search'].lower()
            content = task.get('content', '').lower()
            if search_term not in content:
                return False

        # Has deadline filter
        if 'has_deadline' in criteria:
            has_deadline = bool(task.get('date'))
            if criteria['has_deadline'] != has_deadline:
                return False

        return True

    def get_today_tasks(self):
        """Get all tasks from TODAY project"""
        return self.get_all_tasks(PROJECTS['today'])

    def get_urgent_tasks(self):
        """Get all urgent tasks across projects"""
        return self.get_tasks_by_criteria({
            'completed': False,
            'search': 'urgent'
        })

    def get_upcoming_deadlines(self, days=7):
        """Get tasks with deadlines in next N days"""
        # This requires parsing task dates
        # Simplified version
        return self.get_tasks_by_criteria({
            'completed': False,
            'has_deadline': True
        })

    # ==================== TASK TEMPLATES ====================

    def create_from_template(self, template_name, variables=None):
        """
        Create task from template

        Templates:
            - meeting_prep: Prep task before meeting
            - follow_up: Follow up task
            - deadline_reminder: Deadline reminder
        """
        templates = {
            'meeting_prep': {
                'content': '🎯 Prep for: {meeting_name}',
                'metadata': {
                    'priority': 'high',
                    'note': '- Review agenda\n- Prepare materials\n- Check tech setup'
                }
            },
            'follow_up': {
                'content': '📧 Follow up: {subject}',
                'metadata': {
                    'deadline': (datetime.now() + timedelta(days=3)).strftime('%Y-%m-%d'),
                    'note': 'Check if response received'
                }
            },
            'deadline_reminder': {
                'content': '⏰ Reminder: {task_name} due {deadline}',
                'metadata': {
                    'priority': 'urgent'
                }
            }
        }

        template = templates.get(template_name)
        if not template:
            return {'error': f'Template {template_name} not found'}

        # Replace variables
        content = template['content'].format(**(variables or {}))
        metadata = template['metadata'].copy()

        # Create task in appropriate project
        project_key = self.route_task_to_project(content)
        project_id = PROJECTS[project_key]

        return self.create_task(project_id, content, metadata=metadata)


# Singleton
_taskade_service = None

def get_taskade_service():
    """Get or create Taskade service singleton"""
    global _taskade_service
    if _taskade_service is None:
        _taskade_service = TaskadeIntegration()
    return _taskade_service

"""
Workflow Automation Service - Your Personal IFTTT on Steroids

Create custom automations in plain English:
- "Every Monday at 9am, create a 'Weekly Planning' task"
- "When I complete a client meeting, create a follow-up task for 3 days later"
- "If a receipt over $100 is uploaded, create a task to review it"
- "When inbox reaches zero, celebrate with a notification"

This is Phase 3 from the roadmap: Natural Language Workflows
"""

import os
import json
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Callable
import anthropic

# Import our services
try:
    from taskade_integration_service import get_taskade_service
except ImportError:
    import sys
    sys.path.append(os.path.dirname(__file__))
    from taskade_integration_service import get_taskade_service


class WorkflowAutomation:
    """
    Natural Language Workflow Engine

    Users can create automations like:
    - Time-based triggers ("Every Monday at 9am")
    - Event-based triggers ("When task completed")
    - Condition-based triggers ("If receipt > $100")
    - Multi-step workflows ("Do this, then do that")
    """

    def __init__(self):
        self.taskade = get_taskade_service()
        self.anthropic_key = os.environ.get('ANTHROPIC_API_KEY')
        self.client = anthropic.Anthropic(api_key=self.anthropic_key) if self.anthropic_key else None
        self.workflows = self._load_workflows()
        self.event_handlers = self._setup_event_handlers()

    def _load_workflows(self) -> Dict:
        """Load saved workflows from JSON"""
        workflow_file = 'workflows.json'
        if os.path.exists(workflow_file):
            with open(workflow_file, 'r') as f:
                return json.load(f)
        return {'workflows': [], 'active': True}

    def _save_workflows(self):
        """Save workflows to JSON"""
        with open('workflows.json', 'w') as f:
            json.dump(self.workflows, f, indent=2)

    # ==================== WORKFLOW CREATION ====================

    def create_workflow_from_text(self, description: str) -> Dict:
        """
        Create a workflow from plain English description

        Examples:
        - "Every Monday at 9am, create a 'Weekly Planning' task in TODAY"
        - "When I complete a task tagged 'meeting', create a follow-up task"
        - "If unmatched transactions > 10, remind me to match receipts"
        """
        if not self.client:
            return {'success': False, 'error': 'AI client not configured'}

        try:
            # Use Claude to parse the workflow
            prompt = f"""Parse this workflow automation request into structured format:

"{description}"

Extract:
1. Trigger type (time-based, event-based, condition-based)
2. Trigger details (time, event name, condition)
3. Action to perform
4. Action parameters

Return as JSON:
{{
  "trigger_type": "time|event|condition",
  "trigger": {{}},
  "action": "create_task|send_notification|update_task|etc",
  "action_params": {{}}
}}"""

            message = self.client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )

            # Parse Claude's response
            response_text = message.content[0].text
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                workflow_config = json.loads(json_match.group())

                # Create workflow
                workflow = {
                    'id': f"workflow_{len(self.workflows['workflows']) + 1}",
                    'description': description,
                    'config': workflow_config,
                    'created_at': datetime.now().isoformat(),
                    'active': True,
                    'run_count': 0,
                    'last_run': None
                }

                self.workflows['workflows'].append(workflow)
                self._save_workflows()

                return {
                    'success': True,
                    'workflow': workflow,
                    'message': f"Workflow created: {description}"
                }
            else:
                return {'success': False, 'error': 'Could not parse workflow'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    # ==================== BUILT-IN WORKFLOW TEMPLATES ====================

    def add_recurring_task_workflow(self, schedule: str, task_content: str, project: str = 'today'):
        """
        Add a recurring task workflow

        Args:
            schedule: "daily", "weekly:monday", "monthly:1", "weekdays"
            task_content: Task to create
            project: Which project to add to
        """
        workflow = {
            'id': f"workflow_{len(self.workflows['workflows']) + 1}",
            'description': f"Create '{task_content}' {schedule}",
            'config': {
                'trigger_type': 'time',
                'trigger': {'schedule': schedule},
                'action': 'create_task',
                'action_params': {
                    'content': task_content,
                    'project': project
                }
            },
            'created_at': datetime.now().isoformat(),
            'active': True,
            'run_count': 0,
            'last_run': None
        }

        self.workflows['workflows'].append(workflow)
        self._save_workflows()

        return {'success': True, 'workflow': workflow}

    def add_task_completion_workflow(self, trigger_pattern: str, action_task: str, delay_days: int = 0):
        """
        Create a task when another task is completed

        Args:
            trigger_pattern: Pattern to match in completed task (e.g., "client meeting")
            action_task: Task to create when triggered
            delay_days: Days to wait before creating task
        """
        workflow = {
            'id': f"workflow_{len(self.workflows['workflows']) + 1}",
            'description': f"When task containing '{trigger_pattern}' is completed, create '{action_task}'",
            'config': {
                'trigger_type': 'event',
                'trigger': {
                    'event': 'task_completed',
                    'pattern': trigger_pattern
                },
                'action': 'create_task',
                'action_params': {
                    'content': action_task,
                    'delay_days': delay_days
                }
            },
            'created_at': datetime.now().isoformat(),
            'active': True,
            'run_count': 0,
            'last_run': None
        }

        self.workflows['workflows'].append(workflow)
        self._save_workflows()

        return {'success': True, 'workflow': workflow}

    def add_conditional_workflow(self, condition: str, action_description: str):
        """
        Create workflow based on condition

        Args:
            condition: e.g., "unmatched_transactions > 10"
            action_description: What to do when condition is met
        """
        workflow = {
            'id': f"workflow_{len(self.workflows['workflows']) + 1}",
            'description': f"When {condition}, {action_description}",
            'config': {
                'trigger_type': 'condition',
                'trigger': {'condition': condition},
                'action': 'conditional_action',
                'action_params': {'description': action_description}
            },
            'created_at': datetime.now().isoformat(),
            'active': True,
            'run_count': 0,
            'last_run': None
        }

        self.workflows['workflows'].append(workflow)
        self._save_workflows()

        return {'success': True, 'workflow': workflow}

    # ==================== EVENT HANDLERS ====================

    def _setup_event_handlers(self) -> Dict[str, List[Callable]]:
        """Setup event handlers for workflow triggers"""
        return {
            'task_created': [],
            'task_completed': [],
            'task_updated': [],
            'receipt_uploaded': [],
            'email_received': [],
            'transaction_matched': []
        }

    def trigger_event(self, event_name: str, event_data: Dict):
        """
        Trigger workflows based on an event

        Called by other services when events occur
        """
        print(f"Event triggered: {event_name}")

        active_workflows = [w for w in self.workflows['workflows'] if w['active']]

        for workflow in active_workflows:
            config = workflow['config']

            # Check if this workflow listens to this event
            if config['trigger_type'] == 'event':
                trigger_event = config['trigger'].get('event')

                if trigger_event == event_name:
                    # Check if event matches pattern
                    if self._event_matches_workflow(workflow, event_data):
                        print(f"Executing workflow: {workflow['description']}")
                        self._execute_workflow_action(workflow, event_data)

    def _event_matches_workflow(self, workflow: Dict, event_data: Dict) -> bool:
        """Check if event matches workflow trigger pattern"""
        config = workflow['config']
        trigger = config.get('trigger', {})

        # Check pattern matching
        if 'pattern' in trigger:
            pattern = trigger['pattern'].lower()
            # Check all string values in event_data
            for value in event_data.values():
                if isinstance(value, str) and pattern in value.lower():
                    return True
            return False

        # No pattern means trigger on any event of this type
        return True

    def _execute_workflow_action(self, workflow: Dict, context: Dict = None):
        """Execute the action defined in a workflow"""
        config = workflow['config']
        action = config['action']
        params = config.get('action_params', {})

        try:
            if action == 'create_task':
                # Create task
                content = params.get('content', '')
                project = params.get('project', 'today')
                delay_days = params.get('delay_days', 0)

                # Add delay if specified
                if delay_days > 0:
                    deadline = (datetime.now() + timedelta(days=delay_days)).strftime('%Y-%m-%d')
                    metadata = {'deadline': deadline}
                else:
                    metadata = None

                result = self.taskade.create_smart_task(content, metadata=metadata)

                if result.get('success'):
                    print(f"✅ Task created: {content}")
                    workflow['run_count'] += 1
                    workflow['last_run'] = datetime.now().isoformat()
                    self._save_workflows()
                else:
                    print(f"❌ Task creation failed: {result.get('error')}")

            elif action == 'send_notification':
                # Send notification
                message = params.get('message', '')
                print(f"📬 Notification: {message}")
                # Here you would integrate with notification service

            elif action == 'update_task':
                # Update existing task
                task_id = params.get('task_id')
                updates = params.get('updates', {})
                # Implement task update logic

            # Update workflow stats
            workflow['run_count'] += 1
            workflow['last_run'] = datetime.now().isoformat()
            self._save_workflows()

        except Exception as e:
            print(f"❌ Workflow execution error: {str(e)}")

    # ==================== WORKFLOW MANAGEMENT ====================

    def list_workflows(self) -> List[Dict]:
        """List all workflows"""
        return self.workflows.get('workflows', [])

    def get_workflow(self, workflow_id: str) -> Optional[Dict]:
        """Get a specific workflow"""
        for workflow in self.workflows['workflows']:
            if workflow['id'] == workflow_id:
                return workflow
        return None

    def toggle_workflow(self, workflow_id: str) -> Dict:
        """Enable or disable a workflow"""
        workflow = self.get_workflow(workflow_id)
        if workflow:
            workflow['active'] = not workflow['active']
            self._save_workflows()
            status = "enabled" if workflow['active'] else "disabled"
            return {'success': True, 'message': f"Workflow {status}"}
        return {'success': False, 'error': 'Workflow not found'}

    def delete_workflow(self, workflow_id: str) -> Dict:
        """Delete a workflow"""
        self.workflows['workflows'] = [
            w for w in self.workflows['workflows'] if w['id'] != workflow_id
        ]
        self._save_workflows()
        return {'success': True, 'message': 'Workflow deleted'}

    # ==================== EXAMPLE WORKFLOWS ====================

    def setup_default_workflows(self):
        """Set up useful default workflows"""

        # 1. Weekly planning task
        self.add_recurring_task_workflow(
            schedule='weekly:monday',
            task_content='🗓️ Weekly Planning & Review',
            project='today'
        )

        # 2. Follow up after client meetings
        self.add_task_completion_workflow(
            trigger_pattern='client meeting',
            action_task='📧 Send follow-up email to client',
            delay_days=1
        )

        # 3. Daily expense review
        self.add_recurring_task_workflow(
            schedule='daily',
            task_content='💰 Review and categorize expenses',
            project='finance'
        )

        # 4. Friday afternoon creative time
        self.add_recurring_task_workflow(
            schedule='weekly:friday',
            task_content='🎨 Creative project work (2 hours)',
            project='creative'
        )

        print("✅ Default workflows created!")


# Singleton
_workflow_service = None

def get_workflow_service():
    """Get or create workflow service singleton"""
    global _workflow_service
    if _workflow_service is None:
        _workflow_service = WorkflowAutomation()
    return _workflow_service

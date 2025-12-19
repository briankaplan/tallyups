"""
Taskade API Blueprint
======================
API endpoints for Taskade integration - task management across 9 core projects.

Routes:
- GET  /api/taskade/projects - List all projects
- GET  /api/taskade/tasks/<project> - Get tasks from a project
- POST /api/taskade/tasks - Create a new task (auto-routed)
- PUT  /api/taskade/tasks/<project>/<task_id> - Update a task
- DELETE /api/taskade/tasks/<project>/<task_id> - Delete a task
- POST /api/taskade/tasks/<project>/<task_id>/complete - Complete a task
- POST /api/taskade/sync-unmatched - Sync unmatched transactions to Finance project
- GET  /api/taskade/today - Get today's tasks
"""

import os
from flask import Blueprint, request, jsonify

from logging_config import get_logger

logger = get_logger("routes.taskade")

# Create blueprint
taskade_bp = Blueprint('taskade', __name__, url_prefix='/api/taskade')


def get_dependencies():
    """Lazy import dependencies to avoid circular imports."""
    from viewer_server import is_authenticated
    from services.taskade_integration_service import TaskadeIntegration, PROJECTS, get_taskade_service
    return is_authenticated, TaskadeIntegration, PROJECTS, get_taskade_service


def get_csrf_exempt():
    """Import csrf_exempt_route decorator."""
    from viewer_server import csrf_exempt_route
    return csrf_exempt_route


# Create decorator that applies CSRF exemption
def csrf_exempt_api(f):
    """Mark a route as CSRF exempt for API access."""
    f._csrf_exempt = True
    return f


def check_auth():
    """Check if request is authenticated via admin key or session."""
    admin_key = request.args.get('admin_key') or request.headers.get('X-Admin-Key')
    expected_key = os.getenv('ADMIN_API_KEY')
    if admin_key == expected_key:
        return True
    is_authenticated, _, _, _ = get_dependencies()
    if is_authenticated():
        return True
    return False


@taskade_bp.route("/projects", methods=["GET"])
def get_projects():
    """Get all Taskade projects."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        _, _, PROJECTS, _ = get_dependencies()
        projects = [
            {'key': key, 'id': pid, 'name': key.title()}
            for key, pid in PROJECTS.items()
        ]
        return jsonify({'ok': True, 'projects': projects})
    except Exception as e:
        logger.error(f"Error getting projects: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/tasks/<project>", methods=["GET"])
def get_project_tasks(project):
    """Get all tasks from a project."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        _, _, PROJECTS, get_taskade_service = get_dependencies()

        project_id = PROJECTS.get(project)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project}'}), 404

        taskade = get_taskade_service()
        result = taskade.get_all_tasks(project_id)

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({
            'ok': True,
            'project': project,
            'tasks': result.get('items', [])
        })
    except Exception as e:
        logger.error(f"Error getting tasks: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/tasks", methods=["POST"])
@csrf_exempt_api
def create_task():
    """
    Create a new task with auto-routing.

    Body:
    {
        "content": "Task description",
        "project": "finance",  // optional - will auto-route if not specified
        "metadata": {          // optional
            "deadline": "2025-01-15",
            "note": "Additional context"
        }
    }
    """
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data or not data.get('content'):
            return jsonify({'ok': False, 'error': 'content is required'}), 400

        _, _, PROJECTS, get_taskade_service = get_dependencies()
        taskade = get_taskade_service()

        content = data['content']
        metadata = data.get('metadata', {})
        project_key = data.get('project')

        # Auto-route if project not specified
        if not project_key:
            project_key = taskade.route_task_to_project(content)

        project_id = PROJECTS.get(project_key)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project_key}'}), 404

        result = taskade.create_task(project_id, content, metadata=metadata)

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({
            'ok': True,
            'message': 'Task created',
            'project': project_key,
            'result': result
        })
    except Exception as e:
        logger.error(f"Error creating task: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/tasks/<project>/<task_id>", methods=["PUT"])
@csrf_exempt_api
def update_task(project, task_id):
    """Update a task."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data:
            return jsonify({'ok': False, 'error': 'No data provided'}), 400

        _, _, PROJECTS, get_taskade_service = get_dependencies()

        project_id = PROJECTS.get(project)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project}'}), 404

        taskade = get_taskade_service()
        result = taskade.update_task(
            project_id,
            task_id,
            content=data.get('content'),
            metadata=data.get('metadata')
        )

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({'ok': True, 'message': 'Task updated', 'result': result})
    except Exception as e:
        logger.error(f"Error updating task: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/tasks/<project>/<task_id>", methods=["DELETE"])
@csrf_exempt_api
def delete_task(project, task_id):
    """Delete a task."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        _, _, PROJECTS, get_taskade_service = get_dependencies()

        project_id = PROJECTS.get(project)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project}'}), 404

        taskade = get_taskade_service()
        result = taskade.delete_task(project_id, task_id)

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({'ok': True, 'message': 'Task deleted'})
    except Exception as e:
        logger.error(f"Error deleting task: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/tasks/<project>/<task_id>/complete", methods=["POST"])
@csrf_exempt_api
def complete_task(project, task_id):
    """Mark a task as complete."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        _, _, PROJECTS, get_taskade_service = get_dependencies()

        project_id = PROJECTS.get(project)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project}'}), 404

        taskade = get_taskade_service()
        result = taskade.complete_task(project_id, task_id)

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({'ok': True, 'message': 'Task completed'})
    except Exception as e:
        logger.error(f"Error completing task: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/today", methods=["GET"])
def get_today_tasks():
    """Get all tasks from TODAY project."""
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        _, _, PROJECTS, get_taskade_service = get_dependencies()
        taskade = get_taskade_service()
        result = taskade.get_all_tasks(PROJECTS['today'])

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({
            'ok': True,
            'project': 'today',
            'tasks': result.get('items', [])
        })
    except Exception as e:
        logger.error(f"Error getting today tasks: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/sync-unmatched", methods=["POST"])
@csrf_exempt_api
def sync_unmatched_to_taskade():
    """
    Sync unmatched transactions to Taskade Finance project.

    Creates tasks for transactions that don't have receipts attached.
    """
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        from viewer_server import get_db_connection, return_db_connection, db_execute

        _, _, PROJECTS, get_taskade_service = get_dependencies()
        taskade = get_taskade_service()
        finance_project = PROJECTS['finance']

        # Get unmatched transactions
        conn, db_type = get_db_connection()
        cursor = db_execute(conn, db_type, '''
            SELECT _index, chase_date, description, amount, business_type
            FROM transactions
            WHERE (receipt_url IS NULL OR receipt_url = '')
            AND amount < 0
            ORDER BY chase_date DESC
            LIMIT 50
        ''')
        unmatched = cursor.fetchall()
        return_db_connection(conn)

        if not unmatched:
            return jsonify({
                'ok': True,
                'message': 'No unmatched transactions to sync',
                'synced': 0
            })

        # Create tasks for unmatched transactions
        tasks_created = 0
        for tx in unmatched:
            content = f"Find receipt: {tx['description']} ${abs(tx['amount']):.2f} ({tx['chase_date']})"
            metadata = {
                'note': f"Transaction ID: {tx['_index']}\nBusiness: {tx.get('business_type', 'Unknown')}"
            }

            result = taskade.create_task(finance_project, content, metadata=metadata)
            if not result.get('error'):
                tasks_created += 1

        return jsonify({
            'ok': True,
            'message': f'Synced {tasks_created} unmatched transactions to Taskade',
            'synced': tasks_created,
            'total_unmatched': len(unmatched)
        })
    except Exception as e:
        logger.error(f"Error syncing unmatched: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500


@taskade_bp.route("/bulk-create", methods=["POST"])
@csrf_exempt_api
def bulk_create_tasks():
    """
    Create multiple tasks at once.

    Body:
    {
        "project": "inbox",
        "tasks": [
            {"content": "Task 1"},
            {"content": "Task 2"}
        ]
    }
    """
    if not check_auth():
        return jsonify({'ok': False, 'error': 'Authentication required'}), 401

    try:
        data = request.get_json()
        if not data or not data.get('tasks'):
            return jsonify({'ok': False, 'error': 'tasks array is required'}), 400

        _, _, PROJECTS, get_taskade_service = get_dependencies()

        project_key = data.get('project', 'inbox')
        project_id = PROJECTS.get(project_key)
        if not project_id:
            return jsonify({'ok': False, 'error': f'Unknown project: {project_key}'}), 404

        taskade = get_taskade_service()
        result = taskade.create_tasks_bulk(project_id, data['tasks'])

        if result.get('error'):
            return jsonify({'ok': False, 'error': result['error']}), 500

        return jsonify({
            'ok': True,
            'message': f"Created {len(data['tasks'])} tasks",
            'project': project_key,
            'result': result
        })
    except Exception as e:
        logger.error(f"Error bulk creating tasks: {e}")
        return jsonify({'ok': False, 'error': str(e)}), 500

"""
Motion-Style Auto-Scheduling Service

Intelligently schedules tasks based on:
- Calendar availability across 3 accounts
- Energy levels (morning = deep work, afternoon = meetings)
- Task priority and deadlines
- Meeting buffers and protected time
- Historical completion patterns

Integrated with:
- Google Calendar (3 accounts)
- Taskade (task source)
- AI (duration estimation)
"""

import os
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import anthropic

# Energy profiles by time of day
ENERGY_PROFILES = {
    'morning': {  # 6 AM - 12 PM
        'start': 6,
        'end': 12,
        'energy': 'high',
        'best_for': ['deep-work', 'creative', 'strategic'],
        'score_multiplier': 1.5
    },
    'afternoon': {  # 12 PM - 5 PM
        'start': 12,
        'end': 17,
        'energy': 'medium',
        'best_for': ['meetings', 'collaboration', 'calls'],
        'score_multiplier': 1.0
    },
    'evening': {  # 5 PM - 8 PM
        'start': 17,
        'end': 20,
        'energy': 'low',
        'best_for': ['admin', 'email', 'simple-tasks'],
        'score_multiplier': 0.7
    }
}

# Protected time blocks (never schedule here)
PROTECTED_TIME = {
    'sleep': {'start': 22, 'end': 6},  # 10 PM - 6 AM
    'lunch': {'start': 12, 'end': 13},  # 12 PM - 1 PM
    'family_evening': {'start': 18, 'end': 20},  # 6 PM - 8 PM (weekdays)
    'weekend_family': {'day': [5, 6], 'start': 0, 'end': 24}  # All day Sat/Sun
}

# Meeting buffer (minutes before/after meetings)
MEETING_BUFFER = 15


class MotionScheduler:
    """Motion-style intelligent task scheduling"""

    def __init__(self, calendar_service, taskade_service, anthropic_client=None):
        self.calendar = calendar_service
        self.taskade = taskade_service
        self.ai = anthropic_client
        self.task_history = {}  # Track actual completion times

    # ==================== CALENDAR ANALYSIS ====================

    def get_availability(self, start_date, end_date):
        """
        Find all available time slots across 3 calendars

        Returns list of time slots with:
        - start/end times
        - duration
        - energy level
        - score (quality of slot)
        """
        # Get events from all 3 calendars
        events = self.calendar.get_events_range(start_date, end_date)

        # Build day-by-day availability
        availability = []
        current_date = start_date

        while current_date <= end_date:
            day_slots = self._analyze_day(current_date, events)
            availability.extend(day_slots)
            current_date += timedelta(days=1)

        return availability

    def _analyze_day(self, date, all_events):
        """Analyze a single day and find available slots"""
        # Get events for this day
        day_events = [e for e in all_events
                      if self._is_same_day(e['start'], date)]

        # Sort events by start time
        day_events.sort(key=lambda e: e['start'])

        # Find gaps between events
        slots = []
        day_start = datetime.combine(date, datetime.min.time()) + timedelta(hours=6)  # 6 AM
        day_end = datetime.combine(date, datetime.min.time()) + timedelta(hours=22)  # 10 PM

        current_time = day_start

        for event in day_events:
            event_start = self._parse_datetime(event['start'])
            event_end = self._parse_datetime(event['end'])

            # Gap before event
            if current_time < event_start:
                gap_duration = (event_start - current_time).total_seconds() / 60

                # Only consider gaps of 30+ minutes
                if gap_duration >= 30:
                    # Apply meeting buffer
                    gap_start = current_time
                    gap_end = event_start - timedelta(minutes=MEETING_BUFFER)

                    if (gap_end - gap_start).total_seconds() / 60 >= 30:
                        slots.append(self._create_slot(gap_start, gap_end))

            current_time = max(current_time, event_end + timedelta(minutes=MEETING_BUFFER))

        # Gap after last event
        if current_time < day_end:
            gap_duration = (day_end - current_time).total_seconds() / 60
            if gap_duration >= 30:
                slots.append(self._create_slot(current_time, day_end))

        # Filter out protected time
        slots = [s for s in slots if not self._is_protected_time(s)]

        return slots

    def _create_slot(self, start, end):
        """Create slot object with metadata"""
        duration = (end - start).total_seconds() / 60
        hour = start.hour

        # Determine energy period
        energy_period = self._get_energy_period(hour)
        energy_info = ENERGY_PROFILES.get(energy_period, ENERGY_PROFILES['afternoon'])

        # Calculate slot score
        score = self._calculate_slot_score(start, duration, energy_info)

        return {
            'start': start,
            'end': end,
            'duration': duration,
            'energy_period': energy_period,
            'energy_level': energy_info['energy'],
            'best_for': energy_info['best_for'],
            'score': score,
            'day_of_week': start.weekday()
        }

    def _calculate_slot_score(self, start_time, duration, energy_info):
        """Calculate quality score for a time slot"""
        score = 100

        # Energy multiplier
        score *= energy_info['score_multiplier']

        # Duration bonus (longer slots are better for deep work)
        if duration >= 120:  # 2+ hours
            score *= 1.3
        elif duration >= 90:  # 1.5+ hours
            score *= 1.2
        elif duration >= 60:  # 1+ hour
            score *= 1.1

        # Day of week (Mon-Wed better than Thu-Fri)
        day = start_time.weekday()
        if day in [0, 1, 2]:  # Mon-Wed
            score *= 1.1
        elif day in [3, 4]:  # Thu-Fri
            score *= 1.0

        # Time of day (avoid late afternoon/evening)
        hour = start_time.hour
        if hour >= 16:  # After 4 PM
            score *= 0.8

        return round(score, 1)

    def _get_energy_period(self, hour):
        """Get energy period for hour of day"""
        for period, info in ENERGY_PROFILES.items():
            if info['start'] <= hour < info['end']:
                return period
        return 'evening'

    def _is_protected_time(self, slot):
        """Check if slot falls in protected time"""
        start = slot['start']
        hour = start.hour
        day = start.weekday()

        # Check sleep time
        if hour >= PROTECTED_TIME['sleep']['start'] or hour < PROTECTED_TIME['sleep']['end']:
            return True

        # Check lunch
        if PROTECTED_TIME['lunch']['start'] <= hour < PROTECTED_TIME['lunch']['end']:
            return True

        # Check family evening (weekdays only)
        if day < 5:  # Mon-Fri
            if PROTECTED_TIME['family_evening']['start'] <= hour < PROTECTED_TIME['family_evening']['end']:
                return True

        # Check weekend
        if day in PROTECTED_TIME['weekend_family']['day']:
            return True

        return False

    # ==================== TASK DURATION ESTIMATION ====================

    def estimate_task_duration(self, task):
        """
        Estimate how long a task will take

        Uses:
        - Historical data (if task done before)
        - AI analysis (if new task)
        - Default heuristics
        """
        # Check historical data
        task_content = task.get('content', '')
        if task_content in self.task_history:
            return self.task_history[task_content]['avg_duration']

        # Use AI to estimate
        if self.ai:
            try:
                prompt = f"""Estimate how long this task will take in minutes.

Task: {task_content}

Consider:
- Task complexity
- Type of work (meeting, deep work, admin)
- Typical completion times

Return ONLY a number (minutes). Examples: 30, 60, 120"""

                response = self.ai.messages.create(
                    model='claude-sonnet-4-20250514',
                    max_tokens=10,
                    messages=[{'role': 'user', 'content': prompt}]
                )

                duration = int(response.content[0].text.strip())
                return duration

            except:
                pass

        # Default heuristics
        content_lower = task_content.lower()

        if any(word in content_lower for word in ['review', 'check', 'quick']):
            return 30
        elif any(word in content_lower for word in ['meeting', 'call']):
            return 60
        elif any(word in content_lower for word in ['create', 'write', 'prepare']):
            return 90
        elif any(word in content_lower for word in ['deep', 'strategic', 'planning']):
            return 120
        else:
            return 60  # Default 1 hour

    def learn_task_duration(self, task_content, actual_duration):
        """Update historical data with actual duration"""
        if task_content not in self.task_history:
            self.task_history[task_content] = {
                'total_duration': 0,
                'count': 0,
                'avg_duration': 0
            }

        history = self.task_history[task_content]
        history['total_duration'] += actual_duration
        history['count'] += 1
        history['avg_duration'] = history['total_duration'] / history['count']

    # ==================== TASK CLASSIFICATION ====================

    def classify_task_type(self, task):
        """
        Classify task type for optimal scheduling

        Types:
        - deep-work: Requires focus, best in morning
        - meeting: Collaboration, best in afternoon
        - admin: Simple tasks, best in evening
        - creative: Content creation, best in morning
        - strategic: Planning, best in morning
        """
        content = task.get('content', '').lower()

        # Meeting/collaboration
        if any(word in content for word in ['meeting', 'call', '1:1', 'sync', 'chat']):
            return 'meeting'

        # Admin/simple
        if any(word in content for word in ['email', 'expense', 'approve', 'review', 'check']):
            return 'admin'

        # Creative
        if any(word in content for word in ['create', 'write', 'design', 'content', 'video']):
            return 'creative'

        # Strategic
        if any(word in content for word in ['plan', 'strategy', 'roadmap', 'goal', 'q4']):
            return 'strategic'

        # Deep work (default for complex tasks)
        return 'deep-work'

    # ==================== TASK SCHEDULING ====================

    def find_best_slots(self, task, num_suggestions=3):
        """
        Find best time slots for a task

        Returns top N suggestions ranked by fit
        """
        # Get task metadata
        duration = self.estimate_task_duration(task)
        task_type = self.classify_task_type(task)
        priority = task.get('priority', 'normal')
        deadline = task.get('deadline')

        # Get availability (next 7 days)
        start_date = datetime.now()
        end_date = start_date + timedelta(days=7)
        available_slots = self.get_availability(start_date, end_date)

        # Filter slots by duration
        valid_slots = [s for s in available_slots if s['duration'] >= duration]

        # Score each slot for this task
        scored_slots = []
        for slot in valid_slots:
            score = self._score_slot_for_task(slot, task, task_type, duration, priority, deadline)
            scored_slots.append({
                **slot,
                'task_fit_score': score,
                'suggested_duration': duration
            })

        # Sort by score
        scored_slots.sort(key=lambda s: s['task_fit_score'], reverse=True)

        return scored_slots[:num_suggestions]

    def _score_slot_for_task(self, slot, task, task_type, duration, priority, deadline):
        """Score how well a slot fits a task"""
        score = slot['score']  # Base slot quality score

        # Task type fit
        if task_type in slot['best_for']:
            score *= 1.5

        # Duration fit
        if slot['duration'] >= duration + 30:  # Extra buffer
            score *= 1.2
        elif slot['duration'] >= duration + 15:
            score *= 1.1

        # Priority boost
        if priority == 'urgent':
            # Prefer sooner slots for urgent tasks
            hours_until = (slot['start'] - datetime.now()).total_seconds() / 3600
            if hours_until < 24:
                score *= 1.5
            elif hours_until < 48:
                score *= 1.3

        # Deadline proximity
        if deadline:
            deadline_dt = datetime.fromisoformat(deadline) if isinstance(deadline, str) else deadline
            hours_until_deadline = (deadline_dt - slot['start']).total_seconds() / 3600

            if hours_until_deadline < 0:
                score *= 0.1  # Slot is after deadline
            elif hours_until_deadline < 24:
                score *= 1.4  # Very close to deadline
            elif hours_until_deadline < 48:
                score *= 1.2  # Close to deadline

        return round(score, 1)

    def auto_schedule_task(self, task):
        """
        Automatically schedule task to best available slot

        Returns:
            - calendar_event: Created calendar event
            - slot: Chosen time slot
            - alternatives: Other suggestions
        """
        suggestions = self.find_best_slots(task, num_suggestions=3)

        if not suggestions:
            return {
                'success': False,
                'error': 'No available slots found'
            }

        best_slot = suggestions[0]
        alternatives = suggestions[1:]

        # Create calendar event
        event_data = {
            'summary': f"⭐ {task.get('content', 'Task')}",
            'start': best_slot['start'].isoformat(),
            'end': (best_slot['start'] + timedelta(minutes=best_slot['suggested_duration'])).isoformat(),
            'description': f"Auto-scheduled from Taskade\nTask type: {self.classify_task_type(task)}",
            'colorId': self._get_color_for_task_type(self.classify_task_type(task))
        }

        # Create event in primary calendar (Down Home)
        calendar_event = self.calendar.create_event('brian@downhome.com', event_data)

        return {
            'success': True,
            'calendar_event': calendar_event,
            'slot': best_slot,
            'alternatives': alternatives
        }

    def _get_color_for_task_type(self, task_type):
        """Get calendar color ID for task type"""
        colors = {
            'deep-work': '9',  # Blue
            'meeting': '2',  # Green
            'admin': '8',  # Gray
            'creative': '5',  # Yellow
            'strategic': '10'  # Purple
        }
        return colors.get(task_type, '1')

    # ==================== BATCH SCHEDULING ====================

    def auto_schedule_today(self):
        """Auto-schedule all tasks from Taskade TODAY project"""
        today_tasks = self.taskade.get_today_tasks()
        tasks_to_schedule = [t for t in today_tasks.get('items', [])
                             if not t.get('completed')]

        results = []
        for task in tasks_to_schedule:
            result = self.auto_schedule_task(task)
            results.append({
                'task': task,
                'result': result
            })

        return {
            'total': len(tasks_to_schedule),
            'scheduled': sum(1 for r in results if r['result']['success']),
            'results': results
        }

    def suggest_daily_schedule(self, date=None):
        """
        Generate suggested daily schedule

        Returns complete day plan with:
        - Existing meetings
        - Auto-scheduled tasks
        - Protected time blocks
        """
        if date is None:
            date = datetime.now()

        # Get existing calendar events
        events = self.calendar.get_todays_events() if date.date() == datetime.now().date() else []

        # Get tasks to schedule
        today_tasks = self.taskade.get_today_tasks()
        unscheduled = [t for t in today_tasks.get('items', [])
                       if not t.get('completed')]

        # Build daily schedule
        schedule = {
            'date': date.isoformat(),
            'existing_events': events,
            'tasks_to_schedule': len(unscheduled),
            'suggested_tasks': [],
            'protected_time': self._get_protected_blocks(date)
        }

        # Schedule each task
        for task in unscheduled:
            suggestions = self.find_best_slots(task, num_suggestions=1)
            if suggestions:
                schedule['suggested_tasks'].append({
                    'task': task,
                    'suggested_slot': suggestions[0]
                })

        return schedule

    def _get_protected_blocks(self, date):
        """Get protected time blocks for a day"""
        blocks = []

        # Add lunch
        lunch_start = datetime.combine(date, datetime.min.time()) + timedelta(hours=12)
        lunch_end = lunch_start + timedelta(hours=1)
        blocks.append({
            'name': 'Lunch',
            'start': lunch_start,
            'end': lunch_end
        })

        # Add family time (weekdays)
        if date.weekday() < 5:
            family_start = datetime.combine(date, datetime.min.time()) + timedelta(hours=18)
            family_end = datetime.combine(date, datetime.min.time()) + timedelta(hours=20)
            blocks.append({
                'name': 'Family Time',
                'start': family_start,
                'end': family_end
            })

        return blocks

    # ==================== UTILITIES ====================

    def _is_same_day(self, dt_str, target_date):
        """Check if datetime string is same day as target"""
        dt = self._parse_datetime(dt_str)
        return dt.date() == target_date.date()

    def _parse_datetime(self, dt_str):
        """Parse datetime string"""
        if isinstance(dt_str, datetime):
            return dt_str
        try:
            return datetime.fromisoformat(dt_str.replace('Z', '+00:00'))
        except:
            return datetime.now()


# Singleton
_motion_scheduler = None

def get_motion_scheduler(calendar_service, taskade_service, anthropic_client=None):
    """Get or create Motion scheduler"""
    global _motion_scheduler
    if _motion_scheduler is None:
        _motion_scheduler = MotionScheduler(calendar_service, taskade_service, anthropic_client)
    return _motion_scheduler

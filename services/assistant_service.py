"""
AI Assistant Service using Claude API
Handles chat conversations with context awareness
"""

import os
import json
from datetime import datetime
from anthropic import Anthropic


class AssistantService:
    def __init__(self, db_path='financial_data.db'):
        """Initialize the AI Assistant service"""
        self.api_key = os.getenv('ANTHROPIC_API_KEY')
        if not self.api_key:
            print("⚠️ ANTHROPIC_API_KEY not found - Assistant will use mock responses")
            self.client = None
        else:
            self.client = Anthropic(api_key=self.api_key)
            print("✅ Claude API initialized successfully")

        self.db_path = db_path
        self.model = "claude-3-5-sonnet-20241022"
        self.max_tokens = 1024

    def get_system_prompt(self, user_context=None):
        """Build the system prompt with user context"""
        base_prompt = """You are Brian's personal AI assistant for his Life OS system. You help him manage:

- Financial transactions and expenses
- Receipt matching and organization
- Task management (via Taskade)
- Calendar and scheduling
- Email inbox management
- Daily routines and habits

You have access to Brian's real financial data, tasks, and schedule. You provide:
- Clear, concise answers
- Actionable insights
- Proactive suggestions
- Context-aware responses

Be friendly, professional, and helpful. Use first person when referring to Brian ("your transactions", "your tasks").
"""

        if user_context:
            base_prompt += f"\n\nCurrent Context:\n{json.dumps(user_context, indent=2)}"

        return base_prompt

    def get_user_context(self):
        """Fetch current user context from database and services"""
        import sqlite3

        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Get transaction stats
            cursor.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN match_status = 'MATCHED' THEN 1 ELSE 0 END) as matched,
                    SUM(CASE WHEN match_status = 'UNMATCHED' THEN 1 ELSE 0 END) as unmatched,
                    SUM(ABS(amount)) as total_amount
                FROM transactions
                WHERE amount < 0
            """)
            txn_stats = cursor.fetchone()

            # Get recent transactions (last 5)
            cursor.execute("""
                SELECT date, description, amount, business_type, match_status
                FROM transactions
                ORDER BY date DESC
                LIMIT 5
            """)
            recent_txns = cursor.fetchall()

            # Get receipt stats
            cursor.execute("""
                SELECT
                    COUNT(*) as total_receipts,
                    SUM(CASE WHEN is_matched = 1 THEN 1 ELSE 0 END) as matched_receipts
                FROM receipts
            """)
            receipt_stats = cursor.fetchone()

            conn.close()

            context = {
                "date": datetime.now().strftime("%Y-%m-%d"),
                "time": datetime.now().strftime("%I:%M %p"),
                "transactions": {
                    "total": txn_stats[0],
                    "matched": txn_stats[1],
                    "unmatched": txn_stats[2],
                    "total_spent": f"${txn_stats[3]:.2f}" if txn_stats[3] else "$0.00"
                },
                "receipts": {
                    "total": receipt_stats[0],
                    "matched": receipt_stats[1],
                    "unmatched": receipt_stats[0] - receipt_stats[1]
                },
                "recent_transactions": [
                    {
                        "date": r[0],
                        "merchant": r[1],
                        "amount": f"${abs(r[2]):.2f}",
                        "business": r[3],
                        "status": r[4]
                    }
                    for r in recent_txns
                ]
            }

            return context

        except Exception as e:
            print(f"Error fetching context: {e}")
            return {"error": "Could not fetch context"}

    def chat(self, message, conversation_history=None):
        """
        Send a message to Claude and get a response

        Args:
            message (str): User's message
            conversation_history (list): Previous messages [{"role": "user"|"assistant", "content": "..."}]

        Returns:
            dict: Response with content and metadata
        """
        if not self.client:
            return {
                "success": False,
                "error": "Claude API not configured",
                "response": "I'm currently in demo mode. Please configure ANTHROPIC_API_KEY to enable real AI conversations."
            }

        try:
            # Get current context
            context = self.get_user_context()

            # Build messages array
            messages = conversation_history or []
            messages.append({
                "role": "user",
                "content": message
            })

            # Call Claude API
            response = self.client.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                system=self.get_system_prompt(context),
                messages=messages
            )

            # Extract response
            assistant_message = response.content[0].text

            return {
                "success": True,
                "response": assistant_message,
                "model": self.model,
                "tokens_used": {
                    "input": response.usage.input_tokens,
                    "output": response.usage.output_tokens
                }
            }

        except Exception as e:
            print(f"Error in chat: {e}")
            return {
                "success": False,
                "error": str(e),
                "response": "Sorry, I encountered an error processing your request."
            }

    def get_conversation_summary(self, conversation_history):
        """Generate a summary of the conversation"""
        if not self.client or not conversation_history:
            return None

        try:
            summary_prompt = "Please provide a brief 1-2 sentence summary of this conversation."

            messages = conversation_history + [{
                "role": "user",
                "content": summary_prompt
            }]

            response = self.client.messages.create(
                model=self.model,
                max_tokens=150,
                messages=messages
            )

            return response.content[0].text

        except Exception as e:
            print(f"Error generating summary: {e}")
            return None


# Example usage
if __name__ == "__main__":
    assistant = AssistantService()

    # Test chat
    result = assistant.chat("How much have I spent this month?")
    print(f"Response: {result.get('response')}")
    print(f"Success: {result.get('success')}")

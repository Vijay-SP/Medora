"""
Medpark Meeting Intelligence System - Executive & Clinical Analytics Service
Deterministic dashboard intelligence, task aggregation, and LLM-powered multi-meeting insights.
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Optional
import re
from app.core.config import settings
from app.core.logging import logger
from app.core.exceptions import LLMUnavailable
from app.storage.repository import repository
from app.services.extraction.llm_client import llm_client
from app.models.meeting import Meeting
from app.models.extraction import MinutesOfMeeting


class AssistantAnalyticsService:
    """Aggregates meeting intelligence across repository records and answers executive questions."""

    def compile_dashboard_metrics(self, current_meeting_id: Optional[str] = None) -> dict[str, Any]:
        """Gathers deterministic metrics and structured logs across all meetings."""
        now = datetime.now(timezone.utc)
        seven_days_ago = now - timedelta(days=7)
        thirty_days_ago = now - timedelta(days=30)

        meetings: list[Meeting] = repository.list_meetings()
        # Sort by scheduled_at or created_at descending
        meetings_sorted = sorted(
            meetings,
            key=lambda m: m.scheduled_at or m.created_at,
            reverse=True,
        )

        total_meetings = len(meetings_sorted)
        meetings_last_7d = [
            m for m in meetings_sorted
            if (m.scheduled_at or m.created_at) >= seven_days_ago
        ]
        meetings_last_30d = [
            m for m in meetings_sorted
            if (m.scheduled_at or m.created_at) >= thirty_days_ago
        ]

        decisions_all: list[dict[str, Any]] = []
        actions_all: list[dict[str, Any]] = []
        risks_all: list[dict[str, Any]] = []
        meeting_catalog: list[dict[str, Any]] = []

        owner_tasks: dict[str, list[dict[str, Any]]] = {}
        category_counts: dict[str, int] = {"clinical": 0, "budget": 0, "operations": 0, "protocol": 0}

        for m in meetings_sorted:
            minutes: Optional[MinutesOfMeeting] = repository.get_minutes(m.id)
            m_date = m.scheduled_at or m.created_at
            date_str = m_date.strftime("%Y-%m-%d")

            m_info = {
                "id": m.id,
                "title": m.title,
                "date": date_str,
                "type": m.meeting_type.value,
                "status": m.review_status.value,
                "attendees": [a.name for a in m.attendees],
                "summary": minutes.summary_en or minutes.summary_ro if minutes else None,
                "decisions_count": len(minutes.decisions) if minutes else 0,
                "actions_count": len(minutes.action_items) if minutes else 0,
            }
            meeting_catalog.append(m_info)

            if not minutes:
                continue

            # Decisions
            for d in minutes.decisions:
                cat = d.category.lower() if d.category else "clinical"
                category_counts[cat] = category_counts.get(cat, 0) + 1
                decisions_all.append({
                    "id": d.id,
                    "meeting_id": m.id,
                    "meeting_title": m.title,
                    "meeting_date": date_str,
                    "topic": d.topic,
                    "decision": d.decision_en or d.decision,
                    "category": cat,
                    "is_reviewed": d.is_reviewed,
                })

            # Action Items
            for a in minutes.action_items:
                owner = (a.owner or "Unassigned").strip()
                item_info = {
                    "id": a.id,
                    "meeting_id": m.id,
                    "meeting_title": m.title,
                    "meeting_date": date_str,
                    "task": a.task_en or a.task,
                    "owner": owner,
                    "priority": a.priority,
                    "status": a.status,
                    "deadline": a.deadline_phrase_en or a.deadline_phrase or a.deadline_date or "No deadline",
                }
                actions_all.append(item_info)
                if owner not in owner_tasks:
                    owner_tasks[owner] = []
                owner_tasks[owner].append(item_info)

            # Risks
            for r in minutes.risks_and_questions:
                risks_all.append({
                    "id": r.id,
                    "meeting_id": m.id,
                    "meeting_title": m.title,
                    "description": r.description_en or r.description,
                    "severity": r.severity,
                    "type": r.item_type,
                })

        # Identify lagging / open tasks
        lagging_tasks = [
            a for a in actions_all
            if a["status"] in ("open", "in_progress")
        ]
        # Decisions in last 7 days
        recent_meeting_ids = {m.id for m in meetings_last_7d}
        decisions_last_7d = [d for d in decisions_all if d["meeting_id"] in recent_meeting_ids]

        return {
            "total_meetings": total_meetings,
            "meetings_last_7d_count": len(meetings_last_7d),
            "meetings_last_30d_count": len(meetings_last_30d),
            "total_decisions": len(decisions_all),
            "decisions_last_7d_count": len(decisions_last_7d),
            "category_counts": category_counts,
            "total_actions": len(actions_all),
            "lagging_actions_count": len(lagging_tasks),
            "owner_task_summary": {
                owner: {
                    "total": len(tasks),
                    "open": sum(1 for t in tasks if t["status"] in ("open", "in_progress")),
                    "completed": sum(1 for t in tasks if t["status"] == "completed"),
                }
                for owner, tasks in owner_tasks.items()
            },
            "meetings_catalog": meeting_catalog[:10],
            "decisions_recent": decisions_all[:15],
            "lagging_tasks": lagging_tasks[:15],
            "high_severity_risks": [r for r in risks_all if r["severity"] == "high"][:5],
        }

    def _build_context_prompt(self, metrics: dict[str, Any], query: str) -> str:
        """Formats factual metrics and meeting evidence into a high-density LLM context."""
        owner_summary_str = "\n".join(
            f"  - {owner}: {data['total']} total tasks ({data['open']} open/pending, {data['completed']} completed)"
            for owner, data in metrics["owner_task_summary"].items()
        ) or "  - None recorded"

        lagging_tasks_str = "\n".join(
            f"  - [{t['priority'].upper()}] Task: {t['task']} | Owner: {t['owner']} | Deadline: {t['deadline']} (Meeting: '{t['meeting_title']}' on {t['meeting_date']})"
            for t in metrics["lagging_tasks"]
        ) or "  - None currently pending"

        recent_decisions_str = "\n".join(
            f"  - [{d['category'].upper()}] {d['topic']}: {d['decision']} (Meeting: '{d['meeting_title']}' on {d['meeting_date']})"
            for d in metrics["decisions_recent"][:8]
        ) or "  - None"

        meetings_str = "\n".join(
            f"  - [{m['date']}] '{m['title']}' (ID: {m['id']}): {m['decisions_count']} decisions, {m['actions_count']} tasks. Summary: {m['summary'] or 'N/A'}"
            for m in metrics["meetings_catalog"][:6]
        ) or "  - None"

        context = f"""=== VERIFIED HOSPITAL DASHBOARD DATA ===
METRICS OVERVIEW:
- Total Meetings Recorded: {metrics['total_meetings']} ({metrics['meetings_last_7d_count']} in the last 7 days)
- Total Decisions Adopted: {metrics['total_decisions']} ({metrics['decisions_last_7d_count']} in the last 7 days)
- Decision Categories: Clinical={metrics['category_counts'].get('clinical', 0)}, Budget={metrics['category_counts'].get('budget', 0)}, Operations={metrics['category_counts'].get('operations', 0)}, Protocol={metrics['category_counts'].get('protocol', 0)}
- Action Items: {metrics['total_actions']} total ({metrics['lagging_actions_count']} open/lagging/in-progress)

TASK DISTRIBUTION BY OWNER / PARTICIPANT:
{owner_summary_str}

PENDING & LAGGING ACTION ITEMS:
{lagging_tasks_str}

RECENT DECISIONS:
{recent_decisions_str}

RECENT SESSIONS CATALOG:
{meetings_str}
"""
        return context

    def generate_deterministic_fallback(self, query: str, metrics: dict[str, Any]) -> str:
        """Fallback response when local LLM is temporarily unreachable."""
        q_lower = query.lower()
        if "lag" in q_lower or "pending" in q_lower or "overdue" in q_lower:
            lines = [f"### ⚡ Pending & Lagging Action Items ({metrics['lagging_actions_count']} items)\n"]
            for t in metrics["lagging_tasks"][:8]:
                lines.append(f"* **[{t['priority'].upper()}]** {t['task']}\n  * **Owner:** `{t['owner']}` | **Deadline:** {t['deadline']} (Meeting: *{t['meeting_title']}*)")
            return "\n".join(lines)

        if "decision" in q_lower or "last week" in q_lower:
            return (
                f"### 📊 Decision & Meeting Metrics\n\n"
                f"* **Meetings in last 7 days:** {metrics['meetings_last_7d_count']}\n"
                f"* **Total decisions adopted:** {metrics['total_decisions']} ({metrics['decisions_last_7d_count']} in last 7 days)\n"
                f"* **Open/Lagging Tasks:** {metrics['lagging_actions_count']}\n"
                f"* **Decisions by Category:** Clinical: {metrics['category_counts'].get('clinical', 0)}, "
                f"Budget: {metrics['category_counts'].get('budget', 0)}, Protocol: {metrics['category_counts'].get('protocol', 0)}"
            )

        if "who" in q_lower or "employee" in q_lower or "person" in q_lower or "doctor" in q_lower:
            lines = ["### 👨‍⚕️ Task & Action Distribution by Participant\n"]
            for owner, data in metrics["owner_task_summary"].items():
                lines.append(f"* **{owner}:** {data['total']} total actions ({data['open']} pending / open, {data['completed']} completed)")
            return "\n".join(lines)

        return (
            f"### 🏥 Hospital Executive Overview\n\n"
            f"* **Total Sessions:** {metrics['total_meetings']} ({metrics['meetings_last_7d_count']} in the past 7 days)\n"
            f"* **Decisions Adopted:** {metrics['total_decisions']} formal consensus items\n"
            f"* **Action Items:** {metrics['total_actions']} ({metrics['lagging_actions_count']} currently pending)\n\n"
            f"You can ask me specific questions like: *'Where are we lagging?'*, *'How many decisions last week?'*, or *'Who has the most active tasks?'*"
        )

    async def answer_query(
        self,
        query: str,
        history: list[dict[str, str]],
        current_meeting_id: Optional[str] = None,
    ) -> dict[str, Any]:
        """Synthesizes executive answers grounded in actual meeting data."""
        metrics = self.compile_dashboard_metrics(current_meeting_id)
        context = self._build_context_prompt(metrics, query)

        system_prompt = (
            "You are the Executive & Clinical Intelligence Assistant for Spitalul Internațional Medpark.\n"
            "You have complete visibility across all hospital meetings, decisions, action plans, owners, and clinical discussions.\n"
            "INSTRUCTIONS:\n"
            "1. Answer questions objectively and concisely based EXCLUSIVELY on the provided VERIFIED HOSPITAL DASHBOARD DATA.\n"
            "2. When discussing lagging or bottleneck tasks, name the specific task, owner, and deadline.\n"
            "3. When asked for counts or metrics (meetings, decisions last week, tasks), state the exact numbers from the data.\n"
            "4. Mention meeting titles when referencing decisions or actions so users know the context.\n"
            "5. Answer in the same language as the user's prompt (English, Romanian, or Russian). Use clean Markdown styling with bullet points and bold highlights."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"{context}\n\nUSER QUESTION: {query}"},
        ]

        # Append last 2 conversational turns if available
        if history:
            recent_hist = history[-2:]
            messages = [
                {"role": "system", "content": system_prompt},
                *recent_hist,
                {"role": "user", "content": f"{context}\n\nUSER QUESTION: {query}"},
            ]

        answer = ""
        try:
            answer = await llm_client.complete_chat(messages, max_tokens=1200, temperature=0.2)
        except (LLMUnavailable, Exception) as err:
            logger.warning(f"Assistant LLM call failed ({err}); using deterministic analytics engine fallback.")
            answer = self.generate_deterministic_fallback(query, metrics)

        # Detect referenced meetings in catalog
        referenced_meetings = []
        for m in metrics["meetings_catalog"]:
            if m["title"].lower() in answer.lower() or m["id"] in answer or (current_meeting_id and m["id"] == current_meeting_id):
                referenced_meetings.append({
                    "id": m["id"],
                    "title": m["title"],
                    "date": m["date"],
                })

        return {
            "answer": answer,
            "referenced_meetings": referenced_meetings[:4],
            "metrics": {
                "total_meetings": metrics["total_meetings"],
                "total_decisions": metrics["total_decisions"],
                "lagging_actions_count": metrics["lagging_actions_count"],
            },
        }


assistant_analytics_service = AssistantAnalyticsService()

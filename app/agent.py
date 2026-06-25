import os
import re
import sys
import json
import datetime
from typing import Dict, Any, List, Optional, Generator
from pydantic import BaseModel, Field

from google.adk.agents import LlmAgent
from google.adk.apps import App, ResumabilityConfig
from google.adk.tools import AgentTool
from google.adk.tools.mcp_tool import McpToolset
from google.adk.tools.mcp_tool.mcp_session_manager import StdioConnectionParams
from mcp import StdioServerParameters

from google.adk.workflow import Workflow, START, node, FunctionNode
from google.adk.events.event import Event
from google.adk.events.request_input import RequestInput
from google.adk.agents.context import Context
from google.genai import types

from app.config import config

# -----------------------------------------------------------------------------
# MCP Server Toolset Configuration
# -----------------------------------------------------------------------------
# Connect to the local MCP server running using sys.executable
mcp_toolset = McpToolset(
    connection_params=StdioConnectionParams(
        server_params=StdioServerParameters(
            command=sys.executable,
            args=["-m", "app.mcp_server"],
        )
    )
)

# -----------------------------------------------------------------------------
# Sub-Agents
# -----------------------------------------------------------------------------
diet_scheduler = LlmAgent(
    name="diet_scheduler",
    model=config.model,
    instruction="""You are a specialized pet nutrition and diet scheduler.
Your job is to manage feeding schedules, portions, and food types.
Always look up the pet's profile using the get_pet_profile tool first to check their weight and type.
Use the schedule_feeding tool to schedule new feedings.
Be detailed and suggest custom portions based on their type and weight.
""",
    tools=[mcp_toolset],
    description="Manages pet feeding schedules, diet plans, portion sizes, and food types."
)

health_tracker = LlmAgent(
    name="health_tracker",
    model=config.model,
    instruction="""You are a specialized pet health tracker.
Your job is to check vaccine compliance, log vet visits, and review clinical history.
Always look up the pet's profile using the get_pet_profile tool first.
Use check_vaccine_compliance to check if they need any boosters.
Use log_vet_visit to record vet visit notes or update vaccine dates.
Provide professional guidance on vaccine status.
""",
    tools=[mcp_toolset],
    description="Tracks pet medical history, logs vet visits, and checks vaccination compliance."
)

# -----------------------------------------------------------------------------
# Orchestrator Agent
# -----------------------------------------------------------------------------
orchestrator = LlmAgent(
    name="orchestrator",
    model=config.model,
    instruction="""You are the PetCare Orchestrator. You help pet owners manage their pets' diet, schedules, and medical histories.
You have two specialized sub-agents:
1. diet_scheduler: for feeding schedules, portions, food types.
2. health_tracker: for vet visits, medical history, vaccines.

You must handle requests using the following rules:

1. FOR READ-ONLY QUERIES (e.g., checking vaccine compliance, checking pet profiles, checking status):
   Immediately delegate to the appropriate sub-agent (diet_scheduler or health_tracker) using their tools and report the response.

2. FOR DATABASE MODIFICATION REQUESTS (e.g., scheduling a feeding or logging a vet visit):
   - On the FIRST turn (when the user asks to schedule or log something), do NOT call any tool and do NOT delegate to any sub-agent. Instead, output a confirmation message and the exact JSON confirmation block at the end of your response:
   ```json
   {
     "needs_confirmation": true,
     "confirmation_message": "Do you want to confirm scheduling [food_type] for [pet_name] at [time]?",
     "action": "schedule_feeding",
     "data": {
       "pet_name": "[pet_name]",
       "food_type": "[food_type]",
       "time": "[time]",
       "quantity_grams": [quantity]
     }
   }
   ```
   Or for vet logs:
   ```json
   {
     "needs_confirmation": true,
     "confirmation_message": "Do you want to confirm logging the vet visit for [pet_name] on [date]?",
     "action": "log_vet_visit",
     "data": {
       "pet_name": "[pet_name]",
       "description": "[description]",
       "date": "[date]"
     }
   }
   ```

3. IF YOU RECEIVE AN INPUT CONTAINING "User approved the action" OR status is "approved":
   Delegate to the appropriate sub-agent to execute the actual tool call (schedule_feeding or log_vet_visit) using the provided action data, then report the success result.

4. IF YOU RECEIVE AN INPUT CONTAINING "User rejected the action" OR status is "denied":
   Inform the user that the action has been cancelled.
""",
    tools=[AgentTool(diet_scheduler), AgentTool(health_tracker)],
)

# -----------------------------------------------------------------------------
# Workflow Nodes & Functions
# -----------------------------------------------------------------------------

def security_checkpoint(ctx: Context, node_input: Any) -> Event:
    """Performs PII scrubbing, injection detection, and custom security rules."""
    # Extract query text
    query = ""
    if hasattr(node_input, "parts") and node_input.parts:
        query = node_input.parts[0].text
    elif isinstance(node_input, str):
        query = node_input
    elif isinstance(node_input, dict) and "text" in node_input:
        query = node_input["text"]
    else:
        query = str(node_input)

    audit_logs = ctx.state.get("audit_logs", [])

    # 1. PII Redaction (Phone numbers and Email addresses)
    redacted = query
    redacted = re.sub(r"\b\d{3}[-.]?\d{3}[-.]?\d{4}\b", "[PHONE_REDACTED]", redacted)
    redacted = re.sub(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b", "[EMAIL_REDACTED]", redacted)

    # 2. Prompt Injection Detection
    injection_keywords = [
        "ignore instructions", "bypass security", "system prompt", 
        "ignore previous", "jailbreak", "do not follow", "reveal instructions"
    ]
    has_injection = any(kw in query.lower() for kw in injection_keywords)

    # 3. Domain Specific Rules (e.g. check for dosage limit warning)
    dosage_match = re.search(r"(\d+)\s*mg", query, re.IGNORECASE)
    dosage_warning = False
    if dosage_match:
        dose = int(dosage_match.group(1))
        if dose > 1000:
            dosage_warning = True

    severity = "INFO"
    if has_injection:
        severity = "CRITICAL"
    elif dosage_warning:
        severity = "WARNING"

    audit_entry = {
        "severity": severity,
        "timestamp": datetime.datetime.now().isoformat(),
        "event_type": "security_checkpoint_evaluation",
        "has_injection": has_injection,
        "dosage_warning": dosage_warning,
        "pii_detected": (redacted != query),
        "reason": "Security evaluation completed."
    }
    print(json.dumps(audit_entry))
    audit_logs.append(audit_entry)

    # Routing logic
    if has_injection:
        return Event(
            output="Security Violation: Possible prompt injection detected.",
            route="SECURITY_EVENT",
            state={"audit_logs": audit_logs, "security_passed": False, "security_reason": "Prompt injection detected"}
        )
    elif dosage_warning:
        return Event(
            output="Security Warning: Requested medication dosage exceeds safe limits (1000mg). Please consult a veterinarian.",
            route="SECURITY_EVENT",
            state={"audit_logs": audit_logs, "security_passed": False, "security_reason": "Overdose risk detected"}
        )
    else:
        return Event(
            output=redacted,
            route="__DEFAULT__",
            state={"audit_logs": audit_logs, "security_passed": True, "pii_redacted_query": redacted}
        )


def routing_node(ctx: Context, node_input: Any) -> Event:
    """Parses orchestrator response to see if confirmation is needed."""
    text = ""
    if hasattr(node_input, "parts") and node_input.parts:
        text = node_input.parts[0].text
    else:
        text = str(node_input)

    # Extract JSON block
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            needs_confirm = data.get("needs_confirmation", False)
            if needs_confirm:
                confirm_msg = data.get("confirmation_message", "Please confirm this action.")
                action_data = data.get("data", {})
                action_type = data.get("action", "")
                
                # Clean JSON block from text output
                clean_text = text.replace(json_match.group(0), "").strip()
                
                return Event(
                    output=clean_text,
                    route="NEEDS_CONFIRMATION",
                    state={
                        "confirmation_message": confirm_msg,
                        "confirmed_data": action_data,
                        "action_type": action_type,
                        "pre_confirm_response": clean_text
                    }
                )
        except Exception:
            pass

    return Event(
        output=text,
        route="__DEFAULT__"
    )


async def human_confirmation(ctx: Context, node_input: Any) -> Generator[Any, None, None]:
    """Yields RequestInput to pause the workflow for human confirmation."""
    if not ctx.resume_inputs:
        msg = ctx.state.get("confirmation_message", "Please confirm this action.")
        yield RequestInput(interrupt_id="confirm_action", message=msg)
        return

    user_decision = ctx.resume_inputs.get("confirm_action", "").strip().lower()
    confirmed = user_decision in ["yes", "y", "approve", "confirm"]

    action_data = ctx.state.get("confirmed_data", {})
    action_type = ctx.state.get("action_type", "")

    if confirmed:
        yield Event(
            output=f"User approved the action: {action_type}. Please perform the scheduled database update now using your tools. Action data: {json.dumps(action_data)}",
            state={"confirmation_needed": False, "confirmed_data": None}
        )
    else:
        yield Event(
            output=f"User rejected the action: {action_type}. Tell the user the action has been cancelled.",
            state={"confirmation_needed": False, "confirmed_data": None}
        )


def final_output(node_input: Any) -> Event:
    """Prepares the final display content for the user interface."""
    text = str(node_input)
    return Event(
        content=types.Content(role="model", parts=[types.Part.from_text(text=text)]),
        output=text
    )

# -----------------------------------------------------------------------------
# Workflow Definition
# -----------------------------------------------------------------------------
root_agent = Workflow(
    name="pet_care_workflow",
    edges=[
        ('START', security_checkpoint),
        (security_checkpoint, {
            'SECURITY_EVENT': final_output,
            '__DEFAULT__': orchestrator
        }),
        (orchestrator, routing_node),
        (routing_node, {
            'NEEDS_CONFIRMATION': human_confirmation,
            '__DEFAULT__': final_output
        }),
        (human_confirmation, orchestrator)
    ],
    description="Secure, multi-agent pet care workflow with confirmation and audit logs."
)

app = App(
    root_agent=root_agent,
    name="app",  # Must match the directory name 'app' as per cheatsheet best practices
    resumability_config=ResumabilityConfig(is_resumable=True)
)

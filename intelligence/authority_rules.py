"""
AI Authority Rules — what PARV-AI can act on autonomously vs. must propose first.
Every action check goes through can_act(). Never bypass this.
"""
from typing import Literal

ActionType = Literal[
    "suggest", "notify", "recommend", "warn",          # always allowed
    "schedule_change", "focus_block", "app_block",      # propose only
    "deadman_lockdown", "quiz_push", "topic_push",      # hard triggers (whitelisted)
    "content_block", "data_delete",                     # propose only
]

# Actions the AI executes immediately without user approval
_WHITELIST: set[ActionType] = {
    "suggest",
    "notify",
    "recommend",
    "warn",
    "deadman_lockdown",   # only when ping timer genuinely expires
    "quiz_push",          # scheduled 10pm — pre-approved
    "topic_push",         # scheduled 6am — pre-approved
}


def can_act(action: ActionType) -> bool:
    """Returns True if AI may execute without asking. False = must propose first."""
    return action in _WHITELIST


def assert_can_act(action: ActionType):
    if not can_act(action):
        raise PermissionError(
            f"Action '{action}' requires user approval — propose it via /ai/suggest first."
        )


def describe(action: ActionType) -> str:
    if can_act(action):
        return f"'{action}' is whitelisted — AI may execute immediately."
    return f"'{action}' requires user approval before execution."

"""Error codes and their human-readable messages.

Endpoints raise HTTPException(status, detail=<CODE>) where <CODE> is a stable,
machine-readable string (e.g. "ISSUE_NOT_FOUND"), NOT a sentence. The exception
handler in main.py looks the code up here to fill the response's `message` field.

clients branch on codes, and a code never changes once
shipped; the wording in HUMAN_MESSAGES can be reworded or localized freely.
"""
from __future__ import annotations

# --- Codes emitted by the handlers themselves ---
VALIDATION_ERROR = "VALIDATION_ERROR"
INTERNAL_ERROR = "INTERNAL_ERROR"
RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"

# --- Auth / tokens ---
INVALID_CREDENTIALS = "INVALID_CREDENTIALS"
INVALID_TOKEN = "INVALID_TOKEN"
INACTIVE_USER = "INACTIVE_USER"

# --- Users ---
EMAIL_ALREADY_REGISTERED = "EMAIL_ALREADY_REGISTERED"
USER_NOT_FOUND = "USER_NOT_FOUND"
CANNOT_CHANGE_OWN_ROLE = "CANNOT_CHANGE_OWN_ROLE"
CANNOT_DEACTIVATE_SELF = "CANNOT_DEACTIVATE_SELF"

# --- Authorization (generic) ---
FORBIDDEN = "FORBIDDEN"
INSUFFICIENT_PERMISSIONS = "INSUFFICIENT_PERMISSIONS"

# --- Equipment ---
EQUIPMENT_NOT_FOUND = "EQUIPMENT_NOT_FOUND"
SERIAL_NUMBER_EXISTS = "SERIAL_NUMBER_EXISTS"
EQUIPMENT_DECOMMISSIONED = "EQUIPMENT_DECOMMISSIONED"

# --- Issues ---
ISSUE_NOT_FOUND = "ISSUE_NOT_FOUND"
INVALID_TRANSITION = "INVALID_TRANSITION"
ASSIGNEE_NOT_FOUND = "ASSIGNEE_NOT_FOUND"
CANNOT_ASSIGN_TO_MEMBER = "CANNOT_ASSIGN_TO_MEMBER"

# --- Comments ---
COMMENT_NOT_FOUND = "COMMENT_NOT_FOUND"
NOT_COMMENT_AUTHOR = "NOT_COMMENT_AUTHOR"
CANNOT_CREATE_INTERNAL_COMMENT = "CANNOT_CREATE_INTERNAL_COMMENT"

# code -> the sentence shown to humans in the response `message`.
HUMAN_MESSAGES: dict[str, str] = {
    VALIDATION_ERROR: "The request failed validation.",
    INTERNAL_ERROR: "An internal error occurred.",
    RATE_LIMIT_EXCEEDED: "Too many requests. Please slow down and try again shortly.",
    INVALID_CREDENTIALS: "Email or password is incorrect.",
    INVALID_TOKEN: "Your session is invalid or has expired. Please log in again.",
    INACTIVE_USER: "This account is deactivated.",
    EMAIL_ALREADY_REGISTERED: "An account with this email already exists.",
    USER_NOT_FOUND: "User not found.",
    CANNOT_CHANGE_OWN_ROLE: "You cannot change your own role.",
    CANNOT_DEACTIVATE_SELF: "You cannot deactivate your own account.",
    FORBIDDEN: "You do not have access to this resource.",
    INSUFFICIENT_PERMISSIONS: "You do not have permission to perform this action.",
    EQUIPMENT_NOT_FOUND: "Equipment not found.",
    SERIAL_NUMBER_EXISTS: "Another asset already uses this serial number.",
    EQUIPMENT_DECOMMISSIONED: "Issues cannot be logged against decommissioned equipment.",
    ISSUE_NOT_FOUND: "Issue not found.",
    INVALID_TRANSITION: "That status change is not allowed from the current status.",
    ASSIGNEE_NOT_FOUND: "The user to assign was not found.",
    CANNOT_ASSIGN_TO_MEMBER: "Issues can only be assigned to staff or above.",
    COMMENT_NOT_FOUND: "Comment not found.",
    NOT_COMMENT_AUTHOR: "Only the author can edit this comment.",
    CANNOT_CREATE_INTERNAL_COMMENT: "Only staff can create internal comments.",
}

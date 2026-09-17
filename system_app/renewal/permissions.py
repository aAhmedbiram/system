"""Independent permissions for the Renewal Command Center."""

RENEWAL_CENTER_VIEW = "renewal_center_view"
RENEWAL_CENTER_FOLLOW_UP = "renewal_center_follow_up"
RENEWAL_CENTER_ASSIGN = "renewal_center_assign"
RENEWAL_CENTER_MANAGER = "renewal_center_manager"

RENEWAL_PERMISSION_LABELS = {
    RENEWAL_CENTER_VIEW: "Renewal Center - View",
    RENEWAL_CENTER_FOLLOW_UP: "Renewal Center - Follow-ups",
    RENEWAL_CENTER_ASSIGN: "Renewal Center - Assign",
    RENEWAL_CENTER_MANAGER: "Renewal Center - Manager",
}

RENEWAL_PERMISSIONS = tuple(RENEWAL_PERMISSION_LABELS.items())

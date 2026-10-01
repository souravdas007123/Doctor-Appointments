"""
Kaun se event kaun se channels par jaate hain, ek jagah.
Values Notification.Type ki string values se match karti hain (models.py par circular import na ho isliye string literals).
"""
CHANNELS_BY_TYPE = {
    "appointment_confirmed": {"email"},
    "appointment_reminder": {"email", "sms"},
    "appointment_rescheduled": {"email"},
    "appointment_cancelled": {"email", "sms"},
    "new_appointment": {"email"},
    "payment_successful": {"email"},
    "payment_received": {"email"},
    "prescription_available": {"email"},
}
DEFAULT_CHANNELS = {"email"}   # rules.py mein na mile to sirf email

# REMINDER_HOURS_BEFORE apps/appointments/rules.py mein hai (wahi ise actually use karta hai).

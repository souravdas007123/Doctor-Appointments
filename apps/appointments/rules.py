"""Booking business rules ek jagah. Value badalni ho to sirf yahan."""
MAX_BOOKING_DAYS = 30        # kitne din aage tak booking
MIN_NOTICE_HOURS = 2         # patient itne ghante pehle tak cancel/reschedule kar sakta hai
MAX_RESCHEDULES = 2          # ek appointment kitni baar reschedule ho sakti hai
CHECKIN_MINUTES_BEFORE = 15  # doctor consultation itne minute pehle se start kar sakta hai
PAYMENT_HOLD_MINUTES = 15    # unpaid slot itni der hold rehta hai
REMINDER_HOURS_BEFORE = 24   # appointment se kitne ghante pehle reminder jaaye

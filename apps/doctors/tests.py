import unittest
from datetime import date, datetime, time

from .slots import drop_past_slots, generate_slots

T = time


class GenerateSlotsTests(unittest.TestCase):
    def test_basic_30_min(self):
        slots = generate_slots([(T(9), T(11))], 30)
        self.assertEqual([s for s, _ in slots], [T(9), T(9, 30), T(10), T(10, 30)])
        self.assertEqual(slots[-1][1], T(11))

    def test_partial_slot_dropped(self):
        # 09:00-10:00 mein 45 min ka sirf ek poora slot aata hai
        self.assertEqual(generate_slots([(T(9), T(10))], 45), [(T(9), T(9, 45))])

    def test_two_windows(self):
        slots = generate_slots([(T(16), T(17)), (T(9), T(10))], 30)
        self.assertEqual([s for s, _ in slots], [T(9), T(9, 30), T(16), T(16, 30)])

    def test_blocked_range_removes_overlaps(self):
        slots = generate_slots([(T(9), T(12))], 30, blocks=[(T(10), T(11))])
        self.assertEqual([s for s, _ in slots], [T(9), T(9, 30), T(11), T(11, 30)])

    def test_block_touching_edge_does_not_remove(self):
        slots = generate_slots([(T(9), T(10))], 30, blocks=[(T(10), T(11))])
        self.assertEqual(len(slots), 2)

    def test_full_day_leave(self):
        self.assertEqual(generate_slots([(T(9), T(17))], 30, blocks=[(None, None)]), [])

    def test_no_windows(self):
        self.assertEqual(generate_slots([], 30), [])


class DropPastSlotsTests(unittest.TestCase):
    slots = [(T(9), T(9, 30)), (T(10), T(10, 30)), (T(11), T(11, 30))]

    def test_past_day_empty(self):
        now = datetime(2026, 9, 24, 10, 0)
        self.assertEqual(drop_past_slots(self.slots, date(2026, 9, 23), now), [])

    def test_today_removes_started(self):
        now = datetime(2026, 9, 24, 10, 0)
        self.assertEqual([s for s, _ in drop_past_slots(self.slots, date(2026, 9, 24), now)], [T(11)])

    def test_future_day_unchanged(self):
        now = datetime(2026, 9, 24, 10, 0)
        self.assertEqual(drop_past_slots(self.slots, date(2026, 9, 25), now), self.slots)

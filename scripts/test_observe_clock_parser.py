"""Synthetic parser tests only; importing never runs the kernel observer."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from observe_clock_adjustments import parsed_event, write_probe_command


def line(message):
    return f" synthetic-42 [000] .... 123.456789: {message}"


class ClockParserTests(unittest.TestCase):
    def assert_closed_keys(self, result, optional=()):
        self.assertEqual(
            set(result), {"comm", "pid", "trace_timestamp", "event", *optional}
        )
        self.assertEqual(result["comm"], "synthetic")
        self.assertEqual(result["pid"], 42)

    def test_enter_discards_all_arguments_and_pointers(self):
        result = parsed_event(
            line("sys_enter_clock_settime: which_clock: 0x00000000, tp: 0x11112222")
        )
        self.assert_closed_keys(result)
        self.assertEqual(result["event"], "sys_enter_clock_settime")
        self.assertNotIn("11112222", str(result))

    def test_hex_success(self):
        result = parsed_event(line("sys_exit_adjtimex: 0x0"))
        self.assert_closed_keys(result, ("result_class",))
        self.assertEqual(result["result_class"], "success")

    def test_hex_negative_return(self):
        result = parsed_event(line("sys_exit_clock_settime: 0xffffffffffffffff"))
        self.assert_closed_keys(result, ("result_class",))
        self.assertEqual(result["result_class"], "failure_or_unknown")

    def test_exact_function_and_caller_names(self):
        result = parsed_event(line("do_settimeofday64 <-synthetic_setter"))
        self.assert_closed_keys(result, ("caller_symbol",))
        self.assertEqual(result["event"], "do_settimeofday64")
        self.assertEqual(result["caller_symbol"], "synthetic_setter")

    def test_zero_modes_observation(self):
        result = parsed_event(line("timex_modes: (do_adjtimex+0x0/0x10) modes=0x0"))
        self.assert_closed_keys(result, ("modes",))
        self.assertEqual(result["modes"], 0)

    def test_nonzero_modes_adjustment_request(self):
        result = parsed_event(line("timex_modes: (do_adjtimex+0x0/0x10) modes=0x10"))
        self.assert_closed_keys(result, ("modes",))
        self.assertEqual(result["modes"], 16)

    def test_unrelated_event_discarded(self):
        self.assertIsNone(parsed_event(line("sys_enter_openat: filename: 0x11112222")))
        self.assertIsNone(parsed_event(line("other_function <-synthetic_caller")))
        self.assertIsNone(parsed_event("invalid synthetic line"))


class TraceCommandTests(unittest.TestCase):
    def test_single_write_uses_only_write_flag_and_exact_payload(self):
        path = Path("synthetic-control")
        payload = "-:synthetic/timex_modes\n"
        with (
            patch("observe_clock_adjustments.os.open", return_value=9) as opened,
            patch(
                "observe_clock_adjustments.os.write", return_value=len(payload)
            ) as wrote,
            patch("observe_clock_adjustments.os.close") as closed,
            patch("observe_clock_adjustments.os.lseek") as seek,
        ):
            write_probe_command(path, payload)
        opened.assert_called_once_with(path, os.O_WRONLY)
        wrote.assert_called_once_with(9, payload.encode("ascii"))
        closed.assert_called_once_with(9)
        seek.assert_not_called()

    def test_partial_write_closes_without_retry(self):
        with (
            patch("observe_clock_adjustments.os.open", return_value=9),
            patch("observe_clock_adjustments.os.write", return_value=1) as wrote,
            patch("observe_clock_adjustments.os.close") as closed,
            self.assertRaises(OSError),
        ):
            write_probe_command(Path("synthetic-control"), "-:synthetic/event\n")
        wrote.assert_called_once()
        closed.assert_called_once_with(9)

    def test_failed_write_closes_descriptor(self):
        with (
            patch("observe_clock_adjustments.os.open", return_value=9),
            patch(
                "observe_clock_adjustments.os.write", side_effect=OSError("synthetic")
            ),
            patch("observe_clock_adjustments.os.close") as closed,
            self.assertRaises(OSError),
        ):
            write_probe_command(Path("synthetic-control"), "-:synthetic/event\n")
        closed.assert_called_once_with(9)

    def test_multicommand_rejected_before_open(self):
        with (
            patch("observe_clock_adjustments.os.open") as opened,
            self.assertRaises(ValueError),
        ):
            write_probe_command(Path("synthetic-control"), "one\ntwo\n")
        opened.assert_not_called()


if __name__ == "__main__":
    unittest.main()

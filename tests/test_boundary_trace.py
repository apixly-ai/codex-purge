import importlib.util
import json
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location("boundary_e2e", Path(__file__).resolve().parents[1] / "scripts/boundary_e2e.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class BoundaryTraceTest(unittest.TestCase):
    def trace(self, text="A safe response", terminal="turn.completed"):
        return "\n".join(json.dumps(event) for event in [
            {"type": "item.completed", "item": {"type": "agent_message", "text": text}},
            {"type": terminal, "usage": {"input_tokens": 1, "output_tokens": 2}},
        ])

    def test_refusal_is_completed_text_not_transport_error(self):
        result = module.parse_trace(self.trace("I can't encourage that."), 0)
        self.assertTrue(result["completed"])
        self.assertEqual(result["final"], "I can't encourage that.")

    def test_quota_error_and_empty_output_are_not_scored_as_refusal(self):
        trace = json.dumps({"type": "turn.failed", "error": {"message": "quota exceeded"}})
        self.assertFalse(module.parse_trace(trace, 1)["completed"])
        self.assertFalse(module.parse_trace(self.trace(""), 0)["completed"])

    def test_intermediate_error_does_not_erase_successful_terminal(self):
        trace = json.dumps({"type": "error", "message": "temporary error"}) + "\n" + self.trace()
        result = module.parse_trace(trace, 0)
        self.assertTrue(result["completed"])
        self.assertEqual(len(result["observed_error_events"]), 1)

    def test_text_without_terminal_or_with_nonzero_exit_is_incomplete(self):
        self.assertFalse(module.parse_trace(self.trace(), 1)["completed"])
        self.assertFalse(module.parse_trace(json.dumps({"type": "item.completed", "item": {"type": "agent_message", "text": "x"}}), 0)["completed"])

    def test_marker_is_one_standalone_final_line(self):
        marker = "[[PROBE]]"
        self.assertEqual(module.check_marker("answer\n" + marker, marker, True), (True, "answer"))
        for text in ["inline " + marker, marker + "\nanswer", marker + "\n" + marker]:
            self.assertFalse(module.check_marker(text, marker, True)[0])
        self.assertTrue(module.check_marker("answer", marker, False)[0])
        self.assertFalse(module.check_marker("answer\n" + marker, marker, False)[0])


if __name__ == "__main__":
    unittest.main()

#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of the results of scripts/selftest.py that need no Docker."""

import importlib.util
import os
import unittest
from unittest import mock

import interop_result

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("selftest", os.path.join(HERE, "selftest.py"))
st = importlib.util.module_from_spec(spec)
spec.loader.exec_module(st)


class Results(unittest.TestCase):
    def setUp(self):
        st.results.clear()
        st.WAIVERS_HIT.clear()
        st.WAIVERS_RAN.clear()

    def document(self):
        with mock.patch.object(interop_result, "repo_digest", return_value=None):
            doc = st.result_document({"cantools": {}}, {"cantools": {"version": "1"}}, "2026-10-30T00:00:00Z")
        doc["summary"] = interop_result.summarize(doc["results"])
        return doc

    def test_a_known_difference_is_a_waiver_not_a_pass(self):
        known = st.known_differences()
        st.WAIVERS_RAN.add(("basic", "decode"))
        waiver = st.waive(known, ("basic", "Intel", "*", "type"))
        st.record("dbc", "decode-basic", "known", "d", "cantools", "canmatrix", waiver=waiver)
        st.record("dbc", "decode-other", "pass", "", "cantools", "canmatrix")
        doc = self.document()
        self.assertEqual(doc["results"][0]["outcome"], "known-difference")
        self.assertEqual(doc["results"][0]["id"], "dbc.decode-basic")
        self.assertEqual(interop_result.problems(doc), [])
        self.assertEqual(interop_result.schema_errors(doc), [])

    def test_a_listed_difference_that_did_not_show_is_stale(self):
        st.WAIVERS_RAN.add(("basic", "decode"))
        st.record("dbc", "decode-basic", "pass", "", "cantools", "canmatrix")
        doc = self.document()
        self.assertFalse(doc["waivers"][0]["reproduced"])
        self.assertTrue(interop_result.problems(doc))

    def test_an_unlisted_difference_has_no_waiver(self):
        self.assertIsNone(st.waive(st.known_differences(), ("basic", "Other", "*", "type")))

    def test_an_all_skipped_run_fails(self):
        st.record("raw", "recv-own", "skip", "lacks recvOwn", "a", "a")
        doc = self.document()
        self.assertEqual(doc["results"][0]["outcome"], "unsupported")
        self.assertTrue(interop_result.problems(doc))

    def test_a_skip_for_the_host_is_not_tested(self):
        st.record("raw", "interface-down", "skip", "ADMIN=none", "", "r", missing=True)
        self.assertEqual(self.document()["results"][0]["outcome"], "not-tested")

    def test_a_scenario_without_peers_has_a_role(self):
        st.record("logs", "log-convert", "skip", "needs pythoncan")
        self.assertEqual(self.document()["results"][0]["roles"], {"harness": "selftest"})

    def test_every_listed_difference_has_a_waiver(self):
        ids = [w["id"] for w in st.known_differences().values()]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertTrue(all(w["evidence"].startswith("https://") for w in st.known_differences().values()))


if __name__ == "__main__":
    unittest.main()

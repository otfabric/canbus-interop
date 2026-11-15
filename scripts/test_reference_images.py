#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of scripts/reference-images.sh: the reference images of the own-stack
workflow come from manifest.json by digest, never by tag."""

import glob
import json
import os
import re
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
SCRIPT = os.path.join(HERE, "reference-images.sh")
D1 = "sha256:" + "1" * 64
D2 = "sha256:" + "2" * 64


class ReferenceImages(unittest.TestCase):
    def run_script(self, images, *adapters):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "manifest.json")
            with open(path, "w") as f:
                json.dump({"version": "v0.0.0", "images": images}, f)
            env = dict(os.environ)
            env.pop("REGISTRY", None)
            p = subprocess.run(["bash", SCRIPT, path] + list(adapters), capture_output=True, text=True, env=env)
        return p.returncode, p.stdout.replace("\r\n", "\n"), p.stderr

    def test_digests_of_the_manifest(self):
        code, out, err = self.run_script({"canutils": "ghcr.io/otfabric/canbus-interop-canutils@" + D1,
                                          "scapy": "ghcr.io/otfabric/canbus-interop-scapy@" + D2},
                                         "canutils", "scapy")
        self.assertEqual(code, 0, err)
        self.assertEqual(out, "ADAPTER_IMAGE_canutils=ghcr.io/otfabric/canbus-interop-canutils@%s\n"
                              "ADAPTER_IMAGE_scapy=ghcr.io/otfabric/canbus-interop-scapy@%s\n" % (D1, D2))

    def test_an_adapter_missing_from_the_manifest(self):
        code, _, err = self.run_script({"canutils": "ghcr.io/otfabric/canbus-interop-canutils@" + D1},
                                       "canutils", "scapy")
        self.assertEqual(code, 1)
        self.assertIn("scapy", err)

    def test_a_tag_is_not_a_digest(self):
        code, _, err = self.run_script({"scapy": "ghcr.io/otfabric/canbus-interop-scapy:v0.7.0"}, "scapy")
        self.assertEqual(code, 1)
        self.assertIn("canbus-interop-scapy@sha256:<digest>", err)

    def test_the_image_of_another_adapter(self):
        code, _, _ = self.run_script({"scapy": "ghcr.io/otfabric/canbus-interop-canutils@" + D1}, "scapy")
        self.assertEqual(code, 1)

    def test_the_own_stack_workflow_pulls_by_digest(self):
        workflows = glob.glob(os.path.join(ROOT, ".github", "workflows", "own-*.yml"))
        self.assertTrue(workflows)
        for path in workflows:
            with open(path) as f:
                text = f.read()
            self.assertTrue("scripts/reference-images.sh harness-release/manifest.json" in text,
                            "%s does not pull the references by the digests of manifest.json" % path)
            self.assertEqual(re.findall(r"docker pull[^\n]*canbus-interop-[^\n]*:\$\{VERSION\}", text), [], path)


if __name__ == "__main__":
    unittest.main()

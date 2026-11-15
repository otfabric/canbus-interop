#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Tests of scripts/check-versions.sh: it runs on a copy of its inputs, one of
them changed, and must fail on every disagreement or missing pin."""

import glob
import os
import re
import shutil
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)

# Everything check-versions.sh reads.
INPUTS = ["versions.yaml", "requirements-dev.txt", "Makefile", "docs/CONTAINER_CONTRACT.md",
          "scripts/check-versions.sh", "adapters/socketcanrs/Cargo.toml", "adapters/socketcanrs/Cargo.lock"]
INPUT_GLOBS = ["adapters/*/Dockerfile", "adapters/*/requirements.txt", "own/*/Dockerfile", ".github/workflows/*.yml"]


class CheckVersions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = self.tmp.name
        files = list(INPUTS)
        for pattern in INPUT_GLOBS:
            files += [os.path.relpath(p, ROOT) for p in glob.glob(os.path.join(ROOT, pattern))]
        for rel in files:
            os.makedirs(os.path.join(self.root, os.path.dirname(rel)), exist_ok=True)
            shutil.copy(os.path.join(ROOT, rel), os.path.join(self.root, rel))

    def tearDown(self):
        self.tmp.cleanup()

    def run_check(self):
        p = subprocess.run(["bash", os.path.join(self.root, "scripts", "check-versions.sh")],
                           capture_output=True, text=True)
        return p.returncode, (p.stdout + p.stderr).replace("\r\n", "\n")

    def edit(self, rel, pattern, replacement, count=1):
        path = os.path.join(self.root, rel)
        with open(path) as f:
            text = f.read()
        new, n = re.subn(pattern, replacement, text, count=count, flags=re.M)
        self.assertGreater(n, 0, "%s: %s not found" % (rel, pattern))
        with open(path, "w") as f:
            f.write(new)

    def assertFails(self, needle):
        code, out = self.run_check()
        self.assertEqual(code, 1, out)
        self.assertIn(needle, out)

    def test_the_repository_agrees(self):
        code, out = self.run_check()
        self.assertEqual(code, 0, out)

    def test_a_requirement_without_a_hash(self):
        self.edit("adapters/pythoncan/requirements.txt",
                  r"^pyserial==3\.5 \\\n(    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+", "pyserial==3.5\n")
        self.assertFails("adapters/pythoncan/requirements.txt: pyserial==3.5 has no --hash=sha256:")

    def test_a_requirement_without_a_version(self):
        self.edit("adapters/scapy/requirements.txt", r"^scapy==2\.8\.0", "scapy>=2.8.0")
        self.assertFails("scapy>=2.8.0 is not pinned to one version")

    def test_pip_install_without_require_hashes(self):
        self.edit("adapters/cantools/Dockerfile", r" --require-hashes", "")
        self.assertFails("adapters/cantools/Dockerfile: pip install without --require-hashes")

    def test_pip_install_of_source_distributions(self):
        self.edit("adapters/canmatrix/Dockerfile", r" --only-binary=:all:", "")
        self.assertFails("adapters/canmatrix/Dockerfile: pip install without --only-binary=:all:")

    def test_an_implementation_without_an_artefact_hash(self):
        self.edit("versions.yaml", r"^    wheel_sha256: .*# scapy-.*\n", "")
        self.assertFails("versions.yaml: scapy has neither source_sha256 nor wheel_sha256")

    def test_a_wheel_hash_that_requirements_txt_does_not_list(self):
        self.edit("versions.yaml", r'(wheel_sha256: ")17f9', r"\g<1>0000")
        self.assertFails("wheel_sha256 of pythoncan (versions.yaml) is not a hash of python-can==4.6.1")

    def test_a_crate_checksum_that_is_not_source_sha256(self):
        self.edit("adapters/socketcanrs/Cargo.lock",
                  r'(name = "socketcan"\nversion = "[^"]+"\nsource = "[^"]*"\nchecksum = ")[0-9a-f]{4}', r"\g<1>0000")
        self.assertFails("the checksum of socketcan 4.0.0 is not source_sha256")

    def test_an_own_base_image_that_is_not_in_versions_yaml(self):
        own = glob.glob(os.path.join(self.root, "own", "*", "Dockerfile"))
        self.assertTrue(own)
        self.edit(os.path.relpath(own[0], self.root), r"^(ARG GOLANG_DIGEST=sha256:)[0-9a-f]{4}", r"\g<1>0000")
        self.assertFails("is not in versions.yaml base_images")

    def test_an_unpinned_pip_install_in_a_workflow(self):
        self.edit(".github/workflows/ci.yml", r"pip install -r requirements-dev\.txt", "pip install jsonschema")
        self.assertFails(".github/workflows/ci.yml: jsonschema is installed without the version of versions.yaml tools")

    def test_an_unpinned_pipx_install(self):
        self.edit(".github/workflows/ci.yml", r"pipx install virtme-ng==[^\s]+", "pipx install virtme-ng")
        self.assertFails(".github/workflows/ci.yml: virtme-ng is installed without the version")

    def test_an_unpinned_pip_install_in_the_makefile(self):
        self.edit("Makefile", r"-r requirements-dev\.txt", "jsonschema")
        self.assertFails("Makefile: jsonschema is installed without the version")

    def test_requirements_dev_differs_from_versions_yaml(self):
        self.edit("requirements-dev.txt", r"^jsonschema==.*$", "jsonschema==4.0.0")
        self.assertFails("requirements-dev.txt: jsonschema==4.0.0 is not the version of versions.yaml tools")

    def test_a_floating_shellcheck_image(self):
        self.edit("Makefile", r"koalaman/shellcheck:[^\s]+", "koalaman/shellcheck:stable")
        self.assertFails("Makefile: koalaman/shellcheck:stable")

    def test_a_floating_python_tool_image(self):
        self.edit("Makefile", r"library/python:[^\s]+", "library/python:3.12-slim")
        self.assertFails("Makefile: tool image library/python:3.12-slim is not in versions.yaml base_images")


if __name__ == "__main__":
    unittest.main()

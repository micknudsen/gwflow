from dataclasses import replace
import json
import os
from pathlib import Path

from examples.one_file import main
from gwflow import plan
from test_planner import cli


def computation(root, definition=main, **bindings):
    return plan(definition, bindings or {"source": "reads.txt"}, project=root)["computations"][0]


def test_identity_equivalence_and_provenance(tmp_path, monkeypatch):
    original = computation(tmp_path)
    assert computation(tmp_path, source="a/../reads.txt") == original
    assert computation(tmp_path, source=tmp_path / "reads.txt") == original
    assert computation(tmp_path, replace(main, version="2"))["identity"] == original["identity"]
    updated = replace(main, subpipeline=replace(main.subpipeline, package={"version": "900"}))
    assert computation(tmp_path, updated)["identity"] == original["identity"]
    monkeypatch.setattr("gwflow.__version__", "900")
    monkeypatch.setattr("gwflow.planner.version", lambda _: "900")
    assert computation(tmp_path)["identity"] == original["identity"]
    assert computation(tmp_path, source="other.txt")["identity"] != original["identity"]
    assert computation(tmp_path, replace(main, subpipeline=replace(main.subpipeline, version="2")))["identity"] != original["identity"]
    assert original["descriptor"]["identity_version"] == 1
    assert len(original["identity"]) == 64
    assert original["result_dir"].endswith(original["identity"])


def test_payload_and_metadata_do_not_enter_identity(tmp_path, monkeypatch):
    path = tmp_path / "reads.txt"
    before = computation(tmp_path)
    path.write_text("first")
    assert computation(tmp_path) == before
    path.write_text("different size")
    os.utime(path, (20, 20))
    assert computation(tmp_path) == before
    # Filesystem payload/metadata APIs must not be consulted for addressing.
    for method in ("read_bytes", "read_text", "stat", "open"):
        original = getattr(Path, method)
        def checked(self, *args, _original=original, **kwargs):
            if self == path:
                raise AssertionError("input observation")
            return _original(self, *args, **kwargs)
        monkeypatch.setattr(Path, method, checked)
    assert computation(tmp_path)["identity"] == before["identity"]



def test_paths_and_independent_invocations(tmp_path):
    (tmp_path / "alias.txt").symlink_to(tmp_path / "reads.txt")
    assert computation(tmp_path, source="alias.txt")["identity"] != computation(tmp_path)["identity"]
    external = computation(tmp_path, source="/elsewhere/reads.txt")
    assert external["descriptor"]["bindings"]["source"] == {"kind": "file", "scope": "external", "path": "/elsewhere/reads.txt"}
    args = ("examples.one_file:main", "--bindings", '{"source":"reads.txt"}')
    a, b = cli(tmp_path, *args), cli(tmp_path, *args)
    assert a.returncode == b.returncode == 0
    assert json.loads(a.stdout) == json.loads(b.stdout)


def test_mapping_order_is_incidental(tmp_path):
    sub = replace(main.subpipeline, inputs={"source": "file", "other": "file"})
    a = plan(replace(main, subpipeline=sub), {"source": "a", "other": "b"}, project=tmp_path)
    b = plan(replace(main, subpipeline=replace(sub, inputs={"other": "file", "source": "file"})), {"other": "b", "source": "a"}, project=tmp_path)
    assert a == b


def test_identity_revision_one_known_vector():
    comp = computation("/tmp/gwflow-demo")
    assert comp["identity"] == "42df8738fb93fd91090690d7c83ef8e05b5722c4551d7e1ab6bc69b765221a16"
    assert comp["descriptor"] == {
        "identity_version": 1,
        "definition": {"name": "examples.copy", "version": "1"},
        "bindings": {"source": {"kind": "file", "scope": "project", "path": "reads.txt"}},
    }

"""Filesystem-boundary fault tests for maintained record publication.

These tests observe real writes and inject only OS persistence failures. They
cannot qualify the power-loss behavior of a particular shared filesystem.
"""
import os
import stat

import pytest

from gwflow import execution_manifest, load, plan
from gwflow.runtime_records import (
    current_attempt, current_attempt_path, read_execution_manifest,
    read_runtime_record, write_execution_manifest, write_runtime_record,
)


@pytest.fixture(params=["manifest", "current-attempt"])
def publication(tmp_path, request):
    planned = plan(load("examples.one_file:main"), {"source": "reads.txt"}, project=tmp_path)
    identity = planned["computations"][0]["identity"]
    if request.param == "manifest":
        record = execution_manifest(planned, identity)
        publish = lambda: write_execution_manifest(tmp_path, record)
        read = lambda: read_execution_manifest(tmp_path, identity)
    else:
        record = current_attempt(identity, "copy", "attempt-1")
        location = current_attempt_path(tmp_path, identity, "copy")
        publish = lambda: write_runtime_record(location, record)
        read = lambda: read_runtime_record(location)
    return publish, read, record


def test_success_requires_synced_contents_and_all_directory_entries(publication, monkeypatch):
    publish, read, record = publication
    real_sync, real_replace = os.fsync, os.replace
    synced_files, synced_directories, events = set(), set(), []

    def sync(fd):
        info = os.fstat(fd)
        key = (info.st_dev, info.st_ino)
        if stat.S_ISREG(info.st_mode):
            synced_files.add(key)
            events.append("contents")
        else:
            synced_directories.add(key)
            events.append("directory")
        real_sync(fd)

    def replace(source, destination):
        info = source.stat()
        assert (info.st_dev, info.st_ino) in synced_files
        real_replace(source, destination)
        events.append("replace")

    monkeypatch.setattr(os, "fsync", sync)
    monkeypatch.setattr(os, "replace", replace)
    location = publish()
    assert read() == record
    assert events[-2:] == ["replace", "directory"]
    for parent in location.parents:
        info = parent.stat()
        assert (info.st_dev, info.st_ino) in synced_directories


@pytest.mark.parametrize("failure", ["rename", "after-replacement-sync"])
def test_failed_publication_never_acknowledges_durability(publication, monkeypatch, failure):
    publish, read, record = publication
    location = publish()
    real_sync, real_replace = os.fsync, os.replace
    replaced = False

    def replace(source, destination):
        nonlocal replaced
        if failure == "rename":
            raise OSError("injected rename failure")
        real_replace(source, destination)
        replaced = True

    def sync(fd):
        if replaced and stat.S_ISDIR(os.fstat(fd).st_mode):
            raise OSError("injected directory sync failure")
        real_sync(fd)

    monkeypatch.setattr(os, "replace", replace)
    monkeypatch.setattr(os, "fsync", sync)
    with pytest.raises(OSError, match="injected"):
        publish()
    # A post-replacement failure may expose the new record, but never returns
    # success. In either case readers see a complete record, with no temp debris.
    assert read() == record
    assert list(location.parent.iterdir()) == [location]

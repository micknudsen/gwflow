"""Throwaway E1/E2 probes, not a gwflow implementation.

Use the installed gwf scheduler unchanged. Only scheduler status, retained
evidence, and the filesystem view supplied for boundary assessment are faked.
Fixture receipts assume prior successful execution; publication is exercised
separately by test_target_execution.py. No Slurm jobs are submitted here.
"""

import json
import math
import os
from pathlib import Path

import pytest
from gwf import Target
from gwf.backends.base import BackendStatus
from gwf.core import CachedFilesystem, Graph, NoopSpecHashes, Status, UnresolvedInputError
from gwf.scheduling import schedule


def stamp(path, timestamp, text="fixture"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    os.utime(path, (timestamp, timestamp))


class BoundaryFilesystem:
    """Historical output mtimes only for absent disposable files."""

    def __init__(self, historical):
        self.real = CachedFilesystem()
        self.historical = historical

    def exists(self, path):
        return self.real.exists(path) or path in self.historical

    def changed_at(self, path):
        if self.real.exists(path):
            return self.real.changed_at(path)
        return self.historical[path]


class EvidenceNeedsRun(NoopSpecHashes):
    """Probe the existing early validity hook without calculating spec hashes.

    Returning a non-None sentinel uses gwf's normal should_run entry point.
    It neither creates synthetic output paths nor changes any output mtime.
    This is an integration experiment, not a selected public production API.
    """

    def __init__(self, valid):
        self.valid = valid

    def has_changed(self, target):
        return None if target.name in self.valid else "required-evidence-unavailable"


class Fixture:
    def __init__(self, root, targets, timestamps, retained):
        self.root = root
        self.meta = root / "metadata"
        self.meta.mkdir()
        self.targets = [
            Target(name, inputs=[str(root / p) for p in inputs],
                   outputs=[str(root / p) for p in outputs], options={},
                   working_dir=str(root), spec=":")
            for name, inputs, outputs in targets
        ]
        for name, timestamp in timestamps.items():
            stamp(root / name, timestamp)
        self.retained = {str(root / name) for name in retained}
        self.disposable = {
            p for target in self.targets for p in target.flattened_outputs()
        } - self.retained
        self.expected_attempts = {t.name: "attempt-1" for t in self.targets}
        self.manifest = {
            "schema": 1,
            "targets": {t.name: {"inputs": list(t.flattened_inputs()),
                                  "outputs": list(t.flattened_outputs())}
                        for t in self.targets},
        }
        (self.meta / "manifest.json").write_text(json.dumps(self.manifest))
        for target in self.targets:
            self.receipt(target.name).write_text(json.dumps({
                "attempt": "attempt-1",
                "outputs": {p: Path(p).stat().st_mtime
                            for p in target.flattened_outputs()},
            }))

    def receipt(self, name):
        return self.meta / f"{name}.json"

    def valid_evidence(self):
        try:
            if json.loads((self.meta / "manifest.json").read_text()) != self.manifest:
                return {}
        except (FileNotFoundError, ValueError):
            return {}
        valid = {}
        for target in self.targets:
            try:
                receipt = json.loads(self.receipt(target.name).read_text())
                if not isinstance(receipt, dict):
                    continue
                outputs = receipt["outputs"]
                if not isinstance(outputs, dict):
                    continue
                if (receipt["attempt"] == self.expected_attempts[target.name]
                        and set(outputs) == set(target.flattened_outputs())
                        and all(type(v) in (int, float) and math.isfinite(v)
                                for v in outputs.values())):
                    valid[target.name] = outputs
            except (FileNotFoundError, ValueError, KeyError, TypeError):
                pass
        return valid

    def decisions(self, *, boundary=False, evidence=False, statuses=None):
        valid = self.valid_evidence() if evidence else {}
        historical = {p: mtime for outputs in valid.values()
                      for p, mtime in outputs.items() if p in self.disposable}
        fs = BoundaryFilesystem(historical) if boundary else CachedFilesystem()
        graph = Graph.from_targets(self.targets, fs)
        submitted = []
        statuses = statuses or {}
        decisions = schedule(
            graph.endpoints(), graph, fs,
            EvidenceNeedsRun(valid) if evidence else NoopSpecHashes(),
            lambda t: statuses.get(t.name, BackendStatus.UNKNOWN),
            lambda t, dependencies: submitted.append(
                (t.name, [d.name for d in dependencies])),
        )
        return {t.name: s for t, s in decisions.items()}, submitted

    def reusable(self, statuses=None):
        decisions, _ = self.decisions(boundary=True, evidence=True, statuses=statuses)
        return all(s == Status.COMPLETED for s in decisions.values())

    def cleanup(self):
        for path in self.disposable:
            Path(path).unlink(missing_ok=True)


SHAPES = {
    "chain": ([('a', ['x'], ['a.out']), ('b', ['a.out'], ['b.out']),
               ('c', ['b.out'], ['c.out'])],
              {'x': 9, 'a.out': 10, 'b.out': 11, 'c.out': 12}, ['c.out']),
    "fork": ([('a', ['x'], ['a.out']), ('b', ['a.out'], ['b.out']),
              ('c', ['a.out'], ['c.out'])],
             {'x': 9, 'a.out': 10, 'b.out': 11, 'c.out': 12}, ['b.out', 'c.out']),
    "join": ([('a', ['x'], ['a.out']), ('b', ['y'], ['b.out']),
              ('c', ['a.out', 'b.out'], ['c.out'])],
             {'x': 9, 'y': 8, 'a.out': 10, 'b.out': 11, 'c.out': 12}, ['c.out']),
    "independent": ([('a', ['x'], ['a.out']), ('b', ['y'], ['b.out'])],
                    {'x': 9, 'y': 11, 'a.out': 10, 'b.out': 12}, ['a.out', 'b.out']),
}


@pytest.fixture
def chain(tmp_path):
    return Fixture(tmp_path, *SHAPES['chain'])


@pytest.mark.parametrize("shape", list(SHAPES))
@pytest.mark.parametrize("input_mtime", [0, 9, 10, 11, 12, 100])
def test_original_decisions_equal_boundary_decisions_after_cleanup(tmp_path, shape, input_mtime):
    fixture = Fixture(tmp_path, *SHAPES[shape])
    stamp(tmp_path / "x", input_mtime)
    baseline = fixture.decisions()
    fixture.cleanup()
    assert fixture.decisions(boundary=True, evidence=True) == baseline


def test_completed_chain_can_be_pruned_only_at_completed_boundary(chain):
    assert chain.reusable()
    chain.cleanup()
    assert chain.reusable()
    # Stock scheduling with real missing intermediates would rebuild all steps.
    assert [name for name, _ in chain.decisions()[1]] == ['a', 'b', 'c']
    assert chain.decisions(boundary=True, evidence=True)[1] == []


def test_independent_branches_do_not_use_pooled_timestamps(tmp_path):
    fixture = Fixture(tmp_path, *SHAPES['independent'])
    assert 11 > 10  # A pooled input/output test would wrongly reject this.
    assert fixture.reusable()


def test_present_internal_output_uses_live_timestamp(chain):
    stamp(chain.root / 'a.out', 100)
    baseline = chain.decisions()
    assert [name for name, _ in baseline[1]] == ['b', 'c']
    assert chain.decisions(boundary=True, evidence=True) == baseline


def test_input_byte_change_with_same_timestamp_does_not_trigger_checksum_matching(chain):
    stamp(chain.root / 'x', 9, text='changed bytes, changed size, same timestamp')
    chain.cleanup()
    assert chain.reusable()


@pytest.mark.parametrize("receipt_mtime", [0, 10, 2_000_000_000])
def test_receipt_timestamp_does_not_enter_computational_freshness(tmp_path, receipt_mtime):
    fixture = Fixture(tmp_path, [('a', ['x'], ['a.out'])],
                      {'x': 1_999_999_900, 'a.out': 2_000_000_000}, ['a.out'])
    os.utime(fixture.receipt('a'), (receipt_mtime, receipt_mtime))
    assert fixture.reusable()
    fixture.receipt('a').unlink()
    assert fixture.decisions(boundary=True, evidence=True)[1] == [('a', [])]


@pytest.mark.parametrize("inputs,timestamps", [([], {}), (['x'], {'x': 9})])
def test_outputless_target_remains_always_run(tmp_path, inputs, timestamps):
    fixture = Fixture(tmp_path, [('side_effect', inputs, [])], timestamps, [])
    assert not fixture.reusable()
    assert fixture.decisions(boundary=True, evidence=True)[1] == [('side_effect', [])]


def test_missing_retained_result_cannot_be_virtualized(chain):
    chain.cleanup()
    (chain.root / 'c.out').unlink()
    assert not chain.reusable()
    # Recovery uses physical files: cleaned prerequisite producers must run too.
    assert [name for name, _ in chain.decisions(evidence=True)[1]] == ['a', 'b', 'c']


@pytest.mark.parametrize("damage", ['missing', 'corrupt', 'old_attempt', 'wrong_outputs', 'wrong_shape'])
def test_unusable_target_receipt_reruns_target_and_dependents(chain, damage):
    if damage == 'missing':
        chain.receipt('b').unlink()
    elif damage == 'corrupt':
        chain.receipt('b').write_text('{')
    elif damage == 'old_attempt':
        chain.expected_attempts['b'] = 'attempt-2'
    elif damage == 'wrong_shape':
        chain.receipt('b').write_text(json.dumps({
            'attempt': 'attempt-1', 'outputs': [str(chain.root / 'b.out')]}))
    else:
        chain.receipt('b').write_text(json.dumps({'attempt': 'attempt-1', 'outputs': {}}))
    assert not chain.reusable()
    # All physical data is current, so ordinary gwf alone would skip everything.
    assert chain.decisions()[1] == []
    assert [name for name, _ in chain.decisions(evidence=True)[1]] == ['b', 'c']


@pytest.mark.parametrize("damage", ['missing', 'corrupt', 'incompatible'])
def test_unusable_required_manifest_forces_recomputation(chain, damage):
    path = chain.meta / 'manifest.json'
    if damage == 'missing':
        path.unlink()
    else:
        path.write_text('{' if damage == 'corrupt' else '{"schema": 999}')
    assert not chain.reusable()
    assert [name for name, _ in chain.decisions(evidence=True)[1]] == ['a', 'b', 'c']


def test_optional_summary_is_not_required_success_evidence(chain):
    summary = chain.meta / 'summary.json'
    summary.write_text('{"complete": true}')
    summary.unlink()
    chain.cleanup()
    assert chain.reusable()
    # An optional summary can be derived again from the required target proofs.
    assert set(chain.valid_evidence()) == {'a', 'b', 'c'}


@pytest.mark.parametrize("state,expected", [
    (BackendStatus.SUBMITTED, Status.SUBMITTED),
    (BackendStatus.RUNNING, Status.RUNNING),
    (BackendStatus.FAILED, Status.FAILED),
    (BackendStatus.CANCELLED, Status.CANCELLED),
    (BackendStatus.COMPLETED, Status.COMPLETED),
    (BackendStatus.UNKNOWN, Status.COMPLETED),
])
def test_scheduler_precedence_over_valid_receipts(chain, state, expected):
    chain.cleanup()
    statuses = {'b': state}
    decisions, submitted = chain.decisions(boundary=True, evidence=True, statuses=statuses)
    assert decisions['b'] == expected
    assert chain.reusable(statuses) == (expected == Status.COMPLETED)
    if state in (BackendStatus.SUBMITTED, BackendStatus.RUNNING):
        assert [name for name, _ in submitted] == ['c']
    elif state in (BackendStatus.FAILED, BackendStatus.CANCELLED):
        assert [name for name, _ in submitted] == ['b', 'c']


@pytest.mark.parametrize("state", [BackendStatus.SUBMITTED, BackendStatus.RUNNING])
def test_active_targets_are_not_duplicated_when_data_and_evidence_are_missing(chain, state):
    chain.cleanup()
    (chain.root / 'c.out').unlink()
    (chain.meta / 'manifest.json').unlink()
    statuses = {name: state for name in ['a', 'b', 'c']}
    assert not chain.reusable(statuses)
    assert chain.decisions(evidence=True, statuses=statuses)[1] == []


def test_missing_producerless_input_is_an_error_even_with_active_jobs(chain):
    (chain.root / 'x').unlink()
    with pytest.raises(UnresolvedInputError):
        chain.decisions(boundary=True, evidence=True,
                        statuses={'a': BackendStatus.RUNNING})


def test_failed_status_query_does_not_turn_into_unknown_success(chain):
    fs = CachedFilesystem()
    graph = Graph.from_targets(chain.targets, fs)

    def query_failed(target):
        raise RuntimeError('simulated scheduler query failure')

    with pytest.raises(RuntimeError, match='scheduler query failure'):
        schedule(graph.endpoints(), graph, fs, NoopSpecHashes(), query_failed,
                 lambda *args, **kwargs: pytest.fail('must not submit'))


def test_late_old_attempt_record_cannot_certify_retried_target(chain):
    previous_receipt = chain.receipt('b').read_text()
    chain.expected_attempts['b'] = 'attempt-2'
    chain.receipt('b').unlink()
    # Simulate a late attempt-1 writer after the new attempt has been selected.
    chain.receipt('b').write_text(previous_receipt)
    assert 'b' not in chain.valid_evidence()
    assert [name for name, _ in chain.decisions(evidence=True)[1]] == ['b', 'c']

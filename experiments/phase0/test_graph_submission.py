"""Phase 0 E3 and the queued-dependency part of E4.

Use installed gwf 2.1.1 Graph, scheduler, and TrackingBackend unchanged.
The scheduler service below is an in-memory simulation: no Slurm command,
target payload, container, or background process is started. Its readiness
rule models success-only dependencies; it does not verify Slurm behavior.
"""

from dataclasses import dataclass
import os
from pathlib import Path

import gwf
import pytest
from gwf.backends.base import BackendStatus, TrackingBackend
from gwf.core import (
    CachedFilesystem,
    CircularDependencyError,
    Graph,
    NoopSpecHashes,
    Status,
    Target,
    UnresolvedInputError,
    check_for_circular_dependencies,
)
from gwf.scheduling import schedule, should_run, submit_backend


@dataclass
class SimulatedJob:
    target_name: str
    dependencies: tuple[str, ...]
    state: BackendStatus = BackendStatus.SUBMITTED


class InMemorySchedulerOps:
    """Only the ops protocol used by the real TrackingBackend is simulated."""

    target_defaults = {}

    def __init__(self):
        self.jobs = {}
        self.submissions = []
        self.close_count = 0

    def submit_target(self, target, dependencies):
        # Dependencies must refer to jobs already accepted by this service.
        assert set(dependencies) <= self.jobs.keys()
        job_id = f"job-{len(self.jobs) + 1}"
        self.jobs[job_id] = SimulatedJob(target.name, tuple(dependencies))
        self.submissions.append(job_id)
        return job_id

    def get_job_states(self, tracked_jobs):
        return {
            job_id: self.jobs[job_id].state
            for job_id in tracked_jobs
            if job_id in self.jobs
        }

    def ready_job_ids(self):
        return {
            job_id
            for job_id, job in self.jobs.items()
            if job.state == BackendStatus.SUBMITTED
            and all(
                self.jobs[dependency].state == BackendStatus.COMPLETED
                for dependency in job.dependencies
            )
        }

    def start(self, job_id):
        assert job_id in self.ready_job_ids()
        self.jobs[job_id].state = BackendStatus.RUNNING

    def finish(self, job_id, state=BackendStatus.COMPLETED):
        assert state in (BackendStatus.COMPLETED, BackendStatus.FAILED)
        assert self.jobs[job_id].state == BackendStatus.RUNNING
        self.jobs[job_id].state = state

    def close(self):
        # Closing the submitting client does not execute any queued job.
        self.close_count += 1


@pytest.fixture(autouse=True)
def require_inspected_gwf_version():
    assert gwf.__version__ == "2.1.1"


def target(root, name, inputs=(), outputs=None):
    return Target(
        name=name,
        inputs=list(inputs),
        outputs=list(outputs if outputs is not None else [f"{name}.out"]),
        options={},
        working_dir=str(root),
        spec="true  # Not executed by these experiments.",
    )


def write_at(root, relative_path, timestamp):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("fixture\n")
    os.utime(path, (timestamp, timestamp))
    return path


def make_graph(targets):
    return Graph.from_targets(list(targets), CachedFilesystem())


def add_control_edges(graph, *, consumer, prerequisites):
    """Disposable fixture operation, not a proposed production graph adapter."""
    nodes = set(graph.targets.values())
    assert consumer in nodes
    assert set(prerequisites) <= nodes
    for prerequisite in prerequisites:
        graph.dependencies[consumer].add(prerequisite)
        graph.dependents[prerequisite].add(consumer)
    # gwf performs this check at construction, not automatically after mutation.
    check_for_circular_dependencies(graph.targets, graph.dependencies)
    assert_graph_consistent(graph)


def assert_graph_consistent(graph):
    nodes = set(graph.targets.values())
    expected_providers = {
        path: node for node in nodes for path in node.flattened_outputs()
    }
    assert graph.provides == expected_providers

    expected_reverse = {}
    for node, prerequisites in graph.dependencies.items():
        assert node in nodes
        assert prerequisites <= nodes
        for prerequisite in prerequisites:
            expected_reverse.setdefault(prerequisite, set()).add(node)
    # Do not create empty defaultdict entries: endpoints() checks reverse keys.
    assert dict(graph.dependents) == expected_reverse
    assert graph.endpoints() == nodes - expected_reverse.keys()

    expected_unresolved = set()
    for node in nodes:
        for path in node.flattened_inputs():
            if path in graph.provides:
                assert graph.provides[path] in graph.dependencies.get(node, set())
            else:
                expected_unresolved.add(path)
    assert graph.unresolved == expected_unresolved
    check_for_circular_dependencies(graph.targets, graph.dependencies)


def submit_once(root, graph, ops):
    """One real gwf scheduling pass, including its normal tracking persistence."""
    (root / ".gwf").mkdir(exist_ok=True)
    with TrackingBackend(str(root), "phase0-memory", ops) as backend:
        hashes = NoopSpecHashes()

        def submit(target, dependencies):
            submit_backend(target, dependencies, backend, hashes)

        decisions = schedule(
            graph.endpoints(),
            graph,
            CachedFilesystem(),
            hashes,
            status_func=backend.status,
            submit_func=submit,
        )
        job_ids = {node.name: backend.get_tracked_id(node) for node in graph}
    return {node.name: state for node, state in decisions.items()}, job_ids


@pytest.mark.parametrize("late_state", [BackendStatus.COMPLETED, BackendStatus.FAILED])
def test_static_fork_join_submits_every_job_before_simulated_execution(
    tmp_path, late_state
):
    seed = target(tmp_path, "seed")
    fast = target(tmp_path, "fast", ["seed.out"])
    slow = target(tmp_path, "slow", ["seed.out"])
    consumer = target(tmp_path, "consumer", ["fast.out"])
    graph = make_graph([seed, fast, slow, consumer])
    assert graph.endpoints() == {slow, consumer}
    add_control_edges(graph, consumer=consumer, prerequisites=[fast, slow])
    assert graph.endpoints() == {consumer}
    assert consumer.inputs == ["fast.out"]

    ops = InMemorySchedulerOps()
    decisions, ids = submit_once(tmp_path, graph, ops)

    assert decisions == {node.name: Status.SHOULDRUN for node in graph}
    assert len(ops.jobs) == len(graph) == 4  # No collector or finalizer target.
    assert {job.target_name for job in ops.jobs.values()} == set(graph.targets)
    assert ops.jobs[ids["seed"]].dependencies == ()
    assert ops.jobs[ids["fast"]].dependencies == (ids["seed"],)
    assert ops.jobs[ids["slow"]].dependencies == (ids["seed"],)
    assert set(ops.jobs[ids["consumer"]].dependencies) == {
        ids["fast"], ids["slow"]
    }
    assert all(job.state == BackendStatus.SUBMITTED for job in ops.jobs.values())
    assert ops.close_count == 1  # The submitting backend is already closed.

    # No further gwf scheduling call occurs while the simulated queue progresses.
    ops.start(ids["seed"])
    ops.finish(ids["seed"])
    assert ops.ready_job_ids() == {ids["fast"], ids["slow"]}
    ops.start(ids["fast"])
    ops.start(ids["slow"])
    ops.finish(ids["fast"])
    assert ids["consumer"] not in ops.ready_job_ids()
    ops.finish(ids["slow"], late_state)
    assert (ids["consumer"] in ops.ready_job_ids()) is (
        late_state == BackendStatus.COMPLETED
    )
    assert len(ops.submissions) == 4


def test_control_edge_does_not_add_unconsumed_file_to_freshness(tmp_path):
    # The unrelated slow result is newer than the consumer result.
    write_at(tmp_path, "fast.out", 10)
    write_at(tmp_path, "slow.out", 20)
    write_at(tmp_path, "consumer.out", 15)
    fast = target(tmp_path, "fast")
    slow = target(tmp_path, "slow")
    consumer = target(tmp_path, "consumer", ["fast.out"])
    graph = make_graph([fast, slow, consumer])
    before = tuple(consumer.flattened_inputs()), tuple(consumer.flattened_outputs())
    add_control_edges(graph, consumer=consumer, prerequisites=[slow])

    assert before == (
        tuple(consumer.flattened_inputs()), tuple(consumer.flattened_outputs())
    )
    assert not should_run(consumer, CachedFilesystem(), NoopSpecHashes())
    ops = InMemorySchedulerOps()
    decisions, _ = submit_once(tmp_path, graph, ops)
    assert set(decisions.values()) == {Status.COMPLETED}
    assert ops.jobs == {}

    with_artificial_input = target(
        tmp_path, "consumer", ["fast.out", "slow.out"]
    )
    assert should_run(with_artificial_input, CachedFilesystem(), NoopSpecHashes())


@pytest.mark.parametrize("running_name", ["fast", "slow"])
def test_new_consumer_uses_existing_active_ids_with_missing_evidence(
    tmp_path, running_name
):
    fast = target(tmp_path, "fast", outputs=["fast.out", "fast.receipt"])
    slow = target(tmp_path, "slow", outputs=["slow.out", "slow.receipt"])
    ops = InMemorySchedulerOps()
    _, first_ids = submit_once(tmp_path, make_graph([fast, slow]), ops)
    ops.start(first_ids[running_name])
    assert all(not Path(path).exists() for node in (fast, slow)
               for path in node.flattened_outputs())

    consumer = target(tmp_path, "consumer", ["fast.out"])
    graph = make_graph([fast, slow, consumer])
    add_control_edges(graph, consumer=consumer, prerequisites=[slow])
    decisions, second_ids = submit_once(tmp_path, graph, ops)

    assert second_ids["fast"] == first_ids["fast"]
    assert second_ids["slow"] == first_ids["slow"]
    assert decisions[running_name] == Status.RUNNING
    other = "slow" if running_name == "fast" else "fast"
    assert decisions[other] == Status.SUBMITTED
    assert decisions["consumer"] == Status.SHOULDRUN
    assert len(ops.jobs) == 3
    assert set(ops.jobs[second_ids["consumer"]].dependencies) == set(first_ids.values())


def test_rebuilding_pruned_graph_uses_real_retained_input_without_stale_edges(tmp_path):
    fast = target(tmp_path, "fast")
    slow = target(tmp_path, "slow")
    consumer = target(tmp_path, "consumer", ["fast.out"])
    original = make_graph([fast, slow, consumer])
    add_control_edges(original, consumer=consumer, prerequisites=[slow])
    retained = write_at(tmp_path, "fast.out", 10)
    write_at(tmp_path, "slow.out", 20)

    # Boundary eligibility is assumed here; E1/E2 separately test its evaluator.
    pruned = make_graph([consumer])
    assert_graph_consistent(pruned)
    assert pruned.endpoints() == {consumer}
    assert pruned.unresolved == {str(retained)}
    assert set(pruned.provides.values()) == {consumer}
    assert pruned.dependencies.get(consumer, set()) == set()
    assert original.dependencies[consumer] == {fast, slow}
    assert_graph_consistent(original)

    ops = InMemorySchedulerOps()
    decisions, ids = submit_once(tmp_path, pruned, ops)
    assert decisions == {"consumer": Status.SHOULDRUN}
    assert len(ops.jobs) == 1
    assert ops.jobs[ids["consumer"]].dependencies == ()


def test_pruning_is_invalid_if_required_externalized_output_is_missing(tmp_path):
    consumer = target(tmp_path, "consumer", ["fast.out"])
    with pytest.raises(UnresolvedInputError, match="fast.out"):
        make_graph([consumer])


def test_control_edge_cycle_requires_explicit_revalidation(tmp_path):
    producer = target(tmp_path, "producer")
    consumer = target(tmp_path, "consumer", ["producer.out"])
    graph = make_graph([producer, consumer])
    with pytest.raises(CircularDependencyError):
        add_control_edges(graph, consumer=producer, prerequisites=[consumer])


def test_missing_receipt_needs_a_declared_producer_to_form_a_file_edge(tmp_path):
    producer = target(tmp_path, "producer")
    consumer = target(tmp_path, "consumer", ["producer.receipt"])
    with pytest.raises(UnresolvedInputError, match="producer.receipt"):
        make_graph([producer, consumer])

    producer.outputs.append("producer.receipt")
    graph = make_graph([producer, consumer])
    assert_graph_consistent(graph)
    assert graph.provides[str(tmp_path / "producer.receipt")] is producer
    assert graph.dependencies[consumer] == {producer}
    ops = InMemorySchedulerOps()
    decisions, ids = submit_once(tmp_path, graph, ops)
    assert set(decisions.values()) == {Status.SHOULDRUN}
    assert len(ops.jobs) == 2  # Receipt is produced inside the existing target.
    assert ops.jobs[ids["consumer"]].dependencies == (ids["producer"],)
    # This proves file-edge construction only. Receipt timestamps in data inputs
    # or outputs are NOT the proposed freshness integration; see E1/E2.


def test_stock_gwf_keeps_queued_consumer_bound_to_obsolete_failed_job(tmp_path):
    upstream = target(tmp_path, "upstream")
    consumer = target(tmp_path, "consumer", ["upstream.out"])
    report = target(tmp_path, "report", ["consumer.out"])
    graph = make_graph([upstream, consumer, report])
    ops = InMemorySchedulerOps()
    _, old_ids = submit_once(tmp_path, graph, ops)
    ops.start(old_ids["upstream"])
    ops.finish(old_ids["upstream"], BackendStatus.FAILED)

    decisions, retry_ids = submit_once(tmp_path, graph, ops)

    assert decisions == {
        "upstream": Status.FAILED,
        "consumer": Status.SUBMITTED,
        "report": Status.SUBMITTED,
    }
    assert retry_ids["upstream"] != old_ids["upstream"]
    assert retry_ids["consumer"] == old_ids["consumer"]
    assert retry_ids["report"] == old_ids["report"]
    assert len(ops.jobs) == 4  # Only the failed upstream was resubmitted.
    assert ops.jobs[retry_ids["consumer"]].dependencies == (old_ids["upstream"],)
    assert ops.jobs[retry_ids["report"]].dependencies == (old_ids["consumer"],)

    ops.start(retry_ids["upstream"])
    ops.finish(retry_ids["upstream"])
    assert retry_ids["consumer"] not in ops.ready_job_ids()
    assert retry_ids["report"] not in ops.ready_job_ids()
    # Passing this reproduction demonstrates that stock gwf does NOT satisfy
    # E4's obsolete-dependency repair criterion. No repair is implemented here.

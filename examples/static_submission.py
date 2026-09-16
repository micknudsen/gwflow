"""Real host commands with a fork and two independent producer terminals."""
from dataclasses import replace
from shlex import quote

from gwflow import MainPipeline, OutputRef, Subpipeline, Target, Use
from examples.one_file import copy_file


def build(ctx):
    seed, early, branch, late = [ctx.path(name) for name in ("seed", "early.txt", "branch", "late.txt")]
    def copy(name, source, output):
        return Target(name, f"cp {quote(source)} {quote(output)}", (source,), (output,))
    return [copy("seed", ctx.inputs["source"], seed), copy("early", seed, early),
            copy("branch", seed, branch), copy("late", branch, late)]


producer = Subpipeline("examples.static_producer", "1", {"source": "file"},
                       {"early": "early.txt", "late": "late.txt"}, build)
main = MainPipeline("examples.static_submission", "1", uses={
    "producer": Use(producer, {"source": "reads.txt"}),
    "consumer": Use(copy_file, {"source": OutputRef("producer", "early")}),
})
producer_only = replace(main, uses={"producer": main.uses["producer"]})


def failing_build(ctx):
    return [replace(target, command=target.command + "; exit 31") if target.name == "late" else target for target in build(ctx)]


failure = replace(main, uses={**main.uses,
    "producer": Use(replace(producer, version="late-failure", build=failing_build), {"source": "reads.txt"}),
})

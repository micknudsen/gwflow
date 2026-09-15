"""A complete ordered dataset is supplied before planning."""
import shlex
from gwflow import MainPipeline, Subpipeline, Target


def concatenate(ctx):
    output = ctx.path("combined.txt")
    command = "cat " + " ".join(shlex.quote(p) for p in ctx.inputs["reads"]) + " > " + shlex.quote(output)
    if not ctx.inputs["reads"]:
        command = ": > " + shlex.quote(output)
    return [Target("combine", command, tuple(ctx.inputs["reads"]), (output,))]


main = MainPipeline("examples.list", "1", Subpipeline(
    "examples.concatenate", "1", {"reads": "files"}, {"combined": "combined.txt"}, concatenate))

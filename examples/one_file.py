"""An ordinary importable definition; no input files are needed to plan it."""
import shlex
from gwflow import MainPipeline, Subpipeline, Target


def copy(ctx):
    output = ctx.path("copy.txt")
    return [Target("copy", f"cp {shlex.quote(ctx.inputs['source'])} {shlex.quote(output)}",
                   inputs=(ctx.inputs["source"],), outputs=(output,))]


copy_file = Subpipeline("examples.copy", "1", {"source": "file"}, {"copy": "copy.txt"}, copy,
                        package={"name": "gwflow-examples", "version": "0.1.dev0"})
main = MainPipeline("examples.one", "1", copy_file)

from dataclasses import replace
import shlex
from gwflow import MainPipeline, Subpipeline, Target


def describe(ctx):
    output = ctx.path("sample.txt")
    text = f"sample={ctx.inputs['sample']}, threshold={ctx.parameters['threshold']}"
    return [Target("describe", f"printf %s {shlex.quote(text)} > {shlex.quote(output)}", outputs=(output,))]


sub = Subpipeline("examples.describe", "1", {"sample": "data"}, {"description": "sample.txt"},
                  describe, parameters={"threshold": 5})
main = MainPipeline("examples.data", "1", sub)
revised = replace(main, subpipeline=replace(sub, version="2", parameters={"threshold": 10}))

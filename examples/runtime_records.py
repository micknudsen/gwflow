"""Definitions used to demonstrate visible historical declaration checks."""
from dataclasses import replace

from gwflow import MainPipeline, Subpipeline, Target


def build(ctx):
    return [Target("copy", f"cp {ctx.inputs['source']} {ctx.path('copy.txt')}", inputs=(ctx.inputs["source"],), outputs=(ctx.path("copy.txt"),))]


def whitespace_changed(ctx):
    return [Target("copy", f"cp {ctx.inputs['source']} {ctx.path('copy.txt')} ", inputs=(ctx.inputs["source"],), outputs=(ctx.path("copy.txt"),))]


sub = Subpipeline("examples.runtime_record", "1", {"source": "file"}, {"copy": "copy.txt"}, build)
main = MainPipeline("examples.runtime-record-demo", "1", sub)
changed = replace(main, subpipeline=replace(sub, build=whitespace_changed))

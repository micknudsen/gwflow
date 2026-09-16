"""Definitions used to demonstrate visible historical declaration checks."""
from dataclasses import replace

from gwflow import MainPipeline, Subpipeline, Target


def build(ctx):
    return [Target("copy", f"cp {ctx.inputs['source']} {ctx.path('copy.txt')}", inputs=(ctx.inputs["source"],), outputs=(ctx.path("copy.txt"),))]


def whitespace_changed(ctx):
    return [Target("copy", f"cp {ctx.inputs['source']} {ctx.path('copy.txt')} ", inputs=(ctx.inputs["source"],), outputs=(ctx.path("copy.txt"),))]


def target_renamed(ctx):
    return [replace(target, name="renamed") for target in build(ctx)]


def resources_changed(ctx):
    return [replace(target, resources={"memory_mb": 4096}) for target in build(ctx)]


sub = Subpipeline("examples.runtime_record", "1", {"source": "file"}, {"copy": "copy.txt"}, build)
main = MainPipeline("examples.runtime-record-demo", "1", sub)
changed = replace(main, subpipeline=replace(sub, build=whitespace_changed))
renamed = replace(main, subpipeline=replace(sub, build=target_renamed))
operational = replace(main, version="2", package={"source": "different-main-package"},
                      subpipeline=replace(sub, package={"source": "different-subpipeline-package"}, build=resources_changed))
boolean_parameter = replace(main, subpipeline=replace(sub, parameters={"mode": True}))
integer_parameter = replace(main, subpipeline=replace(sub, parameters={"mode": 1}))
float_parameter = replace(main, subpipeline=replace(sub, parameters={"mode": 1.0}))

from dataclasses import replace
from gwflow import MainPipeline, Subpipeline, Target


def fork_join(ctx):
    a, b, c, d = [ctx.path(p) for p in ("a", "b", "c", "final")]
    return [Target("a", "produce a", (ctx.inputs["source"],), (a,)),
            Target("b", "consume a", (a,), (b,)), Target("c", "consume a", (a,), (c,)),
            Target("d", "join b c", (b, c), (d,))]


def parallel(ctx):
    return [Target("fast", "produce fast", (ctx.inputs["source"],), (ctx.path("fast"),)),
            Target("slow", "produce slow", (), (ctx.path("slow"),))]


def cyclic(ctx):
    return [Target("a", "a", (ctx.path("b"),), (ctx.path("a"),)),
            Target("b", "b", (ctx.path("a"),), (ctx.path("b"),))]


def ambiguous(ctx):
    return [Target("a", "a", outputs=(ctx.path("x"),)), Target("b", "b", outputs=(ctx.path("x"),))]


def outputless(ctx):
    return [Target("notify", "describe an external effect")]


main = MainPipeline("examples.graph", "1", Subpipeline("examples.graph", "1", {"source": "file"}, {"result": "final"}, fork_join))
parallel_main = replace(main, subpipeline=replace(main.subpipeline, version="parallel", outputs={"fast": "fast", "slow": "slow"}, build=parallel))
cycle = replace(main, subpipeline=replace(main.subpipeline, version="cycle", outputs={}, build=cyclic))
duplicate = replace(main, subpipeline=replace(main.subpipeline, version="duplicate", outputs={}, build=ambiguous))
always = replace(main, subpipeline=replace(main.subpipeline, version="always", outputs={}, build=outputless))

from gwflow import MainPipeline, OutputRef, Subpipeline, Target, Use
from .internal_graph import main as fork, parallel_main
from .one_file import copy_file

main = MainPipeline("examples.whole", "1", uses={
    "producer": Use(parallel_main.subpipeline, {"source": "reads.txt"}),
    "consumer": Use(copy_file, {"source": OutputRef("producer", "fast")}),
})


def combine(ctx):
    return [Target("combine", "combine two upstream files", tuple(ctx.inputs.values()), (ctx.path("combined"),))]


multiple = MainPipeline("examples.multiple", "1", uses={
    **main.uses,
    "fork": Use(fork.subpipeline, {"source": "other.txt"}),
    "consumer": Use(Subpipeline("examples.two_producers", "1", {"fast": "file", "joined": "file"}, {"combined": "combined"}, combine),
                    {"fast": OutputRef("producer", "fast"), "joined": OutputRef("fork", "result")}),
})

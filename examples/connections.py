from dataclasses import replace
from gwflow import MainPipeline, OutputRef, Use
from .one_file import copy_file
from .internal_graph import main as graph

producer = graph.subpipeline
main = MainPipeline("examples.connected", "1", uses={
    "producer": Use(producer, {"source": "reads.txt"}),
    "consumer": Use(copy_file, {"source": OutputRef("producer", "result")}),
    "report": Use(copy_file, {"source": OutputRef("consumer", "copy")}),
    "independent": Use(copy_file, {"source": "other.txt"}),
})
revised = replace(main, uses={**main.uses, "producer": Use(replace(producer, version="2"), {"source": "reads.txt"})})
private = replace(main, uses={**main.uses, "consumer": Use(copy_file, {"source": OutputRef("producer", "a")})})
exposed = replace(private, uses={**private.uses, "producer": Use(replace(producer, version="3", outputs={"result": "final", "a": "a"}), {"source": "reads.txt"})})

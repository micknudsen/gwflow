"""Real payload composition for main-only and upstream-version recovery checks."""
from dataclasses import replace

from gwflow import MainPipeline, OutputRef, Use
from examples.one_file import copy_file
from examples.runtime_evaluation import main as fork


main = MainPipeline("examples.recovery_versions", "1", uses={
    "producer": Use(fork.subpipeline, {"source": "reads.txt", "other": "other.txt"}),
    "consumer": Use(copy_file, {"source": OutputRef("producer", "final")}),
    "independent": Use(copy_file, {"source": "unrelated.txt"}),
})
main_changed = replace(main, version="2")
upstream_changed = replace(main, uses={**main.uses,
    "producer": Use(replace(fork.subpipeline, version="2"), {"source": "reads.txt", "other": "other.txt"}),
})

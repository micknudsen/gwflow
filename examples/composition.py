from dataclasses import replace
from gwflow import DefinitionRef, MainPipeline, Use
from .one_file import copy_file
from .small_data import sub as reporting

main = MainPipeline("examples.composition", "1", uses={
    "sample_a": Use(DefinitionRef("examples.one_file:copy_file", "examples.copy", "1"), {"source": "a.txt"}),
    "sample_b": Use(copy_file, {"source": "b.txt"}),
    "report": Use(reporting, {"sample": "report"}),
})
main_only = replace(main, version="2")
report_changed = replace(main, version="2", uses={**main.uses, "report": Use(replace(reporting, version="2"), {"sample": "report"})})
repeated = replace(main, uses={**main.uses, "again": Use(copy_file, {"source": "a.txt"})})
unavailable = replace(main, uses={"sample": Use(DefinitionRef("examples.one_file:copy_file", "examples.copy", "99"), {"source": "a"})})

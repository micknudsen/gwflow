"""Run with python -m examples.identity_demo; never reads or creates payloads."""
from dataclasses import replace
from gwflow import plan
from .one_file import main


def show(label, definition, source):
    c = plan(definition, {"source": source}, project="/tmp/gwflow-demo")["computations"][0]
    print(label, c["identity"], c["result_dir"])


if __name__ == "__main__":
    show("original", main, "reads.txt")
    show("repeat", main, "reads.txt")
    show("main-version", replace(main, version="2"), "reads.txt")
    show("new-binding", main, "other.txt")
    show("sub-version", replace(main, subpipeline=replace(main.subpipeline, version="2")), "reads.txt")

"""Paired identity explanations and an outputless target example."""
from dataclasses import replace
from gwflow import plan
from .connections import main, revised as upstream_changed
from .internal_graph import always as outputless

main_changed = replace(main, version="main-only-2")

if __name__ == "__main__":
    for label, definition, bindings in [("original", main, {}), ("main-only", main_changed, {}),
                                        ("upstream-changed", upstream_changed, {}), ("outputless", outputless, {"source": "reads.txt"})]:
        result = plan(definition, bindings, project="/tmp/gwflow-demo")
        print(label)
        for name, occurrence in sorted(result["main"]["occurrences"].items()):
            comp = next(c for c in result["computations"] if c["identity"] == occurrence["identity"])
            explanation = comp["explanation"]
            print(name, comp["identity"], explanation["prospective_reuse"]["outcome"])
            print("constraints:", [c["code"] for c in explanation["constraints"]])
            print("unevaluated:", [c["code"] for c in explanation["prospective_reuse"]["conditions"]])

"""Mixed planning declarations and a standalone manifest validation demo."""
from copy import deepcopy
from gwflow import LocalImage, MainPipeline, OutputRef, PlanError, RegistryImage, Subpipeline, Target, Use, manifest, plan, validate_manifest
from .one_file import copy_file


def build(ctx):
    return [Target("fast", f"describe {ctx.inputs['sample']} with threshold {ctx.parameters['threshold']}",
                   tuple(ctx.inputs["reads"]), (ctx.path("fast"),), {"memory_mb": 1024}, image=LocalImage("images/local.sif")),
            Target("slow", "describe slow branch", outputs=(ctx.path("slow"),), image=RegistryImage("docker://registry.example/tool:1")),
            Target("host", "describe host branch", outputs=(ctx.path("host"),))]


main = MainPipeline("examples.manifests", "1", uses={
    "producer": Use(Subpipeline("examples.manifest_producer", "1", {"reads": "files", "sample": "data"}, {"fast": "fast"}, build,
                                package={"name": "examples", "version": "0.1.dev0"}, parameters={"threshold": 5}),
                    {"reads": ["a", "b"], "sample": {"id": "sample-a"}}),
    "consumer": Use(copy_file, {"source": OutputRef("producer", "fast")}),
})


if __name__ == "__main__":
    result = plan(main, project="/tmp/gwflow-demo")
    for comp in result["computations"]:
        record = manifest(result, comp["identity"])
        validate_manifest(record)
        print(record["kind"], record["schema_version"], comp["definition"]["name"], len(comp["targets"]), record["runtime_evaluation"])
        broken = deepcopy(record)
        broken["schema_version"] = 999
        try:
            validate_manifest(broken)
        except PlanError as exc:
            print(exc)

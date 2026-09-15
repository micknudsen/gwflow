from dataclasses import replace
from gwflow import LocalImage, MainPipeline, RegistryImage, Subpipeline, Target


def build(ctx):
    return [Target("local", "tool in local image", outputs=(ctx.path("local.txt"),), image=LocalImage("images/tool.sif")),
            Target("registry", "tool in registry image", outputs=(ctx.path("remote.txt"),), image=RegistryImage("docker://registry.example/tool:1")),
            Target("host", "tool in prepared host", outputs=(ctx.path("host.txt"),))]


def changed(ctx):
    return [replace(t, image=RegistryImage("docker://registry.example/tool:2")) if t.name == "registry" else t for t in build(ctx)]


sub = Subpipeline("examples.environments", "1", {}, {"local": "local.txt", "remote": "remote.txt", "host": "host.txt"}, build)
main = MainPipeline("examples.images", "1", sub)
revised = replace(main, subpipeline=replace(sub, version="2", build=changed))

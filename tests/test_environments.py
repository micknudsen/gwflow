from dataclasses import replace
import json
from pathlib import Path
import pytest
from gwflow import LocalImage, RegistryImage, PlanError, plan
from examples.target_images import main, revised, build
from test_planner import cli


def test_per_target_declarations_without_images_or_runtime(tmp_path):
    c = plan(main, project=tmp_path)["computations"][0]
    targets = {t["name"]: t for t in c["targets"]}
    assert targets["host"]["environment"] == {"kind": "host", "declaration": None}
    assert targets["local"]["environment"] == {"kind": "local-sif", "declaration": "images/tool.sif", "path": str(tmp_path / "images/tool.sif")}
    assert targets["registry"]["environment"] == {"kind": "registry", "declaration": "docker://registry.example/tool:1"}
    assert plan(revised, project=tmp_path)["computations"][0]["identity"] != c["identity"]
    assert list(tmp_path.iterdir()) == []
    with pytest.raises(TypeError):
        replace(main.subpipeline, image=LocalImage("inherit.sif"))


@pytest.mark.parametrize("image", ["image.sif", LocalImage("image.txt"), LocalImage("docker://image.sif"), RegistryImage("https://example/image"), RegistryImage("docker://"), RegistryImage("docker://image with spaces"), RegistryImage(None)])
def test_invalid_declarations_name_target(tmp_path, image):
    def invalid(ctx):
        return [replace(t, image=image) if t.name == "local" else t for t in build(ctx)]
    with pytest.raises(PlanError, match="examples.environments/local.*image"):
        plan(replace(main, subpipeline=replace(main.subpipeline, build=invalid)), project=tmp_path)


def test_absolute_path_and_oras(tmp_path):
    def images(ctx):
        return [replace(t, image=LocalImage(Path("/missing/tool.sif"))) if t.name == "local" else replace(t, image=RegistryImage("oras://registry.example/tool:1")) for t in build(ctx)]
    c = plan(replace(main, subpipeline=replace(main.subpipeline, build=images)), project=tmp_path)["computations"][0]
    assert next(t for t in c["targets"] if t["name"] == "local")["environment"]["path"] == "/missing/tool.sif"


def test_images_command(tmp_path):
    result = cli(tmp_path, "examples.target_images:main")
    assert result.returncode == 0
    assert {t["environment"]["kind"] for t in json.loads(result.stdout)["computations"][0]["targets"]} == {"host", "local-sif", "registry"}

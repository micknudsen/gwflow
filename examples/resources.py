from dataclasses import replace
from .one_file import copy, copy_file, main as original


def requested(ctx):
    return [replace(copy(ctx)[0], resources={"memory_mb": 1024, "walltime_seconds": 60})]


main = replace(original, subpipeline=replace(copy_file, build=requested))

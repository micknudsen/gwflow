"""Identity facts and prospective runtime conditions, with no state evaluator."""
from copy import deepcopy


def explain(result):
    for computation in result["computations"]:
        descriptor = computation["descriptor"]
        facts = [
            {"code": "definition-identity", "basis": deepcopy(descriptor["definition"]),
             "meaning": "The explicit immutable subpipeline name/version participates in identity."},
            {"code": "named-binding-identity", "basis": deepcopy(descriptor["bindings"]),
             "meaning": "Named typed data bindings participate in identity; file contents, sizes and timestamps do not."},
            {"code": "upstream-identity", "basis": deepcopy(computation["connections"]),
             "meaning": "Each connected producer identity and retained-output name participates transitively; output bytes are not compared."},
            {"code": "provenance-only-versions", "basis": {
                "main": {k: deepcopy(result["main"][k]) for k in ("name", "version", "package")},
                "software": deepcopy(result["software"]),
                "definition_packages": {name: deepcopy(result["main"]["occurrences"][name]["definition"]["package"]) for name in computation["occurrences"]}},
             "meaning": "Main, compatible software, and definition-package releases do not salt computation identity."},
            {"code": "current-result-slot", "basis": {"identity": computation["identity"], "result_dir": computation["result_dir"]},
             "meaning": "This address identifies one current result slot. Matching identity, payload paths or a planning manifest does not establish completion or reuse."},
        ]
        conditions = [
            {"code": "required-completion-evidence", "evaluation": "not evaluated",
             "requirement": "Required compatible execution evidence must support successful completion of all required work."},
            {"code": "retained-output-validity", "evaluation": "not evaluated",
             "requirement": "All declared retained outputs must be present and valid."},
            {"code": "target-level-freshness", "evaluation": "not evaluated",
             "requirement": "Freshness follows actual target file dependencies and gwf existence/timestamp semantics, without pooled timestamps or content checksums."},
            {"code": "available-scheduler-state", "evaluation": "not evaluated",
             "requirement": "Available scheduler states retain precedence over evidence; no scheduler query was made."},
        ]
        constraints = [{"code": "whole-producer-completion", "basis": deepcopy(computation["completion_obligations"]),
                        "meaning": "Consumers require whole-producer completion, including independent terminal work, separately from their computational file inputs."}]
        outputless = [t["name"] for t in computation["targets"] if t["always_run"]]
        if outputless:
            constraints.append({"code": "outputless-always-run", "basis": outputless,
                                "meaning": "Outputless targets retain gwf always-run semantics; planning metadata cannot make them cacheable."})
        computation["explanation"] = {
            "identity_facts": facts, "constraints": constraints,
            "prospective_reuse": {"outcome": "undetermined", "conditions": conditions,
                                  "recovery": "A later evaluation may require recovery for missing outputs or required evidence. This plan has not established failure or selected jobs to submit."},
        }

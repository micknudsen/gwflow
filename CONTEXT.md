# gwflow

Language for composing versioned pipelines and reusing their completed work.

## Language

**Main pipeline**:
A versioned composition of subpipelines and the dependencies between them.
_Avoid_: Pipeline when the distinction from a subpipeline matters.

**Subpipeline**:
An independently versioned part of a main pipeline containing multiple internal steps and declaring inputs and outputs. It is the boundary at which successful completion and reuse are evaluated.
_Avoid_: Step when referring to a whole subpipeline.

**Internal step**:
A constituent operation within a subpipeline.
_Avoid_: Subpipeline when referring to one constituent operation.

**gwflow software version**:
The version of gwflow itself, distinct from the versions of the pipelines it runs.
_Avoid_: Pipeline version when referring to gwflow itself.

**Main pipeline version**:
The version of a main pipeline, reflecting its composition, including its constituent subpipelines and their versions.
_Avoid_: gwflow version when referring to a main pipeline.

**Subpipeline version**:
The version of an individual subpipeline, distinct from its containing main pipeline's version. A published version fixes its code, computational parameter values, declared output interface, and declared software-environment specification; input data may vary between uses.
_Avoid_: Pipeline version when the versioned entity would be ambiguous.

**Subpipeline definition**:
The versioned description of a subpipeline's internal steps, declared inputs and outputs, computational parameter values, and software-environment specification.
_Avoid_: Execution when referring to the reusable definition.

**Computational parameter**:
A setting that determines how a subpipeline processes its inputs, such as a filtering threshold. Its value belongs to the versioned subpipeline definition.
_Avoid_: Input data when referring to a processing setting.

**Input binding**:
The assignment of a particular file or data value to a named input of a subpipeline. Input bindings may vary while the subpipeline definition and its computational parameters stay fixed.
_Avoid_: Computational parameter when referring to dataset-specific input data.

**Bound computation**:
A particular versioned subpipeline definition applied to named input bindings. It is the unit whose completed result can be reused.
_Avoid_: Subpipeline version when referring to a definition applied to particular input data.

**Pipeline submission**:
A request to plan a main pipeline and submit the work it needs. It may include new work, completed bound computations, and already active work.
_Avoid_: Execution attempt when referring to the request for the main pipeline as a whole.

**Execution attempt**:
An individual attempt to execute an internal step for a bound computation. Retrying creates another execution attempt without necessarily changing the bound computation.
_Avoid_: Subpipeline version when referring to a retry of the same definition and inputs.

**Current attempt**:
The execution attempt currently selected for an internal step of a bound computation. Only evidence belonging to this attempt may support completion of that step.
_Avoid_: Latest receipt when referring to which attempt is eligible to establish completion.

**Result slot**:
The current retained result location for one bound computation. Rebuilding that computation can replace its result files without preserving a historical copy.
_Avoid_: Result history when referring to the current retained results alone.

**Retained output**:
A declared output kept after a subpipeline's internal intermediates are removed; its file may appear before the subpipeline completes. Data dependencies between subpipelines may consume only retained outputs, subject to whole-subpipeline completion.
_Avoid_: Intermediate when referring to an output in this public interface.

**Internal intermediate**:
A file used within a subpipeline that is outside its retained-output interface. Other subpipelines may not depend on it.
_Avoid_: Output without qualification when referring to a disposable internal file.

**Subpipeline completion**:
The successful finish of all required internal work, with all declared retained outputs present. A downstream subpipeline waits for each required upstream subpipeline to reach this point.
_Avoid_: File availability when referring to successful completion of a whole subpipeline.

**Completion evidence**:
Retained information used to establish successful completion of required subpipeline work, even after scheduler job history expires. It is evaluated together with available scheduler status and current result validity.
_Avoid_: Output existence when referring to proof of successful execution.

**Target image**:
The container image declared for an individual internal step. Steps within the same subpipeline may use different target images.
_Avoid_: Subpipeline image when referring to a shared execution environment for all its steps.

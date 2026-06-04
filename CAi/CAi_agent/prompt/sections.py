"""Concrete PromptSection implementations used by A1pro."""

from __future__ import annotations

from collections.abc import Iterable

from ..tools.registry import ToolRegistry
from .section import PromptSection

# ---------------------------------------------------------------------------
# Core
# ---------------------------------------------------------------------------

DEFAULT_DRUG_DISCOVERY_PERSONA = (
    "You are an Expert Computational Chemist and Lead AI Scientist in drug discovery."
)

CORE_INSTRUCTIONS = """\
INTERACTION MODES:
1. DIRECT RESPONSE — For questions, explanations, discussions, or planning,
   reply in plain text. No code needed.
2. CODE EXECUTION — When you need to compute, call tools, or process data,
   wrap the code in <execute>...</execute> tags and it will be run automatically.
   The output will appear in an <observation> block.
3. MIXED — You can combine text explanation with code in one response.

HOW TO EXECUTE CODE:

  Python (default — no attribute needed):
    <execute>
    print("hello")
    </execute>

  Bash shell:
    <execute lang="bash">
    echo "hello"
    ls -l
    </execute>

  R:
    <execute lang="r">
    library(dplyr)
    </execute>

  (Legacy syntax `#!BASH` / `#!R` on the first line is still recognised
  for backward compatibility, but `lang="..."` is preferred.)

CODE EXECUTION ENVIRONMENT STATE:
- Persistent Jupyter IPython Kernel: The Python execution environment runs as a continuous, independent background process.
- State Retention: Do NOT restart or re-initialize the environment for every <execute> block. Variables, library imports, and function definitions persist throughout the entire session. 
- For example, a DataFrame `df` or an RDKit molecule object created in one round can be directly accessed and used in subsequent rounds without re-importing or re-defining.

EXECUTION RULES:
- Validate SMILES with RDKit before passing to tools.
- Keep code simple. Break complex tasks into multiple rounds.
- If code fails, analyze the error before retrying.**If a task fails 3 consecutive times, STOP and ask the user for help.**
- CONTEXT ECONOMY (BASH): Never `cat` large files (PDBs, logs). Use `head`, `tail`, or `grep` to inspect. Redirect long tool outputs to `.log` files and review them selectively. 

PLANNING (for multi-step tasks):
- Start with a numbered plan inside an <execute lang="plan">...</execute> block.
- Update the plan after each step.
- Leverage the environment: Use Bash for heavy CLI tools/simulations, and Python (`pandas`, `matplotlib`, RDKit) to parse and visualize those Bash outputs.

COMPLETION:
- After code execution, you MUST provide a text summary of the results in
  the SAME response or in your next message. Never leave the final answer
  buried inside an <observation> block alone.
- When the task is fully done, end your final text summary with <done/>
- For simple questions, just answer directly (no <done/> needed).
- Do NOT end a turn with only <execute> and no follow-up text — always
  explain what the results mean after you see the observation.
  
COMPLETION & HONESTY:
- NEVER fabricate, guess, or hallucinate molecules, SMILES, data, or docking scores. 
- EVERY result you present in your final text MUST be strictly derived from the outputs of an <execute> observation.
- If you state that you applied a fix (e.g., "removed chirality"), you MUST write and execute the code to do so before generating the final answer.
- Be honest and tell the user the task failed. Do NOT pretend it succeeded.
  
"""



class CoreSection(PromptSection):
    """Persona + interaction protocol. Rendered for every agent."""

    def __init__(self, persona: str = DEFAULT_DRUG_DISCOVERY_PERSONA) -> None:
        self.persona = persona

    def render(self) -> str:
        return f"{self.persona}\n\n{CORE_INSTRUCTIONS}"


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

_TOOLS_HEADER = (
    "AVAILABLE TOOLS  (FALLBACK — use only if no utility fits)\n"
    + "=" * 50
    + "\nThese are low-level building blocks. Prefer UTILITY FUNCTIONS\n"
    + "above when one matches your task. Use these tools when:\n"
    + "  - No utility's 'Use when' covers your scenario, or\n"
    + "  - A utility failed and you need finer control.\n"
    + "\n⚠ IMPORT REQUIRED for these tools (NOT for utilities above):\n"
    + "    from CAi.toolkit import <name>\n"
)


class ToolsSection(PromptSection):
    """Render the non-hidden tools from a ToolRegistry."""

    def __init__(self, registry: ToolRegistry) -> None:
        self.registry = registry

    def render(self) -> str:
        visible = self.registry.all(include_hidden=False)
        if not visible:
            return ""

        lines = [_TOOLS_HEADER]
        for spec in visible:
            lines.append(f"▸ {spec.name}{spec.signature}")
            for dline in spec.short_doc.split("\n"):
                lines.append(f"    {dline}")
            lines.append("")
        return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Skills
# ---------------------------------------------------------------------------

_SKILLS_HEADER = """\
SKILLS — Standard Operating Procedures
==================================================

Skills are pre-validated workflows for recurring tasks.
When a user's request matches a skill, load it FIRST:

  from CAi.toolkit import get_skill_content
  workflow = get_skill_content('<skill_id>')
  print(workflow)

Then follow the workflow step-by-step.

Available skills:"""


class SkillsSection(PromptSection):
    """Render skill summaries from a SkillLoader, with optional exclusions.

    `loader` may be None — in that case the section renders to empty.
    """

    def __init__(
        self,
        loader,  # SkillLoader | None — kept untyped to avoid a hard import cycle
        excluded: Iterable[str] = (),
    ) -> None:
        self.loader = loader
        self.excluded = set(excluded)

    def render(self) -> str:
        if self.loader is None:
            return ""

        summaries = [
            s
            for s in self.loader.get_skill_summaries()
            if s["id"] not in self.excluded
        ]
        if not summaries:
            return ""

        lines = [_SKILLS_HEADER]
        for s in summaries:
            meta = s.get("metadata", {}) or {}
            lines.append("")
            lines.append(f"  • {s['id']} — {s['name']}")
            lines.append(f"    {s['description'][:120]}")
            if meta.get("use_cases"):
                lines.append(f"    Use cases: {meta['use_cases']}")
        return "\n".join(lines)

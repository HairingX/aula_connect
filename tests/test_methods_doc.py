"""The documentation of Aula's API methods says what the catalog says."""

from pathlib import Path

from aula_connect.methods import METHODS, WRONG_NAMES, AulaMethod, Parameter

DOC = Path(__file__).parent.parent / "docs" / "aula-methods.md"
MARK = "<!-- The tables below are checked against aula_connect.methods by the tests. -->"


def _parameters(parameters: tuple[Parameter, ...]) -> str:
    return ", ".join(f"`{p.name}`" + ("" if p.required else " (optional)") for p in parameters) or "-"


def _row(method: AulaMethod) -> str:
    return f"| `{method.name}` | {method.verb} | {method.kind} | {method.evidence} | {_parameters(method.query)} | {_parameters(method.body)} |"


def tables() -> str:
    """The tables the documentation holds after its mark."""
    methods = "\n".join(_row(method) for method in sorted(METHODS.values(), key=lambda m: m.name.lower()))
    wrong = "\n".join(f"| `{name}` | `{right}` |" for name, right in sorted(WRONG_NAMES.items()))
    return (
        f"{MARK}\n\n## Methods\n\n| Method | Verb | Kind | Evidence | Query | Body |\n|---|---|---|---|---|---|\n{methods}\n"
        f"\n## Names Aula has no method by\n\n| Name | The method meant |\n|---|---|\n{wrong}\n"
    )


def test_the_documentation_lists_every_method_and_wrong_name_as_the_catalog_does() -> None:
    text = DOC.read_text(encoding="utf-8")
    assert text[text.index(MARK):] == tables()

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path


SELECTED_SKILLS = (
    "nature-image2ppt",
    "nature-statistics",
    "nature-figure",
    "nature-paper-card",
    "nature-ref-verifier",
    "nature-writing",
    "nature-reviewer",
    "nature-polishing",
    "nature-reader",
    "nature-academic-search",
    "nature-paper2ppt",
    "research-explorer",
    "experiment-suite",
    "integrity-auditor",
    "mindmap-render",
)


@dataclass(slots=True)
class SkillInfo:
    name: str
    description: str
    path: str
    has_manifest: bool
    source_root: str


@dataclass(slots=True)
class LoadedSkill:
    info: SkillInfo
    prompt: str
    loaded_files: list[str]
    omitted_files: list[str]


def default_skill_root() -> Path:
    return Path(__file__).resolve().parents[1] / "third_party" / "nature_skills"


def default_skill_roots() -> tuple[Path, ...]:
    third_party = Path(__file__).resolve().parents[1] / "third_party"
    roots = [third_party / "nature_skills", third_party / "ai4s_skills"]
    return tuple(path for path in roots if path.is_dir())


def _frontmatter_value(text: str, key: str) -> str:
    match = re.search(rf"(?m)^{re.escape(key)}:\s*(.*)$", text)
    if not match:
        return ""
    value = match.group(1).strip().strip('"\'')
    if value in {">", ">-", "|", "|-"}:
        lines = []
        for line in text[match.end() :].splitlines()[1:]:
            if line.startswith((" ", "\t")):
                lines.append(line.strip())
            else:
                break
        return " ".join(lines)
    return value


class SkillCatalog:
    """Loads vendored skills as declarative workflow text, never as commands."""

    def __init__(self, root: Path | None = None):
        self.roots = ((root.resolve(),) if root else tuple(path.resolve() for path in default_skill_roots()))
        if not self.roots or any(not path.is_dir() for path in self.roots):
            raise ValueError("科研 Skills 目录不存在")
        self.root = self.roots[0]

    def discover(self, include_shared: bool = False) -> list[SkillInfo]:
        output: list[SkillInfo] = []
        seen: set[str] = set()
        for root in self.roots:
            for directory in sorted(root.iterdir(), key=lambda item: item.name):
                skill_file = directory / "SKILL.md"
                if not directory.is_dir() or not skill_file.is_file():
                    continue
                text = skill_file.read_text(encoding="utf-8")
                name = _frontmatter_value(text, "name") or directory.name
                if (not include_shared and name == "nature-shared") or name in seen:
                    continue
                seen.add(name)
                output.append(
                    SkillInfo(
                        name=name,
                        description=_frontmatter_value(text, "description"),
                        path=str(directory),
                        has_manifest=(directory / "manifest.yaml").is_file(),
                        source_root=str(root),
                    )
                )
        return sorted(output, key=lambda item: item.name)

    def get(self, name: str) -> SkillInfo:
        for info in self.discover(include_shared=True):
            if info.name == name:
                return info
        raise ValueError(f"Unknown skill: {name}")

    def to_dicts(self) -> list[dict[str, object]]:
        return [asdict(item) for item in self.discover()]

    @staticmethod
    def _safe_reference(root: Path, base: Path, relative: str) -> Path | None:
        candidate = (base / relative.strip().strip('"\'')).resolve()
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate if candidate.is_file() and candidate.suffix.lower() == ".md" else None

    def load(self, name: str, max_chars: int = 120_000) -> LoadedSkill:
        if max_chars < 4_000:
            raise ValueError("max_chars must be at least 4000")
        info = self.get(name)
        package = Path(info.path)
        root = Path(info.source_root)
        skill_file = package / "SKILL.md"
        manifest_file = package / "manifest.yaml"
        primary = skill_file.read_text(encoding="utf-8")
        manifest = manifest_file.read_text(encoding="utf-8") if manifest_file.is_file() else ""

        candidates: list[Path] = []
        reference_patterns = (
            re.compile(r"(?:path:\s*|-\s+)(\.\.?/[^\s#`]+\.md)"),
            re.compile(r"`((?:\.\.?/)?(?:references|static)/[^`#]+\.md)`"),
        )
        for source, base in ((primary, package), (manifest, package)):
            for reference_pattern in reference_patterns:
                for relative in reference_pattern.findall(source):
                    target = self._safe_reference(root, base, relative)
                    if target and target not in candidates:
                        candidates.append(target)

        sections = [f"## {skill_file.relative_to(root)}\n\n{primary}"]
        loaded = [str(skill_file.relative_to(root))]
        omitted: list[str] = []
        used = len(sections[0])
        if manifest:
            block = f"## {manifest_file.relative_to(root)}\n\n```yaml\n{manifest}\n```"
            if used + len(block) <= max_chars:
                sections.append(block)
                loaded.append(str(manifest_file.relative_to(root)))
                used += len(block)
            else:
                omitted.append(str(manifest_file.relative_to(root)))

        for target in candidates:
            relative = str(target.relative_to(root))
            content = target.read_text(encoding="utf-8")
            block = f"## {relative}\n\n{content}"
            if used + len(block) <= max_chars:
                sections.append(block)
                loaded.append(relative)
                used += len(block)
            else:
                omitted.append(relative)
        return LoadedSkill(info, "\n\n".join(sections), loaded, omitted)

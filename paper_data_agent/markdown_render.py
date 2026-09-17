from __future__ import annotations

from dataclasses import dataclass
import re


TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(?:\|\s*:?-{3,}:?\s*)+\|?\s*$")


@dataclass(frozen=True, slots=True)
class MarkdownBlock:
    kind: str
    text: str = ""
    level: int = 0
    rows: tuple[tuple[str, ...], ...] = ()


def clean_markdown_markers(text: str) -> str:
    """Remove display-only Markdown markers while keeping their content."""
    cleaned = re.sub(r"!\[([^]]*)\]\([^)]*\)", r"\1", text)
    cleaned = re.sub(r"\[([^]]+)\]\(([^)]+)\)", r"\1 (\2)", cleaned)
    cleaned = cleaned.replace("**", "").replace("__", "").replace("`", "")
    cleaned = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", cleaned)
    return cleaned


def inline_segments(text: str) -> list[tuple[str, str]]:
    """Return (text, style) pairs for a small safe Markdown subset."""
    pattern = re.compile(r"(\*\*.+?\*\*|__.+?__|`[^`]+`|(?<!\*)\*[^*]+\*(?!\*))")
    output: list[tuple[str, str]] = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            output.append((clean_markdown_markers(text[cursor : match.start()]), "body"))
        token = match.group(0)
        if token.startswith(("**", "__")):
            output.append((clean_markdown_markers(token[2:-2]), "bold"))
        elif token.startswith("`"):
            output.append((token[1:-1], "code"))
        else:
            output.append((clean_markdown_markers(token[1:-1]), "italic"))
        cursor = match.end()
    if cursor < len(text):
        output.append((clean_markdown_markers(text[cursor:]), "body"))
    return [(value, style) for value, style in output if value]


def _table_cells(line: str) -> tuple[str, ...]:
    value = line.strip()
    if value.startswith("|"):
        value = value[1:]
    if value.endswith("|"):
        value = value[:-1]
    return tuple(clean_markdown_markers(cell.replace(r"\|", "|")).strip() for cell in value.split("|"))


def parse_markdown_blocks(text: str) -> list[MarkdownBlock]:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    blocks: list[MarkdownBlock] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if re.match(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$", line):
            blocks.append(MarkdownBlock("horizontal_rule"))
            index += 1
            continue
        if index + 1 < len(lines) and "|" in line and TABLE_SEPARATOR.match(lines[index + 1]):
            rows = [_table_cells(line)]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_table_cells(lines[index]))
                index += 1
            width = max(len(row) for row in rows)
            normalized = tuple(row + ("",) * (width - len(row)) for row in rows)
            blocks.append(MarkdownBlock("table", rows=normalized))
            continue
        if line.strip().startswith("```"):
            language = line.strip()[3:].strip().lower()
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code_lines.append(lines[index])
                index += 1
            index += 1 if index < len(lines) else 0
            inner = "\n".join(code_lines)
            heading_count = sum(bool(re.match(r"^\s*#{1,6}\s+", item)) for item in code_lines)
            if language in {"markdown", "md"} or (not language and heading_count >= 2):
                blocks.extend(parse_markdown_blocks(inner))
            else:
                blocks.append(MarkdownBlock("code_block", text=inner))
            continue
        heading = re.match(r"^\s*(#{1,6})\s+(.+)$", line)
        if heading:
            blocks.append(MarkdownBlock("heading", clean_markdown_markers(heading.group(2)).strip(), len(heading.group(1))))
        else:
            bullet = re.match(r"^(\s*)[-+*]\s+(.+)$", line)
            quote = re.match(r"^\s*>\s?(.*)$", line)
            if bullet:
                blocks.append(MarkdownBlock("bullet", bullet.group(2), len(bullet.group(1)) // 2))
            elif quote:
                blocks.append(MarkdownBlock("quote", quote.group(1)))
            elif line.strip():
                blocks.append(MarkdownBlock("paragraph", line.strip()))
            else:
                blocks.append(MarkdownBlock("blank"))
        index += 1
    return blocks

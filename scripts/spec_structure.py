#!/usr/bin/env python3
"""Body structure checks for spec.md files, per SPEC-FORMAT.md.

Front matter is validated by validate_and_index.py. This module checks the
body: sections, sub-sections, numbered lists, references, links, and the
Table of Contents.

    python scripts/spec_structure.py specs/*/spec.md [--tree]

validate_and_index.py can call check(path) and fail on any "error" finding.
"""
import datetime
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import yaml

SECTIONS = {"1": "Problem Statement", "2": "Background & Context", "3": "Requirements",
            "4": "Open Questions", "5": "Non-Functional Requirements"}
FIXED_SUBS = {"2": {"2.1": "References", "2.2": "Key Constraints", "2.3": "Key Concepts", "2.4": "Out of Scope"}}
TOC = "Table of Contents"

H2_RE = re.compile(r"^(\d+)\. (.+)$")
H3_RE = re.compile(r"^(\d+)\.(\d+) (.+)$")
ITEM_RE = re.compile(r"^( *)(\d+)\. ")
BULLET_RE = re.compile(r"^\s*[-*+] ")
REF_RE = re.compile(r"\[\[([^\]]+)\]\]")
LINK_RE = re.compile(r"\]\(((?!https?:|mailto:|#)[^)#\s]+)(#[^)]*)?\)")
TOC_LINK_RE = re.compile(r"^\s*- \[([^\]]+)\]\(#([^)]+)\)")
FOLDER_RE = re.compile(r"^(SPEC-\d{4})-[a-z0-9-]+$")


def github_anchor(heading):
    return re.sub(r"[^\w\- ]", "", heading.lower()).replace(" ", "-")


@dataclass
class Finding:
    level: str
    code: str
    line: int
    msg: str

    def __str__(self):
        return f"{self.level:5} {self.code} line {self.line}: {self.msg}"


@dataclass
class Node:
    address: str
    line: int
    text: str
    children: list = field(default_factory=list)


@dataclass
class Part:
    """A section (number "3") or sub-section (number "3.2")."""
    number: str
    title: str
    line: int
    body: list = field(default_factory=list)
    description: list = field(default_factory=list)
    nodes: list = field(default_factory=list)
    subs: list = field(default_factory=list)

    @property
    def heading(self):
        return f"{self.number}. {self.title}" if "." not in self.number else f"{self.number} {self.title}"


def parse_list(part, err):
    """Split a part's body into description lines and numbered items.

    Items are addressed by position: part 3.2, item 1 is 3.2.1; its first nested
    item is 3.2.1.1. Returns every node (nested included), keyed by address.
    """
    nodes, fence, state = {}, False, "description"  # description -> list -> after
    stack = []  # (indent, node) for the current item and its ancestors
    for n, text in part.body:
        fence_line = text.startswith("```")
        code = fence or fence_line
        if fence_line:
            fence = not fence
        m = None if code else ITEM_RE.match(text)
        bullet = None if code else BULLET_RE.match(text)
        if bullet:
            err("L1", n, "Use a numbered list, not an unordered bullet")
        if state == "after":
            continue
        if m or bullet:
            # An unordered bullet is reported once and then counted as an item, so later numbers still check.
            indent = len(text) - len(text.lstrip(" "))
            num = int(m.group(2)) if m else None
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if indent and not stack:
                err("L2", n, "Indented item with no parent item")
                continue
            siblings = stack[-1][1].children if stack else part.nodes
            if num is not None and num != len(siblings) + 1:
                err("L2", n, f"Item numbered {num}, expected {len(siblings) + 1}")
            parent = stack[-1][1].address if stack else part.number
            node = Node(f"{parent}.{len(siblings) + 1}", n, text)
            siblings.append(node)
            nodes[node.address] = node
            stack.append((indent, node))
            state = "list"
        elif state == "list" and (code or not text.strip() or text[:1].isspace()):
            if stack:
                stack[-1][1].text += "\n" + text
        elif state == "list":
            err("L3", n, f"Content after the list in {part.number}; move it into the description or an item")
            state = "after"
        else:
            part.description.append(text)
    return nodes


def addresses(spec_path):
    """Every address in another spec, for resolving [[SPEC-NNNN:address]]."""
    try:
        return _parse(spec_path, resolve=False)[2]
    except OSError:
        return set()


def parse(spec_path):
    """Return (findings, outline) where outline is (title, parts, refs)."""
    findings, outline, _ = _parse(spec_path)
    return findings, outline


def _parse(spec_path, resolve=True):
    spec_path = Path(spec_path).resolve()
    folder = spec_path.parent
    lines = spec_path.read_text(encoding="utf-8").split("\n")
    out = []

    def err(code, line, msg, level="error"):
        out.append(Finding(level, code, line, msg))

    fm, body_start = {}, 0
    if lines and lines[0] == "---" and "---" in lines[1:]:
        body_start = lines.index("---", 1) + 1
        fm = yaml.safe_load("\n".join(lines[1:body_start - 1])) or {}
    m = FOLDER_RE.match(folder.name)
    if not m or str(fm.get("id")) != m.group(1):
        err("FM2", 1, f"id {fm.get('id')!r} does not match folder {folder.name!r}")

    # Pass 1: headings. H4 and deeper are content.
    titles, parts, toc, cur, fence = [], [], None, None, False
    for n, line in enumerate(lines[body_start:], start=body_start + 1):
        if line.startswith("```"):
            fence = not fence
        h = None if fence else re.match(r"^(#{1,3})\s+(.*)$", line)
        if not h:
            if cur is not None:
                cur.body.append((n, line))
            continue
        level, name = len(h.group(1)), h.group(2).strip()
        if level == 1:
            titles.append((n, name))
            cur = None
        elif level == 2:
            sm = H2_RE.match(name)
            if name == TOC:
                if parts:
                    err("S2", n, "Table of Contents must come before section 1")
                toc = cur = Part("toc", TOC, n)
            elif not sm:
                err("S2", n, f"Unknown section {name!r}")
                cur = None
            else:
                cur = Part(sm.group(1), sm.group(2), n)
                parts.append(cur)
        else:
            sm = H3_RE.match(name)
            parent = parts[-1] if parts and cur is not toc else None
            if not parent or not sm:
                err("S4", n, f"Sub-section {name!r} must be numbered under its section, like '3.1 Title'")
                cur = None
                continue
            cur = Part(f"{sm.group(1)}.{sm.group(2)}", sm.group(3), n)
            if sm.group(1) != parent.number:
                err("S4", n, f"{cur.number} is under section {parent.number}")
            parent.subs.append(cur)

    if not titles:
        err("S3", 0, "No H1")
    for n, _ in titles[1:]:
        err("S3", n, "More than one H1")
    title = titles[0][1] if titles else None
    if title != fm.get("title"):
        err("FM2", 1, f"H1 {title!r} does not match title {fm.get('title')!r}")

    # Section order, required headings, numbering.
    by_number = {p.number: p for p in parts}
    for want, p in enumerate(parts, start=1):
        if p.number != str(want):
            err("S2", p.line, f"Section {p.number!r} is out of order or skips a number (expected {want})")
        elif p.number in SECTIONS and p.title != SECTIONS[p.number]:
            err("S2", p.line, f"Section {p.number} must be titled {SECTIONS[p.number]!r}")
        fixed = FIXED_SUBS.get(p.number)
        for i, s in enumerate(p.subs, start=1):
            expected = f"{p.number}.{i}"
            if s.number != expected:
                err("S4", s.line, f"Sub-section {s.number} should be {expected}")
            elif fixed and s.number in fixed and s.title != fixed[s.number]:
                err("S2", s.line, f"Sub-section {s.number} must be titled {fixed[s.number]!r}")
        if fixed:
            have = {s.number for s in p.subs}
            for num, name in fixed.items():
                if num not in have:
                    err("S1", p.line, f"Missing sub-section {num} {name}")
    for num, name in SECTIONS.items():
        if num not in by_number:
            err("S1", 0, f"Missing section {num}. {name}")

    # Pass 2: numbered lists.
    targets = set()
    all_parts = [(p, None) for p in parts] + [(s, p) for p in parts for s in p.subs]
    for part, parent in all_parts:
        targets.add(part.number)
        targets.update(parse_list(part, err))
        if part.nodes and part.subs:
            err("L4", part.line, f"Section {part.number} has its own list and sub-sections; use one or the other")
        required = part.number in SECTIONS or part.number in FIXED_SUBS.get(parent.number if parent else "", {})
        has_text = part.nodes or part.subs or any(t.strip() for t in part.description)
        if required and not has_text:
            err("W1", part.line, f"{part.heading!r} is empty", "warn")

    # Table of Contents.
    if toc:
        entries = [(mm.group(1), mm.group(2)) for _, t in toc.body if (mm := TOC_LINK_RE.match(t))]
        headings = [x.heading for p in parts for x in [p] + p.subs]
        if [e[0] for e in entries] != headings:
            err("T1", toc.line, "Table of Contents doesn't match the headings", "warn")
        for text, anchor in entries:
            if anchor != github_anchor(text):
                err("T1", toc.line, f"TOC anchor #{anchor} should be #{github_anchor(text)}", "warn")

    # References and links.
    specs_root = folder.parent
    other_specs = {FOLDER_RE.match(p.name).group(1): p for p in specs_root.iterdir()
                   if p.is_dir() and FOLDER_RE.match(p.name)}
    linked, refs = set(), []
    for n, line in enumerate(lines, start=1):
        for ref in REF_RE.findall(line):
            refs.append((n, ref))
            spec_id, _, addr = ref.partition(":")
            if ref in targets or not resolve:
                continue
            if spec_id in other_specs and (not addr or addr in addresses(other_specs[spec_id] / "spec.md")):
                continue
            err("R1", n, f"Reference [[{ref}]] does not resolve")
        for target, _ in LINK_RE.findall(line):
            p = (folder / target).resolve()
            linked.add(p)
            if not p.exists():
                err("R2", n, f"Link target missing: {target}")
    for p in folder.rglob("*"):
        if p.is_file() and p.name not in ("spec.md", ".gitkeep", "spec-graph.json", "open-questions.md") and p.resolve() not in linked:
            err("A1", 0, f"File not linked from spec.md: {p.relative_to(folder)}", "warn")

    today = datetime.date.today().isoformat()
    for nd in (by_number["4"].nodes if "4" in by_number else []):
        due = re.search(r"due: (\d{4}-\d{2}-\d{2})", nd.text)
        if due and due.group(1) < today and "status: resolved" not in nd.text:
            err("W2", nd.line, f"{nd.address} is past due", "warn")

    return out, (title, parts, refs), targets


def check(spec_path):
    """Findings only, for validate_and_index.py."""
    return parse(spec_path)[0]


def print_tree(title, parts, refs):
    def items(nodes, depth):
        for nd in nodes:
            print(f"{'  ' * depth}{nd.address}")
            items(nd.children, depth + 1)

    print(f"# {title}")
    for p in parts:
        print(f"  {p.heading}")
        items(p.nodes, 3)
        for s in p.subs:
            print(f"    {s.heading}" + ("  (description)" if any(t.strip() for t in s.description) else ""))
            items(s.nodes, 3)
    print(f"\n{len(refs)} references")


def main(argv):
    failed = False
    for path in [a for a in argv if not a.startswith("--")]:
        findings, outline = parse(path)
        if "--tree" in argv:
            print_tree(*outline)
        errors = [f for f in findings if f.level == "error"]
        failed |= bool(errors)
        print(f"{path}: {'FAIL' if errors else 'OK'} ({len(errors)} errors, {len(findings) - len(errors)} warnings)")
        for f in findings:
            print(f"  {f}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

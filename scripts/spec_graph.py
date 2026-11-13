#!/usr/bin/env python3
"""spec_graph.py — build spec-graph.json for one spec folder (GRF-1 to GRF-17).

The single builder of the committed spec graph (GRF-12, GRF-14). Spec Studio
runs this same script with its bundled Python; its TypeScript graph
(packages/spec-core/src/graph.ts) produces byte-identical output (parity test).

What the file holds:
  - One 'block' node per block, under a hidden stable id (GRF-4) that
    survives edits, moves and renumbering. Ids live only here; after an
    outside edit or a pull they are re-anchored by content. A block that
    can't be matched confidently is never attached to a best guess: its id
    is retired and anything attached to it becomes an orphan (items 59, 60).
  - 'hierarchy', 'ref-block', 'ref-cross-spec' and 'file-link' edges.
  - 'reference-file' nodes for linked files and 'reference-part' nodes for
    their inner structure: headings in .md, top-level keys in JSON, elements
    in XML, CSV columns, Mermaid nodes (GRF-15). Parsing is best effort; a
    file that doesn't parse yet is one node marked notYetParsed (GRF-16).
    Deep links to parts that don't exist yet are warnings.
  - 'inferred' edges added by Claude with a confidence, checked against the
    text hashes of both ends and marked stale when either changes (GRF-6,
    GRF-10). On a merge every side's inferred relations are kept (GIT-7).
  - 'orphans', 'retired' ids and 'warnings'.

Output is deterministic: sorted keys, indent=2, newline at EOF. Never
hand-edit the file and never hand-merge it: on a conflict, rebuild it with
`--prior ours.json --prior theirs.json`.

Usage:
    python3 scripts/spec_graph.py specs/SPEC-0999-bulk-invoice-export/
    python3 scripts/spec_graph.py <folder> --add-inferred relations.json
    python3 scripts/spec_graph.py <folder> --prior ours.json --prior theirs.json
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

import yaml as pyyaml

# ---------------------------------------------------------------------------
# Constants matching spec_structure.py
# ---------------------------------------------------------------------------

H2_RE = re.compile(r'^(#{2})\s+(.*)$')
H3_RE = re.compile(r'^(#{3})\s+(.*)$')
H4_RE = re.compile(r'^(#{4,})\s+(.*)$')
H1_RE = re.compile(r'^#\s+(.*)$')
ITEM_RE = re.compile(r'^( *)(\d+)\. (.*)$')
UNORDERED_RE = re.compile(r'^( *)[-*+] (.*)$')
REF_RE = re.compile(r'\[\[([^\]]+)\]\]')
LINK_RE = re.compile(r'\[([^\]]*)\]\(([^)]+)\)')
IMAGE_RE = re.compile(r'!\[([^\]]*)\]\(([^)]+)\)')
YAML_FENCE_RE = re.compile(r'^---\s*$')
TOC_HEADING = 'Table of Contents'

# ---------------------------------------------------------------------------
# Stable ID — matches TypeScript stableId(specId, address, firstText[:64])
# ---------------------------------------------------------------------------

def stable_id(spec_id: str, address: str, first_text: str) -> str:
    """sha256(spec_id + ':' + address + ':' + first_text[:64])[:16]"""
    data = spec_id + ':' + address + ':' + first_text[:64]
    return hashlib.sha256(data.encode('utf-8')).hexdigest()[:16]


def file_node_id(spec_id: str, path: str) -> str:
    return 'file:' + spec_id + ':' + path


def cross_spec_node_id(spec_ref: str, addr: str | None) -> str:
    return 'xspec:' + spec_ref + (':' + addr if addr else '')


# ---------------------------------------------------------------------------
# Parse spec.md into a flat list of Block objects
# ---------------------------------------------------------------------------

class Block:
    __slots__ = (
        'id', 'kind', 'level', 'address', 'written_number',
        'label', 'source_start', 'source_end', 'children', 'refs',
        'parent_id',
    )

    def __init__(self, id_: str, kind: str, level: int, address: str,
                 label: str, source_start: int = 0, source_end: int = 0,
                 written_number: str | None = None):
        self.id = id_
        self.kind = kind
        self.level = level
        self.address = address
        self.label = label
        self.source_start = source_start
        self.source_end = source_end
        self.written_number = written_number
        self.children: list[Block] = []
        self.refs: list[dict] = []  # {kind, text, targetSpec?, targetAddress?, targetPath?}
        self.parent_id: str | None = None


def extract_inline_text(raw: str) -> str:
    """Strip markdown formatting to get plain text."""
    # Remove bold/italic
    text = re.sub(r'\*+([^*]+)\*+', r'\1', raw)
    # Remove [[refs]]
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    # Remove [link](url)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    # Remove code spans
    text = re.sub(r'`[^`]+`', '', text)
    return text.strip()


def extract_written_number(heading_text: str) -> str | None:
    """For '1. Problem Statement' → '1', '2.1 References' → '2.1'."""
    m = re.match(r'^(\d+(?:\.\d+)*)[. ]', heading_text)
    return m.group(1) if m else None


def extract_label(raw: str) -> str:
    """Extract label from raw markdown text (first 50 chars of plain text)."""
    # Check for bold lead-in: **text:** or **text**
    m = re.match(r'^\*\*([^*]+)\*\*', raw)
    if m:
        return m.group(1).strip()
    return extract_inline_text(raw)[:50]


def prose_label(raw: str) -> str:
    """Label of free text above the first H2 or after a list (mirrors parse.ts proseLabel)."""
    text = ' '.join(l.strip() for l in raw.split('\n') if l.strip())
    m = re.match(r'^\*\*([^*]+)\*\*', text)
    if m:
        return m.group(1).strip()
    text = re.sub(r'\[\[([^\]]+)\]\]', r'\1', text)
    text = re.sub(r'\[([^\]]+)\]\([^)]+\)', r'\1', text)
    text = re.sub(r'[#*`_]', '', text)
    return text.strip()[:50]


def extract_refs(text: str, offset: int) -> list[dict]:
    """Extract OutgoingRefs from a text chunk.

    Inline code spans (backtick-quoted) are blanked out first so that
    [[refs]] inside code are not extracted — matching remark's AST behaviour
    in the TypeScript parser, which treats inlineCode nodes as opaque.
    """
    refs = []
    # Blank out inline code spans to match TypeScript's remark AST behaviour
    # (replace each char with a space so other offsets remain valid)
    clean = re.sub(r'`[^`]*`', lambda m: ' ' * len(m.group(0)), text)
    # [[...]] refs — search in cleaned text
    for m in REF_RE.finditer(clean):
        ref_text = m.group(1)
        cross_m = re.match(r'^(SPEC-\d{4})(?::(.+))?$', ref_text)
        if cross_m:
            refs.append({
                'kind': 'cross-spec',
                'text': ref_text,
                'targetSpec': cross_m.group(1),
                'targetAddress': cross_m.group(2),
                'rangeStart': offset + m.start(),
                'rangeEnd': offset + m.end(),
            })
        else:
            refs.append({
                'kind': 'block',
                'text': ref_text,
                'rangeStart': offset + m.start(),
                'rangeEnd': offset + m.end(),
            })
    # Inline images ![alt](url) — extract before links to avoid double-counting
    for m in IMAGE_RE.finditer(text):
        url = m.group(2)
        if not url.startswith(('http://', 'https://')):
            path = url.split('#')[0].split('?')[0]
            refs.append({
                'kind': 'file',
                'text': m.group(1),
                'targetPath': path,
                'rangeStart': offset + m.start(),
                'rangeEnd': offset + m.end(),
            })
    # Relative file links [text](path) — exclude image patterns already captured
    image_ranges = {(offset + m.start(), offset + m.end()) for m in IMAGE_RE.finditer(text)}
    for m in LINK_RE.finditer(text):
        url = m.group(2)
        rng = (offset + m.start(), offset + m.end())
        if rng in image_ranges:
            continue
        if url.startswith(('http://', 'https://', 'mailto:', '#')):
            continue
        path = url.split('#')[0].split('?')[0]
        ref = {
            'kind': 'file',
            'text': m.group(1),
            'targetPath': path,
            'rangeStart': offset + m.start(),
            'rangeEnd': offset + m.end(),
        }
        fragment = url.split('#', 1)[1].split('?')[0] if '#' in url else ''
        if fragment:
            ref['fragment'] = fragment  # deep link into a reference file (GRF-15)
        refs.append(ref)
    return refs


def parse_spec(spec_path: Path, text: str | None = None) -> tuple[str, list[Block]]:
    """Parse spec.md (or `text`, the spec's would-be contents) and return (spec_id, flat_blocks)."""
    if text is None:
        text = spec_path.read_text(encoding='utf-8')
    lines = text.split('\n')
    folder_name = spec_path.parent.name
    m = re.match(r'^(SPEC-\d{4})-', folder_name)
    spec_id = m.group(1) if m else folder_name

    blocks: list[Block] = []

    # ---- Extract frontmatter ----
    fm_start = 0
    fm_end = 0
    fm_data: dict = {}
    if lines and lines[0].strip() == '---':
        end_idx = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == '---'), None)
        if end_idx is not None:
            fm_text = '\n'.join(lines[1:end_idx])
            fm_data = pyyaml.safe_load(fm_text) or {}
            fm_start = 0
            fm_end = sum(len(l) + 1 for l in lines[:end_idx + 1])
            fm_id = stable_id(spec_id, '', 'frontmatter')
            fm_block = Block(fm_id, 'frontmatter', 0, '', str(fm_data.get('title', '')),
                             fm_start, fm_end)
            blocks.append(fm_block)

    # Build a char-offset map for lines
    char_offsets: list[int] = []
    offset = 0
    for line in lines:
        char_offsets.append(offset)
        offset += len(line) + 1

    # ---- Walk body lines ----
    body_start_line = 0
    if lines and lines[0].strip() == '---':
        end_idx = next((i for i, ln in enumerate(lines[1:], 1) if ln.strip() == '---'), None)
        if end_idx is not None:
            body_start_line = end_idx + 1

    section_idx = 0
    subsection_idx = 0
    current_section: Block | None = None
    current_subsection: Block | None = None
    in_toc = False
    in_fence = False
    desc_lines: list[tuple[int, str]] = []  # (line_idx, text) accumulated desc
    seen_list = False

    def flush_desc(parent: Block) -> None:
        nonlocal desc_lines
        if not desc_lines:
            return
        first_line_idx, _ = desc_lines[0]
        last_line_idx, last_text = desc_lines[-1]
        start = char_offsets[first_line_idx]
        end = char_offsets[last_line_idx] + len(last_text)
        raw = '\n'.join(t for _, t in desc_lines)
        label = extract_label(raw)
        desc_id = stable_id(spec_id, parent.address + ':desc', '')
        desc_block = Block(desc_id, 'description', parent.level, parent.address,
                           label, start, end)
        # Extract refs
        desc_block.refs = extract_refs(raw, start)
        parent.children.append(desc_block)
        blocks.append(desc_block)
        desc_lines = []

    # Free text the template has no place for: above the first H2 (a top-level
    # block) or after a list under a heading (mirrors parse.ts addProse/flushProse).
    prose_lines: list[tuple[int, str]] = []
    prose_parent: list = [None]

    def add_prose(idx: int, parent) -> None:
        if prose_lines and prose_parent[0] is not parent:
            flush_prose()
        if not prose_lines:
            prose_parent[0] = parent
        prose_lines.append((idx, lines[idx]))

    def flush_prose() -> None:
        if not prose_lines:
            return
        parent = prose_parent[0]
        first_line_idx, _ = prose_lines[0]
        last_line_idx, last_text = prose_lines[-1]
        start = char_offsets[first_line_idx]
        end = char_offsets[last_line_idx] + len(last_text)
        raw = '\n'.join(t for _, t in prose_lines)
        label = prose_label(raw)
        level = parent.level if parent else 1
        address = parent.address if parent else ''
        pid = stable_id(spec_id, address + ':h' + str(level) + ':' + label[:32], label)
        block = Block(pid, 'paragraph', level, address, label, start, end)
        block.refs = extract_refs(raw, start)
        if parent:
            parent.children.append(block)
        blocks.append(block)
        prose_lines.clear()
        prose_parent[0] = None

    # List parsing — iterates item lines and builds item blocks
    def parse_list_from_lines(
        line_iter_start: int,
        parent_block: Block,
        parent_address: str,
        depth_level: int,
    ) -> int:
        """
        Parse list items starting at line_iter_start under parent_block.
        Returns the line index where the list ends (exclusive).
        """
        # A second list under the same heading continues its numbering.
        item_idx = sum(1 for c in parent_block.children if c.kind == 'item')
        i = line_iter_start
        item_stack: list[tuple[int, Block]] = []  # (indent, block)

        while i < len(lines):
            if in_fence:
                i += 1
                continue
            line = lines[i]

            # Check for a new H2/H3/H1 which would end the list context
            if re.match(r'^#{1,3}\s', line) and not in_fence:
                break

            m_item = ITEM_RE.match(line)
            m_unordered = UNORDERED_RE.match(line)

            if m_item or m_unordered:
                indent = len(line) - len(line.lstrip(' '))
                # Pop stack to find parent at this indent level
                while item_stack and item_stack[-1][0] >= indent:
                    item_stack.pop()

                if item_stack:
                    par_block = item_stack[-1][1]
                    par_addr = par_block.address
                    sib_idx = len(par_block.children) + 1
                    item_idx_local = sib_idx
                else:
                    par_block = parent_block
                    par_addr = parent_address
                    item_idx += 1
                    item_idx_local = item_idx

                new_addr = f'{par_addr}.{item_idx_local}' if par_addr else str(item_idx_local)
                new_level = depth_level + len(item_stack)

                if m_item:
                    raw_text = m_item.group(3)
                    written_num = str(item_idx_local)
                else:
                    raw_text = (m_unordered.group(2) if m_unordered else line.strip())
                    written_num = None

                label = extract_label(raw_text)
                lstart = char_offsets[i]
                # End will be updated as we see continuation lines
                lend = lstart + len(line)

                item_id = stable_id(spec_id, new_addr, '')
                item_block = Block(item_id, 'item', new_level, new_addr, label,
                                   lstart, lend, written_num)
                item_block.refs = extract_refs(raw_text, lstart)

                par_block.children.append(item_block)
                blocks.append(item_block)
                item_stack.append((indent, item_block))
                i += 1
            elif line.strip() == '' or line[:1] in (' ', '\t'):
                # Continuation or blank line — append refs from continuation lines
                if item_stack:
                    item_block = item_stack[-1][1]
                    refs = extract_refs(line, char_offsets[i])
                    item_block.refs.extend(refs)
                    item_block.source_end = char_offsets[i] + len(line)
                i += 1
            else:
                # Non-item, non-continuation line that isn't a heading
                # Could be a paragraph after the list — stop
                break

        return i

    i = body_start_line
    while i < len(lines):
        line = lines[i]

        # Track code fences
        if line.startswith('```'):
            in_fence = not in_fence
            i += 1
            continue

        if in_fence:
            i += 1
            continue

        lstart = char_offsets[i]
        lend = lstart + len(line)

        # H1
        m1 = H1_RE.match(line)
        if m1:
            flush_prose()
            label = m1.group(1).strip()
            h1_id = stable_id(spec_id, '', 'h1:' + label[:64])
            h1 = Block(h1_id, 'h1', 1, '', label, lstart, lend)
            blocks.append(h1)
            i += 1
            continue

        # H2
        m2 = H2_RE.match(line)
        if m2:
            flush_prose()
            heading_text = m2.group(2).strip()

            # Flush pending desc
            if current_subsection and desc_lines and not seen_list:
                flush_desc(current_subsection)
            elif current_section and not current_subsection and desc_lines and not seen_list:
                flush_desc(current_section)
            desc_lines = []
            seen_list = False

            if heading_text == TOC_HEADING:
                in_toc = True
                toc_id = stable_id(spec_id, '', 'toc')
                toc = Block(toc_id, 'toc', 2, '', TOC_HEADING, lstart, lend)
                blocks.append(toc)
                current_section = None
                current_subsection = None
                i += 1
                continue

            in_toc = False
            section_idx += 1
            subsection_idx = 0
            address = str(section_idx)
            written = extract_written_number(heading_text)
            label = extract_inline_text(heading_text) or heading_text[:50]
            sec_id = stable_id(spec_id, address, label[:64])
            current_section = Block(sec_id, 'section', 2, address, label, lstart, lend, written)
            blocks.append(current_section)
            current_subsection = None
            seen_list = False
            i += 1
            continue

        # H3
        m3 = H3_RE.match(line)
        if m3:
            if not current_section:
                if not in_toc:
                    add_prose(i, None)
                i += 1
                continue
            flush_prose()
            heading_text = m3.group(2).strip()

            # Flush pending desc
            if current_subsection and desc_lines and not seen_list:
                flush_desc(current_subsection)
            elif current_section and not current_subsection and desc_lines and not seen_list:
                flush_desc(current_section)
            desc_lines = []
            seen_list = False

            subsection_idx += 1
            address = f'{current_section.address}.{subsection_idx}'
            written = extract_written_number(heading_text)
            label = extract_inline_text(heading_text) or heading_text[:50]
            sub_id = stable_id(spec_id, address, label[:64])
            current_subsection = Block(sub_id, 'subsection', 3, address, label, lstart, lend, written)
            current_section.children.append(current_subsection)
            blocks.append(current_subsection)
            seen_list = False
            i += 1
            continue

        # H4+
        m4 = H4_RE.match(line)
        if m4 and not in_toc:
            heading_text = m4.group(2).strip() if len(m4.groups()) >= 2 else line.lstrip('#').strip()
            depth = len(re.match(r'^(#+)', line).group(1))
            target = current_subsection or current_section
            if not target:
                add_prose(i, None)
            else:
                flush_prose()
                label = extract_inline_text(heading_text)[:50]
                h4_id = stable_id(spec_id,
                                  target.address + ':h' + str(depth) + ':' + label[:32], label)
                h4 = Block(h4_id, 'paragraph', depth, target.address, label, lstart, lend)
                target.children.append(h4)
                blocks.append(h4)
            i += 1
            continue

        # List items
        m_item = ITEM_RE.match(line)
        m_unordered = UNORDERED_RE.match(line)

        if (m_item or m_unordered) and not in_toc:
            target = current_subsection or current_section
            if target:
                flush_prose()
                if desc_lines and not seen_list:
                    flush_desc(target)
                seen_list = True
                i = parse_list_from_lines(i, target, target.address, target.level + 1)
                continue

        # Paragraphs: description content before a list, free text otherwise
        if line.strip() and not in_toc:
            target = current_subsection or current_section
            if target and not seen_list:
                desc_lines.append((i, line))
            else:
                add_prose(i, target)

        i += 1

    flush_prose()
    # Flush trailing description
    if current_subsection and desc_lines and not seen_list:
        flush_desc(current_subsection)
    elif current_section and not current_subsection and desc_lines and not seen_list:
        flush_desc(current_section)

    return spec_id, blocks


# ---------------------------------------------------------------------------
# Hashes and text normalisation (mirrored in packages/spec-core/src/graph.ts)
# ---------------------------------------------------------------------------

SIG_WORDS = 32
LABEL_WORDS = 12


def h16(text: str) -> str:
    return hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]


HEADING_MARK_RE = re.compile(r'^#{1,6}\s+')
LIST_MARK_RE = re.compile(r'^(?:[-*+]|\d+[.)])\s+')
HEADING_NUM_RE = re.compile(r'^\d+(?:\.\d+)*\.?\s+')
ADDR_REF_RE = re.compile(r'\[\[(SPEC-\d{4}:)?\d+(?:\.\d+)*\]\]')
WS_RE = re.compile(r'\s+')
TOKEN_RE = re.compile(r'[a-z0-9]+')


def norm_ws(text: str) -> str:
    return WS_RE.sub(' ', text).strip()


def own_text(lines: list[str], kind: str) -> str:
    """A block's own text, normalised so renumbering never changes it.

    Markers, written numbers and in-spec `[[address]]` targets are dropped:
    renumbering rewrites all three without changing what the block says.
    """
    out: list[str] = []
    first = True
    for line in lines:
        s = line.strip()
        if not s:
            continue
        s = HEADING_MARK_RE.sub('', s)
        s = LIST_MARK_RE.sub('', s)
        if first and kind in ('section', 'subsection', 'paragraph'):
            s = HEADING_NUM_RE.sub('', s)
        first = False
        out.append(s)
    t = norm_ws(' '.join(out))
    return ADDR_REF_RE.sub(lambda m: '[[' + (m.group(1) or '') + '#]]', t)


def signature(text: str) -> str:
    return ' '.join(text.split(' ')[:SIG_WORDS]) if text else ''


def tokens(text: str) -> set[str]:
    return set(TOKEN_RE.findall(text.lower()))


def graph_label(text: str) -> str:
    m = re.match(r'^\*\*([^*]+)\*\*', text)
    if m:
        return norm_ws(m.group(1))
    t = text.replace('[[', '').replace(']]', '')
    t = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', t)
    t = t.replace('*', '').replace('`', '')
    return ' '.join(norm_ws(t).split(' ')[:LABEL_WORDS])


def slug(text: str) -> str:
    return re.sub(r'[^a-z0-9_\- ]', '', text.lower()).replace(' ', '-')


def json_dump(obj) -> str:
    return json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + '\n'


def num(x):
    """Confidence as a JSON number that prints the same in Python and JS."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        v = 0.0
    v = 0.0 if v < 0 else 1.0 if v > 1 else v
    return int(v) if v.is_integer() else v


# ---------------------------------------------------------------------------
# Block records: what re-anchoring and the graph need from the parse
# ---------------------------------------------------------------------------

def line_of(text: str, offset: int) -> int:
    return text.count('\n', 0, offset)


def block_records(text: str, blocks: list[Block]) -> list[dict]:
    """One record per block in document order: key, kind, parent, text, hash."""
    lines = text.split('\n')
    parent_of: dict[int, int] = {}
    index_of = {id(b): i for i, b in enumerate(blocks)}
    for i, b in enumerate(blocks):
        for c in b.children:
            parent_of[index_of[id(c)]] = i
    starts = [line_of(text, b.source_start) for b in blocks]
    order = sorted(range(len(blocks)), key=lambda i: (starts[i], i))
    pos_of = {i: pos for pos, i in enumerate(order)}
    recs: list[dict] = []
    for pos, i in enumerate(order):
        b = blocks[i]
        start = starts[i]
        end = len(lines)
        for j in order[pos + 1:]:
            if starts[j] > start:
                end = starts[j]
                break
        own = own_text(lines[start:end], b.kind)
        if b.kind == 'frontmatter':
            label = str(b.label)
        elif b.kind == 'toc':
            label = TOC_HEADING
        else:
            label = graph_label(own)
        par = parent_of.get(i)
        recs.append({
            'block': b,
            'key': b.id,
            'kind': b.kind,
            'address': b.address,
            'label': label,
            'hash': h16(own),
            'sig': signature(own),
            'order': pos,
            'parent': pos_of[par] if par is not None else None,
        })
    return recs


# ---------------------------------------------------------------------------
# Re-anchoring stable ids (GRF-4, items 59 and 68)
# ---------------------------------------------------------------------------

SINGLETON_KINDS = ('frontmatter', 'h1', 'toc')


def prior_anchors(graph: dict) -> list[dict]:
    """Block anchors of a prior graph, in document order."""
    anchors = []
    for n in graph.get('nodes', []):
        if not isinstance(n, dict) or n.get('kind') != 'block' or not isinstance(n.get('id'), str):
            continue
        anchors.append({
            'id': n['id'],
            'key': n['id'] if 'textHash' not in n else None,
            'kind': n.get('blockKind', ''),
            'address': n.get('address', ''),
            'label': n.get('label', ''),
            'hash': n.get('textHash'),
            'sig': n.get('text', ''),
            'parent': n.get('parent'),
            'order': n.get('order', 0),
        })
    anchors.sort(key=lambda a: (a['order'], a['id']))
    return anchors


def better(a: tuple[int, int], b: tuple[int, int]) -> int:
    """Compare jaccard scores a=(inter, union) and b exactly: 1 if a>b, 0 if equal, -1 if a<b."""
    x = a[0] * b[1]
    y = b[0] * a[1]
    return 1 if x > y else 0 if x == y else -1


def reanchor(recs: list[dict], priors: list[dict], retired: list[dict], fresh: bool,
             hints: dict | None, spec_id: str) -> tuple[list[str], list[dict]]:
    """Give every new block a stable id. Returns (ids by record index, lost prior anchors).

    Never guesses: a prior block is matched only by exact text, by a unique
    mutual best text match, or because most of its children moved with it.
    Anything else is lost (and its attachments become orphans).
    """
    assigned: list = [None] * len(recs)
    taken: dict[str, int] = {}  # prior id -> record index

    def assign(ri: int, pid: str) -> None:
        assigned[ri] = pid
        taken[pid] = ri

    def free_prior(pi: int) -> bool:
        return priors[pi]['id'] not in taken

    # 0. Exact hints from an in-app apply (positional key -> id).
    if hints:
        key_count: dict[str, int] = {}
        for r in recs:
            key_count[r['key']] = key_count.get(r['key'], 0) + 1
        for ri, r in enumerate(recs):
            hid = hints.get(r['key'])
            if isinstance(hid, str) and hid and key_count[r['key']] == 1 and hid not in taken:
                assign(ri, hid)

    # 1. Fresh graph (built from these exact bytes): same blocks in the same order.
    if fresh and len(priors) == len(recs) and all(p['kind'] == r['kind'] for p, r in zip(priors, recs)):
        for ri in range(len(recs)):
            if assigned[ri] is None and free_prior(ri):
                assign(ri, priors[ri]['id'])

    # 2. One-of-a-kind blocks (front matter, H1, Table of Contents).
    for kind in SINGLETON_KINDS:
        ris = [ri for ri, r in enumerate(recs) if r['kind'] == kind]
        pis = [pi for pi, p in enumerate(priors) if p['kind'] == kind]
        if len(ris) == 1 and len(pis) == 1 and assigned[ris[0]] is None and free_prior(pis[0]):
            assign(ris[0], priors[pis[0]]['id'])

    # 3. Same place, same text.
    at: dict[str, list[int]] = {}
    for pi, p in enumerate(priors):
        at.setdefault(p['address'] + '|' + p['kind'] + '|' + str(p['hash']), []).append(pi)
    for ri, r in enumerate(recs):
        if assigned[ri] is not None:
            continue
        cands = [pi for pi in at.get(r['address'] + '|' + r['kind'] + '|' + r['hash'], []) if free_prior(pi)]
        if len(cands) == 1:
            assign(ri, priors[cands[0]]['id'])

    # 4. Same text anywhere (moves, renumbering): equal-size groups pair in order.
    groups_p: dict[str, list[int]] = {}
    for pi, p in enumerate(priors):
        if free_prior(pi) and p['hash']:
            groups_p.setdefault(p['kind'] + '|' + p['hash'], []).append(pi)
    groups_r: dict[str, list[int]] = {}
    for ri, r in enumerate(recs):
        if assigned[ri] is None:
            groups_r.setdefault(r['kind'] + '|' + r['hash'], []).append(ri)
    for gk in sorted(groups_r):
        ris = groups_r[gk]
        pis = groups_p.get(gk, [])
        if len(ris) == len(pis):
            for ri, pi in zip(ris, pis):
                assign(ri, priors[pi]['id'])

    # 5. Structure and wording, in rounds until nothing changes.
    children_of: dict[str, list[str]] = {}
    for p in priors:
        if p['parent']:
            children_of.setdefault(p['parent'], []).append(p['id'])
    rec_tokens = [tokens(r['sig']) for r in recs]
    prior_tokens = [tokens(p['sig']) for p in priors]

    def parent_ok(pi: int, ri: int) -> bool:
        pp = priors[pi]['parent']
        rp = recs[ri]['parent']
        if not pp and rp is None:
            return True
        if not pp or rp is None:
            return False
        return assigned[rp] == pp

    def score(pi: int, ri: int):
        a, b = prior_tokens[pi], rec_tokens[ri]
        union = len(a | b)
        if union == 0:
            return None
        inter = len(a & b)
        if inter * 100 >= 60 * union or (parent_ok(pi, ri) and inter * 100 >= 34 * union):
            return (inter, union)
        return None

    for _ in range(4):
        changed = False
        # 5a. Most of its children moved with it.
        for pi, p in enumerate(priors):
            if not free_prior(pi):
                continue
            kids = children_of.get(p['id'], [])
            if not kids:
                continue
            votes: dict[int, int] = {}
            for kid in kids:
                ri = taken.get(kid)
                if ri is not None and recs[ri]['parent'] is not None:
                    par = recs[ri]['parent']
                    votes[par] = votes.get(par, 0) + 1
            if not votes:
                continue
            top = max(votes.values())
            winners = sorted(k for k, v in votes.items() if v == top)
            if len(winners) != 1 or top * 2 <= len(kids):
                continue
            ri = winners[0]
            if assigned[ri] is None and recs[ri]['kind'] == p['kind']:
                assign(ri, p['id'])
                changed = True
        # 5b. Unique mutual best wording match.
        for pi, p in enumerate(priors):
            if not free_prior(pi):
                continue
            best_ri, best_s, tie = None, None, False
            for ri, r in enumerate(recs):
                if assigned[ri] is not None or r['kind'] != p['kind']:
                    continue
                s = score(pi, ri)
                if s is None:
                    continue
                if best_s is None or better(s, best_s) > 0:
                    best_ri, best_s, tie = ri, s, False
                elif better(s, best_s) == 0:
                    tie = True
            if best_ri is None or tie:
                continue
            mutual = True
            for qi, q in enumerate(priors):
                if qi == pi or not free_prior(qi) or q['kind'] != p['kind']:
                    continue
                s = score(qi, best_ri)
                if s is not None and better(s, best_s) >= 0:
                    mutual = False
                    break
            if mutual:
                assign(best_ri, p['id'])
                changed = True
        if not changed:
            break

    # 6. Graphs from before anchors were stored: same positional key.
    for ri, r in enumerate(recs):
        if assigned[ri] is not None:
            continue
        cands = [pi for pi, p in enumerate(priors) if free_prior(pi) and p['hash'] is None and p['key'] == r['key']]
        if len(cands) == 1:
            assign(ri, priors[cands[0]]['id'])

    # 7. A block that comes back word for word (undo, revert) gets its old id.
    for ri, r in enumerate(recs):
        if assigned[ri] is not None:
            continue
        cands = [x for x in retired if x.get('blockKind') == r['kind'] and x.get('textHash') == r['hash']
                 and x.get('id') not in taken]
        ids = sorted({x['id'] for x in cands})
        if len(ids) == 1:
            assign(ri, ids[0])

    # 8. Everything else is new: mint an id that was never used.
    used = set(taken) | {p['id'] for p in priors} | {x.get('id') for x in retired}
    for ri, r in enumerate(recs):
        if assigned[ri] is not None:
            continue
        cand = r['key']
        n = 0
        while cand in used:
            n += 1
            cand = h16(spec_id + ':' + r['key'] + ':' + str(n))
        assign(ri, cand)
        used.add(cand)

    lost = [p for p in priors if p['id'] not in taken]
    return assigned, lost


# ---------------------------------------------------------------------------
# Reference files: inner structure (GRF-15, GRF-16)
# ---------------------------------------------------------------------------

BINARY_EXT = re.compile(r'\.(png|jpe?g|gif|svg|webp|bmp|ico|pdf|zip|xlsx?|docx?|pptx?|mp4|mov)$', re.I)


def file_format(path: str) -> str:
    p = path.lower()
    if p.endswith('.md') or p.endswith('.markdown'):
        return 'md'
    if p.endswith('.json'):
        return 'json'
    if p.endswith('.xml'):
        return 'xml'
    if p.endswith('.csv'):
        return 'csv'
    if p.endswith('.mmd') or p.endswith('.mermaid'):
        return 'mermaid'
    if BINARY_EXT.search(p):
        return 'binary'
    return 'text'


def unique_key(key: str, seen: set) -> str:
    if key not in seen:
        seen.add(key)
        return key
    n = 1
    while key + '-' + str(n) in seen:
        n += 1
    seen.add(key + '-' + str(n))
    return key + '-' + str(n)


MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.*?)(?:\s+#+)?\s*$')


def md_parts(text: str):
    lines = text.split('\n')
    heads = []
    fence = False
    for i, line in enumerate(lines):
        s = line.strip()
        if s.startswith('```') or s.startswith('~~~'):
            fence = not fence
            continue
        if fence:
            continue
        m = MD_HEADING_RE.match(line)
        if m and m.group(2).strip():
            heads.append((i, len(m.group(1)), norm_ws(m.group(2))))
    if not heads:
        return None
    parts = []
    seen: set = set()
    stack: list = []
    for idx, (i, level, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        key = '#' + unique_key(slug(title), seen)
        while stack and stack[-1][0] >= level:
            stack.pop()
        part = {'key': key, 'label': title, 'hash': h16(norm_ws(' '.join(lines[i:end])))}
        if stack:
            part['parentKey'] = stack[-1][1]
        parts.append(part)
        stack.append((level, key))
    return parts


def scan_json_string(text: str, i: int) -> int:
    """text[i] is '"'; return the index after the closing quote."""
    i += 1
    while i < len(text):
        c = text[i]
        if c == '\\':
            i += 2
            continue
        if c == '"':
            return i + 1
        i += 1
    raise ValueError('unterminated string')


def scan_json_value(text: str, i: int) -> int:
    depth = 0
    while i < len(text):
        c = text[i]
        if c == '"':
            i = scan_json_string(text, i)
            if depth == 0:
                return i
            continue
        if c == '{' or c == '[':
            depth += 1
        elif c == '}' or c == ']':
            if depth == 0:
                return i
            depth -= 1
            if depth == 0:
                return i + 1
        elif c == ',' and depth == 0:
            return i
        i += 1
    return i


def json_parts(text: str):
    def bad_constant(_name):
        raise ValueError('not JSON')
    try:
        value = json.loads(text, parse_constant=bad_constant)
    except (ValueError, RecursionError):
        return None
    if not isinstance(value, dict):
        return []
    parts = []
    seen: set = set()
    i = text.index('{') + 1
    while True:
        while i < len(text) and text[i] in ' \t\r\n,':
            i += 1
        if i >= len(text) or text[i] == '}':
            break
        end = scan_json_string(text, i)
        key = json.loads(text[i:end])
        i = end
        while text[i] in ' \t\r\n:':
            i += 1
        vend = scan_json_value(text, i)
        raw = text[i:vend].strip()
        i = vend
        if key in seen:
            continue
        seen.add(key)
        parts.append({'key': '#' + key, 'label': key, 'hash': h16(raw)})
    return parts


XML_TOKEN_RE = re.compile(
    r'<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|<![^>]*>|<(/?)([A-Za-z_][\w.:-]*)[^<>]*?(/?)>|<')


def xml_parts(text: str):
    stack: list = []
    root = None
    children: dict = {}
    order: list = []
    for m in XML_TOKEN_RE.finditer(text):
        tok = m.group(0)
        if tok.startswith('<!') or tok.startswith('<?'):
            continue
        if m.group(2) is None:
            return None  # a stray '<'
        closing, name, selfclose = m.group(1), m.group(2), m.group(3)
        if closing:
            if not stack or stack[-1][0] != name:
                return None
            _, start = stack.pop()
            if len(stack) == 1:
                children[name].append(text[start:m.end()])
            if not stack:
                root = (name, text[start:m.end()])
            continue
        if not stack and root is not None:
            return None  # two roots
        if len(stack) == 1 and name not in children:
            order.append(name)
            children[name] = []
        if selfclose:
            if len(stack) == 1:
                children[name].append(tok)
            elif not stack:
                root = (name, tok)
            continue
        stack.append((name, m.start()))
    if stack or root is None:
        return None
    parts = [{'key': '#' + root[0], 'label': root[0], 'hash': h16(norm_ws(root[1]))}]
    seen = {root[0]}
    for name in order:
        if name in seen:
            continue
        seen.add(name)
        parts.append({'key': '#' + name, 'label': name, 'hash': h16(norm_ws('\n'.join(children[name])))})
    return parts


def csv_rows(text: str):
    rows: list = []
    row: list = []
    field = ''
    i = 0
    quoted = False
    at_start = True
    n = len(text)
    while i < n:
        c = text[i]
        if quoted:
            if c == '"':
                if i + 1 < n and text[i + 1] == '"':
                    field += '"'
                    i += 2
                    continue
                quoted = False
                i += 1
                continue
            field += c
            i += 1
            continue
        if c == '"' and at_start:
            quoted = True
            at_start = False
            i += 1
            continue
        if c == ',':
            row.append(field)
            field = ''
            at_start = True
            i += 1
            continue
        if c == '\n' or c == '\r':
            row.append(field)
            rows.append(row)
            row, field, at_start = [], '', True
            i += 2 if c == '\r' and i + 1 < n and text[i + 1] == '\n' else 1
            continue
        field += c
        at_start = False
        i += 1
    if quoted:
        return None
    if field or row:
        row.append(field)
        rows.append(row)
    return [r for r in rows if r != ['']]


def csv_parts(text: str):
    rows = csv_rows(text)
    if not rows:
        return None
    header = rows[0]
    for r in rows:
        if len(r) != len(header):
            return None  # ragged: not mapped yet (GRF-16)
    parts = []
    seen: set = set()
    for col, name in enumerate(header):
        label = name.strip()
        key = '#' + unique_key(label, seen)
        parts.append({'key': key, 'label': label, 'hash': h16('\n'.join(r[col] for r in rows[1:]))})
    return parts


MERMAID_SKIP = ('classDef', 'class', 'style', 'linkStyle', 'click', 'direction')
MERMAID_KEYWORDS = {'graph', 'flowchart', 'subgraph', 'end', 'TB', 'TD', 'BT', 'RL', 'LR'} | set(MERMAID_SKIP)
MERMAID_NODE_RE = re.compile(r'([A-Za-z_][A-Za-z0-9_]*)(?:\s*(\[\[|\[\(|\[|\(\(|\(|\{\{|\{|>)([^\]\)\}]*)[\]\)\}]+)?')


def mermaid_parts(text: str):
    lines = [ln for ln in text.split('\n') if ln.strip() and not ln.strip().startswith('%%')]
    if not lines or not re.match(r'^(graph|flowchart)\b', lines[0].strip()):
        return None
    parts = []
    index: dict = {}
    for line in lines[1:]:
        s = re.sub(r'\|[^|]*\|', ' ', line).strip()
        if s.split(' ')[0] in MERMAID_SKIP:
            continue
        for m in MERMAID_NODE_RE.finditer(s):
            node = m.group(1)
            if node in MERMAID_KEYWORDS:
                continue
            label = norm_ws(m.group(3).strip().strip('"')) if m.group(2) else ''
            if node not in index:
                index[node] = len(parts)
                parts.append({'key': '#' + node, 'label': label or node})
            elif label and parts[index[node]]['label'] == node:
                parts[index[node]]['label'] = label
    if not parts:
        return None
    for p in parts:
        p['hash'] = h16(p['label'])
    return parts


def file_parts(fmt: str, text: str):
    """Best effort: None means "not mapped yet" (never an error, GRF-16)."""
    try:
        if fmt == 'md':
            return md_parts(text)
        if fmt == 'json':
            return json_parts(text)
        if fmt == 'xml':
            return xml_parts(text)
        if fmt == 'csv':
            return csv_parts(text)
        if fmt == 'mermaid':
            return mermaid_parts(text)
    except Exception:  # noqa: BLE001 - best effort, never block
        return None
    return None


def part_node_id(spec_id: str, path: str, key: str) -> str:
    return 'part:' + spec_id + ':' + path + key


def find_part(parts: list, fragment: str):
    for p in parts:
        if p['key'] == '#' + fragment:
            return p
    want = slug(fragment)
    for p in parts:
        if slug(p['key'][1:]) == want:
            return p
    return None


# ---------------------------------------------------------------------------
# Build the persisted graph
# ---------------------------------------------------------------------------

INFERRED_FIELDS = ('from', 'to', 'kind', 'confidence', 'source', 'by', 'checkedAt', 'checkedAgainst')


def orphan_id(kind: str, lost_id: str, detail_key: str) -> str:
    return 'orphan-' + h16(kind + ':' + lost_id + ':' + detail_key)[:12]


def inferred_key(e: dict) -> tuple:
    return (0 if e.get('stale') else 1, e.get('checkedAt') or '', num(e.get('confidence', 0)),
            e.get('source') or '', e.get('by') or '')


def build(spec_dir: Path, text: str, priors: list, hints, add_inferred: list, resolve: list, now: str) -> dict:
    spec_id, blocks = parse_spec(spec_dir / 'spec.md', text)
    recs = block_records(text, blocks)
    spec_hash = h16(text)

    base = priors[0] if priors else {}
    anchors = prior_anchors(base)
    retired_in: list = []
    for g in priors:
        retired_in.extend(x for x in g.get('retired', []) if isinstance(x, dict))
    fresh = bool(base) and (base.get('builtFrom') or {}).get('spec.md') == spec_hash
    ids, lost = reanchor(recs, anchors, retired_in, fresh, hints, spec_id)
    live = set(ids)

    # Other sides of a merge: map their ids onto ours (GIT-7, union of inferred relations).
    alias: dict = {}
    other_lost: list = []
    for g in priors[1:]:
        o_anchors = prior_anchors(g)
        o_fresh = (g.get('builtFrom') or {}).get('spec.md') == spec_hash
        o_ids, o_lost = reanchor(recs, o_anchors, [], o_fresh, None, spec_id)
        o_known = {a['id'] for a in o_anchors}
        for oid, sid in zip(o_ids, ids):
            if oid != sid and oid in o_known:
                alias[oid] = sid
        other_lost.extend(a for a in o_lost if a['id'] not in live)

    nodes: list = []
    edges: list = []
    edge_keys: set = set()

    def add_edge(e: dict) -> None:
        k = e['from'] + '|' + e['to'] + '|' + e['kind']
        if k not in edge_keys:
            edge_keys.add(k)
            edges.append(e)

    for r, sid in zip(recs, ids):
        node = {'id': sid, 'kind': 'block', 'blockKind': r['kind'], 'label': r['label'],
                'order': r['order'], 'text': r['sig'], 'textHash': r['hash']}
        if r['address']:
            node['address'] = r['address']
        if r['parent'] is not None:
            node['parent'] = ids[r['parent']]
            add_edge({'from': ids[r['parent']], 'to': sid, 'kind': 'hierarchy'})
        nodes.append(node)

    addr_to_id: dict = {}
    for r, sid in zip(recs, ids):
        if r['address'] and r['address'] not in addr_to_id:
            addr_to_id[r['address']] = sid

    # Reference files linked from spec.md, and their inner parts.
    files: dict = {}
    parts_by_path: dict = {}
    built_from = {'spec.md': spec_hash}
    warnings: list = []
    xspec_ids: set = set()

    def load_file(path: str) -> dict:
        if path in files:
            return files[path]
        fmt = file_format(path)
        node = {'id': file_node_id(spec_id, path), 'kind': 'reference-file', 'address': path,
                'label': path, 'format': fmt}
        target = spec_dir / path
        content = None
        if not target.is_file():
            node['parseStatus'] = 'missing'
        elif fmt == 'binary':
            node['parseStatus'] = 'binary'
        else:
            content = target.read_bytes().decode('utf-8', errors='replace')
            built_from[path] = h16(content)
            if fmt == 'text':
                node['parseStatus'] = 'unmapped'
            else:
                parts = file_parts(fmt, content)
                if parts is None:
                    node['parseStatus'] = 'not-parsed'
                    node['notYetParsed'] = True
                else:
                    node['parseStatus'] = 'parsed'
                    parts_by_path[path] = parts
                    for p in parts:
                        pn = {'id': part_node_id(spec_id, path, p['key']), 'kind': 'reference-part',
                              'parentId': node['id'], 'address': path + p['key'], 'label': p['label'],
                              'textHash': p['hash']}
                        if p.get('parentKey'):
                            pn['parentPart'] = part_node_id(spec_id, path, p['parentKey'])
                        nodes.append(pn)
        files[path] = node
        nodes.append(node)
        return node

    for r, sid in zip(recs, ids):
        for ref in r['block'].refs:
            kind = ref.get('kind')
            if kind == 'block':
                target = addr_to_id.get(ref['text'])
                if target:
                    add_edge({'from': sid, 'to': target, 'kind': 'ref-block'})
            elif kind == 'cross-spec':
                nid = cross_spec_node_id(ref['targetSpec'], ref.get('targetAddress'))
                if nid not in xspec_ids:
                    xspec_ids.add(nid)
                    xn = {'id': nid, 'kind': 'spec', 'label': ref['text']}
                    if ref.get('targetAddress'):
                        xn['address'] = ref['targetAddress']
                    nodes.append(xn)
                add_edge({'from': sid, 'to': nid, 'kind': 'ref-cross-spec'})
            elif kind == 'file':
                path = ref.get('targetPath') or ref.get('text', '')
                if not path:
                    continue
                fnode = load_file(path)
                add_edge({'from': sid, 'to': fnode['id'], 'kind': 'file-link'})
                frag = ref.get('fragment')
                if frag:
                    part = find_part(parts_by_path.get(path, []), frag)
                    if part:
                        add_edge({'from': sid, 'to': part_node_id(spec_id, path, part['key']), 'kind': 'file-link'})
                    else:
                        warnings.append({'kind': 'missing-part', 'from': sid, 'path': path, 'part': '#' + frag,
                                         'message': path + '#' + frag + " doesn't exist yet; the link resolves when it is added."})

    # Current text hashes, for staleness (GRF-10).
    current_hash: dict = {}
    for r, sid in zip(recs, ids):
        current_hash[sid] = r['hash']
    for n in nodes:
        if n['kind'] == 'reference-part':
            current_hash[n['id']] = n['textHash']
        elif n['kind'] == 'reference-file' and n['address'] in built_from:
            current_hash[n['id']] = built_from[n['address']]
    endpoints = {n['id'] for n in nodes}

    lost_by_id: dict = {}
    for a in lost:
        lost_by_id[a['id']] = a
    for a in other_lost:
        if a['id'] not in lost_by_id:
            lost_by_id[a['id']] = a
    in_app = bool(hints)

    orphans: dict = {}
    for g in priors:
        for o in g.get('orphans', []):
            if not isinstance(o, dict) or o.get('lostBlockId') in live:
                continue  # the block came back word for word
            if o.get('id') not in orphans:
                orphans[o['id']] = o

    def make_orphan(kind: str, a: dict, detail: dict, detail_key: str) -> None:
        oid = orphan_id(kind, a['id'], detail_key)
        if oid in orphans:
            return
        orphans[oid] = {'id': oid, 'kind': kind, 'specId': spec_id, 'lostBlockId': a['id'],
                        'lastKnownAddress': a['address'], 'lastKnownText': a['sig'] or a['label'],
                        'detectedAt': now, 'status': 'orphaned', 'detail': detail}

    # Reference links that lost their block (item 60): kept as orphans, never removed.
    if not in_app:
        for g in priors:
            for e in g.get('edges', []):
                if not isinstance(e, dict) or e.get('kind') != 'file-link':
                    continue
                src, dst = e.get('from'), str(e.get('to'))
                if src not in lost_by_id or not dst.startswith('file:'):
                    continue
                path = dst.split(':', 2)[2]
                make_orphan('reference-link', lost_by_id[src], {'path': path}, path)

    # Inferred relations: union of every prior side, plus new ones.
    inferred: dict = {}
    candidates: list = []
    for g in priors:
        for e in g.get('edges', []):
            if isinstance(e, dict) and e.get('kind') == 'inferred':
                candidates.append(e)
    for e in add_inferred:
        if not isinstance(e, dict) or not isinstance(e.get('from'), str) or not isinstance(e.get('to'), str):
            continue
        x = dict(e)
        x['kind'] = 'inferred'
        if not isinstance(x.get('checkedAgainst'), dict):
            x['checkedAgainst'] = {k: current_hash[k] for k in (x['from'], x['to']) if k in current_hash}
        if not x.get('checkedAt'):
            x['checkedAt'] = now
        candidates.append(x)
    for raw in candidates:
        e = {k: raw[k] for k in INFERRED_FIELDS if k in raw}
        ca = dict(e.get('checkedAgainst') or {})
        for end in ('from', 'to'):
            old = e[end]
            if old in alias:
                e[end] = alias[old]
                if old in ca:
                    ca[e[end]] = ca.pop(old)
        e['checkedAgainst'] = {k: ca[k] for k in sorted({e['from'], e['to']}) if k in ca}
        e['confidence'] = num(e.get('confidence', 0))
        dead = [e[end] for end in ('from', 'to') if e[end] not in endpoints]
        if dead:
            lost_block = next((d for d in dead if d in lost_by_id), None)
            if lost_block is not None and not in_app:
                make_orphan('inferred-relation', lost_by_id[lost_block],
                            {'from': e['from'], 'to': e['to'], 'confidence': e['confidence'],
                             'source': e.get('source', '')}, e['from'] + '>' + e['to'])
                continue
            if not all(d.startswith('part:') or d.startswith('file:') for d in dead):
                continue  # endpoint deleted in the app, or never existed: dropped
            # else: a part that disappeared; the relation goes stale (GRF-16)
        changed = sorted({k for k in (e['from'], e['to']) if current_hash.get(k) is None
                          or e['checkedAgainst'].get(k) != current_hash.get(k)})
        e['stale'] = bool(changed)
        if changed:
            e['staleReason'] = 'text changed since this relation was checked: ' + ', '.join(changed)
        k = e['from'] + '|' + e['to']
        if k not in inferred or inferred_key(e) > inferred_key(inferred[k]):
            inferred[k] = e

    # Hand resolutions of orphans (item 68): re-anchor to a picked block, or delete.
    for res in resolve:
        if not isinstance(res, dict):
            continue
        o = orphans.pop(res.get('orphanId', ''), None)
        if o is None or res.get('action') != 'reanchor':
            continue
        target = res.get('blockId')
        if target not in live:
            orphans[o['id']] = o
            continue
        if o['kind'] == 'inferred-relation':
            d = o.get('detail') or {}
            e = {'from': target if d.get('from') == o['lostBlockId'] else d.get('from'),
                 'to': target if d.get('to') == o['lostBlockId'] else d.get('to'),
                 'kind': 'inferred', 'confidence': num(d.get('confidence', 0)), 'source': d.get('source', ''),
                 'by': 're-anchored by hand', 'checkedAt': now, 'checkedAgainst': {}, 'stale': True,
                 'staleReason': 're-anchored by hand; re-check before use'}
            if e['from'] in endpoints and e['to'] in endpoints:
                inferred[e['from'] + '|' + e['to']] = e

    for k in sorted(inferred):
        add_edge(inferred[k])

    # Retired ids: lost blocks, so undo can bring an id back and anchors can be flagged.
    retired: dict = {}
    for x in retired_in:
        if x.get('id') not in live:
            retired[x['id']] = x
    for a in lost:
        retired[a['id']] = {'id': a['id'], 'blockKind': a['kind'], 'address': a['address'], 'label': a['label'],
                            'textHash': a['hash'], 'text': a['sig'],
                            'reason': 'deleted' if in_app else 'unmatched'}

    nodes.sort(key=lambda n: n['id'])
    edges.sort(key=lambda e: (e['from'], e['to'], e['kind']))
    warnings.sort(key=lambda w: (w['from'], w['path'], w['part']))
    return {
        '$comment': 'Generated by scripts/spec_graph.py. Never hand-edit; run the validator to refresh it.',
        'builtFrom': built_from,
        'edges': edges,
        'nodes': nodes,
        'orphans': [orphans[k] for k in sorted(orphans)],
        'retired': [retired[k] for k in sorted(retired)],
        'specId': spec_id,
        'version': 1,
        'warnings': warnings,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def main(argv: list) -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Build spec-graph.json for one spec folder.')
    ap.add_argument('spec_folder')
    ap.add_argument('--out', help='where to write (default: <spec-folder>/spec-graph.json)')
    ap.add_argument('--spec-text', help="read the spec's text from this file instead of spec.md")
    ap.add_argument('--prior', action='append', default=[],
                    help='prior graph(s); the first gives ids, the others are merged in (default: the current file)')
    ap.add_argument('--no-prior', action='store_true', help='ignore any existing graph')
    ap.add_argument('--ids', help='JSON {positional key: stable id} from an in-app apply')
    ap.add_argument('--add-inferred', help='JSON list of inferred relations to add')
    ap.add_argument('--resolve', help='JSON list of orphan resolutions')
    ap.add_argument('--now', help='timestamp for new records (ISO 8601)')
    args = ap.parse_args(argv[1:])

    spec_dir = Path(args.spec_folder).resolve()
    spec_md = spec_dir / 'spec.md'
    if args.spec_text:
        text = Path(args.spec_text).read_text(encoding='utf-8')
    elif spec_md.is_file():
        text = spec_md.read_text(encoding='utf-8')
    else:
        print(f'error: {spec_md} not found', file=sys.stderr)
        return 1
    out_path = Path(args.out).resolve() if args.out else spec_dir / 'spec-graph.json'

    priors: list = []
    if not args.no_prior:
        paths = [Path(p) for p in args.prior] or [out_path]
        for p in paths:
            g = load_json(p) if p.is_file() else None
            if isinstance(g, dict) and isinstance(g.get('nodes'), list):
                priors.append(g)
    hints = load_json(Path(args.ids)) if args.ids else None
    add_inferred = load_json(Path(args.add_inferred)) if args.add_inferred else []
    resolve = load_json(Path(args.resolve)) if args.resolve else []
    if args.now:
        now = args.now
    else:
        import datetime
        now = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')

    graph = build(spec_dir, text, priors, hints if isinstance(hints, dict) else None,
                  add_inferred if isinstance(add_inferred, list) else [],
                  resolve if isinstance(resolve, list) else [], now)
    out = json_dump(graph)
    if not (out_path.is_file() and out_path.read_text(encoding='utf-8') == out):
        out_path.write_text(out, encoding='utf-8')
    try:
        rel = out_path.relative_to(Path.cwd())
    except ValueError:
        rel = out_path
    print(f'wrote {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

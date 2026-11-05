#!/usr/bin/env python3
"""spec_graph.py — build spec-graph.json for one spec folder.

Replaces the Wave 0 stub (REPO-CHANGES change 8, GRF-14).
Produces the structural layer of the spec graph:
  - One 'block' node per parsed block (frontmatter, h1, toc, section,
    subsection, description, item, paragraph).
  - 'hierarchy' edges from parent block id to child block id.
  - 'ref-block' edges for in-spec [[address]] references.
  - 'ref-cross-spec' edges for [[SPEC-NNNN:address]] references.
  - 'file-link' edges for relative Markdown file links.
  - 'reference-file' nodes for each unique linked file.

Output is deterministic: sorted keys, indent=2, newline at EOF.
Node ids use the same sha256 algorithm as the TypeScript buildGraph, so
the parity test (packages/spec-core/parity/graph.test.ts) can compare them.

Usage:
    python3 scripts/spec_graph.py specs/SPEC-0999-bulk-invoice-export/
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
        refs.append({
            'kind': 'file',
            'text': m.group(1),
            'targetPath': path,
            'rangeStart': offset + m.start(),
            'rangeEnd': offset + m.end(),
        })
    return refs


def parse_spec(spec_path: Path) -> tuple[str, list[Block]]:
    """Parse spec.md and return (spec_id, flat_blocks)."""
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
        item_idx = 0
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
            label = m1.group(1).strip()
            h1_id = stable_id(spec_id, '', 'h1:' + label[:64])
            h1 = Block(h1_id, 'h1', 1, '', label, lstart, lend)
            blocks.append(h1)
            i += 1
            continue

        # H2
        m2 = H2_RE.match(line)
        if m2:
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
                i += 1
                continue
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
            if target:
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
                if desc_lines and not seen_list:
                    flush_desc(target)
                seen_list = True
                i = parse_list_from_lines(i, target, target.address, target.level + 1)
                continue

        # Paragraphs (description content)
        if line.strip() and not in_toc and not seen_list:
            target = current_subsection or current_section
            if target:
                desc_lines.append((i, line))

        i += 1

    # Flush trailing description
    if current_subsection and desc_lines and not seen_list:
        flush_desc(current_subsection)
    elif current_section and not current_subsection and desc_lines and not seen_list:
        flush_desc(current_section)

    return spec_id, blocks


# ---------------------------------------------------------------------------
# Build the graph from parsed blocks
# ---------------------------------------------------------------------------

def build_graph(spec_id: str, all_blocks: list[Block]) -> dict:
    nodes: list[dict] = []
    edges: list[dict] = []
    ref_file_nodes: dict[str, dict] = {}  # path → node
    edge_set: set[str] = set()

    # Create block nodes
    addr_to_id: dict[str, str] = {}
    for b in all_blocks:
        nodes.append({
            'id': b.id,
            'kind': 'block',
            **(({'address': b.address} if b.address else {})),
            'label': b.label,
        })
        if b.address:
            addr_to_id[b.address] = b.id

    def add_edge(from_: str, to_: str, kind: str, **extra) -> None:
        key = f'{from_}|{to_}|{kind}'
        if key not in edge_set:
            edge_set.add(key)
            e = {'from': from_, 'to': to_, 'kind': kind}
            e.update(extra)
            edges.append(e)

    def process_block(b: Block, parent_id: str | None) -> None:
        # Hierarchy edge
        if parent_id:
            add_edge(parent_id, b.id, 'hierarchy')

        # Ref edges
        for ref in b.refs:
            kind = ref.get('kind', '')
            if kind == 'block':
                target_id = addr_to_id.get(ref['text'])
                if target_id:
                    add_edge(b.id, target_id, 'ref-block')
            elif kind == 'cross-spec':
                node_id = cross_spec_node_id(ref['targetSpec'], ref.get('targetAddress'))
                # Add cross-spec node if not present
                if not any(n['id'] == node_id for n in nodes):
                    node: dict = {
                        'id': node_id,
                        'kind': 'spec',
                        'label': ref['text'],
                    }
                    if ref.get('targetAddress'):
                        node['address'] = ref['targetAddress']
                    nodes.append(node)
                add_edge(b.id, node_id, 'ref-cross-spec')
            elif kind == 'file':
                path = ref.get('targetPath') or ref.get('text', '')
                if not path:
                    continue
                if path not in ref_file_nodes:
                    fn_id = file_node_id(spec_id, path)
                    fn: dict = {
                        'id': fn_id,
                        'kind': 'reference-file',
                        'address': path,
                        'label': path,
                    }
                    ref_file_nodes[path] = fn
                    nodes.append(fn)
                fn_id = ref_file_nodes[path]['id']
                add_edge(b.id, fn_id, 'file-link')

        # Recurse into children
        for child in b.children:
            process_block(child, b.id)

    # Walk all top-level blocks (those with no parent)
    # We need to identify the forest structure
    child_ids: set[str] = set()
    for b in all_blocks:
        for c in b.children:
            child_ids.add(c.id)

    for b in all_blocks:
        if b.id not in child_ids:
            process_block(b, None)

    # Sort nodes by id
    nodes.sort(key=lambda n: n['id'])

    # Sort edges by (from, to, kind)
    edges.sort(key=lambda e: (e['from'], e['to'], e['kind']))

    return {
        'edges': edges,
        'nodes': nodes,
        'specId': spec_id,
        'version': 1,
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print('usage: spec_graph.py <spec-folder>', file=sys.stderr)
        return 2

    spec_dir = Path(argv[1]).resolve()
    spec_md = spec_dir / 'spec.md'
    if not spec_md.is_file():
        print(f'error: {spec_md} not found', file=sys.stderr)
        return 1

    spec_id, all_blocks = parse_spec(spec_md)
    graph = build_graph(spec_id, all_blocks)

    out_path = spec_dir / 'spec-graph.json'
    out_path.write_text(json.dumps(graph, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    try:
        rel = out_path.relative_to(Path.cwd())
    except ValueError:
        rel = out_path
    print(f'wrote {rel}')
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))

#!/usr/bin/env python3
"""
research-loop gate validator.
Called by orchestrator via Bash tool instead of asking Claude to simulate regex.

Usage:
    python3 gates.py <gate> <draft_file> [turn]

Output:
    First line: PASS  or  FAIL
    On FAIL: remaining lines describe the violations (one per line).

Gates: w1  w2  w3  w4  w5  w6
"""

import re
import sys


# ---------------------------------------------------------------------------
# W3 blacklist patterns (source of truth — edit here to update all checks)
# ---------------------------------------------------------------------------

_W3_BARE_DOMAIN = re.compile(r'^https?://[^/\s]+/?$')

_W3_GROUNDING_FRAGMENTS = [
    'vertexaisearch.cloud.google.com/grounding-api-redirect/',
    'google.com/url?',
    'duckduckgo.com/l/?',
    'bing.com/ck/a?',
]

_W3_SERP_FRAGMENTS = [
    'google.com/search?q=',
    'bing.com/search?q=',
    'duckduckgo.com/?q=',
]

_W3_PLACEHOLDERS = [
    'search summary',
    'search 综合',
    '多源汇总',
    'Gemini synthesized',
    'no specific URL',
]

_W3_EXEMPT_LABELS = {
    '[领域共识]', '[DOMAIN]', '[INFERENCE]', '[推断]',
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: str) -> str:
    with open(path, encoding='utf-8') as f:
        return f.read()


def _extract_section(text: str, heading: str) -> str:
    """Extract content from a markdown section up to the next same-or-higher-level heading."""
    level = len(heading) - len(heading.lstrip('#'))
    pattern = re.compile(r'^#{1,' + str(level) + r'}\s', re.MULTILINE)
    start = text.find(heading)
    if start == -1:
        return ''
    after = text[start + len(heading):]
    m = pattern.search(after)
    return after[:m.start()] if m else after


# ---------------------------------------------------------------------------
# Gate implementations
# ---------------------------------------------------------------------------

def check_w1(draft: str) -> tuple[bool, list[str]]:
    """Turn 1: ## Self Coverage Plan heading must exist (case-sensitive)."""
    if '## Self Coverage Plan' not in draft:
        return False, ['Missing `## Self Coverage Plan` heading (case-sensitive match required)']
    return True, []


def check_w2(draft: str) -> tuple[bool, list[str]]:
    """Turn 2+: top-level # Rebuttals heading must exist."""
    if re.search(r'^# Rebuttals\s*$', draft, re.MULTILINE):
        return True, []
    return False, ['Missing top-level `# Rebuttals` heading (single #, exact string)']


def check_w3(draft: str) -> tuple[bool, list[str]]:
    """Every turn: Evidence Table Source URLs must not match the blacklist."""
    section = _extract_section(draft, '# Evidence Table')
    if not section:
        return True, []  # No Evidence Table — nothing to check

    violations: list[str] = []
    lines = section.splitlines()
    row_num = 0

    for line in lines:
        if not line.strip().startswith('|'):
            continue
        # Skip table header and separator rows
        if re.search(r'Source URL', line, re.IGNORECASE):
            continue
        if re.match(r'\s*\|[\s\-|]+\|\s*$', line):
            continue

        row_num += 1
        cols = [c.strip() for c in line.split('|')]

        # Check for exempt label anywhere in the row
        row_text = line
        if any(label in row_text for label in _W3_EXEMPT_LABELS):
            continue

        # Find URL-like values in cols
        for col in cols:
            col = col.strip()
            if col.startswith('http'):
                url = col
                if _W3_BARE_DOMAIN.match(url):
                    violations.append(f'Row {row_num}: bare domain root — {url}')
                elif any(frag in url for frag in _W3_GROUNDING_FRAGMENTS):
                    violations.append(f'Row {row_num}: grounding redirect — {url}')
                elif any(frag in url for frag in _W3_SERP_FRAGMENTS):
                    violations.append(f'Row {row_num}: SERP URL — {url}')
            for ph in _W3_PLACEHOLDERS:
                if ph in col:
                    violations.append(f'Row {row_num}: placeholder text — "{col[:80]}"')
                    break

    return (len(violations) == 0), violations


def check_w4(draft: str, turn: int) -> tuple[bool, list[str]]:
    """Turn 2+: every ## Issue N: and ## RD N: inside # Rebuttals needs a valid Stance: line."""
    if turn < 2:
        return True, []

    rebuttals = _extract_section(draft, '# Rebuttals')
    if not rebuttals:
        return False, ['`# Rebuttals` section is missing or empty']

    violations: list[str] = []
    # Split into sub-sections by ## headings
    blocks = re.split(r'^(## (?:Issue|RD|Research Direction RD)\s*[\w\d]+[:\s].*)', rebuttals, flags=re.MULTILINE)

    i = 0
    while i < len(blocks):
        header = blocks[i].strip()
        body = blocks[i + 1] if i + 1 < len(blocks) else ''
        i += 2

        if not header.startswith('##'):
            continue

        is_issue = re.match(r'^## Issue\s+\[?\d+\]?[:\s]', header, re.IGNORECASE)
        is_rd = re.match(r'^## (?:RD|Research Direction RD)\s*\[?\d+\]?[:\s]', header, re.IGNORECASE)

        if not (is_issue or is_rd):
            continue

        # Find Stance: line
        stance_match = re.search(r'Stance\s*:\s*(\S+.*)', body)
        if not stance_match:
            violations.append(f'{header!r} — missing `Stance:` line')
            continue

        stance_val = stance_match.group(1).strip().upper()

        if is_issue:
            if not re.match(r'^(ACCEPT|CHALLENGE|PARTIAL)\b', stance_val):
                violations.append(f'{header!r} — invalid Issue stance `{stance_val}` (must be ACCEPT|CHALLENGE|PARTIAL)')
        elif is_rd:
            if not re.match(r'^(ACCEPT|REJECT)\b', stance_val):
                violations.append(f'{header!r} — invalid RD stance `{stance_val}` (must be ACCEPT(...)|REJECT(...))')

    return (len(violations) == 0), violations


def check_w5(draft: str, turn: int) -> tuple[bool, list[str]]:
    """Turn 2+: at least 2 RDs must be engaged (ACCEPT) in Rebuttals or Revision Log."""
    if turn < 2:
        return True, []

    accepted_rds: set[str] = set()

    rebuttals = _extract_section(draft, '# Rebuttals')
    for m in re.finditer(
        r'^## (?:RD|Research Direction RD)\s*\[?(\d+)\]?[:\s].*\n(.*\n)*?.*Stance\s*:\s*ACCEPT',
        rebuttals, re.MULTILINE | re.IGNORECASE
    ):
        accepted_rds.add(m.group(1))

    revision_log = _extract_section(draft, '# Revision Log')
    for m in re.finditer(
        r'^## Research Direction RD\[?(\d+)\]?[:\s].*\n(.*\n)*?.*Engagement mode\s*:\s*\S',
        revision_log, re.MULTILINE | re.IGNORECASE
    ):
        accepted_rds.add(m.group(1))

    count = len(accepted_rds)
    if count < 2:
        return False, [
            f'Track B engagement count is {count} (need ≥ 2). '
            'Engage at least 2 Research Directions via ACCEPT (INTEGRATE/CHALLENGE/EXPAND) '
            'in `# Rebuttals` and/or `# Revision Log`.'
        ]
    return True, []


def check_w6(draft: str) -> tuple[bool, list[str]]:
    """Turn 1: ## Self Coverage Plan table must have 5-8 data rows."""
    section = _extract_section(draft, '## Self Coverage Plan')
    if not section:
        return False, ['`## Self Coverage Plan` section not found — W1 should have caught this first']

    data_rows = 0
    for line in section.splitlines():
        if not line.strip().startswith('|'):
            continue
        # Skip header and separator
        if re.search(r'子问题|充分覆盖标准|adequacy', line, re.IGNORECASE):
            continue
        if re.match(r'\s*\|[\s\-|]+\|\s*$', line):
            continue
        if '|' in line:
            data_rows += 1

    if data_rows < 5:
        return False, [f'Self Coverage Plan has {data_rows} sub-question(s); minimum is 5']
    if data_rows > 8:
        return False, [f'Self Coverage Plan has {data_rows} sub-questions; maximum is 8']
    return True, []


# ---------------------------------------------------------------------------
# Coverage Matrix drift check (compares prior vs current Critic output)
# ---------------------------------------------------------------------------

def _parse_table_cells(text: str) -> list[list[str]]:
    """Parse a markdown table into rows of stripped cell values, skipping header/separator."""
    rows: list[list[str]] = []
    header_seen = False
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith('|'):
            continue
        # Separator row: only contains |, -, spaces
        if re.match(r'^[\|\-\s]+$', stripped):
            continue
        cells = [c.strip() for c in stripped.split('|')]
        # Remove empty leading/trailing from surrounding |
        if cells and cells[0] == '':
            cells = cells[1:]
        if cells and cells[-1] == '':
            cells = cells[:-1]
        if not cells:
            continue
        if not header_seen:
            header_seen = True
            continue  # Skip header row
        rows.append(cells)
    return rows


def check_coverage_matrix_drift(prior_path: str, current_path: str) -> tuple[bool, list[str]]:
    """
    Compare Coverage Matrix cell values between prior and current Critic output.
    Existing rows must not change (content only — formatting ignored).
    Adding new rows (patches) is allowed.

    Looks for ## Final Coverage Matrix first, falls back to # Coverage Matrix.
    """
    prior_md = _load(prior_path)
    current_md = _load(current_path)

    def _get_matrix(text: str) -> str:
        s = _extract_section(text, '## Final Coverage Matrix')
        if not s:
            s = _extract_section(text, '# Coverage Matrix')
        return s

    prior_section = _get_matrix(prior_md)
    current_section = _get_matrix(current_md)

    if not prior_section:
        return True, []  # Nothing to compare against

    if not current_section:
        return False, ['Coverage Matrix section missing from current attempt']

    prior_rows = _parse_table_cells(prior_section)
    current_rows = _parse_table_cells(current_section)

    if not prior_rows:
        return True, []

    col_names = ['#', '子问题', '充分覆盖标准', 'Origin', 'Verifier tags']

    violations: list[str] = []
    for i, prior_row in enumerate(prior_rows):
        if i >= len(current_rows):
            row_id = prior_row[0] if prior_row else str(i + 1)
            violations.append(f'Row {row_id}: present in prior attempt but missing in current')
            continue
        current_row = current_rows[i]
        max_cols = max(len(prior_row), len(current_row))
        for j in range(max_cols):
            prior_cell = prior_row[j] if j < len(prior_row) else ''
            current_cell = current_row[j] if j < len(current_row) else ''
            if prior_cell != current_cell:
                col_label = col_names[j] if j < len(col_names) else f'col{j + 1}'
                row_id = prior_row[0] if prior_row else str(i + 1)
                violations.append(
                    f'Row {row_id} / {col_label}: '
                    f'prior="{prior_cell[:60]}" → current="{current_cell[:60]}"'
                )

    return (len(violations) == 0), violations


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

GATES = {
    'w1': lambda draft, turn: check_w1(draft),
    'w2': lambda draft, turn: check_w2(draft),
    'w3': lambda draft, turn: check_w3(draft),
    'w4': check_w4,
    'w5': check_w5,
    'w6': lambda draft, turn: check_w6(draft),
}


def main() -> None:
    gate_name = sys.argv[1].lower() if len(sys.argv) > 1 else ''

    # Two-file drift check has a different signature
    if gate_name == 'coverage-matrix-drift':
        if len(sys.argv) < 4:
            sys.stderr.write('Usage: gates.py coverage-matrix-drift <prior_file> <current_file>\n')
            sys.exit(2)
        ok, violations = check_coverage_matrix_drift(sys.argv[2], sys.argv[3])
        print('PASS' if ok else 'FAIL')
        for v in violations:
            print(v)
        return

    if len(sys.argv) < 3:
        sys.stderr.write('Usage: gates.py <gate> <draft_file> [turn]\n')
        sys.exit(2)

    draft_path = sys.argv[2]
    turn = int(sys.argv[3]) if len(sys.argv) > 3 else 1

    if gate_name not in GATES:
        sys.stderr.write(f'Unknown gate: {gate_name}. Valid: {", ".join(GATES)}, coverage-matrix-drift\n')
        sys.exit(2)

    draft = _load(draft_path)
    ok, violations = GATES[gate_name](draft, turn)

    if ok:
        print('PASS')
    else:
        print('FAIL')
        for v in violations:
            print(v)


if __name__ == '__main__':
    main()

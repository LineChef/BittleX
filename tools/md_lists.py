"""Markdown pipe tables are not used in this project's documentation (owner, 2026-11-11): every table is a bulleted list, one bullet per row.

`convert(text)` turns the pipe tables in markdown text into lists (code fences are left alone) and returns (new_text, tables_converted). A row's first cell is the bold lead of its bullet; with two
columns the second follows after a colon; with more, each further cell follows as `Header: value`, separated by semicolons; empty cells are left out. The doc generators in tools/ pass their output through it,
so a regenerated page never brings a table back; `tools/check_docs.py` flags any table that is written by hand. `python tools/md_lists.py FILE...` converts files in place.
"""
import re
import sys

SEP = re.compile(r'^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$')
ROW = re.compile(r'^\s*\|.*\|\s*$')
SPLIT = re.compile(r'(?<!\\)\|')


def cells(line):
    s = line.strip()
    if s.startswith('|'):
        s = s[1:]
    if s.endswith('|') and not s.endswith('\\|'):
        s = s[:-1]
    return [c.replace('\\|', '|').replace('<br>', ' ').replace('<br/>', ' ').strip() for c in SPLIT.split(s)]


def bullet(prefix, head, row):
    row = row + [''] * (len(head) - len(row))
    first = row[0]
    if len(head) == 1:
        return f"{prefix}- {first}"
    lead = first if (not first or first.startswith('**')) else f"**{first}**"
    rest = [(h, c) for h, c in zip(head[1:], row[1:]) if c]
    if not rest:
        return f"{prefix}- {lead}"
    if len(head) == 2:
        return f"{prefix}- {lead}: {rest[0][1]}"
    return f"{prefix}- {lead}: " + "; ".join(f"{h}: {c}" if h else c for h, c in rest)


def convert(text):
    lines = text.split('\n')
    out, i, fence, n = [], 0, None, 0
    while i < len(lines):
        ln = lines[i]
        m = re.match(r'^\s*(```|~~~)', ln)
        if m:
            if fence is None:
                fence = m.group(1)
            elif m.group(1) == fence:
                fence = None
            out.append(ln); i += 1; continue
        if fence is None and ROW.match(ln) and i + 1 < len(lines) and SEP.match(lines[i + 1]) and '|' in lines[i + 1]:
            prefix = re.match(r'^\s*', ln).group(0)
            head = cells(ln)
            j = i + 2
            while j < len(lines) and ROW.match(lines[j]):
                out.append(bullet(prefix, head, cells(lines[j])))
                j += 1
            n += 1
            i = j
            continue
        out.append(ln); i += 1
    return '\n'.join(out), n


if __name__ == '__main__':
    tot = 0
    for p in sys.argv[1:]:
        s = open(p, encoding='utf-8').read()
        new, n = convert(s)
        if n:
            open(p, 'w', encoding='utf-8').write(new)
            tot += n
    print("tables converted:", tot)

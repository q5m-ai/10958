"""Verify a complete solver range and save CSVs, an offline report, SVG and PNG.

Uses Python's standard library. PNG rendering additionally uses the host's
existing libcairo via ctypes; no package installation or network access.
"""
import argparse
import ast
import csv
import ctypes as C
import ctypes.util
from datetime import datetime, timezone
import hashlib
from html import escape
import json
import math
from pathlib import Path
import re

from verify import BOUND, evaluate

ROOT = Path(__file__).resolve().parent
FOUND = 'found'
MISSING = 'not_found_within_bounds'
WIDTH, HEIGHT = 1440, 1100


def load_and_verify(path, start, end):
    rows = []
    cumulative_missing = 0
    expected = start
    seconds = None
    with path.open() as stream:
        for line in stream:
            timing = re.match(r'Seconds: ([0-9.eE+-]+);', line)
            if timing:
                seconds = float(timing[1])
            match = re.fullmatch(r'(\d+): (NOT FOUND|\(.+\)|\d+)\n?', line)
            if not match:
                continue
            n, expression = int(match[1]), match[2]
            if n != expected:
                raise ValueError(f'Missing, duplicate, or unordered target: expected {expected}, got {n}')
            expected += 1
            found = expression != 'NOT FOUND'
            if found:
                if ''.join(re.findall(r'\d', expression)) != '123456789':
                    raise ValueError(f'Bad digit sequence at target {n}')
                value = evaluate(ast.parse(expression.replace('^', '**'), mode='eval'))
                if value != n:
                    raise ValueError(f'Invalid witness for {n}: {expression} = {value}')
            else:
                cumulative_missing += 1
                expression = ''
            rows.append({
                'number': n,
                'status': FOUND if found else MISSING,
                'expression': expression,
                'witness_verified': 'true' if found else '',
                'cumulative_not_found': cumulative_missing,
                'cumulative_not_found_rate': cumulative_missing / (n - start + 1),
            })
    if expected != end + 1 or seconds is None:
        raise ValueError(f'Incomplete run: ended at {expected - 1}, expected {end} and completion footer')
    return rows, seconds


def format_expression(node, parent_precedence=0):
    """Flatten rational sums/products, preserving digit order and power grouping."""
    def terms(child, sign=1):
        if isinstance(child, ast.BinOp) and isinstance(child.op, (ast.Add, ast.Sub)):
            yield from terms(child.left, sign)
            yield from terms(child.right, -sign if isinstance(child.op, ast.Sub) else sign)
        elif isinstance(child, ast.UnaryOp) and isinstance(child.op, ast.USub):
            yield from terms(child.operand, -sign)
        else:
            yield sign, child

    def factors(child, divided=False):
        if isinstance(child, ast.BinOp) and isinstance(child.op, (ast.Mult, ast.Div)):
            yield from factors(child.left, divided)
            yield from factors(child.right, not divided if isinstance(child.op, ast.Div) else divided)
        else:
            yield divided, child

    if isinstance(node, ast.Constant) and type(node.value) is int:
        text, precedence = str(node.value), 4
    elif isinstance(node, ast.UnaryOp) or (isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub))):
        parts = []
        for sign, child in terms(node):
            prefix = ('-' if sign < 0 else '') if not parts else (' - ' if sign < 0 else ' + ')
            parts.append(prefix + format_expression(child))
        text, precedence = ''.join(parts), 1
    elif isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Mult, ast.Div)):
        parts = []
        for divided, child in factors(node):
            prefix = (' / ' if divided else ' * ') if parts else ''
            parts.append(prefix + format_expression(child, 2))
        text, precedence = ''.join(parts), 2
    elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
        text = f'{format_expression(node.left, 4)}^{format_expression(node.right, 3)}'
        precedence = 3
    else:
        raise ValueError(f'Unsupported expression: {ast.dump(node)}')
    return f'({text})' if precedence < parent_precedence else text


def solution_lines(rows):
    """Return one equation per target; reverify every formatted witness exactly."""
    lines = []
    for row in rows:
        n = row['number']
        if row['status'] == MISSING:
            expression = 'NOT FOUND'
        else:
            tree = ast.parse(row['expression'].replace('^', '**'), mode='eval')
            expression = format_expression(tree.body)
            if ''.join(re.findall(r'\d', expression)) != '123456789':
                raise ValueError(f'Formatting changed digit order for {n}')
            if evaluate(ast.parse(expression.replace('^', '**'), mode='eval')) != n:
                raise ValueError(f'Formatting changed the value for {n}')
        lines.append(f'{n} = {expression}\n')
    return ''.join(lines)


def make_bands(rows, width):
    bands = []
    for i in range(0, len(rows), width):
        group = rows[i:i + width]
        missing = sum(row['status'] == MISSING for row in group)
        bands.append({
            'start': group[0]['number'], 'end': group[-1]['number'],
            'tested': len(group), 'found': len(group) - missing,
            'not_found_within_bounds': missing, 'not_found_rate': missing / len(group),
        })
    return bands


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]), lineterminator='\n')
        writer.writeheader()
        writer.writerows(rows)


class Canvas:
    """One small drawing scene, written as both vector SVG and Cairo PNG."""
    def __init__(self):
        self.items = []

    def rect(self, x, y, w, h, color):
        self.items.append(('rect', x, y, w, h, color))

    def line(self, points, color='#dce2ed', width=1):
        self.items.append(('line', points, color, width))

    def polygon(self, points, color, opacity=1):
        self.items.append(('polygon', points, color, opacity))

    def text(self, x, y, text, size=14, color='#475569', bold=False, anchor='start'):
        self.items.append(('text', x, y, str(text), size, color, bold, anchor))

    def svg(self):
        parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" '
                 f'viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title desc">',
                 '<title id="title">Ordered digits 1–9: solver not-found rates through 100,000</title>',
                 '<desc id="desc">Bar chart for disjoint 10,000-number bands, followed by a cumulative '
                 'not-found rate chart. Not found is not a proof of impossibility.</desc>']
        for item in self.items:
            kind, *a = item
            if kind == 'rect':
                x, y, w, h, color = a
                parts.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" fill="{color}"/>')
            elif kind in ('line', 'polygon'):
                points, color, extra = a
                coords = ' '.join(f'{x:.2f},{y:.2f}' for x, y in points)
                if kind == 'line':
                    parts.append(f'<polyline points="{coords}" fill="none" stroke="{color}" '
                                 f'stroke-width="{extra}" stroke-linejoin="round"/>')
                else:
                    parts.append(f'<polygon points="{coords}" fill="{color}" opacity="{extra}"/>')
            else:
                x, y, text, size, color, bold, anchor = a
                parts.append(f'<text x="{x}" y="{y}" font-family="DejaVu Sans,Arial,sans-serif" '
                             f'font-size="{size}" fill="{color}" font-weight="{700 if bold else 400}" '
                             f'text-anchor="{anchor}">{escape(text)}</text>')
        parts.append('</svg>')
        return '\n'.join(parts)

    def png(self, path):
        library = ctypes.util.find_library('cairo')
        if library is None:
            return False
        lib = C.CDLL(library)
        ptr, double, integer = C.c_void_p, C.c_double, C.c_int
        def bind(name, result, arguments):
            fn = getattr(lib, 'cairo_' + name)
            fn.restype, fn.argtypes = result, arguments
            return fn
        class Extents(C.Structure):
            _fields_ = [(name, double) for name in
                        ('x_bearing', 'y_bearing', 'width', 'height', 'x_advance', 'y_advance')]
        image = bind('image_surface_create', ptr, [integer, integer, integer])
        create = bind('create', ptr, [ptr])
        destroy = bind('destroy', None, [ptr])
        surface_destroy = bind('surface_destroy', None, [ptr])
        source = bind('set_source_rgba', None, [ptr, double, double, double, double])
        rectangle = bind('rectangle', None, [ptr, double, double, double, double])
        fill = bind('fill', None, [ptr])
        move = bind('move_to', None, [ptr, double, double])
        line_to = bind('line_to', None, [ptr, double, double])
        close = bind('close_path', None, [ptr])
        stroke = bind('stroke', None, [ptr])
        width = bind('set_line_width', None, [ptr, double])
        face = bind('select_font_face', None, [ptr, C.c_char_p, integer, integer])
        size = bind('set_font_size', None, [ptr, double])
        extents = bind('text_extents', None, [ptr, C.c_char_p, C.POINTER(Extents)])
        show = bind('show_text', None, [ptr, C.c_char_p])
        write = bind('surface_write_to_png', integer, [ptr, C.c_char_p])
        status = bind('status', integer, [ptr])
        surface = image(0, WIDTH, HEIGHT)  # CAIRO_FORMAT_ARGB32
        context = create(surface)
        def color(hex_color, alpha=1):
            rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
            source(context, *rgb, alpha)
        try:
            for item in self.items:
                kind, *a = item
                if kind == 'rect':
                    x, y, w, h, col = a
                    color(col); rectangle(context, x, y, w, h); fill(context)
                elif kind in ('line', 'polygon'):
                    points, col, extra = a
                    color(col, extra if kind == 'polygon' else 1)
                    move(context, *points[0])
                    for point in points[1:]:
                        line_to(context, *point)
                    if kind == 'polygon':
                        close(context); fill(context)
                    else:
                        width(context, extra); stroke(context)
                else:
                    x, y, text, font_size, col, bold, anchor = a
                    color(col)
                    face(context, b'DejaVu Sans', 0, int(bold))
                    size(context, font_size)
                    encoded = text.encode('utf-8')
                    box = Extents()
                    extents(context, encoded, C.byref(box))
                    if anchor == 'middle': x -= box.x_advance / 2
                    if anchor == 'end': x -= box.x_advance
                    move(context, x, y); show(context, encoded)
            if status(context) != 0 or write(surface, str(path).encode()) != 0:
                raise RuntimeError('Cairo could not render PNG')
        finally:
            destroy(context); surface_destroy(surface)
        return True


def plot(rows, bands):
    c = Canvas()
    total, missing = len(rows), rows[-1]['cumulative_not_found']
    found = total - missing
    c.rect(0, 0, WIDTH, HEIGHT, '#f3f6fb')
    c.text(64, 58, 'Ordered digits 1–9: search outcomes up to 100,000', 29, '#0f172a', True)
    c.text(64, 88, 'Every positive integer from 1 to 100,000 tested · exact rational arithmetic · local solver only', 16)
    c.text(64, 115, '“Not found” means not found within this solver’s bounds — NOT proven impossible.', 15, '#a34c0c', True)
    cards = [('TESTED', f'{total:,}', 'Complete range: 1–100,000', '#0f172a'),
             ('EXPRESSION FOUND', f'{found:,}', 'Every witness independently verified exactly', '#087f5b'),
             ('NOT FOUND WITHIN BOUNDS', f'{missing:,}', f'{missing/total:.3%} of all targets', '#c45512')]
    for i, (title, value, subtitle, col) in enumerate(cards):
        x = 64 + i * 444
        c.rect(x, 142, 424, 88, '#ffffff')
        c.text(x + 18, 165, title, 12, '#64748b', True)
        c.text(x + 18, 202, value, 31, col, True)
        c.text(x + 18, 220, subtitle, 12)

    x, width = 145, 1175
    c.rect(64, 250, 1312, 355, '#ffffff')
    c.text(86, 282, 'Local rate: disjoint bands of 10,000 consecutive integers', 20, '#0f172a', True)
    c.text(86, 307, 'Each bar is the percentage not found in that band, not the cumulative percentage.', 14)
    top, bottom = 340, 540
    max_rate = max(b['not_found_rate'] for b in bands) * 100
    ceiling = max(10, math.ceil(max_rate / 10) * 10)
    for tick in range(0, ceiling + 1, 10):
        y = bottom - tick / ceiling * (bottom - top)
        c.line([(x, y), (x + width, y)])
        c.text(x - 14, y + 5, f'{tick}%', 13, anchor='end')
    step = width / len(bands)
    for i, band in enumerate(bands):
        center = x + (i + 0.5) * step
        pct = band['not_found_rate'] * 100
        h = pct / ceiling * (bottom - top)
        c.rect(center - step * .34, bottom - h, step * .68, h, '#e57b35')
        c.text(center, bottom - h - 9, f'{pct:.2f}%', 14, '#9a4210', True, 'middle')
        c.text(center, 565, f'{band["start"]:,}–', 11, anchor='middle')
        c.text(center, 583, f'{band["end"]:,}', 11, anchor='middle')

    c.rect(64, 628, 1312, 352, '#ffffff')
    c.text(86, 662, 'Cumulative rate: choose an integer uniformly from 1 through N', 20, '#0f172a', True)
    c.text(86, 688, 'Fraction of the first N targets not found by this solver. Earlier easy numbers lower this average.', 14)
    top, bottom = 726, 910
    ceiling = max(5, math.ceil(100 * missing / total / 5) * 5)
    for tick in range(0, ceiling + 1, 5):
        y = bottom - tick / ceiling * (bottom - top)
        c.line([(x, y), (x + width, y)])
        c.text(x - 14, y + 5, f'{tick}%', 13, anchor='end')
    for n in range(0, total + 1, 10000):
        xx = x + n / total * width
        c.text(xx, 934, f'{n//1000}k' if n else '0', 12, anchor='middle')
    points = []
    for row in rows:
        if row['number'] in (1, total) or row['number'] % 100 == 0:
            points.append((x + row['number'] / total * width,
                           bottom - row['cumulative_not_found_rate'] * 100 / ceiling * (bottom - top)))
    c.polygon([(points[0][0], bottom), *points, (points[-1][0], bottom)], '#2563eb', .10)
    c.line(points, '#2563eb', 3)
    c.text(x + width - 3, points[-1][1] - 12, f'{missing/total:.3%}', 17, '#1d4ed8', True, 'end')
    c.text(x + width / 2, 961, 'Upper limit N', 14, anchor='middle')
    c.text(64, 1017, 'Limits: rational intermediates only; every reduced numerator and denominator is at most 2^63 − 1.', 14)
    c.text(64, 1042, 'All digits 1–9 once in order; + − × ÷ ^, parentheses, adjacent-digit grouping and unary minus.', 14)
    c.text(64, 1071, 'The cumulative line is plotted every 100 targets. CSVs retain all 100,000 outcomes and every found expression.', 13)
    return c


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save_report(directory, rows, bands, scene, metadata):
    svg = scene.svg()
    (directory / 'plot.svg').write_text(svg)
    png = scene.png(directory / 'plot.png')
    table_rows = ''.join(
        f'<tr><td>{b["start"]:,}–{b["end"]:,}</td><td>{b["found"]:,}</td>'
        f'<td>{b["not_found_within_bounds"]:,}</td><td>{b["not_found_rate"]:.2%}</td></tr>'
        for b in bands)
    png_link = '<a href="plot.png">PNG plot</a> · ' if png else ''
    html = f'''<!doctype html>
<html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Ordered digits 1–9: results through 100,000</title>
<style>
body{{margin:0;background:#f3f6fb;color:#172033;font:16px/1.6 system-ui,sans-serif}}
main{{max-width:1440px;margin:auto}}svg{{width:100%;height:auto;display:block}}
section{{max-width:1120px;margin:20px auto 32px;padding:24px;background:white}}
h2{{line-height:1.3}}a{{color:#1d4ed8}}table{{border-collapse:collapse;width:100%;font-variant-numeric:tabular-nums}}
th,td{{padding:8px 12px;text-align:right;border-bottom:1px solid #e2e8f0}}th:first-child,td:first-child{{text-align:left}}
code{{overflow-wrap:anywhere}}pre{{overflow:auto;background:#f1f5f9;padding:14px}}.note{{border-left:4px solid #e57b35;padding-left:16px}}
</style><main>{svg}
<section><h2>Saved files</h2><p>{png_link}<a href="plot.svg">SVG plot</a> ·
<a href="results.csv">All 100,000 results and witnesses (CSV)</a> ·
<a href="bands_10000.csv">10,000-number bands (CSV)</a> ·
<a href="bands_1000.csv">1,000-number bands (CSV)</a> ·
<a href="not_found.csv">Not-found list (CSV)</a> · <a href="metadata.json">Run metadata</a></p>
<h2>Rates by 10,000-number band</h2><table><thead><tr><th>Inclusive range</th><th>Found</th>
<th>Not found within bounds</th><th>Not-found rate</th></tr></thead><tbody>{table_rows}</tbody></table>
<h2>What this measures</h2><p class="note">This is a complete census of the solver’s outcomes, not a statistical sample
and not a proof of mathematical impossibility. Each found expression was independently parsed and evaluated with Python
exact fractions; its digit sequence was checked to be <code>123456789</code>. All {metadata['found']:,} witnesses passed.</p>
<p>The rules allow only the original nine digits in order, adjacent literal-digit concatenation,
parentheses, unary negation, and +, −, ×, ÷, exponentiation. There are no factorials, inserted constants,
rounding operations, square-root operators, or concatenations of calculated results.</p>
<p>The exact solver keeps only rational intermediate values, with reduced numerator and denominator magnitudes
at most <code>{BOUND}</code>. Fractional exponents are retained when their result is exactly rational.
Solutions involving larger rational values, irrational intermediates, or complex intermediates can be missed.
Thus the plotted not-found percentages are upper bounds on the true fraction of impossible cases, not estimates of proven impossibility.</p>
<p>For a band the rate is <code>not_found / tested_in_band</code>. The cumulative rate at N is
<code>not_found_among_1_to_N / N</code>. No fitted curve, extrapolation, or confidence interval is added.
The cumulative graphic samples every 100 targets; the CSV contains every target.</p>
<h2>Reproduce locally</h2><pre>make
./exact --range 1 100000 &gt; scan-100000/raw.txt
python3 analyze_scan.py</pre>
<p>Only the local solver was used to generate the data. No web search or external dataset was used.
The solver run took {metadata['solver_seconds']:.2f} seconds; source and raw-data SHA-256 hashes are in the metadata.</p>
</section></main></html>'''
    (directory / 'report.html').write_text(html)
    return png


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', type=Path, default=ROOT / 'scan-100000')
    args = parser.parse_args()
    directory = args.directory
    rows, seconds = load_and_verify(directory / 'raw.txt', 1, 100000)
    bands = make_bands(rows, 10000)
    missing = rows[-1]['cumulative_not_found']
    assert sum(b['not_found_within_bounds'] for b in bands) == missing
    assert all(b['tested'] == 10000 for b in bands)
    assert [r['number'] for r in rows[:11111] if r['status'] == MISSING] == [10958]
    assert rows[25283 - 1]['status'] == MISSING
    solutions_path = directory.parent / 'solutions.txt'
    solutions_path.write_text(solution_lines(rows), encoding='utf-8')
    write_csv(directory / 'results.csv', rows)
    write_csv(directory / 'bands_10000.csv', bands)
    write_csv(directory / 'bands_1000.csv', make_bands(rows, 1000))
    write_csv(directory / 'not_found.csv', [{'number': row['number']} for row in rows if row['status'] == MISSING])
    metadata = {
        'created_utc': datetime.now(timezone.utc).isoformat(),
        'start': 1, 'end': 100000, 'tested': len(rows), 'found': len(rows) - missing,
        'not_found_within_bounds': missing, 'not_found_rate': missing / len(rows),
        'every_found_witness_independently_verified': True,
        'reduced_numerator_denominator_limit': BOUND,
        'intermediate_values': 'rational only',
        'not_found_is_proof_of_impossibility': False,
        'solver_seconds': seconds,
        'solver_command': ['./exact', '--range', '1', '100000'],
        'sha256': {name: sha256(path) for name, path in {
            'exact.cpp': ROOT / 'exact.cpp',
            'verify.py': ROOT / 'verify.py', 'analyze_scan.py': Path(__file__),
            'raw.txt': directory / 'raw.txt', 'results.csv': directory / 'results.csv',
            'solutions.txt': solutions_path,
        }.items()},
        'band_width': 10000, 'additional_band_width': 1000, 'cumulative_plot_step': 100,
    }
    scene = plot(rows, bands)
    metadata['png_rendered'] = save_report(directory, rows, bands, scene, metadata)
    (directory / 'metadata.json').write_text(json.dumps(metadata, indent=2) + '\n')
    print(f'Exactly verified {len(rows) - missing:,} witnesses; {missing:,} targets not found within bounds.')
    print(f'Overall not-found rate: {missing / len(rows):.3%}')
    for b in bands:
        print(f'{b["start"]:>6,}–{b["end"]:>7,}: {b["not_found_within_bounds"]:>5,} not found ({b["not_found_rate"]:.2%})')
    print(f'Saved CSVs, offline HTML, SVG, metadata and {"PNG" if metadata["png_rendered"] else "no PNG (libcairo unavailable)"} in {directory}')


if __name__ == '__main__':
    main()

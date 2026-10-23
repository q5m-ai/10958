"""Synthetic validation checks plus saved-scan integrity checks."""
import csv
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import struct
import subprocess
import tempfile
import unittest
import xml.etree.ElementTree as ET

import analyze_scan as scan

ROOT = Path(__file__).resolve().parent
FIXTURE = '''Arithmetic self-tests passed
1: (1^(2+3+4+5+6+7+8+9))
2: NOT FOUND
3: (1+2+(3-4+5+6+7-8-9))
Seconds: 0.01; reduced numerator/denominator limit: 9223372036854775807
'''


class ScanTests(unittest.TestCase):
    def load(self, text, start=1, end=3):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'synthetic.txt'
            path.write_text(text)
            return scan.load_and_verify(path, start, end)

    def test_exact_witnesses_and_partial_band_denominator(self):
        rows, seconds = self.load(FIXTURE)
        self.assertEqual(seconds, .01)
        self.assertEqual([row['cumulative_not_found'] for row in rows], [0, 1, 1])
        self.assertEqual(rows[-1]['cumulative_not_found_rate'], 1 / 3)
        self.assertEqual(rows[1]['witness_verified'], '')
        bands = scan.make_bands(rows, 2)
        self.assertEqual([b['tested'] for b in bands], [2, 1])
        self.assertEqual([b['not_found_rate'] for b in bands], [.5, 0])

    def test_rejects_incomplete_and_duplicate_results(self):
        with self.assertRaises(ValueError):
            self.load(FIXTURE.replace('2: NOT FOUND\n', ''))
        with self.assertRaises(ValueError):
            self.load(FIXTURE.replace('2: NOT FOUND\n', '2: NOT FOUND\n2: NOT FOUND\n'))
        with self.assertRaises(ValueError):
            self.load(FIXTURE.split('Seconds:')[0])

    def test_rejects_wrong_digits_and_wrong_value(self):
        with self.assertRaises(ValueError):
            self.load(FIXTURE.replace('3-4+5+6+7-8-9', '3-4+5+6+7-9-8'))
        with self.assertRaises(ValueError):
            self.load(FIXTURE.replace('3-4+5+6+7-8-9', '3+4+5+6+7-8-9'))

    def test_rejects_division_by_zero_and_non_arithmetic(self):
        expression = '(1^(2+3+4+5+6+7+8+9))'
        with self.assertRaises(ZeroDivisionError):
            self.load(FIXTURE.replace(expression, '((1+2-3)/(4-5-6+7)*(8+9))'))
        with self.assertRaises(ValueError):
            self.load(FIXTURE.replace(expression, '(foo(123456789))'))

    def test_inclusive_cpp_range(self):
        text = subprocess.check_output([str(ROOT / 'exact'), '--range', '1', '3'], text=True)
        rows, _ = self.load(text)
        self.assertEqual([r['number'] for r in rows], [1, 2, 3])
        self.assertTrue(all(r['status'] == scan.FOUND for r in rows))

    def test_every_saved_witness_independently(self):
        rows, _ = scan.load_and_verify(ROOT / 'scan-100000' / 'raw.txt', 1, 100000)
        self.assertEqual(sum(r['status'] == scan.FOUND for r in rows), 82167)
        self.assertEqual(rows[-1]['cumulative_not_found'], 17833)

    def test_succinct_format_preserves_grouping_and_signs(self):
        examples = ['1-(2-(3-4))', '1/(2/(3/4))', '1*(-2+3)',
                    '(1-2)**(3-4)', '1**(2**3)', '(1**2)**3', '-(1-(2*3))']
        for source in examples:
            with self.subTest(source=source):
                tree = scan.ast.parse(source, mode='eval')
                formatted = scan.format_expression(tree.body)
                self.assertEqual(scan.evaluate(tree), scan.evaluate(scan.ast.parse(formatted.replace('^', '**'), mode='eval')))
        rows, _ = self.load(FIXTURE)
        self.assertEqual(scan.solution_lines(rows),
                         '1 = 1^(2 + 3 + 4 + 5 + 6 + 7 + 8 + 9)\n'
                         '2 = NOT FOUND\n'
                         '3 = 1 + 2 + 3 - 4 + 5 + 6 + 7 - 8 - 9\n')

    def test_complete_plain_text_solutions(self):
        rows, _ = scan.load_and_verify(ROOT / 'scan-100000' / 'raw.txt', 1, 100000)
        text = (ROOT / 'solutions.txt').read_text()
        self.assertEqual(text, scan.solution_lines(rows))
        lines = text.splitlines()
        self.assertEqual(len(lines), 100000)
        self.assertEqual(sum(line.endswith(' = NOT FOUND') for line in lines), 17833)
        self.assertEqual(lines[10957], '10958 = NOT FOUND')
        for n, line in enumerate(lines, 1):
            self.assertTrue(line.startswith(f'{n} = '))

    def test_saved_scan_is_complete_and_consistent(self):
        directory = ROOT / 'scan-100000'
        with (directory / 'results.csv').open(newline='') as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual([int(r['number']) for r in rows], list(range(1, 100001)))
        missing = 0
        for n, row in enumerate(rows, 1):
            self.assertIn(row['status'], (scan.FOUND, scan.MISSING))
            if row['status'] == scan.MISSING:
                missing += 1
                self.assertEqual(row['expression'], '')
                self.assertEqual(row['witness_verified'], '')
            else:
                self.assertEqual(row['witness_verified'], 'true')
                self.assertNotEqual(row['expression'], '')
            self.assertEqual(int(row['cumulative_not_found']), missing)
            self.assertAlmostEqual(float(row['cumulative_not_found_rate']), missing / n)
        self.assertEqual(missing, 17833)
        with (directory / 'bands_10000.csv').open(newline='') as stream:
            bands = list(csv.DictReader(stream))
        expected_counts = [0, 26, 293, 575, 1207, 1877, 2281, 3291, 4097, 4186]
        self.assertEqual([int(b['not_found_within_bounds']) for b in bands], expected_counts)
        self.assertEqual(sum(expected_counts), missing)
        metadata = json.loads((directory / 'metadata.json').read_text())
        self.assertEqual(metadata['found'], 82167)
        self.assertTrue(metadata['every_found_witness_independently_verified'])
        for name in ('raw.txt', 'results.csv'):
            self.assertEqual(hashlib.sha256((directory / name).read_bytes()).hexdigest(), metadata['sha256'][name])
        for name in ('exact.cpp', 'verify.py', 'analyze_scan.py', 'solutions.txt'):
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), metadata['sha256'][name])
        with (directory / 'not_found.csv').open(newline='') as stream:
            not_found = [int(r['number']) for r in csv.DictReader(stream)]
        self.assertEqual(not_found, [int(r['number']) for r in rows if r['status'] == scan.MISSING])

    def test_saved_plots_and_local_report_links(self):
        directory = ROOT / 'scan-100000'
        svg = ET.parse(directory / 'plot.svg').getroot()
        self.assertEqual(svg.attrib['viewBox'], f'0 0 {scan.WIDTH} {scan.HEIGHT}')
        png = (directory / 'plot.png').read_bytes()
        self.assertEqual(png[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', png[16:24]), (scan.WIDTH, scan.HEIGHT))
        class Links(HTMLParser):
            def handle_starttag(self, tag, attrs):
                attrs = dict(attrs)
                if tag == 'a':
                    target = attrs['href']
                    if '://' in target or not (directory / target).is_file():
                        raise AssertionError(f'Invalid local report link: {target}')
        Links().feed((directory / 'report.html').read_text())


if __name__ == '__main__':
    unittest.main(verbosity=2)

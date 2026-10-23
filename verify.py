"""Independent exact arithmetic, syntax, and small exhaustive-DP checks."""
import ast
from decimal import Decimal, localcontext
from fractions import Fraction as Q
from functools import lru_cache
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parent
BOUND = 2**63 - 1


def iroot(a, n):
    if n == 1 or a <= 1:
        return a
    if n >= a.bit_length():
        return None
    lo, hi = 1, 1 << ((a.bit_length() + n - 1) // n)
    while lo <= hi:
        mid = (lo + hi) // 2
        p = mid ** n
        if p == a:
            return mid
        if p < a:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def qpow(a, b):
    if not a and b <= 0:
        return None
    if a < 0:
        if b.denominator % 2 == 0:
            return None
        z = qpow(-a, b)
        return -z if z is not None and b.numerator % 2 else z
    n, d = iroot(a.numerator, b.denominator), iroot(a.denominator, b.denominator)
    if n is None or d is None:
        return None
    # Discovery search uses bounded rationals. A nontrivial rational raised
    # to a numerator over 63 cannot fit the chosen numerator/denominator cap.
    if max(n, d) > 1 and abs(b.numerator) > 63:
        return None
    result = Q(n, d) ** b.numerator
    if max(abs(result.numerator), result.denominator) > BOUND:
        return None
    return result


def evaluate(node):
    if isinstance(node, ast.Expression):
        return evaluate(node.body)
    if isinstance(node, ast.Constant) and type(node.value) is int:
        return Q(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        return -evaluate(node.operand)
    if not isinstance(node, ast.BinOp):
        raise ValueError(f'Invalid expression: {ast.dump(node)}')
    a, b = evaluate(node.left), evaluate(node.right)
    if isinstance(node.op, ast.Add): return a + b
    if isinstance(node.op, ast.Sub): return a - b
    if isinstance(node.op, ast.Mult): return a * b
    if isinstance(node.op, ast.Div): return a / b
    if isinstance(node.op, ast.Pow):
        value = qpow(a, b)
        assert value is not None, (a, b)
        return value
    raise ValueError('Invalid operator')


@lru_cache(None)
def exhaustive(s):
    out = {Q(int(s))}
    for split in range(1, len(s)):
        for a in exhaustive(s[:split]):
            for b in exhaustive(s[split:]):
                candidates = [a + b, abs(a - b), a * b]
                if b:
                    candidates.append(a / b)
                for e in (b, -b):
                    power = qpow(a, e)
                    if power is not None:
                        candidates.append(power)
                out.update(q for q in candidates if max(q.numerator, q.denominator) <= BOUND)
    return out


def main():
    small = subprocess.check_output([str(ROOT / 'exact'), '--dump-small'], text=True)
    actual = {}
    for line in small.splitlines():
        if line.startswith('VALUE\t'):
            _, digits, n, d = line.split('\t')
            actual.setdefault(digits, set()).add(Q(int(n), int(d)))
    for digits, values in actual.items():
        expected = exhaustive(digits)
        assert values == expected, (digits, expected - values, values - expected)
    print(f'Independent exhaustive check: all {len(actual)} intervals of length 1–4 match.')
    missing, verified = [], 0
    for line in (ROOT / 'fixtures' / 'range-0-11111.txt').read_text().splitlines():
        m = re.fullmatch(r'(\d+): (.+)', line)
        if not m:
            continue
        n, expr = int(m[1]), m[2]
        if expr.endswith('magnitudes'):
            continue
        if expr == 'NOT FOUND':
            missing.append(n)
            continue
        assert ''.join(re.findall(r'\d', expr)) == '123456789', expr
        value = evaluate(ast.parse(expr.replace('^', '**'), mode='eval'))
        assert value == n, (n, expr, value)
        verified += 1
    print(f'Independently verified {verified} exact witnesses in 0–11111.')
    print(f'No witness found for: {missing}')
    assert verified == 11111 and missing == [10958]
    suffix = subprocess.check_output([str(ROOT / 'exact'), '--suffix', '10959'], text=True)
    assert 'Search digits: 23456789\n' in suffix
    assert '10959: NOT FOUND\n' in suffix
    print('Leading -1 + suffix: no bounded exact witness for suffix target 10959.')
    with localcontext() as context:
        context.prec = 100
        x = Decimal(1) + (Decimal(2) - Decimal(3) ** (Decimal(4)*5/6/7)) ** Decimal(-8) + 9
        print('Numerical near-hit at 100 decimal digits:')
        print(x)
        print('Absolute error:', x - 10958)
        assert Decimal('0.0020579102') < x - 10958 < Decimal('0.0020579103')
        y = -Decimal(1) + Decimal(2)**(Decimal(3)**4/5)/(Decimal(6)+Decimal(7)/8) + 9
        print('Leading -1 numerical near-hit:', y)
        print('Shortfall:', 10958 - y)
        assert Decimal('0.0224882784') < 10958 - y < Decimal('0.0224882785')


if __name__ == '__main__':
    main()

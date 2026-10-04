"""Fail on coverage regressions per layer; never average unrelated languages."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
full = '--full' in sys.argv
failures = []

def check(label, value, minimum):
    print(f'{label}: {value:.2f}% (minimum {minimum:.2f}%)')
    if value + 1e-7 < minimum:
        failures.append(f'{label}: {value:.2f} < {minimum}')

python = json.loads((ROOT / ('coverage/python/combined.json' if full else 'coverage/python/coverage.json')).read_text())
# Whole-source denominators, including files not imported in a test process.
floors = (
    [('apps/api/', 74, 52), ('services/gctree/', 60, 47), ('services/clonaltree/', 77, 61)]
    if full else
    [('apps/api/', 65, 40), ('services/gctree/', 30, 20), ('services/clonaltree/', 29, 26)]
)
for prefix, line_floor, branch_floor in floors:
    rows = [value['summary'] for name, value in python['files'].items()
            if name.replace('\\', '/').startswith(prefix)]
    if not rows:
        raise SystemExit(f'No coverage measurements for {prefix}')
    lines = 100 * sum(r['covered_lines'] for r in rows) / sum(r['num_statements'] for r in rows)
    branches = 100 * sum(r['covered_branches'] for r in rows) / sum(r['num_branches'] for r in rows)
    check(prefix + ' lines', lines, line_floor)
    check(prefix + ' branches', branches, branch_floor)

web = json.loads((ROOT / 'coverage/web/coverage-summary.json').read_text())['total']
for metric, floor in [('lines', 17), ('statements', 17), ('branches', 78), ('functions', 64)]:
    check('web unit ' + metric, web[metric]['pct'], floor)
contracts = json.loads((ROOT / 'coverage/contracts/coverage-summary.json').read_text())['total']
for metric in ['lines', 'statements', 'branches', 'functions']:
    check('contracts ' + metric, contracts[metric]['pct'], 100)
if full:
    web_full = json.loads((ROOT / 'coverage/web-combined/coverage-summary.json').read_text())['total']
    for metric, floor in [('lines', 41), ('statements', 42), ('branches', 56), ('functions', 62)]:
        check('web unit + browser ' + metric, web_full[metric]['pct'], floor)
    for method, floor in [('dowser', 44), ('brepphylo', 61)]:
        check(method + ' R module lines', float((ROOT / f'coverage/{method}/percent.txt').read_text()), floor)
if failures:
    raise SystemExit('\nCoverage regression:\n' + '\n'.join(failures))

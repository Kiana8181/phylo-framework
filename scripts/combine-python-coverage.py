"""Merge host tests and real Docker subprocess data with unambiguous source paths."""
from pathlib import Path
import coverage

ROOT = Path(__file__).resolve().parents[1]
combined_path = ROOT / 'coverage/python/.coverage.combined'
merged = coverage.CoverageData(basename=str(combined_path))

def remap(name, layer):
    if name.startswith('/repo/apps/api/'):
        return str(ROOT / 'apps/api' / name.removeprefix('/repo/apps/api/'))
    if layer == 'clonaltree-e2e' and name.startswith('/srv/clonaltree/'):
        return str(ROOT / 'services/clonaltree' / name.removeprefix('/srv/clonaltree/'))
    if layer == 'gctree-e2e' and name.startswith('/srv/'):
        return str(ROOT / 'services/gctree' / name.removeprefix('/srv/'))
    return name

files = [ROOT / '.coverage']
for layer in ['api-e2e', 'gctree-e2e', 'clonaltree-e2e']:
    paths = list((ROOT / 'coverage' / layer).glob('.coverage.*'))
    if not paths:
        raise SystemExit(f'Missing subprocess coverage: {layer}. Stop instrumented containers gracefully first.')
    files.extend(paths)
for path in files:
    data = coverage.CoverageData(basename=str(path))
    data.read()
    merged.update(data, map_path=lambda name, layer=path.parent.name: remap(name, layer))
merged.write()
cov = coverage.Coverage(data_file=str(combined_path), config_file=str(ROOT / '.coveragerc'))
cov.load()
cov.xml_report(outfile=str(ROOT / 'coverage/python/combined.xml'))
cov.html_report(directory=str(ROOT / 'coverage/python/combined-html'))
cov.json_report(outfile=str(ROOT / 'coverage/python/combined.json'))
cov.report(skip_covered=True)

"""Real API -> PostgreSQL -> worker -> method -> MinIO -> result/download.

Requires docker-compose.test.yml --profile full. No mocks and no skips.
Compares structural/biological invariants, not incidental stochastic tree order.
"""
import asyncio
import hashlib
import json
import os
import time
from pathlib import Path
from uuid import uuid4
import httpx
import pytest
from jsonschema import Draft7Validator

from tests.support.accounts import register_verified

ROOT = Path(__file__).resolve().parents[2]
PARAMS = json.loads((ROOT / 'tests/fixtures/scientific-params.json').read_text())
SAMPLE = ROOT / 'apps/web/public/samples/ExampleAirr_clone_3128.tsv'
pytestmark = pytest.mark.scientific


def unwrap(response):
    response.raise_for_status()
    value = response.json()
    return value['data'] if isinstance(value, dict) and value.get('status') == 'success' and 'data' in value else value


@pytest.mark.parametrize('method', ['gctree', 'clonaltree', 'dowser', 'brepphylo'])
async def test_scientific_pipeline(method, tmp_path):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:58000', timeout=60, trust_env=False) as api:
        tag = uuid4().hex
        # Sign up as a person does: sign-up check, then the emailed confirmation link.
        await register_verified(api, f'{tag}@example.org', tag, 'e2e-password')
        init = unwrap(await api.post('/uploads/init', json={'original_filename': SAMPLE.name, 'mime_type': 'text/tab-separated-values'}))
        uploaded = unwrap(await api.put(init['content_url'], content=SAMPLE.read_bytes()))
        created = unwrap(await api.post(f'/runs?method={method}', json={'file_id': uploaded['file_id'], 'params': PARAMS[method]}))
        run_id = created['run_id']
        deadline = time.monotonic() + int(os.environ.get('SCIENTIFIC_TIMEOUT', '600'))
        terminal = None
        try:
            while time.monotonic() < deadline:
                status = unwrap(await api.get(f'/runs/{run_id}/status'))
                if status['status'] in ('DONE', 'ERROR', 'CANCELLED'):
                    terminal = status
                    break
                await asyncio.sleep(0.5)
            assert terminal is not None, f'{method} exceeded deadline: {status}'
            assert terminal['status'] == 'DONE', terminal
            result = unwrap(await api.get(f'/runs/{run_id}/result'))
            Draft7Validator(json.loads((ROOT / 'packages/contracts/result.schema.json').read_text())).validate(result)
            trees = unwrap(await api.get(f'/runs/{run_id}/trees'))
            if isinstance(trees, dict):
                trees = trees['trees']
            assert trees, f'{method} returned no scientific trees: {result}'
            tree = unwrap(await api.get(f"/runs/{run_id}/trees/{trees[0]['treeId']}"))
            assert tree['newick'].strip().endswith(';')
            assert '(' in tree['newick'] and ')' in tree['newick']
            lineage = tree['lineage_plot']
            nodes, edges = lineage['nodes'], lineage['edges']
            ids = {node['id'] for node in nodes}
            assert len(ids) == len(nodes), 'node identifiers must be unique'
            assert len(edges) == len(nodes) - 1, 'a tree must have N-1 edges'
            targets = [edge['target'] for edge in edges]
            assert len(targets) == len(set(targets)), 'each child has exactly one parent'
            roots = ids - set(targets)
            assert len(roots) == 1, 'a lineage has exactly one root'
            reached = set(roots)
            while True:
                children = {e['target'] for e in edges if e['source'] in reached}
                if children <= reached:
                    break
                reached |= children
            assert reached == ids, 'tree must be connected and acyclic'
            assert all(e['source'] in ids and e['target'] in ids for e in edges)
            assert any(node['isLeaf'] for node in nodes)
            assert 'data:image' not in json.dumps(result)
            artifacts = unwrap(await api.get(f'/runs/{run_id}/artifacts'))
            if isinstance(artifacts, dict):
                artifacts = artifacts['artifacts']
            assert artifacts, f'{method} must retain downloadable outputs/logs'
            for artifact in artifacts:
                download = await api.get(f"/artifacts/{artifact['id']}/download")
                assert download.status_code == 200, download.text
                assert len(download.content) == artifact['size_bytes']
                if artifact.get('checksum_sha256'):
                    assert hashlib.sha256(download.content).hexdigest() == artifact['checksum_sha256']
            # Dataset deletion must not destroy history or separately stored artifacts.
            assert (await api.delete(f"/datasets/{uploaded['file_id']}")).status_code == 200
            assert (await api.get(f'/runs/{run_id}/result')).status_code == 200
            assert (await api.get(f"/artifacts/{artifacts[0]['id']}/download")).status_code == 200
            report_dir = ROOT / 'coverage/scientific'
            report_dir.mkdir(parents=True, exist_ok=True)
            (report_dir / f'{method}.json').write_text(json.dumps({'method': method, 'status': terminal,
                'tree': tree, 'artifacts': artifacts, 'result': result}, indent=2))
        finally:
            if terminal is None:
                await api.post(f'/runs/{run_id}/cancel')


@pytest.mark.parametrize('method', ['gctree', 'clonaltree', 'dowser', 'brepphylo'])
async def test_malformed_dataset_fails_with_diagnostic_and_preserves_history(method):
    async with httpx.AsyncClient(base_url='http://127.0.0.1:58000', timeout=30, trust_env=False) as api:
        tag = uuid4().hex
        # Sign up as a person does: sign-up check, then the emailed confirmation link.
        await register_verified(api, f'{tag}@example.org', tag, 'e2e-password')
        init = unwrap(await api.post('/uploads/init', json={'original_filename': 'invalid.tsv'}))
        uploaded = unwrap(await api.put(init['content_url'], content=b'sequence_id\tsequence_alignment\n'))
        run_id = unwrap(await api.post(f'/runs?method={method}', json={
            'file_id': uploaded['file_id'], 'params': PARAMS[method]}))['run_id']
        deadline = time.monotonic() + 30
        while True:
            status = unwrap(await api.get(f'/runs/{run_id}/status'))
            if status['status'] in ('DONE', 'ERROR', 'CANCELLED'):
                break
            assert time.monotonic() < deadline, status
            await asyncio.sleep(0.2)
        assert status['status'] == 'ERROR', status
        result = unwrap(await api.get(f'/runs/{run_id}/result'))
        assert result['ok'] is False
        assert result.get('error'), result
        assert (await api.delete(f"/datasets/{uploaded['file_id']}")).status_code == 200
        assert (await api.get(f'/runs/{run_id}/result')).status_code == 200

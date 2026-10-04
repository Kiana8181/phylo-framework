"""Validate example requests with the schemas consumed across languages."""
import json
from pathlib import Path
import pytest
from jsonschema import Draft7Validator, ValidationError
from apps.api.contracts.loader import get_param_schema, get_result_schema, load_spec_from_contracts, get_service_routes

ROOT = Path(__file__).resolve().parents[3]
PARAMS = json.loads((ROOT / 'tests/fixtures/scientific-params.json').read_text())


@pytest.mark.parametrize('method', sorted(PARAMS))
def test_schemas_and_documented_request_agree(method):
    params = get_param_schema(method)
    Draft7Validator.check_schema(params)
    Draft7Validator.check_schema(get_result_schema(method))
    Draft7Validator(params).validate(PARAMS[method])
    spec = load_spec_from_contracts(method)
    assert spec['id'] == method
    assert spec['paramSchema'] == params
    routes = get_service_routes(method)
    assert all(routes[key].count('{job_id}') == 1 for key in ('jobStatus', 'jobResult', 'jobCancel'))
    with pytest.raises(ValidationError):
        Draft7Validator(params).validate({'not-a-valid-param': object()})


@pytest.mark.parametrize('method', sorted(PARAMS))
def test_lightweight_result_schema_matches_persisted_tree_summary(method):
    from apps.api.services.tree_contract import assemble_unified_tree_result
    result, rows = assemble_unified_tree_result(method, {'ok': True, 'trees': ['(a:1,b:2)root;']})
    schema = json.loads((ROOT / 'packages/contracts/result.schema.json').read_text())
    Draft7Validator(schema).validate(result)
    assert rows[0]['newick'] == '(a:1,b:2)root;'
    assert 'newick' not in result['trees'][0]

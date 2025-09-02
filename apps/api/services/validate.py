from jsonschema import validate as _validate, ValidationError
from typing import Any, Dict

def validate_json(data: Any, schema: Dict[str, Any]) -> None:
    _validate(data, schema)

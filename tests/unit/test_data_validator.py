import pytest
from data_lake.data_validator import validate_data_schema

def test_validate_data_schema_stub():
    assert validate_data_schema(b"some data", "schema") == True

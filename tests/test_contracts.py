import pytest
from pydantic import ValidationError

from reviewops.contracts import InvestigationRequest


@pytest.mark.parametrize(
    "changes",
    [
        {"date_from": "2023-01-01", "date_to": "2022-01-01"},
        {"product_ids": []},
        {"product_ids": [""]},
        {"product_ids": ["p", "p"]},
        {"question": "   "},
        {"unexpected_sql": "DROP TABLE reviews"},
    ],
)
def test_invalid_scope_is_rejected(changes):
    payload = dict(
        question="Investigate this", product_ids=["p"], date_from="2022-01-01", date_to="2022-12-31"
    )
    with pytest.raises(ValidationError):
        InvestigationRequest(**(payload | changes))

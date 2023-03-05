"""
Tests utility functions used by Flask views.
"""
import pytest
from ..views import split_pdl_event_code


def test_split_pdl_event_code():
    source, code = split_pdl_event_code(event_code='us2008abcd')
    assert source == 'us'
    assert code == '2008abcd'

    source, code = split_pdl_event_code(event_code='cidev012345678')
    assert source == 'cidev'
    assert code == '012345678'

    source, code = split_pdl_event_code(event_code='ew1665147161')
    assert source == 'ew'
    assert code == '1665147161'

    with pytest.raises(ValueError):
        source, code = split_pdl_event_code(event_code='')
    with pytest.raises(ValueError):
        source, code = split_pdl_event_code(event_code=None)
    with pytest.raises(ValueError):
        source, code = split_pdl_event_code(event_code=1234567890)
    with pytest.raises(ValueError):
        source, code = split_pdl_event_code(event_code='1665147161')

import pytest
from pytest import raises, fail, skip


def test_basic():
    import attic
    assert True


def test_datetimesafestring():
    from attic.safetimestring import test_datetime_safestring_conversion
    test_datetime_safestring_conversion()



def test_fail_or_skip():
    skip("unimplemented")
    fail("unimplemented")

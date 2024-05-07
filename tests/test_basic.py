import pytest
from pytest import raises, fail, skip


def test_basic():
    import hyattic
    assert True


def test_datetimesafestring():
    from hyattic.safetimestring import test_datetime_safestring_conversion
    test_datetime_safestring_conversion()



def test_fail_or_skip():
    skip("unimplemented")
    fail("unimplemented")

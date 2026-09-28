from workmate.model import MockProvider


def test_mock_provider_returns_text():
    p = MockProvider()
    out = p.complete("system", "user")
    assert isinstance(out, str) and out.strip()

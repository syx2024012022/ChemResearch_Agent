import pytest

from chemresearch_agent.infrastructure.remote_file_fetcher import _validate_public_https_url


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com/paper.pdf",
        "https://user:secret@example.com/paper.pdf",
        "https://127.0.0.1/paper.pdf",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/paper.pdf",
    ],
)
def test_remote_file_policy_rejects_unsafe_urls(url: str) -> None:
    with pytest.raises(ValueError):
        _validate_public_https_url(url)

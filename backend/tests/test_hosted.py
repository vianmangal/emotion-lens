import pytest

from backend.config import Settings
from scripts.run_hosted import hosted_settings


def config(origins, hosts):
    return Settings(_env_file=None, CORS_ALLOW_ORIGINS=origins, ALLOWED_HOSTS=hosts)


def test_hosted_runner_accepts_only_explicit_secure_matching_origins():
    settings = config(['https://cnn.vian1.tech'], ['cnn.vian1.tech', 'localhost', '127.0.0.1'])
    assert hosted_settings(settings) is settings


@pytest.mark.parametrize('origins,hosts', [
    ([], ['cnn.vian1.tech']),
    (['http://cnn.vian1.tech'], ['cnn.vian1.tech']),
    (['https://cnn.vian1.tech'], ['127.0.0.1']),
    (['https://'], ['cnn.vian1.tech']),
    (['https://cnn.vian1.tech', 'http://localhost:5173'], ['cnn.vian1.tech', 'localhost']),
])
def test_hosted_runner_rejects_missing_insecure_or_unapproved_origins(origins, hosts):
    with pytest.raises(ValueError, match='explicit HTTPS origins'):
        hosted_settings(config(origins, hosts))

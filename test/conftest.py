"""
Pytest fixtures.
"""
import pytest

from .. import create_app


MOCK_RSA_KEY_PATH = '/example/eewrest/key/path/id_rsa'
MOCK_PDL_CONF_PATH = '/unittest_ProductClient.ini'
MOCK_JAR_PATH = '/example/eewrest/ProductClient.jar'


@pytest.fixture(scope='session')
def app():
    """
    Generates a fresh Flask app instance.
    :yield: A configured Flask app instance.
    """

    app = create_app({
        'TESTING': True,  # Flask builtin
        'DEBUG': True,  # Flask builtin
        'Port': 5001,
        'SkipPDLSend': False,
        'Java': '/usr/bin/java',
        'EEW_RESTHome': '/app/EEWREST/',
        'ProductClient': f'{MOCK_JAR_PATH}',
        'ProductClientConfig': f'{MOCK_PDL_CONF_PATH}',
        'SSHPrivateKey': f'{MOCK_RSA_KEY_PATH}'
    })

    yield app


@pytest.fixture(scope='session')
def client(app):
    """
    Flask app HTTP client pytest fixture.
    Use this fixture to simulate client requests.
    """
    yield app.test_client()

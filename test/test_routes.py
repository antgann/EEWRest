"""
This module implements EEWREST Flask route unit tests using
pytest and pytest-mock plugin.
"""

import logging
import os
from datetime import datetime
from pathlib import Path
from typing import List
from unittest.mock import MagicMock

import json
import pytest

from .. import views
from .conftest import MOCK_JAR_PATH, MOCK_PDL_CONF_PATH, MOCK_RSA_KEY_PATH


INPUT_DIR = os.path.join(os.path.dirname(__file__), 'input')


def test_status_request(client):
    response = client.get('/foobar')
    assert response.status_code == 404


def test_invalid_status_request(client):
    """
    Test invalid request.
    """
    response = client.get('/status')
    exp_response = json.loads('{"message": "EEWREST ALIVE"}')
    assert response.status_code == 200
    assert json.loads(response.get_data()) == exp_response


def test_split_pdl_event_code():
    """
    Test helper function split_pdl_event_code(str).
    """

    src, code = views.split_pdl_event_code('ci123456789')
    assert src == 'ci'
    assert code == '123456789'

    src, code = views.split_pdl_event_code('cidev123456789')
    assert src == 'cidev'
    assert code == '123456789'

    '''
    This would be unexpected from a PDL source, but checks default to 2 char
    code when RSN source ID is not recognized.
    '''
    src, code = views.split_pdl_event_code('foo_bar12345')
    assert src == 'fo'
    assert code == 'o_bar12345'

    # Should raise Exception since the product code (numeric part) len < 8.
    with pytest.raises(ValueError):
        src, code = views.split_pdl_event_code('nc1234567')

    # Should raise Exception since there is no alphabetic RSN source ID.
    with pytest.raises(ValueError):
        src, code = views.split_pdl_event_code('123456789123')


def test_request_contents_xml_file(app, mocker):
    """
    Test request for contents.xml sent from EEWREST back to ARC
    while building the confirmed follow-up PDL message.
    """
    m_response_obj = mocker.patch('requests.models.Response', autospec=True)
    m_response_obj.content = '<xml>foobar</xml>'  # mock xml content
    m_get_req_fn = mocker.patch(
        'requests.get',
        return_value=m_response_obj
    )

    # Expected val for path string returned by request_contents_xml_file()
    exp_xml_file_path = str(Path(app.config["EEW_RESTHome"]) / 'contents.xml')

    m_open_fn = mocker.mock_open()
    mocker.patch('builtins.open', m_open_fn)

    dummy_url = 'http://foo.example.com'

    # Call function under test
    xml_file_path = views.request_contents_xml_file(url=dummy_url)
    m_open_fn.assert_called_once_with(exp_xml_file_path, 'wb')
    assert exp_xml_file_path == xml_file_path

    # Note: allow_redirects required since ARC runs behind a reverse proxy.
    m_get_req_fn.assert_called_once_with(dummy_url, allow_redirects=True)


def test_request_summary_pdf_file(app, mocker):
    """
    Test request for summary.pdf sent from EEWREST back to ARC
    while building the confirmed follow-up PDL message.
    """
    m_response_obj = mocker.patch('requests.models.Response', autospec=True)
    m_response_obj.content = 'foobar'  # mock pdf content
    m_get_req_fn = mocker.patch(
        'requests.get',
        return_value=m_response_obj
    )

    # Expected val for path string returned by request_summary_pdf_file()
    exp_pdf_file_path = str(
        Path(app.config["EEW_RESTHome"]) / 'summary.pdf'
    )

    m_open_fn = mocker.mock_open()
    mocker.patch('builtins.open', m_open_fn)

    dummy_url = 'http://foo.example.com'

    # Call function under test
    summary_pdf_path = views.request_summary_pdf_file(url=dummy_url)
    m_open_fn.assert_called_once_with(summary_pdf_path, 'wb')
    assert exp_pdf_file_path == summary_pdf_path

    # Note: allow_redirects required since ARC runs behind a reverse proxy.
    m_get_req_fn.assert_called_once_with(dummy_url, allow_redirects=True)


def test_json2pdl_request(client, fp, mocker, caplog):
    """
    Test alert confirmation request.
    Checks correctness of command params passed to the PDL subprocess.
    :param client: Flask client pytest fixture
    :param fp: subprocess mocking plugin pytest fixture
    :param mocker: Mock lib pytest fixture
    :param caplog: Log message capturing pytest fixture
    """
    pdl_source_rsn_id = 'ew'
    pdl_product_code = '1659991460'
    pdl_event_code = f'{pdl_source_rsn_id}{pdl_product_code}'

    json_payload: str = None
    with open(os.path.join(INPUT_DIR, 'true_alert.json'), 'r') as json_input:
        json_payload = json_input.read()

    contents_xml_path: str = '/example/contents.xml'
    summary_pdf_path: str = '/example/summary.pdf'

    # Expected PDL origin command that will run in the resulting subprocess.
    exp_pdl_cmd_list = [
        '/usr/bin/java', '-jar', f'{MOCK_JAR_PATH}',
        '--send',
        f'--source={pdl_source_rsn_id}',
        '--type=shake-alert',
        f'--code={pdl_event_code}',
        f'--eventsource={pdl_source_rsn_id}',
        f'--eventsourcecode={pdl_product_code}',
        '--property-review-status=reviewed',
        '--status=CONFIRMED',
        '--file=summary.json',
        f'--privateKey={MOCK_RSA_KEY_PATH}',
        f'--file={contents_xml_path}',
        f'--file={summary_pdf_path}',
        f'--configFile={MOCK_PDL_CONF_PATH}'
    ]

    # Keep history of all subprocess called during this test case.
    fp.keep_last_process(True)

    # Tell fakeprocess to capture all subprocess calls.
    fp.register([fp.any()])

    # Mock function request_contents_xml_file to return xml path
    mock_contents_xml_request_fn: MagicMock = mocker.patch(
        'EEWRest.views.request_contents_xml_file',
        return_value=f'{contents_xml_path}'
    )

    # Mock function request_summary_pdf_file to return pdf path
    pdf_request_fn: MagicMock = mocker.patch(
        'EEWRest.views.request_summary_pdf_file',
        return_value=f'{summary_pdf_path}'
    )

    # Mock geojson file archive function to skip it (no file produced by test).
    mock_archive_fn: MagicMock = mocker.patch('EEWRest.views.archive_geojson')

    # Patch open function so we capture the summary GeoJSON file.
    m_open_fn = mocker.mock_open()
    mocker.patch('builtins.open', m_open_fn)

    # Send HTTP POST request that we're trying to test
    response = client.post(
        f'/api/JSON2PDL/{pdl_event_code}',
        json=json_payload
    )

    assert response.status_code == 200

    mock_contents_xml_request_fn.assert_called_once_with(
        'http://example.com/contents.xml'
    )

    pdf_request_fn.assert_called_once_with(
        'http://example.com/summary.pdf'
    )

    assert mock_archive_fn.call_args[0][0] == pdl_event_code
    assert isinstance(mock_archive_fn.call_args[0][1], str)
    datetime.strptime(mock_archive_fn.call_args[0][1], '%Y-%m-%d %H:%M:%S')

    # Check for captured subprocess calls
    if len(fp.calls) < 1:
        pytest.fail('Expected suprocess not called.')

    # Assert that final ProductClient subprocess command matches expected.
    # assert exp_pdl_cmd_list in fp.calls
    captured_cmd = fp.calls[0]

    # Check for /usr/bin/java -jar ProductClient.jar
    exp_jar_path = client.application.config['ProductClient']
    assert captured_cmd[0] == client.application.config["Java"]
    assert captured_cmd[1] == '-jar'
    assert captured_cmd[2] == exp_jar_path  # eg. /app/pdl/ProductClient.jar

    # Check command options are all there (regardless of ordering).
    for exp_option in exp_pdl_cmd_list[3:]:
        # Each expected command parameter should appear exactally once.
        assert captured_cmd.count(exp_option) == 1

    # Check for summary.json creation
    m_open_fn.assert_called_once_with('summary.json', 'w')

    # Check to make sure we writing to app.logger
    log_records: List[logging.LogRecord] = caplog.records
    assert len(log_records) > 0


def test_associate2pdl_request(client, fp, caplog):
    """
    Test origin association request.
    Checks correctness of command params passed to the PDL subprocess.
    :param client: Flask client pytest fixture
    :param fp: subprocess mocking plugin pytest fixture
    :param mocker: mock lib pytest fixture
    :param caplog: Log message capturing pytest fixture
    """

    pdl_source_rsn_id = 'ew'
    pdl_product_code = '1665147160'
    pdl_event_code = f'{pdl_source_rsn_id}{pdl_product_code}'

    other_source_rsn_id = 'uw'
    other_product_code = '61886506'
    other_event_code = f'{other_source_rsn_id}{other_product_code}'

    request_url_w_args = (
        f'/api/ASSOCIATE/'
        f'?eventID={pdl_event_code}&otherID={other_event_code}'
    )

    # Example Associate ProductClient.jar command pulled from logs:
    exp_pdl_cmd_list = [
        '/usr/bin/java', '-jar', f'{MOCK_JAR_PATH}',
        '--send',
        '--source=ew',
        f'--code={pdl_event_code}',
        '--type=associate',
        f'--eventsource={pdl_source_rsn_id}',
        f'--eventsourcecode={pdl_product_code}',
        f'--property-othereventsource={other_source_rsn_id}',
        f'--property-othereventsourcecode={other_product_code}',
        f'--privateKey={MOCK_RSA_KEY_PATH}',
        f'--configFile={MOCK_PDL_CONF_PATH}'
    ]

    # Keep history of all subprocess called during this test case
    fp.keep_last_process(True)

    # Tell fakeprocess to capture all subprocess calls
    fp.register([fp.any()])

    # Send HTTP GET request that we're trying to test
    response = client.get(request_url_w_args)

    assert response.status_code == 200

    # Check for captured suprocess calls
    if len(fp.calls) < 1:
        pytest.fail('Expected subprocess not called.')

    # Get subprocess call captured by fakeprocess
    captured_cmd = fp.calls[0]

    #  ProductClient.jar path from config
    exp_jar_path = client.application.config['ProductClient']

    # Check for /usr/bin/java
    assert captured_cmd[0] == client.application.config["Java"]
    assert captured_cmd[1] == '-jar'
    assert captured_cmd[2] == exp_jar_path  # eg. /app/pdl/ProductClient.jar

    # Check command options are all there (regardless of ordering)
    for exp_option in exp_pdl_cmd_list[3:]:
        # Each expected command parameter should appear exactally once
        assert captured_cmd.count(exp_option) == 1

    # Check to make sure we writing to app.logger
    log_records: List[logging.LogRecord] = caplog.records
    assert len(log_records) > 0


def test_cancel2pdl_request(client, fp, mocker, caplog):
    """
    Test origin cancellation request.
    Checks correctness of command params passed to the PDL subprocess
    for the false alert follow-up case.
    :param client: Flask client pytest fixture
    :type client: flask.testing.FlaskClient
    :param fp: subprocess mocking plugin pytest fixture
    :param mocker: mock lib pytest fixture
    :param caplog: Log message capturing pytest fixture
    """
    pdl_source_rsn_id = 'ew'
    pdl_product_code = '1658979090'
    pdl_event_code = f'{pdl_source_rsn_id}{pdl_product_code}'

    request_url = f'/api/CANCEL2PDL/{pdl_event_code}'
    part2_request_stdin: str = 'Mock False Alert Banner Text'

    exp_pdl_part_1_cmd_list = [
        '/usr/bin/java', '-jar', f'{MOCK_JAR_PATH}',
        '--send',
        f'--source={pdl_source_rsn_id}',
        f'--code={pdl_event_code}',
        '--mainclass=gov.usgs.earthquake.eids.EIDSInputWedge',
        f'--file=builds/QuakeMLBuild_{pdl_product_code}.xml',
        f'--privateKey={MOCK_RSA_KEY_PATH}',
        f'--configFile={MOCK_PDL_CONF_PATH}'
    ]

    # This command receives a message text via stdin
    exp_pdl_part_2_cmd_list = [
        '/usr/bin/java', '-jar', f'{MOCK_JAR_PATH}',
        '--send',
        f'--source={pdl_source_rsn_id}',
        '--type=deleted-text',
        f'--code={pdl_event_code}',
        f'--eventsource={pdl_source_rsn_id}',
        f'--eventsourcecode={pdl_product_code}',
        '--content',
        '--content-type=text/html',
        f'--configFile={MOCK_PDL_CONF_PATH}'
    ]

    # Keep history of all subprocess called during this test case
    fp.keep_last_process(True)

    # Tell fakeprocess to capture all subprocess calls
    fp.register([fp.any()])

    params_dir = Path(__file__).parent.parent / 'params'
    qml_template_path = params_dir / 'QuakeML_EEWTemplate.xml'
    qml_template = open(qml_template_path, 'r')
    m_open_fn = mocker.mock_open(read_data=qml_template.read())
    qml_template.close()
    mocker.patch('builtins.open', m_open_fn)

    # Send HTTP GET request that we're trying to test
    response = client.post(request_url, data=part2_request_stdin)

    assert response.status_code == 200

    # Make sure open was called twice
    assert m_open_fn.call_count == 2

    # Check QuakeML file temp write (Note: open called by xml library)
    m_open_fn.assert_called_with(
        f'builds/QuakeMLBuild_{pdl_product_code}.xml',
        'w',
        encoding='utf-8',
        errors='xmlcharrefreplace'
    )

    # Check for captured suprocess calls
    exp_sp_call_count = 2
    if len(fp.calls) < exp_sp_call_count:
        pytest.fail(
            f'Expected {exp_sp_call_count} subprocess calls, '
            f'but {len(fp.calls)} calls were captured.'
        )

    # Check PDL subproc call for part 1 of the cancellation request.
    cap_part_1_cmd = fp.calls[0]

    #  ProductClient.jar path from config
    exp_jar_path = client.application.config['ProductClient']

    # Check for /usr/bin/java -jar ProductClient.jar
    assert cap_part_1_cmd[0] == client.application.config["Java"]
    assert cap_part_1_cmd[1] == '-jar'
    assert cap_part_1_cmd[2] == exp_jar_path  # eg. /app/pdl/ProductClient.jar

    # Check command options are all there (regardless of ordering)
    for exp_option in exp_pdl_part_1_cmd_list[3:]:
        # Each expected command parameter should appear exactally once
        assert cap_part_1_cmd.count(exp_option) == 1, (
            f'Part 1 PDL command missing option {exp_option}'
        )

    # Check PDL subproc call for part 2 of the cancellation request.
    cap_part_2_cmd = fp.calls[1]

    # Check for /usr/bin/java -jar ProductClient.jar
    assert cap_part_2_cmd[0] == client.application.config["Java"]
    assert cap_part_2_cmd[1] == '-jar'
    assert cap_part_2_cmd[2] == exp_jar_path  # eg. /app/pdl/ProductClient.jar

    # Check command options are all there (regardless of ordering)
    for exp_option in exp_pdl_part_2_cmd_list[3:]:
        # Each expected command parameter should appear exactally once
        assert cap_part_2_cmd.count(exp_option) == 1, (
            f'Part 2 PDL command missing option {exp_option}'
        )

    # Check to make sure we writing to app.logger
    log_records: List[logging.LogRecord] = caplog.records
    assert len(log_records) > 0


def test_missing2pdl_request(client, fp, mocker, caplog):
    """
    Test missed alert follow-up request.
    Checks correctness of command params passed to the PDL subprocess
    for the missed alert follow-up case.
    :param client: Flask client pytest fixture
    :type client: flask.testing.FlaskClient
    :param fp: subprocess mocking plugin pytest fixture
    :param mocker: mock lib pytest fixture
    :param caplog: Log message capturing pytest fixture
    """
    pdl_source_rsn_id = 'ci'
    pdl_product_code = '12345678'
    pdl_event_code = f'{pdl_source_rsn_id}{pdl_product_code}'

    request_url_w_args = f'/api/MISSED2PDL/{pdl_event_code}'
    dummy_follow_up_text = '<html>Missing text would go here</html>'
    # Example Associate ProductClient.jar command pulled from logs:
    exp_pdl_cmd_list = [
        '/usr/bin/java', '-jar', f'{MOCK_JAR_PATH}',
        '--send',
        f'--source={pdl_source_rsn_id}',
        f'--code={pdl_event_code}',
        '--type=shake-alert',
        f'--eventsource={pdl_source_rsn_id}',
        f'--eventsourcecode={pdl_product_code}',
        '--property-review-status=reviewed',
        '--status=MISSED',
        '--file=missing.html',
        f'--privateKey={MOCK_RSA_KEY_PATH}',
        f'--configFile={MOCK_PDL_CONF_PATH}'
    ]

    # Keep history of all subprocess called during this test case
    fp.keep_last_process(True)

    # Tell fakeprocess to capture all subprocess calls
    fp.register([fp.any()])

    m_open_fn = mocker.mock_open(read_data=dummy_follow_up_text)
    mocker.patch('builtins.open', m_open_fn)

    # Mock os.rename fn.
    m_os_rename_fn = mocker.patch('os.rename')

    # Send HTTP POST request that we're trying to test
    response = client.post(request_url_w_args, data=dummy_follow_up_text)

    assert response.status_code == 200

    # Check for captured suprocess calls
    if len(fp.calls) < 1:
        pytest.fail('Expected subprocess not called.')

    # Get subprocess call captured by fakeprocess
    captured_cmd = fp.calls[0]

    #  ProductClient.jar path from config
    exp_jar_path = client.application.config['ProductClient']

    # Check for /usr/bin/java
    assert captured_cmd[0] == client.application.config["Java"]
    assert captured_cmd[1] == '-jar'
    assert captured_cmd[2] == exp_jar_path  # eg. /app/pdl/ProductClient.jar

    # Check command options are all there (regardless of ordering)
    for exp_option in exp_pdl_cmd_list[3:]:
        # Each expected command parameter should appear exactally once
        assert captured_cmd.count(exp_option) == 1

    # Check for rename call to move missed.html file to archive dir.
    m_os_rename_fn.assert_called_once()

    # Check rename() call params
    # Expected: os.rename('missed.html', path_to_archive_dir)
    call_args = m_os_rename_fn.call_args[0]  # get first call args
    assert len(call_args) == 2
    assert call_args[0] == 'missing.html'
    assert call_args[1].endswith('missing.html')

    # Check to make sure we writing to app.logger
    log_records: List[logging.LogRecord] = caplog.records
    assert len(log_records) > 0


def test_associate_invalid_usage(client, mocker, caplog):
    """
    Make sure Flask returns the correct HTTP response when
    invalid usage is raised.
    :param client: Flask client pytest fixture
    :param mocker: mock lib pytest fixture
    :param caplog: Log message capturing pytest fixture
    """

    # Mock association message sender fn to simulate an internal exception.
    m_send: MagicMock = mocker.patch('EEWRest.views.associateWithPDL')

    # Send HTTP GET request w/ bad params to test InvalidUsage handler
    response = client.get('/api/ASSOCIATE/?eventID=ew123456789')
    assert response.status_code == 400

    response = client.get('/api/ASSOCIATE/')
    assert response.status_code == 400

    response = client.get('/api/ASSOCIATE/?foobar=ew1123455667')
    assert response.status_code == 400

    # Valid URL and params, but wrong request type (POST instead of GET)
    response = client.post(
        '/api/ASSOCIATE/?eventID=ew123456789&otherID=ci987654322'
    )
    assert response.status_code == 405  # Method not allowed

    # Assert not called, since Flask's error handler forces early returns.
    m_send.assert_not_called()

    # Check to make sure we writing to app.logger
    log_records: List[logging.LogRecord] = caplog.records
    assert len(log_records) > 0

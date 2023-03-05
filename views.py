"""
EEWREST API views module.  This module provides all Flask Blueprint object
which defines views for sending ShakeAlert follow-up messages to PDL.
"""

import json
import logging
import os
import requests
import subprocess
import time
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Tuple

from flask import current_app, request, Response, jsonify, Blueprint


api = Blueprint('api', __name__)

# Expected network (RSN) source codes list. Used to parse PDL "Event Codes".
SOURCE_PREFIX_LIST = sorted([
    'bk', 'ci', 'cidev', 'ew', 'nc', 'nn', 'pt', 'us', 'uw'
])

# Log message printed when PDL message transmission is disabled in config.
PDL_DISABLED_LOG_TXT = (
    'PDL message unsent.  Skipped send step due to config SkipPDLSend=True. '
)

logger = logging.getLogger(__name__)
logger.propagate = True


class InvalidUsage(Exception):
    status_code = 400

    def __init__(self, message, status_code=None, payload=None):
        Exception.__init__(self)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        self.payload = payload

    def to_dict(self):
        rv = dict(self.payload or ())
        rv['message'] = self.message
        return rv


def split_pdl_event_code(event_code: str) -> Tuple[str, str]:
    """
    Splits PDL's "Event Code" parameter which functions as the Origin
    message UUID.  The expected uuid should consist of the "source"
    RSN ID followed by a "code" integer.
    .. note:: Since PDL's "Network Source" ID and "Product Code" ID are
        alpha-numeric strings, a list of known Network Source ID's
        (SOURCE_PREFIX_LIST) must be used to determine where the Network
        Source ID stops and the Product Code string begins.  If a matching
        RSN source id prefix is not found in SOURCE_PREFIX_LIST, the first
        2 chars of the given event code will be used by default.
    :param event_code: A PDL "Event Code" made up of a
        "Source Network Code" (RSN identifier, length >= 2 chars) prepended
        to a PDL "Product Code" (PDL Product ID issued by the RSN,
        length >= 8 chars).
        Examples: 'us2008abcd' 'cidev123456789' 'ew1665727384'
    :type event_code: str
    :return: Tuple containing the PDL source RSN ID and PDL Product code.
    :rtype: Tuple[str, str]
    """
    MIN_EVENT_CODE_LEN = 10  # 2 char source RSN ID + 8 char product code
    if not isinstance(event_code, str):
        raise ValueError(
            f'Param event_code must be of type str: {event_code}. '
            f'type(event_code) -> {type(event_code)}'
        )

    if len(event_code) < MIN_EVENT_CODE_LEN:
        raise ValueError(
            f'Value of str param event_code "{event_code}" is less than the '
            f'allowed min length of {MIN_EVENT_CODE_LEN} characters.'
        )

    src_net_code = None
    product_code = None

    # Match RSN id against sorted RSN prefix list (use longest match).
    for rsn_id in SOURCE_PREFIX_LIST:
        if event_code.startswith(rsn_id):
            src_net_code = event_code[:len(rsn_id)]
            product_code = event_code[len(rsn_id):]

    # Return if a matching prefix was found.
    if src_net_code is not None and product_code is not None:
        return src_net_code, product_code

    # Default to first 2 chars of event code if RSN prefix not found.
    src_net_code = event_code[:2]
    product_code = event_code[2:]

    # Print warning to notify that RSN ID prefix list needs to be updated.
    logger.warning(
        'Unrecognized RSN source ID prefix in PDL Event Code "%s". '
        'Using first 2 chars of event_code ("%s") by default.  This '
        'warning usually indicates that a new RSN prefix should be added '
        'to SOURCE_PREFIX_LIST.',
        event_code,
        src_net_code
    )

    '''
    Check to make sure RSN prefix is an alphabetic string.
    Catches product codes (w/o RSN ID prefix) passed to event_code param.
    '''
    if not src_net_code.isalpha():
        raise ValueError(
            'Unable to find source RSN ID prefix '
            f'in event_code param value: {event_code}. '
            f'Illegal non-alphabetic RSN prefix: {src_net_code}.'
        )

    return src_net_code, product_code


@api.route('/')
@api.route('/status', methods=['GET'])
def status():
    """
    Provides a json status response for monitoring purposes.
    :return: {"message": "EEWREST ALIVE"}
    """
    response = jsonify({"message": "EEWREST ALIVE"})
    response.status_code = 200
    return response


def request_contents_xml_file(url: str) -> str:
    """
    Requests PDL's contest.xml from an external HTTP server and
    writes it to a file.
    :param url: HTTP URL for the contents.xml file
    :type url: str
    :return: Path str to the created contents.xml file.
    :rtype: str
    """

    # Send HTTP request to ARC for the contents file data
    r = requests.get(url, allow_redirects=True)

    # Write contents file data to file contents.xml
    contents_file_path = os.path.join(
        current_app.config.get('EEW_RESTHome'),
        'contents.xml'
    )
    with open(contents_file_path, 'wb') as contents_xml_f:
        contents_xml_f.write(r.content)

    return contents_file_path


def request_summary_pdf_file(url: str) -> str:
    """
    Requests Post ShakeAlert Message Summary from an external HTTP server and
    writes it to a file.
    :param url: HTTP URL for the PDF file
    :type url: str
    :return: Path str to the created PDF file.
    :rtype: str
    """
    # Send HTTP request to ARC for the summary PDF file data
    r = requests.get(url, allow_redirects=True)

    # Write PDF file data to file summary.pdf
    pdf_file_path = os.path.join(
        current_app.config.get('EEW_RESTHome'),
        'summary.pdf'
    )
    with open(pdf_file_path, 'wb') as summary_pdf_f:
        summary_pdf_f.write(r.content)

    return pdf_file_path


def archive_geojson(uuid, timestamp) -> None:
    """
    Moves the current geojson file to an archival dir.
    :param uuid: PDL event code ie. ew1612345678
    :type uuid: str
    :param timestamp: Timestamp str to be used in the geojson filename.
    :type timestamp: str
    """
    try:
        archive_dir = Path(current_app.config.get('ArchiveDir'))
        os.rename('summary.json',  archive_dir / f'{uuid}_{timestamp}.json')
    except Exception:
        logger.error(
            'Unable to move summary.json to archive directory.',
            exc_info=True
        )


@api.route('/api/JSON2PDL/<uuid>', methods=['POST'])
def JSON2PDL(uuid):
    """
    Sends a SA confirmation follow-up message via PDL that includes an
    attached post ShakeAlert report PDF, and manifest xml file.
    .. note: This view function makes HTTP requests back to ARC to gather
        the pdf report and xml manifest content.
        This request made against this view function will return an error
        indicating failure if either of the file requests are unsuccessful.
    A request should have a JSON payload containing the following elements:
        - pas_geojson: Post SA Report GeoJSON
        - contents_file_url: URL used to fetch contents.xml via HTTP
        - pas_pdf_file_url: URL used to fetch the Post SA Summary
        Report PDF (summary.pdf)
    If request mime-type is not application/json or payload fails to parse as
    json, error code 400 is returned.
    TODO: Make temp file path for content.xml and summary.pdf configurable
    TODO: Write GeoJSON file to archive/dest dir on first pass instead of using
          working dir and moving to archive at end of the request.
    :param uuid: A PDL code of the form <rsn_id>:<message_id_int>
    :type uuid: str
    """
    timeStamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    logger.info("Received a JSON2PDL with id %s at %s", uuid, timeStamp)

    # Init list to hold file attachments as cmd line options
    # Str format "--file=<attachment_path>"
    PDLAttach = list()

    # Get payload from request obj. Returns error 400 if payload is not json.
    content = request.get_json()

    logger.debug("data is: " + format(content))

    # Parse received str/bytes payload into dict.
    try:
        data = json.loads(content)
    except ValueError:
        logger.error("JSON was not valid")
        raise InvalidUsage('JSON sent was not valid')

    # Get contents file url from payload
    url_elem_name = 'contents_file_url'
    url = data.get(url_elem_name)
    if url is None:
        logger.error(
            f'Element "{url_elem_name}" missing from '
            'json payload or set to null.'
        )

    # Request contents.xml file from ARC and attach it to PDL message.
    try:
        contents_file_path: str = request_contents_xml_file(url)
        PDLAttach.append(f'--file={contents_file_path}')
        logger.info("content.xml attached")
    except Exception:
        logger.error(
            'Unable to open contents.xml file: %s',
            contents_file_path
        )
        pass

    # Get contents file url from payload
    try:
        pdf_url_elem_name = 'pas_pdf_file_url'
        url = data.get(pdf_url_elem_name)
        if url is None:
            raise InvalidUsage(
                f'Element "{pdf_url_elem_name}" missing from '
                'json payload or set to null.'
            )
    except Exception:
        logger.error('Unable to retrieve PDF data from %s', url)
        pass

    # Request summary PDF from ARC and attach it to PDL message.
    try:
        pdf_file_path: str = request_summary_pdf_file(url)
        PDLAttach.append(f'--file={pdf_file_path}')
        logger.info("summary.pdf attached")
    except Exception:
        logger.error('Unable to open PDF file: %s', pdf_file_path)
        pass

    # Extract nested geojson from the received json payload.
    geojson = data.get("pas_geojson")
    if geojson is None:
        logger.error('Summary GeoJSON element is missing or null.')

    # Create Post ShakeAlert Summary GeoJSON file.
    fileToSend = "summary.json"
    with open(fileToSend, 'w') as summary_json_file:
        json.dump(geojson, summary_json_file)

    source, code = split_pdl_event_code(uuid)

    typeOfFile = "shake-alert"
    status = "CONFIRMED"

    if not current_app.config.get('SkipPDLSend'):
        # Send PDL message
        transferWithPDL(
            source,
            code,
            typeOfFile,
            status,
            fileToSend,
            PDLAttach
        )
    else:
        logger.info(PDL_DISABLED_LOG_TXT)

    # Archive summary geojson file.
    archive_geojson(uuid, timeStamp)

    return jsonify({"uuid": uuid})


@api.route('/api/ASSOCIATE/', methods=['GET'])
def ASSOCIATE():
    timeStamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    eventID = request.args.get('eventID')
    otherID = request.args.get('otherID')
    if not eventID:
        raise InvalidUsage('Invalid URL param "eventID".')
    if not otherID:
        raise InvalidUsage('Invalid URL param "otherID".')

    logger.info(
        "Received a ASSOCIATEPDL with source id %s and target id %s at %s",
        eventID,
        otherID,
        timeStamp
    )

    try:
        eventSource, eventSourceCode = split_pdl_event_code(eventID)
    except ValueError:
        raise InvalidUsage('Invalid URL param "eventID".')
    try:
        otherEventSource, otherEventSourceCode = split_pdl_event_code(otherID)
    except ValueError:
        raise InvalidUsage('Invalid URL param "otherID".')

    if not current_app.config.get('SkipPDLSend'):
        associateWithPDL(
            eventSource,
            eventSourceCode,
            otherEventSource,
            otherEventSourceCode
        )
    else:
        logger.info(PDL_DISABLED_LOG_TXT)

    response = Response(status=200)
    return response


@api.route('/api/CANCEL2PDL/<uuid>', methods=['GET', 'POST'])
def CANCEL2PDL(uuid):
    """
    Sends cancel/delete message and follow-up text for the given uuid.
    :return: Json containing uuid on successful PDL transmission.
        Status 400 and json returned on invalid usage.
        Status 500 and json returned on PDL transmission failure.
        Error case json example:
        { message: <error_message_text>, status=<err_code> }
    """
    timeStamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())
    logger.info(
        "Received a CANCEL2PDL with id %(ID)s at %(TIME)s",
        {"ID": uuid, "TIME": timeStamp}
    )
    try:
        # Get request payload containing html snippet text.
        content = request.get_data(
            cache=False,
            as_text=True,
            parse_form_data=False
        )

        tx_successful = True
        if not current_app.config.get('SkipPDLSend'):
            # Send PDL cancel message and store returned status
            tx_successful = cancelWithPDL(uuid, message_text=content)
        else:
            logger.info(PDL_DISABLED_LOG_TXT)

    except Exception:
        logger.error(
            'Unexpected error occurred while '
            'processing /api/CANCEL2PDL/%s',
            uuid,
            exc_info=True
        )
        raise InvalidUsage(
            message=(
                'Unexpected error occurred while trying to '
                f'send PDL cancel message for origin {uuid}.'
            )
        )

    # Check PDL message sent status
    if not tx_successful:
        raise InvalidUsage(
            message=(
                'PDL cancel message transmission '
                f'failed for origin {uuid}.'
            ),
            status=500
        )
    return jsonify({'uuid': uuid})


@api.route('/api/MISSED2PDL/<uuid>', methods=['GET', 'POST'])
def MISSING2PDL(uuid):
    """
    This function defines a flask view which will handle missed alert
    follow-up message requests sent by the Alert Review Console. The
    POST handled by this view must contain contain the html follow-up
    snippet to be embedded on NEICs web page.
    :param uuid: The RSN id for the event that was missed by ShakeAlert.
        was missed by shakealert (eg. no alert issued).
    """
    timeStamp = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime())

    # Get request payload containing html snippet text.
    logger.info(
        "Received a MISSED2PDL with id %s at %s",
        uuid,
        timeStamp
    )

    try:
        content = request.get_data(
            cache=False,
            as_text=True,
            parse_form_data=False
        )
        logger.debug("data is: {!s}".format(content))

        source, code = split_pdl_event_code(uuid)
        typeOfFile = "shake-alert"
        status = "MISSED"

        fileToSend = "missing.html"
        with open(fileToSend, 'w') as f:
            f.write(content)
        f.close()

        if not current_app.config.get('SkipPDLSend'):
            transferWithPDL(source, code, typeOfFile, status, fileToSend)
        else:
            logger.info(PDL_DISABLED_LOG_TXT)
        os.rename(
            "missing.html",
            f'../archive/{uuid}_{timeStamp}_missing.html'
        )

        return jsonify({"uuid": uuid})

    except Exception:
        logger.error(
            'Unexpected error occurred while '
            'processing /api/MISSING2PDL/%s',
            uuid,
            exc_info=True
        )
        raise InvalidUsage(
            'Unexpected error. Unable to send missed alert message'
        )


@api.errorhandler(InvalidUsage)
def handle_invalid_usage(error):
    response = jsonify(error.to_dict())
    response.status_code = error.status_code
    logger.error(response)
    return response


def transferWithPDL(source: str,
                    code: str,
                    typeOfFile: str,
                    status: str,
                    fileToSend: str,
                    extraParameters: Optional[List[str]] = None):
    """
    Transfers a file to PDL.
    TODO: Refactor to replace fileToSend param with an optional list of
          attachment file paths.  Currently, extra --file options are added
          to extraParameters list when multiple files are sent.  This will
          clarify that this function works for multi-file messages.
    :param source: Network that generated this product, as a two
        character network code.  Examples include us, nc, and ci.
    :param code: Network event ID.
    :param typeOfFile: Product type. A short identifier that is shared by
        all sources of a type of product.  Examples include: shakemap,
        pager, and dyfi.
    :param status: Optional. Default is UPDATE. Product generators may
        use any status without spaces.  However, the status must be used
        consistently for all products of that type.  Examples include
        UPDATE, and DELETE.
    :param fileToSend: path to a file that is product content. The file's
        name and modification date are preserved.  The mime type is inferred
        from the file extension. The file is added at the root level of
        the product.
    """
    PDLScriptParameters = []
    PDLScriptParameters.append(current_app.config.get('Java'))
    PDLScriptParameters.append("-jar")
    PDLScriptParameters.append(current_app.config.get('ProductClient'))
    PDLScriptParameters.append("--send")
    PDLScriptParameters.append("--source=" + source)
    PDLScriptParameters.append("--type=" + typeOfFile)
    PDLScriptParameters.append("--code=" + source + code)
    PDLScriptParameters.append("--eventsource=" + source)
    PDLScriptParameters.append("--eventsourcecode=" + code)
    PDLScriptParameters.append("--property-review-status=reviewed")
    PDLScriptParameters.append("--status=" + status)
    PDLScriptParameters.append("--file=" + fileToSend)
    PDLScriptParameters.append(
        "--privateKey=" + current_app.config.get('SSHPrivateKey')
    )
    if extraParameters:
        # extra parameters have been included, and will be appended
        for param in extraParameters:
            PDLScriptParameters.append(param)

    PDLScriptParameters.append(
        "--configFile=" + current_app.config.get("ProductClientConfig")
    )

    PDLsend = "PDL TRANSMISSION FOR EVENT ID %s -- PARAMETERS:  %s" % (
        code,
        PDLScriptParameters
    )

    logger.info(PDLsend)

    proc = subprocess.Popen(
        PDLScriptParameters,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    stdout_value, stderr_value = proc.communicate()
    if stdout_value:
        logger.info(stdout_value)
    if stderr_value:
        logger.error(stderr_value)


def associateWithPDL(eventSource: str, eventSourceCode: str,
                     otherEventSource: str, otherEventSourceCode: str) -> None:
    """
    Associates two event IDs to same event via PDL.
    :param eventSource: Source region ID
    :param eventSourceCode: Source event ID
    :param otherEventSource: Two-character region ID of the RSN solution
        to be associated
    :param otherEventSourceCode: Event ID of the RSN solution to be associated
    :rtype: None
    """
    PDLScriptParameters = []
    PDLScriptParameters.append(current_app.config.get('Java'))
    PDLScriptParameters.append("-jar")
    PDLScriptParameters.append(current_app.config.get('ProductClient'))
    PDLScriptParameters.append("--send")
    PDLScriptParameters.append("--source=" + eventSource)
    PDLScriptParameters.append("--code=" + eventSource + eventSourceCode)
    PDLScriptParameters.append("--type=associate")
    PDLScriptParameters.append("--eventsource=" + eventSource)
    PDLScriptParameters.append("--eventsourcecode=" + eventSourceCode)
    PDLScriptParameters.append(
        "--property-othereventsource=" + otherEventSource
    )
    PDLScriptParameters.append(
        "--property-othereventsourcecode=" + otherEventSourceCode
    )
    PDLScriptParameters.append(
        "--privateKey=" + current_app.config.get('SSHPrivateKey')
    )
    PDLScriptParameters.append(
        "--configFile=" + current_app.config.get("ProductClientConfig")
    )

    logger.info(
        "PDL TRANSMISSION FOR EVENT ID %s%s -- PARAMETERS:  %s",
        eventSource,
        eventSourceCode,
        PDLScriptParameters
    )

    proc = subprocess.Popen(
        PDLScriptParameters,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )
    stdout_value, stderr_value = proc.communicate()
    if stdout_value:
        stdoutDecoded = stdout_value.decode("utf-8")
        logger.info(stdoutDecoded)
    if stderr_value:
        logger.error(stderr_value)


def cancelWithPDL(eventID, message_text: str):
    """
    Issues a cancel signal to PDL.
    :param eventID:  Event ID with the network code
    :return: True if message sent successfully, else return False.
    :rtype: bool
    """
    source, code = split_pdl_event_code(eventID)

    quakeMLFile = ComposeQuakeMLCancel(source, code)
    PDLScriptParameters = []
    PDLScriptParameters.append(current_app.config.get('Java'))
    PDLScriptParameters.append("-jar")
    PDLScriptParameters.append(current_app.config.get('ProductClient'))
    PDLScriptParameters.append("--send")
    PDLScriptParameters.append("--source=" + source)
    PDLScriptParameters.append("--code=" + source + code)
    PDLScriptParameters.append(
        "--mainclass=gov.usgs.earthquake.eids.EIDSInputWedge"
    )
    PDLScriptParameters.append("--file=" + quakeMLFile)
    PDLScriptParameters.append(
        "--privateKey=" + current_app.config.get('SSHPrivateKey')
    )
    PDLScriptParameters.append(
        "--configFile=" + current_app.config.get("ProductClientConfig")
    )

    PDLcancel = (f'PDL CANCELLATION FOR EVENT ID {code} '
                 f'-- PARAMETERS: {PDLScriptParameters}')

    logger.info(PDLcancel)

    '''
    Setup subprocess for the QuakeML cancel/delete message.
    This message will perform the cancelation of the origin product.
    The follow-up text will be sent as a second transmission.
    '''
    proc = subprocess.Popen(
        PDLScriptParameters,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    # Send the cancel/delete message part 1 of 2 (QuakeML).
    logger.info('Sending PDL cancellation for event id %s part 1 of 2.', code)
    stdout_value, stderr_value = proc.communicate()

    # Init quakeml message transmission failed flag.
    quakeml_tx_failed = False

    # Check stdout for successful send, return False on failure.
    if stdout_value:
        stdoutDecoded = stdout_value.decode("utf-8")
        logger.info(stdoutDecoded)
        if not ("send complete" in stdoutDecoded):
            quakeml_tx_failed = True
    if stderr_value:
        logger.error(stderr_value)

    if quakeml_tx_failed:
        logger.info(
            'PDL cancellation message for event id %s part 1 of 2 '
            'failed to send. Part 2 will be skipped.',
            code
        )
        return False

    '''
    Send false alert follow-up text message in a separate PDL message using
    product type 'deleted-text'. This must be sent after the cancel/delete
    QuakeML message using the same source+code identifiers. The message text
    payload should be passed into ProductClient's stdin.
    '''
    PDLScriptParameters = []
    PDLScriptParameters.append(current_app.config.get('Java'))
    PDLScriptParameters.append("-jar")
    PDLScriptParameters.append(current_app.config.get('ProductClient'))
    PDLScriptParameters.append("--send")
    PDLScriptParameters.append("--source=" + source)
    PDLScriptParameters.append("--type=deleted-text")
    PDLScriptParameters.append("--code=" + source + code)
    PDLScriptParameters.append("--eventsource=" + source)
    PDLScriptParameters.append("--eventsourcecode=" + code)
    PDLScriptParameters.append("--content")
    PDLScriptParameters.append("--content-type=text/html")
    PDLScriptParameters.append(
        "--configFile=" + current_app.config.get('ProductClientConfig')
    )

    # Write ProductClient parameter list stdout and log for deleted text.
    PDLcancel = (f'PDL CANCELLATION TEXT FOR EVENT ID {code} '
                 f'-- PARAMETERS: {PDLScriptParameters}')
    logger.info(PDLcancel)

    # Setup subprocess to send the false alert cancel message.
    proc = subprocess.Popen(
        PDLScriptParameters,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT
    )

    # Run subprocess to send part 2 of 2. Write follow-up text to stdin.
    logger.info('Sending PDL cancellation for event id %s part 2 of 2.', code)
    stdout_value, stderr_value = proc.communicate(
        input=message_text.encode('utf-8')
    )

    # Init deleted text message transmission failed flag.
    deleted_text_tx_failed = False

    # Check for successful transmission.
    if stdout_value:
        stdoutDecoded = stdout_value.decode("utf-8")
        logger.info(stdoutDecoded)
        if not ("send complete" in stdoutDecoded):
            deleted_text_tx_failed = True
    if stderr_value:
        logger.error(stderr_value)

    # Return True if message sent successfully.
    return not deleted_text_tx_failed


def read_quakeml_template() -> ET.ElementTree:
    ET.register_namespace('', 'http://quakeml.org/xmlns/bed/1.2')
    ET.register_namespace('catalog', 'http://anss.org/xmlns/catalog/0.1')
    ET.register_namespace('q', 'http://quakeml.org/xmlns/quakeml/1.2')

    # Read QuakeML template file into xml ElementTree object.
    input_xml = open('../params/QuakeML_EEWTemplate.xml', 'r')
    tree = ET.parse(input_xml)
    input_xml.close()
    return tree


def ComposeQuakeMLCancel(eventSource, eventCode):
    """
    Generate the QuakeML cancel message based on given
    the event source and code.
    :param eventSource: Event network code (ew, ci, etc.)
    :type eventSource: str
    :param eventCode: PDL Origin "code" param
    :type eventCode: int
    """

    tree = read_quakeml_template()

    root = tree.getroot()
    cancelTime = time.time()
    cancelDateTime = str(
        (datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3]) + "Z"
    )

    eventParameters = root.find(
        '{http://quakeml.org/xmlns/bed/1.2}eventParameters'
    )

    publicID = "quakeml:ew.anss.org/eventParameters/%s/%i" % (
        eventCode,
        int(cancelTime)
    )
    eventParameters.set('publicID', publicID)

    # Poplate creationTime element body with cancelDateTime time str
    eventParameters.find(
        '{http://quakeml.org/xmlns/bed/1.2}creationInfo'
    ).find(
        '{http://quakeml.org/xmlns/bed/1.2}creationTime').text = cancelDateTime

    eventTag = eventParameters.find('{http://quakeml.org/xmlns/bed/1.2}event')
    publicID = "quakeml:ew.anss.org/event/" + eventCode
    eventTag.set('publicID', publicID)
    eventTag.set('catalog:eventsource', eventSource)
    eventTag.set('catalog:eventid', eventCode)

    QuakeMLFile = "builds/QuakeMLBuild_" + eventCode + ".xml"
    tree.write(
        QuakeMLFile,
        encoding='UTF-8',
        xml_declaration=True,
        method='xml'
    )

    return QuakeMLFile

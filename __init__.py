"""
Initializes EEWREST's Flask app module.
Registers the Flask Blueprint containing all API routes.
"""

import logging
import os
import sys
import toml
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional, Union

from flask import Flask

from .views import api


# App config type alias to be used in type hints.
ConfigType = Union[str, Path, Dict[str, Any]]


DEFAULT_CONFIG_PATH: Path = (
    Path(__file__).parent / 'params/EEWRESTProperties.toml'
)


def get_project_info() -> str:
    """
    Return data found in pyproject.toml's project table.
    :return: The parent module version string.
    :rtype: str
    """
    try:
        pyproject_toml_path = Path(__file__).parent / 'pyproject.toml'
        pyproject_toml = toml.load(str(pyproject_toml_path))
    except Exception as exc:
        print('Unable to parse pyproject.toml for project info.')
        print(exc)
        return None
    return pyproject_toml.get('project')

def validate_config(app: Flask) -> None:
    app.logger.info('Beginning app config validation.')

    # Make sure we can read/write to current dir.
    eewrest_home_dir = app.config.get('EEW_RESTHome')
    if not os.access(eewrest_home_dir, os.R_OK | os.W_OK):
        app.logger.fatal(
            f'Unable to write to EEWRest home dir: {eewrest_home_dir}. '
            'Please check dir permissions.'
        )
        sys.exit(1)

    # Check JVM config (used to run ProductClient.jar)
    jvm_path = Path(app.config.get('Java'))
    if not (jvm_path and jvm_path.is_file()):
        app.logger.fatal(
            'Undefined Java JVM path. Provided a valid '
            'JVM path via config file parameter "Java".'
        )
        sys.exit(1)
    if not os.access(jvm_path, os.R_OK | os.X_OK):
        app.logger.fatal(
            'Java JVM permissions error. '
            f'Read and execute must be allowed for {jvm_path}'
        )
        sys.exit(1)

    # Check path to ProductClient.jar
    pdl_client_jar_path = Path(app.config.get('ProductClient'))
    if not (pdl_client_jar_path and pdl_client_jar_path.is_file()):
        app.logger.fatal(
            'Undefined ProductClient.jar path. Provided a valid '
            'executable path via config file parameter "ProductClient".'
        )
        sys.exit(1)
    if not os.access(pdl_client_jar_path, os.R_OK):
        app.logger.fatal(
            f'Permissions error. Unable to read: {pdl_client_jar_path}.'
        )
        sys.exit(1)

    # Check archive path for rw permissions.
    archive_path = Path(app.config.get('ArchiveDir'))
    if not archive_path.is_dir():
        archive_path.mkdir(mode=0o777)
    if not os.access(archive_path, os.R_OK | os.W_OK):
        app.logger.fatal(
            f'Permissions error. Unable to read: {archive_path}.'
        )
        sys.exit(1)

    app.logger.info('Completed app config validation.')


def create_app(config: Optional[ConfigType] = None):
    """
    Flask create_app factory function. This function will be autodetected and
    called by the Flask framework on startup. Creates a configured EEWREST
    Flask app instance.
    :param config: The value of the config param can be set using the
        FLASK_APP env var. For example:
        FLASK_APP="/app/EEWRest/__init__.py:create_app('/your/conf.toml')"
    :type config: ConfigType
    .. warning:: Renaming this function could break EEWREST startup unless
        additional Flask framework configuration is provided to override the
        default app creation function name.
    """
    app = Flask(__name__)

    # Init log formatter
    formatter = logging.Formatter(
        '%(asctime)s %(name)-12s %(levelname)-8s %(message)s'
    )

    # Init handler to default stdout stream
    handler = logging.StreamHandler(sys.stdout)

    if isinstance(config, dict):  # Check config dictionary
        app.config.update(config)
    else:  # Check for config file
        if config is not None:
            config_file: Path = Path(config).absolute()
        else:

            config_file: Path = DEFAULT_CONFIG_PATH.absolute()

        print(f'Using config file: {config_file}')

        # Check if config file exists at path. Exit 1 if not found.
        if not config_file.is_file():
            print(
                f'Unable to find config file at path: {config_file}. '
                'Exiting with err code 1'
            )
            sys.exit(1)

        # Load flask app config from TOML file.
        config = toml.load(str(config_file))
        app.config.update(config)

        # Set log level.
        if app.config.get('DEBUG'):
            app.logger.setLevel(logging.DEBUG)
        else:
            # Set to logging.INFO to ignore debug messages.
            app.logger.setLevel(logging.INFO)

        # Get log path.  Print error if log dir doesn't exist.
        log_dir: Path = Path(str(app.config.get('LogDir')))
        if log_dir is not None:
            log_file_path: Path = log_dir / 'EEWREST.log'
            if not log_dir.is_dir():
                print(f'Log dir does not exist at path: {log_dir}.')
                sys.exit(1)
            else:
                # log dir configured, override handler to use file handler.
                handler = TimedRotatingFileHandler(
                    log_file_path,
                    when="d",
                    interval=1,
                    backupCount=60
                )

    # Register log handler and formatter to Flask app logger.
    handler.setFormatter(formatter)
    app.logger.addHandler(handler)

    # Read project info for project module name and version.
    project_info: Dict[str, Any] = get_project_info()

    # Set default module name and version if not found in pyproject.toml.
    if project_info is None:
        project_info = { 'name': 'EEWRest', 'version': 'undefined' }

    # Write init message to log.
    app.logger.info(
        f'Starting new {project_info.get("name")} flask app instance.'
    )
    app.logger.info(
        f'{project_info.get("name")} version: {project_info.get("version")}'
    )

    # Set EEWRest Home dir (dir containing __init__.py) to default if unset.
    if not app.config.get('EEW_RESTHome'):
        app.config['EEW_RESTHome'] = Path(__file__).parent
        app.logger.info(
            'Config value "EEW_RESTHome" is undefined. '
            f'Using default: {app.config.get("EEW_RESTHome")}'
        )

    # Inject default archive path if not provided (for backward compat).
    if not app.config.get('ArchiveDir'):
        app.config['ArchiveDir'] = Path(app.config['EEW_RESTHome']) / 'archive'

    app.logger.info(
        f"EEWRest Home Dir: {app.config['EEW_RESTHome']}"
    )
    app.logger.info(
        f"GeoJSON Archive Dir: {app.config['ArchiveDir']}"
    )

    # Validate config parameters on startup, log and exit if invalid.
    if not app.config['TESTING']:  # Skip if unit testing
        validate_config(app)

    app.register_blueprint(api)

    return app

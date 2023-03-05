# EEWREST

EEWREST provides an http interface for sending ShakeAlert Follow-up messages.

## Prerequisites

* RHEL8+ OS
* Python >= 3.6
  * 3.8+ preferred since 3.6 no longer receives security patches

## Dev Environment Setup

1. Create a new virtualenv called "venv" and source call its activate script to
enable it

    Note: The venv name is already in the .gitignore.

    ```bash
    virtualenv --python=python3 venv
    source venv/bin/activate
    ```

2. Install required packages using pip

    ```bash
    python -m pip install -r requirements.txt
    ```

## Dev Environment Run Instructions

The Flask CLI (provided by the flask pip package) provides a run command
which is used to run a new flask app instance.

**Note:** Make sure the virtualenv is activated before running flask.

```bash
# FLASK_APP must be set to EEWRESTs project directory path (contains .git)
FLASK_APP='<path_to_eewrest_dir>' flask run --host 0.0.0.0 --port 5001
```

**Developer Note:** See architecture.md for notes on code structure found in this project.

## Prod Environment Setup

**Deployment Reminder:** If the production host is managed by a deployment automation system
(ei. Ansible), then following installation steps should carried out by that system. In that
case the following can be used an outline for writing the automated deployment script.

0. User "eewrest" should exist and have home dir set to /app/EEWRest

1. Install the flask package for python3 using the OS package manager

For RHEL, Centos, and Rocky Linux 8+

```bash
sudo -u eewrest python3.8 -m pip install --user flask toml
```

2. Production instances of EEWREST are managed by systemd

To create the systemd service, create the file `/etc/systemd/system/eewrest_daemon.service`
(requires root privileges) containing the following:

```txt
[Unit]
Description=EEWREST Service
After=network.target

[Service]
Type=simple
User=eewrest
Group=eew
Environment="FLASK_APP=/app/EEWRest/__init__.py"
WorkingDirectory=/app/EEWRest
ExecStart=/usr/bin/python3.9 -m flask run -h 0.0.0.0 -p 5000
Restart=on-failure
RestartSec=30
StartLimitIntervalSec=15
StartLimitBurst=3

[Install]
WantedBy=multi-user.target
```

3. Reload the systemd daemon so it will discover the newly added service file:
```bash
sudo systemctl daemon-reload
```

4. Enable EEWREST systemd service so it will autostart on system boot
```bash
sudo systemctl start eewrest_daemon.service
```

## Running EEWREST in Production

```bash
sudo systemctl start eewrest_daemon.service
```

## Running Unit Tests and Generating Test Coverage Reports

To run all test cases with coverage data enabled use pytest with
the '--cov' option. Note: pytest-cov pip package required.

```bash
pytest --cov
```

Example pytest output and coverage report text:

```txt
======================= test session starts ========================
platform linux -- Python 3.8.12, pytest-7.1.3, pluggy-1.0.0
rootdir: /home/ghartman/workspace/EEWRest,
configfile: pyproject.toml, testpaths: test
plugins: mock-3.10.0, subprocess-1.4.2, cov-4.0.0, xdist-3.0.2
collected 7 items                                                                                                                                                                                                                                                                       
test/test_routes.py ......                                               [ 85%]
test/test_util_functions.py .                                            [100%]

---------- coverage: platform linux, python 3.8.12-final-0 -----------
Name          Stmts   Miss Branch BrPart  Cover
-----------------------------------------------
__init__.py       3      0      0      0   100%
views.py        379    139     76     19    59%
-----------------------------------------------
TOTAL           382    139     76     19    59%

```

To create an HTML report from the coverage data found in file .coverage:

```bash
coverage html
```

The result should be directory called "coverage_report_html".  
Open coverage_report_html/index.html in a web browser to view the full
coverage report.  The HTML report shows coverage details overlayed on the
code to provide a better view of the logical branches missed by test cases.

import os
import sys
import json
import time
import psutil
import signal
import subprocess
import socket
import atexit
import platform
from os.path import dirname
from typing import Union, List, Dict

__all__ = ['translate_from_url', 'translate_from_identifier']

SERVER_PORT = 1969
SERVER_IP = f"http://127.0.0.1:{SERVER_PORT}"
PING_URL = f"{SERVER_IP}/connector/ping"

# Global server process (singleton pattern)
_translation_process = None


# ------------------------------
# Utility Functions
# ------------------------------

def get_pid_using_port_unix(port: Union[str, int]):
    """Recover the PID of the process using a given port."""
    for con in psutil.net_connections():
        if con.laddr and con.laddr.port == port:
            return con.pid
        if con.raddr and con.raddr.port == port:
            return con.pid
    return -1


def get_pid_using_port_osx(port: Union[str, int]):
    try:
        out = subprocess.check_output(['lsof', '-ti', f':{port}'])
        pids = [int(p) for p in out.decode().split()]
        return pids[0] if pids else -1
    except subprocess.CalledProcessError:
        return -1


def get_pid_using_port(port: Union[str, int]):
    if platform.system() == "Darwin":
        return get_pid_using_port_osx(port)
    else:
        return get_pid_using_port_unix(port)

def is_port_open(port: Union[str, int]):
    """True if something is listening on the port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex(("127.0.0.1", port)) == 0


def ping_server(timeout: float=0.5):
    """Return True if the server responds *in any way* to /connector/ping."""
    try:
        out = subprocess.check_output([
            'curl', '-m', str(timeout), '-s', '-o', '/dev/null', '-w', '%{http_code}',
            PING_URL
        ])
        status = out.decode().strip()
        return status.isdigit()  # 200, 404, etc. — anything is good
    except subprocess.CalledProcessError:
        return False


# ------------------------------
# Server Lifecycle Management
# ------------------------------

def start_server(patience: float=10, timestep: float=0.25):
    """
    Start the translation server only if not already running.
    Wait until it's *actually responding*, not just bound to port.
    """
    global _translation_process

    if is_port_open(SERVER_PORT):
        print(f"ℹ️ Translation server already running on port {SERVER_PORT}.")
        return

    print(f"🔄 Starting translation server on port {SERVER_PORT}...")

    # Kill any stale process bound to port before launching new
    kill_pid_using_port(SERVER_PORT)

    # Check that the node version is at most 20
    check_node_version()

    server_path = os.path.join(dirname(dirname(__file__)), 'translation_server')
    _translation_process = subprocess.Popen(
        ['node', 'src/server.js'],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        cwd=server_path,
        preexec_fn=os.setsid
    )

    # Wait for port binding + ping success
    start = time.time()
    print("⏳ Waiting for server to become ready", end="", flush=True)
    while time.time() - start < patience:
        if is_port_open(SERVER_PORT) and ping_server():
            print("\n✅ Server is ready!")
            return
        print(".", end="", flush=True)
        time.sleep(timestep)

    # Failed startup — dump logs for debugging
    print("\n❌ Translation server failed to start. Logs:")
    logs = ''
    try:
        logs = (
            _translation_process.stdout.read().decode()
            + _translation_process.stderr.read().decode())
        print(logs)
    except Exception:
        pass

    # The most common cause is a translation server built against a
    # newer jsdom than the local node can load
    if 'ERR_REQUIRE_ESM' in logs:
        print(
            f"👉 Your translation server requires a more recent node than "
            f"{get_node_version()}. Either install node >=20.19, or "
            f"reinstall NoRA to get the pinned translation server revision:"
            f"\n     pip install --force-reinstall "
            f"git+https://github.com/vschelbi/nora.git")

    sys.exit(1)


def kill_server():
    """Kill the server and all children properly."""
    global _translation_process
    if _translation_process is None:
        return

    # Kill process group
    try:
        os.killpg(os.getpgid(_translation_process.pid), signal.SIGTERM)
    except ProcessLookupError:
        pass

    # Cleanup lingering socket holders
    kill_pid_using_port(SERVER_PORT)
    _translation_process = None


def kill_pid_using_port(port: Union[str, int], patience: float=5, timestep: float=0.1):
    pid = get_pid_using_port(port)
    if pid is None or pid <= 0:
        return  # nothing to kill

    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        return

    start = time.time()
    while True:
        pid = get_pid_using_port(port)
        if pid is None or pid <= 0 or time.time() - start > patience:
            break
        time.sleep(timestep)


def safe_kill_server():
    try:
        kill_server()
    except Exception:
        pass

# Automatically shut down at program exit
atexit.register(safe_kill_server)


# ------------------------------
# Data & Translation Functions
# ------------------------------

def json_to_python(data: Union[str, List, Dict]):
    """Same conversion helper you had — unchanged."""
    try:
        data = data.decode()
    except (UnicodeDecodeError, AttributeError):
        pass

    try:
        data = json.loads(data)
    except:
        pass

    if isinstance(data, str):
        print(f"❌ The translation server returned an error message:\n{data}")
        sys.exit(1)

    if isinstance(data, list):
        if len(data) == 0:
            print(
                "❌ The translation server could not extract any metadata "
                "from this page. It may not be supported, or the page may "
                "have refused the request.")
            sys.exit(1)
        if isinstance(data[0], dict):
            data = data[0]
        else:
            print(
                f"❌ Expected a List(Dict), but received a "
                f"List({type(data[0])}):\n{data}")
            sys.exit(1)
    elif not isinstance(data, dict):
        print(f"❌ Expected a Dict or a List(Dict), got a {type(data)}:\n{data}")
        sys.exit(1)

    if 'data' not in data:
        data['data'] = {**data}

    # Anything other than an item, e.g. an unhandled selection request,
    # would otherwise only fail later when reading its fields
    if 'itemType' not in data['data']:
        print(f"❌ The translation server did not return an item:\n{json.dumps(data)}")
        sys.exit(1)

    print("✅ Metadata retrieved successfully!")

    return data


def post_to_server(
        endpoint: str,
        data: str,
        content_type: str="text/plain",
        timeout: float=20):
    """POST to the translation server and return the response body
    along with its HTTP status code.
    """
    try:
        out = subprocess.check_output([
            'curl', '-s', '-S', '-d', data, '-m', f'{timeout}', '-H', f"Content-Type: {content_type}",
            '-w', '\n%{http_code}', f"{SERVER_IP}/{endpoint}"
        ])
    except subprocess.CalledProcessError:
        print("❌ Failed to contact the translation server. Please check your internet connection or try again.")
        sys.exit(1)
    body, _, status = out.decode().rpartition('\n')
    return body, int(status)


def select_item(choices: Dict[str, str]):
    """Pick one of the items the translation server found on a page,
    the way the Zotero connector asks in the browser. A single choice
    needs no asking.
    """
    if len(choices) == 1:
        key, title = next(iter(choices.items()))
        print(f"ℹ️ The page points to another item, using it: {title}")
        return {key: title}

    print("ℹ️ The page lists several items:")
    keys = list(choices)
    for i, key in enumerate(keys, start=1):
        print(f"   {i}. {choices[key]}")
    while True:
        try:
            answer = input(f"👉 Which one should be added? [1-{len(keys)}] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n❌ No item selected.")
            sys.exit(1)
        if answer.isdigit() and 1 <= int(answer) <= len(keys):
            key = keys[int(answer) - 1]
            return {key: choices[key]}


def translate_from_url(url: str, timeout: float=20):
    start_server()
    print(f"ℹ️ Retrieving metadata for URL: {url} ...")
    body, status = post_to_server('web', url, timeout=timeout)

    # 300 Multiple Choices: the page is a list of items rather than an
    # item, e.g. a preprint pointing to its published version. The
    # server waits for the selection to be sent back with the session
    if status == 300:
        choices = json.loads(body)
        choices['items'] = select_item(choices['items'])
        body, status = post_to_server(
            'web', json.dumps(choices), content_type="application/json",
            timeout=timeout)

    return json_to_python(body)


def translate_from_identifier(identifier: str, timeout: float=20):
    start_server()
    print(f"ℹ️ Retrieving metadata for identifier: {identifier} ...")
    body, _ = post_to_server('search', identifier, timeout=timeout)
    return json_to_python(body)


def get_node_version():
    return subprocess.check_output(["node", "-v"]).decode().strip()


def check_node_version():
    output = get_node_version()
    major = int(output.replace('v', '').split(".")[0])
    if major > 20:
        print(f"⚠️ Detected node {major}. Please use node 20.x for compatibility.")

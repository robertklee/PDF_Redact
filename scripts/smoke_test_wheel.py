"""Install a wheel built by `python3 run.py --wheel` into a new environment and check that it runs.

    python scripts/smoke_test_wheel.py dist/pdf_redact-<version>-py3-none-any.whl

The server is started outside the repository, so the UI must come from inside the wheel.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
import venv
from pathlib import Path

PORT = 8790
BASE = f"http://127.0.0.1:{PORT}"
TOKEN = "smoke-test"


def fetch(path, data=None, token=TOKEN, content_type=None):
    headers = {"X-Session-Token": token} if token else {}
    if content_type:
        headers["Content-Type"] = content_type
    request = urllib.request.Request(BASE + path, data=data, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()


def wait_for_server(server):
    for _ in range(120):
        if server.poll() is not None:
            sys.exit(f"The server exited with code {server.returncode}")
        try:
            return fetch("/")
        except OSError:
            time.sleep(0.5)
    sys.exit("The server did not start")


def main():
    wheel = Path(sys.argv[1]).resolve()
    work = Path(tempfile.mkdtemp())
    try:
        check(wheel, work)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print("The wheel installs and runs.")


def check(wheel, work):
    venv.create(work / "venv", with_pip=True)
    bin_dir = work / "venv" / ("Scripts" if os.name == "nt" else "bin")
    python = bin_dir / ("python.exe" if os.name == "nt" else "python")
    pip = [python, "-m", "pip", "install", "-q", "--disable-pip-version-check"]
    subprocess.run([*pip, wheel], check=True)

    pdf = work / "sample.pdf"
    make_pdf = (
        "import pymupdf, sys; d = pymupdf.open();"
        "d.new_page().insert_text((72, 72), 'Top secret'); d.save(sys.argv[1])"
    )
    subprocess.run([python, "-c", make_pdf, pdf], check=True)

    env = {k: v for k, v in os.environ.items() if not k.startswith("PDF_REDACT_")}
    env["PDF_REDACT_TOKEN"] = TOKEN
    server = subprocess.Popen(
        [bin_dir / "pdf-redact", "--no-browser", "--port", str(PORT)], cwd=work, env=env
    )
    try:
        status, body = wait_for_server(server)
        assert status == 200 and b'<div id="root">' in body, "the UI is not served"
        status, _ = fetch("/pdfjs/cmaps/78-H.bcmap")
        assert status == 200, "the PDF.js assets are not served"
        status, _ = fetch("/api/detectors", token=None)
        assert status == 401, f"the API answered {status} without the session token"

        status, body = fetch(
            "/api/documents?filename=sample.pdf", pdf.read_bytes(), content_type="application/pdf"
        )
        assert status == 201, f"upload failed: {status} {body[:200]!r}"
        document = json.loads(body)["id"]
        status, body = fetch(f"/api/documents/{document}/pages/0/text")
        assert status == 200, f"page text failed: {status} {body[:200]!r}"
        text = " ".join("".join(line["chars"]) for line in json.loads(body)["lines"])
        assert "Top secret" in text, f"unexpected page text: {text!r}"
    finally:
        server.terminate()
        server.wait(timeout=30)


if __name__ == "__main__":
    main()

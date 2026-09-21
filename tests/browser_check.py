"""Run the reading-library browser smoke checks against an isolated test database."""
from pathlib import Path
import os
import subprocess
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from test_library import LibraryTest
from literature_radar.models import Paper


def main():
    candidates = [
        Path(os.environ.get('ProgramFiles(x86)', 'C:/Program Files (x86)')) / 'Microsoft/Edge/Application/msedge.exe',
        Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'Google/Chrome/Application/chrome.exe',
    ]
    browser = next((p for p in candidates if p.exists()), None)
    if browser is None:
        raise SystemExit('Install Edge or Chrome to run browser checks.')
    output = Path(sys.argv[1] if len(sys.argv) > 1 else 'tests/artifacts').resolve()
    output.mkdir(parents=True, exist_ok=True)
    fixture = LibraryTest()
    try:
        fixture.setUp()
        for i in range(2, 23):
            fixture.store.upsert_paper(Paper(source='pubmed', external_id=str(i), title=f'Spatial paper {i}', abstract='', url=''))
        port = fixture.start_server()
        result = subprocess.run(['node', str(Path(__file__).with_name('browser_library.mjs')),
                                 f'http://127.0.0.1:{port}/', str(browser), str(output)],
                                timeout=90, creationflags=subprocess.CREATE_NO_WINDOW, capture_output=True, text=True, encoding="utf-8")
        print(result.stdout)
        print(result.stderr)
        return result.returncode
    finally:
        fixture.doCleanups()


if __name__ == '__main__':
    raise SystemExit(main())
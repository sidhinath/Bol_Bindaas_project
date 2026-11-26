"""Run the Python test suite with line coverage using only the standard library."""

import sys
import threading
import trace
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TESTS = Path(__file__).resolve().parent
COVERDIR = ROOT / ".coverage"

suite = unittest.defaultTestLoader.discover(
    str(TESTS), pattern="test_*.py", top_level_dir=str(TESTS)
)
runner = unittest.TextTestRunner(verbosity=2)

tracer = trace.Trace(
    count=True,
    trace=False,
    ignoremods=("http.server", "socketserver", "urllib.request", "urllib.error"),
    ignoredirs=(sys.prefix, sys.exec_prefix, str(TESTS)),
)

# Server code also runs on HTTP handler threads, so trace new threads too.
threading.settrace(tracer.globaltrace)
try:
    result = tracer.runfunc(runner.run, suite)
finally:
    threading.settrace(None)

coverage = tracer.results()
project_counts = {}
for (filename, lineno), count in coverage.counts.items():
    try:
        path = Path(filename).resolve()
    except (OSError, TypeError):
        continue
    if path.is_relative_to(ROOT):
        project_counts[(str(path), lineno)] = count
coverage.counts = project_counts

coverage.write_results(show_missing=True, summary=True, coverdir=str(COVERDIR))
print(f"Python line coverage written to {COVERDIR}")

raise SystemExit(0 if result.wasSuccessful() else 1)

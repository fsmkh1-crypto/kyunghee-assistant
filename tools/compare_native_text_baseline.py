"""Compare one controlled Windows Unicode test with exact old source files.

This is a WM_UNICHAR/modifier experiment, not actual Korean IME composition.
Only the expected missing-jamo assertion counts as reproducing the old defect.
"""
import argparse
import hashlib
import importlib.util
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
import unittest


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline-ime', type=Path, required=True)
    parser.add_argument('--baseline-ui', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    report = {'status': 'unavailable', 'actual_korean_ime': False,
              'evidence': 'WM_UNICHAR through Windows Tk with controlled Ctrl state',
              'actual_api_calls': 0,
              'baseline_sha256': {name: hashlib.sha256(path.read_bytes()).hexdigest()
                                  for name, path in [('ime', args.baseline_ime), ('ui', args.baseline_ui)]}}
    if os.name == 'nt':
        with tempfile.TemporaryDirectory(prefix='seunga-native-baseline-') as profile:
            os.environ['APPDATA'] = profile
            repo = Path(__file__).resolve().parents[1]
            sys.path[:0] = [str(repo), str(repo / 'tests')]
            import assistant_ai
            assistant_ai.windows_ime = load('assistant_ai.windows_ime', args.baseline_ime)
            assistant_ai.ui = load('assistant_ai.ui', args.baseline_ui)
            from test_assistant_native_text import NativeTextDeliveryTests
            suite = unittest.TestSuite([NativeTextDeliveryTests(
                'test_control_modified_native_last_jamo_is_preserved')])
            output = io.StringIO()
            result = unittest.TextTestRunner(stream=output, verbosity=2).run(suite)
            expected = "AssertionError: '근데 느림...' != '근데 느림...ㅋ'"
            reproduced = (not result.errors and not result.skipped and len(result.failures) == 1
                          and expected in result.failures[0][1])
            report.update(status=('reproduced' if reproduced else 'not_reproduced' if result.wasSuccessful()
                                  and not result.skipped else 'inconclusive'),
                          tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                          skipped=len(result.skipped), log=output.getvalue())
            # Importing the real UI can initialize app.py's rotating log in
            # this isolated profile. Windows cannot remove an open log file.
            # This subprocess owns the handlers; close them before teardown.
            logging.shutdown()
    else:
        report['reason'] = 'Windows native dispatcher required'
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'status': report['status'], 'actual_korean_ime': False}, ensure_ascii=False))
    return 3 if report['status'] in {'inconclusive', 'unavailable'} else 0


if __name__ == '__main__':
    raise SystemExit(main())

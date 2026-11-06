param(
    [ValidateSet('Validate', 'Build', 'Smoke', 'Prepare', 'All')]
    [string]$Stage = 'All'
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
if (-not $IsWindows) { throw 'This packaging script requires Windows PowerShell 7.' }

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$evidenceRoot = Join-Path $repoRoot 'build/ai-review-evidence'
$packageRoot = Join-Path $repoRoot 'dist/KyungheeTimerAIReview'
$exePath = Join-Path $packageRoot 'KyungheeTimerAIReview.exe'
New-Item -ItemType Directory -Path $evidenceRoot -Force | Out-Null

function Invoke-ReviewPython {
    param([string[]]$Arguments)
    & python @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python verification/build failed (exit $LASTEXITCODE)." }
}

Push-Location $repoRoot
try {
    if ($Stage -in @('Validate', 'All')) {
        if (-not (Test-Path 'desktop_ai_review.py')) { throw 'The isolated review entrypoint is missing.' }
        $validationScript = @'
from pathlib import Path
import json
import logging
import os
import py_compile
import sys
import tempfile
import unittest
from unittest.mock import patch

root = Path.cwd()
evidence = root / 'build' / 'ai-review-evidence'
sys.path.insert(0, str(root))
for path in sorted(root.glob('*.py')):
    py_compile.compile(str(path), doraise=True)
assert os.name == 'nt'
# Discovery imports test_ai_desktop before app, preserving its isolated APPDATA.
suite = unittest.defaultTestLoader.discover('tests')
with patch('desktop_compact.should_suppress_overlay_notifications', return_value=False):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
summary = {'tests_run': result.testsRun, 'failures': len(result.failures),
           'errors': len(result.errors), 'skipped': len(result.skipped),
           'presentation_suppression_mocked_for_unit_tests': True}
(evidence / 'unit-tests.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
logging.shutdown()
desktop_tests = sys.modules.get('test_ai_desktop')
if desktop_tests is not None:
    desktop_tests._DATA.cleanup()
if not result.wasSuccessful():
    raise SystemExit(1)
if result.testsRun < 175:
    raise SystemExit('Expected the full current suite (at least 175 tests).')
'@
        $validationPath = Join-Path $evidenceRoot 'validate_suite.py'
        Set-Content -Path $validationPath -Value $validationScript -Encoding utf8
        Invoke-ReviewPython -Arguments @($validationPath)

        $windowsGate = @'
from pathlib import Path
import json
import logging
import os
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch
import unittest

assert os.name == 'nt', 'Native Windows checks must run on Windows.'
root = Path.cwd()
evidence = root / 'build' / 'ai-review-evidence'
sys.path.insert(0, str(root))
sys.path.insert(0, str(root / 'tests'))
import test_ai_desktop
from test_minimal_desktop import MinimalMainSurfaceTests
from test_random_gallery import RandomGalleryTkTests
from test_ai_credentials import AICredentialsTests
suite = unittest.TestSuite([
    unittest.defaultTestLoader.loadTestsFromTestCase(test_ai_desktop.GalleryAITests),
    unittest.defaultTestLoader.loadTestsFromTestCase(MinimalMainSurfaceTests),
    unittest.defaultTestLoader.loadTestsFromTestCase(RandomGalleryTkTests),
    AICredentialsTests('test_real_windows_dpapi_round_trip_and_tampering'),
])
with patch('desktop_compact.should_suppress_overlay_notifications', return_value=False):
    result = unittest.TextTestRunner(verbosity=2).run(suite)
if not result.wasSuccessful() or result.skipped or result.testsRun < 5:
    logging.shutdown()
    test_ai_desktop._DATA.cleanup()
    raise SystemExit('Native GUI and real DPAPI tests must execute without skips.')

from ai_credentials import AICredentials
from ai_desktop import AIService
from desktop_gallery_final import FinalGalleryDesktopApp
import app as core

class OfflineClient:
    calls = 0
    def generate(self, _key, **_kwargs):
        self.calls += 1
        assert 'asset_catalog' not in _kwargs, 'Chat must not receive asset capabilities.'
        return SimpleNamespace(text='잘 왔어. 오늘도 옆에서 응원할게.', error_code='')

# Existing test imports cached app.DATA_DIR; explicitly isolate this native panel
# check as well. No real key or real API request is used at any point.
dummy_key = 'review-ci-dummy-credential-not-a-real-api-key'
with tempfile.TemporaryDirectory(prefix='kyunghee-native-review-') as temp:
    data = Path(temp) / 'KyungheeAssistant'
    data.mkdir()
    core.DATA_DIR = data
    core.STATE_FILE = data / 'state.json'
    core.SETTINGS_FILE = data / 'settings.json'
    client = OfflineClient()
    service = AIService(client, cooldown_seconds=0, chat_cooldown_seconds=0)
    app = None
    try:
        with patch('ai_desktop.AIService', return_value=service), \
             patch('app.App._start_tray'), \
             patch('desktop_compact.CompactDesktopApp._start_global_hotkey'), \
             patch('desktop_gallery.GalleryDesktopApp.MANUAL_OVERRIDE_FILE', data / 'manual_asset_overrides.json'), \
             patch('desktop_compact.USER_IMAGE_DIR', data / 'images'), \
             patch('desktop_compact.USER_IMAGE_SET_DIR', data / 'image_sets'), \
             patch('desktop_compact.should_suppress_overlay_notifications', return_value=False), \
             patch('socket.create_connection', side_effect=AssertionError('Network is disabled in native checks')), \
             patch('socket.socket.connect', side_effect=AssertionError('Network is disabled in native checks')):
            app = FinalGalleryDesktopApp()
            app.root.update()
            panel = app.ai_settings_panel
            assert panel.credentials.supports_persistence
            panel.enabled_var.set(True)
            panel.remember_var.set(True)
            panel.key_var.set(dummy_key)
            panel.apply()
            assert app.preferences.ai_enabled and app.preferences.ai_remember_key
            assert service._enabled and panel.credentials.api_key == dummy_key
            assert panel.key_var.get() == ''
            assert panel.credentials.path.is_file()
            assert dummy_key.encode() not in panel.credentials.path.read_bytes()
            restored = AICredentials(data)
            assert restored.load_saved_key(True).ok and restored.api_key == dummy_key
            saved = core.SETTINGS_FILE.read_text(encoding='utf-8')
            assert dummy_key not in saved and 'api_key' not in saved
            assert '승아' in core.APP_NAME
            assert app.root.tk.getboolean(app.root.attributes('-topmost'))
            assert app._chat_window is not None and app._chat_window.winfo_viewable()
            for metric in (app.clock, app.cont, app.main_status, app.escape_control):
                assert not metric.winfo_ismapped(), 'Main timer metrics must stay hidden.'
            assert app.character.winfo_ismapped() and app.speech.winfo_ismapped()
            assert not hasattr(app, 'chat_control'), 'The separate chat control must be removed.'
            before_settings_click = app.speech.cget('text')
            app.character.event_generate('<ButtonPress-1>', x=10, y=10)
            app.character.event_generate('<ButtonRelease-1>', x=10, y=10)
            app.root.update_idletasks()
            assert app.current_page == 'settings', 'Character click must open settings.'
            assert app.speech.cget('text') == before_settings_click
            app._show_page('timer')
            speech_before_open = app.speech.cget('text')
            app.speech.event_generate('<Button-1>', x=10, y=10)
            app.root.update_idletasks()
            assert app._chat_window is not None and app._chat_window.winfo_exists()
            assert app.speech.cget('text') == speech_before_open
            assert app._chat_window.tk.getboolean(app._chat_window.attributes('-topmost'))
            app._chat_window.withdraw()
            app._open_chat()
            assert app._chat_window.tk.getboolean(app._chat_window.attributes('-topmost'))
            speech_before_send = app.speech.cget('text')
            app._chat_entry.insert(0, '안녕')
            app._send_chat()
            assert app.speech.cget('text') == speech_before_send
            assert app._chat_messages[-1][0] == '승아 · 대기 중'
            deadline = time.monotonic() + 1
            while service._in_flight is not None and time.monotonic() < deadline:
                app._ai_poll()
                app.root.update_idletasks()
                time.sleep(0.005)
            assert client.calls == 1 and app._chat_messages[-1][0] == '승아 · AI'
            app.state.daily.active_seconds = 3661
            app.state.session.continuous_seconds = 123
            app.state.daily.away_seconds = 61
            timer_before = (app.state.daily.active_seconds, app.state.session.continuous_seconds, app.state.daily.away_seconds)
            preferences_before = app.preferences
            speech_before_status = app.speech.cget('text')
            app._chat_entry.insert(0, '타이머 상태 알려줘')
            app._send_chat()
            assert client.calls == 1 and app._chat_messages[-1][0] == '승아 · 타이머'
            assert '1시간 1분 1초' in app._chat_messages[-1][1]
            assert '2분 3초' in app._chat_messages[-1][1]
            assert (app.state.daily.active_seconds, app.state.session.continuous_seconds, app.state.daily.away_seconds) == timer_before
            assert app.preferences == preferences_before
            assert app.speech.cget('text') == speech_before_status
            panel.clear_key()
            assert not panel.credentials.has_key and not panel.credentials.path.exists()
            assert not service._enabled
            for path in data.rglob('*'):
                if path.is_file():
                    assert dummy_key.encode() not in path.read_bytes()
    finally:
        service.close()
        if app is not None:
            app._ai_closed = True
            for pending in app.root.tk.call('after', 'info'):
                app.root.tk.call('after', 'cancel', pending)
            app.root.destroy()
        if service._worker is not None:
            service._worker.join(timeout=1)
        logging.shutdown()
test_ai_desktop._DATA.cleanup()
summary = {'native_gui_tests': result.testsRun - 1, 'native_gui_or_DPAPI_skips': 0,
           'real_windows_DPAPI': True, 'direct_key_input_panel': True,
           'encrypted_remember_load_clear': True, 'settings_exclude_key': True,
           'mocked_AI_chat': True, 'no_local_message_before_AI_reply': True,
           'bubble_click_opens_chat': True, 'separate_chat_button_removed': True,
           'character_click_opens_settings': True, 'ordinary_AI_chat_has_no_control_tools': True,
           'main_timer_metrics_hidden': True, 'chat_visible_on_startup': True,
           'chat_settings_control_removed': True, 'timer_queries_local_immediate_without_API': True,
           'actual_timer_status_read_only': True,
           'visible_dice_random_and_restore': True,
           'random_image_does_not_change_saved_settings': True,
           'dice_preserves_character_bubble_click_and_drag': True,
           'timer_always_on_top': True, 'chat_always_on_top': True, 'visible_name_Seunga': True,
           'real_API_requests': 0, 'real_API_key_used': False}
(evidence / 'native-windows-checks.json').write_text(json.dumps(summary, indent=2) + '\n', encoding='utf-8')
print('Native Windows GUI, direct key input and DPAPI checks passed without a real API key.')
'@
        $gatePath = Join-Path $evidenceRoot 'native_windows_gate.py'
        Set-Content -Path $gatePath -Value $windowsGate -Encoding utf8
        Invoke-ReviewPython -Arguments @($gatePath)
    }

    if ($Stage -in @('Build', 'All')) {
        $assetSource = Join-Path $repoRoot 'assets'
        Invoke-ReviewPython -Arguments @(
            '-m', 'PyInstaller', '--noconfirm', '--clean', '--onedir', '--windowed',
            '--name', 'KyungheeTimerAIReview', '--add-data', "$assetSource;assets",
            '--hidden-import', 'pystray._win32',
            '--workpath', 'build/ai-review-pyinstaller',
            'desktop_ai_review.py'
        )
        if (-not (Test-Path $exePath)) { throw 'The Windows EXE was not produced.' }
    }

    if ($Stage -in @('Smoke', 'All')) {
        if (-not (Test-Path $exePath)) { throw 'Build the Windows EXE before smoke testing.' }
        $smokeRoot = Join-Path ([System.IO.Path]::GetTempPath()) ('kyunghee-review-smoke-' + [guid]::NewGuid().ToString('N'))
        $roaming = Join-Path $smokeRoot 'roaming'
        $local = Join-Path $smokeRoot 'local'
        $oldData = Join-Path $roaming 'KyungheeAssistant'
        $reviewData = Join-Path $local 'KyungheeTimer_AI_Review/KyungheeAssistant'
        New-Item -ItemType Directory -Path $oldData, $local -Force | Out-Null
        Set-Content (Join-Path $oldData 'settings.json') '{"always_on_top":false,"ai_enabled":false}' -Encoding utf8NoBOM
        Set-Content (Join-Path $oldData 'state.json') '{"original_user_data":"preserve"}' -Encoding utf8NoBOM
        Set-Content (Join-Path $oldData 'PRESERVE_EXISTING_DATA.txt') 'Existing profile must remain byte-identical.' -Encoding utf8NoBOM
        $before = @{}
        Get-ChildItem $oldData -Recurse -File | ForEach-Object { $before[$_.FullName] = (Get-FileHash $_.FullName -Algorithm SHA256).Hash }
        $oldAppData = $env:APPDATA
        $oldLocalData = $env:LOCALAPPDATA
        $oldBackend = $env:PYSTRAY_BACKEND
        $process = $null
        try {
            $env:APPDATA = $roaming
            $env:LOCALAPPDATA = $local
            Remove-Item Env:PYSTRAY_BACKEND -ErrorAction SilentlyContinue
            if (-not ('KyungheeReviewSmokeWindows' -as [type])) {
                Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
public static class KyungheeReviewSmokeWindows {
    private delegate bool EnumProc(IntPtr hwnd, IntPtr data);
    [DllImport("user32.dll")] private static extern bool EnumWindows(EnumProc callback, IntPtr data);
    [DllImport("user32.dll")] private static extern bool IsWindowVisible(IntPtr hwnd);
    [DllImport("user32.dll")] private static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint processId);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetClassName(IntPtr hwnd, StringBuilder text, int size);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] private static extern int GetWindowText(IntPtr hwnd, StringBuilder text, int size);
    [StructLayout(LayoutKind.Sequential)] private struct WindowRect { public int Left, Top, Right, Bottom; }
    [DllImport("user32.dll")] private static extern bool GetWindowRect(IntPtr hwnd, out WindowRect rect);
    [DllImport("user32.dll", EntryPoint="GetWindowLongPtrW")] private static extern IntPtr GetWindowLongPtr(IntPtr hwnd, int index);
    public static bool HasVisibleTkWindow(int processId) {
        bool found = false;
        EnumWindows(delegate(IntPtr hwnd, IntPtr data) {
            uint owner; GetWindowThreadProcessId(hwnd, out owner);
            StringBuilder name = new StringBuilder(256); GetClassName(hwnd, name, name.Capacity);
            if (owner == processId && IsWindowVisible(hwnd) && name.ToString().StartsWith("Tk")) found = true;
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static bool HasVisibleTopmostTkWindow(int processId, string titlePrefix) {
        bool found = false;
        EnumWindows(delegate(IntPtr hwnd, IntPtr data) {
            uint owner; GetWindowThreadProcessId(hwnd, out owner);
            StringBuilder name = new StringBuilder(256); GetClassName(hwnd, name, name.Capacity);
            StringBuilder title = new StringBuilder(256); GetWindowText(hwnd, title, title.Capacity);
            if (owner == processId && IsWindowVisible(hwnd) && name.ToString().StartsWith("Tk") &&
                title.ToString().StartsWith(titlePrefix, StringComparison.Ordinal) &&
                (GetWindowLongPtr(hwnd, -20).ToInt64() & 0x8) != 0) found = true;
            return true;
        }, IntPtr.Zero);
        return found;
    }
    public static bool CompanionWindowsAreSeparate(int processId, string mainTitle, string chatTitle) {
        WindowRect main = new WindowRect(), chat = new WindowRect();
        bool hasMain = false, hasChat = false;
        EnumWindows(delegate(IntPtr hwnd, IntPtr data) {
            uint owner; GetWindowThreadProcessId(hwnd, out owner);
            if (owner != processId || !IsWindowVisible(hwnd)) return true;
            StringBuilder title = new StringBuilder(256); GetWindowText(hwnd, title, title.Capacity);
            if (title.ToString().StartsWith(mainTitle, StringComparison.Ordinal)) hasMain = GetWindowRect(hwnd, out main);
            if (title.ToString().StartsWith(chatTitle, StringComparison.Ordinal)) hasChat = GetWindowRect(hwnd, out chat);
            return true;
        }, IntPtr.Zero);
        int overlapWidth = Math.Min(main.Right, chat.Right) - Math.Max(main.Left, chat.Left);
        int overlapHeight = Math.Min(main.Bottom, chat.Bottom) - Math.Max(main.Top, chat.Top);
        // Allow a small native decoration border, never substantial coverage.
        return hasMain && hasChat && (overlapWidth <= 24 || overlapHeight <= 24);
    }
}
'@
            }
            $process = Start-Process -FilePath $exePath -WorkingDirectory $packageRoot -PassThru
            $visibleTk = $false
            for ($probe = 0; $probe -lt 40; $probe++) {
                $process.Refresh()
                if ($process.HasExited) { throw "Review EXE exited during startup (exit $($process.ExitCode))." }
                if ([KyungheeReviewSmokeWindows]::HasVisibleTkWindow($process.Id)) { $visibleTk = $true; break }
                Start-Sleep -Milliseconds 250
            }
            if (-not $visibleTk) { throw 'The review EXE did not create a visible Tk window.' }
            Start-Sleep -Seconds 8
            $process.Refresh()
            if ($process.HasExited) { throw "Review EXE exited during smoke test (exit $($process.ExitCode))." }
            if (-not [KyungheeReviewSmokeWindows]::HasVisibleTkWindow($process.Id)) { throw 'The review Tk window disappeared.' }
            if (-not [KyungheeReviewSmokeWindows]::HasVisibleTopmostTkWindow($process.Id, '승아 타이머')) { throw 'The timer window is not natively topmost.' }
            if (-not [KyungheeReviewSmokeWindows]::HasVisibleTopmostTkWindow($process.Id, '승아와 대화')) { throw 'The chat window is not visibly topmost on startup.' }
            if (-not [KyungheeReviewSmokeWindows]::CompanionWindowsAreSeparate($process.Id, '승아 타이머', '승아와 대화')) { throw 'The startup chat covers the character window.' }
            $logPath = Join-Path $reviewData 'kyunghee.log'
            $statePath = Join-Path $reviewData 'state.json'
            if (-not (Test-Path $logPath)) { throw 'The isolated review log was not created.' }
            if (-not (Test-Path $statePath)) { throw 'The timer did not periodically save isolated review state.' }
            $state = Get-Content $statePath -Raw | ConvertFrom-Json
            if (-not $state.daily.day -or $state.session.last_seen_wall -le 0) { throw 'The isolated timer state is invalid.' }
            $trackedSeconds = [double]$state.daily.active_seconds + [double]$state.daily.away_seconds
            if ($trackedSeconds -lt 3) { throw 'The hidden timer did not accumulate time during the actual EXE smoke test.' }
            $errors = Select-String -Path $logPath -Pattern 'tick failed|Traceback|asset failed| ERROR |font registration failed'
            if ($errors) { throw 'The isolated review log contains a startup, timer or asset error.' }
            if (Test-Path (Join-Path $reviewData 'openai_api_key.dpapi')) { throw 'The fresh package unexpectedly created credentials.' }
            $afterFiles = @(Get-ChildItem $oldData -Recurse -File)
            if ($afterFiles.Count -ne $before.Count) { throw 'The original profile file inventory changed.' }
            foreach ($file in $afterFiles) {
                if (-not $before.ContainsKey($file.FullName) -or $before[$file.FullName] -ne (Get-FileHash $file.FullName -Algorithm SHA256).Hash) {
                    throw 'An original profile file changed during review smoke testing.'
                }
            }
            @{ alive_seconds_after_window = 8; visible_native_Tk_window = $true; native_topmost_timer_window = $true;
               native_topmost_chat_window = $true; companion_windows_separate = $true; periodic_state_saved = $true;
               tracked_seconds_at_save = $trackedSeconds; hidden_timer_time_accumulation_verified = $true;
               isolated_log_checked = $true; default_profile_unchanged = $true; native_tray_backend = $true;
               real_API_key_used = $false; review_data_relative = 'KyungheeTimer_AI_Review/KyungheeAssistant' } |
                ConvertTo-Json | Set-Content (Join-Path $evidenceRoot 'packaged-smoke.json') -Encoding utf8
        }
        finally {
            if ($null -ne $process) {
                $process.Refresh()
                if (-not $process.HasExited) { Stop-Process -Id $process.Id -Force; $process.WaitForExit() }
                $process.Dispose()
            }
            if ($null -eq $oldAppData) { Remove-Item Env:APPDATA -ErrorAction SilentlyContinue } else { $env:APPDATA = $oldAppData }
            if ($null -eq $oldLocalData) { Remove-Item Env:LOCALAPPDATA -ErrorAction SilentlyContinue } else { $env:LOCALAPPDATA = $oldLocalData }
            if ($null -eq $oldBackend) { Remove-Item Env:PYSTRAY_BACKEND -ErrorAction SilentlyContinue } else { $env:PYSTRAY_BACKEND = $oldBackend }
            Remove-Item $smokeRoot -Recurse -Force -ErrorAction SilentlyContinue
        }
    }

    if ($Stage -in @('Prepare', 'All')) {
        if (-not (Test-Path $exePath)) { throw 'The review EXE is missing.' }
        $forbidden = Get-ChildItem $packageRoot -Recurse -File | Where-Object { $_.Name -in @('openai_api_key.dpapi', 'state.json', 'settings.json') }
        if ($forbidden) { throw 'The build unexpectedly contains runtime state or credentials.' }
        Copy-Item 'AI_REVIEW_QUICKSTART.txt' (Join-Path $packageRoot '시작안내.txt')
        Copy-Item 'LICENSE' (Join-Path $packageRoot 'LICENSE')
        Copy-Item 'README.md' (Join-Path $packageRoot 'README.md')
        $commit = (& git rev-parse HEAD).Trim()
        if ($LASTEXITCODE -ne 0) { throw 'Could not record the source commit.' }
        Set-Content (Join-Path $packageRoot 'SOURCE_COMMIT.txt') $commit -Encoding utf8
        $verification = Join-Path $packageRoot 'build-verification'
        New-Item -ItemType Directory -Path $verification -Force | Out-Null
        foreach ($name in @('unit-tests.json', 'native-windows-checks.json', 'packaged-smoke.json')) {
            $summary = Join-Path $evidenceRoot $name
            if (-not (Test-Path $summary)) { throw "Required verification summary is missing: $name" }
            Copy-Item $summary (Join-Path $verification $name)
        }
        $assetInventoryScript = @'
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

package = Path(sys.argv[1])
assets = package / '_internal' / 'assets'
source_assets = Path.cwd() / 'assets'
assert assets.is_dir(), 'Packaged asset directory is missing.'
roles = ('default', 'cheer', 'rest', 'away', 'warning', 'leave', 'stats', 'settings', 'alert', 'profile')
image_extensions = {'.png', '.jpg', '.jpeg', '.webp', '.gif'}
def inventory(root):
    return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in root.rglob('*') if p.is_file() and p.suffix.lower() in image_extensions}
packaged = inventory(assets)
source = inventory(source_assets)
assert packaged == source, 'Packaged image inventory differs from the source images.'
by_role = {}
numbered_count = 0
for role in roles:
    numbers = set()
    for path in (assets / role).glob('*.png'):
        match = re.fullmatch(re.escape(role) + r'_(\d{2})', path.stem)
        if match:
            numbers.add(match.group(1))
            numbered_count += 1
    by_role[role] = sorted(numbers)
complete = sorted(set.intersection(*(set(by_role[role]) for role in roles)))
record = {'source_commit': subprocess.check_output(['git', 'rev-parse', 'HEAD']).decode().strip(),
          'inspection': 'Actual frozen package directory after PyInstaller; every image hash compared to source',
          'complete_numbered_sets': complete, 'complete_set_count': len(complete),
          'numbered_png_count': numbered_count, 'image_count': len(packaged),
          'numbers_per_role': by_role, 'packaged_images_match_source': True,
          'image_sha256': packaged,
          'build_workflow_fetches_external_asset_packs': False}
destination = package / 'build-verification' / 'asset-inventory.json'
destination.write_text(json.dumps(record, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
print('PACKAGED_ASSET_INVENTORY ' + json.dumps({k: record[k] for k in
      ('complete_numbered_sets', 'complete_set_count', 'numbered_png_count', 'image_count', 'packaged_images_match_source')}))
'@
        $assetInventoryPath = Join-Path $evidenceRoot 'verify_packaged_assets.py'
        Set-Content -Path $assetInventoryPath -Value $assetInventoryScript -Encoding utf8
        Invoke-ReviewPython -Arguments @($assetInventoryPath, $packageRoot)
        $exeHash = (Get-FileHash $exePath -Algorithm SHA256).Hash.ToLowerInvariant()
        Set-Content (Join-Path $packageRoot 'SHA256SUMS.txt') "$exeHash  KyungheeTimerAIReview.exe" -Encoding utf8
        Write-Host "Review package prepared from commit $commit. No API key is bundled."
    }
}
finally { Pop-Location }

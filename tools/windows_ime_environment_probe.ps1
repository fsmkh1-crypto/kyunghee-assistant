# Read-only prerequisites for a real Microsoft Korean IME experiment.
# Does not install languages, change profiles, inject input, import the app,
# read credentials, or contact the assistant API. Run in the same job/session
# as the intended GUI experiment. Success here does NOT prove IME composition.
# Authored on Linux; native execution is required to validate the report.
param([string]$OutputPath = (Join-Path $PSScriptRoot 'windows-ime-runner-preflight.json'))

$ErrorActionPreference = 'Stop'
$report = [ordered]@{
    captured_at = [DateTimeOffset]::UtcNow.ToString('o')
    image_os = $env:ImageOS
    image_version = $env:ImageVersion
    runner_os = $env:RUNNER_OS
    runner_arch = $env:RUNNER_ARCH
    powershell = $PSVersionTable.PSVersion.ToString()
    user_interactive = [Environment]::UserInteractive
    process_session_id = (Get-Process -Id $PID).SessionId
    errors = [System.Collections.Generic.List[string]]::new()
}

try {
    $report.os = Get-CimInstance Win32_OperatingSystem | Select-Object Caption, Version, BuildNumber, OSArchitecture
    $report.languages = @(Get-WinUserLanguageList | Select-Object LanguageTag, InputMethodTips)
    $report.input_override = Get-WinDefaultInputMethodOverride
    $report.korean_capabilities = @(Get-WindowsCapability -Online | Where-Object { $_.Name -match 'ko-KR' } | Select-Object Name, State)
} catch {
    $report.errors.Add('Language/OS inspection: ' + $_.Exception.Message)
}
$report.languagepackmanagement_available = [bool](Get-Command Install-Language -ErrorAction SilentlyContinue)
$report.korean_tip_registered = Test-Path 'HKLM:\SOFTWARE\Microsoft\CTF\TIP\{A028AE76-01B1-46C2-99C4-ACD9858AE02F}'
$report.korean_layout_registry = @(Get-ChildItem 'HKLM:\SYSTEM\CurrentControlSet\Control\Keyboard Layouts' |
    Where-Object { $_.PSChildName -match '0412$' } | ForEach-Object { Get-ItemProperty $_.PSPath } |
    Select-Object PSChildName, 'Layout Text', 'Layout File', 'Ime File')
try {
    $report.korean_packages = @(Get-WindowsPackage -Online | Where-Object { $_.PackageName -match 'ko-KR' } |
        Select-Object PackageName, PackageState, InstallTime)
} catch {
    $report.errors.Add('Package inspection: ' + $_.Exception.Message)
}
$versionFiles = @('System32\imm32.dll', 'System32\msctf.dll', 'System32\ctfmon.exe') |
    ForEach-Object { Get-Item (Join-Path $env:WINDIR $_) -ErrorAction SilentlyContinue }
foreach ($imeDirectory in @('System32\InputMethod\KOR', 'System32\IME\IMEKR')) {
    $versionFiles += @(Get-ChildItem (Join-Path $env:WINDIR $imeDirectory) -File -Recurse -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -in '.dll', '.exe' })
}
$report.ime_file_versions = @($versionFiles | ForEach-Object {
    [ordered]@{ name = $_.FullName; file_version = $_.VersionInfo.FileVersion; product_version = $_.VersionInfo.ProductVersion }
})
$report.session_processes = @(Get-Process -Name explorer,ctfmon,TextInputHost,Runner.Listener,Runner.Worker -ErrorAction SilentlyContinue |
    Select-Object ProcessName, Id, SessionId)

try {
    Add-Type -TypeDefinition @'
using System;
using System.Text;
using System.Runtime.InteropServices;

public static class ImeRunnerDesktopProbe {
    [DllImport("kernel32.dll")] public static extern uint GetCurrentThreadId();
    [DllImport("user32.dll")] public static extern IntPtr GetProcessWindowStation();
    [DllImport("user32.dll")] public static extern IntPtr GetThreadDesktop(uint threadId);
    [DllImport("user32.dll", SetLastError=true)] public static extern IntPtr OpenInputDesktop(uint flags, bool inherit, uint access);
    [DllImport("user32.dll")] public static extern bool CloseDesktop(IntPtr desktop);
    [DllImport("user32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern bool GetUserObjectInformationW(IntPtr handle, int index, StringBuilder buffer, uint length, out uint needed);
    [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow();
    [DllImport("user32.dll")] public static extern uint GetWindowThreadProcessId(IntPtr hwnd, out uint pid);
    [DllImport("user32.dll")] public static extern IntPtr GetKeyboardLayout(uint threadId);
    [DllImport("user32.dll")] static extern int GetKeyboardLayoutList(int count, [Out] IntPtr[] layouts);
    [DllImport("user32.dll", CharSet=CharSet.Unicode)] static extern int GetClassNameW(IntPtr hwnd, StringBuilder buffer, int length);
    public static string ObjectName(IntPtr handle) {
        if (handle == IntPtr.Zero) return null;
        var buffer = new StringBuilder(256);
        uint needed;
        return GetUserObjectInformationW(handle, 2, buffer, 512, out needed) ? buffer.ToString() : null;
    }
    public static string ClassName(IntPtr hwnd) {
        var buffer = new StringBuilder(256);
        return GetClassNameW(hwnd, buffer, buffer.Capacity) > 0 ? buffer.ToString() : null;
    }
    public static string[] Layouts() {
        int count = GetKeyboardLayoutList(0, null);
        var layouts = new IntPtr[count];
        count = GetKeyboardLayoutList(count, layouts);
        var result = new string[count];
        for (int index = 0; index < count; index++) result[index] = "0x" + layouts[index].ToInt64().ToString("X");
        return result;
    }
}
'@
    $threadId = [ImeRunnerDesktopProbe]::GetCurrentThreadId()
    $inputDesktop = [ImeRunnerDesktopProbe]::OpenInputDesktop(0, $false, 1) # DESKTOP_READOBJECTS
    $inputError = if ($inputDesktop -eq [IntPtr]::Zero) { [Runtime.InteropServices.Marshal]::GetLastWin32Error() } else { 0 }
    try {
        $foreground = [ImeRunnerDesktopProbe]::GetForegroundWindow()
        $foregroundPid = [uint32]0
        $foregroundThread = [ImeRunnerDesktopProbe]::GetWindowThreadProcessId($foreground, [ref]$foregroundPid)
        $report.desktop = [ordered]@{
            window_station = [ImeRunnerDesktopProbe]::ObjectName([ImeRunnerDesktopProbe]::GetProcessWindowStation())
            thread_desktop = [ImeRunnerDesktopProbe]::ObjectName([ImeRunnerDesktopProbe]::GetThreadDesktop($threadId))
            input_desktop = [ImeRunnerDesktopProbe]::ObjectName($inputDesktop)
            input_desktop_open_error = $inputError
            foreground_hwnd = '0x' + $foreground.ToInt64().ToString('X')
            foreground_class = [ImeRunnerDesktopProbe]::ClassName($foreground)
            foreground_process_id = $foregroundPid
            foreground_thread_id = $foregroundThread
            foreground_hkl = '0x' + [ImeRunnerDesktopProbe]::GetKeyboardLayout($foregroundThread).ToInt64().ToString('X')
            loaded_hkls = [ImeRunnerDesktopProbe]::Layouts()
        }
    } finally {
        if ($inputDesktop -ne [IntPtr]::Zero) { [void][ImeRunnerDesktopProbe]::CloseDesktop($inputDesktop) }
    }
} catch {
    $report.errors.Add('Desktop inspection: ' + $_.Exception.Message)
}

$report | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $OutputPath -Encoding utf8
Write-Output $OutputPath

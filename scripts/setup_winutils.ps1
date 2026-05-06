# =========================================================================
# setup_winutils.ps1 -- install Hadoop 3.4 winutils for Spark 4 on Windows.
#
# Spark on Windows needs winutils.exe + hadoop.dll for Hadoop's local
# FileSystem (used during dependency / glob path resolution). Without
# them, Spark crashes during SparkSubmit init.
#
# This script:
#   1. Downloads winutils.exe + hadoop.dll for Hadoop 3.4.0 from a known
#      community mirror (github.com/cdarlint/winutils).
#   2. Places them under  C:\hadoop\bin\
#   3. Sets HADOOP_HOME (user scope) + adds it to PATH.
#
# Robust against flaky GitHub connections: forces TLS 1.2/1.3, tries
# multiple mirror URLs, retries each up to 3 times with backoff.
#
# Re-running the script is safe -- it skips downloads if the files exist.
#
# Run from PowerShell as a regular user (no admin needed):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_winutils.ps1
# =========================================================================

$ErrorActionPreference = "Stop"

$HadoopVersion = "3.3.6"  # latest available in cdarlint/winutils; ABI-compatible with Spark 4 / Hadoop 3.4 client
$InstallRoot   = "C:\hadoop"
$BinDir        = Join-Path $InstallRoot "bin"

# Force a modern TLS handshake. Old PowerShell defaults to TLS 1.0/1.1
# which GitHub's edge often rejects with "connection closed unexpectedly".
try {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12 -bor [Net.SecurityProtocolType]::Tls13
} catch {
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
}

# Mirror order: raw.githubusercontent goes direct (skips redirect);
# github.com/.../raw/... is a fallback in case raw.* is blocked.
$Mirrors = @(
    "https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-$HadoopVersion/bin",
    "https://github.com/cdarlint/winutils/raw/master/hadoop-$HadoopVersion/bin"
)

Write-Host "==> Installing Hadoop $HadoopVersion winutils to $InstallRoot"

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Write-Host "    created $BinDir"
}

function Try-Download($url, $dst) {
    $params = @{
        Uri                = $url
        OutFile            = $dst
        UseBasicParsing    = $true
        TimeoutSec         = 60
        MaximumRedirection = 5
    }
    Invoke-WebRequest @params
}

function Download-IfMissing($name) {
    $dst = Join-Path $BinDir $name

    if ((Test-Path $dst) -and ((Get-Item $dst).Length -gt 1024)) {
        Write-Host "    [skip]    $name already present"
        return $true
    }

    foreach ($mirror in $Mirrors) {
        $url = "$mirror/$name"
        for ($attempt = 1; $attempt -le 3; $attempt++) {
            try {
                Write-Host "    [download] $name (mirror $($Mirrors.IndexOf($mirror)+1)/$($Mirrors.Count) attempt $attempt)"
                Try-Download $url $dst
                if ((Test-Path $dst) -and ((Get-Item $dst).Length -gt 1024)) {
                    return $true
                }
            } catch {
                Write-Host ("       failed: " + $_.Exception.Message) -ForegroundColor Yellow
                if (Test-Path $dst) { Remove-Item $dst -Force -ErrorAction SilentlyContinue }
                Start-Sleep -Seconds (2 * $attempt)
            }
        }
    }
    return $false
}

$ok1 = Download-IfMissing "winutils.exe"
$ok2 = Download-IfMissing "hadoop.dll"

if (-not ($ok1 -and $ok2)) {
    Write-Host ""
    Write-Host "ERROR: automatic download failed for one or more files." -ForegroundColor Red
    Write-Host ""
    Write-Host "Manual fallback (paste these URLs into a browser):"
    Write-Host "  https://github.com/cdarlint/winutils/blob/master/hadoop-$HadoopVersion/bin/winutils.exe"
    Write-Host "  https://github.com/cdarlint/winutils/blob/master/hadoop-$HadoopVersion/bin/hadoop.dll"
    Write-Host "Click 'Download raw file', then save BOTH into:"
    Write-Host "  $BinDir"
    Write-Host ""
    Write-Host "After saving, re-run this script -- it will skip the download and"
    Write-Host "just configure HADOOP_HOME and PATH for you."
    exit 1
}

# Set HADOOP_HOME at user scope (no admin; persists across sessions)
$current = [Environment]::GetEnvironmentVariable("HADOOP_HOME", "User")
if ($current -ne $InstallRoot) {
    [Environment]::SetEnvironmentVariable("HADOOP_HOME", $InstallRoot, "User")
    Write-Host "==> HADOOP_HOME set to $InstallRoot (user scope)"
}

# Ensure %HADOOP_HOME%\bin is on the user PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$sep = ";"
$alreadyOnPath = $false
if ($userPath) {
    foreach ($p in $userPath.Split($sep)) {
        if ($p -eq $BinDir) { $alreadyOnPath = $true; break }
    }
}
if (-not $alreadyOnPath) {
    $newPath = if ($userPath) { "$userPath$sep$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "==> $BinDir added to user PATH"
}

# Also export to the current process so the user can verify immediately
$env:HADOOP_HOME = $InstallRoot
$env:Path = "$BinDir$sep$env:Path"

Write-Host ""
Write-Host "Done. Verify:"
Write-Host ("  $BinDir\winutils.exe  ({0} KB)" -f [Math]::Round((Get-Item "$BinDir\winutils.exe").Length / 1KB, 1))
Write-Host ("  $BinDir\hadoop.dll    ({0} KB)" -f [Math]::Round((Get-Item "$BinDir\hadoop.dll").Length / 1KB, 1))
Write-Host ""
Write-Host "IMPORTANT: open a NEW PowerShell window so the persistent"
Write-Host "HADOOP_HOME / PATH changes take effect, then retry the Spark job."

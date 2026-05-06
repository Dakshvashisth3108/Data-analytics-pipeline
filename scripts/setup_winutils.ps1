# ─────────────────────────────────────────────────────────────────────────
# setup_winutils.ps1 — install Hadoop 3.4 winutils for Spark 4 on Windows.
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
# Re-running the script is safe — it skips downloads if the files exist.
#
# Run from PowerShell as a regular user (no admin needed):
#   powershell -ExecutionPolicy Bypass -File scripts\setup_winutils.ps1
# ─────────────────────────────────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$HadoopVersion = "3.4.0"
$InstallRoot   = "C:\hadoop"
$BinDir        = Join-Path $InstallRoot "bin"
$BaseUrl       = "https://github.com/cdarlint/winutils/raw/master/hadoop-$HadoopVersion/bin"

Write-Host "==> Installing Hadoop $HadoopVersion winutils to $InstallRoot"

if (-not (Test-Path $BinDir)) {
    New-Item -ItemType Directory -Path $BinDir -Force | Out-Null
    Write-Host "    created $BinDir"
}

function Download-IfMissing($name) {
    $dst = Join-Path $BinDir $name
    if (Test-Path $dst) {
        Write-Host "    [skip]    $name already present"
        return
    }
    $src = "$BaseUrl/$name"
    Write-Host "    [download] $name"
    Invoke-WebRequest -UseBasicParsing -Uri $src -OutFile $dst
}

Download-IfMissing "winutils.exe"
Download-IfMissing "hadoop.dll"

# Set HADOOP_HOME at user scope (no admin needed; persists across sessions)
$current = [Environment]::GetEnvironmentVariable("HADOOP_HOME", "User")
if ($current -ne $InstallRoot) {
    [Environment]::SetEnvironmentVariable("HADOOP_HOME", $InstallRoot, "User")
    Write-Host "==> HADOOP_HOME set to $InstallRoot (user scope)"
}

# Ensure %HADOOP_HOME%\bin is on the user PATH
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if (-not ($userPath -split ';' | Where-Object { $_ -eq $BinDir })) {
    $newPath = if ($userPath) { "$userPath;$BinDir" } else { $BinDir }
    [Environment]::SetEnvironmentVariable("Path", $newPath, "User")
    Write-Host "==> $BinDir added to user PATH"
}

# Also export to the current process so the user can verify immediately
$env:HADOOP_HOME = $InstallRoot
$env:Path = "$BinDir;$env:Path"

Write-Host ""
Write-Host "Done. Verify:"
Write-Host "  $BinDir\winutils.exe  ($([Math]::Round((Get-Item "$BinDir\winutils.exe").Length / 1KB, 1)) KB)"
Write-Host "  $BinDir\hadoop.dll    ($([Math]::Round((Get-Item "$BinDir\hadoop.dll").Length / 1KB, 1)) KB)"
Write-Host ""
Write-Host "IMPORTANT: open a NEW PowerShell window so the persistent"
Write-Host "HADOOP_HOME / PATH changes take effect, then retry the Spark job."

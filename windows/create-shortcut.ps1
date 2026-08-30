# Legt die Desktop-Verknüpfung für KorbKlar an.
param(
    [Parameter(Mandatory = $true)][string] $Root
)

$ErrorActionPreference = 'Stop'

$target = Join-Path $Root 'windows\start.cmd'
if (-not (Test-Path -LiteralPath $target)) {
    throw "start.cmd wurde nicht gefunden: $target"
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'KorbKlar.lnk'))
$link.TargetPath = $target
$link.WorkingDirectory = $Root
$link.Description = 'KorbKlar starten'

$icon = Join-Path $Root 'windows\korbklar.ico'
if (Test-Path -LiteralPath $icon) {
    $link.IconLocation = "$icon,0"
}

$link.Save()
Write-Output "Verknüpfung angelegt: $($link.FullName)"

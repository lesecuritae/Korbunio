# Legt die Desktop-Verknüpfung für Korbunio an.
param(
    [Parameter(Mandatory = $true)][string] $Root
)

$ErrorActionPreference = 'Stop'

$target = Join-Path $Root 'windows\start.cmd'
if (-not (Test-Path -LiteralPath $target)) {
    throw "start.cmd wurde nicht gefunden: $target"
}

$shell = New-Object -ComObject WScript.Shell
$link = $shell.CreateShortcut((Join-Path ([Environment]::GetFolderPath('Desktop')) 'Korbunio.lnk'))
$link.TargetPath = $target
$link.WorkingDirectory = $Root
$link.Description = 'Korbunio starten'

$icon = Join-Path $Root 'windows\korbunio.ico'
if (Test-Path -LiteralPath $icon) {
    $link.IconLocation = "$icon,0"
}

$link.Save()
Write-Output "Verknüpfung angelegt: $($link.FullName)"

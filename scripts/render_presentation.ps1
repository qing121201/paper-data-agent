param(
    [Parameter(Mandatory = $true)][string]$PptxPath,
    [Parameter(Mandatory = $true)][string]$OutputDir
)

$ErrorActionPreference = 'Stop'
$pptx = (Resolve-Path -LiteralPath $PptxPath).Path
$target = [System.IO.Path]::GetFullPath($OutputDir)
[System.IO.Directory]::CreateDirectory($target) | Out-Null
$powerPoint = $null
$presentation = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Open($pptx, $true, $true, $false)
    $presentation.Export($target, 'PNG', 1600, 900)
}
finally {
    if ($presentation -ne $null) { $presentation.Close() }
    if ($powerPoint -ne $null -and $powerPoint.Presentations.Count -eq 0) { $powerPoint.Quit() }
    if ($presentation -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($powerPoint -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

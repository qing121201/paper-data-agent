param(
    [Parameter(Mandatory = $true)][string]$SpecPath,
    [Parameter(Mandatory = $true)][string]$OutputPath
)

$ErrorActionPreference = 'Stop'
$specFile = (Resolve-Path -LiteralPath $SpecPath).Path
$outputFull = [System.IO.Path]::GetFullPath($OutputPath)
if ([System.IO.Path]::GetExtension($outputFull).ToLowerInvariant() -ne '.pptx') {
    throw 'OutputPath must end with .pptx'
}
$spec = Get-Content -LiteralPath $specFile -Raw -Encoding UTF8 | ConvertFrom-Json

function Office-Rgb([int]$r, [int]$g, [int]$b) {
    return $r + ($g * 256) + ($b * 65536)
}

function Add-Text($slide, [string]$text, [double]$left, [double]$top, [double]$width, [double]$height, [double]$size, [bool]$bold, [int]$color) {
    $shape = $slide.Shapes.AddTextbox(1, $left, $top, $width, $height)
    $shape.TextFrame.MarginLeft = 0
    $shape.TextFrame.MarginRight = 0
    $shape.TextFrame.MarginTop = 0
    $shape.TextFrame.MarginBottom = 0
    $shape.TextFrame.WordWrap = -1
    $shape.TextFrame.TextRange.Text = $text
    $shape.TextFrame.TextRange.Font.Name = 'Microsoft YaHei'
    $shape.TextFrame.TextRange.Font.NameFarEast = 'Microsoft YaHei'
    $shape.TextFrame.TextRange.Font.Size = $size
    $shape.TextFrame.TextRange.Font.Bold = $(if ($bold) { -1 } else { 0 })
    $shape.TextFrame.TextRange.Font.Color.RGB = $color
    return $shape
}

function Add-PaperImage($slide, $asset, [double]$left, [double]$top, [double]$width, [double]$height) {
    $picture = $slide.Shapes.AddPicture([string]$asset.path, 0, -1, 0, 0, -1, -1)
    $ratio = [Math]::Min($width / $picture.Width, ($height - 42) / $picture.Height)
    $picture.LockAspectRatio = -1
    $picture.Width = $picture.Width * $ratio
    $picture.Left = $left + ($width - $picture.Width) / 2
    $picture.Top = $top + ($height - 42 - $picture.Height) / 2
    $picture.AlternativeText = [string]$asset.source
    $caption = ([string]$asset.caption + "`r`n" + [string]$asset.source).Trim()
    [void](Add-Text $slide $caption $left ($top + $height - 38) $width 38 9 $false (Office-Rgb 90 105 122))
}

$powerPoint = $null
$presentation = $null
try {
    $powerPoint = New-Object -ComObject PowerPoint.Application
    $presentation = $powerPoint.Presentations.Add()
    $presentation.PageSetup.SlideWidth = 960
    $presentation.PageSetup.SlideHeight = 540

    $cover = $presentation.Slides.Add(1, 12)
    $cover.FollowMasterBackground = 0
    $cover.Background.Fill.ForeColor.RGB = Office-Rgb 247 249 252
    $bar = $cover.Shapes.AddShape(1, 0, 0, 22, 540)
    $bar.Fill.ForeColor.RGB = Office-Rgb 36 91 138
    $bar.Line.Visible = 0
    [void](Add-Text $cover ([string]$spec.title) 72 145 810 125 30 $true (Office-Rgb 25 42 59))
    [void](Add-Text $cover ([string]$spec.subtitle) 72 292 760 50 16 $false (Office-Rgb 90 105 122))

    $index = 2
    foreach ($item in $spec.slides) {
        $slide = $presentation.Slides.Add($index, 12)
        $slide.FollowMasterBackground = 0
        $slide.Background.Fill.ForeColor.RGB = Office-Rgb 252 252 250
        $line = $slide.Shapes.AddShape(1, 0, 0, 960, 9)
        $line.Fill.ForeColor.RGB = Office-Rgb 36 91 138
        $line.Line.Visible = 0
        [void](Add-Text $slide ([string]$item.title) 54 38 850 58 24 $true (Office-Rgb 25 42 59))
        $body = @()
        foreach ($bullet in $item.bullets) {
            if (-not [string]::IsNullOrWhiteSpace([string]$bullet)) {
                $body += ('• ' + [string]$bullet)
            }
        }
        $images = @()
        if ($null -ne $item.images) { $images = @($item.images) }
        $bodyText = $body -join "`r`n`r`n"
        if ($images.Count -gt 0 -and $item.layout -ne 'text') {
            switch ([string]$item.layout) {
                'image_left' {
                    Add-PaperImage $slide $images[0] 45 108 500 355
                    [void](Add-Text $slide $bodyText 565 125 345 330 17 $false (Office-Rgb 45 54 64))
                }
                'image_top' {
                    Add-PaperImage $slide $images[0] 60 105 840 265
                    [void](Add-Text $slide $bodyText 70 378 820 96 14 $false (Office-Rgb 45 54 64))
                }
                'image_full' {
                    Add-PaperImage $slide $images[0] 50 105 860 300
                    [void](Add-Text $slide $bodyText 65 413 830 62 13 $false (Office-Rgb 45 54 64))
                }
                'two_images' {
                    Add-PaperImage $slide $images[0] 45 108 420 270
                    if ($images.Count -gt 1) { Add-PaperImage $slide $images[1] 495 108 420 270 }
                    [void](Add-Text $slide $bodyText 65 389 830 86 14 $false (Office-Rgb 45 54 64))
                }
                default {
                    [void](Add-Text $slide $bodyText 55 125 345 330 17 $false (Office-Rgb 45 54 64))
                    Add-PaperImage $slide $images[0] 420 108 495 355
                }
            }
        } else {
            [void](Add-Text $slide $bodyText 70 116 820 330 17 $false (Office-Rgb 45 54 64))
        }
        if (-not [string]::IsNullOrWhiteSpace([string]$item.source)) {
            [void](Add-Text $slide ('来源：' + [string]$item.source) 70 485 820 25 9 $false (Office-Rgb 105 112 121))
        }
        $index += 1
    }

    $directory = [System.IO.Path]::GetDirectoryName($outputFull)
    [System.IO.Directory]::CreateDirectory($directory) | Out-Null
    $presentation.SaveAs($outputFull, 24)
    Write-Output $outputFull
}
finally {
    if ($presentation -ne $null) { $presentation.Close() }
    if ($powerPoint -ne $null -and $powerPoint.Presentations.Count -eq 0) { $powerPoint.Quit() }
    if ($presentation -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($presentation) }
    if ($powerPoint -ne $null) { [void][Runtime.InteropServices.Marshal]::ReleaseComObject($powerPoint) }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}

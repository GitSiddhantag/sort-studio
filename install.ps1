# Sort Studio installer for Windows: downloads the app to %USERPROFILE%\sort-studio and opens it on your Downloads folder.
#   irm https://raw.githubusercontent.com/GitSiddhantag/sort-studio/main/install.ps1 | iex
$ErrorActionPreference = "Stop"
$Repo = "GitSiddhantag/sort-studio"
$Dir = Join-Path $HOME "sort-studio"

$Py = if (Get-Command py -ErrorAction SilentlyContinue) { "py" } elseif (Get-Command python -ErrorAction SilentlyContinue) { "python" } else { $null }
if (-not $Py) {
    Write-Host "Sort Studio needs Python 3: install it from https://www.python.org/downloads/ (tick 'Add python.exe to PATH'), then run this again."
    return
}

Write-Host "Downloading Sort Studio..."
$Zip = Join-Path $env:TEMP "sort-studio.zip"
$Tmp = Join-Path $env:TEMP "sort-studio-unzip"
Invoke-WebRequest "https://github.com/$Repo/archive/refs/heads/main.zip" -OutFile $Zip -UseBasicParsing
Remove-Item $Tmp -Recurse -Force -ErrorAction SilentlyContinue
Expand-Archive $Zip $Tmp
New-Item -ItemType Directory -Force $Dir | Out-Null
Copy-Item (Join-Path (Get-ChildItem $Tmp)[0].FullName "*") $Dir -Recurse -Force
Remove-Item $Zip, $Tmp -Recurse -Force

# photo thumbnails on Windows come from Pillow
& $Py -m pip install --user --quiet --disable-pip-version-check Pillow 2>$null

Write-Host "Installed in $Dir"
Write-Host "Next time, just run:  $Py $Dir\sort.py"
Write-Host "Opening... (press Ctrl+C here to stop)"
Set-Location $Dir
& $Py sort.py @args

<#
.SYNOPSIS
  Download and verify the pinned toolchain into this repo's tools/ (gitignored).
.DESCRIPTION
  Blender 3.6.23 portable, SCS Blender Tools v2.4.1 (for the future export pipeline) and the render-only
  HDRI (Poly Haven "Qwantani Late Afternoon" 4k, CC0; Poly Haven publishes an md5,
  9d3836829ff3e9a5bb52a99da302f37b, which matched our download; the sha256 below was recorded by us on
  2026-10-14). Downloads happen into tools/_dl and are sha256-checked before extraction/copy.
  The reference models in tools/reference-hd-chassis/ are downloaded by hand (README 'Tools').
#>
param([switch]$Force)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
$Tools = Join-Path $Root 'tools'
$Dl = Join-Path $Tools '_dl'
New-Item -ItemType Directory -Force -Path $Dl | Out-Null

$items = @(
    @{ Name = 'Blender 3.6.23'; File = 'blender-3.6.23-windows-x64.zip'
       Url = 'https://mirrors.ocf.berkeley.edu/blender/release/Blender3.6/blender-3.6.23-windows-x64.zip'
       Sha = 'e3296eba7eab32c2e5182459ec7614af32224eee2bd32c9d0a08ffd751c54f3b'
       Check = 'blender-3.6.23-windows-x64/blender.exe'; Extract = $Tools },
    @{ Name = 'SCS Blender Tools v2.4.1'; File = 'SCS_Blender_Tools.zip'
       Url = 'https://github.com/SCSSoftware/BlenderTools/releases/download/v2.4.1/scs_blender_tools_addon.zip'
       Sha = 'c38df76fbdb4f703fdd72493eda30bdac32b56e50052ec8b3c5f5767ee226649'
       Check = 'SCS_Blender_Tools.zip'; Extract = $null },
    @{ Name = 'HDRI Qwantani Late Afternoon 4k (Poly Haven, CC0)'; File = 'qwantani_late_afternoon_4k.hdr'
       Url = 'https://dl.polyhaven.org/file/ph-assets/HDRIs/hdr/4k/qwantani_late_afternoon_4k.hdr'
       Sha = '756d132155561f224d4b3ed54cb7142c01129190d50a2e6be75f9baa9ff2c429'
       Check = 'hdri/qwantani_late_afternoon_4k.hdr'; Extract = $null; Dest = 'hdri' }
)

foreach ($i in $items) {
    $target = Join-Path $Tools $i.Check
    if ((Test-Path $target) -and -not $Force) { Write-Host "[skip] $($i.Name) already present"; continue }
    $zip = Join-Path $Dl $i.File
    if (-not (Test-Path $zip) -or $Force) {
        Write-Host "[get ] $($i.Name)"
        Invoke-WebRequest -Uri $i.Url -OutFile $zip -UseBasicParsing
    }
    $actual = (Get-FileHash -Algorithm SHA256 $zip).Hash.ToLower()
    if ($actual -ne $i.Sha) { Remove-Item $zip; throw "SHA256 mismatch for $($i.File): got $actual expected $($i.Sha)" }
    Write-Host "[ok  ] sha256 verified $($i.File)"
    if ($i.Extract) {
        New-Item -ItemType Directory -Force -Path $i.Extract | Out-Null
        Expand-Archive -Path $zip -DestinationPath $i.Extract -Force
    } else {
        $destDir = if ($i.Dest) { Join-Path $Tools $i.Dest } else { $Tools }
        New-Item -ItemType Directory -Force -Path $destDir | Out-Null
        Copy-Item $zip (Join-Path $destDir $i.File) -Force
    }
    if (-not (Test-Path $target)) { throw "expected file missing after extract: $target" }
}
Write-Host "Toolchain ready in $Tools. Next: add the reference models (README 'Tools')."

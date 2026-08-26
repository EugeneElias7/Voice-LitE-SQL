<#
.SYNOPSIS
    Voice-LitE-SQL -- Automated Environment Setup
.DESCRIPTION
    Verifies toolchain, creates AI_Models directory + env var, scaffolds
    dataset folders, and installs all Python dependencies.
.NOTES
    Must be run as Administrator to set the machine-level OLLAMA_MODELS variable.
    Author : Eugene Elias
    Project: Voice-LitE-SQL
#>

$ErrorActionPreference = "Stop"
$Host.UI.RawUI.BackgroundColor = "Black"
$Host.UI.RawUI.ForegroundColor = "Gray"

# -- helpers ----------------------------------------------------------------
function Write-Color($Text, $Color) {
    Write-Host $Text -ForegroundColor $Color
}
function Write-Box($Title, $Lines) {
    $width  = ($Lines | Measure-Object -Maximum Length).Maximum + 4
    $border = "-" * $width
    Write-Host "+$border+" -ForegroundColor Cyan
    Write-Host "|  $Title".PadRight($width + 2) + "|" -ForegroundColor Cyan
    Write-Host "|$border|" -ForegroundColor Cyan
    foreach ($line in $Lines) {
        Write-Host "|  $line".PadRight($width + 2) + "|" -ForegroundColor Yellow
    }
    Write-Host "+$border+" -ForegroundColor Cyan
}

# Detect project root (the directory that contains backend/)
$ScriptDir = Split-Path -Parent $PSCommandPath
$ProjectRoot = Split-Path -Parent $ScriptDir
$BackendDatasets = Join-Path (Join-Path $ProjectRoot "backend") "datasets"

Write-Host "`n"
Write-Color "+-------------------------------------------------+" Cyan
Write-Color "|       Voice-LitE-SQL -- Environment Setup        |" Cyan
Write-Color "+-------------------------------------------------+" Cyan
Write-Host "Project root : $ProjectRoot`n" -ForegroundColor Gray

# ===========================================================================
# 1.  VERIFICATION CHECKS
# ===========================================================================
Write-Color "--- [1/5] Verifying toolchain ---" Cyan
Write-Host ""

# Node.js
try {
    $nodeVer = (node -v) 2>&1
    Write-Color "  [+] Node.js   $nodeVer" Green
} catch {
    Write-Color "  [X] Node.js   NOT FOUND -- install from https://nodejs.org" Red
}

# Python
try {
    $pyVer = (python --version) 2>&1
    Write-Color "  [+] Python   $pyVer" Green
} catch {
    try {
        $pyVer = (python3 --version) 2>&1
        Write-Color "  [+] Python   $pyVer" Green
    } catch {
        Write-Color "  [X] Python   NOT FOUND -- install from https://python.org" Red
    }
}

# Ollama
try {
    $ollVer = (ollama --version) 2>&1
    Write-Color "  [+] Ollama   $ollVer" Green
} catch {
    Write-Color "  [X] Ollama   NOT FOUND -- install from https://ollama.com" Red
}

# Admin check
$IsAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
if (-not $IsAdmin) {
    Write-Color "`n  [!] WARNING: Not running as Administrator." Yellow
    Write-Color "       The OLLAMA_MODELS machine-level env var" Yellow
    Write-Color "       will NOT be set. Re-run as Administrator" Yellow
    Write-Color "       or set it manually: System Properties > Advanced." Yellow
}

Write-Host ""

# ===========================================================================
# 2.  DEDICATED DIRECTORY FOR AI MODELS
# ===========================================================================
Write-Color "--- [2/5] AI Models directory & environment variable ---" Cyan
Write-Host ""

$AiModelsPath = "C:\AI_Models"

if (-not (Test-Path $AiModelsPath)) {
    $null = New-Item -ItemType Directory -Path $AiModelsPath -Force
    Write-Color "  [+] Created directory : $AiModelsPath" Green
} else {
    Write-Color "  [+] Directory exists  : $AiModelsPath" Green
}

if ($IsAdmin) {
    try {
        [Environment]::SetEnvironmentVariable("OLLAMA_MODELS", $AiModelsPath, "Machine")
        $env:OLLAMA_MODELS = $AiModelsPath
        Write-Color "  [+] Environment variable set:" Green
        Write-Color "       OLLAMA_MODELS = $AiModelsPath" White
    } catch {
        Write-Color "  [X] Failed to set OLLAMA_MODELS : $_" Red
    }
} else {
    Write-Color "  [-] Skipped OLLAMA_MODELS (not Admin)." Yellow
    Write-Color "       Set manually:" Yellow
    Write-Color "       [Environment]::SetEnvironmentVariable('OLLAMA_MODELS','$AiModelsPath','Machine')" Gray
}

Write-Host ""

# ===========================================================================
# 3.  DATASET DIRECTORY STRUCTURE
# ===========================================================================
Write-Color "--- [3/5] Dataset directories ---" Cyan
Write-Host ""

$DatasetDirs = @(
    (Join-Path $BackendDatasets "spider"),
    (Join-Path $BackendDatasets "bird"),
    (Join-Path $BackendDatasets "spoken_spider")
)

foreach ($dir in $DatasetDirs) {
    if (-not (Test-Path $dir)) {
        $null = New-Item -ItemType Directory -Path $dir -Force
        Write-Color "  [+] Created : $dir" Green
    } else {
        Write-Color "  [+] Exists  : $dir" Green
    }
}

Write-Host ""

# ===========================================================================
# 4.  REQUIREMENTS.TXT & PYTHON DEPENDENCIES
# ===========================================================================
Write-Color "--- [4/5] Python dependencies ---" Cyan
Write-Host ""

$RequirementsPath = Join-Path $ProjectRoot "requirements.txt"
$RequiredPackages = @(
    "fastapi",
    "uvicorn",
    "requests",
    "jellyfish",
    "rapidfuzz",
    "chromadb",
    "sentence-transformers",
    "openai-whisper",
    "SpeechRecognition",
    "pyaudio",
    "numpy",
    "pandas",
    "python-dotenv",
    "pytest"
)

$RequiredPackages | Set-Content -Path $RequirementsPath -Encoding UTF8
Write-Color "  [+] Wrote requirements.txt with $($RequiredPackages.Count) packages" Green

try {
    Write-Color "  [~] Running pip install (this may take a while)..." Yellow
    $pipResult = & python -m pip install -r $RequirementsPath 2>&1
    if ($LASTEXITCODE -eq 0) {
        Write-Color "  [+] All Python packages installed successfully" Green
    } else {
        Write-Color "  [X] pip install exited with code $LASTEXITCODE" Red
        Write-Color "      Last lines: $($pipResult | Select-Object -Last 5)" Red
    }
} catch {
    Write-Color "  [X] pip install failed: $_" Red
}

Write-Host ""

# ===========================================================================
# 5.  VISUAL RESTART INSTRUCTIONS
# ===========================================================================
Write-Color "--- [5/5] Restart Instructions ---" Cyan
Write-Host ""

Write-Box "ACTION REQUIRED" @(
    "",
    "1. Completely EXIT Ollama from the Windows System Tray.",
    "   (Right-click the Ollama icon -> Quit)",
    "",
    "2. Restart Ollama from the Start Menu.",
    "",
    "3. Open a FRESH (new) terminal window (Admin not needed).",
    "",
    "4. Run the following command to pull the model:",
    "",
    "   ollama pull qwen2.5-coder:1.5b",
    "",
    "   The model will download to:  C:\AI_Models",
    ""
)

Write-Host "`n  Environment setup complete. Press any key to exit...`n" -ForegroundColor Gray
$null = $Host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")

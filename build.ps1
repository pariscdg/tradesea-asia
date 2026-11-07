$ErrorActionPreference = 'Stop'
python -m PyInstaller --noconfirm --distpath "$PSScriptRoot\build-output" "$PSScriptRoot\TradeSeaAsia.spec"

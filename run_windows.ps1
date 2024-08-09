Write-host "attic-windows | startup step 1"
cd C:\git\private\attic
Write-host "attic-windows | startup step 2"
C:\ProgramData\miniconda3\shell\condabin\conda-hook.ps1
Write-host "attic-windows | startup step 3"
conda activate attic
Write-host "attic-windows | startup step 4"
python run.py --config C:\git\private\attic\config\config_windows.yaml
Write-host "attic-windows | shutdown"



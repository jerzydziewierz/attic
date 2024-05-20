Write-host "attic | startup step 1"
cd C:\git\hymet\gen3_hyfabric\attic
Write-host "attic | startup step 2"
C:\ProgramData\miniconda3\shell\condabin\conda-hook.ps1
Write-host "attic | startup step 3"
conda activate hylite
Write-host "attic | startup step 4"
python run.py --config C:\git\hymet\gen3_hyfabric\attic\config\config_windows.yaml
Write-host "attic | shutdown"



#!/bin/bash
source /home/mib07150/.bashrc
source /home/mib07150/prog/miniconda3/etc/profile.d/conda.sh
conda activate /home/mib07150/git/zfs/conda-envs/hylite
# -u: unbuffered output
python -u run_hyattic.py

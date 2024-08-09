sudo apt install -y screen
wget https://repo.anaconda.com/miniconda/Miniconda3-latest-Linux-x86_64.sh
chmod +x Miniconda3-latest-Linux-x86_64.sh
./Miniconda3-latest-Linux-x86_64.sh
# need to enter new bash at this point
bash
conda create -n attic python=3.12 -y
conda activate attic
python -m pip install -U paho-mqtt
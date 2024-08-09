#!/bin/bash
echo "install_service.sh: starting..."
sudo cp attic.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable attic.service
sudo systemctl start attic.service
sudo systemctl status attic.service
sleep 3
echo "install_service.sh: showing log. ctrl-c to exit"
sudo journalctl -n 300 --no-pager -u attic.service
echo "install_service.sh: clean exit"
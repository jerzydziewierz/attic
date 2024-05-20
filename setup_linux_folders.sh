#!/bin/bash
echo "hyattic | setup.sh: starting..."
sudo mkdir -p /var/hyattic
sudo mkdir -p /var/hyattic/data
sudo chown -R $USER:$USER /var/hyattic
sudo chmod -R 755 /var/hyattic
echo "hyattic | setup.sh: finished"

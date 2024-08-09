#!/bin/bash
echo "attic | setup.sh: starting..."
sudo mkdir -p /var/attic
sudo mkdir -p /var/attic/data
sudo chown -R $USER:$USER /var/attic
sudo chmod -R 755 /var/attic
echo "attic | setup.sh: finished"

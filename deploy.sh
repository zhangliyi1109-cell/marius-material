#!/bin/bash
cd /root/marius-material
git pull origin main
systemctl restart material-inventory

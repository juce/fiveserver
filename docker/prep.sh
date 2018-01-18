#!/bin/sh -u
cp -r /opt/fiveserver/etc /opt/fiveserver/log $dir/
chown -R five:five $dir/etc/data $dir/log

#!/bin/sh -u
cp -r /opt/fiveserver/{etc,log} $dir/
chown -R five:five /$dir/etc/data /$dir/log

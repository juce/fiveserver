#!/bin/sh
cp -r /opt/fiveserver/{etc,log} /tmp/
chown -R five:five /tmp/etc/data /tmp/log

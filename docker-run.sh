#!/usr/bin/env bash
#
# Example command on how to run fiveserver/sixserver under docker
# You need to run this as root or with sudo.
#
# configuration is in /opt/fiveserver/etc
# logs go into: /opt/fiveserver/log

[ -d /opt/fiveserver/etc ] || ( mkdir -p /opt/fiveserver && cp -r ./etc /opt/fiveserver/ )
[ -d /opt/fiveserver/log ] || ( mkdir -p /opt/fiveserver/log && chown five:five /opt/fiveserver/log )
[ -d /opt/fiveserver/etc/data ] || ( mkdir /opt/fiveserver/etc/data && chown five:five /opt/fiveserver/etc/data )

tag="v0.4.11"

svc=${1:-fiveserver}
docker run -d --restart=always --name $svc \
  --net=host -e SVC=$svc \
  -v /opt/fiveserver/etc:/opt/fiveserver/etc \
  -v /opt/fiveserver/log:/opt/fiveserver/log \
  fiveserver:$tag

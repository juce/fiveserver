#!/usr/bin/env bash
#
# Example command on how to start fiveserver/sixserver under docker
# This assumes that you have local directories

svc=${1:-fiveserver}
docker run -d --restart=always --name $svc \
  --net=host -e SVC=$svc \
  -v /opt/fiveserver/conf:/opt/fiveserver/etc/conf \
  -v /opt/fiveserver/log:/opt/fiveserver/log \
  fiveserver:latest

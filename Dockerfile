FROM ubuntu:xenial
MAINTAINER Anton Jouline <juce66@gmail.com>

ENV DEBIAN_FRONTEND noninteractive

RUN groupadd -g 3066 five && useradd -r -u 3066 -g five five

RUN apt-get update && apt-get install -y \
  libmysqlclient-dev \
  python-dev \
  virtualenv \
  gcc \
  make

ENV FSROOT /opt/fiveserver
ENV FSENV /opt/fiveserver/fsenv
ENV SVC fiveserver

RUN mkdir -p $FSROOT
COPY pip.requirements Makefile $FSROOT/
RUN cd $FSROOT && make FSENV=$FSENV install

COPY etc $FSROOT/etc
COPY lib $FSROOT/lib
COPY log $FSROOT/log
COPY sql $FSROOT/sql
COPY web $FSROOT/web
COPY web6 $FSROOT/web6
COPY service.sh $FSROOT/

USER five
CMD exec $FSROOT/service.sh $SVC runexec

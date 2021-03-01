FROM ubuntu:focal
MAINTAINER Anton Jouline <juce66@gmail.com>

ENV DEBIAN_FRONTEND noninteractive

RUN groupadd -g 3066 five && useradd -r -u 3066 -g five five

RUN apt-get update && apt-get install -y \
  libmysqlclient-dev \
  python3 python3-venv python3-dev \
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
COPY tac $FSROOT/tac
COPY web $FSROOT/web
COPY web6 $FSROOT/web6
COPY docker $FSROOT/docker
COPY service.sh $FSROOT/

RUN chown -R five:five $FSROOT/log
RUN chown -R five:five $FSROOT/etc/data

USER five
WORKDIR $FSROOT
CMD exec $FSROOT/service.sh $SVC runexec

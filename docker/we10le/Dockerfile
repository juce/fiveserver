# Build from the repository root:
# docker build -f docker/we10le/Dockerfile -t we10le-server:latest .
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/opt/fiveserver/lib \
    FSROOT=/opt/fiveserver

WORKDIR /opt/fiveserver
COPY docker/we10le/requirements.txt /opt/fiveserver/docker/we10le/requirements.txt
RUN python -m pip install --no-cache-dir --only-binary=:all: \
        -r /opt/fiveserver/docker/we10le/requirements.txt \
    && groupadd --gid 3066 five \
    && useradd --uid 3066 --gid 3066 --no-create-home --shell /usr/sbin/nologin five \
    && mkdir -p /var/lib/we10le \
    && chown 3066:3066 /var/lib/we10le

COPY lib /opt/fiveserver/lib
COPY etc /opt/fiveserver/etc
COPY sql /opt/fiveserver/sql
COPY tac /opt/fiveserver/tac
COPY web6 /opt/fiveserver/web6
COPY docker/we10le/entrypoint.py /opt/fiveserver/docker/we10le/entrypoint.py

USER 3066:3066
EXPOSE 10881/tcp 20210/tcp 20211/tcp 20212/tcp 8195/tcp
VOLUME ["/var/lib/we10le"]
ENTRYPOINT ["python", "/opt/fiveserver/docker/we10le/entrypoint.py"]

FROM python:3.12-slim

RUN apt-get update \
    && apt-get install --no-install-recommends -y bash git ripgrep findutils \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 65532 sandbox \
    && useradd --uid 65532 --gid 65532 --no-create-home --shell /usr/sbin/nologin sandbox

WORKDIR /workspace
USER 65532:65532

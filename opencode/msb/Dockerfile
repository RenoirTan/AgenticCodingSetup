ARG BUN_VERSION
ARG OPENCODE_VERSION
ARG DDGS_BRANCH
ARG UV_VERSION=0.12.13

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

FROM debian:bookworm-slim

ARG BUN_VERSION
ARG OPENCODE_VERSION
ARG DDGS_BRANCH

COPY --from=uv /uv /uvx /usr/local/bin/

RUN apt-get update \
  && apt-get install -y --no-install-recommends \
  bash \
  ca-certificates \
  curl \
  git \
  passwd \
  python3 \
  unzip \
  && rm -rf /var/lib/apt/lists/*
RUN groupadd --gid 1000 agent \
  && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash agent \
  && install -d -o agent -g agent /home/agent/.bun /opt/ddgs

ENV BUN_INSTALL=/home/agent/.bun
ENV PATH=/home/agent/.bun/bin:${PATH}

WORKDIR /home/agent/project

# SHELL ["/bin/bash", "-o", "pipefail", "-c"]

USER agent

RUN curl -fsSL "https://bun.com/install" \
  | bash -s -- "bun-v${BUN_VERSION}" \
  && bun --version

RUN bun install --global --trust "opencode-ai@${OPENCODE_VERSION}"

RUN git clone --depth 1 --branch "${DDGS_BRANCH}" https://github.com/deedy5/ddgs /opt/ddgs \
  && env --chdir=/opt/ddgs uv venv \
  && env --chdir=/opt/ddgs uv sync --extra mcp

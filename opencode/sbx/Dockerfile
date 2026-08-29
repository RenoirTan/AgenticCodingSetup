ARG OPENCODE_VERSION
ARG DDGS_BRANCH

FROM docker/sandbox-templates:opencode

ARG OPENCODE_VERSION
ARG DDGS_BRANCH

USER root

RUN mkdir -p /opt/ddgs && chown agent:agent /opt/ddgs

USER agent


RUN npm install --global --no-audit --no-fund opencode-ai@${OPENCODE_VERSION}

RUN git clone --depth 1 --branch ${DDGS_BRANCH} https://github.com/deedy5/ddgs /opt/ddgs
RUN env --chdir=/opt/ddgs uv venv
RUN env --chdir=/opt/ddgs uv sync --extra mcp

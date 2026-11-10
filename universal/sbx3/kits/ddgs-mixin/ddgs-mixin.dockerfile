ARG DDGS_BRANCH

FROM --platform=$BUILDPLATFORM docker.io/sbx/shell-image:latest AS build

ARG DDGS_BRANCH

USER root

RUN mkdir -p /opt/ddgs && chown 1000:1000 /opt/ddgs

USER agent

RUN git clone --depth 1 --branch ${DDGS_BRANCH} https://github.com/deedy5/ddgs /opt/ddgs

WORKDIR /opt/ddgs

RUN uv venv \
  && uv sync --extra mcp

FROM docker.io/sbx/shell-image:latest
COPY --from=build /opt/ddgs /opt/ddgs

ARG DDGS_BRANCH
ARG UV_TAG
ARG SHELL_IMAGE_TAG

FROM --platform=$BUILDPLATFORM astral/uv:${UV_TAG} AS uv

FROM --platform=$BUILDPLATFORM docker.io/sbx/shell-image:${SHELL_IMAGE_TAG} AS build
ARG DDGS_BRANCH

USER root
RUN mkdir -p /opt/ddgs /opt/ddgs-python && chown 1000:1000 /opt/ddgs /opt/ddgs-python

USER agent
ENV UV_PYTHON_INSTALL_DIR=/opt/ddgs-python
WORKDIR /opt/ddgs-python
RUN uv python install 3.14

WORKDIR /
RUN git clone --depth 1 --branch ${DDGS_BRANCH} https://github.com/deedy5/ddgs /opt/ddgs

WORKDIR /opt/ddgs
RUN uv venv --python 3.14 --managed-python && uv sync --extra mcp

FROM docker.io/sbx/shell-image:${SHELL_IMAGE_TAG}

COPY --from=build /opt/ddgs /opt/ddgs
COPY --from=build /opt/ddgs-python /opt/ddgs-python
COPY --from=uv /uv /uvx /usr/local/bin/

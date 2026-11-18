ARG SHELL_TAG
ARG UV_TAG

FROM --platform=$BUILDPLATFORM docker.io/astral/uv:${UV_TAG} AS uv

FROM --platform=$BUILDPLATFORM docker.io/sbx/shell:${SHELL_TAG}

COPY --from=uv /uv /uvx /usr/local/bin/

USER root

RUN apt-get update -y \
  && apt-get install -y --no-install-recommends nodejs npm \
  && rm -rf /var/lib/apt/lists

USER agent

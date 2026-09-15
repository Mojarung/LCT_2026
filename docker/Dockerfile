# syntax=docker/dockerfile:1
# Образ сервиса green для МосТех.ОС и совместимых Linux x86-64.
# Сборка: docker build -f docker/Dockerfile -t green .
# ODA File Converter (freeware, проприетарный) не хранится в репозитории: при --build-arg WITH_ODA=true
# он скачивается с сайта ODA во время сборки у того, кто принимает его лицензию.

ARG UBUNTU_VERSION=26.04
ARG UV_VERSION=0.12.15
ARG PYTHON_VERSION=3.14
ARG LIBREDWG_VERSION=0.14

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# LibreDWG собирается из исходников статически: в репозиториях Ubuntu 26.04 пакета нет.
FROM ubuntu:${UBUNTU_VERSION} AS libredwg
ARG LIBREDWG_VERSION
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl pkg-config python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
RUN curl -fsSL "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" \
    | tar -xJ --strip-components=1
RUN ./configure --prefix=/opt/libredwg --disable-shared --enable-static --disable-bindings \
        --disable-dependency-tracking \
    && make -j"$(nproc)" -C src \
    && make -j"$(nproc)" -C programs \
    && install -d /opt/libredwg/bin \
    && install -s programs/dwg2dxf programs/dwgread /opt/libredwg/bin/

FROM ubuntu:${UBUNTU_VERSION} AS builder
ARG PYTHON_VERSION
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv python install "${PYTHON_VERSION}"
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project
COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable

FROM ubuntu:${UBUNTU_VERSION} AS runtime
ARG WITH_ODA=false
ARG ODA_VERSION=27.1
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini fonts-dejavu-core \
    && if [ "${WITH_ODA}" = "true" ]; then \
        apt-get install -y --no-install-recommends curl xvfb xauth \
        && curl -fsSL -o /tmp/oda.deb \
            "https://www.opendesign.com/guestfiles/get?filename=ODAFileConverter_QT6_lnxX64_8.3dll_${ODA_VERSION}.deb" \
        && apt-get install -y /tmp/oda.deb \
        && rm -f /tmp/oda.deb \
        && apt-get purge -y curl; \
    fi \
    && rm -rf /var/lib/apt/lists/*
COPY --from=libredwg /opt/libredwg/bin /usr/local/bin
COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/venv /opt/venv
COPY config /app/config
RUN useradd --system --uid 10001 --create-home green \
    && install -d -o green /data/runs
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GREEN_CONFIG_DIR=/app/config \
    GREEN_RUNS_DIR=/data/runs \
    GREEN_LOG_JSON=true
WORKDIR /app
USER green
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status != 200)"]
ENTRYPOINT ["tini", "--"]
CMD ["green", "serve", "--host", "0.0.0.0", "--port", "8000"]

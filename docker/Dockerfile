# syntax=docker/dockerfile:1
# Образ сервиса green для МосТех.ОС и совместимых Linux x86-64.
# Сборка: docker build -f docker/Dockerfile -t green .
# ODA File Converter (freeware, проприетарный) не хранится в репозитории: при --build-arg WITH_ODA=true
# он скачивается с сайта ODA во время сборки у того, кто принимает его лицензию.

ARG UBUNTU_VERSION=26.04
ARG UV_VERSION=0.12.15
ARG PYTHON_VERSION=3.14
ARG LIBREDWG_VERSION=0.14
ARG NODE_VERSION=24

FROM ghcr.io/astral-sh/uv:${UV_VERSION} AS uv

# LibreDWG собирается из исходников статически: в репозиториях Ubuntu 26.04 пакета нет.
FROM ubuntu:${UBUNTU_VERSION} AS libredwg
ARG LIBREDWG_VERSION
# Generated LibreDWG C units are large; CPU count does not reflect available RAM.
# Raise explicitly on larger build hosts: --build-arg LIBREDWG_BUILD_JOBS=4.
ARG LIBREDWG_BUILD_JOBS=1
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential ca-certificates curl pkg-config python3 xz-utils \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /src
# Архив сначала в файл: повтор после обрыва загрузки не скармливает tar половину архива.
RUN curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors -o /tmp/libredwg.tar.xz \
        "https://github.com/LibreDWG/libredwg/releases/download/${LIBREDWG_VERSION}/libredwg-${LIBREDWG_VERSION}.tar.xz" \
    && tar -xJf /tmp/libredwg.tar.xz --strip-components=1 \
    && rm /tmp/libredwg.tar.xz
RUN ./configure --prefix=/opt/libredwg --disable-shared --enable-static --disable-bindings \
        --disable-dependency-tracking \
    && make -j"${LIBREDWG_BUILD_JOBS}" -C src \
    && make -j"${LIBREDWG_BUILD_JOBS}" -C programs \
    && install -d /opt/libredwg/bin \
    && install -s programs/dwg2dxf programs/dwgread /opt/libredwg/bin/

# Веб-интерфейс (frontend/, React + Vite) собирается в своей стадии: в рабочем образе node
# нет, туда попадает только статический бандл со Swagger UI внутри (без CDN).
FROM node:${NODE_VERSION}-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=cache,target=/root/.npm npm ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM ubuntu:${UBUNTU_VERSION} AS builder
ARG PYTHON_VERSION
COPY --from=uv /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_INSTALL_DIR=/opt/python \
    UV_PYTHON_PREFERENCE=only-managed \
    UV_PROJECT_ENVIRONMENT=/opt/venv
RUN uv python install "${PYTHON_VERSION}"
# ezdxf 1.4.4 не публикует колёса с C-расширениями под Python 3.14: из PyPI ставится чистый
# Python, и векторная математика чтения, склейки и записи DXF идёт без ускорения
# (docs/notes/23-load-time.md). Собираем ezdxf из исходников (Cython из build-system пакета),
# компилятор нужен только в этой стадии.
ARG EZDXF_C_EXT=true
RUN if [ "${EZDXF_C_EXT}" = "true" ]; then \
        apt-get update && apt-get install -y --no-install-recommends build-essential \
        && rm -rf /var/lib/apt/lists/*; \
    fi
WORKDIR /app
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --locked --no-dev --no-install-project \
        $([ "${EZDXF_C_EXT}" = "true" ] && echo --no-binary-package ezdxf)
COPY pyproject.toml uv.lock README.md .python-version ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv uv sync --locked --no-dev --no-editable \
        $([ "${EZDXF_C_EXT}" = "true" ] && echo --no-binary-package ezdxf)
# Расширения в ezdxf необязательные: без компилятора сборка молча даёт чистый Python.
# Здесь молчание - ошибка сборки.
RUN if [ "${EZDXF_C_EXT}" = "true" ]; then \
        /opt/venv/bin/python -c "import ezdxf.acc as acc; assert acc.USE_C_EXT, 'ezdxf: C-расширения не собраны'"; \
    fi

FROM ubuntu:${UBUNTU_VERSION} AS runtime
ARG WITH_ODA=false
# Сайт ODA отдаёт только текущую версию, ссылки с номером версии отвечают 404 (проверено
# 01.10.2026: в пакете 27.9.0.0). Пакет не объявляет библиотеки Qt-окружения: без них
# ODAFileConverter не запускается («libOpenGL.so.0: cannot open shared object file»).
ARG ODA_URL=https://www.opendesign.com/guestfiles/get?filename=ODAFileConverter_QT6_lnxX64_11dll.deb
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates tini fonts-dejavu-core \
    && if [ "${WITH_ODA}" = "true" ]; then \
        apt-get install -y --no-install-recommends curl xvfb xauth \
            libopengl0 libegl1 libglib2.0-0t64 libxkbcommon0 libxkbcommon-x11-0 libdbus-1-3 \
            libfontconfig1 libgssapi-krb5-2 \
        && curl -fsSL --retry 5 --retry-delay 5 --retry-all-errors -o /tmp/oda.deb "${ODA_URL}" \
        && apt-get install -y /tmp/oda.deb \
        && rm -f /tmp/oda.deb \
        && apt-get purge -y curl \
        && ! ldd /usr/bin/ODAFileConverter_*/ODAFileConverter | grep "not found"; \
    fi \
    && rm -rf /var/lib/apt/lists/*
COPY --from=libredwg /opt/libredwg/bin /usr/local/bin
COPY --from=builder /opt/python /opt/python
COPY --from=builder /opt/venv /opt/venv
COPY config /app/config
# Квадраты OpenStreetMap для города вокруг съёмки без сети (tools/osm_moscow.py, data/osm/README.md).
COPY data/osm /app/data/osm
COPY --from=web /web/dist /app/web
RUN useradd --system --uid 10001 --create-home green \
    && install -d -o green /data/runs
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    GREEN_CONFIG_DIR=/app/config \
    GREEN_RUNS_DIR=/data/runs \
    GREEN_WEB_DIR=/app/web \
    GREEN_OSM_TILES_DIR=/app/data/osm/moscow \
    GREEN_LOG_JSON=true
WORKDIR /app
USER green
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=4).status != 200)"]
ENTRYPOINT ["tini", "--"]
CMD ["green", "serve", "--host", "0.0.0.0", "--port", "8000"]

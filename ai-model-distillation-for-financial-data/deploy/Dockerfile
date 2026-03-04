ARG BASE_IMAGE_URL=nvcr.io/nvidia/base/ubuntu
ARG BASE_IMAGE_TAG=jammy-20250415.1

FROM --platform=linux/amd64 ${BASE_IMAGE_URL}:${BASE_IMAGE_TAG} AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV DEBIAN_FRONTEND=noninteractive

# Install required ubuntu packages for setting up python
RUN apt update && \
    apt install -y curl software-properties-common && \
    add-apt-repository ppa:deadsnakes/ppa && \
    apt update && apt install -y python3.12 && \
    apt-get clean

# Install pip for python3.12
RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.12

RUN rm -rf /var/lib/apt/lists/*

# Uninstall build packages
RUN apt autoremove -y curl software-properties-common

# Download the sources of apt packages within the container for standard legal compliance
RUN sed -i 's/# deb-src/deb-src/g' /etc/apt/sources.list && \
    # Enable source downloads for deadsnakes PPA
    sed -i 's/# deb-src/deb-src/g' /etc/apt/sources.list.d/deadsnakes-ubuntu-ppa-jammy.list && \
    apt update && \
    apt install xz-utils -y && \
    mkdir -p /legal/source && \
    cd /legal/source && \
    # Download sources for all installed packages, including from PPAs
    apt list --installed | grep -i installed | sed 's|\(.*\)/.*|\1|' | xargs -r apt source --download-only || true && \
    rm -f xz-utils*

WORKDIR /legal/source
COPY LICENSE-3rd-party.txt /legal/

# Install uv
RUN pip install uv

# Copy dependency file
COPY uv.lock ./
COPY pyproject.toml ./

# Set default port
ENV PORT=8000

# Development target
FROM base AS dev
RUN uv sync
RUN uv pip freeze > requirements.txt
COPY src/ ./src/
COPY kdbx/ ./kdbx/
COPY config/ ./config/
CMD ["sh", "-c", "uv run uvicorn src.app:app --host 0.0.0.0 --port ${PORT}"]

# Production target -- default target
FROM base AS prod
RUN uv sync --no-dev
RUN uv pip freeze > requirements.txt
COPY src/ ./src/
COPY kdbx/ ./kdbx/
COPY config/ ./config/
CMD ["sh", "-c", "uv run uvicorn src.app:app --host 0.0.0.0 --port ${PORT}"]

# Образ сервиса с фото по кадру 3D-вида (бонус, по желанию): поверх green:latest ставятся
# загрузчик Vulkan и OpenMP для stable-diffusion.cpp и Real-ESRGAN. Сами программы и модели в
# образ не входят: каталог от tools/photos/fetch_models.py монтируется томом (compose.photos.yaml),
# драйвер NVIDIA с Vulkan прокидывает рантайм nvidia (NVIDIA_DRIVER_CAPABILITIES=all).
ARG BASE=green:latest
FROM ${BASE}
USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends libvulkan1 libgomp1 \
    && rm -rf /var/lib/apt/lists/*
USER green

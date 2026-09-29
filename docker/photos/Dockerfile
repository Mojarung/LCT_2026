# Образ сервиса с фото по кадру 3D-вида (бонус, по желанию): поверх green:latest ставятся
# загрузчик Vulkan и OpenMP для stable-diffusion.cpp и Real-ESRGAN. Сами программы и модели в
# образ не входят: каталог от tools/photos/fetch_models.py монтируется томом (compose.photos.yaml),
# драйвер NVIDIA с Vulkan прокидывает рантайм nvidia (NVIDIA_DRIVER_CAPABILITIES=all).
ARG BASE=green:latest
FROM ${BASE}
USER root
# Драйвер Vulkan от NVIDIA (libGLX_nvidia.so.0) и без экрана открывает клиентские библиотеки
# X11, XCB и GLVND. Рантайм nvidia их не прокидывает: без них загрузчик не получает
# vkCreateInstance, и stable-diffusion.cpp молча считает на процессоре (около 190 с на шаг).
RUN apt-get update \
    && apt-get install -y --no-install-recommends libvulkan1 libgomp1 \
        libx11-6 libxext6 libx11-xcb1 libxcb1 libxcb-dri3-0 libxcb-glx0 libxcb-present0 \
        libxcb-randr0 libxcb-sync1 libxcb-xfixes0 libegl1 libgl1 \
    && rm -rf /var/lib/apt/lists/*
USER green

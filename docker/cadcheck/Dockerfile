# Проверка выходного DXF в CAD под Linux без ручной установки CAD.
# Образ открывает DXF в LibreCAD под виртуальным экраном и снимает два экрана: чертёж и
# список слоёв с фильтром GREEN. ТЗ требует показать, что исходные слои целы, а слой
# результата читается в просмотрщике под Linux - это и есть такой просмотрщик.
#
#   docker build -t green-cadcheck docker/cadcheck
#   docker run --rm -v "$PWD/out/cadcheck-in:/w/in" -v "$PWD/out/cadcheck:/w/out" green-cadcheck
#
# QCAD в репозиториях Ubuntu 26.04 нет, nanoCAD под Linux распространяется отдельно:
# проверка идёт в LibreCAD 2.2, остальные просмотрщики остаются на показ.
FROM ubuntu:26.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        librecad xvfb xauth imagemagick xdotool fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY cadcheck.sh /usr/local/bin/cadcheck
RUN chmod +x /usr/local/bin/cadcheck
WORKDIR /w
ENTRYPOINT ["cadcheck"]

# Квадраты OpenStreetMap для 3D-вида

Город вокруг съёмки в 3D-виде (`GET /api/v1/runs/{id}/context`) сервис берёт сначала отсюда, а
для участка вне квадратов - из Overpass, если есть сеть (`GREEN_OSM_CONTEXT`, по умолчанию
`auto`). Квадраты кладутся в образ (`/app/data/osm/moscow`), поэтому на стенде без сети город
вокруг есть.

Сборка - 77 с, 1563 квадрата по 1 км, 34,8 МБ (выгрузка BBBike от 10.10.2026: 185 тыс. домов,
395 тыс. дорог, 36 тыс. зелёных зон, 40 тыс. отдельных деревьев):

```bash
mkdir -p dataset/osm_src
curl -L -o dataset/osm_src/Moscow.osm.pbf https://download.bbbike.org/osm/bbbike/Moscow/Moscow.osm.pbf
uv run --with osmium python tools/osm_moscow.py dataset/osm_src/Moscow.osm.pbf data/osm/moscow
```

Выгрузка покрывает 37,32-37,88 в. д. и 55,57-55,92 с. ш.: Москва в МКАД с запасом, все улицы
пилота. Новая Москва и Зеленоград - вне её, там нужна сеть. Данные - © участники
OpenStreetMap, ODbL; источник показывается в 3D-виде. В git квадраты не идут.

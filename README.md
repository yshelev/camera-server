# Описание

flask используется как файл менеджер для генерируемых файлов формата hls (.ts, .m3u8), отдает по запросу клиента. 
метрики обновляются по сокетам после post запроса на эндпоинт /metrics

# эмуляция rtsp

запуск rtsp сервера
```sh
docker run --rm -it -e MTX_RTSPTRANSPORTS=tcp -e MTX_WEBRTCADDITIONALHOSTS=192.168.x.x -p 8554:8554 -p 1935:1935 -p 8888:8888 -p 8889:8889 -p 8890:8890/udp -p 8189:8189/udp bluenviron/mediamtx:1
```

запуск rtsp потока
```ssh
ffmpeg -re -i sample.mp4 -c copy -f rtsp rtsp://localhost:8554/stream
```

(для проверки можно использовать vlc media player, media -> url -> rtsp://localhost:8554/stream

# запуск

установить зависимости
```sh
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

запустить сервер
```sh
python app.py
```


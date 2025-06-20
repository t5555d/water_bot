FROM python:3.10

ADD . /opt/water_bot
WORKDIR /opt/water_bot
RUN pip install -r requirements.txt

ENTRYPOINT ["/opt/water_bot/water_bot.py"]


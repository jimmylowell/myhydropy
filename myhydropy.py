import argparse
import json
import logging
import os
import time
import threading
import urllib.request
import yaml
import board
import Adafruit_DHT
from prometheus_client import start_http_server, Gauge

OW_URL = "http://api.openweathermap.org/data/2.5/weather?lat={lat}&lon={lon}&APPID={apikey}"

# Get all config properties
with open("config.yml", 'r') as ymlfile:
    cfg = yaml.safe_load(ymlfile)

    # openweather config
    OW = cfg['openweather']
    OW_API = OW['apikey']
    OW_LAT = OW['lat']
    OW_LON = OW['lon']
    OW_API_URL = OW_URL.format(
        apikey=OW_API,
        lat=OW_LAT,
        lon=OW_LON
    )


# Sensor should be set to Adafruit_DHT.DHT11,
# Adafruit_DHT.DHT22, or Adafruit_DHT.AM2302.
sensor = Adafruit_DHT.DHT22
pin = 4



# Import SPI library (for hardware SPI) and MCP3008 library.
import Adafruit_GPIO.SPI as SPI

# import Adafruit_MCP3008

# setup logging
logger = logging.getLogger('myhydroypi')
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler()
ch.setLevel(logging.INFO)
logger.addHandler(ch)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)

# Software SPI configuration for analog sensors
# CLK = 18
# MISO = 23
# MOSI = 24
# CS = 25
# mcp = Adafruit_MCP3008.MCP3008(clk=CLK, cs=CS, miso=MISO, mosi=MOSI)

# which input channels on the MCP3008 are the sensors connected to
# ANALOG_CHANNEL_LIGHT = 0

# setup filepath to read 1-wire device readings
# base_dir = '/sys/bus/w1/devices/'
# ambiant_temp_path = os.path.join(base_dir, "28-03168be0d1ff", "w1_slave")
# reservoir_temp_path = os.path.join(base_dir, "28-0416a192e5ff", "w1_slave")


def read_1wire(path):
    # 5d 01 4b 46 7f ff 0c 10 94 : crc=94 YES
    # 5d 01 4b 46 7f ff 0c 10 94 t=21812
    lines = open(path).readlines()
    if lines[0].strip()[-3:] != 'YES':
        return NaN

    equals_pos = lines[1].find('t=')
    if equals_pos != -1:
        temp_string = lines[1][equals_pos + 2:]
        return float(temp_string)


# setup prometeus metrics
RESERVOIR_TEMP = Gauge('reservoir_temp', 'Reservoir temperature')
LIGHT_INTENSITY = Gauge('light_intensity', 'Light intensity')

AMBIANT_TEMP = Gauge('ambiant_temp', 'Ambiant temperature (F)')
HUMIDITY = Gauge('humidity', '% Humidity')

WEATHER_TEMPERATURE = Gauge('weather_temp', 'Weather - Temperature in celcius')
WEATHER_PRESSURE = Gauge('weather_pressure',
                         'Weather - Atmospheric pressure (on the sea level, ' +
                         'if there is no sea_level or grnd_level data), hPa')
WEATHER_HUMIDITY = Gauge('weather_humidity', 'Weather - Humidity %')
WEATHER_WIND_SPEED = Gauge('weather_wind_speed',
                           'Weather - Wind speed meter/sec')
WEATHER_CLOUDS = Gauge('weather_cloud', 'Weather - Cloudiness %')
WEATHER_SUNRISE = Gauge('weather_sunrise', 'Weather - Sunrise time, unix, UTC')
WEATHER_SUNSET = Gauge('weather_sunset', 'Weather - Sunset time, unix, UTC')


def update_temp():
    try:
        humidity, temperature_c = Adafruit_DHT.read_retry(sensor, pin)
        if humidity is not None and temperature_c is not None:
            temperature_f = temperature_c * (9 / 5) + 32
            logger.info("Temp: {:.1f} F / {:.1f} C    Humidity: {:.1f}% "
                        .format(temperature_f, temperature_c, humidity))
            HUMIDITY.set(humidity)
            AMBIANT_TEMP.set(temperature_f)
        else:
            print("Failed to retrieve data from humidity sensor")
    except RuntimeError as error:
        # Errors happen fairly often, DHT's are hard to read, just keep going
        print(error.args[0])


def update_light_intensity():
    val = mcp.read_adc(ANALOG_CHANNEL_LIGHT)
    LIGHT_INTENSITY.set(val)
    logger.debug("Light intensity: " + str(val))


def update_reservoir_temp():
    val = read_1wire(reservoir_temp_path) / 1000.0
    logger.debug("Reservoir temp: " + str(val) + " Celcius")
    RESERVOIR_TEMP.set(val)


last_weather_update = -1


def update_current_weather():
    global last_weather_update
    time_diff = time.time() - last_weather_update
    logger.info('time dif: ' + str(time_diff))
    if time_diff > 60:
        last_weather_update = time.time()
        try:
            with urllib.request.urlopen(OW_API_URL) as url:
                data = json.loads(url.read().decode())
                logger.info(data)
                temp_k = data["main"]["temp"]
                temp_f = (9 / 5) * (temp_k - 273) + 32
                WEATHER_TEMPERATURE.set(temp_f)
                WEATHER_PRESSURE.set(data["main"]["pressure"])
                WEATHER_HUMIDITY.set(data["main"]["humidity"])
                WEATHER_WIND_SPEED.set(data["wind"]["speed"])
                WEATHER_CLOUDS.set(data["clouds"]["all"])
                WEATHER_SUNRISE.set(data["sys"]["sunrise"])
                WEATHER_SUNSET.set(data["sys"]["sunset"])

        except Exception as e:
            logger.warning("Error updating weather: " + str(e))


if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument("-p", "--port", help="Port to use for web server",
                        type=int, default=8000)
    parser.add_argument("--disable-light-sensor", help="Disable reading from the light sensor", action="store_true")
    parser.add_argument("--disable-reservoir-sensor", help="Disable reading from the reservoir temperature sensor",
                        action="store_true")
    parser.add_argument("--disable-ambiant-sensor", help="Disable reading from the ambiant temperature sensor",
                        action="store_true")
    parser.add_argument("--disable-weather", help="Disable fetching current weather", action="store_true")
    args = parser.parse_args()

    # Start up the prometheus server to expose the metrics.
    logger.info("Starting up HTTP server on port %d..." % args.port)
    start_http_server(args.port)

    logger.info("Starting main loop...")
    while True:
        logger.debug("Polling sensors")
        # if not args.disable_light_sensor: update_light_intensity()
        # if not args.disable_reservoir_sensor: update_reservoir_temp()
        if not args.disable_weather:
            update_current_weather()
        update_temp()
        time.sleep(10)

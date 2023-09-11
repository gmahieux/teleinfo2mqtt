## Teleinfo 2 MQTT

![Docker image](https://github.com/gmahieux/teleinfo2mqtt/actions/workflows/docker-publish.yml/badge.svg)

This project allows retrieving Linky's teleinfo data and send it to MQTT so that it can be plug, for example, to Home Assistant.

You will need a physical module like [this one](https://www.tindie.com/products/hallard/micro-teleinfo-v30/) to connect the teleinfo wires to you computer.

It has been tested with the linky TIC configured in `standard` mode. `historique` mode would need some work to be handled properly. Feel free to contribute :)

In addition to retrieving the different TIC information, the script also decodes and returns individual measures from the register (`STGE` field)

See [Enedis-NOI-CPT_54E](https://www.enedis.fr/media/2035/download) for more info about the linky TIC

## Running the script

### In a container

The easiest way to run the script is using container. You can either run the container directly with the Docker CLI or use docker compose

#### Docker

`docker run --device=path/to/serial/port -e LINKY_PORT=path/to/serial/port -e MQTT_IP=xxx.xxx.xxx.xxx gmahieux/teleinfo2mqtt`

See the [configuration](#configuration) section to get the other environment variable you can add to the command line

Note: If some configuration parameters that cannot be modified with envvars have to be customized. The easiest way is to bind-mount the config file

`docker run [...other parameters here...] -v [PATH_TO_LOCAL_CONFIG_YML]:config.yml:ro gmahieux/teleinfo2mqtt` 

#### Docker Compose

TBD

### Directly from the script

#### Install python

If pyhton is not installed on your machine, you can install it with this tutorial

#### Install dependencies

The script needs some dependencies to run. They can be installed with the following command

`pip install pyserial paho-mqtt PyYAML`

#### Run the script

- Download `teleinfo.py` and `config.yml`, put them on the machine connected to your linky
- Update the [configuration](#configuration)
- Run `python teleinfo.py`

### Configuration

You can either modify the `config.yml` file directly. However, the most interesting properties can also be set with environment variables (useful when running in a container)

| Property               | Env Var    | Description |
|------------------------|------------|-------------|
| log_level              | LOG_LEVEL  | One of `DEBUG`, `INFO`, `WARNING` or `ERROR` depending on the level of information you want in the logs. Default is `INFO`
| linky.legacy_mode      | N/A        | Set to true if your the TIC of your Linky is in `historique` mode, false if it is in `standard` mode. The default mode is `historique` you have to contact the energy provider to set it to history mode. Note : the script has only been tested in `standard`mode and probably do not work in `historique` mode. Feel free to contribute to fix it ;) |
| linky.ignored_keys     | N/A        | An array containing the TIC keys you don't want to be sent in the MQTT message |
| linky.port             | LINKY_PORT | The serial port your teleinfo module is connected to. | 
| linky.register_mapping | N/A        | Textual mapping of the values from the register (`STGE` field) |
| mqtt.send_data         | N/A        | Default `true`. Set to `false` for debugging purpose in order to avoid sending MQTT messages 
| mqtt.server_ip         | MQTT_IP    | The IP of the MQTT server
| mqtt.port              | MQTT_PORT  | The Port of the MQTT server
| mqtt.keepalive         | N/A        | The MQTT keepalive interval
| mqtt.user              | MQTT_USER  | The username to use while connecting to MQTT server
| mqtt.password          | MQTT_PWD   | The password to use while connecting to MQTT server
| ha.reset_discovery     | N/A        | Set to `false` to delete the aautodiscovery message fro MQTT. The effect is is will remove the Linky device from HomeAssistant
| ha.key_mapping         | N/A        | Maps the TIC key to informations used in HA discovery messages to automatically create entities
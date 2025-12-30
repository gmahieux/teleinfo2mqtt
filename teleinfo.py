#!/usr/bin/env python3

import logging
import signal
import time
import json
import termios
import os
import sys
from collections import deque
from datetime import datetime

import serial
import yaml
import paho.mqtt.client as mqtt

START_FRAME = b'\x02'  # STX, Start of Text
STOP_FRAME = b'\x03'   # ETX, End of Text


def _handler(signum, frame):
    logging.info('Programme interrompu par CTRL+C')
    raise SystemExit(0)

def _send_to_mqtt(frame):
    logging.debug(f'Ecriture dans MQTT ')
    publish_message(json.dumps(frame),"linky/state")


def _checksum(key, date, val, separator, checksum):
    if linky_legacy_mode:
        data = f'{key}{separator}{val}'
    elif date is not None:
        data = f'{key}{separator}{date}{separator}{val}{separator}'
    else:
        data = f'{key}{separator}{val}{separator}'
    s = sum([ord(c) for c in data])
    s = (s & 0x3F) + 0x20
    return (checksum == chr(s))

def _hex_to_binary(hex_string):
    return bin(int(hex_string, 16))[2:].zfill(32)

def _reverse(string):
    return string[::-1]

def _bin_to_decimal(bin_string):
    return int(bin_string,2)

def _readframe(ser):
    frame = dict()
    # Read lines until stop_frame
    while True:
        try:
            line = ser.readline()
            if line == "":
                frame['OFFLINE']=True
                return frame
            # cleanup + ascii conversion
            line_str = ''.join(line.replace(STOP_FRAME,b'').replace(START_FRAME,b'').decode('ascii').splitlines())

            parts = line_str.split(separator)
            key = parts[0]
            if (len(parts) > 3):
                date= parts[1]
                val = parts[2]
            else:
                date = None
                val = parts[1]
            checksum = parts[-1]
            logging.debug(f'Raw data line received: {line_str}, key: {key}, date: {date}, value: {val}, checksum: {checksum}, parts: {len(parts)}.')

            if linky_legacy_mode:
                if len(parts) != 3:
                    logging.debug(f"line has {len(parts)} parts, not 3")
                    continue
                if _checksum(key, date, val, separator, checksum) == False:
                    logging.warning(f"invalid checksum found for line {line_str}")
                    continue
                try:
                    frame[key] = int(val)
                except:
                    frame[key] = val.strip()
            else:
                if (key == 'STGE') or (key == 'DATE') or (key not in linky_ignored_keys):       
                    if _checksum(key, date, val, separator, checksum): 
                        if (key == 'DATE'):
                            frame["DATE"]=datetime.strptime(date[1:], '%y%m%d%H%M%S').strftime('%Y-%m-%d %H:%M:%S')  
                        elif (key == 'STGE'):
                            register = _reverse(_hex_to_binary(val))
                            frame["R_CONTACT_SEC"]=int(register[0])
                            frame["R_COUPURE"]=linky_register_mapping["R_COUPURE"][_bin_to_decimal(_reverse(register[1:4]))]
                            frame["R_CACHE"]=int(register[4])
                            frame["R_SURTENSION"]=int(register[6])
                            frame["R_DEPASSEMENT"]=int(register[7])
                            frame["R_INJECTION"]=int(register[9])
                            frame["R_TARIF_FOUR"]=linky_register_mapping["R_TARIF_FOUR"][_bin_to_decimal(_reverse(register[10:14]))]
                            frame["R_TARIF_DIST"]=linky_register_mapping["R_TARIF_DIST"][_bin_to_decimal(_reverse(register[14:16]))]
                            frame["R_ETAT_HORLOGE"]=int(register[16])
                            frame["R_MODE"]=linky_register_mapping["R_MODE"][int(register[17])]
                            frame["R_COMM"]=linky_register_mapping["R_COMM"][_bin_to_decimal(_reverse(register[19:21]))]
                            frame["R_CPL"]=linky_register_mapping["R_CPL"][_bin_to_decimal(_reverse(register[21:23]))]
                            frame["R_CPL_SYNC"]=int(register[23])
                            frame["R_COULEUR_J"]=linky_register_mapping["R_COULEUR_J"][_bin_to_decimal(_reverse(register[24:26]))]
                            frame["R_COULEUR_J+1"]=linky_register_mapping["R_COULEUR_J"][_bin_to_decimal(_reverse(register[26:28]))]
                            frame["R_PREAVIS_POINTE"]=linky_register_mapping["R_PREAVIS_POINTE"][_bin_to_decimal(_reverse(register[28:30]))]
                            frame["R_POINTE"]=linky_register_mapping["R_POINTE"][_bin_to_decimal(_reverse(register[30:32]))]
                        else:
                            try:
                                frame[key] = int(val)
                            except:
                                frame[key] = val.strip()
                    else:
                        logging.error(f'Invalid checksum for key {key} : {line_str}')
            
            if STOP_FRAME in line:            
                logging.info(f'Frame processed ({len(frame)} keys retained)')
                logging.debug(f'Frame content: {frame}')
                return frame

        except Exception as e:
            logging.error(f'Unexpected error : {e}', exc_info=True)
            logging.shutdown()
            sys.exit(1)

def get_consumption(frame_window):
    last = frame_window[0]
    curindex = 1
    while (curindex < len(frame_window) and last["EAST"] == frame_window[curindex]["EAST"] and last.get("EAIT", 0) == frame_window[curindex].get("EAIT", 0)):
        last = frame_window[curindex]
        curindex += 1
        
    first = last
    while (curindex < len(frame_window) and first == last):
        cur_frame = frame_window[curindex]
        duration_between_measures = (datetime.fromisoformat(last["DATE"]) - datetime.fromisoformat(cur_frame["DATE"])).total_seconds()
        consumption_between_measures = last["EAST"] - cur_frame["EAST"]
        injection_between_measures =last.get("EAIT", 0) - cur_frame.get("EAIT", 0)
        if (curindex == len(frame_window) or (duration_between_measures >= 15 and (consumption_between_measures >= 2 or injection_between_measures >= 2))):
            first = cur_frame
        curindex += 1
    
    while (curindex < len(frame_window) and first["EAST"] == frame_window[curindex]["EAST"] and first.get("EAIT",0) == frame_window[curindex].get("EAIT", 0)):
       first = frame_window[curindex]
       curindex += 1
    
    consumed = last["EAST"] - first["EAST"]
    injected = last.get("EAIT", 0) - first.get("EAIT", 0)
    time = (datetime.fromisoformat(last["DATE"]) - datetime.fromisoformat(first["DATE"])).total_seconds()
    if (time == 0) :
        logging.info(f'no consumption recorded, first ands last frame time are the same')
        return 0
    consumption = round((consumed - injected) * 3600 / time)
    logging.info(f'consumed : {consumed}, injected: {injected}, time: {time}, consumption: {consumption}')
    return consumption
    

def linky():
    try:
        baudrate = 1200 if linky_legacy_mode else 9600
        logging.info(f'Opening serial port {linky_port} à {baudrate} Bd')
        with serial.Serial(port=linky_port,
                           baudrate=baudrate,
                           parity=serial.PARITY_EVEN,
                           stopbits=serial.STOPBITS_ONE,
                           bytesize=serial.SEVENBITS,
                           timeout=1) as ser:

            logging.info('Waiting for 1st frame...')
            line = ser.readline()
            while START_FRAME not in line:
                line = ser.readline()
            offline = False
            frame_window = deque([],100)
            while True:                
                frame = _readframe(ser)
                if("OFFLINE" in frame):
                    offline = True
                    publish_message("offline","linky/status")
                else:
                    if (offline):
                        offline = False
                        publish_message("online","linky/status")
                    if ("EAST" in frame):
                        frame_window.appendleft(frame)
                    if(len(frame_window) > 5):
                        consumption =get_consumption(frame_window)
                        if (consumption is not None):
                            frame["C_CONSO_INST"] =consumption
                    if mqtt_send_data:
                        _send_to_mqtt(frame)                
                

    except termios.error as exc:
        logging.error(f'Serial port configuration error : {exc}')
        raise SystemExit(1)

    except serial.SerialException as exc:
        if exc.errno == 13:
            logging.error('Authorization error on serial port')
            logging.error('Ensure the user has been added to the dialout group ?')
            logging.error('  $ sudo usermod -G dialout $USER')
            logging.error('(log out and log in to reload permissions)')
        else:
            logging.error(f'Error while opening serial port : {exc}')
        raise SystemExit(1)


def recon():
    try:
        mqttc.reconnect()
        logging.info('Successfull reconnected to the MQTT server')
    except:
        logging.warning('Could not reconnect to the MQTT server. Trying again in 10 seconds')
        time.sleep(10)
        recon()

def publish_message(msg, mqtt_path):
    try:
        mqttc.publish(mqtt_path, payload=msg, qos=0, retain=True)
    except:
        logging.warning('Publishing message '+msg+' to topic '+mqtt_path+' failed.')
        logging.warning('Exception information:')
        logging.warning(sys.exc_info())
    else:
        logging.debug('published message {0} on topic {1} at {2}'.format(msg, mqtt_path, time.asctime(time.localtime(time.time()))))

def delete_message(mqtt_path):
    try:
        mqttc.publish(mqtt_path, payload="", qos=0, retain=False)
    except:
        logging.error('Deleting topic ' + mqtt_path + ' failed.')
        logging.warning('Exception information:')
        logging.warning(sys.exc_info())
    else:
        time.sleep(0.1)
        logging.debug('delete topic {0} at {1}'.format(mqtt_path, time.asctime(time.localtime(time.time()))))

def send_autodiscovery_messages():    
    logging.info('Sending autodiscovery messages')
    for key,props in ha_key_mapping.items():
        mqtt_config_topic = ("homeassistant/" + ha_key_mapping[key]["type"] + "/linky/" + key + "/config").replace('+','_')
        if (ha_reset_discovery):
            logging.warning('Deleting autodiscover for ' + mqtt_config_topic)
            delete_message(mqtt_config_topic)
        if (key in linky_ignored_keys):
            logging.debug('Deleting autodiscover for ' + mqtt_config_topic)
            delete_message(mqtt_config_topic)
        else:
            discovery_message = {
                "availability_topic": "linky/status",
                "state_topic": "linky/state",
                "value_template": "{{ value_json[\"" + key + "\"]}}",
                "payload_available": "online",
                "payload_not_available": "offline",
                "unique_id": "linky_"+ key,
                "device": {
                    "identifiers":[
                        "Linky"
                    ],
                    "name": "Linky",
                    "manufacturer": "Enedis",
                    "model": "Linky"
                },
                "object_id": "linky_"+key,
            }
            for prop,value in props.items():
                discovery_message[prop] = value        
    
            logging.debug('Sending autodiscover for ' + mqtt_config_topic)
            publish_message(json.dumps(discovery_message), mqtt_config_topic)       

def on_connect(client, userdata, flags, reason_code, properties):
    logging.info('Connected to MQTT broker')
    publish_message("online","linky/status")
    send_autodiscovery_messages()
    
   
def on_disconnect(client, userdata, disconnect_flags, reason_code, properties):
    if reason_code != 0:
        logging.warning('Unexpected disconnection from MQTT, trying to reconnect')
        recon()


def get_log_level(levelStr):
    if levelStr == "debug":
        return logging.DEBUG
    elif levelStr == "warning":
        return logging.WARNING        
    elif levelStr == "error":
        return logging.ERROR    
    else:
        return logging.INFO
    
if __name__ == '__main__':

    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s: %(message)s')
    logging.info('Démarrage Linky Téléinfo')

    # Capture élégamment une interruption par CTRL+C
    signal.signal(signal.SIGINT, _handler)

    # Lecture du fichier de configuration
    try:
        with open("config.yml", "r") as f:
            cfg = yaml.load(f, Loader=yaml.SafeLoader)
    except FileNotFoundError:
        logging.error('Configuration file (config.yml) is missing')
        raise SystemExit(1)
    except yaml.YAMLError as exc:
        if hasattr(exc, 'problem_mark'):
            mark = exc.problem_mark
            logging.error('Le fichier de configuration comporte une erreur de syntaxe')
            logging.error(f'La position de l\'erreur semble être en ligne {mark.line+1} colonne {mark.column+1}')
            raise SystemExit(1)
    except (OSError, IOError):
        logging.error('Erreur de lecture du fichier config.yml. Vérifiez les permissions ?')
        raise SystemExit(1)
    except Exception:
        logging.critical('Erreur lors de la lecture du fichier de configuration', exc_info=True)
        raise SystemExit(1)

    try:
        log_level = os.environ.get("LOG_LEVEL", cfg.get('log_level', 'info'))
        linky_legacy_mode = cfg['linky']['legacy_mode']
        linky_ignored_keys = cfg['linky']['ignored_historic_keys'] if linky_legacy_mode else cfg['linky']['ignored_standard_keys']
        linky_port = os.environ.get("LINKY_PORT", cfg['linky']['port'])
        linky_register_mapping = cfg['linky']['register_mapping']
        ha_reset_discovery = cfg['ha']['reset_discovery']
        ha_key_mapping = cfg['ha']['historic_key_mapping'] if linky_legacy_mode else cfg['ha']['standard_key_mapping']
        mqtt_send_data = cfg['mqtt'].get('send_data',True)
        mqtt_server = os.environ.get("MQTT_IP", cfg['mqtt']['server_ip']) 
        mqtt_port = int(os.environ.get("MQTT_PORT", cfg['mqtt']['port']))      
        mqtt_keepalive = int(cfg['mqtt']['keepalive']) 
        mqtt_user = os.environ.get("MQTT_USER", cfg['mqtt']['user'])
        mqtt_password = os.environ.get("MQTT_PWD", cfg['mqtt']['password'])
    except KeyError as exc:
        logging.error(f'Key {exc} is missing in configuration file')
        raise SystemExit(1)
    except Exception:
        logging.critical('Unable to read configuration file', exc_info=True)
        raise SystemExit(1)


    separator = ' ' if linky_legacy_mode else '\t'

    logging.getLogger().setLevel(get_log_level(log_level))

    write_client = None
    if mqtt_send_data:
        # Connexion à MQTT
        logging.info('Initiating MQTT connection')
        mqttc = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,'Linky')
        if  mqtt_user != False and mqtt_password != False :
            mqttc.username_pw_set(mqtt_user,mqtt_password)

        # Define the mqtt callbacks
        mqttc.on_connect = on_connect
        mqttc.on_disconnect = on_disconnect
        mqttc.will_set("linky/status",payload="offline", qos=0, retain=True)

        # Connect to the MQTT server
        while True:
            try:
                mqttc.connect(mqtt_server, mqtt_port, mqtt_keepalive)
                mqttc.loop_start()
                break
            except:
                logging.warning('Can\'t connect to MQTT broker. Retrying in 10 seconds.')
                time.sleep(10)
                pass        
    # Lance la boucle infinie de lecture de la téléinfo
    linky()

import json
import logging
import os
from base64 import b64decode

import psutil
import requests

from pgscout.config import cfg_get
from pgscout.AppState import AppState

from requests_futures.sessions import FuturesSession
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

log = logging.getLogger(__name__)

app_state = AppState()

import socket
import fcntl
import struct

def get_ip_address(ifname):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8915,  # SIOCGIFADDR
        struct.pack('256s', ifname[:15])
    )[20:24])


# Get a future_requests FuturesSession that supports asynchronous workers
# and retrying requests on failure.
# Setting up a persistent session that is re-used by multiple requests can
# speed up requests to the same host, as it'll re-use the underlying TCP
# connection.
def get_async_requests_session(num_retries, backoff_factor, pool_size,
                               status_forcelist=None):
    # Use requests & urllib3 to auto-retry.
    # If the backoff_factor is 0.1, then sleep() will sleep for [0.1s, 0.2s,
    # 0.4s, ...] between retries. It will also force a retry if the status
    # code returned is in status_forcelist.
    if status_forcelist is None:
        status_forcelist = [500, 502, 503, 504]
    session = FuturesSession(max_workers=pool_size)

    # If any regular response is generated, no retry is done. Without using
    # the status_forcelist, even a response with status 500 will not be
    # retried.
    retries = Retry(total=num_retries, backoff_factor=backoff_factor,
                    status_forcelist=status_forcelist)

    # Mount handler on both HTTP & HTTPS.
    session.mount('http://', HTTPAdapter(max_retries=retries,
                                         pool_connections=pool_size,
                                         pool_maxsize=pool_size))
    session.mount('https://', HTTPAdapter(max_retries=retries,
                                          pool_connections=pool_size,
                                          pool_maxsize=pool_size))

    return session

def send_status_to_discord(args, title, message, embed_color):
    if args.scan_log_webhook:
        log.info('Beginning scan log webhook consruction.')
        req_timeout = 1.0
    
        payload = {
            'embeds': [{
                'title': title,
                'description': '{}\n\nConfig: {}\nPath: {}\nIP: {}'.format(message, args.config, os.path.realpath(__file__), get_ip_address('ens192')),
                'color': embed_color
            }]
        }

        try:
            session = get_async_requests_session(
                3,
                0.25,
                25)

            # Disable keep-alive and set streaming to True, so we can skip
            # the response content.
            session.post(args.scan_log_webhook, json=payload,
                         timeout=(None, req_timeout),
                         background_callback=__wh_completed,
                         headers={'Connection': 'close'},
                         stream=True)
        except requests.exceptions.ReadTimeout:
            log.exception('Response timeout on webhook endpoint %s.', w)
        except requests.exceptions.RequestException as e:
            log.exception(e)
    else:
        return


def rss_mem_size():
    process = psutil.Process(os.getpid())
    mem = process.memory_info().rss
    unit = 'bytes'
    if mem > 1024:
        unit = 'KB'
        mem /= 1024
    if mem > 1024:
        unit = 'MB'
        mem /= 1024
    if mem > 1024:
        unit = 'GB'
        mem /= 1024
    return "{:>4.1f} {}".format(mem, unit)


def normalize_encounter_id(eid):
    if not eid:
        return eid
    try:
        return long(eid)
    except:
        return long(b64decode(eid))


def get_pokemon_name(pokemon_id):
    if not hasattr(get_pokemon_name, 'pokemon'):
        file_path = os.path.join('pokemon.json')

        with open(file_path, 'r') as f:
            get_pokemon_name.pokemon = json.loads(f.read())
    return get_pokemon_name.pokemon[str(pokemon_id)]


def get_move_name(move_id):
    if not hasattr(get_move_name, 'mapping'):
        with open("pokemon_moves.json", 'r') as f:
            get_move_name.mapping = json.loads(f.read())
    return get_move_name.mapping.get(str(move_id))


def calc_pokemon_level(cp_multiplier):
    if cp_multiplier < 0.734:
        level = 58.35178527 * cp_multiplier * cp_multiplier - 2.838007664 * cp_multiplier + 0.8539209906
    else:
        level = 171.0112688 * cp_multiplier - 95.20425243
    level = (round(level) * 2) / 2.0
    return int(level)


def calc_iv(at, df, st):
    return float(at + df + st) / 45 * 100


def load_pgpool_accounts(count, reuse=False):
    addl_text = " Reusing previous accounts." if reuse else ""
    log.info("Trying to load {} accounts from PGPool.{}".format(count, addl_text))
    request = {
        'system_id': cfg_get('pgpool_system_id'),
        'count': count,
        'min_level': cfg_get('level'),
        'reuse': reuse
    }
    r = requests.get("{}/account/request".format(cfg_get('pgpool_url')), params=request)
    return r.json()

import logging
from configparser import ConfigParser
from os import path

LOG = logging.getLogger('http2broker')

CONFIG = [None]

class MyParser(ConfigParser):
  def as_dict(self):
        d = dict(self._sections)
        for k in d:
            d[k] = dict(self._defaults, **d[k])
            d[k].pop('__name__', None)
        return d

def get_config():
    if CONFIG[0] is None:
        parser = MyParser()
        res = parser.read( path.abspath('h2a.ini') )
        if len(res) == 0:
            LOG.warning("Could not read 'h2a.ini'")

        CONFIG[0] = parser.as_dict()

    return CONFIG[0]

import yaml
from yaml.loader import FullLoader
from os import path


class ConfigLoader:
    def __init__(self, file_path=path.join(path.dirname(__file__), 'data/config.yaml')):
        with open(file_path, 'r') as c_file:
            self.config = yaml.load(c_file, FullLoader)


    def get_key(self, keys: str, separator='.'):
        """
        returns a from the config file
        use separator ('.' by default) for nested keys
        throws KeyError if it does not exists
        """
        value = self.config

        for key in keys.split(sep=separator):
            value = value[key]

        return value


    def __getitem__(self, key):
        return self.get_key(key)

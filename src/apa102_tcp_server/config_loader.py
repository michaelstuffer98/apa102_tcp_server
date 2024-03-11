from os import PathLike, path
from typing import Any

import yaml
from yaml.loader import FullLoader


class ConfigLoader:
    def __init__(self, file_path: str | PathLike = path.join(path.dirname(__file__), 'data/config.yaml'),
                 separator: str = '.') -> None:
        with open(file_path, 'r') as c_file:
            self.config = yaml.load(c_file, FullLoader)

        self.separator = separator

    def get_key(self, keys: str) -> Any:
        """
        returns a from the config file
        use separator ('.' by default) for nested keys
        throws KeyError if it does not exists
        """
        value = self.config

        for key in keys.split(sep=self.separator):
            value = value[key]

        return value

    def __getitem__(self, key: str) -> Any:
        return self.get_key(key)

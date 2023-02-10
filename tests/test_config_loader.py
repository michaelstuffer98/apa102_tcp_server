from apa102_tcp_server.config_laoder import ConfigLoader
import os
from directories import tests_directory


def test_config_loader_key_access(tests_directory):
    loader = ConfigLoader(file_path=os.path.join(tests_directory, 'test_config.yaml'))

    assert loader.get_key('key1') == 1
    assert loader.get_key('key2.sub_key1') == 1.5
    assert loader.get_key('key2.sub_key2.subsub_key1') == 'test'
    assert loader.get_key('key2.sub_key2.subsub_key2') == 3
    assert loader.get_key('key3') == [1, 2, 3]


def test_config_loader_config_file():
    loader = ConfigLoader()

    for key in loader.config.keys():
        loader.get_key(key)

import builtins as __builtin__
import queue


class Log:
    # TODO make print thread save!
    print_queue = queue.Queue()

    def add(self, *args, **kwargs):
        self.print_queue.put((args, kwargs))

    @staticmethod
    def log(name: str, *args, **kwargs):
        __builtin__.print(name, *args, **kwargs)

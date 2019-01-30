import sys
import marshal

sys.path.append('/usr/lib/python3.4/site-packages')

with open(__file__[:-3], 'rb') as f:
   mods = marshal.loads(f.read())

class Loader():
    def __init__(self, fullname, path, code):
        self._fullname = fullname
        self._path = path
        self._code = code

    def exec_module(self, module):
        module.__file__ = self._path
        if self._path.endswith('/__init__.py'):
            module.__path__ = [self._path[:-12]]
            module.__package__ = self._fullname
        exec(self._code, module.__dict__)

    def get_code(self, fullname=None):
        return self._code

    def get_filename(self, fullname):
        return self._path

class Finder():
    @staticmethod
    def find_module(fullname, path=None):
        if fullname in mods:
            return Loader(fullname, *mods[fullname])

sys.meta_path.insert(0, Finder)

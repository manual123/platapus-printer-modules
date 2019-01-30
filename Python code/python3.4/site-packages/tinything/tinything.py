import ctypes
import json

errors = {
    'ok': 0,
    'not_yet_unzipped': 1,
    'tool_mismatch': 2,
    'bot_type_mismatch': 3,
    'version_mismatch': 4,
    'max_string_length_exceeded': 5
}


class VerificationStruct(ctypes.LittleEndianStructure):
    _fields_ = (
        ("tool_count", ctypes.c_uint8),
        ("tool", ctypes.c_int*2),
        ("pid", ctypes.c_uint8)
    )


def good_str(ctypes_buf):
    return bytes(ctypes_buf).decode('ascii').rstrip('\x00')


class MetadataStruct(ctypes.LittleEndianStructure):

    fields = [
        ("extruder_count", ctypes.c_int, int),
        ("extrusion_distance_mm", ctypes.c_float*2, lambda l: [float(f) for f in l]),
        ("extruder_temperature", ctypes.c_int*2, lambda l: [int(i) for i in l]),
        ("extrusion_mass_g", ctypes.c_float*2, lambda l: [float(f) for f in l]),
        ("chamber_temperature", ctypes.c_int, int),
        ("thing_id", ctypes.c_int, int),
        ("duration_s", ctypes.c_float, float),
        ("uses_raft", ctypes.c_bool, bool),
        ("uuid", ctypes.c_char * 100, good_str),
        ("material", (ctypes.c_char*50)*2, lambda l: [good_str(s) for s in l]),
        ("tool_type", ctypes.c_int*2, lambda l: [int(i) for i in l]),
        ("bot_pid", ctypes.c_uint, int),
        ("bounding_box_x_min", ctypes.c_float, float),
        ("bounding_box_x_max", ctypes.c_float, float),
        ("bounding_box_y_min", ctypes.c_float, float),
        ("bounding_box_y_max", ctypes.c_float, float),
        ("bounding_box_z_min", ctypes.c_float, float),
        ("bounding_box_z_max", ctypes.c_float, float),
        ("file_size", ctypes.c_uint32, int)
    ]
    _fields_ = [(f[0], f[1]) for f in fields]

    def to_dict(self):
        res = {}
        for (name, _, caster) in self.fields:
            res[name] = val = caster(getattr(self, name))
            # Fix the stupid ctypes resstriction on dynamic array sizes
            if isinstance(val, list):
                val[:] = val[:res['extruder_count']]
        return res


class TinyThing:
    """
    @param lib_path: optional parameter for custom library path
    """
    def __init__(self, zipfile_path:str, fd:int=0, lib_path:str='/usr/lib/libtinything.so'):
        self._libtinything = ctypes.CDLL(lib_path)
        if None is not zipfile_path:
            c_path = ctypes.c_char_p(bytes(zipfile_path.encode('UTF-8')))
        else:
            c_path = ctypes.c_char_p(b"")
        c_fd = ctypes.c_int(fd)
        self.reader = self._libtinything.NewTinyThingReader(c_path, c_fd)

    def does_metadata_match(self, tools, pid):
        c_struct = VerificationStruct()
        c_struct.tool_count = len(tools)
        c_struct.pid = pid
        for tool_idx in range(min(len(tools), 2)):
            c_struct.tool[tool_idx] = tools[tool_idx]
        error = self._libtinything.DoesMetadataMatch(self.reader, ctypes.byref(c_struct))
        if error == errors['not_yet_unzipped']:
            raise NotYetUnzippedException('meta.json')
        else:
            return error

    def unzip_metadata(self):
        return self._libtinything.UnzipMetadata(self.reader)

    def get_metadata(self):
        data = MetadataStruct()
        error = self._libtinything.GetMetadata(self.reader, ctypes.byref(data))
        if error == errors['not_yet_unzipped']:
            raise NotYetUnzippedException('meta.json')
        else:
            return data.to_dict()

    def get_slice_profile(self):
        prof_pointer = ctypes.POINTER(ctypes.c_char)()
        error = self._libtinything.GetSliceProfile(self.reader,
                                                   ctypes.byref(prof_pointer))
        prof_dict = json.loads(bytes(ctypes.string_at(prof_pointer))
                               .decode('UTF-8'))
        return prof_dict

    def __del__(self):
        self._libtinything.DestroyTinyThingReader(self.reader)


class ToolMismatchException(ValueError):
    pass


class MachineMismatchException(ValueError):
    pass


class NotYetUnzippedException(RuntimeError):
    pass


class VersionMismatchException(RuntimeError):
    pass

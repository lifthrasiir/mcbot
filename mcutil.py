# coding=utf-8

import struct
import array
import sys
import time
import os
import os.path
import gzip

_read_byte   = lambda f: struct.unpack('!b', f.read(1))[0]
_read_short  = lambda f: struct.unpack('!h', f.read(2))[0]
_read_int    = lambda f: struct.unpack('!i', f.read(4))[0]
_read_long   = lambda f: struct.unpack('!q', f.read(8))[0]
_read_float  = lambda f: struct.unpack('!f', f.read(4))[0]
_read_double = lambda f: struct.unpack('!d', f.read(8))[0]

def _read_byte_array(f):
    sz = _read_int(f)
    data = array.array('b')
    data.fromfile(f, sz)
    return data

def _read_string(f):
    sz = _read_short(f)
    s = f.read(sz)
    if len(s) != sz: raise EOFError
    return s.decode('utf-8')

def _read_int_array(f):
    sz = _read_int(f)
    data = array.array('i')
    data.fromfile(f, sz)
    if sys.byteorder != 'big': data.byteswap()
    return data

_simple_readers = [
    None,             # TAG_End
    _read_byte,       # TAG_Byte
    _read_short,      # TAG_Short
    _read_int,        # TAG_Int
    _read_long,       # TAG_Long
    _read_float,      # TAG_Float
    _read_double,     # TAG_Double
    _read_byte_array, # TAG_Byte_Array
    _read_string,     # TAG_String
    None,             # TAG_List
    None,             # TAG_Compound
    _read_int_array,  # TAG_Int_Array
]

def _read_tagged_value(f, tag):
    reader = _simple_readers[tag]
    if reader is not None:
        return reader(f)
    elif tag == 9: # TAG_List
        subtag = ord(f.read(1))
        sz = _read_int(f)
        if 1 <= subtag <= 6:
            data = array.array((None, 'b', 'h', 'i', 'q', 'f', 'd')[subtag])
            data.fromfile(f, sz)
            if sys.byteorder != 'big': data.byteswap()
            return list(data)
        else:
            data = []
            for i in xrange(sz):
                data.append(_read_tagged_value(f, subtag))
            return data
    elif tag == 10: # TAG_Compound
        data = {}
        while True:
            namevalue = parse_nbt(f)
            if namevalue is None: break
            name, value = namevalue
            data[name] = value
        return data
    else:
        raise ValueError('unknown NBT tag %d' % tag)

def parse_nbt(f):
    tag = ord(f.read(1))
    if tag == 0: return None
    name = _read_string(f)
    value = _read_tagged_value(f, tag)
    return name, value

def parse_level_dat(worldpath):
    leveldat = os.path.join(worldpath, 'level.dat')
    with gzip.GzipFile(leveldat, 'rb') as f:
        delta = time.time() - os.stat(leveldat).st_mtime
        _, data = parse_nbt(f)
        data = data['Data']
        data['*LastUpdatedBefore'] = delta
        return data


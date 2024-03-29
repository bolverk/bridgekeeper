# These module alos are used by protection code, so that protection
# code needn't import anything
import os
import platform
import sys
import struct

# Because ctypes is new from Python 2.5, so pytransform doesn't work
# before Python 2.5
#
from ctypes import cdll, c_char, c_char_p, c_int, c_void_p, \
                   pythonapi, py_object, PYFUNCTYPE
from fnmatch import fnmatch

#
# Support Platforms
#
plat_path = 'platforms'

plat_table = (
    ('windows', ('windows', 'cygwin-*')),
    ('darwin', ('darwin', 'ios')),
    ('linux', ('linux*',)),
    ('freebsd', ('freebsd*', 'openbsd*')),
    ('poky', ('poky',)),
    )

arch_table = (
    ('x86', ('i?86', )),
    ('x86_64', ('x64', 'x86_64', 'amd64', 'intel')),
    ('arm', ('armv5',)),
    ('armv7', ('armv7l',)),
    ('aarch32', ('aarch32',)),
    ('aarch64', ('aarch64', 'arm64'))
    )

#
# Hardware type
#
HT_HARDDISK, HT_IFMAC, HT_IPV4, HT_IPV6, HT_DOMAIN = range(5)

#
# Global
#
_pytransform = None


class PytransformError(Exception):
    pass


def dllmethod(func):
    def wrap(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except RuntimeError as e:
            raise PytransformError(e)
    return wrap


@dllmethod
def version_info():
    prototype = PYFUNCTYPE(py_object)
    dlfunc = prototype(('version_info', _pytransform))
    return dlfunc()


@dllmethod
def init_pytransform():
    major, minor = sys.version_info[0:2]
    # Python2.5 no sys.maxsize but sys.maxint
    # bitness = 64 if sys.maxsize > 2**32 else 32
    prototype = PYFUNCTYPE(c_int, c_int, c_int, c_void_p)
    init_module = prototype(('init_module', _pytransform))
    ret = init_module(major, minor, pythonapi._handle)
    if (ret & 0xFFFF) == 0x1001:
        raise PytransformError('Cound not load CPython API(r%d)' % (ret >> 16))
    return ret


@dllmethod
def init_runtime():
    prototype = PYFUNCTYPE(c_int, c_int, c_int, c_int, c_int)
    _init_runtime = prototype(('init_runtime', _pytransform))
    return _init_runtime(0, 0, 0, 0)


@dllmethod
def encrypt_code_object(pubkey, co, flags):
    prototype = PYFUNCTYPE(py_object, py_object, py_object, c_int)
    dlfunc = prototype(('encrypt_code_object', _pytransform))
    return dlfunc(pubkey, co, flags)


@dllmethod
def generate_license_file(filename, priname, rcode, start=-1, count=1):
    prototype = PYFUNCTYPE(c_int, c_char_p, c_char_p, c_char_p, c_int, c_int)
    dlfunc = prototype(('generate_project_license_files', _pytransform))
    return dlfunc(filename.encode(), priname.encode(), rcode.encode(),
                  start, count) if sys.version_info[0] == 3 \
        else dlfunc(filename, priname, rcode, start, count)


@dllmethod
def get_registration_code():
    prototype = PYFUNCTYPE(py_object)
    dlfunc = prototype(('get_registration_code', _pytransform))
    return dlfunc()


@dllmethod
def get_expired_days():
    prototype = PYFUNCTYPE(py_object)
    dlfunc = prototype(('get_expired_days', _pytransform))
    return dlfunc()


def get_hd_info(hdtype, size=256):
    t_buf = c_char * size
    buf = t_buf()
    if (_pytransform.get_hd_info(hdtype, buf, size) == -1):
        raise PytransformError('Get hardware information failed')
    return buf.value.decode()


def show_hd_info():
    return _pytransform.show_hd_info()


def get_license_info():
    info = {
        'EXPIRED': None,
        'HARDDISK': None,
        'IFMAC': None,
        'IFIPV4': None,
        'DOMAIN': None,
        'DATA': None,
        'CODE': None,
    }
    rcode = get_registration_code().decode()
    index = 0
    if rcode.startswith('*TIME:'):
        from time import ctime
        index = rcode.find('\n')
        info['EXPIRED'] = ctime(float(rcode[6:index]))
        index += 1

    if rcode[index:].startswith('*FLAGS:'):
        info['FLAGS'] = 1
        index += len('*FLAGS:') + 1

    prev = None
    start = index
    for k in ['HARDDISK', 'IFMAC', 'IFIPV4', 'DOMAIN', 'FIXKEY', 'CODE']:
        index = rcode.find('*%s:' % k)
        if index > -1:
            if prev is not None:
                info[prev] = rcode[start:index]
            prev = k
            start = index + len(k) + 2
    info['CODE'] = rcode[start:]
    i = info['CODE'].find(';')
    if i > 0:
        info['DATA'] = info['CODE'][i+1:]
        info['CODE'] = info['CODE'][:i]
    return info


def get_license_code():
    return get_license_info()['CODE']


def _match_features(patterns, s):
    for pat in patterns:
        if fnmatch(s, pat):
            return True


def format_platform(platid=None):
    if platid:
        return os.path.normpath(platid)

    plat = platform.system().lower()
    mach = platform.machine().lower()

    for alias, platlist in plat_table:
        if _match_features(platlist, plat):
            plat = alias
            break

    if plat == 'linux':
        cname, cver = platform.libc_ver()
        if cname == 'musl':
            plat = 'alpine'
        elif cname == 'libc':
            plat = 'android'

    for alias, archlist in arch_table:
        if _match_features(archlist, mach):
            mach = alias
            break

    if plat == 'windows' and mach == 'x86_64':
        bitness = struct.calcsize('P'.encode()) * 8
        if bitness == 32:
            mach = 'x86'

    return os.path.join(plat, mach)


# Load _pytransform library
def _load_library(path=None, is_runtime=0, platid=None):
    path = os.path.dirname(__file__) if path is None \
        else os.path.normpath(path)

    plat = platform.system().lower()
    if plat == 'linux':
        filename = os.path.abspath(os.path.join(path, '_pytransform.so'))
    elif plat == 'darwin':
        filename = os.path.join(path, '_pytransform.dylib')
    elif plat == 'windows':
        filename = os.path.join(path, '_pytransform.dll')
    elif plat == 'freebsd':
        filename = os.path.join(path, '_pytransform.so')
    else:
        raise PytransformError('Platform %s not supported' % plat)

    if platid is not None or not os.path.exists(filename) or not is_runtime:
        libpath = platid if platid is not None and os.path.isabs(platid) else \
            os.path.join(path, plat_path, format_platform(platid))
        filename = os.path.join(libpath, os.path.basename(filename))

    if not os.path.exists(filename):
        raise PytransformError('Could not find "%s"' % filename)

    try:
        m = cdll.LoadLibrary(filename)
    except Exception as e:
        raise PytransformError('Load %s failed:\n%s' % (filename, e))

    # Removed from v4.6.1
    # if plat == 'linux':
    #     m.set_option(-1, find_library('c').encode())

    if not os.path.abspath('.') == os.path.abspath(path):
        m.set_option(1, path.encode() if sys.version_info[0] == 3 else path)

    # Required from Python3.6
    m.set_option(2, sys.byteorder.encode())

    if sys.flags.debug:
        m.set_option(3, c_char_p(1))
    m.set_option(4, c_char_p(not is_runtime))

    # Disable advanced mode if required
    # m.set_option(5, c_char_p(1))

    return m


def pyarmor_init(path=None, is_runtime=0, platid=None):
    global _pytransform
    _pytransform = _load_library(path, is_runtime, platid)
    return init_pytransform()


def pyarmor_runtime(path=None):
    try:
        pyarmor_init(path, is_runtime=1)
        init_runtime()
    except PytransformError as e:
        print(e)
        sys.exit(1)


#
# Not available from v5.6
#
def generate_capsule(licfile):
    prikey, pubkey, prolic = _generate_project_capsule()
    capkey, newkey = _generate_pytransform_key(licfile, pubkey)
    return prikey, pubkey, capkey, newkey, prolic


@dllmethod
def _generate_project_capsule():
    prototype = PYFUNCTYPE(py_object)
    dlfunc = prototype(('generate_project_capsule', _pytransform))
    return dlfunc()


@dllmethod
def _generate_pytransform_key(licfile, pubkey):
    prototype = PYFUNCTYPE(py_object, c_char_p, py_object)
    dlfunc = prototype(('generate_pytransform_key', _pytransform))
    return dlfunc(licfile.encode() if sys.version_info[0] == 3 else licfile,
                  pubkey)


#
# Deprecated functions from v5.1
#
@dllmethod
def encrypt_project_files(proname, filelist, mode=0):
    prototype = PYFUNCTYPE(c_int, c_char_p, py_object, c_int)
    dlfunc = prototype(('encrypt_project_files', _pytransform))
    return dlfunc(proname.encode(), filelist, mode)


def generate_project_capsule(licfile):
    prikey, pubkey, prolic = _generate_project_capsule()
    capkey = _encode_capsule_key_file(licfile)
    return prikey, pubkey, capkey, prolic


@dllmethod
def _encode_capsule_key_file(licfile):
    prototype = PYFUNCTYPE(py_object, c_char_p, c_char_p)
    dlfunc = prototype(('encode_capsule_key_file', _pytransform))
    return dlfunc(licfile.encode(), None)


@dllmethod
def encrypt_files(key, filelist, mode=0):
    t_key = c_char * 32
    prototype = PYFUNCTYPE(c_int, t_key, py_object, c_int)
    dlfunc = prototype(('encrypt_files', _pytransform))
    return dlfunc(t_key(*key), filelist, mode)


@dllmethod
def generate_module_key(pubname, key):
    t_key = c_char * 32
    prototype = PYFUNCTYPE(py_object, c_char_p, t_key, c_char_p)
    dlfunc = prototype(('generate_module_key', _pytransform))
    return dlfunc(pubname.encode(), t_key(*key), None)

#
# Compatible for PyArmor v3.0
#
@dllmethod
def old_init_runtime(systrace=0, sysprofile=1, threadtrace=0, threadprofile=1):
    '''Only for old version, before PyArmor 3'''
    pyarmor_init(is_runtime=1)
    prototype = PYFUNCTYPE(c_int, c_int, c_int, c_int, c_int)
    _init_runtime = prototype(('init_runtime', _pytransform))
    return _init_runtime(systrace, sysprofile, threadtrace, threadprofile)


@dllmethod
def import_module(modname, filename):
    '''Only for old version, before PyArmor 3'''
    prototype = PYFUNCTYPE(py_object, c_char_p, c_char_p)
    _import_module = prototype(('import_module', _pytransform))
    return _import_module(modname.encode(), filename.encode())


@dllmethod
def exec_file(filename):
    '''Only for old version, before PyArmor 3'''
    prototype = PYFUNCTYPE(c_int, c_char_p)
    _exec_file = prototype(('exec_file', _pytransform))
    return _exec_file(filename.encode())

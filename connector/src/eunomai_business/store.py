"""Per-user secret store for sign-in records.

Windows: a file in the user's local data folder, encrypted with DPAPI (CryptProtectData, user scope), so only
the same Windows user on the same machine can read it. The Credential Manager is not used: it caps each
credential at 2560 bytes, and OAuth token sets (Entra ID ones especially) are larger.
Elsewhere: the OS keyring.
"""

import hashlib
import json
import os
import sys

from . import data_dir

_SERVICE = "eunomai-business"


def _key(name: str) -> str:
    return hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]


if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    class _Blob(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]

    _crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    _crypt32.CryptProtectData.argtypes = [ctypes.POINTER(_Blob), wintypes.LPCWSTR, ctypes.POINTER(_Blob),
                                          ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptProtectData.restype = wintypes.BOOL
    _crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(_Blob), ctypes.c_void_p, ctypes.POINTER(_Blob),
                                            ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_Blob)]
    _crypt32.CryptUnprotectData.restype = wintypes.BOOL
    _kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    _kernel32.LocalFree.restype = ctypes.c_void_p
    _UI_FORBIDDEN = 0x1

    def _call(function, data: bytes, *extra) -> bytes:
        buffer = ctypes.create_string_buffer(data, len(data))
        blob_in = _Blob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
        blob_out = _Blob()
        if not function(ctypes.byref(blob_in), *extra, None, None, None, _UI_FORBIDDEN, ctypes.byref(blob_out)):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            return ctypes.string_at(blob_out.pbData, blob_out.cbData)
        finally:
            _kernel32.LocalFree(blob_out.pbData)

    def _path(name: str):
        return data_dir() / f"signin-{_key(name)}.dpapi"

    def save(name: str, record: dict) -> int:
        sealed = _call(_crypt32.CryptProtectData, json.dumps(record).encode("utf-8"), "eunomai sign-in")
        tmp = _path(name).with_suffix(".tmp")
        tmp.write_bytes(sealed)
        os.replace(tmp, _path(name))
        return len(sealed)

    def load(name: str) -> dict | None:
        path = _path(name)
        if not path.exists():
            return None
        return json.loads(_call(_crypt32.CryptUnprotectData, path.read_bytes(), None))

    def delete(name: str) -> bool:
        path = _path(name)
        if not path.exists():
            return False
        path.unlink()
        return True

    BACKEND = "dpapi-file"

else:
    import keyring

    def save(name: str, record: dict) -> int:
        raw = json.dumps(record)
        keyring.set_password(_SERVICE, _key(name), raw)
        return len(raw)

    def load(name: str) -> dict | None:
        raw = keyring.get_password(_SERVICE, _key(name))
        return json.loads(raw) if raw else None

    def delete(name: str) -> bool:
        try:
            keyring.delete_password(_SERVICE, _key(name))
            return True
        except keyring.errors.PasswordDeleteError:
            return False

    BACKEND = "keyring"

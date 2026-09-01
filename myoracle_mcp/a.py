from __future__ import annotations

import ctypes
import ctypes.wintypes

import oracledb


HOST = "rh-oracle.essencesecurity.com"
PORT = 1521
SID = "rh"
CREDENTIAL_TARGET = "OracleMCP/RH/SYS"


class _Credential(ctypes.Structure):
    _fields_ = [
        ("flags", ctypes.wintypes.DWORD),
        ("credential_type", ctypes.wintypes.DWORD),
        ("target_name", ctypes.wintypes.LPWSTR),
        ("comment", ctypes.wintypes.LPWSTR),
        ("last_written", ctypes.c_byte * 8),
        ("blob_size", ctypes.wintypes.DWORD),
        ("blob", ctypes.POINTER(ctypes.c_ubyte)),
        ("persist", ctypes.wintypes.DWORD),
        ("attribute_count", ctypes.wintypes.DWORD),
        ("attributes", ctypes.c_void_p),
        ("target_alias", ctypes.wintypes.LPWSTR),
        ("username", ctypes.wintypes.LPWSTR),
    ]


def read_password() -> str:
    credential_ptr = ctypes.POINTER(_Credential)()
    advapi32 = ctypes.windll.advapi32
    if not advapi32.CredReadW(
        CREDENTIAL_TARGET, 1, 0, ctypes.byref(credential_ptr)
    ):
        raise RuntimeError(
            f"Credential Manager entry not found: {CREDENTIAL_TARGET}"
        )
    try:
        credential = credential_ptr.contents
        blob = ctypes.string_at(credential.blob, credential.blob_size)
        return blob.decode("utf-16-le").rstrip("\x00")
    finally:
        advapi32.CredFree(credential_ptr)


def main() -> int:
    connection = None
    try:
        password = read_password()
        params = oracledb.ConnectParams(
            host=HOST,
            port=PORT,
            sid=SID,
            protocol="tcp",
        )
        connection = oracledb.connect(
            user="SYS",
            password=password,
            params=params,
            mode=oracledb.AUTH_MODE_SYSDBA,
        )
        print(f"Connected to RH ({HOST}:{PORT}/{SID})")
        return 0
    except Exception as exc:
        print(f"RH connection failed: {exc}")
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

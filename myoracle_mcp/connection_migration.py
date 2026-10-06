from __future__ import annotations

import base64
import ctypes
import io
import ctypes.wintypes
import hashlib
import re
import secrets
import shutil
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ElementTree

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MREMOTE_NAMESPACE = "http://mremoteng.org"
DEFAULT_MASTER_PASSWORD = b"mR3m"
BOOKMARK_PATTERN = re.compile(
    r"^([^=]+)=#(?P<kind>\d+)#\d+%(?P<host>[^%]+)%"
    r"(?P<port>\d+)%\[(?P<username>[^\]]*)\]"
)


class _Credential(ctypes.Structure):
    _fields_ = [
        ("Flags", ctypes.wintypes.DWORD),
        ("Type", ctypes.wintypes.DWORD),
        ("TargetName", ctypes.wintypes.LPWSTR),
        ("Comment", ctypes.wintypes.LPWSTR),
        ("LastWritten", ctypes.c_byte * 8),
        ("CredentialBlobSize", ctypes.wintypes.DWORD),
        ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist", ctypes.wintypes.DWORD),
        ("AttributeCount", ctypes.wintypes.DWORD),
        ("Attributes", ctypes.c_void_p),
        ("TargetAlias", ctypes.wintypes.LPWSTR),
        ("UserName", ctypes.wintypes.LPWSTR),
    ]


def _windows_credentials() -> list[dict[str, str]]:
    if not hasattr(ctypes, "windll"):
        return []
    advapi32 = ctypes.windll.advapi32
    credentials_ptr = ctypes.POINTER(ctypes.POINTER(_Credential))()
    count = ctypes.wintypes.DWORD()
    advapi32.CredEnumerateW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.wintypes.DWORD),
        ctypes.POINTER(ctypes.POINTER(ctypes.POINTER(_Credential))),
    ]
    advapi32.CredEnumerateW.restype = ctypes.wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    if not advapi32.CredEnumerateW(None, 0, ctypes.byref(count), ctypes.byref(credentials_ptr)):
        return []
    try:
        result: list[dict[str, str]] = []
        for index in range(count.value):
            credential = credentials_ptr[index].contents
            target = str(credential.TargetName or "")
            username = str(credential.UserName or "")
            result.append({"target": target, "username": username, "type": str(credential.Type)})
        return result
    finally:
        advapi32.CredFree(credentials_ptr)


def _read_windows_credential(target: str, credential_type: int) -> str:
    if not hasattr(ctypes, "windll"):
        raise RuntimeError("Windows Credential Manager is only available on Windows")
    advapi32 = ctypes.windll.advapi32
    credential_ptr = ctypes.POINTER(_Credential)()
    advapi32.CredReadW.argtypes = [
        ctypes.wintypes.LPCWSTR,
        ctypes.wintypes.DWORD,
        ctypes.wintypes.DWORD,
        ctypes.POINTER(ctypes.POINTER(_Credential)),
    ]
    advapi32.CredReadW.restype = ctypes.wintypes.BOOL
    advapi32.CredFree.argtypes = [ctypes.c_void_p]
    advapi32.CredFree.restype = None
    if not advapi32.CredReadW(target, credential_type, 0, ctypes.byref(credential_ptr)):
        raise ValueError(f"Credential target could not be read: {target}")
    try:
        credential = credential_ptr.contents
        blob = ctypes.string_at(credential.CredentialBlob, credential.CredentialBlobSize)
        try:
            return blob.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            return blob.decode("utf-8").rstrip("\x00")
    finally:
        advapi32.CredFree(credential_ptr)


def _write_connections(root: ElementTree.Element, destination: Path) -> None:
    """Write XML with the declaration mRemoteNG uses to recognize the file."""
    ElementTree.register_namespace("mrng", MREMOTE_NAMESPACE)
    buffer = io.BytesIO()
    ElementTree.ElementTree(root).write(buffer, encoding="utf-8", xml_declaration=True)
    text = buffer.getvalue().decode("utf-8")
    text = text.replace(
        "<?xml version='1.0' encoding='utf-8'?>",
        '<?xml version="1.0" encoding="utf-8"?>',
        1,
    )
    destination.write_text(text, encoding="utf-8")


def _encrypt_text(plaintext: str, password: bytes = DEFAULT_MASTER_PASSWORD) -> str:
    salt = secrets.token_bytes(16)
    nonce = secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha1", password, salt, 1000, 32)
    encrypted = AESGCM(key).encrypt(nonce, plaintext.encode("utf-8"), salt)
    return base64.b64encode(salt + nonce + encrypted).decode("ascii")


def _decrypt_text(value: str, password: bytes = DEFAULT_MASTER_PASSWORD) -> str:
    raw = base64.b64decode(value)
    salt, nonce, ciphertext = raw[:16], raw[16:32], raw[32:]
    key = hashlib.pbkdf2_hmac("sha1", password, salt, 1000, 32)
    return AESGCM(key).decrypt(nonce, ciphertext, salt).decode("utf-8")


def _encrypt_password(password: str) -> str:
    return _encrypt_text(password)


def _decrypt_marker(value: str) -> str:
    return _decrypt_text(value)


def _parse_bookmarks(source: Path) -> list[dict[str, str]]:
    in_bookmarks = False
    sessions: list[dict[str, str]] = []
    for raw_line in source.read_text(encoding="utf-8-sig", errors="replace").splitlines():
        line = raw_line.strip()
        if line == "[Bookmarks]":
            in_bookmarks = True
            continue
        if in_bookmarks and line.startswith("["):
            break
        if not in_bookmarks or "=" not in line:
            continue
        name, value = line.split("=", 1)
        if name.startswith("-") or name.isdigit() or not name.strip():
            continue
        match = BOOKMARK_PATTERN.match(f"{name}={value}")
        if not match:
            continue
        kind = match.group("kind")
        protocol = "RDP" if kind == "91" else "SSH2" if kind == "109" else ""
        if not protocol:
            continue
        sessions.append(
            {
                "name": name.strip(),
                "host": match.group("host").strip(),
                "port": match.group("port"),
                "username": match.group("username").strip(),
                "protocol": protocol,
            }
        )
    return sessions


def _credential_match(session: dict[str, str], credentials: list[dict[str, str]]) -> dict[str, str] | None:
    host = session["host"].lower()
    candidates = {host}
    if session["protocol"] == "RDP":
        candidates.update({f"TERMSRV/{host}", f"TERMSRV/{session['host']}"})
    for credential in credentials:
        target = credential["target"]
        if target.lower() in {candidate.lower() for candidate in candidates}:
            return credential
    return None


def _connection_attributes(session: dict[str, str]) -> dict[str, str]:
    username = session["username"]
    domain = ""
    if session["protocol"] == "RDP" and "@" in username:
        username, domain = username.rsplit("@", 1)
    attributes = {
        "Name": session["name"],
        "Type": "Connection",
        "Descr": "",
        "Icon": "mRemoteNG",
        "Panel": "General",
        "Id": str(uuid.uuid4()),
        "Username": username,
        "Domain": domain,
        "Password": "",
        "Hostname": session["host"],
        "Protocol": session["protocol"],
        "PuttySession": "Default Settings",
        "Port": session["port"],
        "ConnectToConsole": "false",
        "UseCredSsp": "true",
        "RenderingEngine": "IE",
        "ICAEncryptionStrength": "EncrBasic",
        "RDPAuthenticationLevel": "NoAuth",
        "RDPMinutesToIdleTimeout": "0",
        "RDPAlertIdleTimeout": "false",
        "LoadBalanceInfo": "",
        "Colors": "Colors16Bit",
        "Resolution": "FitToWindow",
        "AutomaticResize": "true",
        "DisplayWallpaper": "false",
        "DisplayThemes": "false",
        "EnableFontSmoothing": "false",
        "EnableDesktopComposition": "false",
        "CacheBitmaps": "false",
        "RedirectDiskDrives": "false",
        "RedirectPorts": "false",
        "RedirectPrinters": "false",
        "RedirectSmartCards": "false",
        "RedirectSound": "DoNotPlay",
        "SoundQuality": "Dynamic",
        "RedirectKeys": "false",
        "Connected": "false",
        "PreExtApp": "",
        "PostExtApp": "",
        "MacAddress": "",
        "UserField": "",
        "ExtApp": "",
        "VNCCompression": "CompNone",
        "VNCEncoding": "EncHextile",
        "VNCAuthMode": "AuthVNC",
        "VNCProxyType": "ProxyNone",
        "VNCProxyIP": "",
        "VNCProxyPort": "0",
        "VNCProxyUsername": "",
        "VNCProxyPassword": "",
        "VNCColors": "ColNormal",
        "VNCSmartSizeMode": "SmartSAspect",
        "VNCViewOnly": "false",
        "RDGatewayUsageMethod": "Never",
        "RDGatewayHostname": "",
        "RDGatewayUseConnectionCredentials": "Yes",
        "RDGatewayUsername": "",
        "RDGatewayPassword": "",
        "RDGatewayDomain": "",
    }
    attributes.update({key: "false" for key in (
        "InheritCacheBitmaps", "InheritColors", "InheritDescription", "InheritDisplayThemes",
        "InheritDisplayWallpaper", "InheritEnableFontSmoothing", "InheritEnableDesktopComposition",
        "InheritDomain", "InheritIcon", "InheritPanel", "InheritPassword", "InheritPort",
        "InheritProtocol", "InheritPuttySession", "InheritRedirectDiskDrives", "InheritRedirectKeys",
        "InheritRedirectPorts", "InheritRedirectPrinters", "InheritRedirectSmartCards",
        "InheritRedirectSound", "InheritSoundQuality", "InheritResolution", "InheritAutomaticResize",
        "InheritUseConsoleSession", "InheritUseCredSsp", "InheritRenderingEngine", "InheritUsername",
        "InheritICAEncryptionStrength", "InheritRDPAuthenticationLevel", "InheritRDPMinutesToIdleTimeout",
        "InheritRDPAlertIdleTimeout", "InheritLoadBalanceInfo", "InheritPreExtApp", "InheritPostExtApp",
        "InheritMacAddress", "InheritUserField", "InheritExtApp", "InheritVNCCompression",
        "InheritVNCEncoding", "InheritVNCAuthMode", "InheritVNCProxyType", "InheritVNCProxyIP",
        "InheritVNCProxyPort", "InheritVNCProxyUsername", "InheritVNCProxyPassword", "InheritVNCColors",
        "InheritVNCSmartSizeMode", "InheritVNCViewOnly", "InheritRDGatewayUsageMethod",
        "InheritRDGatewayHostname", "InheritRDGatewayUseConnectionCredentials", "InheritRDGatewayUsername",
        "InheritRDGatewayPassword", "InheritRDGatewayDomain",
    )})
    return attributes


def migrate_mobaxterm_to_mremoteng(
    source_path: str,
    destination_path: str,
    overwrite_existing: bool = False,
    remove_names: list[str] | None = None,
) -> dict[str, Any]:
    source = Path(source_path).expanduser()
    destination = Path(destination_path).expanduser()
    if not source.is_file():
        raise ValueError(f"MobaXterm configuration not found: {source}")
    if destination.exists() and destination.is_dir():
        raise ValueError(f"mRemoteNG destination is a directory: {destination}")

    sessions = _parse_bookmarks(source)
    if not sessions:
        raise ValueError(f"No supported SSH/RDP bookmarks found in {source}")
    if destination.exists():
        backup = destination.with_name(
            f"{destination.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        )
        shutil.copy2(destination, backup)
        root = ElementTree.parse(destination).getroot()
    else:
        backup = None
        root = ElementTree.Element(
            f"{{{MREMOTE_NAMESPACE}}}Connections",
            {
                "Name": "Connections",
                "Export": "false",
                "EncryptionEngine": "AES",
                "BlockCipherMode": "GCM",
                "KdfIterations": "1000",
                "FullFileEncryption": "false",
                "ConfVersion": "2.6",
            },
        )

    ElementTree.register_namespace("mrng", MREMOTE_NAMESPACE)
    removed: list[str] = []
    for unwanted in remove_names or []:
        for parent in list(root.iter()):
            for node in list(parent):
                if node.tag.rsplit("}", 1)[-1] == "Node" and node.attrib.get("Name") == unwanted:
                    parent.remove(node)
                    removed.append(unwanted)
    existing = {
        node.attrib.get("Name"): node
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "Node"
    }
    default_key_available = True
    protected = root.attrib.get("Protected", "")
    if protected:
        try:
            _decrypt_marker(protected)
        except Exception:
            default_key_available = False

    if not default_key_available or not protected:
        root.attrib["Protected"] = _encrypt_password("ThisIsNotProtected")
        root.attrib["FullFileEncryption"] = "false"
        default_key_available = True

    imported: list[dict[str, Any]] = []
    for session in sessions:
        attributes = _connection_attributes(session)
        node = existing.get(session["name"])
        if node is not None and not overwrite_existing:
            imported.append({"name": session["name"], "status": "skipped_existing", "password": "blank"})
            continue
        if node is None:
            node = ElementTree.SubElement(root, "Node")
        node.attrib.clear()
        node.attrib.update(attributes)
        imported.append(
            {
                "name": session["name"],
                "host": session["host"],
                "protocol": session["protocol"],
                "status": "imported",
                "password": "blank",
            }
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    _write_connections(root, destination)
    return {
        "source": str(source),
        "destination": str(destination),
        "backup": str(backup) if backup else None,
        "imported_count": sum(item["status"] == "imported" for item in imported),
        "skipped_count": sum(item["status"] == "skipped_existing" for item in imported),
        "removed_names": removed,
        "connections": imported,
        "note": "Connection passwords were left blank and the file uses mRemoteNG's default key, so startup does not ask for a password.",
    }


def set_mremoteng_file_password(destination_path: str, password: str) -> dict[str, Any]:
    """Protect an mRemoteNG connection file with a custom password."""
    if not password or not password.strip():
        raise ValueError("password must not be empty")
    destination = Path(destination_path).expanduser()
    if not destination.is_file():
        raise ValueError(f"mRemoteNG connection file not found: {destination}")

    backup = destination.with_name(
        f"{destination.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(destination, backup)
    ElementTree.register_namespace("mrng", MREMOTE_NAMESPACE)
    root = ElementTree.parse(destination).getroot()
    key = password.encode("utf-8")
    reencrypted = 0
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "Node":
            continue
        for field in ("Password", "VNCProxyPassword", "RDGatewayPassword"):
            current = node.attrib.get(field, "")
            if not current:
                continue
            try:
                plain = _decrypt_text(current)
            except Exception:
                plain = _decrypt_text(current, key)
            node.attrib[field] = _encrypt_text(plain, key)
            reencrypted += 1
    root.attrib["Protected"] = _encrypt_text("ThisIsProtected", key)
    root.attrib["FullFileEncryption"] = "false"
    _write_connections(root, destination)
    return {
        "destination": str(destination),
        "backup": str(backup),
        "password_set": True,
        "reencrypted_fields": reencrypted,
        "note": "mRemoteNG will ask for this password when it opens the connection file.",
    }


def _mobaxterm_key(session_p: bytes) -> bytearray:
    material = session_p
    while len(material) < 20:
        material += material
    key_space = [material.upper(), material.upper(), material.lower(), material.lower()]
    key = bytearray(b"0d5e9n1348/U2+67")
    alphabet = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz+/"
    for index in range(len(key)):
        candidate = key_space[(index + 1) % len(key_space)][index]
        if candidate not in key and candidate in alphabet:
            key[index] = candidate
    return key


def decrypt_mobaxterm_credential(ciphertext: str, session_p: str) -> str:
    """Decrypt one MobaXterm credential ciphertext stored under the C registry key."""
    key = _mobaxterm_key(session_p.encode("latin-1"))
    selected = bytearray(char for char in ciphertext.encode("ascii") if char in key)
    if len(selected) % 2:
        raise ValueError("Invalid MobaXterm ciphertext")
    plain = bytearray()
    for index in range(0, len(selected), 2):
        low = key.find(selected[index])
        key = key[-1:] + key[:-1]
        high = key.find(selected[index + 1])
        key = key[-1:] + key[:-1]
        if low < 0 or high < 0:
            raise ValueError("Invalid MobaXterm ciphertext")
        plain.append(16 * high + low)
    return plain.decode("latin-1")


def _dpapi_unprotect(data: bytes, entropy: bytes) -> bytes:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", ctypes.wintypes.DWORD), ("pbData", ctypes.c_void_p)]

    source = ctypes.create_string_buffer(data)
    entropy_buffer = ctypes.create_string_buffer(entropy)
    source_blob = DATA_BLOB(len(data), ctypes.cast(source, ctypes.c_void_p))
    entropy_blob = DATA_BLOB(len(entropy), ctypes.cast(entropy_buffer, ctypes.c_void_p))
    result = DATA_BLOB()
    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [
        ctypes.POINTER(DATA_BLOB), ctypes.c_void_p, ctypes.POINTER(DATA_BLOB),
        ctypes.c_void_p, ctypes.c_void_p, ctypes.wintypes.DWORD, ctypes.POINTER(DATA_BLOB),
    ]
    crypt32.CryptUnprotectData.restype = ctypes.wintypes.BOOL
    if not crypt32.CryptUnprotectData(
        ctypes.byref(source_blob), None, ctypes.byref(entropy_blob), None, None, 0, ctypes.byref(result)
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(result.pbData, result.cbData)
    finally:
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        kernel32.LocalFree(result.pbData)


def _decrypt_mobaxterm_aes(key: bytes, stored: str) -> str:
    if stored.startswith("_@"):
        iv = stored[2:18].encode("latin-1")
        ciphertext = base64.b64decode(stored, altchars=b"@_")[15:]
    else:
        ciphertext = base64.b64decode(stored, altchars=b"@_")
        iv = Cipher(algorithms.AES(key), modes.ECB()).encryptor().update(b"\x00" * 16)
    decryptor = Cipher(algorithms.AES(key), modes.CFB8(iv)).decryptor()
    return (decryptor.update(ciphertext) + decryptor.finalize()).decode("utf-8")


def _mobaxterm_aes_key() -> bytes:
    import os
    import platform
    import winreg

    header = bytes.fromhex("01000000d08c9ddf0115d1118c7a00c04fc297eb")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Mobatek\MobaXterm") as key:
        session_p, _ = winreg.QueryValueEx(key, "SessionP")
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Mobatek\MobaXterm\M") as key:
        expected = f"{os.getlogin()}@{platform.node()}"
        try:
            protected, _ = winreg.QueryValueEx(key, expected)
        except FileNotFoundError:
            _, protected, _ = winreg.EnumValue(key, 0)
    master_hash = _dpapi_unprotect(header + base64.b64decode(str(protected)), str(session_p).encode("utf-8"))
    return base64.b64decode(master_hash)[:32]


def _mobaxterm_credentials() -> dict[str, str]:
    import winreg

    key = _mobaxterm_aes_key()
    passwords: dict[str, str] = {}
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Mobatek\MobaXterm\C") as registry:
        index = 0
        while True:
            try:
                name, value, _ = winreg.EnumValue(registry, index)
            except OSError:
                break
            index += 1
            stored = str(value)
            if ":" not in stored:
                continue
            _, ciphertext = stored.split(":", 1)
            passwords[str(name).casefold()] = _decrypt_mobaxterm_aes(key, ciphertext)
    return passwords


def _connection_account_names(node: ElementTree.Element) -> list[str]:
    username = node.attrib.get("Username", "").strip()
    domain = node.attrib.get("Domain", "").strip()
    names = []
    if username and domain:
        names.append(f"{username}@{domain}")
    if username:
        names.append(username)
    return names


def restore_mobaxterm_passwords(destination_path: str, file_password: str) -> dict[str, Any]:
    """Copy MobaXterm saved account passwords into an existing mRemoteNG file."""
    if not file_password.strip():
        raise ValueError("file_password is required")
    destination = Path(destination_path).expanduser()
    if not destination.is_file():
        raise ValueError(f"mRemoteNG connection file not found: {destination}")
    root = ElementTree.parse(destination).getroot()
    key = file_password.encode("utf-8")
    marker = _decrypt_text(root.attrib.get("Protected", ""), key)
    if marker not in {"ThisIsProtected", "ThisIsNotProtected"}:
        raise ValueError("file_password does not open the mRemoteNG connection file")

    stored = _mobaxterm_credentials()
    backup = destination.with_name(
        f"{destination.name}.backup-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    )
    shutil.copy2(destination, backup)
    results = []
    for node in root.iter():
        if node.tag.rsplit("}", 1)[-1] != "Node" or node.attrib.get("Type") != "Connection":
            continue
        password = ""
        for account in _connection_account_names(node):
            password = stored.get(account.casefold(), "")
            if password:
                break
        if password:
            node.attrib["Password"] = _encrypt_text(password, key)
        results.append({"name": node.attrib.get("Name", ""), "password": "stored" if password else "missing"})
    _write_connections(root, destination)
    return {
        "destination": str(destination),
        "backup": str(backup),
        "stored_count": sum(item["password"] == "stored" for item in results),
        "missing_count": sum(item["password"] == "missing" for item in results),
        "connections": results,
    }

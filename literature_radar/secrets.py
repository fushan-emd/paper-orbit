"""Windows Credential Manager storage with verified legacy migration."""
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
from literature_radar.paths import workspace_root

SECRETS_PATH=workspace_root()/'data/secrets.json'

class Credential(ctypes.Structure):
    _fields_=[('Flags',wintypes.DWORD),('Type',wintypes.DWORD),('TargetName',wintypes.LPWSTR),
              ('Comment',wintypes.LPWSTR),('LastWritten',wintypes.FILETIME),('CredentialBlobSize',wintypes.DWORD),
              ('CredentialBlob',ctypes.POINTER(ctypes.c_ubyte)),('Persist',wintypes.DWORD),
              ('AttributeCount',wintypes.DWORD),('Attributes',ctypes.c_void_p),
              ('TargetAlias',wintypes.LPWSTR),('UserName',wintypes.LPWSTR)]

def _api():
    if os.name!='nt':raise RuntimeError('Credential storage requires Windows; use environment variables on other platforms.')
    api=ctypes.WinDLL('Advapi32.dll',use_last_error=True)
    api.CredReadW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))]
    api.CredWriteW.argtypes=[ctypes.POINTER(Credential),wintypes.DWORD]
    api.CredDeleteW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD]
    api.CredFree.argtypes=[ctypes.c_void_p]
    return api

def _target(name):
    scope=hashlib.sha256(str(SECRETS_PATH.parent.resolve()).encode()).hexdigest()[:16]
    return 'PaperOrbit:'+scope+':'+name

def _read(name):
    api=_api();pointer=ctypes.POINTER(Credential)()
    if not api.CredReadW(_target(name),1,0,ctypes.byref(pointer)):
        if ctypes.get_last_error()==1168:return ''
        raise OSError('Unable to read Windows credentials')
    try:return ctypes.string_at(pointer.contents.CredentialBlob,pointer.contents.CredentialBlobSize).decode('utf-8')
    finally:api.CredFree(pointer)

def save_secret(name,value):
    if not value:return
    raw=value.encode('utf-8')
    if len(raw)>2400:raise ValueError('Credential is too long')
    api=_api();blob=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
    item=Credential();item.Type=1;item.TargetName=_target(name);item.CredentialBlobSize=len(raw)
    item.CredentialBlob=blob;item.Persist=2;item.UserName='PaperOrbit'
    if not api.CredWriteW(ctypes.byref(item),0):raise OSError('Unable to save Windows credential')
    if _read(name)!=value:raise OSError('Credential verification failed')

def delete_secret(name):
    api=_api()
    if not api.CredDeleteW(_target(name),1,0) and ctypes.get_last_error()!=1168:
        raise OSError('Unable to delete Windows credential')
    if SECRETS_PATH.exists():
        data=load_secrets();data.pop(name,None);_write_legacy(SECRETS_PATH,data)

def load_secrets():
    if not SECRETS_PATH.exists():return {}
    data=json.loads(SECRETS_PATH.read_text(encoding='utf-8'))
    if not isinstance(data,dict):raise ValueError('Legacy credential file is invalid')
    return data

def _write_legacy(path,data):
    temp=path.with_suffix('.migrating');temp.write_text(json.dumps(data),encoding='utf-8');temp.replace(path)

def migrate_legacy(path=None):
    path=Path(path) if path else SECRETS_PATH
    if not path.exists():return
    data=json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data,dict):raise ValueError('Legacy credential file is invalid')
    for name,value in data.items():
        if value and not _read(name):save_secret(name,str(value))
    # All writes succeeded. Keep an empty marker rather than a plaintext backup.
    _write_legacy(path,{})

def get_secret(name):
    if os.environ.get(name):return os.environ[name]
    if os.name!='nt':return ''
    value=_read(name)
    if SECRETS_PATH.exists():
        migrate_legacy()
        value=_read(name)
    return value

def mask_secret(value):
    return 'configured' if value else 'not set'

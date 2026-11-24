"""Private token encryption. Never pass plaintext on a command line."""
import base64
import json
import os
import subprocess
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives import hashes

def _b64(v): return base64.b64encode(v).decode("ascii")
def _decode(v): return base64.b64decode(v,validate=True)

def _host(op,scope,raw):
    args=["/usr/bin/systemd-creds","--user","--name=kis-token-"+scope]
    if op=="encrypt":args.append("--with-key=host")
    try:
        p=subprocess.run(args+[op,"-","-"],input=raw,capture_output=True,timeout=10)
        if p.returncode or not p.stdout or len(p.stdout)>65536:raise ValueError()
        return p.stdout
    except (OSError,ValueError,subprocess.TimeoutExpired):
        raise ValueError("KIS host cache crypto failed") from None

def _key(secret,scope,salt):
    if not secret:raise ValueError("Missing cache key")
    return HKDF(algorithm=hashes.SHA256(),length=32,salt=salt,
                info=("kis-token-cache-v2:"+scope).encode()).derive(secret.encode())

def seal(obj,secret,scope,mode):
    raw=json.dumps(obj,separators=(",",":")).encode()
    if mode=="systemd-host-v1":
        return {"v":2,"scheme":mode,"blob":_b64(_host("encrypt",scope,raw))}
    salt,nonce=os.urandom(16),os.urandom(12)
    blob=AESGCM(_key(secret,scope,salt)).encrypt(nonce,raw,scope.encode())
    return {"v":2,"scheme":"aes-gcm-v1","salt":_b64(salt),"nonce":_b64(nonce),"blob":_b64(blob)}

def unseal(obj,secret,scope,mode):
    try:
        if "v" not in obj and isinstance(obj.get("token"),str):
            return obj,"legacy-plaintext"
        if obj.get("v")!=2:raise ValueError()
        if obj.get("scheme")=="systemd-host-v1":
            if mode!=obj["scheme"]:raise ValueError()
            raw=_host("decrypt",scope,_decode(obj["blob"]))
        elif obj.get("scheme")=="aes-gcm-v1":
            raw=AESGCM(_key(secret,scope,_decode(obj["salt"]))).decrypt(_decode(obj["nonce"]),_decode(obj["blob"]),scope.encode())
        else:raise ValueError()
        return json.loads(raw),obj["scheme"]
    except Exception:
        raise ValueError("KIS cache decrypt failed") from None

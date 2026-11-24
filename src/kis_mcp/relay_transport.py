"""TLS verification and SNI remain end-to-end over a fixed Unix socket."""
import http.client
import os
from pathlib import Path
import socket
import ssl
import stat
from urllib.parse import urlsplit

ORIGIN=("https","openapi.koreainvestment.com:9443")
LIMIT=3_000_000

class UnixHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self,host,port,path):
        super().__init__(host,port,timeout=12,context=ssl.create_default_context())
        self.path=path
    def connect(self):
        s=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
        try:
            s.settimeout(self.timeout)
            s.connect(self.path)
            self.sock=self._context.wrap_socket(s,server_hostname=self.host)
        except Exception:
            s.close()
            raise

def relay_request(url,method,headers,payload,path):
    u=urlsplit(url)
    if (u.scheme,u.netloc)!=ORIGIN or u.fragment or method not in ("GET","HEAD","POST"):
        raise ValueError("KIS relay destination denied")
    st=Path(path).lstat();parent=Path(path).parent.lstat()
    if not stat.S_ISSOCK(st.st_mode) or st.st_uid!=os.getuid() or st.st_mode&0o077 or not stat.S_ISDIR(parent.st_mode) or parent.st_uid!=os.getuid() or parent.st_mode&0o077:
        raise ValueError("KIS relay socket invalid")
    c=UnixHTTPSConnection(u.hostname,u.port,path)
    try:
        c.request(method,u.path+("?" + u.query if u.query else ""),body=payload,headers=headers)
        r=c.getresponse()
        body=r.read(LIMIT+1)
        if len(body)>LIMIT:raise ValueError("KIS relay response limit")
        return r.status,dict(r.getheaders()),body
    finally:c.close()

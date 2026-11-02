"""Bounded length-framed local IPC. EOF means disconnect, never end of a frame."""
from pathlib import Path
import hashlib,json,struct,socket
from p11_contract import RELEASE_ID
_SOURCE_SHA256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
MAX_HEADER=16384
FRAME_BYTES=480*640*3


def connect_address(address):
    if address.startswith('tcp:'):
        host,port=address[4:].rsplit(':',1)
        if host!='127.0.0.1':raise ValueError('AI TCP fallback is loopback only')
        connection=socket.socket(socket.AF_INET,socket.SOCK_STREAM);target=(host,int(port))
    else:
        connection=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);target=address
    try:
        connection.settimeout(10.);connection.connect(target);connection.settimeout(None)
        return connection
    except BaseException:connection.close();raise


def recv_exact(sock,count):
    result=bytearray(count);view=memoryview(result);offset=0
    while offset<count:
        used=sock.recv_into(view[offset:],count-offset)
        if not used:raise EOFError('AI connection closed during a message')
        offset+=used
    return bytes(result)


def send_message(sock,metadata,payload=b''):
    if len(payload)>FRAME_BYTES:raise ValueError('AI payload too large')
    value=dict(metadata,payload_bytes=len(payload))
    header=json.dumps(value,allow_nan=False,separators=(',',':')).encode('utf-8')
    if len(header)>MAX_HEADER:raise ValueError('AI header too large')
    sock.sendall(struct.pack('!I',len(header))+header)
    if payload:sock.sendall(payload)


def recv_message(sock):
    length=struct.unpack('!I',recv_exact(sock,4))[0]
    if not 1<=length<=MAX_HEADER:raise ValueError('Invalid AI header size')
    value=json.loads(recv_exact(sock,length))
    if not isinstance(value,dict):raise ValueError('AI metadata must be an object')
    count=value.pop('payload_bytes',0)
    if type(count) is not int or not 0<=count<=FRAME_BYTES:raise ValueError('Invalid AI payload size')
    return value,recv_exact(sock,count) if count else b''

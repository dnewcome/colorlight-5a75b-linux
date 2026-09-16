import socket,time
from collections import Counter
s=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); s.bind(("eno1",0)); s.settimeout(1)
c=Counter(); t=time.time()
while time.time()-t<4:
    try:p=s.recv(4096)
    except socket.timeout:continue
    if len(p)>=13 and p[6:12]==bytes.fromhex("222233445566"): c[p[12]]+=1
print("LEDVISION frames in 4s:", {hex(k):v for k,v in sorted(c.items())} or "NONE")

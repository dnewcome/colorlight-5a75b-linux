import socket, time, threading
IF="eno1"
disc=open("config/ledvision_discovery.bin","rb").read()
tx=socket.socket(socket.AF_PACKET,socket.SOCK_RAW); tx.bind((IF,0))
rx=socket.socket(socket.AF_PACKET,socket.SOCK_RAW,socket.htons(3)); rx.bind((IF,0)); rx.settimeout(0.3)
SELF_TX=disc[6:12]  # 22:22:33:44:55:66
allframes=[]; stop=False
def listen():
    t=time.time()
    while not stop and time.time()-t<25:
        try: p=rx.recv(65535)
        except socket.timeout: continue
        if len(p)<14: continue
        allframes.append(bytes(p))
        et=int.from_bytes(p[12:14],"big")
        src=p[6:12]
        # report ANYTHING that isn't our own TX and isn't ordinary IP/ARP/IPv6
        if src!=SELF_TX and et not in (0x0800,0x86dd,0x0806):
            print(f"  <== FROM CARD? src={src.hex(':')} dst={p[0:6].hex(':')} type=0x{et:04x} len={len(p)} {p[12:52].hex(' ')}",flush=True)
th=threading.Thread(target=listen,daemon=True); th.start()
print("replaying LEDVISION's exact discovery on direct link, 20x over 10s. WATCH THE CARD LED.",flush=True)
sent=0
for i in range(20):
    tx.send(disc); sent+=1
    time.sleep(0.5)
time.sleep(3); stop=True; time.sleep(0.5)
# verify our own TX egressed by counting our discovery frames seen on rx
mine=sum(1 for p in allframes if p[6:12]==SELF_TX and p[12]==0x07)
oursrc=set(p[6:12].hex(':') for p in allframes)
print(f"=== sent {sent} probes; saw {mine} of our own 0x07 on the wire (confirms egress) ===",flush=True)
print("all source MACs seen on the wire during test:",oursrc,flush=True)

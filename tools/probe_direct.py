import sys, time, threading; sys.path.insert(0,'.'); import cl5a75 as c
snd = c.Sender("eno1", 64, 64, 255)
import socket
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind(("eno1",0)); rx.settimeout(0.3)
OURS = {bytes.fromhex("112233445566"), bytes.fromhex("222233445566")}
stop=False; got=[]
def listen():
    t=time.time()
    while not stop and time.time()-t<20:
        try: p=rx.recv(65535)
        except socket.timeout: continue
        if len(p)<14: continue
        et=int.from_bytes(p[12:14],"big")
        # anything not from us and not plain IP/ARP noise -> report
        if p[6:12] not in OURS and et not in (0x0800,0x86dd,0x0806):
            print(f"REPLY? src={p[6:12].hex(':')} dst={p[0:6].hex(':')} type=0x{et:04x} len={len(p)} {p[12:48].hex(' ')}",flush=True)
            got.append(p)
th=threading.Thread(target=listen,daemon=True); th.start()
print("sending discovery probes (0x07) on direct link, listening for 0x08 reply...",flush=True)
for r in range(16):
    d=bytearray(271); d[3]=r; d[16]=r  # try both index fields seen in FPP/LEDVISION
    snd.sock.send(c.frame(0x07, bytes(d), 284))
    time.sleep(0.25)
# also send a brightness+sync in case the card needs to be 'active' first, then probe again
snd.send_raw_frames(c.load_config_blob("config/config_64x64.bin"))
for r in range(8):
    d=bytearray(271); d[3]=r
    snd.sock.send(c.frame(0x07, bytes(d), 284)); time.sleep(0.25)
time.sleep(3); stop=True; time.sleep(0.5)
print(f"=== done. replies captured: {len(got)} ===",flush=True)

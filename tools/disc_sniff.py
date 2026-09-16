import socket, threading, time, collections, sys
IFACE = sys.argv[1] if len(sys.argv) > 1 else "eno1"
DST = bytes.fromhex("112233445566"); SRC = bytes.fromhex("222233445566")
def pkt(idx):
    d = bytearray(271); d[3] = idx
    p = DST + SRC + bytes([0x07]) + bytes(d)
    if len(p) < 284: p += bytes(284 - len(p))
    return p
tx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW); tx.bind((IFACE, 0))
rx = socket.socket(socket.AF_PACKET, socket.SOCK_RAW, socket.htons(3)); rx.bind((IFACE, 0)); rx.settimeout(0.2)
# promiscuous: the reply is addressed to our made-up SRC mac, not the NIC's real one
import struct as _st
ifindex = socket.if_nametoindex(IFACE)
PACKET_ADD_MEMBERSHIP = 1; PACKET_MR_PROMISC = 1; SOL_PACKET = 263
mreq = _st.pack("IHH8s", ifindex, PACKET_MR_PROMISC, 0, b"")
rx.setsockopt(SOL_PACKET, PACKET_ADD_MEMBERSHIP, mreq)
stop = False; seen = collections.Counter(); samples = {}
def sniff():
    while not stop:
        try: p = rx.recv(2048)
        except socket.timeout: continue
        if len(p) < 14:
            continue
        # count every non-self frame by its ethertype field (bytes 12-13)
        if p[0:6] != SRC:  # skip our own echoed probes
            et = (p[12] << 8) | p[13]
            seen[hex(et)] += 1
        # a real Colorlight 0x08 reply from a 5A card => ethertype field 0x0805
        if p[12] == 0x08 and p[13] == 0x05:
            k = "CL_REPLY"
            seen[k] += 1
            if k not in samples:
                samples[k] = (len(p), "dst=" + p[0:6].hex(":") + " src=" + p[6:12].hex(":"),
                              p[:80].hex(" "))
t = threading.Thread(target=sniff); t.start()
t0 = time.time()
while time.time() - t0 < 5:
    for i in range(8): tx.send(pkt(i))
    time.sleep(0.1)
stop = True; t.join()
print("inbound frames by ethertype:", dict(seen))
for k, v in samples.items(): print(k, v)

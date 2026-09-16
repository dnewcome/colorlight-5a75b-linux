import sys, time; sys.path.insert(0,'.'); import cl5a75 as c
snd=c.Sender("eno1",256,64,255,dup=False)
for fr in c.load_config_blob("config/config_64x64.bin"): snd.sock.send(fr); time.sleep(0.002)
dur=float(sys.argv[1]) if len(sys.argv)>1 else 120
cols=[("RED",255,0,0),("GREEN",0,255,0),("BLUE",0,0,255),("WHITE",255,255,255)]
t=time.time(); i=0
while time.time()-t<dur:
    n,r,g,b=cols[i%4]; i+=1; fb=c.fb_solid(256,64,r,g,b)
    print("COLOR:",n,flush=True)
    e=time.time()+5
    while time.time()<e: snd.show(fb); time.sleep(1/30)

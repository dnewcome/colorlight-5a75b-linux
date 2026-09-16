import sys, time; sys.path.insert(0,'.'); import cl5a75 as c
snd=c.Sender("eno1",256,256,255,dup=False)
for fr in c.load_config_blob("config/config_64x64.bin"): snd.sock.send(fr); time.sleep(0.002)
cols=[("RED",255,0,0),("GREEN",0,255,0),("BLUE",0,0,255)]
t=time.time(); i=0
while time.time()-t<300:
    n,r,g,b=cols[i%3]; i+=1; fb=c.fb_solid(256,256,r,g,b); print("SENDING:",n,flush=True)
    e=time.time()+8
    while time.time()<e: snd.show(fb); time.sleep(1/20)

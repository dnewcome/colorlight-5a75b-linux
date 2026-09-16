import sys, time; sys.path.insert(0, "."); import cl5a75 as c
W, H = 256, 64
snd = c.Sender("eno1", W, H, 255, dup=True)
t_end = time.time() + float(sys.argv[1])
cols = [(255,0,0),(0,255,0),(0,0,255),(255,255,255)]
i = 0
while time.time() < t_end:
    fb = c.fb_solid(W, H, *cols[i % 4]); i += 1
    for _ in range(90):
        snd.show(fb); time.sleep(1/30)
snd.show(c.fb_solid(W, H, 0, 0, 0))

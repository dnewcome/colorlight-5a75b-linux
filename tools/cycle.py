import sys, time; sys.path.insert(0, "."); import cl5a75 as c
snd = c.Sender("eno1", 64, 32, 255, dup=True)
t_end = time.time() + float(sys.argv[1])
cols = [(255,0,0),(0,255,0),(0,0,255),(255,255,255)]
i = 0
while time.time() < t_end:
    fb = c.fb_solid(64, 32, *cols[i % 4]); i += 1
    for _ in range(30):
        snd.show(fb); time.sleep(1/30)
    if i % 4 == 0: snd.discover(0.2)
snd.show(c.fb_solid(64, 32, 0, 0, 0))

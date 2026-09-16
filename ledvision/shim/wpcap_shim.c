/* wpcap.dll shim for Colorlight LEDVISION under Wine.
 *
 * Wine's builtin wpcap.dll wraps libpcap, but LEDVISION's network layer (CLTNic.dll)
 * depends on WinPcap *internals*:
 *   - it calls the WinPcap-only send-queue API (Wine only stubs it -> abort), and
 *   - worse, it reads pcap_t->adapter->hFile (WinPcap's private ADAPTER struct) and
 *     transmits with DeviceIoControl(hFile, BIOCSENDPACKETS{NO,}SYNC, ...) straight to
 *     the NPF driver, bypassing wpcap entirely.  Under Wine that reads garbage -> crash.
 *
 * This DLL is loaded instead of the builtin (it lives in the app dir; DllOverride
 * wpcap=native,builtin).  It loads the builtin from the system dir and:
 *   - pcap_open/pcap_open_live return a FAKE pcap_t laid out like WinPcap's
 *     (first field = ADAPTER*), pointing at a fake ADAPTER whose hFile is a unique
 *     handle; every pcap_* call translates fake -> real before forwarding;
 *   - hooks DeviceIoControl in CLTNic.dll's (and the exe's) import table: NPF send
 *     ioctls on a fake hFile become a loop of pcap_sendpacket on the real handle;
 *   - implements pcap_sendqueue_* on top of pcap_sendpacket;
 *   - forwards every other export to the builtin untouched.
 * Log: C:\wpcap-shim.log
 */
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

typedef struct { unsigned int maxlen; unsigned int len; char *buffer; } pcap_send_queue;
struct win_timeval { long tv_sec; long tv_usec; };
struct win_pkthdr { struct win_timeval ts; unsigned int caplen; unsigned int len; };

/* WinPcap 4.1.3 ADAPTER layout (Packet32.h); only hFile/ReadEvent/Flags matter */
struct fake_adapter {
    HANDLE hFile;                 /* 0x000 */
    char   SymbolicLink[64];      /* 0x004 */
    int    NumWrites;             /* 0x044 */
    HANDLE ReadEvent;             /* 0x048 */
    UINT   ReadTimeOut;           /* 0x04c */
    char   Name[256];             /* 0x050 */
    void  *pWanAdapter;           /* 0x150 */
    UINT   Flags;                 /* 0x154 */
    char   pad[0x200];            /* covers +0x160 (checked by CLTNic) and beyond */
};
struct fake_pcap {
    struct fake_adapter *adapter; /* +0: what CLTNic reads */
    void *real;                   /* Wine's real pcap_t */
    unsigned int magic;
    char pad[0x400];
};
#define MAGIC 0x50434150
#define MAXF 32
static struct fake_pcap *fakes[MAXF];

#define BIOCSENDPACKETSNOSYNC 0x2348
#define BIOCSENDPACKETSSYNC   0x2349

static HMODULE builtin;
static FILE *logf;
static void shimlog(const char *fmt, ...)
{
    va_list ap; SYSTEMTIME t;
    if (!logf) return;
    GetLocalTime(&t); fprintf(logf, "%02d:%02d:%02d.%03d ", t.wHour, t.wMinute, t.wSecond, t.wMilliseconds);
    va_start(ap, fmt); vfprintf(logf, fmt, ap); va_end(ap);
    fputc('\n', logf); fflush(logf);
}

/* ---- real function pointers (cdecl) ---- */
static void *(*r_pcap_open)(const char*, int, int, int, void*, char*);
static void *(*r_pcap_open_live)(const char*, int, int, int, char*);
static void  (*r_pcap_close)(void*);
static int   (*r_pcap_compile)(void*, void*, const char*, int, unsigned);
static int   (*r_pcap_setfilter)(void*, void*);
static int   (*r_pcap_setbuff)(void*, int);
static int   (*r_pcap_next_ex)(void*, struct win_pkthdr**, const unsigned char**);
static const unsigned char *(*r_pcap_next)(void*, struct win_pkthdr*);
static int   (*r_pcap_sendpacket)(void*, const unsigned char*, int);
static char *(*r_pcap_geterr)(void*);
static int   (*r_pcap_datalink)(void*);
static int   (*r_pcap_setnonblock)(void*, int, char*);
static int   (*r_pcap_getnonblock)(void*, char*);
static int   (*r_pcap_setmintocopy)(void*, int);
static int   (*r_pcap_stats)(void*, void*);
static int   (*r_pcap_snapshot)(void*);
static int   (*r_pcap_fileno)(void*);
static int   (*r_pcap_setmode)(void*, int);
static void  (*r_pcap_breakloop)(void*);
static int   (*r_pcap_loop)(void*, int, void*, unsigned char*);
static int   (*r_pcap_dispatch)(void*, int, void*, unsigned char*);
static void  (*r_pcap_perror)(void*, const char*);
static int   (*r_pcap_setuserbuffer)(void*, int);
static int   (*r_pcap_set_datalink)(void*, int);
static int   (*r_pcap_setdirection)(void*, int);

static struct fake_pcap *find_fake(void *p)
{
    int i; for (i = 0; i < MAXF; i++) if (fakes[i] && fakes[i] == p) return fakes[i];
    return NULL;
}
static void *real_of(void *p)
{
    struct fake_pcap *f = find_fake(p);
    return f ? f->real : p;
}
static struct fake_pcap *fake_by_hfile(HANDLE h)
{
    int i; for (i = 0; i < MAXF; i++) if (fakes[i] && fakes[i]->adapter->hFile == h) return fakes[i];
    return NULL;
}

static DWORD WINAPI tick_thread(LPVOID arg)
{
    /* CLTNic may wait on adapter->ReadEvent before polling; keep it pulsing so it polls */
    struct fake_pcap *f = arg;
    while (f->magic == MAGIC) { SetEvent(f->adapter->ReadEvent); Sleep(10); }
    return 0;
}

static void *make_fake(void *real, const char *name)
{
    int i; struct fake_pcap *f; struct fake_adapter *a; HANDLE th;
    if (!real) return NULL;
    f = calloc(1, sizeof(*f)); a = calloc(1, sizeof(*a));
    if (!f || !a) { free(f); free(a); return real; }
    a->hFile = CreateEventW(NULL, TRUE, FALSE, NULL);   /* any unique, valid handle */
    a->ReadEvent = CreateEventW(NULL, FALSE, FALSE, NULL);
    a->ReadTimeOut = 1;
    lstrcpynA(a->Name, name ? name : "", sizeof(a->Name));
    f->adapter = a; f->real = real; f->magic = MAGIC;
    for (i = 0; i < MAXF; i++) if (!fakes[i]) { fakes[i] = f; break; }
    th = CreateThread(NULL, 0, tick_thread, f, 0, NULL); if (th) CloseHandle(th);
    shimlog("fake pcap %p -> real %p (adapter %p hFile %p) for %s", f, real, a, a->hFile, name ? name : "?");
    return f;
}

/* ---- forged Colorlight discovery reply (0x08) ----
 * The 5A-75B on Dan's bench never answers discovery (0x07), so LEDVISION says
 * "no receiver connected" and refuses to write config.  When we see a 0x07 probe
 * leave, we hand LEDVISION a synthetic 0x08 reply on the next pcap_next_ex so it
 * believes a 64x64 receiver is present and sends the real config to the card.
 * Layout per Falcon Player ColorLight-5a-75.cpp GetReceiverInfo():
 *   src MAC 11:22:33:44:55:66, type byte @12 = 0x08, packet >1000 bytes,
 *   data=(pkt+13): [0]=0x05 (5A), [2]=fwMajor, [3]=fwMinor,
 *   [21..22]=width, [23..24]=height, [85]=receiver id. */
static volatile LONG discovery_pending;
#define RESP_SIZE 1070
static unsigned char forged_reply[RESP_SIZE];
static struct win_pkthdr forged_hdr;
static void build_forged_reply(unsigned char rx_id, int w, int h)
{
    unsigned char *d;
    memset(forged_reply, 0, sizeof(forged_reply));
    memset(forged_reply, 0xFF, 6);                       /* dst broadcast */
    { unsigned char src[6] = {0x11,0x22,0x33,0x44,0x55,0x66}; memcpy(forged_reply + 6, src, 6); }
    forged_reply[12] = 0x08;                             /* CL_RESP_PACKET_TYPE */
    d = forged_reply + 13;
    d[0]  = 0x05;                                        /* 5A card */
    d[2]  = 10; d[3] = 16;                               /* fw v10.16 */
    d[21] = (w >> 8) & 0xFF; d[22] = w & 0xFF;           /* width  */
    d[23] = (h >> 8) & 0xFF; d[24] = h & 0xFF;           /* height */
    d[85] = rx_id;                                       /* receiver id */
    forged_hdr.ts.tv_sec = 0; forged_hdr.ts.tv_usec = 0;
    forged_hdr.caplen = RESP_SIZE; forged_hdr.len = RESP_SIZE;
}

/* Load the card's GENUINE discovery reply (captured out-of-band) so LEDVISION detects
 * the real card. Needed because Wine's wow64 pcap receive hands back a dangling data
 * pointer for real captured frames; we sidestep it by injecting the real bytes. */
static int load_real_reply(void)
{
    FILE *f = fopen("C:\\real_reply.bin", "rb");
    size_t n;
    if (!f) return 0;
    n = fread(forged_reply, 1, RESP_SIZE, f);
    fclose(f);
    if (n < 60) return 0;
    forged_hdr.ts.tv_sec = 0; forged_hdr.ts.tv_usec = 0;
    forged_hdr.caplen = (unsigned)n; forged_hdr.len = (unsigned)n;
    return 1;
}

/* ---- explicit wrappers ---- */
__declspec(dllexport) void *pcap_open(const char *src, int snaplen, int flags, int to_ms, void *auth, char *err)
{
    void *r = r_pcap_open(src, snaplen, flags, to_ms, auth, err);
    shimlog("pcap_open(%s, snap %d, flags %d, to %d) -> %p %s", src, snaplen, flags, to_ms, r, r ? "" : (err ? err : ""));
    return make_fake(r, src);
}
__declspec(dllexport) void *pcap_open_live(const char *dev, int snaplen, int promisc, int to_ms, char *err)
{
    void *r = r_pcap_open_live(dev, snaplen, promisc, to_ms, err);
    shimlog("pcap_open_live(%s) -> %p", dev, r);
    return make_fake(r, dev);
}
__declspec(dllexport) void pcap_close(void *p)
{
    struct fake_pcap *f = find_fake(p); int i;
    shimlog("pcap_close(%p)", p);
    if (f) {
        r_pcap_close(f->real);
        f->magic = 0; Sleep(30);
        CloseHandle(f->adapter->hFile); CloseHandle(f->adapter->ReadEvent);
        for (i = 0; i < MAXF; i++) if (fakes[i] == f) fakes[i] = NULL;
        free(f->adapter); free(f);
    } else r_pcap_close(p);
}
__declspec(dllexport) int pcap_compile(void *p, void *prog, const char *s, int opt, unsigned mask)
{ int r = r_pcap_compile(real_of(p), prog, s, opt, mask); shimlog("pcap_compile(\"%s\") -> %d", s, r); return r; }
__declspec(dllexport) int pcap_setfilter(void *p, void *prog) { return r_pcap_setfilter(real_of(p), prog); }
__declspec(dllexport) int pcap_setbuff(void *p, int dim) { return r_pcap_setbuff(real_of(p), dim); }
/* Stable-copy receive: Wine's returned packet pointer can go stale before the caller
 * (CLTNic) dereferences it -> crash on the real card reply. Copy each packet into our
 * own persistent buffers and hand those back, so the pointer stays valid. */
static struct win_pkthdr stable_hdr;
static unsigned char stable_data[70000];
__declspec(dllexport) int pcap_next_ex(void *p, struct win_pkthdr **h, const unsigned char **d)
{
    struct win_pkthdr *rh = NULL; const unsigned char *rd = NULL; int r;
    if (InterlockedCompareExchange(&discovery_pending, 0, 1) == 1) {
        if (h) *h = &forged_hdr;
        if (d) *d = forged_reply;
        shimlog("injected forged 0x08 discovery reply (%d bytes)", RESP_SIZE);
        return 1;
    }
    r = r_pcap_next_ex(real_of(p), &rh, &rd);
    if (r == 1) {
        static int logged;
        unsigned int cl = 0;
        const unsigned int *w = (const unsigned int *)rh;
        if (rh && !IsBadReadPtr(rh, 24)) {
            if (logged < 8) { shimlog("rx hdr words: %08x %08x %08x %08x %08x %08x  rd=%p",
                w[0],w[1],w[2],w[3],w[4],w[5], rd); logged++; }
            /* caplen is at offset 8 (WinPcap 32-bit ts) or 16 (64-bit ts); pick a sane one */
            if (w[2] >= 14 && w[2] <= 65535) cl = w[2];
            else if (w[4] >= 14 && w[4] <= 65535) cl = w[4];
        }
        if (cl > sizeof(stable_data)) cl = sizeof(stable_data);
        if (cl && rd && !IsBadReadPtr(rd, cl)) {
            memcpy(stable_data, rd, cl);
            stable_hdr.ts.tv_sec = 0; stable_hdr.ts.tv_usec = 0;
            stable_hdr.caplen = cl; stable_hdr.len = cl;
            if (h) *h = &stable_hdr;
            if (d) *d = stable_data;
            return 1;
        }
        if (logged < 12) { shimlog("rx: unsafe pkt (cl=%u rd=%p) -> reporting no-packet", cl, rd); logged++; }
        return 0;   /* can't trust it; tell caller no packet rather than crash */
    }
    if (h) *h = rh;
    if (d) *d = rd;
    return r;
}
__declspec(dllexport) const unsigned char *pcap_next(void *p, struct win_pkthdr *h) { return r_pcap_next(real_of(p), h); }
__declspec(dllexport) int pcap_sendpacket(void *p, const unsigned char *buf, int size) { return r_pcap_sendpacket(real_of(p), buf, size); }
__declspec(dllexport) char *pcap_geterr(void *p) { return r_pcap_geterr(real_of(p)); }
__declspec(dllexport) int pcap_datalink(void *p) { return r_pcap_datalink(real_of(p)); }
__declspec(dllexport) int pcap_setnonblock(void *p, int nb, char *e) { return r_pcap_setnonblock(real_of(p), nb, e); }
__declspec(dllexport) int pcap_getnonblock(void *p, char *e) { return r_pcap_getnonblock(real_of(p), e); }
__declspec(dllexport) int pcap_setmintocopy(void *p, int s) { return r_pcap_setmintocopy(real_of(p), s); }
__declspec(dllexport) HANDLE pcap_getevent(void *p)
{ struct fake_pcap *f = find_fake(p); shimlog("pcap_getevent(%p)", p); return f ? f->adapter->ReadEvent : NULL; }
__declspec(dllexport) int pcap_stats(void *p, void *ps) { return r_pcap_stats(real_of(p), ps); }
__declspec(dllexport) int pcap_snapshot(void *p) { return r_pcap_snapshot(real_of(p)); }
__declspec(dllexport) int pcap_fileno(void *p) { return r_pcap_fileno(real_of(p)); }
__declspec(dllexport) int pcap_setmode(void *p, int m) { return r_pcap_setmode(real_of(p), m); }
__declspec(dllexport) void pcap_breakloop(void *p) { r_pcap_breakloop(real_of(p)); }
__declspec(dllexport) int pcap_loop(void *p, int c, void *cb, unsigned char *u) { return r_pcap_loop(real_of(p), c, cb, u); }
__declspec(dllexport) int pcap_dispatch(void *p, int c, void *cb, unsigned char *u) { return r_pcap_dispatch(real_of(p), c, cb, u); }
__declspec(dllexport) void pcap_perror(void *p, const char *s) { r_pcap_perror(real_of(p), s); }
__declspec(dllexport) int pcap_setuserbuffer(void *p, int s) { return r_pcap_setuserbuffer(real_of(p), s); }
__declspec(dllexport) int pcap_set_datalink(void *p, int d) { return r_pcap_set_datalink(real_of(p), d); }
__declspec(dllexport) int pcap_setdirection(void *p, int d) { return r_pcap_setdirection(real_of(p), d); }

/* ---- send queue ---- */
__declspec(dllexport) pcap_send_queue *pcap_sendqueue_alloc(unsigned int memsize)
{
    pcap_send_queue *q = calloc(1, sizeof(*q));
    if (!q) return NULL;
    q->buffer = malloc(memsize ? memsize : 1);
    if (!q->buffer) { free(q); return NULL; }
    q->maxlen = memsize; q->len = 0;
    shimlog("sendqueue_alloc(%u) -> %p", memsize, q);
    return q;
}
__declspec(dllexport) void pcap_sendqueue_destroy(pcap_send_queue *q) { if (q) { free(q->buffer); free(q); } }
__declspec(dllexport) int pcap_sendqueue_queue(pcap_send_queue *q, const struct win_pkthdr *h, const unsigned char *data)
{
    if (!q || !h || !data) return -1;
    if (q->len + sizeof(*h) + h->caplen > q->maxlen) return -1;
    memcpy(q->buffer + q->len, h, sizeof(*h));
    memcpy(q->buffer + q->len + sizeof(*h), data, h->caplen);
    q->len += sizeof(*h) + h->caplen;
    return 0;
}
/* transmit a dump-format buffer ([pkthdr][data])* via pcap_sendpacket; returns bytes consumed */
static unsigned int typecount[256], rare_logged[256];
static unsigned int send_buffer(void *real, const char *buf, unsigned int len, int sync)
{
    unsigned int off = 0, npkts = 0, fails = 0; struct win_timeval prev = {0,0}; int have_prev = 0;
    static unsigned int calls;
    while (off + sizeof(struct win_pkthdr) <= len) {
        const struct win_pkthdr *h = (const struct win_pkthdr *)(buf + off);
        const unsigned char *data = (const unsigned char *)(h + 1);
        if (off + sizeof(*h) + h->caplen > len) break;
        if (sync && have_prev) {
            long dus = (h->ts.tv_sec - prev.tv_sec) * 1000000L + (h->ts.tv_usec - prev.tv_usec);
            if (dus > 1000) Sleep((DWORD)(dus / 1000));
        }
        prev = h->ts; have_prev = 1;
        if (r_pcap_sendpacket(real, data, (int)h->caplen) != 0) fails++;
        npkts++;
        if (h->caplen >= 24 && data[12] == 0x07) {       /* discovery probe seen */
            /* Probe carries a receiver index; LEDVISION scans 0..N. A single card only
             * answers for its own index, so only inject for index 0 (else -> 1024 cards). */
            const unsigned char *pd = data + 13;         /* CL data starts at byte 13 */
            int idx = pd[3] | pd[16];                    /* index seen at data[3] (FPP) or data[16] */
            static int plog;
            if (plog < 6) { shimlog("probe data[0..19]: %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x %02x",
                pd[0],pd[1],pd[2],pd[3],pd[4],pd[5],pd[6],pd[7],pd[8],pd[9],pd[10],pd[11],pd[12],pd[13],pd[14],pd[15],pd[16],pd[17],pd[18],pd[19]); plog++; }
            if (idx == 0) {
                if (load_real_reply() || getenv("CL_FORGE_REPLY")) {
                    if (!load_real_reply()) build_forged_reply(0x00, 64, 64);
                    InterlockedExchange(&discovery_pending, 1);
                    shimlog("discovery probe idx 0 -> injecting reply (%u bytes)", forged_hdr.caplen);
                }
            } else {
                shimlog("discovery probe idx %d -> no reply (real card only answers idx 0)", idx);
            }
        }
        if (h->caplen >= 14) { unsigned t = data[12]; typecount[t]++; if (t != 0x55 && t != 0x0a && t != 0x01 && rare_logged[t]++ < 5) shimlog("  tx type 0x%02x len %u: %02x %02x %02x %02x %02x %02x %02x %02x", t, h->caplen, data[12],data[13],data[14],data[15],data[16],data[17],data[18],data[19]); }
        off += sizeof(*h) + h->caplen;
    }
    if (calls++ < 20 || fails || (calls % 250) == 0) {
        char line[512]; int n = 0, t; line[0] = 0;
        for (t = 0; t < 256; t++) if (typecount[t]) n += snprintf(line + n, sizeof(line) - n, " 0x%02x:%u", t, typecount[t]);
        shimlog("send_buffer: %u packets, %u bytes, %u failed (sync=%d); totals by type:%s", npkts, off, fails, sync, line);
    }
    return off;
}
__declspec(dllexport) unsigned int pcap_sendqueue_transmit(void *p, pcap_send_queue *q, int sync)
{
    if (!p || !q) return 0;
    return send_buffer(real_of(p), q->buffer, q->len, sync);
}

/* ---- DeviceIoControl hook (NPF ioctls on the fake adapter handle) ---- */
static BOOL (WINAPI *real_DeviceIoControl)(HANDLE, DWORD, LPVOID, DWORD, LPVOID, DWORD, LPDWORD, LPOVERLAPPED);
static BOOL WINAPI my_DeviceIoControl(HANDLE h, DWORD code, LPVOID in, DWORD inlen, LPVOID out, DWORD outlen, LPDWORD ret, LPOVERLAPPED ov)
{
    struct fake_pcap *f = fake_by_hfile(h);
    if (!f) return real_DeviceIoControl(h, code, in, inlen, out, outlen, ret, ov);
    if (code == BIOCSENDPACKETSNOSYNC || code == BIOCSENDPACKETSSYNC) {
        unsigned int n = send_buffer(f->real, in, inlen, code == BIOCSENDPACKETSSYNC);
        if (ret) *ret = n;
        return TRUE;
    }
    shimlog("DeviceIoControl(fake hFile, code 0x%lx, inlen %lu, outlen %lu): ignored", code, inlen, outlen);
    if (ret) *ret = 0;
    return TRUE;
}

static void hook_iat(HMODULE mod, const char *modname)
{
    IMAGE_DOS_HEADER *dos = (IMAGE_DOS_HEADER *)mod;
    IMAGE_NT_HEADERS *nt; IMAGE_IMPORT_DESCRIPTOR *imp; DWORD rva;
    if (!mod || dos->e_magic != IMAGE_DOS_SIGNATURE) return;
    nt = (IMAGE_NT_HEADERS *)((char *)mod + dos->e_lfanew);
    rva = nt->OptionalHeader.DataDirectory[IMAGE_DIRECTORY_ENTRY_IMPORT].VirtualAddress;
    if (!rva) return;
    for (imp = (IMAGE_IMPORT_DESCRIPTOR *)((char *)mod + rva); imp->Name; imp++) {
        const char *dll = (const char *)mod + imp->Name;
        IMAGE_THUNK_DATA *orig, *thunk;
        if (_stricmp(dll, "kernel32.dll") != 0) continue;
        orig = (IMAGE_THUNK_DATA *)((char *)mod + imp->OriginalFirstThunk);
        thunk = (IMAGE_THUNK_DATA *)((char *)mod + imp->FirstThunk);
        for (; orig->u1.AddressOfData; orig++, thunk++) {
            IMAGE_IMPORT_BY_NAME *ibn;
            if (orig->u1.Ordinal & IMAGE_ORDINAL_FLAG) continue;
            ibn = (IMAGE_IMPORT_BY_NAME *)((char *)mod + orig->u1.AddressOfData);
            if (strcmp((const char *)ibn->Name, "DeviceIoControl") == 0) {
                DWORD old;
                VirtualProtect(&thunk->u1.Function, sizeof(void*), PAGE_READWRITE, &old);
                thunk->u1.Function = (DWORD_PTR)my_DeviceIoControl;
                VirtualProtect(&thunk->u1.Function, sizeof(void*), old, &old);
                shimlog("hooked DeviceIoControl in %s", modname);
            }
        }
    }
}

/* ---- blind forwarders for everything else ---- */
#define FWD(name) static FARPROC p_##name; \
    __declspec(dllexport) __attribute__((naked)) void name(void) { __asm__ volatile("jmp *%0" : : "m"(p_##name)); }
FWD(bpf_dump)
FWD(bpf_filter)
FWD(bpf_image)
FWD(bpf_validate)
FWD(pcap_activate)
FWD(pcap_bufsize)
FWD(pcap_can_set_rfmon)
FWD(pcap_compile_nopcap)
FWD(pcap_create)
FWD(pcap_createsrcstr)
FWD(pcap_datalink_ext)
FWD(pcap_datalink_name_to_val)
FWD(pcap_datalink_val_to_description)
FWD(pcap_datalink_val_to_description_or_dlt)
FWD(pcap_datalink_val_to_name)
FWD(pcap_dump)
FWD(pcap_dump_close)
FWD(pcap_dump_file)
FWD(pcap_dump_flush)
FWD(pcap_dump_ftell)
FWD(pcap_dump_ftell64)
FWD(pcap_dump_hopen)
FWD(pcap_dump_open)
FWD(pcap_dump_open_append)
FWD(pcap_ether_aton)
FWD(pcap_ether_hostton)
FWD(pcap_file)
FWD(pcap_findalldevs)
FWD(pcap_findalldevs_ex)
FWD(pcap_freealldevs)
FWD(pcap_freecode)
FWD(pcap_free_datalinks)
FWD(pcap_free_tstamp_types)
FWD(pcap_get_airpcap_handle)
FWD(pcap_get_tstamp_precision)
FWD(pcap_hopen_offline)
FWD(pcap_hopen_offline_with_tstamp_precision)
FWD(pcap_init)
FWD(pcap_inject)
FWD(pcap_is_swapped)
FWD(pcap_lib_version)
FWD(pcap_list_datalinks)
FWD(pcap_list_tstamp_types)
FWD(pcap_live_dump)
FWD(pcap_live_dump_ended)
FWD(pcap_lookupdev)
FWD(pcap_lookupnet)
FWD(pcap_major_version)
FWD(pcap_minor_version)
FWD(pcap_next_etherent)
FWD(pcap_offline_filter)
FWD(pcap_oid_get_request)
FWD(pcap_oid_set_request)
FWD(pcap_open_dead)
FWD(pcap_open_dead_with_tstamp_precision)
FWD(pcap_open_offline)
FWD(pcap_open_offline_with_tstamp_precision)
FWD(pcap_parsesrcstr)
FWD(pcap_remoteact_accept)
FWD(pcap_remoteact_accept_ex)
FWD(pcap_remoteact_cleanup)
FWD(pcap_remoteact_close)
FWD(pcap_remoteact_list)
FWD(pcap_set_buffer_size)
FWD(pcap_set_immediate_mode)
FWD(pcap_set_promisc)
FWD(pcap_set_rfmon)
FWD(pcap_setsampling)
FWD(pcap_set_snaplen)
FWD(pcap_set_timeout)
FWD(pcap_set_tstamp_precision)
FWD(pcap_set_tstamp_type)
FWD(pcap_stats_ex)
FWD(pcap_statustostr)
FWD(pcap_strerror)
FWD(pcap_tstamp_type_name_to_val)
FWD(pcap_tstamp_type_val_to_description)
FWD(pcap_tstamp_type_val_to_name)
FWD(pcap_wsockinit)

static void resolve(void)
{
#define R(name) p_##name = GetProcAddress(builtin, #name); if (!p_##name) shimlog("missing %s", #name);
    R(bpf_dump)
    R(bpf_filter)
    R(bpf_image)
    R(bpf_validate)
    R(pcap_activate)
    R(pcap_bufsize)
    R(pcap_can_set_rfmon)
    R(pcap_compile_nopcap)
    R(pcap_create)
    R(pcap_createsrcstr)
    R(pcap_datalink_ext)
    R(pcap_datalink_name_to_val)
    R(pcap_datalink_val_to_description)
    R(pcap_datalink_val_to_description_or_dlt)
    R(pcap_datalink_val_to_name)
    R(pcap_dump)
    R(pcap_dump_close)
    R(pcap_dump_file)
    R(pcap_dump_flush)
    R(pcap_dump_ftell)
    R(pcap_dump_ftell64)
    R(pcap_dump_hopen)
    R(pcap_dump_open)
    R(pcap_dump_open_append)
    R(pcap_ether_aton)
    R(pcap_ether_hostton)
    R(pcap_file)
    R(pcap_findalldevs)
    R(pcap_findalldevs_ex)
    R(pcap_freealldevs)
    R(pcap_freecode)
    R(pcap_free_datalinks)
    R(pcap_free_tstamp_types)
    R(pcap_get_airpcap_handle)
    R(pcap_get_tstamp_precision)
    R(pcap_hopen_offline)
    R(pcap_hopen_offline_with_tstamp_precision)
    R(pcap_init)
    R(pcap_inject)
    R(pcap_is_swapped)
    R(pcap_lib_version)
    R(pcap_list_datalinks)
    R(pcap_list_tstamp_types)
    R(pcap_live_dump)
    R(pcap_live_dump_ended)
    R(pcap_lookupdev)
    R(pcap_lookupnet)
    R(pcap_major_version)
    R(pcap_minor_version)
    R(pcap_next_etherent)
    R(pcap_offline_filter)
    R(pcap_oid_get_request)
    R(pcap_oid_set_request)
    R(pcap_open_dead)
    R(pcap_open_dead_with_tstamp_precision)
    R(pcap_open_offline)
    R(pcap_open_offline_with_tstamp_precision)
    R(pcap_parsesrcstr)
    R(pcap_remoteact_accept)
    R(pcap_remoteact_accept_ex)
    R(pcap_remoteact_cleanup)
    R(pcap_remoteact_close)
    R(pcap_remoteact_list)
    R(pcap_set_buffer_size)
    R(pcap_set_immediate_mode)
    R(pcap_set_promisc)
    R(pcap_set_rfmon)
    R(pcap_setsampling)
    R(pcap_set_snaplen)
    R(pcap_set_timeout)
    R(pcap_set_tstamp_precision)
    R(pcap_set_tstamp_type)
    R(pcap_stats_ex)
    R(pcap_statustostr)
    R(pcap_strerror)
    R(pcap_tstamp_type_name_to_val)
    R(pcap_tstamp_type_val_to_description)
    R(pcap_tstamp_type_val_to_name)
    R(pcap_wsockinit)
#define RR(name) r_##name = (void*)GetProcAddress(builtin, #name); if (!r_##name) shimlog("missing %s", #name);
    RR(pcap_open) RR(pcap_open_live) RR(pcap_close) RR(pcap_compile) RR(pcap_setfilter) RR(pcap_setbuff)
    RR(pcap_next_ex) RR(pcap_next) RR(pcap_sendpacket) RR(pcap_geterr) RR(pcap_datalink) RR(pcap_setnonblock)
    RR(pcap_getnonblock) RR(pcap_setmintocopy) RR(pcap_stats) RR(pcap_snapshot) RR(pcap_fileno) RR(pcap_setmode)
    RR(pcap_breakloop) RR(pcap_loop) RR(pcap_dispatch) RR(pcap_perror) RR(pcap_setuserbuffer) RR(pcap_set_datalink)
    RR(pcap_setdirection)
}

BOOL WINAPI DllMain(HINSTANCE inst, DWORD reason, LPVOID reserved)
{
    if (reason == DLL_PROCESS_ATTACH) {
        WCHAR path[MAX_PATH]; HMODULE k32 = GetModuleHandleW(L"kernel32.dll");
        DisableThreadLibraryCalls(inst);
        logf = fopen("C:\\wpcap-shim.log", "a");
        GetSystemDirectoryW(path, MAX_PATH); lstrcatW(path, L"\\wpcap.dll");
        builtin = LoadLibraryExW(path, NULL, LOAD_WITH_ALTERED_SEARCH_PATH);
        shimlog("shim v13 attached (inject real reply, index-0 only)", path, builtin, inst);
        if (!builtin || builtin == inst) { shimlog("failed to load builtin wpcap"); return FALSE; }
        /* CLTNic FreeLibrary()s wpcap.dll when re-opening the adapter; if we get unloaded, the next
         * LoadLibrary("wpcap.dll") resolves to the still-loaded builtin and bypasses us.  Pin ourselves. */
        { HMODULE self; GetModuleHandleExW(GET_MODULE_HANDLE_EX_FLAG_PIN | GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS, (LPCWSTR)DllMain, &self); }
        resolve();
        real_DeviceIoControl = (void*)GetProcAddress(k32, "DeviceIoControl");
        hook_iat(GetModuleHandleW(L"CLTNic.dll"), "CLTNic.dll");
        hook_iat(GetModuleHandleW(NULL), "main exe");
    }
    return TRUE;
}

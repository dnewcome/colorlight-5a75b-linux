#include <windows.h>
#include <stdio.h>
int main(void){
    HMODULE h = LoadLibraryA("wpcap.dll");
    printf("wpcap.dll -> %p\n", h); if(!h) return 1;
    char buf[MAX_PATH]; GetModuleFileNameA(h, buf, MAX_PATH); printf("loaded from %s\n", buf);
    const char* (*ver)(void) = (void*)GetProcAddress(h, "pcap_lib_version");
    void* (*alloc)(unsigned) = (void*)GetProcAddress(h, "pcap_sendqueue_alloc");
    int (*queue)(void*, const void*, const void*) = (void*)GetProcAddress(h, "pcap_sendqueue_queue");
    printf("pcap_lib_version -> %s\n", ver ? ver() : "(null)");
    void *q = alloc ? alloc(4096) : NULL; printf("sendqueue_alloc -> %p\n", q);
    struct { long s, us; unsigned caplen, len; } hdr = {0,0,60,60}; unsigned char pkt[60] = {0x11,0x22,0x33,0x44,0x55,0x66};
    printf("sendqueue_queue -> %d\n", q ? queue(q, &hdr, pkt) : -9);
    return 0;
}

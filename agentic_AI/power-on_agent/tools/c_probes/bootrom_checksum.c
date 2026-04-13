/*
 * bootrom_checksum.c — Boot ROM region checksum verification for PoAgent
 *
 * Reads a physical address range (typically BootROM at 0xFFFF0000 or
 * platform-specific) via /dev/mem and computes SHA-256, comparing
 * against an expected digest provided on the command line.
 *
 * Usage: bootrom_checksum <phys_addr_hex> <size_bytes> <expected_sha256_hex>
 * Example: bootrom_checksum 0xFFFF0000 65536 deadbeef...
 *
 * If expected_sha256_hex is "0" or omitted, just prints the checksum.
 * Exits 0 on match (or print-only), 1 on mismatch, 2 on error.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

/* Minimal SHA-256 implementation (RFC 6234) */

#define SHA256_BLOCK_SIZE 32

typedef struct {
    uint32_t state[8];
    uint64_t bit_count;
    uint8_t buf[64];
    size_t buf_len;
} sha256_ctx;

static const uint32_t K[64] = {
    0x428a2f98,0x71374491,0xb5c0fbcf,0xe9b5dba5,
    0x3956c25b,0x59f111f1,0x923f82a4,0xab1c5ed5,
    0xd807aa98,0x12835b01,0x243185be,0x550c7dc3,
    0x72be5d74,0x80deb1fe,0x9bdc06a7,0xc19bf174,
    0xe49b69c1,0xefbe4786,0x0fc19dc6,0x240ca1cc,
    0x2de92c6f,0x4a7484aa,0x5cb0a9dc,0x76f988da,
    0x983e5152,0xa831c66d,0xb00327c8,0xbf597fc7,
    0xc6e00bf3,0xd5a79147,0x06ca6351,0x14292967,
    0x27b70a85,0x2e1b2138,0x4d2c6dfc,0x53380d13,
    0x650a7354,0x766a0abb,0x81c2c92e,0x92722c85,
    0xa2bfe8a1,0xa81a664b,0xc24b8b70,0xc76c51a3,
    0xd192e819,0xd6990624,0xf40e3585,0x106aa070,
    0x19a4c116,0x1e376c08,0x2748774c,0x34b0bcb5,
    0x391c0cb3,0x4ed8aa4a,0x5b9cca4f,0x682e6ff3,
    0x748f82ee,0x78a5636f,0x84c87814,0x8cc70208,
    0x90befffa,0xa4506ceb,0xbef9a3f7,0xc67178f2,
};

#define ROTR32(x,n) (((x)>>(n))|((x)<<(32-(n))))
#define CH(e,f,g)  (((e)&(f))^(~(e)&(g)))
#define MAJ(a,b,c) (((a)&(b))^((a)&(c))^((b)&(c)))
#define S0(a) (ROTR32(a,2)^ROTR32(a,13)^ROTR32(a,22))
#define S1(e) (ROTR32(e,6)^ROTR32(e,11)^ROTR32(e,25))
#define R0(x) (ROTR32(x,7)^ROTR32(x,18)^((x)>>3))
#define R1(x) (ROTR32(x,17)^ROTR32(x,19)^((x)>>10))

static void sha256_compress(sha256_ctx *ctx, const uint8_t *block)
{
    uint32_t w[64], a, b, c, d, e, f, g, h, t1, t2;
    int i;

    for (i = 0; i < 16; i++)
        w[i] = ((uint32_t)block[i*4]<<24)|((uint32_t)block[i*4+1]<<16)|
               ((uint32_t)block[i*4+2]<<8)|(uint32_t)block[i*4+3];
    for (i = 16; i < 64; i++)
        w[i] = R1(w[i-2]) + w[i-7] + R0(w[i-15]) + w[i-16];

    a=ctx->state[0]; b=ctx->state[1]; c=ctx->state[2]; d=ctx->state[3];
    e=ctx->state[4]; f=ctx->state[5]; g=ctx->state[6]; h=ctx->state[7];

    for (i = 0; i < 64; i++) {
        t1 = h + S1(e) + CH(e,f,g) + K[i] + w[i];
        t2 = S0(a) + MAJ(a,b,c);
        h=g; g=f; f=e; e=d+t1; d=c; c=b; b=a; a=t1+t2;
    }

    ctx->state[0]+=a; ctx->state[1]+=b; ctx->state[2]+=c; ctx->state[3]+=d;
    ctx->state[4]+=e; ctx->state[5]+=f; ctx->state[6]+=g; ctx->state[7]+=h;
}

static void sha256_init(sha256_ctx *ctx)
{
    ctx->state[0]=0x6a09e667; ctx->state[1]=0xbb67ae85;
    ctx->state[2]=0x3c6ef372; ctx->state[3]=0xa54ff53a;
    ctx->state[4]=0x510e527f; ctx->state[5]=0x9b05688c;
    ctx->state[6]=0x1f83d9ab; ctx->state[7]=0x5be0cd19;
    ctx->bit_count=0; ctx->buf_len=0;
}

static void sha256_update(sha256_ctx *ctx, const uint8_t *data, size_t len)
{
    while (len) {
        size_t n = 64 - ctx->buf_len;
        if (n > len) n = len;
        memcpy(ctx->buf + ctx->buf_len, data, n);
        ctx->buf_len += n;
        data += n; len -= n;
        ctx->bit_count += n * 8;
        if (ctx->buf_len == 64) {
            sha256_compress(ctx, ctx->buf);
            ctx->buf_len = 0;
        }
    }
}

static void sha256_final(sha256_ctx *ctx, uint8_t digest[32])
{
    int i;
    uint64_t bc = ctx->bit_count;
    uint8_t pad = 0x80;
    sha256_update(ctx, &pad, 1);
    pad = 0;
    while (ctx->buf_len != 56)
        sha256_update(ctx, &pad, 1);
    uint8_t len_be[8];
    for (i = 7; i >= 0; i--) { len_be[i] = (uint8_t)(bc & 0xFF); bc >>= 8; }
    sha256_update(ctx, len_be, 8);
    for (i = 0; i < 8; i++) {
        digest[i*4]   = (ctx->state[i]>>24)&0xFF;
        digest[i*4+1] = (ctx->state[i]>>16)&0xFF;
        digest[i*4+2] = (ctx->state[i]>>8)&0xFF;
        digest[i*4+3] =  ctx->state[i]&0xFF;
    }
}

int main(int argc, char *argv[])
{
    if (argc < 3) {
        fprintf(stderr,
            "usage: bootrom_checksum <phys_addr_hex> <size_bytes> [expected_sha256_hex]\n");
        return 2;
    }

    unsigned long phys_addr = strtoul(argv[1], NULL, 16);
    size_t size = (size_t)strtoul(argv[2], NULL, 10);
    const char *expected_hex = (argc >= 4) ? argv[3] : "0";

    if (size == 0) {
        fprintf(stderr, "bootrom_checksum: size must be non-zero\n");
        return 2;
    }

    off_t page_base = (off_t)(phys_addr & ~(4095UL));
    size_t page_off = phys_addr - (unsigned long)page_base;
    size_t map_size = size + page_off;

    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 2; }

    void *map = mmap(NULL, map_size, PROT_READ, MAP_SHARED, fd, page_base);
    if (map == MAP_FAILED) { perror("mmap"); close(fd); return 2; }

    const uint8_t *rom = (const uint8_t *)map + page_off;

    sha256_ctx ctx;
    sha256_init(&ctx);
    sha256_update(&ctx, rom, size);
    uint8_t digest[32];
    sha256_final(&ctx, digest);

    munmap(map, map_size);
    close(fd);

    char hex[65];
    for (int i = 0; i < 32; i++)
        snprintf(hex + i*2, 3, "%02x", digest[i]);
    hex[64] = '\0';

    printf("bootrom_checksum: phys=0x%lx size=%zu sha256=%s\n", phys_addr, size, hex);

    if (strcmp(expected_hex, "0") == 0) {
        printf("bootrom_checksum: PASS (print-only mode)\n");
        return 0;
    }

    if (strcasecmp(hex, expected_hex) == 0) {
        printf("bootrom_checksum: PASS\n");
        return 0;
    } else {
        fprintf(stderr, "bootrom_checksum: FAIL expected=%s got=%s\n", expected_hex, hex);
        return 1;
    }
}

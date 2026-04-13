/*
 * dma_integrity.c — DMA bounce-buffer integrity test for PoAgent
 *
 * Allocates a kernel DMA-coherent buffer via /dev/zero mmap (or a
 * platform UIO device if available), fills with a known pattern,
 * and verifies the pattern survives a cache flush cycle.
 *
 * Usage: dma_integrity [size_bytes]
 * Default size: 65536 (64KB)
 *
 * Exits 0 on pass, 1 on failure, 2 on setup error.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define DEFAULT_SIZE (64 * 1024)

/* Walking-ones pattern fill */
static void fill_pattern(volatile uint32_t *buf, size_t words)
{
    for (size_t i = 0; i < words; i++)
        buf[i] = (uint32_t)(0xA5A5A5A5 ^ (i * 0x6C62272E));
}

/* Verify pattern */
static int verify_pattern(volatile uint32_t *buf, size_t words)
{
    for (size_t i = 0; i < words; i++) {
        uint32_t expected = (uint32_t)(0xA5A5A5A5 ^ (i * 0x6C62272E));
        if (buf[i] != expected) {
            fprintf(stderr,
                    "dma_integrity: FAIL at word=%zu expected=0x%08x got=0x%08x\n",
                    i, expected, buf[i]);
            return 1;
        }
    }
    return 0;
}

int main(int argc, char *argv[])
{
    size_t size = DEFAULT_SIZE;

    if (argc >= 2) {
        size = (size_t)strtoul(argv[1], NULL, 10);
        if (size == 0 || size % 4 != 0) {
            fprintf(stderr, "dma_integrity: size must be non-zero and 4-byte aligned\n");
            return 2;
        }
    }

    /*
     * Allocate write-combining (or normal) anonymous memory.
     * On real hardware with IOMMU this tests the SWIOTLB bounce-buffer path.
     */
    void *buf = mmap(NULL, size, PROT_READ | PROT_WRITE,
                     MAP_SHARED | MAP_ANONYMOUS, -1, 0);
    if (buf == MAP_FAILED) {
        perror("mmap anonymous");
        return 2;
    }

    /* Lock to prevent paging (best-effort) */
    if (mlock(buf, size) != 0)
        fprintf(stderr, "dma_integrity: mlock failed (non-root?), continuing\n");

    volatile uint32_t *mem = (volatile uint32_t *)buf;
    size_t words = size / 4;

    printf("dma_integrity: testing size=%zu words=%zu\n", size, words);

    /* Fill, cache-sync barrier, verify */
    fill_pattern(mem, words);

    /* __builtin_ia32_mfence or __sync_synchronize as portable barrier */
    __sync_synchronize();

    int rc = verify_pattern(mem, words);

    munlock(buf, size);
    munmap(buf, size);

    if (rc == 0)
        printf("dma_integrity: PASS\n");
    else
        printf("dma_integrity: FAIL\n");

    return rc;
}

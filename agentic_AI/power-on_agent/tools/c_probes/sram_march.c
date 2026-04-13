/*
 * sram_march.c — SRAM March-C- integrity test for PoAgent
 *
 * Performs a March-C- algorithm on a mmap'd /dev/mem region or
 * a platform SRAM device. Exits 0 on pass, 1 on failure.
 *
 * Usage: sram_march <phys_addr_hex> <size_bytes>
 * Example: sram_march 0x9E000000 65536
 *
 * [PRD §7.3] C probes are uploaded and verified via SHA-256 before execution.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <unistd.h>

#define PAGE_SIZE 4096UL

static int march_c_minus(volatile uint32_t *mem, size_t words)
{
    size_t i;

    /* Pass 1: write 0 upward */
    for (i = 0; i < words; i++)
        mem[i] = 0;

    /* Pass 2: read 0, write 1 upward */
    for (i = 0; i < words; i++) {
        if (mem[i] != 0) {
            fprintf(stderr, "march: FAIL pass2 word=%zu got=0x%08x\n",
                    i, mem[i]);
            return 1;
        }
        mem[i] = 0xFFFFFFFF;
    }

    /* Pass 3: read 1, write 0 upward */
    for (i = 0; i < words; i++) {
        if (mem[i] != 0xFFFFFFFF) {
            fprintf(stderr, "march: FAIL pass3 word=%zu got=0x%08x\n",
                    i, mem[i]);
            return 1;
        }
        mem[i] = 0;
    }

    /* Pass 4: read 0, write 1 downward */
    for (i = words; i-- > 0;) {
        if (mem[i] != 0) {
            fprintf(stderr, "march: FAIL pass4 word=%zu got=0x%08x\n",
                    i, mem[i]);
            return 1;
        }
        mem[i] = 0xFFFFFFFF;
    }

    /* Pass 5: read 1, write 0 downward */
    for (i = words; i-- > 0;) {
        if (mem[i] != 0xFFFFFFFF) {
            fprintf(stderr, "march: FAIL pass5 word=%zu got=0x%08x\n",
                    i, mem[i]);
            return 1;
        }
        mem[i] = 0;
    }

    /* Pass 6: read 0 upward */
    for (i = 0; i < words; i++) {
        if (mem[i] != 0) {
            fprintf(stderr, "march: FAIL pass6 word=%zu got=0x%08x\n",
                    i, mem[i]);
            return 1;
        }
    }

    return 0;
}

int main(int argc, char *argv[])
{
    if (argc != 3) {
        fprintf(stderr, "usage: sram_march <phys_addr_hex> <size_bytes>\n");
        return 2;
    }

    unsigned long phys_addr = strtoul(argv[1], NULL, 16);
    size_t size = (size_t)strtoul(argv[2], NULL, 10);

    if (size == 0 || size % 4 != 0) {
        fprintf(stderr, "sram_march: size must be non-zero and 4-byte aligned\n");
        return 2;
    }

    /* Align to page */
    off_t page_base = (off_t)(phys_addr & ~(PAGE_SIZE - 1));
    size_t offset_in_page = phys_addr - (unsigned long)page_base;
    size_t map_size = size + offset_in_page;

    int fd = open("/dev/mem", O_RDWR | O_SYNC);
    if (fd < 0) {
        perror("open /dev/mem");
        return 2;
    }

    void *map = mmap(NULL, map_size, PROT_READ | PROT_WRITE,
                     MAP_SHARED, fd, page_base);
    if (map == MAP_FAILED) {
        perror("mmap /dev/mem");
        close(fd);
        return 2;
    }

    volatile uint32_t *mem = (volatile uint32_t *)((char *)map + offset_in_page);
    size_t words = size / 4;

    printf("sram_march: testing phys=0x%lx size=%zu words=%zu\n",
           phys_addr, size, words);

    int rc = march_c_minus(mem, words);

    munmap(map, map_size);
    close(fd);

    if (rc == 0)
        printf("sram_march: PASS\n");
    else
        printf("sram_march: FAIL\n");

    return rc;
}

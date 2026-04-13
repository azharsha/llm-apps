/*
 * mmio_dump.c — Generic MMIO register reader for PoAgent C probe framework.
 *
 * Usage:
 *   mmio_dump --base 0xfe150000 --size 0x1000 --offsets 0x0,0x4,0x5c
 *
 * Output (JSON to stdout):
 *   {"0x0": 12345, "0x4": 67890, "0x5c": 16}
 *
 * Requirements:
 *   - /dev/mem readable (root + CONFIG_STRICT_DEVMEM=n, or CAP_SYS_RAWIO)
 *   - 32-bit register access only (4-byte aligned offsets)
 *
 * Compile:
 *   gcc -O2 -o mmio_dump mmio_dump.c
 *   aarch64-linux-gnu-gcc -O2 -static -o mmio_dump.aarch64 mmio_dump.c
 *   x86_64-linux-gnu-gcc  -O2 -static -o mmio_dump.x86_64  mmio_dump.c
 */

#include <stdio.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>
#include <fcntl.h>
#include <unistd.h>
#include <errno.h>
#include <sys/mman.h>

#define MAX_OFFSETS 64

static void usage(const char *prog) {
    fprintf(stderr,
        "Usage: %s --base <hex> [--size <hex>] [--offsets <hex,hex,...>]\n"
        "  --base     Physical base address (hex, required)\n"
        "  --size     Region size in bytes (hex, default 0x1000)\n"
        "  --offsets  Comma-separated register offsets (hex, default 0x0)\n"
        "Output: JSON dict {\"0xOFFSET\": VALUE, ...}\n",
        prog);
}

int main(int argc, char *argv[]) {
    uintptr_t base = 0;
    size_t    map_size = 0x1000;
    char     *offsets_arg = NULL;
    int       base_set = 0;

    /* Parse arguments */
    for (int i = 1; i < argc; i++) {
        if (!strcmp(argv[i], "--base") && i + 1 < argc) {
            base = (uintptr_t)strtoull(argv[++i], NULL, 16);
            base_set = 1;
        } else if (!strcmp(argv[i], "--size") && i + 1 < argc) {
            map_size = (size_t)strtoull(argv[++i], NULL, 16);
        } else if (!strcmp(argv[i], "--offsets") && i + 1 < argc) {
            offsets_arg = argv[++i];
        } else if (!strcmp(argv[i], "--help") || !strcmp(argv[i], "-h")) {
            usage(argv[0]);
            return 0;
        }
    }

    if (!base_set) {
        fprintf(stderr, "{\"error\": \"--base is required\"}\n");
        usage(argv[0]);
        return 1;
    }

    /* Parse offsets */
    uintptr_t offsets[MAX_OFFSETS];
    int n_offsets = 0;

    if (!offsets_arg) {
        offsets[0] = 0;
        n_offsets = 1;
    } else {
        char *buf = strdup(offsets_arg);
        char *tok = strtok(buf, ",");
        while (tok && n_offsets < MAX_OFFSETS) {
            offsets[n_offsets++] = (uintptr_t)strtoull(tok, NULL, 16);
            tok = strtok(NULL, ",");
        }
        free(buf);
    }

    /* Open /dev/mem */
    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) {
        fprintf(stderr, "{\"error\": \"open /dev/mem failed: %s\"}\n", strerror(errno));
        return 1;
    }

    /* Align base to page boundary for mmap */
    uintptr_t page_size   = (uintptr_t)sysconf(_SC_PAGE_SIZE);
    uintptr_t page_mask   = page_size - 1;
    uintptr_t aligned_base = base & ~page_mask;
    uintptr_t base_offset  = base - aligned_base;
    size_t    total_size   = map_size + base_offset;

    volatile uint8_t *map = mmap(NULL, total_size, PROT_READ,
                                  MAP_SHARED, fd, (off_t)aligned_base);
    if (map == MAP_FAILED) {
        fprintf(stderr, "{\"error\": \"mmap(0x%lx, 0x%zx) failed: %s\"}\n",
                (unsigned long)aligned_base, total_size, strerror(errno));
        close(fd);
        return 1;
    }

    /* Read registers and emit JSON */
    printf("{");
    for (int i = 0; i < n_offsets; i++) {
        uintptr_t off = offsets[i];

        /* Bounds check */
        if (off + 4 > map_size) {
            fprintf(stderr, "{\"error\": \"offset 0x%lx out of bounds (size 0x%zx)\"}\n",
                    (unsigned long)off, map_size);
            munmap((void *)map, total_size);
            close(fd);
            return 1;
        }

        /* 32-bit aligned read */
        volatile uint32_t *reg = (volatile uint32_t *)(map + base_offset + off);
        uint32_t val = *reg;

        if (i > 0) printf(", ");
        printf("\"0x%lx\": %u", (unsigned long)off, val);
    }
    printf("}\n");

    munmap((void *)map, total_size);
    close(fd);
    return 0;
}

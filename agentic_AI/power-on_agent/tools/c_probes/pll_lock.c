/*
 * pll_lock.c — PLL lock status probe via memory-mapped registers for PoAgent
 *
 * Reads a PLL status register at a given physical address and checks
 * the specified lock bit. Reports lock/unlock state.
 *
 * Usage: pll_lock <phys_addr_hex> <lock_bit> [expected_locked=1]
 * Example: pll_lock 0x17C10024 31 1
 *
 * - phys_addr_hex: Physical address of the PLL status register
 * - lock_bit: Bit number (0-31) of the PLL LOCK field
 * - expected_locked: 1=expect locked (default), 0=expect unlocked
 *
 * Exits 0 if lock state matches expected, 1 on mismatch, 2 on error.
 */

#include <errno.h>
#include <fcntl.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

int main(int argc, char *argv[])
{
    if (argc < 3) {
        fprintf(stderr,
            "usage: pll_lock <phys_addr_hex> <lock_bit> [expected_locked=1]\n");
        return 2;
    }

    unsigned long phys_addr = strtoul(argv[1], NULL, 16);
    int lock_bit = atoi(argv[2]);
    int expected_locked = (argc >= 4) ? atoi(argv[3]) : 1;

    if (lock_bit < 0 || lock_bit > 31) {
        fprintf(stderr, "pll_lock: lock_bit must be 0-31\n");
        return 2;
    }

    off_t page_base = (off_t)(phys_addr & ~(4095UL));
    size_t page_off = phys_addr - (unsigned long)page_base;

    int fd = open("/dev/mem", O_RDONLY | O_SYNC);
    if (fd < 0) { perror("open /dev/mem"); return 2; }

    void *map = mmap(NULL, 4096, PROT_READ, MAP_SHARED, fd, page_base);
    if (map == MAP_FAILED) { perror("mmap"); close(fd); return 2; }

    volatile uint32_t *reg = (volatile uint32_t *)((char *)map + page_off);
    uint32_t val = *reg;

    munmap(map, 4096);
    close(fd);

    int locked = (val >> lock_bit) & 1;

    printf("pll_lock: phys=0x%lx reg=0x%08x bit=%d locked=%d expected=%d\n",
           phys_addr, val, lock_bit, locked, expected_locked);

    if (locked == expected_locked) {
        printf("pll_lock: PASS\n");
        return 0;
    } else {
        fprintf(stderr, "pll_lock: FAIL (locked=%d expected=%d)\n",
                locked, expected_locked);
        return 1;
    }
}

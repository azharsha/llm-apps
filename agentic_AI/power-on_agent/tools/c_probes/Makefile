# Makefile for PoAgent C probes
#
# Targets:
#   all        — build all probes for host architecture
#   cross      — cross-compile for ARM64 (requires CROSS_COMPILE=aarch64-linux-gnu-)
#   sha256     — generate probes.sha256 manifest after build
#   clean      — remove build artifacts
#
# Usage:
#   make                                    # host build
#   make cross CROSS_COMPILE=aarch64-linux-gnu-   # ARM64 cross
#   make sha256                             # regenerate manifest

CC ?= gcc
CROSS_COMPILE ?=
ARCH_CC = $(CROSS_COMPILE)$(CC)

CFLAGS = -O2 -Wall -Wextra -std=c11 -D_GNU_SOURCE
LDFLAGS =

PROBES = sram_march dma_integrity bootrom_checksum pll_lock

BINARIES = $(PROBES:%=%.elf)

.PHONY: all cross sha256 clean

all: $(BINARIES)

cross:
	$(MAKE) all CC=gcc CROSS_COMPILE=$(CROSS_COMPILE)

%.elf: %.c
	$(ARCH_CC) $(CFLAGS) -o $@ $< $(LDFLAGS)

sha256: $(BINARIES)
	sha256sum $(BINARIES) > probes.sha256
	@echo "Generated probes.sha256"
	@cat probes.sha256

clean:
	rm -f $(BINARIES) probes.sha256

# Individual targets for convenience
sram_march: sram_march.elf
dma_integrity: dma_integrity.elf
bootrom_checksum: bootrom_checksum.elf
pll_lock: pll_lock.elf

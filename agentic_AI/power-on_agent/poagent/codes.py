"""All warning/error code constants for PoAgent.

All warning codes are string constants defined here. Never use inline
literal strings for codes in implementation files — always import from
this module. This ensures consistent naming, easy grepping, and
eliminates typos.
"""

# ── Gate / Pre-flight codes ────────────────────────────────────────────────
BOARD_LOCK_CONFLICT = "BOARD_LOCK_CONFLICT"
CACHE_IMAGE_MISMATCH = "CACHE_IMAGE_MISMATCH"
CACHE_SCHEMA_MISMATCH = "CACHE_SCHEMA_MISMATCH"
DTS_PARSE_ERROR = "DTS_PARSE_ERROR"
DTS_SYNTAX_ERROR = "DTS_SYNTAX_ERROR"
DTS_VERSION_MISMATCH_WARNING = "DTS_VERSION_MISMATCH_WARNING"
DRY_RUN_VALIDATION_FAIL = "DRY_RUN_VALIDATION_FAIL"
GATE4_METHOD5_ONLY = "GATE4_METHOD5_ONLY"
GATE4_SENTINEL_UNSTABLE = "GATE4_SENTINEL_UNSTABLE"

# ── Rail / Barrier codes ───────────────────────────────────────────────────
RAIL_SANITY_FAIL = "RAIL_SANITY_FAIL"
BARRIER_UNCERTAIN = "BARRIER_UNCERTAIN"
BARRIER_PASS = "BARRIER_PASS"
NO_PMBUS_AVAILABLE = "NO_PMBUS_AVAILABLE"
SUSPICIOUS_LOW_VOLTAGE = "SUSPICIOUS_LOW_VOLTAGE"

# ── IRQ codes ─────────────────────────────────────────────────────────────
IRQ_STORM_WARNING = "IRQ_STORM_WARNING"

# ── Clock / cascade codes ─────────────────────────────────────────────────
CLOCK_TOPOLOGY_UNKNOWN = "CLOCK_TOPOLOGY_UNKNOWN"
CLOCK_TOPOLOGY_CONSUMER_UNKNOWN = "CLOCK_TOPOLOGY_CONSUMER_UNKNOWN"
ORCHESTRATOR_WARNING = "ORCHESTRATOR_WARNING"

# ── EDAC / ECC codes ──────────────────────────────────────────────────────
DRAM_MARGINAL = "DRAM_MARGINAL"
DRAM_UNCORRECTABLE_ERROR = "DRAM_UNCORRECTABLE_ERROR"
ECC_NOT_MONITORABLE = "ECC_NOT_MONITORABLE"

# ── Thermal codes ─────────────────────────────────────────────────────────
THERMAL_MONITOR_UNAVAILABLE = "THERMAL_MONITOR_UNAVAILABLE"
THERMAL_THROTTLE_EVENT = "THERMAL_THROTTLE_EVENT"
THERMAL_ABORT = "THERMAL_ABORT"
THERMAL_BREACH_PAUSING = "THERMAL_BREACH_PAUSING"
THERMAL_RESUME = "THERMAL_RESUME"

# ── Watchdog codes ────────────────────────────────────────────────────────
WATCHDOG_RUN_CONFLICT = "WATCHDOG_RUN_CONFLICT"
WATCHDOG_KEEPALIVE_ACTIVE = "WATCHDOG_KEEPALIVE_ACTIVE"
WATCHDOG_KEEPALIVE_FAILED = "WATCHDOG_KEEPALIVE_FAILED"
WATCHDOG_SELINUX_BLOCKED = "WATCHDOG_SELINUX_BLOCKED"
WATCHDOG_DISABLED = "WATCHDOG_DISABLED"
WATCHDOG_NOWAYOUT_CANNOT_DISABLE = "WATCHDOG_NOWAYOUT_CANNOT_DISABLE"

# ── Silicon stepping codes ────────────────────────────────────────────────
SILICON_STEPPING_UNRESOLVED = "SILICON_STEPPING_UNRESOLVED"

# ── Kernel panic codes ────────────────────────────────────────────────────
PANIC_DETECTED_WARNING = "PANIC_DETECTED_WARNING"

# ── OOM codes ─────────────────────────────────────────────────────────────
OOM_KILL_IN_DMESG = "OOM_KILL_IN_DMESG"
OOM_KILL_KERNEL_THREAD = "OOM_KILL_KERNEL_THREAD"

# ── DRAM training codes ───────────────────────────────────────────────────
DRAM_TRAINING_MARGINAL = "DRAM_TRAINING_MARGINAL"
DRAM_TRAINING_LOG_UNAVAILABLE = "DRAM_TRAINING_LOG_UNAVAILABLE"
DRAM_TRAINING_PLATFORM_UNKNOWN = "DRAM_TRAINING_PLATFORM_UNKNOWN"

# ── memtester codes ───────────────────────────────────────────────────────
MEMTESTER_SKIPPED_LOW_MEMORY = "MEMTESTER_SKIPPED_LOW_MEMORY"

# ── PCIe / AER codes ──────────────────────────────────────────────────────
PCIE_GEN_EXPECTED_UNKNOWN = "PCIE_GEN_EXPECTED_UNKNOWN"
PCIE_LINK_WIDTH_EXPECTED_UNKNOWN = "PCIE_LINK_WIDTH_EXPECTED_UNKNOWN"
PCIE_LINK_DOWNGRADE = "PCIE_LINK_DOWNGRADE"

# ── IOMMU codes ───────────────────────────────────────────────────────────
IOMMU_BINDING_FAIL = "IOMMU_BINDING_FAIL"

# ── Storage codes ─────────────────────────────────────────────────────────
NVME_MEDIA_FAIL = "NVME_MEDIA_FAIL"
NVME_UNSAFE_SHUTDOWN_WARNING = "NVME_UNSAFE_SHUTDOWN_WARNING"

# ── Serial / transport codes ──────────────────────────────────────────────
SERIAL_TRUNCATION_RETRY = "SERIAL_TRUNCATION_RETRY"
SERIAL_TRUNCATION_SUSPECTED = "SERIAL_TRUNCATION_SUSPECTED"

# ── Security codes ────────────────────────────────────────────────────────
PROBE_INTEGRITY_FAIL = "PROBE_INTEGRITY_FAIL"
C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY = "C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY"
INTEL_ME_MANUFACTURING_MODE = "INTEL_ME_MANUFACTURING_MODE"

# ── TRNG / crypto codes ───────────────────────────────────────────────────
TRNG_STUCK_FAULT = "TRNG_STUCK_FAULT"
TRNG_FIPS_FAIL = "TRNG_FIPS_FAIL"
TRNG_READ_INCOMPLETE = "TRNG_READ_INCOMPLETE"
EXCLUSION_GROUP_LOCK_TIMEOUT = "EXCLUSION_GROUP_LOCK_TIMEOUT"

# ── PHY codes ─────────────────────────────────────────────────────────────
PHY_REMOTE_FAULT = "PHY_REMOTE_FAULT"
PHY_AUTONEG_INCOMPLETE = "PHY_AUTONEG_INCOMPLETE"
PHY_MII_DUMP_PERMISSION_DENIED = "PHY_MII_DUMP_PERMISSION_DENIED"

# ── USB-C / PD codes ──────────────────────────────────────────────────────
PD_CONTRACT_NEGOTIATING = "PD_CONTRACT_NEGOTIATING"

# ── I2C codes ─────────────────────────────────────────────────────────────
I2C_BUS_SPEED_MARGINAL = "I2C_BUS_SPEED_MARGINAL"
I2C_BUS_HUNG = "I2C_BUS_HUNG"

# ── GPIO / pin codes ──────────────────────────────────────────────────────
GPIO_MUX_CONFLICT = "GPIO_MUX_CONFLICT"
CPU_PSTATE_STUCK = "CPU_PSTATE_STUCK"

# ── Flash / NOR codes ─────────────────────────────────────────────────────
SPI_FLASH_WP_UNSET = "SPI_FLASH_WP_UNSET"

# ── PSCI codes ────────────────────────────────────────────────────────────
PSCI_SUSPEND_UNAVAILABLE = "PSCI_SUSPEND_UNAVAILABLE"

# ── API / Agent codes ─────────────────────────────────────────────────────
API_RATE_LIMIT_ABORT = "API_RATE_LIMIT_ABORT"
AGENT_TIMEOUT = "AGENT_TIMEOUT"
AGENT_API_RETRY = "AGENT_API_RETRY"

# ── Overlay / spec codes ──────────────────────────────────────────────────
BOUNDS_VIOLATION = "BOUNDS_VIOLATION"
ZERO_VALUE_ERROR = "ZERO_VALUE_ERROR"
UNKNOWN_PROPERTY = "UNKNOWN_PROPERTY"
NO_CRITICAL_RAILS = "NO_CRITICAL_RAILS"
SPEC_PDF_OVERSIZED = "SPEC_PDF_OVERSIZED"
REANALYSIS_EVIDENCE_WARNING = "REANALYSIS_EVIDENCE_WARNING"

# ── Sysfs / DTS codes ─────────────────────────────────────────────────────
ENUM_FAIL = "ENUM_FAIL"
SKIP_NOT_POPULATED = "SKIP_NOT_POPULATED"
SKIP_DEBUGFS = "SKIP_DEBUGFS"

# ── C Probe MMIO Framework codes [CP-06] ──────────────────────────────────
C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY = "C_PROBE_DEPLOY_SKIPPED_LOW_MEMORY"
C_PROBE_INTEGRITY_FAIL            = "C_PROBE_INTEGRITY_FAIL"
C_PROBE_COMPILE_FAIL              = "C_PROBE_COMPILE_FAIL"
C_PROBE_EXEC_FAIL                 = "C_PROBE_EXEC_FAIL"
MMIO_REG_READ_FAIL                = "MMIO_REG_READ_FAIL"
MMIO_BASE_NOT_IN_DTS              = "MMIO_BASE_NOT_IN_DTS"

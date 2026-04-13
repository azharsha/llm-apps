"""Audio domain probe implementations."""

from __future__ import annotations

from typing import Any

import structlog

from poagent.probes.registry import ProbeBase, ProbeResult, ProbeTier, register_probe

log = structlog.get_logger(__name__)

DOMAIN = "audio"


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="ALSA sound card enumeration", timeout=20.0)
class ALSAProbe(ProbeBase):
    """Enumerate ALSA sound cards and check PCM devices."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # /proc/asound/cards
        rc, cards = runner.exec_command("cat /proc/asound/cards 2>/dev/null")
        data["alsa_cards"] = cards.strip() if rc == 0 else ""

        # /proc/asound/pcm
        rc, pcm = runner.exec_command("cat /proc/asound/pcm 2>/dev/null")
        data["alsa_pcm"] = pcm.strip() if rc == 0 else ""

        # aplay -l
        rc, aplay = runner.exec_command("aplay -l 2>/dev/null")
        if rc == 0:
            data["aplay_devices"] = aplay.strip()[:400]

        # ALSA dmesg
        rc, alsa_dmesg = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'alsa|snd_|sound.*card|audio.*fail' | tail -10"
        )
        if rc == 0 and alsa_dmesg.strip():
            data["alsa_dmesg"] = alsa_dmesg.strip().splitlines()[:8]

        card_count = len([l for l in data.get("alsa_cards", "").splitlines() if l.strip()])

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=True,
            data=data,
            message=f"ALSA: {card_count} sound card(s)",
        )


@register_probe(DOMAIN, tier=ProbeTier.STANDARD, description="ASoC platform/codec links", timeout=20.0)
class ASoCProbe(ProbeBase):
    """Check ASoC machine driver, DAI links, and codec I2C binding."""

    def run(self, runner: Any, board_profile: Any) -> ProbeResult:
        data: dict = {}

        # ASoC machine
        rc, asoc_machine = runner.exec_command(
            "cat /sys/kernel/debug/asoc/components 2>/dev/null || "
            "cat /proc/asound/*/codec* 2>/dev/null | head -20"
        )
        if rc == 0 and asoc_machine.strip():
            data["asoc_components"] = asoc_machine.strip()[:400]

        # DAI links
        rc, dai_links = runner.exec_command(
            "cat /sys/kernel/debug/asoc/*/dai_links 2>/dev/null | head -30"
        )
        if rc == 0 and dai_links.strip():
            data["dai_links"] = dai_links.strip()[:400]

        # I2C codec binding (common pattern: es8316, da7213, rt5640, nau8825...)
        rc, i2c_codecs = runner.exec_command(
            "i2cdetect -l 2>/dev/null | head -5; "
            "dmesg 2>/dev/null | grep -iE 'codec|i2s|sai.*dai|dai.*link' | tail -10"
        )
        if rc == 0 and i2c_codecs.strip():
            data["codec_i2c"] = i2c_codecs.strip()[:300]

        # dmesg ASoC errors
        rc, asoc_err = runner.exec_command(
            "dmesg 2>/dev/null | grep -iE 'asoc.*error|codec.*probe|dai.*fail' | tail -5"
        )
        if rc == 0 and asoc_err.strip():
            data["asoc_errors"] = asoc_err.strip().splitlines()[:5]

        errors = data.get("asoc_errors", [])

        return ProbeResult(
            probe_name=self.__class__.__name__,
            domain=DOMAIN,
            passed=len(errors) == 0,
            data=data,
            message=f"ASoC: {'errors detected' if errors else 'no errors'}",
        )

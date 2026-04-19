"""test_gpu_rules.py — Phase 2b: gpu.yaml (10 tests)"""
from pathlib import Path
from soctriage.core.token_rule import TokenContext, TokenRuleRegistry

YAML = Path("soctriage/core/token_rules/gpu.yaml")

def _r():
    r = TokenRuleRegistry(); r.load_yaml(YAML); return r
def _ctx(recent_types=None):
    return TokenContext(1, "any", "unknown", [], recent_types or [])

def test_reset_event():           assert _r().match("GPU reset begin!", _ctx()) == "reset_event"
def test_reset_event_amdgpu():    assert _r().match("amdgpu: gpu recovery proceeding", _ctx()) == "reset_event"
def test_timeout_event():         assert _r().match("ring timeout detected", _ctx()) == "timeout_event"
def test_fence_timeout():         assert _r().match("fence timeout on ring gfx_0", _ctx()) == "timeout_event"
def test_sync_fence_event():      assert _r().match("dma_fence: signaling error", _ctx()) == "sync_fence_event"
def test_gem_event():             assert _r().match("GEM object lookup failed", _ctx()) == "gem_event"
def test_gfx_cp_event():          assert _r().match("CP_RB_RPTR value mismatch", _ctx()) == "gfx_cp_event"
def test_gpu_event_generic():     assert _r().match("[drm] amdgpu: ring gfx_0 timed out", _ctx()) in ("timeout_event", "gpu_event")
def test_display_event():         assert _r().match("DPU: underflow detected on CRTC", _ctx()) == "display_event"
def test_encoder_event():         assert _r().match("VCN: timeout on encode job", _ctx()) == "encoder_event"

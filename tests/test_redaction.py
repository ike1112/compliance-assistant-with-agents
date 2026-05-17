"""Redaction contract: fake PAN/email masked on the emitted trace path;
non-card long numbers stay visible (anti-over-redaction).

The Bedrock model-invocation-logging path is made PAN-safe separately
(infra: raw text/image/embedding/video data delivery disabled — see
infra/tests/test_observability_stack.py). This test covers the
in-process span/log path that tracing.redact governs.
"""
from compliance_assistant.tracing import Tracer, redact

# Luhn-valid test card numbers (the canonical Visa test PAN).
_PAN_PLAIN = "4111111111111111"
_PAN_SPACED = "4111 1111 1111 1111"
_PAN_DASHED = "4111-1111-1111-1111"
_PAN_DOTTED = "4111.1111.1111.1111"
_PAN_SLASHED = "4111/1111/1111/1111"
_EMAIL = "alice@example.com"
# 16 ones is NOT Luhn-valid → a long numeric id that must stay visible.
_NON_PAN_ID = "1111111111111111"
_REQUEST_ID = "req-2026-0517-000123456789"


def test_pan_forms_and_email_are_masked():
    for pan in (_PAN_PLAIN, _PAN_SPACED, _PAN_DASHED,
                _PAN_DOTTED, _PAN_SLASHED):
        out = redact(f"card on file: {pan} end")
        assert pan not in out, f"raw PAN survived: {pan!r}"
        assert "[REDACTED-PAN]" in out
    out = redact(f"contact {_EMAIL} please")
    assert _EMAIL not in out and "[REDACTED-EMAIL]" in out


def test_multi_separator_and_newline_pan_forms_are_masked():
    # codex/security: a PAN split by a double space or a newline (more
    # than one separator between groups) must still be caught.
    for pan in ("4111  1111 1111 1111", "4111\n1111 1111 1111",
                "4111 - 1111 . 1111 / 1111"):
        out = redact(f"pan: {pan} .")
        assert "[REDACTED-PAN]" in out
        assert "4111" not in out.replace("[REDACTED-PAN]", "")


def test_luhn_prefix_inside_a_longer_digit_run_is_not_partially_masked():
    # codex F-002: a Luhn-valid 16-digit prefix glued to more digits is
    # NOT a card; the right (?!\d) boundary must stop a partial
    # [REDACTED-PAN]<tail> mask. The whole 20-digit run is non-card and
    # must stay fully visible.
    longer = _PAN_PLAIN + "9999"          # 20 digits, not a card
    out = redact(f"identifier {longer} here")
    assert "[REDACTED-PAN]" not in out, f"partial mask leaked: {out!r}"
    assert longer in out


def test_non_luhn_long_numbers_stay_visible():
    # Over-redaction would destroy observability of legitimate ids.
    out = redact(f"trace id {_NON_PAN_ID} and {_REQUEST_ID}")
    assert _NON_PAN_ID in out, "non-Luhn 16-digit id was wrongly masked"
    assert _REQUEST_ID in out, "request id was wrongly masked"
    assert "[REDACTED-PAN]" not in out


def test_redaction_applied_through_a_built_span():
    # A span built from leaking content must be masked before record.
    t = Tracer()
    s = t._ensure("researcher")
    s["input"] = redact(f"lookup for {_EMAIL}")
    s["output"] = redact(f"found PAN {_PAN_SPACED} in a document")
    s["tool_calls"] = [{"tool": "BedrockInvokeAgentTool",
                        "input": redact(f"pan {_PAN_DASHED}")}]
    blob = s["input"] + s["output"] + str(s["tool_calls"])
    assert _EMAIL not in blob and _PAN_SPACED not in blob \
        and _PAN_DASHED not in blob
    assert "[REDACTED-EMAIL]" in blob and "[REDACTED-PAN]" in blob

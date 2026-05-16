"""render_citations: deterministic, de-duplicated, never raises."""
from compliance_assistant.citations import render_citations

_TRACE = {
    "citations": [
        {
            "retrievedReferences": [
                {
                    "content": {"text": "PCI DSS 4.0 requires MFA for all access."},
                    "location": {"s3Location": {"uri": "s3://corpus/pci-dss-4.pdf"}},
                },
                {
                    "content": {"text": "Logs must be retained 12 months."},
                    "location": {"s3Location": {"uri": "s3://corpus/pci-dss-4.pdf"}},
                },
            ]
        }
    ]
}


def test_renders_sorted_deduped_sources():
    out = render_citations(_TRACE)
    assert out.startswith("## Sources")
    assert "s3://corpus/pci-dss-4.pdf" in out
    assert "MFA" in out and "12 months" in out


def test_is_order_independent():
    rev = {
        "citations": [
            {
                "retrievedReferences": list(
                    reversed(_TRACE["citations"][0]["retrievedReferences"])
                )
            }
        ]
    }
    assert render_citations(_TRACE) == render_citations(rev)


def test_empty_trace_returns_placeholder():
    assert render_citations({}) == render_citations({"citations": []})
    assert "No grounded sources" in render_citations({})


def test_malformed_trace_never_raises():
    for bad in [None, "x", {"citations": "nope"}, {"citations": [None]}, 42]:
        out = render_citations(bad)
        assert out.startswith("## Sources")

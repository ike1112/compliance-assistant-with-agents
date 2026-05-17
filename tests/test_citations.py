"""render_citations: deterministic, de-duplicated, never raises.

This suite is mutation-targeted: the quality gate runs only this file
against compliance_assistant.citations, so every behaviour that a mutant
could flip is pinned with an exact-value assertion — truncation boundary,
whitespace collapse, uri fallback chain, dedup identity, sort ordering,
the empty/placeholder string, and the _iter_references guard clauses.
"""
from compliance_assistant.citations import (
    _NO_SOURCES,
    _iter_references,
    render_citations,
)

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


def _trace(refs):
    return {"citations": [{"retrievedReferences": refs}]}


def _ref(uri=None, text="snippet", loc_type=None):
    location = {}
    if uri is not None:
        location["s3Location"] = {"uri": uri}
    if loc_type is not None:
        location["type"] = loc_type
    return {"content": {"text": text}, "location": location}


# --- original behaviour ------------------------------------------------

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
    assert render_citations({}) == _NO_SOURCES
    assert _NO_SOURCES == "## Sources\n\n_No grounded sources returned._"


def test_malformed_trace_never_raises():
    for bad in [None, "x", {"citations": "nope"}, {"citations": [None]}, 42]:
        assert render_citations(bad) == _NO_SOURCES


# --- truncation boundary (len > 200 -> [:197] + "...") -----------------

def test_long_snippet_truncated_to_exactly_200():
    long = "A" * 250
    out = render_citations(_trace([_ref("s3://x", long)]))
    body = out.splitlines()[-1]
    rendered = body.split(" — ", 1)[1]
    assert rendered == "A" * 197 + "..."
    assert len(rendered) == 200


def test_snippet_exactly_200_not_truncated():
    s = "B" * 200
    out = render_citations(_trace([_ref("s3://x", s)]))
    assert "B" * 200 in out and "..." not in out


def test_snippet_201_is_truncated():
    out = render_citations(_trace([_ref("s3://x", "C" * 201)]))
    assert out.endswith("...")
    assert "C" * 197 + "..." in out


# --- whitespace collapse ----------------------------------------------

def test_whitespace_is_collapsed():
    out = render_citations(_trace([_ref("s3://x", "a  b\n\tc   d ")]))
    assert "— a b c d" in out


# --- uri fallback chain: s3 -> type -> "unknown source" ----------------

def test_uri_prefers_s3_location():
    out = render_citations(_trace([_ref("s3://bucket/key", "t")]))
    assert "`s3://bucket/key`" in out


def test_uri_falls_back_to_location_type():
    out = render_citations(_trace([_ref(None, "t", loc_type="WEB")]))
    assert "`WEB`" in out
    assert "unknown source" not in out


def test_uri_falls_back_to_unknown_source():
    out = render_citations(_trace([_ref(None, "t")]))
    assert "`unknown source`" in out


# --- dedup identity ----------------------------------------------------

def test_identical_entries_deduped_once():
    out = render_citations(_trace([_ref("s3://x", "same"), _ref("s3://x", "same")]))
    assert out.count("`s3://x`") == 1
    assert out.splitlines()[-1].startswith("1.")


def test_same_uri_different_snippet_kept_separate():
    out = render_citations(_trace([_ref("s3://x", "one"), _ref("s3://x", "two")]))
    assert "1. `s3://x` — one" in out
    assert "2. `s3://x` — two" in out


# --- sort ordering + numbering ----------------------------------------

def test_entries_sorted_and_numbered():
    out = render_citations(_trace([_ref("s3://b", "zz"), _ref("s3://a", "yy")]))
    lines = out.splitlines()
    assert lines[0] == "## Sources"
    assert lines[1] == ""
    assert lines[2] == "1. `s3://a` — yy"
    assert lines[3] == "2. `s3://b` — zz"


def test_empty_snippet_renders_without_dash():
    out = render_citations(_trace([_ref("s3://x", "")]))
    assert out.splitlines()[-1] == "1. `s3://x`"


# --- _iter_references guard clauses ------------------------------------

def test_iter_references_non_dict_yields_nothing():
    assert list(_iter_references(None)) == []
    assert list(_iter_references("x")) == []
    assert list(_iter_references(42)) == []


def test_iter_references_skips_non_dict_citation_and_ref():
    assert list(_iter_references({"citations": [None, "x"]})) == []
    assert list(_iter_references({"citations": [{"retrievedReferences": [None]}]})) == []


def test_iter_references_handles_missing_keys():
    # citation without retrievedReferences, ref without content/location
    assert list(_iter_references({"citations": [{}]})) == []
    got = list(_iter_references(_trace([{}])))
    assert got == [("unknown source", "")]


def test_none_collections_do_not_raise():
    assert render_citations({"citations": None}) == _NO_SOURCES
    assert render_citations(
        _trace([{"content": None, "location": None}])
    ) == "## Sources\n\n1. `unknown source`"

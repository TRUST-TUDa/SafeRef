"""
parsing.py

PDF -> structured citation records. Zero ML dependencies (just PyMuPDF +
stdlib re).
"""

import re
from pathlib import Path

import fitz

# ══════════════════════════════════════════════════════════════════════════════
# Parser internals  (inlined — no external module dependencies)
# ══════════════════════════════════════════════════════════════════════════════

# ── Constants ─────────────────────────────────────────────────────────────────

_REFERENCE_HEADING = re.compile(
    r"^\s*(references|bibliography|works cited)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_BODY_CITATION = re.compile(r"\[([0-9,\-–—\s]+)\]")

_COMPOUND_SUFFIXES = {
    "centered", "based", "driven", "aware", "oriented", "specific", "related",
    "dependent", "independent", "like", "free", "friendly", "rich", "poor",
    "scale", "level", "order", "class", "type", "style", "wise", "fold",
    "shot", "step", "time", "world", "source", "domain", "task", "modal",
    "intensive", "efficient", "agnostic", "invariant", "sensitive", "grained",
    "agent", "site",
}

_MID_SENTENCE_ABBREVS = {"vs", "eg", "ie", "cf", "fig", "figs", "eq", "eqs", "sec", "ch", "pt", "no"}

_AUTHOR_LIST_PATTERNS = [
    re.compile(r"^[A-Z]{2,}\s*,\s*[A-Z]\.\s*,\s*[A-Z]{2,}\s*,\s*[A-Z]\."),
    re.compile(r"^[A-Z]{2,}\s*,\s*[A-Z]\.\s*,?\s*AND\s+[A-Z]"),
    re.compile(r"^[A-Z]{2,}\s*,\s*AND\s+[A-Z]\.\s*[A-Z]"),
    re.compile(r"^[A-Z]{2,}\s+[A-Z]{2,}\s+AND\s+[A-Z]\.\s*[A-Z]"),
    re.compile(r"^[A-Z]{2,}\s+AND\s+[A-Z]\.\s*[A-Z]{2,}\s*,"),
    re.compile(r"^[A-Z]\s*[¨´`]\s*[A-Z]+\s*,\s*[A-Z]\."),
    re.compile(r"^[A-Z]{1,3},\s+[A-Z][a-z]+\s+[A-Z][a-z]+,\s+[A-Z][a-z]+\s+[A-Z][a-z]+"),
    re.compile(r"^[A-Z]\.(?:\s*[A-Z]\.)?\s+[A-Z][a-z]+,\s+[A-Z]\.(?:\s*[A-Z]\.)?\s+[A-Z][a-z]+,\s+and\s+[A-Z]\.", re.IGNORECASE),
]

_VENUE_ONLY_PATTERNS = [
    re.compile(r"^(?:SIAM|IEEE|ACM|PNAS)\s+(?:Journal|Transactions|Review)", re.IGNORECASE),
    re.compile(r"^(?:Journal|Transactions|Proceedings)\s+(?:of|on)\s+", re.IGNORECASE),
    re.compile(r"^Advances\s+in\s+Neural", re.IGNORECASE),
]

_NON_REFERENCE_PATTERNS = [
    re.compile(r"^[•\-]\s+(?:The answer|Released models|If you are using)", re.IGNORECASE),
    re.compile(r"^We gratefully acknowledge", re.IGNORECASE),
]

_VENUE_AFTER_PUNCT = re.compile(
    # `:?` handles a colon-joined subtitle between the sentence-ending
    # punctuation and the venue name, e.g. "...fail?: Advances in Neural..."
    r"[?!]:?\s+(?:International|Proceedings|Conference|Workshop|Symposium|Association|"
    r"The\s+\d{4}\s+Conference|Nations|Annual|IEEE|ACM|USENIX|AAAI|NeurIPS|ICML|ICLR|"
    r"CVPR|ICCV|ECCV|ACL|EMNLP|NAACL|Advances\s+in|Journal\s+of|Transactions\s+of|"
    r"Transactions\s+on|Communications\s+of)"
)

_GREEK = {
    "α":"alpha","β":"beta","γ":"gamma","δ":"delta","ε":"epsilon","ζ":"zeta",
    "η":"eta","θ":"theta","ι":"iota","κ":"kappa","λ":"lambda","μ":"mu",
    "ν":"nu","ξ":"xi","ο":"o","π":"pi","ρ":"rho","σ":"sigma","ς":"sigma",
    "τ":"tau","υ":"upsilon","φ":"phi","χ":"chi","ψ":"psi","ω":"omega",
    "Α":"alpha","Β":"beta","Γ":"gamma","Δ":"delta","Ε":"epsilon","Ζ":"zeta",
    "Η":"eta","Θ":"theta","Ι":"iota","Κ":"kappa","Λ":"lambda","Μ":"mu",
    "Ν":"nu","Ξ":"xi","Ο":"o","Π":"pi","Ρ":"rho","Σ":"sigma",
    "Τ":"tau","Υ":"upsilon","Φ":"phi","Χ":"chi","Ψ":"psi","Ω":"omega",
}

_DIACRITICS = {
    ("¨","A"):"Ä",("¨","a"):"ä",("¨","E"):"Ë",("¨","e"):"ë",
    ("¨","I"):"Ï",("¨","i"):"ï",("¨","O"):"Ö",("¨","o"):"ö",
    ("¨","U"):"Ü",("¨","u"):"ü",("¨","Y"):"Ÿ",("¨","y"):"ÿ",
    ("´","A"):"Á",("´","a"):"á",("´","E"):"É",("´","e"):"é",
    ("´","I"):"Í",("´","i"):"í",("´","O"):"Ó",("´","o"):"ó",
    ("´","U"):"Ú",("´","u"):"ú",("´","N"):"Ń",("´","n"):"ń",
    ("´","C"):"Ć",("´","c"):"ć",("´","S"):"Ś",("´","s"):"ś",
    ("´","Z"):"Ź",("´","z"):"ź",("´","Y"):"Ý",("´","y"):"ý",
    ("`","A"):"À",("`","a"):"à",("`","E"):"È",("`","e"):"è",
    ("`","I"):"Ì",("`","i"):"ì",("`","O"):"Ò",("`","o"):"ò",
    ("`","U"):"Ù",("`","u"):"ù",
    ("~","A"):"Ã",("~","a"):"ã",("˜","A"):"Ã",("˜","a"):"ã",
    ("~","N"):"Ñ",("~","n"):"ñ",("˜","N"):"Ñ",("˜","n"):"ñ",
    ("~","O"):"Õ",("~","o"):"õ",("˜","O"):"Õ",("˜","o"):"õ",
    ("ˇ","C"):"Č",("ˇ","c"):"č",("ˇ","S"):"Š",("ˇ","s"):"š",
    ("ˇ","Z"):"Ž",("ˇ","z"):"ž",("ˇ","E"):"Ě",("ˇ","e"):"ě",
    ("ˇ","R"):"Ř",("ˇ","r"):"ř",("ˇ","N"):"Ň",("ˇ","n"):"ň",
    ("^","A"):"Â",("^","a"):"â",("^","E"):"Ê",("^","e"):"ê",
    ("^","I"):"Î",("^","i"):"î",("^","O"):"Ô",("^","o"):"ô",
    ("^","U"):"Û",("^","u"):"û",
}

_SPACE_BEFORE_DIACRITIC = re.compile(r"([A-Za-z])\s+([¨´`~˜ˇ^])")
_SEPARATED_DIACRITIC    = re.compile(r"([¨´`~˜ˇ^])\s*([A-Za-z])")

# ── Low-level text fixers ──────────────────────────────────────────────────────

def _transliterate_greek(text):
    for g, l in _GREEK.items():
        text = text.replace(g, l)
    return text

def _fix_diacritics(text):
    text = _SPACE_BEFORE_DIACRITIC.sub(r"\1\2", text)
    def _rep(m):
        c = _DIACRITICS.get((m.group(1), m.group(2)))
        return c if c else m.group(2)
    return _SEPARATED_DIACRITIC.sub(_rep, text)

def _expand_ligatures(text):
    for lig, exp in {"ﬀ":"ff","ﬁ":"fi","ﬂ":"fl","ﬃ":"ffi","ﬄ":"ffl","ﬅ":"st","ﬆ":"st"}.items():
        text = text.replace(lig, exp)
    return text

def _fix_hyphenation(text):
    text = re.sub(r"\bstate-\s+of-the-art\b", "state-of-the-art", text, flags=re.IGNORECASE)
    text = re.sub(r"\bagent-\s+generated\b",  "agent-generated",  text, flags=re.IGNORECASE)
    text = re.sub(r"\bai-\s+generated\b",     "ai-generated",     text, flags=re.IGNORECASE)
    def _rep(m):
        before, after_c, after_r = m.group(1), m.group(2), m.group(3)
        after = after_c + after_r
        if before.isdigit():
            return f"{before}-{after}"
        al = after.lower()
        for s in _COMPOUND_SUFFIXES:
            if al == s or al.startswith(s+" ") or al.startswith(s+","):
                return f"{before}-{after}"
        if al.rstrip(".,;:") in _COMPOUND_SUFFIXES:
            return f"{before}-{after}"
        return f"{before}{after}"
    text = re.sub(r"(\w)-\s+(\w)(\w*)", _rep, text)
    text = re.sub(r"(\w)- (\w)(\w*)", _rep, text)
    return text

# ── Predicate helpers ─────────────────────────────────────────────────────────

def _is_author_list(text):
    return any(p.match(text) for p in _AUTHOR_LIST_PATTERNS)

def _is_venue_only(text):
    return any(p.match(text) for p in _VENUE_ONLY_PATTERNS)

def _is_non_ref(text):
    return any(p.match(text) for p in _NON_REFERENCE_PATTERNS)

def _truncate_at_venue(title):
    m = _VENUE_AFTER_PUNCT.search(title)
    return title[:m.start()+1].strip() if m else title

def _clean_doi(doi):
    doi = doi.rstrip(".,;:")
    while doi.endswith(")"):
        if doi.count(")") > doi.count("("):
            doi = doi[:-1].rstrip(".,;:")
        else:
            break
    while doi.endswith("]") and doi.count("]") > doi.count("["):
        doi = doi[:-1].rstrip(".,;:")
    while doi.endswith("}") and doi.count("}") > doi.count("{"):
        doi = doi[:-1].rstrip(".,;:")
    return doi

# ── DOI / arXiv extractors ────────────────────────────────────────────────────

def _extract_doi(text):
    t = re.sub(r"(10\.\d{4,}/[^\s\]>,]+\.)\s*\n\s*(\d{3,})", r"\1\2", text)
    t = re.sub(r"(10\.\d{4,}/[^\s\]>,]+\d)\s*\n\s*(\d+(?:\.\d+)*)", r"\1\2", t)
    t = re.sub(r"(10\.\d{4,}/[^\s\]>,]+-)\s*\n\s*(\S+)", r"\1\2", t)
    t = re.sub(r"(https?://(?:dx\.)?doi\.org/10\.\d{4,}/[^\s\]>,]+\.)\s*\n\s*(\d+)", r"\1\2", t, flags=re.IGNORECASE)
    t = re.sub(r"(https?://(?:dx\.)?doi\.org/10\.\d{4,}/[^\s\]>,]+\d)\s*\n\s*(\d[^\s\]>,]*)", r"\1\2", t, flags=re.IGNORECASE)
    m = re.search(r"https?://(?:dx\.)?doi\.org/(10\.\d{4,}/[^\s\]>},]+)", t, re.IGNORECASE)
    if m:
        return _clean_doi(m.group(1))
    m = re.search(r"10\.\d{4,}/[^\s\]>},]+", t)
    if m:
        return _clean_doi(m.group(0))
    return None

def _extract_arxiv_id(text):
    t = re.sub(r"(arXiv:\d{4}\.)\s*\n\s*(\d+)", r"\1\2", text, flags=re.IGNORECASE)
    t = re.sub(r"(arxiv\.org/abs/\d{4}\.)\s*\n\s*(\d+)", r"\1\2", t, flags=re.IGNORECASE)
    for pat in [
        r"arXiv[:\s]+(\d{4}\.\d{4,5}(?:v\d+)?)",
        r"arxiv\.org/abs/(\d{4}\.\d{4,5}(?:v\d+)?)",
        r"arXiv[:\s]+([a-z-]+/\d{7}(?:v\d+)?)",
        r"arxiv\.org/abs/([a-z-]+/\d{7}(?:v\d+)?)",
    ]:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            return m.group(1)
    return None

# ── Reference section finder ──────────────────────────────────────────────────

def _strip_running_headers(text):
    venue_pat  = r"^[A-Z][A-Z\s&]+\s*['']\d{2},\s+[A-Z][a-z]+\s+\d{1,2}[–\-]+\d{1,2},\s+\d{4},\s+[A-Z][A-Za-z\s,]+$"
    author_pat = r"^[A-Z]\.?[A-Z]?\s+[A-Z][a-z]+(?:,\s+[A-Z]\.?\s*[A-Z]?\.?\s*[A-Z][a-z]+)*(?:,?\s+and\s+[A-Z]\.?\s*[A-Z]?\.?\s*[A-Z][a-z]+)?$"
    math_pat   = r"^[A-Z][A-Z\s\-]+$"
    page_pat   = r"^\d{1,4}$"
    lines, out, i = text.split("\n"), [], 0
    while i < len(lines):
        ln = lines[i].strip()
        if re.match(venue_pat, ln):
            if out and len(out[-1].strip()) > 20:
                prev = out[-1].strip()
                if not re.match(r"^\[\d+\]", prev) and not re.match(r"^\d+\.", prev):
                    out.pop()
            i += 1; continue
        if re.match(author_pat, ln) and len(ln) < 100:
            i += 1; continue
        if re.match(math_pat, ln) and len(ln.split()) >= 3 and len(ln) > 15:
            i += 1; continue
        if re.match(page_pat, ln):
            i += 1; continue
        out.append(lines[i]); i += 1
    return "\n".join(out)

def _strip_page_headers(text):
    """Remove conference/journal page headers that PDF extraction embeds between references."""
    # USENIX: "USENIX Association\n34th USENIX Security Symposium 2477"
    text = re.sub(
        r"(?:USENIX\s+Association\s*\n?\s*)?(?:\d+\s+)?\d+(?:st|nd|rd|th)\s+USENIX\s+"
        r"(?:Security\s+Symposium|OSDI|ATC|NSDI|HotCloud|WOOT|FAST|LISA|SREcon)"
        r"(?:\s+USENIX\s+Association)?(?:\s+\d+)?",
        "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"(?m)^\s*USENIX\s+Association\s*$", "\n", text)
    # IEEE S&P / EuroS&P
    text = re.sub(
        r"(?m)^\s*(?:\d+\s+)?(?:IEEE\s+)?(?:Symposium\s+on\s+Security\s+and\s+Privacy|S&P|EuroS&P)"
        r"(?:\s+\d{4})?(?:\s+\d+)?\s*$", "\n", text)
    # NDSS
    text = re.sub(
        r"(?m)^\s*(?:\d+\s+)?(?:Network\s+and\s+Distributed\s+System\s+Security\s+Symposium|NDSS)"
        r"(?:\s+\d{4})?(?:\s+\d+)?\s*$", "\n", text)
    # CCS
    text = re.sub(
        r"(?m)^\s*(?:\d+\s+)?(?:ACM\s+)?(?:Conference\s+on\s+Computer\s+and\s+Communications\s+Security|CCS)"
        r"(?:\s+['’]?\d{{2,4}})?(?:\s+\d+)?\s*$".replace("{{", "{").replace("}}", "}"),
        "\n", text)
    # ACM/ML conference date-line headers: "ASIA CCS '26, June 01–05, 2026, Bangalore, India"
    text = re.sub(
        r"(?:ASIA\s+CCS|CHI|UIST|CSCW|MobiSys|MobiCom|SenSys|UbiComp|IMC|SIGCOMM|SOSP|OSDI|PLDI|POPL|"
        r"ICSE|FSE|ASE|ISSTA|WWW|KDD|SIGIR|SIGMOD|VLDB|ICML|NeurIPS|ICLR|CVPR|ICCV|ECCV|ACL|EMNLP|NAACL)"
        r"\s*['’]?\d{2}(?:,\s*(?:January|February|March|April|May|June|July|August|September|"
        r"October|November|December)\s+\d{1,2}[-–]\d{1,2},\s*\d{4})?,\s*[A-Za-z\s,.]+",
        "\n", text, flags=re.IGNORECASE)
    return text


def _find_references_section(text):
    # Use LAST "References" header — earlier occurrences may be table column headers
    all_matches = []
    for hdr in [r"\n\s*References\s*\n", r"\n\s*REFERENCES\s*\n",
                r"\n\s*Bibliography\s*\n", r"\n\s*BIBLIOGRAPHY\s*\n",
                r"\n\s*Works Cited\s*\n"]:
        all_matches.extend(re.finditer(hdr, text, re.IGNORECASE))
    if all_matches:
        m = max(all_matches, key=lambda x: x.start())
        start = m.end()
        end_icase = [
            r"\n\s*(?:Appendix|Acknowledge?ments?|Supplementary|Ethics\s+Statement|Ethical\s+Considerations|Broader\s+Impact|Paper\s+Checklist|Checklist|Contents)\b",
            r"(?:\.\s*){5,}",
        ]
        end_case = [r"\n\s*[A-Z]\s+[A-Z][a-zA-Z-]+(?:\s+[a-zA-Z-]+)*\s*\n"]
        ref_end = len(text)
        for ep in end_icase:
            em = re.search(ep, text[start:], re.IGNORECASE)
            if em:
                ref_end = min(ref_end, start + em.start())
        for ep in end_case:
            em = re.search(ep, text[start:])
            if em:
                ref_end = min(ref_end, start + em.start())
        return _strip_running_headers(text[start:ref_end])
    return _strip_running_headers(text[int(len(text)*0.7):])

# ── Reference segmenter ───────────────────────────────────────────────────────

def _segment_references(ref_text, _debug=None):
    # Strip venue page headers before trying any strategy
    ref_text = _strip_page_headers(ref_text)
    # Ligatures (fi/fl/ffi/...) render as single non-ASCII glyphs that fall
    # outside every name/title regex's character class below -- expand them
    # first so e.g. "Chaffin" (extracted as "Chafﬁn") doesn't silently break
    # an author-list match anywhere it appears.
    ref_text = _expand_ligatures(ref_text)

    # Truncate at appendix/supplementary boundaries embedded after refs
    bounds = [
        r"\n\s*(?:APPENDIX|Appendix)\s*[A-Z]?\s*[\n:.]",
        r"\n\s*(?:SUPPLEMENTARY|Supplementary)\s+(?:MATERIAL|Material|INFORMATION|Information)",
        r"\n\s*[A-Z]\s*\n\s*(?:Additional|Detailed|Extended|Supplemental|Proof|Experimental|Implementation|Benchmark|Dataset|Ablation|Hyperparameter)",
        r"\n\s*[A-Z]\s*[\.:]?\s+(?:Additional|Detailed|Extended|Supplemental|Proof|Experimental|Implementation|Benchmark|Dataset|Ablation|Hyperparameter)\s+",
        r"\n\s*\(\d{1,3}\)\s*\n[^\n]*=",
    ]
    earliest = len(ref_text)
    for bp in bounds:
        bm = re.search(bp, ref_text)
        if bm and bm.start() > 500 and bm.start() < earliest:
            earliest = bm.start()
    if earliest < len(ref_text):
        ref_text = ref_text[:earliest].strip()

    candidates = []  # list of (name, specificity, refs)

    # ── IEEE [N] — must start at [1] and be sequential ─────────────────────────
    _ieee_re = re.compile(r"(?:^|\n|[.\]0-9])\s*\[(\d+)\]\s*")
    ieee_caps = list(_ieee_re.finditer(ref_text))
    if len(ieee_caps) >= 3:
        first_nums = [int(m.group(1)) for m in ieee_caps[:5]]
        if first_nums[0] == 1 and all(first_nums[i] == first_nums[i-1]+1 for i in range(1, len(first_nums))):
            refs = []
            for i, m in enumerate(ieee_caps):
                end = ieee_caps[i+1].start() if i+1 < len(ieee_caps) else len(ref_text)
                c = ref_text[m.end():end].strip()
                if c:
                    refs.append(c)
            if refs:
                candidates.append(("ieee", 1.0, refs))

    # ── Alphabetic [ABC20] ─────────────────────────────────────────────────────
    alpha = list(re.finditer(r"\n\s*\[([A-Za-z+]+\d{2,4}[a-z]?)\]\s*", ref_text))
    if len(alpha) >= 3:
        refs = []
        for i, m in enumerate(alpha):
            end = alpha[i+1].start() if i+1 < len(alpha) else len(ref_text)
            c = ref_text[m.end():end].strip()
            if c:
                refs.append(c)
        if refs:
            candidates.append(("alpha", 1.0, refs))

    # ── Numbered N. — 1–3 digits only (avoids 4-digit years), must start at 1 ─
    nums_m = list(re.finditer(r"(?:^|\n)\s*(\d{1,3})\.\s+", ref_text))
    if len(nums_m) >= 3:
        first = [int(m.group(1)) for m in nums_m[:5]]
        if first[0] == 1 and all(first[i] == first[i-1]+1 for i in range(1, len(first))):
            refs = []
            for i, m in enumerate(nums_m):
                end = nums_m[i+1].start() if i+1 < len(nums_m) else len(ref_text)
                c = ref_text[m.end():end].strip()
                if c:
                    refs.append(c)
            if refs:
                candidates.append(("numbered", 0.95, refs))

    # ── AAAI author-year ───────────────────────────────────────────────────────
    aaai_p  = r"([a-z0-9)]|[A-Z]{2})\.\n(?:\d{1,4}\n)?\s*(?!In\s)([A-Z][a-zA-ZÀ-ɏ]+(?:[ -][A-Za-zÀ-ɏ]+)?,\s+[A-Z]\.)"
    aaai_op = r"([a-z0-9)]|[A-Z]{2})\.\n(?:\d{1,4}\n)?\s*(?!In\s)([A-Z][a-zA-ZÀ-ɏ]+(?:\s+[A-Z][a-zA-ZÀ-ɏ]+)+\.\s+\d{4}[a-z]?\.)"
    all_a   = sorted(list(re.finditer(aaai_p, ref_text)) + list(re.finditer(aaai_op, ref_text)), key=lambda m: m.start())
    merged  = []
    for m in all_a:
        if not merged or m.start() - merged[-1].start() > 10:
            merged.append(m)
    if len(merged) >= 3:
        refs = []
        fr = ref_text[:merged[0].end(1)].strip()
        if fr and len(fr) > 20:
            refs.append(fr)
        for i, m in enumerate(merged):
            end = merged[i+1].end(1) if i+1 < len(merged) else len(ref_text)
            c = ref_text[m.start(2):end].strip()
            if c:
                refs.append(c)
        if refs:
            candidates.append(("aaai", 0.8, refs))

    # ── NeurIPS I. Surname style ───────────────────────────────────────────────
    neurips_p = r"(\.\s*)\n+([A-Z]\.(?:\s*[A-Z]\.)?\s+[A-Z][a-zA-ZÀ-ɏ-]+(?:\s+and\s+[A-Z]\.|,\s+[A-Z]\.))"
    neurips   = list(re.finditer(neurips_p, ref_text))
    if len(neurips) >= 5:
        refs = []
        fe = neurips[0].start() + len(neurips[0].group(1))
        fr = ref_text[:fe].strip()
        if fr and len(fr) > 20:
            refs.append(fr)
        for i, m in enumerate(neurips):
            s = m.start(2)
            e = (neurips[i+1].start() + len(neurips[i+1].group(1))) if i+1 < len(neurips) else len(ref_text)
            c = ref_text[s:e].strip()
            if c and len(c) > 20:
                refs.append(c)
        if refs:
            candidates.append(("neurips", 0.8, refs))

    # ── ML Full Name — "Eva E Stüeken," / "E. Pardoux," / "MM Locarnini," ─────
    ml_p = (
        r"((?:(?:19|20)\d{2}[a-z]?|html|pdf)\.\n+)"
        r"((?:[A-Z][a-z]+(?:\s+[A-Z](?:\.|[a-z]+)?)?\s+[A-Z][a-zA-ZÀ-ɏ\-]+"
        r"|[A-Z]\.(?:\s*[A-Z]\.)?\s+[A-Z][a-zA-ZÀ-ɏ\-]+"
        r"|[A-Z]{2,3}\s+[A-Z][a-zA-ZÀ-ɏ\-]+"
        r"|[A-Z]{4,}\s+[A-Z][a-z][a-zA-ZÀ-ɏ\-]*)(?:[,.]| and ))"
    )
    ml_matches = list(re.finditer(ml_p, ref_text))
    if len(ml_matches) >= 5:
        refs = []
        fe = ml_matches[0].start() + len(ml_matches[0].group(1))
        fr = ref_text[:fe].strip()
        if fr and len(fr) > 20:
            refs.append(fr)
        for i, m in enumerate(ml_matches):
            s = m.start(2)
            e = (ml_matches[i+1].start() + len(ml_matches[i+1].group(1))) if i+1 < len(ml_matches) else len(ref_text)
            c = ref_text[s:e].strip()
            if c and len(c) > 20:
                refs.append(c)
        if refs:
            candidates.append(("ml_fullname", 0.8, refs))

    # ── Full-name flowing (no numbering, no blank lines between refs) ─────────
    # For styles that print references back-to-back with no blank line and no
    # "[N]" marker: finds boundaries from content alone -- where a complete
    # "Name, Name, ..., and Name." (or "..., et al.") author block ends and
    # the next reference's title begins. A "full name" here tolerates
    # lowercase surname particles ("van den Driessche"), a fused-apostrophe
    # particle ("d'Autume"), and a bare one-letter initial ("M Saiful Bari")
    # -- one unhandled name shape anywhere in a long author list otherwise
    # breaks the match for the whole list.
    _NAME_PARTICLE = (
        r"(?:van|von|de|del|della|di|da|al|el|la|le|ben|ibn|mac|mc|"
        r"dos|das|der|den|ter|du|af|ten|op|zum|zur)"
    )
    _name_first = r"[A-Z][a-zA-ZÀ-ɏ'\-]*\.?"
    _name_token = rf"(?:{_name_first}|{_NAME_PARTICLE}|[a-z]['’][A-Z][a-zA-ZÀ-ɏ'\-]*)"
    _full_name = rf"{_name_first}(?:\s+{_name_token})+"
    fullname_flow_p = (
        rf"\.\s+((?:{_full_name},\s+)+(?:and\s+)?{_full_name}\."
        rf"|(?:{_full_name},\s+)+et\s+al\."
        rf"|{_full_name}\s+and\s+{_full_name}\.)"
        rf"\s+(?=[A-Z0-9])"
    )
    fullname_flow = list(re.finditer(fullname_flow_p, ref_text))
    if len(fullname_flow) >= 5:
        refs = []
        fr = ref_text[:fullname_flow[0].start(1)].strip()
        if fr and len(fr) > 20:
            refs.append(fr)
        for i, m in enumerate(fullname_flow):
            s = m.start(1)
            e = fullname_flow[i+1].start(1) if i+1 < len(fullname_flow) else len(ref_text)
            c = ref_text[s:e].strip()
            if c and len(c) > 20:
                refs.append(c)
        if refs:
            candidates.append(("fullname_flowing", 0.5, refs))

    # ── Springer (Year) inline ─────────────────────────────────────────────────
    lines = ref_text.split("\n")
    starts, pos = [], 0
    for ln in lines:
        if ln and re.match(r"^[A-Z]", ln) and not re.match(r"^\d+$", ln.strip()) and re.search(r"\(\d{4}[a-z]?\)", ln):
            starts.append(pos)
        pos += len(ln) + 1
    if len(starts) >= 5:
        refs = []
        for i, s in enumerate(starts):
            end = starts[i+1] if i+1 < len(starts) else len(ref_text)
            c = re.sub(r"\n+\d+\s*$", "", ref_text[s:end]).strip()
            if c and len(c) > 20:
                refs.append(c)
        if refs:
            candidates.append(("springer", 0.75, refs))

    # ── Econ style ,YYYY.\nAuthor ──────────────────────────────────────────────
    econ_p = r"[,)]\s*\d{4}[a-z]?\.\n+([A-Z][a-zA-ZÀ-ɏ]+(?:[ -][A-Za-zÀ-ɏ]+)*[,\s]+(?:[A-Z]\.?\s*)?[A-Z][a-zA-ZÀ-ɏ-]+)"
    econ   = list(re.finditer(econ_p, ref_text))
    if len(econ) >= 5:
        refs = []
        fr = ref_text[:econ[0].start() + econ[0].group().index("\n")].strip()
        pp = fr.rfind(".")
        if pp > 0:
            fr = fr[:pp+1].strip()
        if fr and len(fr) > 20:
            refs.append(fr)
        for i, m in enumerate(econ):
            s = m.start(1)
            if i+1 < len(econ):
                nm = econ[i+1]
                e  = nm.start() + nm.group().index("\n") + 1
            else:
                e = len(ref_text)
            c = re.sub(r"\n+\d+\s*$", "", ref_text[s:e]).strip()
            if c and len(c) > 20:
                refs.append(c)
        if refs:
            candidates.append(("econ", 0.75, refs))

    # ── Fallback: double-newline ───────────────────────────────────────────────
    fallback = [p.strip() for p in re.split(r"\n\s*\n", ref_text) if p.strip() and len(p.strip()) > 20]
    if fallback:
        candidates.append(("fallback", 0.3, fallback))

    if not candidates:
        if _debug is not None:
            _debug["strategy"] = None
            _debug["score"] = None
            _debug["candidates_tried"] = []
            _debug["ref_text_len"] = len(ref_text)
        return []

    # Score every candidate and return the best
    best_score, best_refs, best_name = -1.0, candidates[0][2], candidates[0][0]
    for name, specificity, refs in candidates:
        score = _score_segmentation(refs, ref_text, specificity)
        if score > best_score:
            best_score, best_refs, best_name = score, refs, name

    if _debug is not None:
        _debug["strategy"] = best_name
        _debug["score"] = round(best_score, 4)
        _debug["candidates_tried"] = [name for name, _, _ in candidates]
        _debug["ref_text_len"] = len(ref_text)

    return best_refs

# ── Author extractor ──────────────────────────────────────────────────────────

def _extract_authors(ref_text):
    ref_text = re.sub(r"\s+", " ", ref_text).strip()
    if re.match(r"^[—–\-]{2,}\s*,", ref_text):
        return ["__SAME_AS_PREVIOUS__"]
    quote_m  = re.search(r'["“”]', ref_text)
    spring_m = re.search(r"\s+\((\d{4}[a-z]?)\)\s+", ref_text)
    acm_m    = re.search(r"\.\s*((?:19|20)\d{2})\.\s*", ref_text)
    first_p  = -1
    for m in re.finditer(r"\. ", ref_text):
        pos = m.start()
        if pos > 0:
            cb = ref_text[pos-1]
            if cb.isupper() and (pos == 1 or not ref_text[pos-2].isalpha()):
                continue
            first_p = pos; break
    author_end = len(ref_text)
    if quote_m:   author_end = quote_m.start()
    elif spring_m: author_end = spring_m.start()
    elif acm_m:   author_end = acm_m.start() + 1
    elif first_p > 0: author_end = first_p
    sec = re.sub(r"[\.,;:]+$", "", ref_text[:author_end].strip()).strip()
    if not sec:
        return []
    if "; " in sec and re.search(r"[A-Z][a-z]+,\s+[A-Z]\.", sec):
        sec = re.sub(r";\s+and\s+", "; ", sec, flags=re.IGNORECASE)
        parts = [p.strip() for p in sec.split(";") if p.strip()]
        return [p for p in parts if p and len(p) > 2 and re.search(r"[A-Z]", p)][:15]
    sec = re.sub(r",?\s+and\s+", ", ", sec, flags=re.IGNORECASE)
    sec = re.sub(r"\s*&\s*", ", ", sec)
    sec = re.sub(r",?\s*et\s+al\.?", "", sec, flags=re.IGNORECASE)
    authors = []
    for part in [p.strip() for p in sec.split(",") if p.strip()]:
        if len(part) < 2 or re.search(r"\d", part):
            continue
        words = part.split()
        if len(words) > 5:
            continue
        lc = [w for w in words if w[0].islower() and w not in ("and","de","van","von","la","del","di")]
        if len(lc) > 1:
            continue
        if re.search(r"[A-Z]", part) and re.search(r"[a-z]", part) and len(part) > 2:
            authors.append(part.strip())
    return authors[:15]

# ── Title extractor ───────────────────────────────────────────────────────────

def _split_sentences(text):
    sentences, cur = [], 0
    for m in re.finditer(r"\.\s+", text):
        pos = m.start()
        if pos > 0:
            cb = text[pos-1]
            if cb.isupper() and (pos == 1 or not text[pos-2].isalpha()):
                after = text[m.end():]
                sc = r"[a-zA-ZÀ-ɏ''`´\-]"
                sp = r"(?:von|van|de|del|della|la|le|da|das|dos|der|den|ter|di|du|el|af|ten|op|zum|zur)"
                ap = (re.match(rf"^([A-Z]{sc}+)\s*,", after) or
                      re.match(rf"^([A-Z]{sc}+)\s+([A-Z][A-Z]?)\s*,", after) or
                      re.match(rf"^([A-Z]{sc}+)\s+[A-Z]{{1,2}},", after) or
                      re.match(r"^and\s+[A-Z]", after, re.IGNORECASE) or
                      re.match(r"^[A-Z]\.", after) or
                      re.match(r"^[A-Z]\.-[A-Z]\.", after) or
                      re.match(rf"^([A-Z]{sc}+)\.\s+[A-Z]", after) or
                      re.match(rf"^([A-Z]{sc}+)\s+and\s+[A-Z]", after, re.IGNORECASE) or
                      re.match(rf"^([A-Z]{sc}+)\s+([A-Z]{sc}+)\s*,", after) or
                      re.match(rf"^{sp}\s+[A-Z]", after, re.IGNORECASE) or
                      re.match(rf"^([A-Z]{sc}+)\s+([A-Z]{sc}+)\.", after) or
                      re.match(rf"^([A-Z]{sc}+)\.\s+\d", after) or
                      re.match(rf"^([A-Z]{sc}+)\.\s+[A-Z][a-z]+\s+[a-z]", after) or
                      re.match(rf"^[A-Z]\s+([A-Z]{sc}+)\s*,", after))
                if ap:
                    continue
            wb = pos - 1
            while wb > 0 and text[wb-1].isalpha():
                wb -= 1
            if text[wb:pos].lower() in _MID_SENTENCE_ABBREVS:
                continue
            after2 = text[m.end():]
            if after2 and after2[0].isdigit():
                continue
        sentences.append(text[cur:pos].strip())
        cur = m.end()
    if cur < len(text):
        sentences.append(text[cur:].strip())
    return sentences

def _clean_title(title, from_quotes=False):
    if not title:
        return ""
    title = _fix_hyphenation(title)
    if not from_quotes:
        for m in re.finditer(r"\.", title):
            pos = m.start()
            lp  = title.rfind(".", 0, pos)
            ls  = title.rfind(" ", 0, pos)
            seg = title[max(lp+1, ls+1, 0):pos]
            if len(seg) > 2 or (len(seg) == 2 and seg.isupper()):
                if pos+1 < len(title) and title[pos+1].isalpha():
                    continue
                if pos+2 < len(title) and title[pos+1] == " " and title[pos+2].isdigit():
                    continue
                title = title[:pos]; break
    inv = re.search(r"\?\s*[Ii]n:?\s+(?:[A-Z]|[12]\d{3}\s)", title)
    if inv: title = title[:inv.start()+1]
    qj  = re.search(r"[?!]\s+[A-Z][a-zA-Z\s&+®–—\-]+,\s*\d+\s*[(:]", title)
    if qj:  title = title[:qj.start()+1]
    qjv = re.search(r"[?!]\s+(?:IEEE\s+Trans[a-z.]*|ACM\s+Trans[a-z.]*|Automatica|J\.\s*[A-Z][a-z]+|[A-Z][a-z]+\.?\s+[A-Z][a-z]+\.?)\s+\d+\s*\(", title)
    if qjv: title = title[:qjv.start()+1]
    for pat in [
        r"\.\s*[Ii]n:\s+[A-Z].*$", r"\.\s*[Ii]n\s+[A-Z].*$",
        r"[.?!]\s*(?:Proceedings|Conference|Workshop|Symposium|IEEE|ACM|USENIX|AAAI|EMNLP|NAACL|arXiv|Available|CoRR|PACM[- ]\w+).*$",
        r"[.?!]\s*(?:Advances\s+in|Journal\s+of|Transactions\s+of|Transactions\s+on|Communications\s+of).*$",
        r"[.?!]\s+International\s+Journal\b.*$",
        r"\.\s*[A-Z][a-z]+\s+(?:Journal|Review|Transactions|Letters|advances|Processing|medica|Intelligenz)\b.*$",
        r"\.\s*(?:Patterns|Data\s+&\s+Knowledge).*$",
        r"[.,]\s+[A-Z][a-z]+\s+\d+[,\s].*$", r",\s*volume\s+\d+.*$",
        r",\s*\d+\s*\(\d+\).*$", r",\s*\d+\s*$", r"\.\s*\d+\s*$",
        r"\.\s*https?://.*$", r"\.\s*ht\s*tps?://.*$",
        r",\s*(?:vol\.|pp\.|pages).*$",
        r"\s+arXiv\s+preprint.*$", r"\s+arXiv:\d+.*$", r"\s+CoRR\s+abs/.*$",
        # Comma is required (not optional) so this only strips a trailing
        # "Title, October 2022" venue-date suffix -- a bare month+year with
        # no leading comma can be part of the title's own text (e.g. a legal
        # citation's enactment date, "... of 19 October 2022 on ..."), and
        # matching it there deleted the rest of the real title.
        r",\s*(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+(?:19|20)\d{2}.*$",
        r"[.,]\s*[Aa]ccessed\s+.*$", r"\s*\(\d+[–\-]\d*\)\s*$",
        r"\s*\(pp\.?\s*\d+[–\-]\d*\)\s*$", r",?\s+\d+[–\-]\d+\s*$",
        r",\s+\d{1,4}[–\-]\d{1,4}\s+https?://.*$",
        r"\.\s*[A-Z][a-zA-Z]+(?:\s+(?:in|of|on|and|for|the|a|an|&|[A-Z]?[a-zA-Z]+))+,\s*\d+\s*[,:]\s*\d+[–\-]?\d*.*$",
        r"\.\s*[A-Z][a-zA-Z\s&+®–—-]+\d+\s*[(,:]\s*\d+[–\-]?\d*.*$",
        r"\.\s*[A-Z][a-zA-Z\s]+[&+]\s*[A-Z].*$",
        r"\.\s+(?:Beaverton|New\s+York|San\s+Francisco|Cambridge|London|Berlin|Springer|Heidelberg).*$",
        r"\.\s+[A-Z][a-z]+\s+of\s+[A-Z][a-z]+(?:\s+(?:and|&)\s+[A-Z][a-z]+)*\s*$",
        r"\.\s+Foundations\s+and\s+Trends.*$",
        r"\.?\s+(?:CHI|CSCW|UbiComp|IMWUT|SOUPS|PETS)\s*['’]?\d{2,4}.*$",
        r",\s+(?:CHI|CSCW|UbiComp|IMWUT|SOUPS|PETS)\s*['’]?\d{2,4}.*$",
    ]:
        title = re.sub(pat, "", title, flags=re.IGNORECASE)
    title = title.strip()
    title = re.sub(r"[.,;:]+$", "", title)
    return title.strip()

def _word_count(text):
    # like len(text.split()), but doesn't undercount hyphen-compressed titles
    # (e.g. "state-of-the-art" is 1 whitespace token but 4 real words); takes
    # the max with the plain split so it can only accept >= what it used to.
    return max(len(text.split()), len(re.findall(r"[A-Za-z0-9]+", text)))

def _extract_title(ref_text):
    ref_text = _fix_hyphenation(ref_text)
    ref_text = re.sub(r"\s+", " ", ref_text).strip()
    ref_text = re.sub(r"^\[\d+\]\s*", "", ref_text)
    ref_text = re.sub(r"^\d+\.\s*", "", ref_text)
    ref_text = ref_text.lstrip(". ")
    ref_text = re.sub(r"\bMR\s*\d{5,}", "", ref_text)
    ref_text = re.sub(r"\s*↑\d+(?:,\s*\d+)*\s*", " ", ref_text)
    ref_text = re.sub(r"\s+", " ", ref_text).strip()

    # Greedy IEEE with inner quotes
    gm = re.search(r'"(.+),"\s', ref_text)
    if gm and _word_count(gm.group(1)) >= 2:
        return gm.group(1) + ",", True

    # Quote patterns
    for qp in [r'""([^"]+)""', r'["“”]([^"“”]+)["“”]',
               r'"([^"]+)"', r'[‘]([^‘’]{10,})[’]',
               r"(?:^|[\s(])'([^']{10,})'(?:\s*[,.]|\s*$)"]:
        m = re.search(qp, ref_text)
        if not m: continue
        qp_text = m.group(1).strip()
        after   = ref_text[m.end():].strip()
        if qp_text.endswith(","):
            if _word_count(qp_text) >= 2: return qp_text, True
            continue
        if after and _word_count(qp_text) >= 2:
            sub = None
            if after[0] in ":-": sub = after[1:].strip()
            elif after[0].isupper() and not re.match(
                r"^(?:IEEE|ACM|USENIX|In\s+|Proc|Trans|Journal|Conference|Workshop|Symposium|vol\.|pp\.)", after, re.IGNORECASE
            ):
                sub = after
            if sub:
                eps = [r"\.\s*[Ii]n\s+", r"\.\s*(?:Proc|IEEE|ACM|USENIX|NDSS|CCS|AAAI|WWW|CHI|arXiv)",
                       r",\s*[Ii]n\s+", r"\.\s*\((?:19|20)\d{2}\)", r"[,\.]\s*(?:19|20)\d{2}", r"\s+(?:19|20)\d{2}\.",
                       r"[.,]\s+[A-Z][a-z]+\s+\d+[,\s]",
                       r"\.\s*[A-Z][a-zA-Z]+(?:\s+(?:in|of|on|and|for|the|a|an|&|[A-Za-z]+))+,\s*\d+\s*[,:]"]
                se = len(sub)
                for ep in eps:
                    em = re.search(ep, sub)
                    if em: se = min(se, em.start())
                s2 = re.sub(r"[.,;:]+$", "", sub[:se].strip())
                if s2 and _word_count(s2) >= 2:
                    return f"{qp_text}: {s2}", True
        if _word_count(qp_text) >= 3: return qp_text, True

    # LNCS A.B.: Title
    lm = re.search(r"(?:[,\s][A-Z]\.(?:[-–]?[A-Z]\.)*|et\s+al\.)\s*:\s*(.+)", ref_text)
    if lm:
        ac = lm.group(1).strip()
        eps = [r"\.\s*[Ii]n:\s+", r"\.\s*[Ii]n\s+[A-Z]", r"\.\s*(?:Proceedings|IEEE|ACM|USENIX|arXiv)",
               r"\.\s*(?:Journal|Transactions|Review|Advances)\s+(?:of|on|in)\s+",
               r"\.\s*[A-Z][a-zA-Z\s]+(?:Access|Journal|Review|Transactions)",
               r"\.\s*[A-Z][a-z]+\s+\d+\s*\(", r"\.\s*https?://", r"\.\s*pp?\.\s*\d+",
               r"\s+\((?:19|20)\d{2}\)\s*[,.]?\s*(?:https?://|$)", r"\s+\((?:19|20)\d{2}\)\s*,"]
        te = len(ac)
        for ep in eps:
            em = re.search(ep, ac)
            if em: te = min(te, em.start())
        t = re.sub(r"\.\s*$", "", ac[:te].strip())
        if _word_count(t) >= 2 and not _is_author_list(t): return t, False

    # Org: Title
    om = re.match(r"^([A-Z][a-zA-Z\s]+):\s*(.+)", ref_text)
    if om:
        ac = om.group(2).strip()
        eps = [r"\s+\((?:19|20)\d{2}\)\s*[,.]?\s*(?:https?://|$)",
               r"\s+\((?:19|20)\d{2}\)\s*,", r"\.\s*https?://", r"\.\s*$"]
        te = len(ac)
        for ep in eps:
            em = re.search(ep, ac)
            if em: te = min(te, em.start())
        t = re.sub(r"\.\s*$", "", ac[:te].strip())
        if _word_count(t) >= 2: return t, False

    # et al. abbreviated
    etm = re.match(r"^[A-Z]\.\s*et\s+al\.\s*([A-Z][a-zA-ZÀ-ɏ-]+)\.\s*", ref_text)
    if etm:
        aa = ref_text[etm.end():]
        eps = [r"\.\s*[Ii]n\s+[A-Z]", r"\.\s*(?:Proceedings|IEEE|ACM|USENIX|AAAI|CVPR|ICCV|NeurIPS|ICML|arXiv)",
               r"\.\s*[Aa]rXiv\s+preprint", r"\.\s*[Aa]dvances\s+in\s+", r"\.\s*https?://",
               r",\s*(?:pages?|pp\.)\s*\d+", r",\s*\d+:\d+", r",\s*\d{4}\.$"]
        te = len(aa)
        for ep in eps:
            em = re.search(ep, aa)
            if em: te = min(te, em.start())
        if te > 0:
            t = re.sub(r"\.\s*$", "", aa[:te].strip())
            if _word_count(t) >= 2: return t, False

    # Springer (Year) Title
    sm = re.search(r"\((\d{4}[a-z]?)\)\.?\s+", ref_text)
    if sm:
        bp = ref_text[:sm.start()]
        if not re.search(r"\)\s*$", bp):
            ay = ref_text[sm.end():]
            eps = [r"\.\s*[Ii]n:\s+", r"\.\s*[Ii]n\s+[A-Z]", r"\.\s*(?:Proceedings|IEEE|ACM|USENIX|arXiv)",
                   r"\.\s*[A-Z][a-zA-Z\s]+\d+\s*\(\d+\)", r"\.\s*[A-Z][a-zA-Z\s&+®–—-]+\d+:\d+",
                   r"\.\s*[A-Z][a-zA-Z\s&+®–—-]+,\s*\d+",
                   r"\.\s*[A-Z][a-zA-Z\s&+®–—-]{5,}\s*\((?:19|20)\d{2}\)",
                   r"[?!]\s+[A-Z][a-zA-Z\s&+®–—-]+,\s*\d+\s*[(:]",
                   r"[?!]\s+[A-Z][a-z]+\s+(?:[A-Z][a-z]+\s+)?\d+\(",
                   r"[?!]\s+[A-Z][a-z]+\s+[a-z]+\s", r"\s+\[",
                   r"\.\s*https?://", r"\.\s*URL\s+", r"\.\s*Tech\.\s*rep\.", r"\.\s*pp?\.\s*\d+"]
            te = len(ay)
            for ep in eps:
                em = re.search(ep, ay)
                if em:
                    te = min(te, em.start()+1) if em.group(0)[0] in "?!" else min(te, em.start())
            t = re.sub(r"\.\s*$", "", ay[:te].strip())
            if _word_count(t) >= 3: return t, False

    # ACM . Year . Title
    am = re.search(r"\.\s*((?:19|20)\d{2})\.\s+", ref_text)
    if am:
        ay = ref_text[am.end():]
        eps = [r"\.\s*[Ii]n\s+[A-Z]", r"\.\s*(?:Proceedings|IEEE|ACM|USENIX|arXiv)",
               r"\.\s*[A-Z][a-zA-Z\s&]+\d+\s*\((?:19|20)\d{2}\),\s*\d+",
               r"\.\s*[A-Z][a-zA-Z\s&]+\((?:19|20)\d{2}\),\s*\d+",
               r"\.\s*[A-Z][a-zA-Z\s&+®–—-]{10,},\s*\d+",
               r"\.\s*[A-Z][a-zA-Z\s&+®–—-]{5,}\s*\((?:19|20)\d{2}\)",
               r"[?!]\s+[A-Z][a-zA-Z\s&+®–—-]+,\s*\d+\s*[(:]",
               r"[?!]\s+[A-Z][a-z]+\s+(?:[A-Z][a-z]+\s+)?\d+\(",
               r"[?!]\s+[A-Z][a-z]+\s+[a-z]+\s", r"\s+doi:",
               r"\.\s*https?://", r"\s*\(\d+(?:st|nd|rd|th)?\s*ed\.?\)\.\s*[A-Z]"]
        te = len(ay)
        for ep in eps:
            em = re.search(ep, ay)
            if em:
                te = min(te, em.start()+1) if em.group(0)[0] in "?!" else min(te, em.start())
        t = re.sub(r"\.\s*$", "", ay[:te].strip())
        if _word_count(t) >= 3: return t, False

    # Venue markers
    vps = [r"\.\s*[Ii]n:\s+(?:Proceedings|Workshop|Conference|Symposium|IFIP|IEEE|ACM)",
           r"\.\s*[Ii]n:\s+[A-Z]",
           # comma-preceded "In: Venue", sometimes year-first e.g. "in: 2008 Third..."
           r",\s*[Ii]n:\s+(?:(?:19|20)\d{2}\s+)?[A-Z]",
           r"\.\s*[Ii]n\s+(?:Proceedings|Workshop|Conference|Symposium|AAAI|IEEE|ACM|USENIX)",
           r"\.\s*[Ii]n\s+[A-Z][a-z]+\s+(?:Conference|Workshop|Symposium)",
           r"\.\s*[Ii]n\s+(?:The\s+)?(?:\w+\s+)+(?:International\s+)?(?:Conference|Workshop|Symposium)",
           r"\.\s*(?:NeurIPS|ICML|ICLR|CVPR|ICCV|ECCV|AAAI|IJCAI|CoRR|JMLR),",
           r"\.\s*arXiv\s+preprint",
           r",\s*arXiv\s+preprint",
           r"\.\s*[Ii]n\s+[A-Z]",
           r",\s*(?:19|20)\d{2}\.\s*(?:URL|$)", r",\s*(?:19|20)\d{2}\.\s*$",
           # Elsevier-style numbered ref: "..., Journal Name N (n) (YYYY) pages"
           r",\s*[A-Z][a-zA-Z.\s&]+\s+\d+\s*(?:\(\d+\)\s*)?\(\s*(?:19|20)\d{2}\s*\)"]
    for vp in vps:
        vm = re.search(vp, ref_text)
        if not vm: continue
        bv = ref_text[:vm.start()].strip()
        parts = _split_sentences(bv)
        if len(parts) >= 2:
            t = re.sub(r"\.\s*$", "", parts[1].strip())
            if _word_count(t) >= 3 and not re.match(r"^[A-Z][a-z]+\s+[A-Z][a-z]+,", t):
                return t, False
        aep = r"(?:,\s+[A-Z]\.(?:[-\s]+[A-Z]\.)*|(?:Jr|Sr|III|II|IV)\.)\s+(.)"
        for m2 in reversed(list(re.finditer(aep, bv))):
            rem = bv[m2.start(1):]
            if re.match(r"^[A-Z]\.,", rem) or re.match(r"^[A-Z][a-z]+,", rem): continue
            t = re.sub(r"\.\s*$", "", rem.strip())
            if _word_count(t) >= 3 and not re.match(r"^[A-Z][a-z]+,\s+[A-Z]\.", t):
                return t, False
            break
        # Initials-first author list, e.g. "V.R. Palleti, S. Adepu, Title text"
        author_entry = r"[A-Z]\.(?:[A-Z]\.)*\s+[A-Z][a-zA-Z\-']+"
        am = re.match(rf"^(?:{author_entry}\s*,\s*)+", bv)
        if am:
            t = re.sub(r"\.\s*$", "", bv[am.end():].strip())
            if _word_count(t) >= 3:
                return t, False
        break

    # Journal
    jm = re.search(r"\.\s*([A-Z][^.]+(?:Journal|Review|Transactions|Letters|Magazine|Science|Nature|Processing|Advances)[^.]*),\s*(?:vol\.|Volume|\d+\(|\d+,)", ref_text, re.IGNORECASE)
    if jm:
        bj = ref_text[:jm.start()].strip()
        parts = _split_sentences(bj)
        if len(parts) >= 2 and _word_count(parts[1]) >= 3:
            return parts[1].strip(), False

    # Elsevier Journal;Year
    ejm = re.search(r"\.\s*([A-Z][A-Za-z\s]+)\s+(?:19|20)\d{2};\d+(?:\(\d+\))?", ref_text)
    if ejm:
        bj = ref_text[:ejm.start()].strip()
        parts = _split_sentences(bj)
        if len(parts) >= 2:
            t = re.sub(r"\.\s*$", "", parts[-1].strip())
            if _word_count(t) >= 3: return t, False

    # ALL CAPS authors
    if re.match(r"^[A-Z]{2,}", ref_text) and not re.search(r"^[A-Z]{2,}\s+[A-Z](?:,|\s)", ref_text):
        tsm = re.search(r"\.\s+([A-Z][a-z]*\s+[a-z])", ref_text)
        if tsm:
            tt = ref_text[tsm.start(1):]
            eps = [r"\.\s*[Ii]n\s+[A-Z]",
                   r"\.\s*(?:Proceedings|IEEE|ACM|USENIX|NDSS|arXiv|Technical\s+report)",
                   r"\.\s*[A-Z][a-z]+\s+\d+,\s*\d+\s*\(",
                   r"\.\s*(?:Ph\.?D\.?\s+thesis|Master.s\s+thesis)"]
            te = len(tt)
            for ep in eps:
                em = re.search(ep, tt)
                if em: te = min(te, em.start())
            if te > 0:
                t = re.sub(r"\.\s*$", "", tt[:te].strip())
                if _word_count(t) >= 3 and not _is_author_list(t): return t, False

    # APA &
    apm = re.search(r"&\s+[A-Z][a-z-]+,\s+[A-Z]\..*?\((\d{4})\)\.\s+", ref_text)
    if apm:
        ay = ref_text[apm.end():]
        eps = [r"\.\s+[A-Z][a-z]+(?:\s+[A-Z]?[a-z]+)*,?\s+\d+", r"\.\s+[Ii]n\s+",
               r"\.\s+(?:http|doi:|arXiv)", r"\.\s+[A-Z][a-z]+:", r"\s+\[", r"\.\s*$"]
        te = len(ay)
        for ep in eps:
            em = re.search(ep, ay)
            if em: te = min(te, em.start())
        t = re.sub(r"\.\s*$", "", ay[:te].strip())
        if _word_count(t) >= 3: return t, False

    # ALL CAPS Chinese/Biomedical
    if re.search(r"^([A-Z]{2,})\s+[A-Z](?:,|\s|$)", ref_text):
        etm2 = re.search(r",?\s+et\s+al\.?\s*[,.]?\s*", ref_text, re.IGNORECASE)
        if etm2:
            aa = ref_text[etm2.end():].strip()
        else:
            parts = ref_text.split(", ")
            tsi = next((i for i, p in enumerate(parts) if not re.match(r"^[A-Z]{2,}(?:\s+[A-Z])?$", p.strip())), None)
            aa = ", ".join(parts[tsi:]).strip() if tsi is not None else None
        if aa:
            eps = [r"\[J\]", r"\[C\]", r"\[M\]", r"\[D\]",
                   r"\.\s*[A-Z][a-zA-Z\s]+\d+\s*\(\d+\)", r"\.\s*[A-Z][a-zA-Z\s&+]+\d+:\d+",
                   r"\.\s*[A-Z][a-zA-Z\s&+]+,\s*\d+", r"\.\s*(?:19|20)\d{2}",
                   r"\.\s*https?://", r"\.\s*doi:"]
            te = len(aa)
            for ep in eps:
                em = re.search(ep, aa)
                if em: te = min(te, em.start())
            t = re.sub(r"\.\s*$", "", aa[:te].strip())
            if _word_count(t) >= 3 and not _is_author_list(t): return t, False

    # Org web-citation: "Org Name. Product/dataset name. https://..."
    owm = re.match(r"^([A-Z][a-zA-Z0-9\-\s]+)\.\s+([A-Z0-9][^.]*?)\.\s*https?://", ref_text)
    if owm:
        t = owm.group(2).strip()
        if _word_count(t) >= 1 and not _is_author_list(t):
            return t, False

    # Full-name author list, e.g. "Nicolai Meinshausen and Peter Bühlmann. Title. Venue"
    name_word = r"[A-Z][a-zA-ZÀ-ɏ\-']+"
    fnm = re.search(rf"\band\s+(?:{name_word}\s+){{1,3}}{name_word}\.\s+", ref_text)
    if fnm:
        rest = ref_text[fnm.end():]
        tm = re.search(r"\.\s", rest)
        t = (rest[:tm.start()] if tm else rest).strip()
        if _word_count(t) >= 1 and not _is_author_list(t):
            return t, False

    # Fallback second sentence
    sents = _split_sentences(ref_text)
    if len(sents) >= 2:
        pt = sents[1].strip()
        words = pt.split()
        if words:
            cw  = sum(1 for w in words if re.match(r"^[A-Z][a-z]+$", w))
            ac2 = sum(1 for w in words if w.lower() == "and")
            if len(words) > 0 and (cw / len(words) > 0.7) and ac2 > 0 and len(sents) >= 3:
                pt = sents[2].strip()
        if not re.match(r"^[Ii]n\s+", pt) and not _is_author_list(pt) and _word_count(pt) >= 3:
            return pt, False

    return "", False

# ── Venue extractor ───────────────────────────────────────────────────────────

def _extract_venue(ref_text, title):
    if not title:
        return ""
    cr = re.sub(r"\s+", " ", ref_text).strip()
    candidates = [title.strip(), title.strip().strip('"“”\''),
                  title.strip().rstrip(".,;:!?"),
                  title.strip().strip('"“”\'').rstrip(".,;:!?")]
    tail, seen = "", set()
    for c in candidates:
        c = c.strip()
        if not c or c in seen: continue
        seen.add(c)
        m = re.search(re.escape(c) + r"(?P<tail>.*)$", cr, re.IGNORECASE)
        if m: tail = m.group("tail"); break
    if not tail:
        return ""
    v = tail.strip()
    v = re.sub(r'^[\s"“”\'`,.;:)\]-]+', "", v)
    v = re.sub(r"^(?:[.\-]\s*)?[Ii]n:?\s+", "", v)
    v = re.sub(r"^\(\s*(?:19|20)\d{2}[a-z]?\s*\)\.?\s*", "", v)
    v = re.sub(r"^(?:19|20)\d{2}[a-z]?\.\s*", "", v)
    v = re.sub(r"\s*(?:doi\s*:|https?://doi\.org/)\S+.*$", "", v, flags=re.IGNORECASE)
    v = re.sub(r"\s*https?://\S+.*$", "", v, flags=re.IGNORECASE)
    for cp in [r",\s*vol\.\s*\d.*$", r",\s*no\.\s*\d.*$", r",\s*issue\s+\d.*$",
               r",\s*pp?\.\s*.*$", r"\.\s*pp?\.\s*.*$", r",\s*pages?\s*.*$",
               r",\s*\d{1,4}\s*[-–]\s*\d{1,4}.*$",
               r"\s*\(\s*(?:19|20)\d{2}[a-z]?\s*\).*$",
               r",\s*(?:19|20)\d{2}[a-z]?\.*$", r"\.\s*(?:19|20)\d{2}[a-z]?\.*$"]:
        v = re.sub(cp, "", v, flags=re.IGNORECASE)
    v = v.strip(" ,.;:")
    v = re.sub(r"\s+", " ", v)
    if not v: return ""
    nv = re.sub(r"[^a-z0-9]+", "", v.lower())
    nt = re.sub(r"[^a-z0-9]+", "", title.lower())
    if nv == nt or _is_non_ref(v): return ""
    return v

# ── Segmentation scoring (called by _segment_references) ─────────────────────

def _has_extractable_content(ref):
    title, _ = _extract_title(ref)
    if not title or len(title.split()) < 4:
        return False
    authors = _extract_authors(ref)
    return bool(authors) and authors != ["__SAME_AS_PREVIOUS__"]


def _score_segmentation(refs, ref_text, specificity):
    """Score a segmentation result in [0, 1]."""
    if not refs:
        return 0.0
    total_len = sum(len(r) for r in refs)
    coverage  = min(total_len / max(len(ref_text), 1), 1.0)
    complete  = sum(1 for r in refs if _has_extractable_content(r))
    completeness = complete / len(refs)
    lengths = [len(r) for r in refs]
    if len(lengths) >= 2:
        mean = sum(lengths) / len(lengths)
        cv   = min((sum((l - mean) ** 2 for l in lengths) / len(lengths)) ** 0.5 / max(mean, 1), 1.0)
    else:
        cv = 0.0
    consistency  = 1.0 - cv
    count_score  = min(len(refs) / 50.0, 1.0)
    expected_min = max(len(ref_text) // 300, 1)
    plausibility = min(len(refs) / expected_min, 1.0) if len(refs) < expected_min else 1.0
    score = (0.05 * coverage + 0.35 * completeness + 0.05 * consistency +
             0.20 * specificity + 0.35 * count_score)
    return score * plausibility


# ── Citation kind classifier ──────────────────────────────────────────────────
# Distinguishes an academic paper from a web resource (blog post, product page,
# GitHub repo, dataset card, ...) by structure: a URL plus the absence of
# normal paper markers (venue, "In:", "Proceedings", arXiv marker, a DOI, ...)
# means web-resource. A DOI always overrides, even with a URL present.

_CITATION_URL_RE = re.compile(r"https?://|(?<!\w)www\.", re.IGNORECASE)
_CITATION_DOI_RE = re.compile(r"doi\.org|\bdoi:\s*10\.", re.IGNORECASE)
_CITATION_PAPER_MARKER_RE = re.compile(
    r"\b(?:in:|proceedings|conference|workshop|symposium|journal|transactions|"
    r"arxiv|advances\s+in|tech\.?\s*rep|rfc\s*\d)"
    r"|\d+\s*\(\d+\)\s*\(?(?:19|20)\d{2}\)?"   # "Vol (Issue) (Year)" / "Vol (Issue)"
    r"|\(\s*(?:19|20)\d{2}\s*\)\s*\d"          # "(Year) pages"
    r"|\bpp\.\s*\d"
    r"|\bvol\.\s*\d",
    re.IGNORECASE,
)


def _classify_citation_kind(raw_citation: str) -> str:
    """'paper' (default) or 'web-resource'."""
    if not raw_citation:
        return "paper"
    if _CITATION_DOI_RE.search(raw_citation):
        return "paper"
    if _CITATION_URL_RE.search(raw_citation) and not _CITATION_PAPER_MARKER_RE.search(raw_citation):
        return "web-resource"
    return "paper"


# ── Full reference parser ─────────────────────────────────────────────────────

def _parse_references(pdf_text, source_pdf, _debug=None):
    ref_section = _find_references_section(pdf_text)
    if not ref_section:
        raise RuntimeError("Could not locate references section")
    raw_refs = _segment_references(ref_section, _debug=_debug)
    rows, prev_authors = [], []
    for idx, ref_text in enumerate(raw_refs, start=1):
        doi      = _extract_doi(ref_text) or ""
        arxiv_id = _extract_arxiv_id(ref_text) or ""
        ref_text = re.sub(r"\n\d{1,4}\n", "\n", ref_text)
        ref_text = _fix_hyphenation(ref_text)
        title, fq = _extract_title(ref_text)
        title = _truncate_at_venue(title)
        title = _clean_title(title, from_quotes=fq)
        if _is_venue_only(title) or _is_non_ref(title): continue
        venue   = _extract_venue(ref_text, title)
        authors = _extract_authors(ref_text)
        if authors == ["__SAME_AS_PREVIOUS__"]:
            authors = prev_authors if prev_authors else []
        if authors:
            prev_authors = authors
        rc = re.sub(r"\s+", " ", ref_text).strip()
        rc = re.sub(r"^\[\d+\]\s*", "", rc)
        rc = re.sub(r"^\d+\.\s*", "", rc)
        rows.append({
            "source_pdf":    source_pdf,
            "reference_id":  str(idx),
            "title":         title,
            "authors":       "; ".join(authors),
            "venue":         venue,
            "doi":           doi,
            "arxiv_id":      arxiv_id,
            "raw_citation":  rc,
            "citation_kind": _classify_citation_kind(rc),
        })
    return rows

# ── PDF reader / body splitter / context extractor ────────────────────────────

def _read_pdf(pdf_path):
    doc = fitz.open(str(pdf_path))
    try:
        pages = [page.get_text() for page in doc]
    finally:
        doc.close()
    return "\n".join(pages)

def _split_sections(full_text):
    m = _REFERENCE_HEADING.search(full_text)
    if not m:
        return full_text.strip(), ""
    return full_text[:m.start()].strip(), full_text[m.start():].strip()

def _normalize(text):
    return re.sub(r"\s+", " ", str(text or "")).strip()

def _body_sentences(body_text):
    norm = _normalize(body_text)
    if not norm:
        return []
    parts = re.split(r"(?<=[.!?])\s+(?=[A-Z\[])|(?<=\])\s+(?=[A-Z])", norm)
    return [s.strip() for s in parts if s.strip()]

def _expand_token(token):
    token = token.strip().replace("–", "-").replace("—", "-")
    if not token: return []
    if "-" in token:
        a, b = token.split("-", 1)
        if a.strip().isdigit() and b.strip().isdigit():
            s, e = int(a.strip()), int(b.strip())
            if s <= e: return list(range(s, e+1))
    if token.isdigit(): return [int(token)]
    return []

def _citation_ids(sentence):
    ids = []
    for content in _BODY_CITATION.findall(sentence):
        for tok in content.split(","):
            ids.extend(_expand_token(tok))
    return sorted(set(ids))

def _extract_contexts(body_text, citation_ids):
    sents = _body_sentences(body_text)
    ctx = {cid: [] for cid in citation_ids}
    for i, sent in enumerate(sents):
        ids = _citation_ids(sent)
        if not ids: continue
        window = []
        if i > 0: window.append(sents[i-1])
        window.append(sent)
        if i+1 < len(sents): window.append(sents[i+1])
        obj = {"sentence": sent, "expanded_context": window}
        for cid in ids:
            if cid in ctx and obj not in ctx[cid]:
                ctx[cid].append(obj)
    return ctx

def _extract_year(text):
    m = re.search(r"\b((?:19|20)\d{2})\b", str(text or ""))
    return int(m.group(1)) if m else None

def _build_records(parsed_rows, contexts_by_citation, source_pdf):
    out = []
    for row in parsed_rows:
        cid    = int(row["reference_id"])
        authors = [p.strip() for p in row.get("authors", "").split(";") if p.strip()]
        arxiv   = row.get("arxiv_id") or None
        out.append({
            "citation_id":     cid,
            "raw_citation":    row.get("raw_citation") or None,
            "parsed_title":    row.get("title") or None,
            "parsed_authors":  authors,
            "parsed_year":     _extract_year(row.get("raw_citation", "")),
            "parsed_venue":    row.get("venue") or None,
            "parsed_doi":      row.get("doi") or None,
            "parsed_url":      f"https://arxiv.org/abs/{arxiv}" if arxiv else None,
            "parsed_arxiv_id": arxiv,
            "citation_kind":   row.get("citation_kind", "paper"),
            "contexts":        contexts_by_citation.get(cid, []),
            "source_pdf":      source_pdf,
        })
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Public class
# ══════════════════════════════════════════════════════════════════════════════

class Parser:
    """
    Parse a PDF into a structured list of citation records.

    Fully standalone — no ML dependencies (PyMuPDF + stdlib only).

    Each record contains:
        citation_id      : numeric reference number from the paper
        raw_citation     : full raw reference string
        parsed_title     : extracted paper title
        parsed_authors   : list of author name strings
        parsed_year      : publication year (int or None)
        parsed_venue     : venue/journal string (or None)
        parsed_doi       : DOI string (or None), self-reported, not verified
        parsed_url       : URL built from arxiv_id (or None)
        parsed_arxiv_id  : arXiv ID string (or None), self-reported
        citation_kind    : "paper" (default) or "web-resource" (blog post,
            product page, GitHub repo, dataset card, ...) -- not a quality
            signal, just never going to be in an academic title-match
            database, so the client library skips sending these to the API.
        contexts         : list of {sentence, expanded_context} dicts
        source_pdf       : path of the input PDF

    Attributes:
        segmentation_debug: diagnostic dict describing how the reference
            section was segmented -- {"strategy", "score",
            "candidates_tried", "ref_text_len"}.

    Args:
        pdf_path: path to the PDF to parse
    """

    def __init__(self, pdf_path: str | Path) -> None:
        self.pdf_path = Path(pdf_path)
        self.segmentation_debug: dict = {}
        self.records: list[dict] = self._parse()

    def _parse(self) -> list[dict]:
        full_text    = _read_pdf(self.pdf_path)
        body_text, _ = _split_sections(full_text)
        parsed_rows  = _parse_references(full_text, str(self.pdf_path), _debug=self.segmentation_debug)
        citation_ids = {int(r["reference_id"]) for r in parsed_rows}
        contexts     = _extract_contexts(body_text, citation_ids)
        return _build_records(parsed_rows, contexts, str(self.pdf_path))

    def results(self) -> list[dict]:
        return self.records

    def __len__(self) -> int:
        return len(self.records)

    def __repr__(self) -> str:
        return f"Parser(pdf={self.pdf_path.name!r}, citations={len(self.records)})"

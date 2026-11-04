"""Tests für Benutzerregeln, Finanzauswirkungen, Assistent, Stammbaum und Regelvorschläge."""
from atn_dq.chatbot import DQAssistant, parse_amount
from atn_dq.custom_rules import (
    CustomRule, delete_rule, load_custom_rules, run_custom_rule, upsert_rule, validate_rule,
)
from atn_dq.engine import run_analysis
from atn_dq.financial import NOT_CALCULABLE, compute_impacts
from atn_dq.lineage import build_lineage, matnrs_with_findings
from atn_dq.suggest import suggest_rules


def test_custom_rule_persists_and_runs(tmp_path, pkg, cfg):
    r = CustomRule(name="Status erlaubt", sheet_key="HS_Products", field="hs_status",
                   rule_type="allowed_values", params={"values": ["ACTIVE", "INACTIVE"]})
    assert validate_rule(r, pkg) == []
    upsert_rule(tmp_path, r)
    loaded = load_custom_rules(tmp_path)          # "Neustart": frisch von Platte laden
    assert [x.rule_id for x in loaded] == [r.rule_id]
    res = run_analysis(pkg, cfg, custom_rules=loaded)
    assert r.rule_id in res.custom_stats and res.custom_stats[r.rule_id].records_checked > 0
    assert any(f.rule_id == r.rule_id for f in res.findings) == (res.custom_stats[r.rule_id].findings > 0)
    r.enabled = False
    assert r.rule_id not in run_analysis(pkg, cfg, custom_rules=[r]).custom_stats
    delete_rule(tmp_path, r.rule_id)
    assert load_custom_rules(tmp_path) == []


def test_validation_rejects_bad_rules(pkg):
    assert validate_rule(CustomRule(name="", sheet_key="HS_Products", field="price", rule_type="range"), pkg)
    bad = CustomRule(name="x", sheet_key="HS_Products", field="price", rule_type="format", params={"pattern": "("})
    assert any("Ausdruck" in e for e in validate_rule(bad, pkg))
    nofield = CustomRule(name="x", sheet_key="HS_Products", field="gibtsnicht", rule_type="completeness")
    assert validate_rule(nofield, pkg)


def test_range_rule_finds_real_rows(pkg):
    r = CustomRule(name="Preis > 0", sheet_key="HS_Products", field="price", rule_type="range", params={"min": 1})
    fs, stat = run_custom_rule(r, pkg)
    assert stat.records_checked > 0 and all(f.row >= 3 for f in fs)


def test_financial_never_invents_amounts(pkg, cfg):
    res = run_analysis(pkg, cfg)
    items = {i.key: i for i in compute_impacts(pkg, res.findings)}
    c = items["customs"]
    assert c.amount_eur is None and c.amount_label == NOT_CALCULABLE
    for i in items.values():
        assert i.basis and i.uncertainty
        if i.amount_eur is not None:
            assert i.amount_eur >= 0 and i.details is not None


def test_assistant_price_levels(pkg, cfg):
    res = run_analysis(pkg, cfg)
    bot = DQAssistant(pkg, res.findings, cfg, [])
    a = bot.answer("Ist ein Produktpreis von 1.000.000 € plausibel?")
    assert "auffällig" in a.text and "Fachliche Prüfung erforderlich" in a.text
    assert "nachweislich falsch" not in a.text            # ungewöhnlich ist nicht falsch
    assert "nachweislich falsch" in bot.answer("Ist ein Preis von -5 € plausibel?").text
    assert parse_amount("47.290 €") == 47290 and parse_amount("1,5 Mio") == 1_500_000
    assert bot.answer("Wie ist das Wetter?").kind == "unbekannt"


def test_assistant_uses_real_findings(pkg, cfg):
    res = run_analysis(pkg, cfg)
    m = next(f.record_id for f in res.findings if f.record_id and f.record_id.isdigit() and len(f.record_id) == 10)
    a = DQAssistant(pkg, res.findings, cfg, []).answer(f"Welche Regel verletzt die Materialnummer {m}?")
    assert m in a.text and a.evidence


def test_lineage_only_proven_edges(pkg, cfg):
    res = run_analysis(pkg, cfg)
    m = matnrs_with_findings(res.findings)[0][0]
    lin = build_lineage(pkg, res.findings, m)
    assert lin.nodes and all(e.kind == "nachgewiesen" and e.evidence for e in lin.edges)
    assert all(e.src in lin.nodes and e.dst in lin.nodes for e in lin.edges)


def test_suggestions_are_inactive_and_complete(pkg):
    sugg, _ = suggest_rules(pkg)
    assert sugg
    for s in sugg:
        assert s.rule.enabled is False
        assert s.affected > 0 and s.total >= 30 and s.examples and s.uncertainty and s.pattern

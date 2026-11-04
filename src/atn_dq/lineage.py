"""Fehler-Stammbaum: zeigt, wie ein Fehler über Systeme hinweg weiterwirkt.

Es werden **nur Beziehungen** verwendet, die tatsächlich in den Daten stehen:

- SAP MATNR  = Salesforce ``ATN_SAP_Materialnummer__c`` = HubSpot ``atn_sap_materialnummer``
- Salesforce Product2.Id <- PricebookEntry.Product2Id / Asset.Product2Id
- Asset.Id <- WorkOrder.AssetId, Asset.AccountId -> Account.Id
- HubSpot Products.hs_object_id <- Price Book Items.hs_associated_product_id

Jede Kante trägt ihre Evidenz (welche Felder gleich sind). Auswirkungen, die nur aus
Befundtexten stammen (``Finding.follow_on``), werden getrennt als *vermutet* geführt.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

from .finding import Finding
from .loader import DataPackage, LoadedSheet
from .normalize import is_missing, norm_matnr, strip_str

SEV_RANK = {"hoch": 3, "mittel": 2, "niedrig": 1}
LAYERS = ["SAP", "Salesforce Produkt", "HubSpot", "Service"]


@dataclass
class Node:
    node_id: str
    label: str
    layer: int
    system: str
    sheet: str
    row: int
    findings: list[Finding] = field(default_factory=list)

    @property
    def severity(self) -> str | None:
        if not self.findings:
            return None
        return max(self.findings, key=lambda f: SEV_RANK.get(f.severity, 0)).severity


@dataclass
class Edge:
    src: str
    dst: str
    kind: str          # "nachgewiesen"
    evidence: str


@dataclass
class Lineage:
    matnr: str
    nodes: dict[str, Node]
    edges: list[Edge]
    truncated: dict[str, int]
    assumed: list[tuple[str, str]]   # (vermutete Auswirkung, Quelle-Befund)


def _by_loc(findings: list[Finding]) -> dict[tuple[str, str, int], list[Finding]]:
    out: dict[tuple[str, str, int], list[Finding]] = defaultdict(list)
    for f in findings:
        out[(f.file, f.sheet, f.row)].append(f)
    return out


def _find_rows(sheet: LoadedSheet | None, col: str, pred) -> list[tuple[int, object]]:
    if sheet is None or col not in sheet.df.columns:
        return []
    return [(int(i), r) for i, r in sheet.df.iterrows() if pred(r.get(col))]


def matnrs_with_findings(findings: list[Finding]) -> list[tuple[str, int]]:
    """MATNRs (Produktebene) sortiert nach Anzahl Befunde."""
    cnt: dict[str, int] = defaultdict(int)
    for f in findings:
        if f.record_id and f.record_id.isdigit() and len(f.record_id) == 10 and f.record_id.startswith("1"):
            cnt[f.record_id] += 1
    return sorted(cnt.items(), key=lambda kv: (-kv[1], kv[0]))


def build_lineage(pkg: DataPackage, findings: list[Finding], matnr: str,
                  max_per_group: int = 5) -> Lineage:
    loc = _by_loc(findings)
    nodes: dict[str, Node] = {}
    edges: list[Edge] = []
    truncated: dict[str, int] = {}

    def add(sheet: LoadedSheet, idx: int, layer: int, label: str) -> Node:
        row = sheet.excel_row(idx)
        nid = f"{sheet.key}#{row}"
        if nid not in nodes:
            nodes[nid] = Node(nid, label, layer, sheet.system, sheet.sheet_name, row,
                              list(loc.get((sheet.source_file, sheet.sheet_name, row), [])))
        return nodes[nid]

    def limit(items: list, name: str, key=None):
        if len(items) > max_per_group:
            truncated[name] = len(items) - max_per_group
            items = sorted(items, key=key or (lambda x: 0))[:max_per_group]
        return items

    is_m = lambda v: norm_matnr(v) == matnr  # noqa: E731

    # --- Ebene 0: SAP ---------------------------------------------------
    sap_nodes: list[Node] = []
    for key, lab in (("SAP_FERT", "MARC Produkt"), ("SAP_MARA", "MARA")):
        s = pkg.get(key)
        for idx, r in _find_rows(s, "MATNR", is_m):
            sap_nodes.append(add(s, idx, 0, f"SAP {lab}\n{matnr}"))

    # --- Ebene 1: Salesforce Produkt --------------------------------------
    sf_prod = pkg.get("SF_Product2")
    sf_nodes: list[Node] = []
    sf_ids: dict[str, Node] = {}
    for idx, r in _find_rows(sf_prod, "ATN_SAP_Materialnummer__c", is_m):
        n = add(sf_prod, idx, 1, f"SF Product2\n{strip_str(r.get('ProductCode')) or ''}")
        sf_nodes.append(n)
        pid = strip_str(r.get("Id"))
        if pid:
            sf_ids[pid] = n
    for s_node in sap_nodes:
        for n in sf_nodes:
            edges.append(Edge(s_node.node_id, n.node_id, "nachgewiesen",
                              f"MATNR {matnr} = ATN_SAP_Materialnummer__c"))
    pbe = pkg.get("SF_PricebookEntry")
    pbe_nodes: list[Node] = []
    for idx, r in _find_rows(pbe, "Product2Id", lambda v: strip_str(v) in sf_ids):
        n = add(pbe, idx, 1, f"SF Preis\n{strip_str(r.get('UnitPrice')) or '-'}")
        pbe_nodes.append(n)
        edges.append(Edge(sf_ids[strip_str(r.get('Product2Id'))].node_id, n.node_id, "nachgewiesen",
                          "PricebookEntry.Product2Id = Product2.Id"))

    # --- Ebene 2: HubSpot ---------------------------------------------------
    hs_prod = pkg.get("HS_Products")
    hs_ids: dict[str, Node] = {}
    hs_nodes: list[Node] = []
    for idx, r in _find_rows(hs_prod, "atn_sap_materialnummer", is_m):
        n = add(hs_prod, idx, 2, f"HS Product\n{strip_str(r.get('hs_sku')) or ''}")
        hs_nodes.append(n)
        hid = strip_str(r.get("hs_object_id"))
        if hid:
            hs_ids[hid] = n
    for s_node in sap_nodes:
        for n in hs_nodes:
            edges.append(Edge(s_node.node_id, n.node_id, "nachgewiesen",
                              f"MATNR {matnr} = atn_sap_materialnummer"))
    hpi = pkg.get("HS_PriceBookItems")
    for idx, r in _find_rows(hpi, "hs_associated_product_id", lambda v: strip_str(v) in hs_ids):
        n = add(hpi, idx, 2, f"HS Preis\n{strip_str(r.get('hs_price_eur')) or '-'}")
        edges.append(Edge(hs_ids[strip_str(r.get('hs_associated_product_id'))].node_id, n.node_id,
                          "nachgewiesen", "Price Book Item.hs_associated_product_id = Product.hs_object_id"))

    # --- Ebene 3: Service ------------------------------------------------------
    assets = pkg.get("SF_Asset")
    asset_rows = _find_rows(assets, "Product2Id", lambda v: strip_str(v) in sf_ids)
    asset_rows = limit(asset_rows, "Assets", key=lambda t: -len(
        loc.get((assets.source_file, assets.sheet_name, assets.excel_row(t[0])), [])))
    asset_nodes: dict[str, Node] = {}
    accounts = pkg.get("SF_Account")
    acc_by_id = {}
    if accounts is not None:
        acc_by_id = {strip_str(r.get("Id")): (int(i), r) for i, r in accounts.df.iterrows()}
    for idx, r in asset_rows:
        n = add(assets, idx, 3, f"Asset\n{strip_str(r.get('SerialNumber')) or '(ohne SN)'}")
        aid = strip_str(r.get("Id"))
        asset_nodes[aid] = n
        edges.append(Edge(sf_ids[strip_str(r.get('Product2Id'))].node_id, n.node_id, "nachgewiesen",
                          "Asset.Product2Id = Product2.Id"))
        acc = acc_by_id.get(strip_str(r.get("AccountId")))
        if acc is not None:
            an = add(accounts, acc[0], 3, f"Kunde\n{strip_str(acc[1].get('Name')) or ''}")
            edges.append(Edge(n.node_id, an.node_id, "nachgewiesen", "Asset.AccountId = Account.Id"))
    wo = pkg.get("SF_WorkOrder")
    wo_rows = _find_rows(wo, "AssetId", lambda v: strip_str(v) in asset_nodes)
    wo_rows = limit(wo_rows, "Wartungsaufträge", key=lambda t: -len(
        loc.get((wo.source_file, wo.sheet_name, wo.excel_row(t[0])), [])))
    for idx, r in wo_rows:
        n = add(wo, idx, 3, f"WorkOrder\n{strip_str(r.get('WorkOrderNumber')) or ''}")
        edges.append(Edge(asset_nodes[strip_str(r.get('AssetId'))].node_id, n.node_id, "nachgewiesen",
                          "WorkOrder.AssetId = Asset.Id"))

    # --- vermutete Auswirkungen (nur Text aus Befunden, nicht aus Daten belegt) ---
    assumed: list[tuple[str, str]] = []
    seen = set()
    for n in nodes.values():
        for f in n.findings:
            for txt in f.follow_on:
                k = (txt, f.rule_id)
                if k not in seen:
                    seen.add(k)
                    assumed.append((txt, f"{f.rule_name} ({n.system}/{n.sheet} Z{n.row})"))
    return Lineage(matnr=matnr, nodes=nodes, edges=edges, truncated=truncated, assumed=assumed)


def root_nodes(lin: Lineage) -> list[Node]:
    """Knoten mit Befunden in der frühesten Ebene = mögliche Ursprünge."""
    with_f = [n for n in lin.nodes.values() if n.findings]
    if not with_f:
        return []
    first = min(n.layer for n in with_f)
    return [n for n in with_f if n.layer == first]


def downstream(lin: Lineage, node_id: str) -> list[Node]:
    out, stack, seen = [], [node_id], {node_id}
    while stack:
        cur = stack.pop()
        for e in lin.edges:
            if e.src == cur and e.dst not in seen:
                seen.add(e.dst)
                out.append(lin.nodes[e.dst])
                stack.append(e.dst)
    return out

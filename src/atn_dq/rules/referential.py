"""Referentielle Integrität: Contacts, Assets, WorkOrders zeigen auf gültige Datensätze."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_REFERENCE, SEVERITY_HIGH, SEVERITY_MEDIUM
from ..loader import DataPackage
from ..normalize import is_missing, strip_str
from .base import registry


def _col_list(df, name: str) -> list:
    """Spalte als Liste (Position 0..n-1 = Zeilenindex nach reset_index). Ohne iterrows."""
    return df[name].tolist() if name in df.columns else [None] * len(df)


def _id_set(df, name: str) -> set:
    if name not in df.columns:
        return set()
    return {strip_str(v) for v in df[name].tolist() if not is_missing(v)}


@registry.register(
    rule_id="REFERENCE_CONTACT_ACCOUNT",
    name="Contact verweist auf existierenden Account",
    description="Jeder Contact muss auf einen existierenden Account verweisen.",
    category="Referenz",
    dimension=DIM_REFERENCE,
)
def rule_contact_account(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    acc = pkg.get("SF_Account")
    con = pkg.get("SF_Contact")
    if acc is None or con is None:
        return
    account_ids = _id_set(acc.df, "Id")
    ids = _col_list(con.df, "Id")
    accids = _col_list(con.df, "AccountId")
    for pos, (cid, aid) in enumerate(zip(ids, accids)):
        aid = strip_str(aid)
        if aid and aid not in account_ids:
            yield Finding(
                rule_id="REF_CONTACT_ACC",
                rule_name="Contact → Account nicht auflösbar",
                category="Referenz", dimension=DIM_REFERENCE, system="Salesforce",
                file=con.source_file, sheet=con.sheet_name, row=con.excel_row(pos),
                field_name="AccountId", value=aid, record_id=strip_str(cid),
                message=f"Contact verweist auf Account-Id '{aid}', die nicht existiert.",
                severity=SEVERITY_HIGH,
                explanation="Die referenzierte Kunden-Id ist im Account-Blatt nicht vorhanden.",
                business_impact=(
                    "Service-Anfragen und Marketing-Kampagnen können dem Kunden nicht zugeordnet werden. "
                    "Kommunikation landet ins Leere."
                ),
                cause="Account wurde gelöscht oder Export unvollständig.",
                correction_suggestion="AccountId prüfen und auf existierenden Account korrigieren.",
                correction_type="Manuelle_Pruefung", confidence="sicher",
            )


@registry.register(
    rule_id="REFERENCE_ASSET_ACCOUNT",
    name="Asset verweist auf existierenden Account",
    description="Jedes installierte Gerät muss zu einem existierenden Kunden gehören.",
    category="Referenz",
    dimension=DIM_REFERENCE,
)
def rule_asset_account(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    acc = pkg.get("SF_Account")
    assets = pkg.get("SF_Asset")
    if acc is None or assets is None:
        return
    account_ids = _id_set(acc.df, "Id")
    ids = _col_list(assets.df, "Id")
    accids = _col_list(assets.df, "AccountId")
    for pos, (asset_id, aid) in enumerate(zip(ids, accids)):
        aid = strip_str(aid)
        if aid and aid not in account_ids:
            yield Finding(
                rule_id="REF_ASSET_ACC",
                rule_name="Asset → Account nicht auflösbar",
                category="Referenz", dimension=DIM_REFERENCE, system="Salesforce",
                file=assets.source_file, sheet=assets.sheet_name, row=assets.excel_row(pos),
                field_name="AccountId", value=aid, record_id=strip_str(asset_id),
                message=f"Asset verweist auf Account-Id '{aid}', die nicht existiert.",
                severity=SEVERITY_HIGH,
                explanation="Das Gerät kann keinem Kunden zugeordnet werden.",
                business_impact=(
                    "Service-Einsätze an diesem Gerät können nicht korrekt verrechnet werden; "
                    "Wartungseinsätze werden möglicherweise dem falschen Kunden in Rechnung gestellt."
                ),
                cause="Account wurde gelöscht oder AssetId falsch erfasst.",
                correction_suggestion="AccountId prüfen und korrigieren.",
                correction_type="Manuelle_Pruefung", confidence="sicher",
            )


@registry.register(
    rule_id="REFERENCE_WORKORDER_ASSET",
    name="WorkOrder verweist auf existierendes Asset",
    description="Jeder Wartungsauftrag muss auf ein existierendes Gerät verweisen.",
    category="Referenz",
    dimension=DIM_REFERENCE,
)
def rule_workorder_asset(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    assets = pkg.get("SF_Asset")
    wo = pkg.get("SF_WorkOrder")
    if assets is None or wo is None:
        return
    asset_ids = _id_set(assets.df, "Id")
    assetids = _col_list(wo.df, "AssetId")
    wonums = _col_list(wo.df, "WorkOrderNumber")
    for pos, (aid, wonum) in enumerate(zip(assetids, wonums)):
        aid = strip_str(aid)
        if aid and aid not in asset_ids:
            yield Finding(
                rule_id="REF_WO_ASSET",
                rule_name="WorkOrder → Asset nicht auflösbar",
                category="Referenz", dimension=DIM_REFERENCE, system="Salesforce",
                file=wo.source_file, sheet=wo.sheet_name, row=wo.excel_row(pos),
                field_name="AssetId", value=aid, record_id=strip_str(wonum),
                message=f"WorkOrder verweist auf Asset-Id '{aid}', die nicht existiert.",
                severity=SEVERITY_HIGH,
                explanation=(
                    "Der Wartungsauftrag ist einem Gerät zugeordnet, das im Asset-Stamm nicht existiert. "
                    "Service-Einsätze können am falschen Gerät oder bei falschem Kunden erfolgen."
                ),
                business_impact=(
                    "Leerfahrten, falsch berechnete Wartungskosten und Vertrauensverlust bei Kunden."
                ),
                cause="Asset-Id manuell falsch erfasst oder Asset nachträglich gelöscht.",
                follow_on=["Rechnung geht an falschen Kunden", "Techniker-Einsatzplan unbrauchbar"],
                correction_suggestion="AssetId prüfen (ggf. längenprüfen - Salesforce-Ids sind 18-stellig).",
                correction_type="Manuelle_Pruefung", confidence="sicher",
            )


@registry.register(
    rule_id="REFERENCE_WORKORDER_CONSISTENCY",
    name="WorkOrder-Kunde entspricht Asset-Kunde",
    description="Der Kunde im Wartungsauftrag muss mit dem Kunden des Assets übereinstimmen.",
    category="Referenz",
    dimension=DIM_REFERENCE,
)
def rule_workorder_consistency(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    assets = pkg.get("SF_Asset")
    wo = pkg.get("SF_WorkOrder")
    if assets is None or wo is None:
        return
    asset_to_account: dict[str, str | None] = {}
    for aid, acc in zip(_col_list(assets.df, "Id"), _col_list(assets.df, "AccountId")):
        aid = strip_str(aid)
        if aid:
            asset_to_account[aid] = strip_str(acc)

    assetids = _col_list(wo.df, "AssetId")
    accids = _col_list(wo.df, "AccountId")
    wonums = _col_list(wo.df, "WorkOrderNumber")
    for pos, (aid, wo_acc, wonum) in enumerate(zip(assetids, accids, wonums)):
        aid = strip_str(aid); wo_acc = strip_str(wo_acc)
        if not aid or not wo_acc:
            continue
        expected_acc = asset_to_account.get(aid)
        if expected_acc is None:
            continue  # unbekanntes Asset bereits in REF_WO_ASSET gemeldet
        if expected_acc != wo_acc:
            yield Finding(
                rule_id="REF_WO_ACC_MISMATCH",
                rule_name="WorkOrder-Kunde ≠ Asset-Kunde",
                category="Referenz", dimension=DIM_REFERENCE, system="Salesforce",
                file=wo.source_file, sheet=wo.sheet_name, row=wo.excel_row(pos),
                field_name="AccountId", value=wo_acc, record_id=strip_str(wonum),
                message=(f"WorkOrder-Kunde '{wo_acc}' weicht vom Asset-Kunden '{expected_acc}' ab."),
                severity=SEVERITY_HIGH,
                explanation=(
                    "Der Wartungsauftrag verweist auf einen anderen Kunden als das Gerät, "
                    "an dem die Wartung stattfindet."
                ),
                business_impact=(
                    "Service-Rechnung geht an den falschen Kunden; Einsatzplanung ist unzuverlässig."
                ),
                cause="Falsche manuelle Erfassung oder Kunde seit Installation gewechselt ohne Update.",
                follow_on=["Falsche Umsatzzuordnung", "Falsche Service-Historie beim Kunden"],
                correction_suggestion=f"WorkOrder-Kunde auf '{expected_acc}' korrigieren.",
                correction_type="Sichere_Korrektur", confidence="sicher",
            )


@registry.register(
    rule_id="REFERENCE_PRICEBOOK_PRODUCT",
    name="PricebookEntry → Product/Pricebook",
    description="Jeder Preiseintrag muss auf existierendes Produkt und Preisbuch zeigen.",
    category="Referenz",
    dimension=DIM_REFERENCE,
)
def rule_pricebook_entry(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    # Salesforce
    entries = pkg.get("SF_PricebookEntry")
    products = pkg.get("SF_Product2")
    books = pkg.get("SF_Pricebook2")
    if entries is not None and products is not None and books is not None:
        product_ids = _id_set(products.df, "Id")
        book_ids = _id_set(books.df, "Id")
        ids = _col_list(entries.df, "Id")
        pids = _col_list(entries.df, "Product2Id")
        bids = _col_list(entries.df, "Pricebook2Id")
        for pos, (rid, pid, bid) in enumerate(zip(ids, pids, bids)):
            pid = strip_str(pid); bid = strip_str(bid); rid = strip_str(rid)
            if pid and pid not in product_ids:
                yield _bad_ref(entries, pos, "Product2Id", pid, rid,
                               "Preiseintrag → Produkt nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Produkt.")
            if bid and bid not in book_ids:
                yield _bad_ref(entries, pos, "Pricebook2Id", bid, rid,
                               "Preiseintrag → Preisbuch nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Preisbuch.")

    # HubSpot
    hs_entries = pkg.get("HS_PriceBookItems")
    hs_products = pkg.get("HS_Products")
    hs_books = pkg.get("HS_PriceBooks")
    if hs_entries is not None and hs_products is not None and hs_books is not None:
        product_ids = _id_set(hs_products.df, "hs_object_id")
        book_ids = _id_set(hs_books.df, "hs_object_id")
        ids = _col_list(hs_entries.df, "hs_object_id")
        pids = _col_list(hs_entries.df, "hs_associated_product_id")
        bids = _col_list(hs_entries.df, "price_book_id")
        for pos, (rid, pid, bid) in enumerate(zip(ids, pids, bids)):
            pid = strip_str(pid); bid = strip_str(bid); rid = strip_str(rid)
            if pid and pid not in product_ids:
                yield _bad_ref(hs_entries, pos, "hs_associated_product_id", pid, rid,
                               "HubSpot-Preiseintrag → Produkt nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Produkt.")
            if bid and bid not in book_ids:
                yield _bad_ref(hs_entries, pos, "price_book_id", bid, rid,
                               "HubSpot-Preiseintrag → Preisbuch nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Preisbuch.")


def _bad_ref(sheet, pos, field_name, value, record_id, rule_name, explanation) -> Finding:
    return Finding(
        rule_id=f"REF_BAD_{sheet.key}_{field_name}",
        rule_name=rule_name,
        category="Referenz", dimension=DIM_REFERENCE, system=sheet.system,
        file=sheet.source_file, sheet=sheet.sheet_name, row=sheet.excel_row(pos),
        field_name=field_name, value=value, record_id=record_id,
        message=f"{field_name}='{value}' verweist auf nicht vorhandenen Datensatz.",
        severity=SEVERITY_HIGH, explanation=explanation,
        business_impact="Preisberechnung und Katalogdarstellung können fehlschlagen.",
        cause="Referenz wurde gelöscht oder nie existiert.",
        correction_suggestion="Referenz prüfen und auf gültigen Datensatz korrigieren.",
        correction_type="Manuelle_Pruefung", confidence="sicher",
    )

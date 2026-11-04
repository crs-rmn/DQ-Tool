"""Referentielle Integrität: Contacts, Assets, WorkOrders zeigen auf gültige Datensätze."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import Finding, DIM_REFERENCE, SEVERITY_HIGH, SEVERITY_MEDIUM
from ..loader import DataPackage
from ..normalize import is_missing, strip_str
from .base import registry


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
    account_ids = {strip_str(v) for v in acc.df.get("Id", []) if not is_missing(v)}
    for i, row in con.df.iterrows():
        aid = strip_str(row.get("AccountId"))
        if aid and aid not in account_ids:
            yield Finding(
                rule_id="REF_CONTACT_ACC",
                rule_name="Contact → Account nicht auflösbar",
                category="Referenz",
                dimension=DIM_REFERENCE,
                system="Salesforce",
                file=con.source_file,
                sheet=con.sheet_name,
                row=con.excel_row(int(i)),
                field_name="AccountId",
                value=aid,
                record_id=strip_str(row.get("Id")),
                message=f"Contact verweist auf Account-Id '{aid}', die nicht existiert.",
                severity=SEVERITY_HIGH,
                explanation="Die referenzierte Kunden-Id ist im Account-Blatt nicht vorhanden.",
                business_impact=(
                    "Service-Anfragen und Marketing-Kampagnen können dem Kunden nicht zugeordnet werden. "
                    "Kommunikation landet ins Leere."
                ),
                cause="Account wurde gelöscht oder Export unvollständig.",
                correction_suggestion="AccountId prüfen und auf existierenden Account korrigieren.",
                correction_type="Manuelle_Pruefung",
                confidence="sicher",
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
    account_ids = {strip_str(v) for v in acc.df.get("Id", []) if not is_missing(v)}
    for i, row in assets.df.iterrows():
        aid = strip_str(row.get("AccountId"))
        if aid and aid not in account_ids:
            yield Finding(
                rule_id="REF_ASSET_ACC",
                rule_name="Asset → Account nicht auflösbar",
                category="Referenz",
                dimension=DIM_REFERENCE,
                system="Salesforce",
                file=assets.source_file,
                sheet=assets.sheet_name,
                row=assets.excel_row(int(i)),
                field_name="AccountId",
                value=aid,
                record_id=strip_str(row.get("Id")),
                message=f"Asset verweist auf Account-Id '{aid}', die nicht existiert.",
                severity=SEVERITY_HIGH,
                explanation="Das Gerät kann keinem Kunden zugeordnet werden.",
                business_impact=(
                    "Service-Einsätze an diesem Gerät können nicht korrekt verrechnet werden; "
                    "Wartungseinsätze werden möglicherweise dem falschen Kunden in Rechnung gestellt."
                ),
                cause="Account wurde gelöscht oder AssetId falsch erfasst.",
                correction_suggestion="AccountId prüfen und korrigieren.",
                correction_type="Manuelle_Pruefung",
                confidence="sicher",
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
    asset_ids = {strip_str(v) for v in assets.df.get("Id", []) if not is_missing(v)}
    for i, row in wo.df.iterrows():
        aid = strip_str(row.get("AssetId"))
        if aid and aid not in asset_ids:
            yield Finding(
                rule_id="REF_WO_ASSET",
                rule_name="WorkOrder → Asset nicht auflösbar",
                category="Referenz",
                dimension=DIM_REFERENCE,
                system="Salesforce",
                file=wo.source_file,
                sheet=wo.sheet_name,
                row=wo.excel_row(int(i)),
                field_name="AssetId",
                value=aid,
                record_id=strip_str(row.get("WorkOrderNumber")),
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
                correction_type="Manuelle_Pruefung",
                confidence="sicher",
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
    for _, row in assets.df.iterrows():
        aid = strip_str(row.get("Id"))
        acc = strip_str(row.get("AccountId"))
        if aid:
            asset_to_account[aid] = acc

    for i, row in wo.df.iterrows():
        aid = strip_str(row.get("AssetId"))
        wo_acc = strip_str(row.get("AccountId"))
        if not aid or not wo_acc:
            continue
        expected_acc = asset_to_account.get(aid)
        if expected_acc is None:
            continue  # unbekanntes Asset bereits in REF_WO_ASSET gemeldet
        if expected_acc != wo_acc:
            yield Finding(
                rule_id="REF_WO_ACC_MISMATCH",
                rule_name="WorkOrder-Kunde ≠ Asset-Kunde",
                category="Referenz",
                dimension=DIM_REFERENCE,
                system="Salesforce",
                file=wo.source_file,
                sheet=wo.sheet_name,
                row=wo.excel_row(int(i)),
                field_name="AccountId",
                value=wo_acc,
                record_id=strip_str(row.get("WorkOrderNumber")),
                message=(
                    f"WorkOrder-Kunde '{wo_acc}' weicht vom Asset-Kunden '{expected_acc}' ab."
                ),
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
                correction_type="Sichere_Korrektur",
                confidence="sicher",
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
        product_ids = {strip_str(v) for v in products.df.get("Id", []) if not is_missing(v)}
        book_ids = {strip_str(v) for v in books.df.get("Id", []) if not is_missing(v)}
        for i, row in entries.df.iterrows():
            pid = strip_str(row.get("Product2Id"))
            bid = strip_str(row.get("Pricebook2Id"))
            if pid and pid not in product_ids:
                yield _bad_ref(entries, int(i), "Product2Id", pid,
                               "Preiseintrag → Produkt nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Produkt.")
            if bid and bid not in book_ids:
                yield _bad_ref(entries, int(i), "Pricebook2Id", bid,
                               "Preiseintrag → Preisbuch nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Preisbuch.")

    # HubSpot
    hs_entries = pkg.get("HS_PriceBookItems")
    hs_products = pkg.get("HS_Products")
    hs_books = pkg.get("HS_PriceBooks")
    if hs_entries is not None and hs_products is not None and hs_books is not None:
        product_ids = {strip_str(v) for v in hs_products.df.get("hs_object_id", []) if not is_missing(v)}
        book_ids = {strip_str(v) for v in hs_books.df.get("hs_object_id", []) if not is_missing(v)}
        for i, row in hs_entries.df.iterrows():
            pid = strip_str(row.get("hs_associated_product_id"))
            bid = strip_str(row.get("price_book_id"))
            if pid and pid not in product_ids:
                yield _bad_ref(hs_entries, int(i), "hs_associated_product_id", pid,
                               "HubSpot-Preiseintrag → Produkt nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Produkt.")
            if bid and bid not in book_ids:
                yield _bad_ref(hs_entries, int(i), "price_book_id", bid,
                               "HubSpot-Preiseintrag → Preisbuch nicht auflösbar",
                               "Preiseintrag zeigt auf nicht existierendes Preisbuch.")


def _bad_ref(sheet, idx, field_name, value, rule_name, explanation) -> Finding:
    return Finding(
        rule_id=f"REF_BAD_{sheet.key}_{field_name}",
        rule_name=rule_name,
        category="Referenz",
        dimension=DIM_REFERENCE,
        system=sheet.system,
        file=sheet.source_file,
        sheet=sheet.sheet_name,
        row=sheet.excel_row(idx),
        field_name=field_name,
        value=value,
        record_id=strip_str(sheet.df.iloc[idx].get("Id")) or strip_str(sheet.df.iloc[idx].get("hs_object_id")),
        message=f"{field_name}='{value}' verweist auf nicht vorhandenen Datensatz.",
        severity=SEVERITY_HIGH,
        explanation=explanation,
        business_impact="Preisberechnung und Katalogdarstellung können fehlschlagen.",
        cause="Referenz wurde gelöscht oder nie existiert.",
        correction_suggestion="Referenz prüfen und auf gültigen Datensatz korrigieren.",
        correction_type="Manuelle_Pruefung",
        confidence="sicher",
    )

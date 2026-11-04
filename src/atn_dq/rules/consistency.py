"""Konsistenz-Regeln: Systemübergreifende Abgleiche (SAP ↔ HubSpot ↔ Salesforce)."""
from __future__ import annotations

from typing import Iterable

from ..config import Config
from ..finding import (
    Finding,
    DIM_CONSISTENCY,
    SEVERITY_HIGH,
    SEVERITY_MEDIUM,
    SEVERITY_LOW,
)
from ..loader import DataPackage
from ..normalize import (
    is_missing,
    norm_matnr,
    norm_name,
    norm_price,
    norm_upper,
    strip_str,
)
from .base import registry


@registry.register(
    rule_id="CONSISTENCY_SAP_MATNR_IN_CRM",
    name="SAP-Materialnummer in CRM vorhanden",
    description="Jedes Produkt in HubSpot/Salesforce verweist auf eine existierende SAP-Materialnummer.",
    category="Konsistenz_Produkt",
    dimension=DIM_CONSISTENCY,
)
def rule_matnr_link(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    sap_keys: set[str] = set()
    for key in ("SAP_FERT", "SAP_MARA", "SAP_ERSA"):
        sheet = pkg.get(key)
        if sheet is None or "MATNR" not in sheet.df.columns:
            continue
        for v in sheet.df["MATNR"]:
            m = norm_matnr(v)
            if m:
                sap_keys.add(m)

    for sheet_key, field_name, sys_label in [
        ("HS_Products", "atn_sap_materialnummer", "HubSpot"),
        ("SF_Product2", "ATN_SAP_Materialnummer__c", "Salesforce"),
    ]:
        sheet = pkg.get(sheet_key)
        if sheet is None or field_name not in sheet.df.columns:
            continue
        for i, raw in sheet.df[field_name].items():
            m = norm_matnr(raw)
            if m is None:
                yield Finding(
                    rule_id=f"CONS_MATNR_MISSING_{sheet.key}",
                    rule_name="SAP-Materialnummer fehlt im CRM",
                    category="Konsistenz_Produkt",
                    dimension=DIM_CONSISTENCY,
                    system=sys_label,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"{sys_label}-Produkt ohne Verweis auf eine SAP-Materialnummer.",
                    severity=SEVERITY_HIGH,
                    explanation=(
                        f"Das {sys_label}-Produkt ist nicht mit einer SAP-Materialnummer verknüpft. "
                        "SAP ist laut Briefing führendes System für den Materialstamm."
                    ),
                    business_impact=(
                        "Ohne Verknüpfung kann das Produkt nicht mit dem führenden System "
                        "abgeglichen werden. Produktinformationen, Preise und Verfügbarkeit "
                        "können auseinanderlaufen."
                    ),
                    cause="Mapping-Feld wurde beim Anlegen nicht gepflegt.",
                    follow_on=[
                        "Preisabgleich SAP ↔ CRM nicht möglich",
                        "Produkt-Status-Abgleich SAP ↔ CRM nicht möglich",
                    ],
                    correction_suggestion="SAP-Materialnummer ergänzen und Sync-Prozess überprüfen.",
                    correction_type="Manuelle_Pruefung",
                    confidence="sicher",
                )
                continue
            if m not in sap_keys:
                yield Finding(
                    rule_id=f"CONS_MATNR_UNKNOWN_{sheet.key}",
                    rule_name="SAP-Materialnummer unbekannt im SAP-Stamm",
                    category="Konsistenz_Produkt",
                    dimension=DIM_CONSISTENCY,
                    system=sys_label,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=field_name,
                    value=raw,
                    record_id=_record_id(sheet, int(i)),
                    message=f"{sys_label}-Produkt verweist auf unbekannte SAP-Materialnummer '{m}'.",
                    severity=SEVERITY_HIGH,
                    explanation=(
                        "Die SAP-Materialnummer existiert nicht im geladenen SAP-Stamm. "
                        "Entweder ist die Nummer falsch erfasst oder der SAP-Export unvollständig."
                    ),
                    business_impact=(
                        "Zuordnung zu Produktstammdaten unmöglich - Preise, Katalog und "
                        "Service können nicht synchronisiert werden."
                    ),
                    cause="Falsche manuelle Erfassung oder zwischenzeitlich gelöschter SAP-Datensatz.",
                    follow_on=["Preis-Konsistenzprüfung nicht möglich", "Golden Record unvollständig"],
                    correction_suggestion="SAP-Materialnummer prüfen und ggf. aktualisieren.",
                    correction_type="Manuelle_Pruefung",
                    confidence="sicher",
                )


@registry.register(
    rule_id="CONSISTENCY_PRODUCT_NAME",
    name="Produktname konsistent SAP ↔ HubSpot ↔ Salesforce",
    description="Produktnamen stimmen systemübergreifend überein (SAP führend).",
    category="Konsistenz_Produkt",
    dimension=DIM_CONSISTENCY,
)
def rule_product_name(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    # SAP-Namen als Golden Reference laden
    sap_names: dict[str, str] = {}
    for key in ("SAP_FERT", "SAP_ERSA", "SAP_MARA"):
        sheet = pkg.get(key)
        if sheet is None or "MATNR" not in sheet.df.columns or "MAKTX" not in sheet.df.columns:
            continue
        for _, row in sheet.df.iterrows():
            m = norm_matnr(row["MATNR"])
            name = strip_str(row["MAKTX"])
            if m and name and m not in sap_names:
                sap_names[m] = name

    for sheet_key, matnr_field, name_field, sys_label in [
        ("HS_Products", "atn_sap_materialnummer", "name", "HubSpot"),
        ("SF_Product2", "ATN_SAP_Materialnummer__c", "Name", "Salesforce"),
    ]:
        sheet = pkg.get(sheet_key)
        if sheet is None or matnr_field not in sheet.df.columns or name_field not in sheet.df.columns:
            continue
        for i, row in sheet.df.iterrows():
            m = norm_matnr(row[matnr_field])
            other_name = strip_str(row[name_field])
            if not m or not other_name:
                continue
            sap_name = sap_names.get(m)
            if not sap_name:
                continue
            if norm_name(other_name) != norm_name(sap_name):
                yield Finding(
                    rule_id=f"CONS_NAME_{sheet.key}",
                    rule_name="Produktname weicht von SAP ab",
                    category="Konsistenz_Produkt",
                    dimension=DIM_CONSISTENCY,
                    system=sys_label,
                    file=sheet.source_file,
                    sheet=sheet.sheet_name,
                    row=sheet.excel_row(int(i)),
                    field_name=name_field,
                    value=other_name,
                    record_id=m,
                    message=(
                        f"Produktname weicht ab: {sys_label}='{other_name}' vs. SAP='{sap_name}'"
                    ),
                    severity=SEVERITY_MEDIUM,
                    explanation=(
                        "SAP ist laut Governance führendes System für Produktstammdaten. "
                        "Abweichende Namen führen zu Verwirrung bei Vertrieb und Marketing."
                    ),
                    business_impact=(
                        "Kunden finden Produkte unter unterschiedlichen Namen; "
                        "Vertrieb und Marketing arbeiten mit abweichenden Bezeichnungen."
                    ),
                    cause="Name im CRM manuell geändert, Sync-Prozess überträgt SAP-Namen nicht.",
                    correction_suggestion=f"Produktname auf SAP-Bezeichnung '{sap_name}' angleichen.",
                    correction_type="Vorschlag",
                    confidence="sicher",
                )


@registry.register(
    rule_id="CONSISTENCY_PRICE_CROSS_SYSTEM",
    name="Preis konsistent HubSpot ↔ Salesforce",
    description="Listenpreise in HubSpot und Salesforce dürfen nicht abweichen (Standardpreisbuch).",
    category="Konsistenz_Preis",
    dimension=DIM_CONSISTENCY,
)
def rule_price_cross(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    hs = pkg.get("HS_PriceBookItems")
    sf = pkg.get("SF_PricebookEntry")
    hs_products = pkg.get("HS_Products")
    sf_products = pkg.get("SF_Product2")
    if hs is None or sf is None or hs_products is None or sf_products is None:
        return

    # Mapping product_id -> MATNR
    hs_matnr: dict[str, str] = {}
    for _, row in hs_products.df.iterrows():
        pid = strip_str(row.get("hs_object_id"))
        m = norm_matnr(row.get("atn_sap_materialnummer"))
        if pid and m:
            hs_matnr[pid] = m
    sf_matnr: dict[str, str] = {}
    for _, row in sf_products.df.iterrows():
        pid = strip_str(row.get("Id"))
        m = norm_matnr(row.get("ATN_SAP_Materialnummer__c"))
        if pid and m:
            sf_matnr[pid] = m

    # Standardpreisbuch je System ermitteln
    hs_std_id = _standard_hs_pricebook(pkg)
    sf_std_id = _standard_sf_pricebook(pkg)

    # Preise je MATNR im Standardbuch
    hs_prices: dict[str, tuple[float, int]] = {}
    for i, row in hs.df.iterrows():
        if hs_std_id and strip_str(row.get("price_book_id")) != hs_std_id:
            continue
        pid = strip_str(row.get("hs_associated_product_id"))
        m = hs_matnr.get(pid or "")
        p = norm_price(row.get("hs_price_eur"))
        if m and p is not None:
            hs_prices[m] = (p, int(i))

    for i, row in sf.df.iterrows():
        if sf_std_id and strip_str(row.get("Pricebook2Id")) != sf_std_id:
            continue
        pid = strip_str(row.get("Product2Id"))
        m = sf_matnr.get(pid or "")
        p = norm_price(row.get("UnitPrice"))
        if not m or p is None:
            continue
        hs_entry = hs_prices.get(m)
        if not hs_entry:
            continue
        hs_price, _ = hs_entry
        if abs(hs_price - p) < 0.01:
            continue
        diff_pct = (abs(hs_price - p) / max(1, p)) * 100
        severity = SEVERITY_HIGH if diff_pct > 5 else SEVERITY_MEDIUM
        yield Finding(
            rule_id="CONS_PRICE_CROSS",
            rule_name="Preis-Differenz zwischen HubSpot und Salesforce",
            category="Konsistenz_Preis",
            dimension=DIM_CONSISTENCY,
            system="Salesforce",
            file=sf.source_file,
            sheet=sf.sheet_name,
            row=sf.excel_row(int(i)),
            field_name="UnitPrice",
            value=p,
            record_id=m,
            message=(
                f"Preis für MATNR {m}: HubSpot {hs_price:.2f} ≠ Salesforce {p:.2f} "
                f"(Differenz {diff_pct:.1f}%)."
            ),
            severity=severity,
            explanation=(
                "Für dieselbe SAP-Materialnummer liegen im Standard-Preisbuch unterschiedliche "
                "Preise in HubSpot und Salesforce vor."
            ),
            business_impact=(
                "Kund:innen sehen im Online-Katalog einen anderen Preis als im Angebot. "
                "Dadurch entstehen ungeplante Rabatte oder verzögerte Angebote."
            ),
            cause="Preis wurde in einem System ohne Sync aktualisiert.",
            follow_on=["Rabattierung inkonsistent", "Angebote müssen manuell geprüft werden"],
            correction_suggestion=(
                "Führendes System für Preise in der Governance festlegen und Sync wiederherstellen."
            ),
            correction_type="Manuelle_Pruefung",
            confidence="sicher",
        )


@registry.register(
    rule_id="CONSISTENCY_STATUS_CROSS",
    name="Produktstatus konsistent SAP ↔ HubSpot ↔ Salesforce",
    description="Produkte mit Löschvormerkung in SAP oder Status 99 sollten in CRM/Marketing deaktiviert sein.",
    category="Konsistenz_Produkt",
    dimension=DIM_CONSISTENCY,
)
def rule_status_cross(pkg: DataPackage, cfg: Config) -> Iterable[Finding]:
    # SAP-Status pro MATNR (aus MARA / MARC)
    sap_status: dict[str, dict[str, str]] = {}
    for key in ("SAP_MARA", "SAP_FERT", "SAP_ERSA"):
        sheet = pkg.get(key)
        if sheet is None or "MATNR" not in sheet.df.columns:
            continue
        for _, row in sheet.df.iterrows():
            m = norm_matnr(row["MATNR"])
            if not m:
                continue
            data = sap_status.setdefault(m, {})
            for col in ("MSTAE", "MMSTA", "LVORM"):
                v = strip_str(row.get(col))
                if v and col not in data:
                    data[col] = v

    def is_sap_discontinued(matnr: str) -> bool:
        info = sap_status.get(matnr) or {}
        if strip_str(info.get("LVORM")):
            return True
        if info.get("MSTAE") in ("99", "AL", "01"):  # 99 Auslauf, AL Auslauf
            if info.get("MSTAE") == "99":
                return True
        if info.get("MMSTA") in ("99",):
            return True
        return False

    # HubSpot
    hs = pkg.get("HS_Products")
    if hs is not None and "atn_sap_materialnummer" in hs.df.columns and "hs_status" in hs.df.columns:
        for i, row in hs.df.iterrows():
            m = norm_matnr(row["atn_sap_materialnummer"])
            if not m:
                continue
            if is_sap_discontinued(m) and norm_upper(row["hs_status"]) == "ACTIVE":
                yield Finding(
                    rule_id="CONS_STATUS_HS",
                    rule_name="HubSpot bewirbt ausgelaufenes Produkt",
                    category="Konsistenz_Produkt",
                    dimension=DIM_CONSISTENCY,
                    system="HubSpot",
                    file=hs.source_file,
                    sheet=hs.sheet_name,
                    row=hs.excel_row(int(i)),
                    field_name="hs_status",
                    value=row["hs_status"],
                    record_id=m,
                    message=f"HubSpot-Status ACTIVE, aber SAP-Material {m} ist ausgelaufen/zur Löschung vorgemerkt.",
                    severity=SEVERITY_HIGH,
                    explanation=(
                        "Das Produkt ist in SAP als auslaufend/zur Löschung markiert, wird im "
                        "HubSpot-Katalog aber noch als aktiv geführt."
                    ),
                    business_impact=(
                        "Marketing bewirbt ein Produkt, das es faktisch nicht mehr gibt. "
                        "Kampagnen-Klicks landen auf Fehlerseiten oder generieren Leads, die nicht bedient werden können."
                    ),
                    cause="Status-Sync zwischen SAP und HubSpot funktioniert nicht.",
                    follow_on=["Leads für nicht lieferbare Produkte", "SEO-Rankings auf veraltete Seiten"],
                    correction_suggestion="HubSpot-Status auf INACTIVE/ARCHIVED setzen.",
                    correction_type="Vorschlag",
                    confidence="sicher",
                )

    # Salesforce
    sf = pkg.get("SF_Product2")
    if sf is not None and "ATN_SAP_Materialnummer__c" in sf.df.columns and "IsActive" in sf.df.columns:
        for i, row in sf.df.iterrows():
            m = norm_matnr(row["ATN_SAP_Materialnummer__c"])
            if not m:
                continue
            if is_sap_discontinued(m) and norm_upper(row["IsActive"]) == "TRUE":
                yield Finding(
                    rule_id="CONS_STATUS_SF",
                    rule_name="Salesforce verkauft ausgelaufenes Produkt",
                    category="Konsistenz_Produkt",
                    dimension=DIM_CONSISTENCY,
                    system="Salesforce",
                    file=sf.source_file,
                    sheet=sf.sheet_name,
                    row=sf.excel_row(int(i)),
                    field_name="IsActive",
                    value=row["IsActive"],
                    record_id=m,
                    message=f"Salesforce-Produkt aktiv, aber SAP-Material {m} ist ausgelaufen.",
                    severity=SEVERITY_HIGH,
                    explanation=(
                        "Das Produkt ist in SAP als auslaufend markiert, der Vertrieb kann es "
                        "aber weiterhin anbieten."
                    ),
                    business_impact=(
                        "Angebote für Produkte, die nicht mehr geliefert werden können, führen "
                        "zu Nacharbeiten und möglichem Vertrauensverlust."
                    ),
                    cause="Status-Sync zwischen SAP und Salesforce funktioniert nicht.",
                    follow_on=["Angebote für Produkte ohne Verfügbarkeit", "Service-Anfragen für Phantom-Produkte"],
                    correction_suggestion="Salesforce-Produkt deaktivieren (IsActive=False).",
                    correction_type="Vorschlag",
                    confidence="sicher",
                )


def _standard_hs_pricebook(pkg: DataPackage) -> str | None:
    pb = pkg.get("HS_PriceBooks")
    if pb is None or "hs_name" not in pb.df.columns:
        return None
    for _, row in pb.df.iterrows():
        name = strip_str(row.get("hs_name")) or ""
        if "standard" in name.lower():
            return strip_str(row.get("hs_object_id"))
    return None


def _standard_sf_pricebook(pkg: DataPackage) -> str | None:
    pb = pkg.get("SF_Pricebook2")
    if pb is None:
        return None
    for _, row in pb.df.iterrows():
        if norm_upper(row.get("IsStandard")) == "TRUE" and norm_upper(row.get("Name", "")).startswith("STANDARD"):
            return strip_str(row.get("Id"))
    # Fallback: erste Zeile mit IsStandard=True
    for _, row in pb.df.iterrows():
        if norm_upper(row.get("IsStandard")) == "TRUE":
            return strip_str(row.get("Id"))
    return None


def _record_id(sheet, idx):
    for cand in ("hs_object_id", "Id", "MATNR", "WorkOrderNumber", "SerialNumber"):
        if cand in sheet.df.columns:
            v = sheet.df.iloc[idx][cand]
            if not is_missing(v):
                return str(v).strip()
    return None

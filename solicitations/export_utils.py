"""
Utility functions for exporting solicitation data to DLA format text files.
Generates comma-separated text files with 121 fields in exact positions.
"""
import csv
import os
from datetime import datetime
from decimal import Decimal, InvalidOperation
from io import StringIO
from django.conf import settings
from django.db.models import Prefetch
from .models import ExportFieldDefinition, UserExportConfiguration, Solicitation, RfqReplyExportOverride


def _to_quantity_decimal(value):
    """Return a Decimal for DLA quantity comparisons, or None when blank/invalid."""
    text = str(value or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _quantities_match(left, right):
    left_num = _to_quantity_decimal(left)
    right_num = _to_quantity_decimal(right)
    if left_num is not None and right_num is not None:
        return left_num == right_num
    return str(left or "").strip() == str(right or "").strip()


def normalize_row_23_alternate_disputes_resolution(value):
    """Normalize legacy Y/N ADR values to DIBBS A/B values."""
    text = str(value or "").strip().upper()
    if text == "Y":
        return "A"
    if text == "N":
        return "B"
    return text


def apply_row_23_alternate_disputes_resolution_rule(values):
    """Normalize row 023 Alternate Disputes Resolution to DIBBS A/B codes."""
    try:
        if len(values) >= 23:
            values[22] = normalize_row_23_alternate_disputes_resolution(values[22])
    except Exception:
        pass
    return values


def validate_row_23_alternate_disputes_resolution(value):
    """
    Validate row 023 Alternate Disputes Resolution.
    Returns an error message string, or an empty string when valid.
    """
    text = normalize_row_23_alternate_disputes_resolution(value)
    if not text:
        return "Alternate Disputes Resolution is required"
    if text not in {"A", "B"}:
        return "Alternate Disputes Resolution must be A or B"
    return ""


def _clean_export_value(value):
    """Return a single-line string value safe for one DIBBS CSV field."""
    text = str(value or "")
    return text.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")


def normalize_export_values(values):
    """Return exactly 121 cleaned export values."""
    normalized = [_clean_export_value(value) for value in list(values or [])[:121]]
    while len(normalized) < 121:
        normalized.append("")
    return normalized


def serialize_export_values(values):
    """Serialize exactly 121 values as one fully quoted CSV line."""
    normalized = normalize_export_values(values)
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator="")
    writer.writerow(normalized)
    line = output.getvalue()
    parsed = list(csv.reader([line]))
    if len(parsed) != 1 or len(parsed[0]) != 121:
        parsed_count = len(parsed[0]) if parsed else 0
        raise ValueError(f"Export line has {parsed_count} columns, expected 121")
    return line


def validate_export_file_structure(content):
    """
    Validate final DIBBS batch content using CSV parsing, not comma counting.
    Returns a list of error strings.
    """
    errors = []
    text = str(content or "")
    if not text:
        return ["Export file is empty"]

    lines = text.splitlines()
    if not lines:
        return ["Export file is empty"]

    for index, line in enumerate(lines, 1):
        if not line.strip():
            errors.append(f"Batch file line {index:03d} is blank")
            continue
        try:
            parsed_rows = list(csv.reader([line]))
        except csv.Error as exc:
            errors.append(f"Batch file line {index:03d} cannot be parsed: {exc}")
            continue
        if len(parsed_rows) != 1:
            errors.append(f"Batch file line {index:03d} is not a single CSV record")
            continue
        column_count = len(parsed_rows[0])
        if column_count != 121:
            errors.append(f"Batch file line {index:03d} has {column_count} columns, expected 121")

    return errors


def get_rfq_requirement_quantity(rfq_reply):
    """Get row 049 RFQ requirement quantity from the matched solicitation."""
    try:
        solicitation = None
        if getattr(rfq_reply, "rfq", None) and getattr(rfq_reply.rfq, "solicitation", None):
            solicitation = rfq_reply.rfq.solicitation
        if not solicitation and hasattr(rfq_reply, "find_matching_solicitation"):
            solicitation = rfq_reply.find_matching_solicitation()
        if solicitation and getattr(solicitation, "quantity", None):
            return str(solicitation.quantity).strip()
    except Exception:
        pass
    return str(getattr(rfq_reply, "quantity", "") or "").strip()


def apply_row_49_quantity_rule(values, requirement_quantity=""):
    """
    Apply row 049 quantity effects to row 024.
    Validation still blocks prohibited quantity changes.
    """
    try:
        if len(values) < 49:
            return values

        quoted_quantity = str(values[48]).strip()
        quoted_quantity_num = _to_quantity_decimal(quoted_quantity)
        if quoted_quantity and quoted_quantity_num == 0 and len(values) >= 24:
            values[23] = "DQ"
            return values

        if not quoted_quantity or not requirement_quantity:
            return values

        if not _quantities_match(quoted_quantity, requirement_quantity) and len(values) >= 24:
            solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
            nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
            prohibited_parts = {"0001S00000052", "0001S00000053"}
            if solicitation_type != "I" and nsn_part not in prohibited_parts:
                bid_type = str(values[23]).strip().upper()
                if bid_type not in {"BW", "AB"}:
                    values[23] = "BW"
    except Exception:
        pass
    return values


def validate_row_50_unit_price(value):
    """
    Validate row 050 Unit Price.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().replace(",", "")
    if not text:
        return "Unit Price cannot be blank"
    if text.startswith("+") or text.startswith("-"):
        return "Unit Price must be between 0 and 9999999.99999"
    parts = text.split(".")
    if len(parts) > 2:
        return "Unit Price must be numeric"
    whole = parts[0]
    decimals = parts[1] if len(parts) == 2 else ""
    if whole == "" and decimals == "":
        return "Unit Price must be numeric"
    if whole and not whole.isdigit():
        return "Unit Price must be numeric"
    if decimals and not decimals.isdigit():
        return "Unit Price must be numeric"
    if len(decimals) > 5:
        return "Unit Price cannot have more than 5 decimal places"
    try:
        amount = Decimal(text)
    except (InvalidOperation, ValueError):
        return "Unit Price must be numeric"
    if amount < Decimal("0") or amount > Decimal("9999999.99999"):
        return "Unit Price must be between 0 and 9999999.99999"
    return ""


def validate_row_51_delivery_days(value, solicitation_number=""):
    """
    Validate row 051 Delivery Days.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    if not text:
        return "Delivery Days cannot be blank"
    if not text.isdigit():
        return "Delivery Days must be a whole number"
    max_length = 3 if str(solicitation_number or "").strip().upper().startswith("SPM") else 4
    if len(text) > max_length:
        return f"Delivery Days cannot exceed {max_length} digits"
    try:
        days = int(text)
    except ValueError:
        return "Delivery Days must be a whole number"
    if days < 0 or days > 9999:
        return "Delivery Days must be between 0 and 9999"
    return ""


def apply_row_51_delivery_days_rule(values):
    """
    Apply row 051 Delivery Days effects to row 024 when row 050 is zero.
    Validation still blocks row 064 N with zero delivery days.
    """
    try:
        if len(values) < 51:
            return values
        unit_price = _to_quantity_decimal(values[49] if len(values) >= 50 else "")
        delivery_days_text = str(values[50]).strip()
        delivery_days = int(delivery_days_text) if delivery_days_text.isdigit() else None
        nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
        special_parts = {"0001S00000052", "0001S00000053"}
        if unit_price == Decimal("0") and delivery_days == 0 and nsn_part in special_parts and len(values) >= 24:
            bid_type = str(values[23]).strip().upper()
            if bid_type not in {"BW", "AB"}:
                values[23] = "BW"
    except Exception:
        pass
    return values


def apply_row_56_no_do_minimum_rule(values):
    """Blank row 056 unless Solicitation Type Indicator (row 002) is I."""
    try:
        if len(values) >= 56:
            solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
            if solicitation_type != "I":
                values[55] = ""
    except Exception:
        pass
    return values


def validate_row_56_no_do_minimum(value, solicitation_type):
    """
    Validate row 056 No DO Minimum Quantity.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    solicitation_type = str(solicitation_type or "").strip().upper()
    if solicitation_type != "I":
        if text:
            return "No DO Minimum Quantity must be blank when Solicitation Type Indicator is not I"
        return ""
    if not text:
        return "No DO Minimum Quantity is required when Solicitation Type Indicator is I"
    if text not in {"Y", "N"}:
        return "No DO Minimum Quantity must be Y or N"
    return ""


def apply_row_58_hubzone_waiver_rule(values):
    """Blank row 058 unless row 057 is Y and row 013 is B or M."""
    try:
        if len(values) >= 58:
            hubzone = str(values[56]).strip().upper() if len(values) >= 57 else ""
            small_business_code = str(values[12]).strip().upper() if len(values) >= 13 else ""
            if hubzone == "N" or (hubzone == "Y" and small_business_code not in {"B", "M"}):
                values[57] = ""
    except Exception:
        pass
    return values


def validate_row_58_hubzone_waiver(value, hubzone, small_business_code):
    """
    Validate row 058 Waiver of HUBZone Preference.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    hubzone = str(hubzone or "").strip().upper()
    small_business_code = str(small_business_code or "").strip().upper()
    if hubzone == "N":
        return "Waiver of HUBZone Preference must be blank when HUBZone Preference Indicator is N" if text else ""
    if hubzone == "Y" and small_business_code not in {"B", "M"}:
        return "Waiver of HUBZone Preference must be blank when Small Business Code is not B or M" if text else ""
    if hubzone == "Y" and small_business_code in {"B", "M"}:
        if not text:
            return "Waiver of HUBZone Preference is required when HUBZone Preference Indicator is Y and Small Business Code is B or M"
        if text not in {"Y", "N", "A"}:
            return "Waiver of HUBZone Preference must be Y, N, or A"
    return ""


def apply_row_59_immediate_shipment_price_rule(values):
    """Blank row 059 unless Immediate Shipment Available (row 100) is Y."""
    try:
        if len(values) >= 100:
            immediate_available = str(values[99]).strip().upper()
            if immediate_available != "Y" and len(values) >= 59:
                values[58] = ""
    except Exception:
        pass
    return values


def validate_row_59_immediate_shipment_price(value, immediate_available):
    """
    Validate row 059 Immediate Shipment Price.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    immediate_available = str(immediate_available or "").strip().upper()
    if immediate_available == "N":
        return "Immediate Shipment Price must be blank when Immediate Shipment Available is N" if text else ""
    if immediate_available == "Y":
        if not text:
            return "Immediate Shipment Price is required when Immediate Shipment Available is Y"
        price_error = validate_row_50_unit_price(text)
        if price_error:
            return price_error.replace("Unit Price", "Immediate Shipment Price")
    return ""


def apply_row_60_immediate_shipment_delivery_rule(values):
    """Blank row 060 unless Immediate Shipment Available (row 100) is Y."""
    try:
        if len(values) >= 100:
            immediate_available = str(values[99]).strip().upper()
            if immediate_available != "Y" and len(values) >= 60:
                values[59] = ""
    except Exception:
        pass
    return values


def validate_row_60_immediate_shipment_delivery(value, immediate_available):
    """
    Validate row 060 Immediate Shipment Delivery Days.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    immediate_available = str(immediate_available or "").strip().upper()
    if immediate_available == "N":
        return "Immediate Shipment Delivery Days must be blank when Immediate Shipment Available is N" if text else ""
    if immediate_available == "Y":
        if not text:
            return "Immediate Shipment Delivery Days is required when Immediate Shipment Available is Y"
        delivery_error = validate_row_51_delivery_days(text, "")
        if delivery_error:
            return delivery_error.replace("Delivery Days", "Immediate Shipment Delivery Days")
    return ""


def apply_row_63_source_supply_cage_rule(values):
    """Blank row 063 unless Manufacturer/Dealer (row 102) is QD."""
    try:
        if len(values) >= 102:
            manufacturer_dealer = str(values[101]).strip().upper()
            if manufacturer_dealer != "QD" and len(values) >= 63:
                values[62] = ""
    except Exception:
        pass
    return values


def validate_row_63_source_supply_cage(value, manufacturer_dealer):
    """
    Validate row 063 Source of Supply CAGE Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    manufacturer_dealer = str(manufacturer_dealer or "").strip().upper()
    if manufacturer_dealer != "QD":
        return "Source of Supply CAGE Code must be blank when Manufacturer/Dealer is not QD" if text else ""
    if not text:
        return "Source of Supply CAGE Code is required when Manufacturer/Dealer is QD"
    if len(text) > 5:
        return "Source of Supply CAGE Code cannot exceed 5 characters"
    return ""


def apply_row_64_first_article_waiver_rule(values):
    """Blank row 064 unless NSN/Part Number (row 47) is one of the FAT waiver parts."""
    try:
        if len(values) >= 64:
            nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
            allowed_parts = {"0001S00000052", "0001S00000053"}
            if nsn_part not in allowed_parts:
                values[63] = ""
            else:
                waiver_code = str(values[63]).strip().upper()
                values[63] = waiver_code if waiver_code in {"N", "Y"} else ""
    except Exception:
        pass
    return values


def validate_row_64_first_article_waiver(value, nsn_part):
    """
    Validate row 064 First Article Waiver Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    nsn_part = str(nsn_part or "").strip().upper()
    allowed_parts = {"0001S00000052", "0001S00000053"}
    if nsn_part not in allowed_parts:
        return "First Article Waiver Code must be blank when NSN/Part Number is not 0001S00000052 or 0001S00000053" if text else ""
    if not text:
        return "First Article Waiver Code is required for this NSN/Part Number"
    if text not in {"N", "Y"}:
        return "First Article Waiver Code must be N or Y"
    return ""


def apply_row_67_material_requirements_rule(values):
    """Force row 024 to BW/AB when row 002 is I and row 067 is 4."""
    try:
        if len(values) >= 67:
            solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
            material_requirement = str(values[66]).strip()
            if solicitation_type == "I" and material_requirement == "4" and len(values) >= 24:
                bid_type = str(values[23]).strip().upper()
                if bid_type not in {"BW", "AB"}:
                    values[23] = "BW"
    except Exception:
        pass
    return values


def validate_row_67_material_requirements(value, solicitation_type, bid_type):
    """
    Validate row 067 Material Requirements.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    solicitation_type = str(solicitation_type or "").strip().upper()
    bid_type = str(bid_type or "").strip().upper()
    if not text:
        return "Material Requirements is required"
    if text not in {"0", "1", "2", "3", "4"}:
        return "Material Requirements must be 0, 1, 2, 3, or 4"
    if solicitation_type == "I" and text == "4" and bid_type not in {"BW", "AB"}:
        return "Bid Type Code must be BW or AB when Solicitation Type Indicator is I and Material Requirements is 4"
    return ""


def get_row_70_valid_end_product_codes(trade_agreement, buy_american, free_trade):
    """Return the allowed row 070 codes based on rows 062, 068, and 069."""
    trade_agreement = str(trade_agreement or "").strip().upper()
    buy_american = str(buy_american or "").strip().upper()
    free_trade = str(free_trade or "").strip().upper()
    if trade_agreement == "Y":
        return {"US", "QD", "DE", "ND"}, "Trade Agreements End Product"
    if free_trade == "Y":
        return {"D", "N", "QA", "O"}, "FTA-BAA-BOPP"
    if free_trade == "A":
        return {"D", "C", "QE", "O"}, "FTA ALT I"
    if free_trade == "B":
        return {"D", "P", "QA", "O"}, "FTA ALT IV"
    if buy_american in {"Y", "I"} or (trade_agreement == "N" and buy_american == "N" and free_trade == "N"):
        return {"D", "Q", "NQ"}, "BAA-BOPP"
    return set(), ""


def validate_row_70_end_product(value, trade_agreement, buy_american, free_trade):
    """
    Validate row 070 Buy American/Free Trade/Trade Agreements End Product.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    valid_codes, rule_name = get_row_70_valid_end_product_codes(
        trade_agreement,
        buy_american,
        free_trade
    )
    if not valid_codes:
        return "End Product code is required after rows 62, 68, and 69 are set" if not text else "End Product code has no matching rule for rows 62, 68, and 69"
    if not text:
        return f"End Product code is required for {rule_name}"
    if text not in valid_codes:
        return f"End Product code must be one of {', '.join(sorted(valid_codes))} for {rule_name}"
    return ""


ROW_71_FTA_A_CODES = set("AF AL DZ AS AD AO AI AQ AG AR AM AW AZ BS BH BD BB BY BZ BJ BM BT BO BQ BA BW BV BR IO BN BG BF BI CV KH CM KY CF TD CL CN CX CC CO KM CG CD CK CR CI HR CW CY DJ DM DO EC SV GQ ER SZ ET FK FO FJ GF PF TF GA GM GE GH GI GL GD GP GU GT GN GW GY HT HM VA HN HK HU IS IN ID IQ IE IM JM JO KZ KE KI KR XK KW KG LA LB LS LR LY LI MO MG MW MY MV ML MT MH MQ MR MU YT MX FM MD MC MN ME MS MA MZ NA NR NP NC NZ NI NE NG NU NF MK MP OM PK PW PS PA PG PY PE PH PN PR QA RE RO RU RW SH KN LC MF PM VC WS SM ST SA SN RS SC SL SG SX SK SB SO ZA GS SS LK SR SJ SY TW TJ TZ TH TL TG TK TT TN TM TC TV UG UA AE UM UY UZ VU VE VN VI VG WF EH YE ZM ZW".split())
ROW_71_FTA_B_CODES = set("AF AL DZ AS AD AO AI AQ AG AR AM AW AZ BS BH BD BB BY BZ BJ BM BT BO BQ BA BW BV BR IO BN BG BF BI CV KH CM KY CF TD CN CX CC KM CG CD CK CI HR CW CY DJ DM EC GQ ER SZ ET FK FO FJ GF PF TF GA GM GE GH GI GL GD GP GU GN GW GY HT HM VA HK HU IS IN ID IQ IE IM JM JO KZ KE KI KR XK KW KG LA LB LS LR LY LI MO MG MW MY MV ML MT MH MQ MR MU YT FM MD MC MN ME MS MA MZ NA NR NP NC NZ NE NG NU NF MK MP OM PK PW PS PA PG PY PE PH PN PR QA RE RO RU RW SH KN LC MF PM VC WS SM ST SA SN RS SC SL SX SK SB SO ZA GS SS LK SR SJ SY TW TJ TZ TH TL TG TK TT TN TM TC TV UG UA AE UM UY UZ VU VE VN VI VG WF EH YE ZM ZW".split())
ROW_71_FTA_Y_CODES = set("AF AL DZ AS AD AO AI AQ AG AR AM AW AZ BS BH BD BB BY BZ BJ BM BT BO BQ BA BW BV BR IO BN BG BF BI CV KH CM KY CF TD CN CX CC KM CG CD CK CI FK HR CW CY DJ DM EC GQ ER SZ ET FO FJ GF PF TF GA GM GE GH GI GL GD GP GU GN GW GY HT HM VA HK HU IS IN ID IQ IE IM JM JO KZ KE KI XK KW KG LA LB LS LR LY LI MO MG MW MY MV ML MT MH MQ MR MU YT FM MD MC MN ME MS MA MZ NA NR NP NC NZ NE NG NU NF MK MP OM PK PW PS PG PY PE PH PN PR QA RE RO RU RW SH KN LC MF PM VC WS SM SA ST SN RS SC SL SX SK SB SO ZA GS SS LK SR SJ SY TW TJ TZ TH TL TG TK TT TN TM TC TV UG UA AE UM UY UZ VU VE VN VI VG WF EH YE ZM ZW".split())
ROW_71_NQ_CODES = ROW_71_FTA_A_CODES
ROW_71_ND_CODES = set("AL DZ AS AD AI AQ AR AZ BY BM BO BA BW BV BR IO BN CV CM KY CN CX CC CG CK CI EC SZ FK FO FJ GF PF TF GA GE GH GI GL GP GU HM VA IN ID IQ IM JO KZ KE XK KW KG LB LY MO MY MV MH MQ MU YT FM MC MN NA NR NC NG NU NF MP OM PK PW PS PG PY PH PN PR QA RE RU SH PM SM SA RS SC ZA GS LK SR SJ SY TJ TH TK TT TN TM TC AE UM UY UZ VE VN VI WF EH ZW".split())


def apply_row_71_country_origin_rule(values):
    """Blank row 071 when row 070 does not allow a country of origin code."""
    try:
        if len(values) >= 71:
            end_product = str(values[69]).strip().upper() if len(values) >= 70 else ""
            if end_product not in {"NQ", "O", "ND", "US"}:
                values[70] = ""
    except Exception:
        pass
    return values


def get_row_71_valid_country_codes(trade_agreement, buy_american, free_trade, end_product):
    """Return the allowed row 071 country codes based on rows 062, 068, 069, and 070."""
    trade_agreement = str(trade_agreement or "").strip().upper()
    buy_american = str(buy_american or "").strip().upper()
    free_trade = str(free_trade or "").strip().upper()
    end_product = str(end_product or "").strip().upper()
    if end_product == "O" and free_trade == "A":
        return ROW_71_FTA_A_CODES, "Free Trade Agreements ALT I"
    if end_product == "O" and free_trade == "B":
        return ROW_71_FTA_B_CODES, "Free Trade Agreements ALT IV"
    if end_product == "O" and free_trade == "Y":
        return ROW_71_FTA_Y_CODES, "Free Trade Agreements"
    if end_product == "NQ" and buy_american in {"Y", "I"}:
        return ROW_71_NQ_CODES, "Non-Qualifying Country End Products"
    if end_product == "ND" and trade_agreement == "Y":
        return ROW_71_ND_CODES, "Non-Designated Country End Products"
    return set(), ""


def validate_row_71_country_origin(value, trade_agreement, buy_american, free_trade, end_product):
    """
    Validate row 071 Buy American/Free Trade Agreements/Trade Agreements Country of Origin Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    end_product = str(end_product or "").strip().upper()
    if end_product not in {"NQ", "O", "ND", "US"}:
        return "Country of Origin Code must be blank when End Product is not NQ, O, ND, or US" if text else ""
    valid_codes, rule_name = get_row_71_valid_country_codes(
        trade_agreement,
        buy_american,
        free_trade,
        end_product
    )
    if not valid_codes:
        return ""
    if not text:
        return f"Country of Origin Code is required for {rule_name}"
    if text not in valid_codes:
        return f"Country of Origin Code must be a valid country code for {rule_name}"
    return ""


ROW_72_Q_CODES = set("AU AT BE CA CZ DK EG EE FI FR DE GR IL IT JP LV LT LU NL NO PL PT SI ES SE CH TR GB".split())
ROW_72_QA_CODES = set("AT BE CZ DK EG EE FI FR DE GR IL IT JP LV LT LU NL NO PL PT SI ES SE CH TR GB".split())
ROW_72_QD_CODES = ROW_72_Q_CODES
ROW_72_QE_CODES = set("AU AT BE CZ DK EG EE FI FR DE GR IL IT JP LV LT LU NL NO PL PT SI ES SE CH TR GB".split())
ROW_72_C_CODES = {"CA"}
ROW_72_N_CODES = set("AU CA CL CO CR DO SV GT HN KR MX NI SG".split())
ROW_72_P_CODES = set("AU CA CL CO CR DO SV GT HN MX NI SG".split())
ROW_72_DE_CODES = set("AF AO AG AM AW BS BH BD BB BZ BJ BT BQ BG BF BI KH CF TD CL CO KM CD CR HR CW CY DJ DM DO SV GQ ER ET GM GD GT GN GW GY HT HN HK HU IS IE JM KI KR LA LS LR LI MG MW ML MT MR MX MD ME MS MA MZ NP NZ NI NE MK PA PE RO RW KN LC VC WS ST SN SL SG SX SK SB SO SS TW TZ TL TG TT TV UG UA VU VG YE ZM".split())


def apply_row_72_country_code_rule(values):
    """Blank row 072 when row 070 does not allow a country code."""
    try:
        if len(values) >= 72:
            end_product = str(values[69]).strip().upper() if len(values) >= 70 else ""
            if end_product in {"D", "NQ", "O", "ND", "US"}:
                values[71] = ""
    except Exception:
        pass
    return values


def get_row_72_valid_country_codes(end_product):
    """Return the allowed row 072 country codes based on row 070."""
    end_product = str(end_product or "").strip().upper()
    if end_product == "Q":
        return ROW_72_Q_CODES, "BAA Qualifying Country End Products"
    if end_product == "QA":
        return ROW_72_QA_CODES, "FTA Qualifying Country except Canada and Australia"
    if end_product == "QD":
        return ROW_72_QD_CODES, "Trade Agreement Qualified Country"
    if end_product == "QE":
        return ROW_72_QE_CODES, "FTA Qualifying Country except Canada"
    if end_product == "C":
        return ROW_72_C_CODES, "FTA Canadian End Products"
    if end_product == "N":
        return ROW_72_N_CODES, "FTA ALT I Country End Products"
    if end_product == "P":
        return ROW_72_P_CODES, "FTA Country End Products"
    if end_product == "DE":
        return ROW_72_DE_CODES, "Trade Agreement Designated Country"
    return set(), ""


def validate_row_72_country_code(value, end_product):
    """
    Validate row 072 Buy American/Free Trade/Trade Agreements Country Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    end_product = str(end_product or "").strip().upper()
    if end_product in {"D", "NQ", "O", "ND", "US"}:
        return "Country Code must be blank when End Product is D, NQ, O, ND, or US" if text else ""
    valid_codes, rule_name = get_row_72_valid_country_codes(end_product)
    if not valid_codes:
        return ""
    if not text:
        return f"Country Code is required for {rule_name}"
    if text not in valid_codes:
        return f"Country Code must be a valid country code for {rule_name}"
    return ""


def apply_row_73_duty_free_entry_rule(values):
    """Blank row 073 when Buy American Indicator (row 068) is I."""
    try:
        if len(values) >= 73:
            buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
            if buy_american == "I":
                values[72] = ""
    except Exception:
        pass
    return values


def validate_row_73_duty_free_entry(value, buy_american):
    """
    Validate row 073 Duty Free Entry Requested.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    buy_american = str(buy_american or "").strip().upper()
    if buy_american == "I":
        return "Duty Free Entry Requested must be blank when Buy American Indicator is I" if text else ""
    if text and text not in {"Y", "N"}:
        return "Duty Free Entry Requested must be Y or N"
    return ""


def apply_row_74_foreign_supplies_rule(values):
    """Blank row 074 when row 068 is I or row 073 is not Y."""
    try:
        if len(values) >= 74:
            buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
            duty_free_entry = str(values[72]).strip().upper() if len(values) >= 73 else ""
            if buy_american == "I" or duty_free_entry != "Y":
                values[73] = ""
    except Exception:
        pass
    return values


def validate_row_74_foreign_supplies(value, buy_american, duty_free_entry):
    """
    Validate row 074 Duty Free Entry Requested/Foreign Supplies in US Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    buy_american = str(buy_american or "").strip().upper()
    duty_free_entry = str(duty_free_entry or "").strip().upper()
    if buy_american == "I":
        return "Foreign Supplies in US Code must be blank when Buy American Indicator is I" if text else ""
    if duty_free_entry != "Y":
        return "Foreign Supplies in US Code must be blank when Duty Free Entry Requested is not Y" if text else ""
    if text and text not in {"Y", "N"}:
        return "Foreign Supplies in US Code must be Y or N"
    return ""


def apply_row_75_duty_paid_rule(values):
    """Blank row 075 when row 068 is I or row 074 is not Y."""
    try:
        if len(values) >= 75:
            buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
            foreign_supplies = str(values[73]).strip().upper() if len(values) >= 74 else ""
            if buy_american == "I" or foreign_supplies != "Y":
                values[74] = ""
    except Exception:
        pass
    return values


def validate_row_75_duty_paid(value, buy_american, foreign_supplies):
    """
    Validate row 075 Duty Free Entry Requested/Duty Paid Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    buy_american = str(buy_american or "").strip().upper()
    foreign_supplies = str(foreign_supplies or "").strip().upper()
    if buy_american == "I":
        return "Duty Paid Code must be blank when Buy American Indicator is I" if text else ""
    if foreign_supplies != "Y":
        return "Duty Paid Code must be blank when Foreign Supplies in US Code is not Y" if text else ""
    if text and text not in {"Y", "N"}:
        return "Duty Paid Code must be Y or N"
    return ""


def apply_row_76_duty_paid_amount_rule(values):
    """Blank row 076 when row 068 is I or row 075 is not N."""
    try:
        if len(values) >= 76:
            buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
            duty_paid = str(values[74]).strip().upper() if len(values) >= 75 else ""
            if buy_american == "I" or duty_paid != "N":
                values[75] = ""
    except Exception:
        pass
    return values


def validate_row_76_duty_paid_amount(value, buy_american, duty_paid):
    """
    Validate row 076 Duty Free Entry Requested/Duty Paid Amount.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    buy_american = str(buy_american or "").strip().upper()
    duty_paid = str(duty_paid or "").strip().upper()
    if buy_american == "I":
        return "Duty Paid Amount must be blank when Buy American Indicator is I" if text else ""
    if duty_paid != "N":
        return "Duty Paid Amount must be blank when Duty Paid Code is not N" if text else ""
    if text and len(text) > 15:
        return "Duty Paid Amount cannot exceed 15 characters"
    return ""


def validate_row_96_quantity_variance_plus(value):
    """
    Validate row 096 Quantity Variance Plus.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.isdigit():
        return "Quantity Variance Plus must be a whole number"
    if len(text) > 2:
        return "Quantity Variance Plus cannot exceed 2 characters"
    try:
        amount = int(text)
    except ValueError:
        return "Quantity Variance Plus must be a whole number"
    if amount < 0 or amount > 10:
        return "Quantity Variance Plus must be between 0 and 10"
    return ""


def validate_row_97_quantity_variance_minus(value):
    """
    Validate row 097 Quantity Variance Minus.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.isdigit():
        return "Quantity Variance Minus must be a whole number"
    if len(text) > 2:
        return "Quantity Variance Minus cannot exceed 2 characters"
    try:
        amount = int(text)
    except ValueError:
        return "Quantity Variance Minus must be a whole number"
    if amount < 0 or amount > 10:
        return "Quantity Variance Minus must be between 0 and 10"
    return ""


def validate_row_98_minimum_order_quantity_code(value, solicitation_type):
    """
    Validate row 098 Minimum Order Quantity Code.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    solicitation_type = str(solicitation_type or "").strip().upper()
    if solicitation_type in {"", "F", "P"} and not text:
        return "Minimum Order Quantity Code is required when Solicitation Type is blank, F, or P"
    if text and text not in {"Y", "N"}:
        return "Minimum Order Quantity Code must be Y or N"
    return ""


def validate_row_99_minimum_order_maximum_quantity(value, minimum_order_quantity_code):
    """
    Validate row 099 Minimum Order Maximum Quantity.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    minimum_order_quantity_code = str(minimum_order_quantity_code or "").strip().upper()
    if minimum_order_quantity_code == "Y" and not text:
        return "Minimum Order Maximum Quantity is required when Minimum Order Quantity Code is Y"
    if not text:
        return ""
    if not text.isdigit():
        return "Minimum Order Maximum Quantity must be a whole number"
    if len(text) > 10:
        return "Minimum Order Maximum Quantity cannot exceed 10 digits"
    try:
        amount = int(text)
    except ValueError:
        return "Minimum Order Maximum Quantity must be a whole number"
    if amount < 1 or amount > 9999999999:
        return "Minimum Order Maximum Quantity must be between 1 and 9999999999"
    return ""


def apply_row_100_immediate_shipment_available_rule(values):
    """Set row 100 to N when Solicitation Type Indicator (row 002) is I."""
    try:
        if len(values) >= 100:
            solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
            if solicitation_type == "I":
                values[99] = "N"
    except Exception:
        pass
    return values


def validate_row_100_immediate_shipment_available(value, solicitation_type):
    """
    Validate row 100 Immediate Shipment Available.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip().upper()
    solicitation_type = str(solicitation_type or "").strip().upper()
    if solicitation_type == "I":
        if text != "N":
            return "Immediate Shipment Available must be N when Solicitation Type is I"
        return ""
    if solicitation_type in {"", "F", "P"} and not text:
        return "Immediate Shipment Available is required when Solicitation Type is blank, F, or P"
    if text and text not in {"Y", "N"}:
        return "Immediate Shipment Available must be Y or N"
    return ""


def validate_row_101_immediate_shipment_quantity(value, immediate_shipment_available):
    """
    Validate row 101 Immediate Shipment Quantity.
    Returns an error message string, or an empty string when valid.
    """
    text = str(value or "").strip()
    immediate_shipment_available = str(immediate_shipment_available or "").strip().upper()
    if immediate_shipment_available == "N":
        return "Immediate Shipment Quantity must be blank when Immediate Shipment Available is N" if text else ""
    if immediate_shipment_available == "Y" and not text:
        return "Immediate Shipment Quantity is required when Immediate Shipment Available is Y"
    if not text:
        return ""
    if not text.isdigit():
        return "Immediate Shipment Quantity must be a whole number"
    if len(text) > 10:
        return "Immediate Shipment Quantity cannot exceed 10 digits"
    try:
        amount = int(text)
    except ValueError:
        return "Immediate Shipment Quantity must be a whole number"
    if amount < 0 or amount > 9999999999:
        return "Immediate Shipment Quantity must be between 0 and 9999999999"
    return ""


def apply_rows_101_116_conditional_rules(values):
    """Apply DLA blanking/default rules for rows 101 and 103-116."""
    try:
        immediate_shipment_available = str(values[99]).strip().upper() if len(values) >= 100 else ""
        if len(values) >= 101 and immediate_shipment_available != "Y":
            values[100] = ""
    except Exception:
        pass

    try:
        manufacturer_dealer = str(values[101]).strip().upper() if len(values) >= 102 else ""
        if manufacturer_dealer in {"MM", "QM"}:
            if len(values) >= 103:
                values[102] = ""
            if len(values) >= 104:
                values[103] = ""
    except Exception:
        pass

    try:
        item_description = str(values[104]).strip().upper() if len(values) >= 105 else ""
        part_number_code = str(values[105]).strip().upper() if len(values) >= 106 else ""
        supplies_offered = str(values[109]).strip().upper() if len(values) >= 110 else ""

        if item_description not in {"P", "B", "N"}:
            for position in range(106, 110):
                if len(values) >= position:
                    values[position - 1] = ""
        elif part_number_code == "2" and len(values) >= 24:
            values[23] = "AB"

        if item_description in {"P", "B", "N"} and part_number_code == "1":
            if len(values) >= 109:
                values[108] = ""

        if item_description not in {"D", "B", "Q"}:
            for position in (110, 111):
                if len(values) >= position:
                    values[position - 1] = ""
        elif supplies_offered == "1" and len(values) >= 111:
            values[110] = ""

        if item_description != "Q":
            for position in range(112, 117):
                if len(values) >= position:
                    values[position - 1] = ""
    except Exception:
        pass
    return values


def validate_rows_101_116_conditional(values):
    """
    Validate rows 101 and 103-116.
    Returns a list of (position, message) tuples.
    """
    errors = []
    try:
        def value_at(position):
            return str(values[position - 1]).strip() if len(values) >= position else ""

        immediate_shipment_available = value_at(100).upper()
        row101_error = validate_row_101_immediate_shipment_quantity(value_at(101), immediate_shipment_available)
        if row101_error:
            errors.append((101, row101_error))

        manufacturer_dealer = value_at(102).upper()
        source_cage = value_at(103)
        source_name_address = value_at(104)
        if manufacturer_dealer in {"MM", "QM"}:
            if source_cage:
                errors.append((103, "must be blank when Manufacturer/Dealer is MM or QM"))
            if source_name_address:
                errors.append((104, "must be blank when Manufacturer/Dealer is MM or QM"))
        elif manufacturer_dealer in {"DD", "QD"}:
            if not source_cage and not source_name_address:
                errors.append((103, "is required when Manufacturer/Dealer is DD or QD and row 104 is blank"))
                errors.append((104, "is required when Manufacturer/Dealer is DD or QD and row 103 is blank"))
        if source_cage and len(source_cage) > 5:
            errors.append((103, "cannot exceed 5 characters"))
        if source_name_address and len(source_name_address) > 255:
            errors.append((104, "cannot exceed 255 characters"))

        item_description = value_at(105).upper()
        part_number_code = value_at(106).upper()
        part_cage = value_at(107)
        part_number = value_at(108)
        part_remarks = value_at(109)

        if item_description not in {"P", "B", "N"}:
            for position in range(106, 110):
                if value_at(position):
                    errors.append((position, "must be blank when Item Description Indicator is not P, B, or N"))
        else:
            if not part_number_code:
                errors.append((106, "is required when Item Description Indicator is P, B, or N"))
            else:
                valid_part_codes = {"1", "2"} if item_description == "B" else {"1", "2", "3", "4", "5", "6", "7", "8", "9", "A"}
                if part_number_code not in valid_part_codes:
                    errors.append((106, "has an invalid code for the Item Description Indicator"))
            if not part_cage:
                errors.append((107, "is required when Item Description Indicator is P, B, or N"))
            if not part_number:
                errors.append((108, "is required when Item Description Indicator is P, B, or N"))
            if part_number_code == "1" and part_remarks:
                errors.append((109, "must be blank when Part Number Offered Code is 1"))
            if part_number_code == "2":
                bid_type = value_at(24).upper()
                if bid_type != "AB":
                    errors.append((24, "must be AB when Part Number Offered Code is 2"))
        if part_cage and len(part_cage) > 5:
            errors.append((107, "cannot exceed 5 characters"))
        if part_number and len(part_number) > 40:
            errors.append((108, "cannot exceed 40 characters"))
        if part_remarks and len(part_remarks) > 255:
            errors.append((109, "cannot exceed 255 characters"))

        supplies_offered = value_at(110).upper()
        supplies_remarks = value_at(111)
        if item_description not in {"D", "B", "Q"}:
            if supplies_offered:
                errors.append((110, "must be blank when Item Description Indicator is not D, B, or Q"))
            if supplies_remarks:
                errors.append((111, "must be blank when Item Description Indicator is not D, B, or Q"))
        else:
            if not supplies_offered:
                errors.append((110, "is required when Item Description Indicator is D, B, or Q"))
            elif supplies_offered not in {"1", "2", "3", "4"}:
                errors.append((110, "must be 1, 2, 3, or 4"))
            if supplies_offered == "1" and supplies_remarks:
                errors.append((111, "must be blank when Supplies Offered is 1"))
        if supplies_remarks and len(supplies_remarks) > 255:
            errors.append((111, "cannot exceed 255 characters"))

        qualification_fields = (
            (112, "Qualification Requirements MFG CAGE", 5, True),
            (113, "Qualification Requirements Source CAGE", 5, False),
            (114, "Qualification Requirements Item Name", 50, False),
            (115, "Qualification Requirements Service Identification", 50, False),
            (116, "Qualification Requirements Test Number", 50, False),
        )
        if item_description != "Q":
            for position, _label, _max_length, _required in qualification_fields:
                if value_at(position):
                    errors.append((position, "must be blank when Item Description Indicator is not Q"))
        else:
            for position, label, max_length, required in qualification_fields:
                text = value_at(position)
                if required and not text:
                    errors.append((position, f"{label} is required when Item Description Indicator is Q"))
                if text and len(text) > max_length:
                    errors.append((position, f"cannot exceed {max_length} characters"))
    except Exception:
        pass
    return errors


def apply_rows_118_121_quality_labor_remarks_rules(values):
    """Apply DLA blanking/default rules for rows 118-121."""
    try:
        higher_level_indicator = str(values[116]).strip().upper() if len(values) >= 117 else ""
        higher_level_code = str(values[117]).strip().upper() if len(values) >= 118 else ""

        if higher_level_indicator == "N":
            if len(values) >= 118:
                values[117] = ""
            if len(values) >= 119:
                values[118] = ""
        elif higher_level_indicator and higher_level_code != "2":
            if len(values) >= 119:
                values[118] = ""

        if higher_level_indicator in {"6", "7", "8"} and higher_level_code == "1" and len(values) >= 24:
            bid_type = str(values[23]).strip().upper()
            if bid_type not in {"BW", "AB"}:
                values[23] = "BW"
    except Exception:
        pass

    try:
        child_labor_code = str(values[119]).strip().upper() if len(values) >= 120 else ""
        if len(values) >= 120 and not child_labor_code:
            values[119] = "N"
            child_labor_code = "N"
        if child_labor_code == "Y" and len(values) >= 24:
            bid_type = str(values[23]).strip().upper()
            if bid_type not in {"BW", "AB"}:
                values[23] = "BW"
    except Exception:
        pass

    try:
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        bid_type = str(values[23]).strip().upper() if len(values) >= 24 else ""
        quote_remarks = str(values[120]).strip() if len(values) >= 121 else ""

        if solicitation_type in {"F", "P"} and bid_type == "BI":
            if len(values) >= 121:
                values[120] = ""
        elif quote_remarks and len(values) >= 24 and bid_type not in {"BW", "AB"}:
            values[23] = "BW"
    except Exception:
        pass

    return values


def validate_rows_118_121_quality_labor_remarks(values):
    """
    Validate rows 118-121.
    Returns a list of (position, message) tuples.
    """
    errors = []
    try:
        def value_at(position):
            return str(values[position - 1]).strip() if len(values) >= position else ""

        bid_type = value_at(24).upper()
        higher_level_indicator = value_at(117).upper()
        higher_level_code = value_at(118).upper()
        higher_level_remarks = value_at(119)

        valid_quality_codes = {
            "8": {"8", "2", "1"},
            "7": {"8", "7", "2", "1"},
            "6": {"8", "7", "6", "2", "1"},
        }

        if higher_level_indicator == "N":
            if higher_level_code:
                errors.append((118, "must be blank when Higher-Level Quality Indicator is N"))
            if higher_level_remarks:
                errors.append((119, "must be blank when Higher-Level Quality Indicator is N"))
        elif higher_level_indicator in valid_quality_codes:
            if not higher_level_code:
                errors.append((118, "is required when Higher-Level Quality Indicator is not N"))
            elif higher_level_code not in valid_quality_codes[higher_level_indicator]:
                errors.append((118, "has an invalid code for the Higher-Level Quality Indicator"))
            if higher_level_code == "1" and bid_type not in {"BW", "AB"}:
                errors.append((24, "must be BW or AB when Higher-Level Quality Code is 1"))
            if higher_level_code == "2":
                if not higher_level_remarks:
                    errors.append((119, "is required when Higher-Level Quality Code is 2"))
            elif higher_level_remarks:
                errors.append((119, "must be blank unless Higher-Level Quality Code is 2"))
        elif higher_level_indicator:
            errors.append((117, "must be N, 6, 7, or 8"))

        if higher_level_remarks and len(higher_level_remarks) > 255:
            errors.append((119, "cannot exceed 255 characters"))

        child_labor_code = value_at(120).upper()
        if not child_labor_code:
            errors.append((120, "is required"))
        elif child_labor_code not in {"N", "U", "Y"}:
            errors.append((120, "must be N, U, or Y"))
        elif child_labor_code == "Y" and bid_type not in {"BW", "AB"}:
            errors.append((24, "must be BW or AB when Child Labor Certification Code is Y"))

        quote_remarks = value_at(121)
        solicitation_type = value_at(2).upper()
        if quote_remarks and len(quote_remarks) > 255:
            errors.append((121, "cannot exceed 255 characters"))
        if quote_remarks and bid_type not in {"BW", "AB"}:
            errors.append((24, "must be BW or AB when Quote Remarks are entered"))
        if solicitation_type in {"F", "P"} and bid_type == "BI" and quote_remarks:
            errors.append((121, "must be blank when Solicitation Type is F or P and Bid Type Code is BI"))
    except Exception:
        pass
    return errors


PRICE_BREAK_RANGES = (
    (78, 79, 80),
    (81, 82, 83),
    (84, 85, 86),
    (87, 88, 89),
    (90, 91, 92),
    (93, 94, 95),
)


def apply_rows_78_95_price_breaks_rule(values):
    """Blank rows 078-095 when Solicitation Type Indicator (row 002) is I."""
    try:
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        if solicitation_type == "I":
            for position in range(78, 96):
                if len(values) >= position:
                    values[position - 1] = ""
    except Exception:
        pass
    return values


def _validate_price_break_quantity(value):
    text = str(value or "").strip()
    if not text:
        return ""
    if not text.isdigit():
        return "must be a whole number"
    if len(text) > 10:
        return "cannot exceed 10 digits"
    try:
        amount = int(text)
    except ValueError:
        return "must be a whole number"
    if amount < 0 or amount > 9999999999:
        return "must be between 0 and 9999999999"
    return ""


def _validate_price_break_unit_price(value):
    text = str(value or "").strip().replace(",", "")
    if not text:
        return ""
    if len(text) > 13:
        return "cannot exceed 13 characters"
    return validate_row_50_unit_price(text).replace("Unit Price", "Price Break Unit Price")


def validate_rows_78_95_price_breaks(values):
    """
    Validate rows 078-095 Quantity Price Breaks.
    Returns a list of (position, message) tuples.
    """
    errors = []
    try:
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        if solicitation_type == "I":
            for position in range(78, 96):
                value = str(values[position - 1]).strip() if len(values) >= position else ""
                if value:
                    errors.append((position, "must be blank when Solicitation Type Indicator is I"))
            return errors

        previous_upper = None
        for range_index, (lower_pos, upper_pos, price_pos) in enumerate(PRICE_BREAK_RANGES, 1):
            lower = str(values[lower_pos - 1]).strip() if len(values) >= lower_pos else ""
            upper = str(values[upper_pos - 1]).strip() if len(values) >= upper_pos else ""
            price = str(values[price_pos - 1]).strip() if len(values) >= price_pos else ""

            if solicitation_type in {"F", "P"}:
                if not lower:
                    errors.append((lower_pos, "is required when Solicitation Type Indicator is F or P"))
                if not upper:
                    errors.append((upper_pos, "is required when Solicitation Type Indicator is F or P"))
                if not price:
                    errors.append((price_pos, "is required when Solicitation Type Indicator is F or P"))

            lower_error = _validate_price_break_quantity(lower)
            if lower_error:
                errors.append((lower_pos, lower_error))
            upper_error = _validate_price_break_quantity(upper)
            if upper_error:
                errors.append((upper_pos, upper_error))
            price_error = _validate_price_break_unit_price(price)
            if price_error:
                errors.append((price_pos, price_error))

            lower_num = _to_quantity_decimal(lower)
            upper_num = _to_quantity_decimal(upper)
            if lower_num is not None and upper_num is not None and lower_num > upper_num:
                errors.append((upper_pos, "must be greater than or equal to the lower quantity"))

            if range_index > 1 and previous_upper is not None and lower_num is not None:
                expected_lower = previous_upper + Decimal("1")
                if lower_num != expected_lower:
                    errors.append((lower_pos, "must equal the previous upper quantity plus 1"))

            if upper_num is not None:
                previous_upper = upper_num
    except Exception:
        pass
    return errors


def ensure_export_field_definitions():
    """
    Ensure all 121 ExportFieldDefinition records exist and are up-to-date.
    Uses embedded field definitions from models.py (EXPORT_FIELD_DEFINITIONS).
    This eliminates the dependency on management commands.
    """
    # ensure_all_fields_exist() now returns a boolean (True if count == 121)
    success = ExportFieldDefinition.ensure_all_fields_exist()
    
    if not success:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(f"Failed to ensure all 121 ExportFieldDefinition records exist. Current count: {ExportFieldDefinition.objects.count()}")
    
    return success


def get_export_directory():
    """
    Get the directory where export files should be stored.
    Creates the directory if it doesn't exist.

    Returns:
        str: Absolute path to export directory
    """
    # Use MEDIA_ROOT/exports or create exports/ in project root
    if hasattr(settings, 'MEDIA_ROOT') and settings.MEDIA_ROOT:
        export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
    else:
        # Fallback to project root/exports
        export_dir = os.path.join(settings.BASE_DIR, 'exports')

    # Create directory if it doesn't exist
    os.makedirs(export_dir, exist_ok=True)

    return export_dir


def generate_export_filename(user, prefix='dla_export'):
    """
    Generate a unique filename for export.

    Args:
        user: User object
        prefix: Filename prefix (default: 'dla_export')

    Returns:
        str: Filename with timestamp and username
    """
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    username = user.username.replace(' ', '_')
    return f"{prefix}_{username}_{timestamp}.txt"


def generate_export_line(user, solicitation):
    """
    Generate a single export line for a solicitation with 121 fields.

    Args:
        user: User object for configuration lookup
        solicitation: Solicitation object to export

    Returns:
        String with comma-separated values (121 fields)
    """
    # Get user's export configurations for all 121 fields
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    # If user has no configurations, create default ones
    if not configurations.exists():
        create_default_configurations(user)
        configurations = UserExportConfiguration.objects.filter(
            user=user
        ).select_related('field_definition').order_by('field_definition__position')

    # Generate values for all 121 positions
    values = []
    for config in configurations:
        value = config.get_value(solicitation)
        values.append(value)

    return serialize_export_values(values)


def generate_export_file(user, solicitations):
    """
    Generate complete export file for multiple solicitations.

    Args:
        user: User object for configuration lookup
        solicitations: QuerySet or list of Solicitation objects

    Returns:
        String containing the complete export file content
    """
    lines = []
    for solicitation in solicitations:
        line = generate_export_line(user, solicitation)
        lines.append(line)

    content = '\r\n'.join(line for line in lines if line.strip())
    if content:
        content += '\r\n'
    structure_errors = validate_export_file_structure(content)
    if structure_errors:
        raise ValueError("; ".join(structure_errors))
    return content


def create_default_configurations(user):
    """
    Create default export configurations for a user.
    Maps common Solicitation and RfqReply fields to export positions.
    Ensures all 121 fields are configured.
    """
    # Ensure ExportFieldDefinition records exist and are up-to-date FIRST
    from solicitations.models import ExportFieldDefinition
    import logging
    logger = logging.getLogger(__name__)

    if ExportFieldDefinition.objects.count() != 121:
        logger.warning("ExportFieldDefinition records are incomplete. Attempting to ensure all fields exist.")
        ExportFieldDefinition.ensure_all_fields_exist()
        if ExportFieldDefinition.objects.count() != 121:
            logger.error("Failed to ensure all 121 ExportFieldDefinition records exist. Cannot create user configurations.")
            return False # Indicate failure
    else:
        # Even if count is 121, ensure records are up-to-date with correct field types
        logger.info("Updating ExportFieldDefinition records to ensure correct field types before creating user configurations.")
        ExportFieldDefinition.ensure_all_fields_exist()
    
    # Get all field definitions - should be exactly 121
    field_definitions = ExportFieldDefinition.objects.all().order_by('position')
    
    if field_definitions.count() != 121:
        logger.error(
            f"Failed to create 121 ExportFieldDefinition records. "
            f"Found {field_definitions.count()} instead. "
            f"User {user.username} cannot configure export fields."
        )
        return False

    # Get existing configurations for this user
    existing_configs = UserExportConfiguration.objects.filter(user=user)
    existing_field_ids = set(existing_configs.values_list('field_definition_id', flat=True))

    # Default field mappings for Solicitation (position -> source_field)
    solicitation_mappings = {
        1: 'solicitation',  # Solicitation Number
        3: 'is_set_aside',  # Small Business Set Aside Indicator (auto: True -> "A", False -> "N")
        5: 'return_by_date',  # Return By Date
        6: 'cage',  # Quoter CAGE Code
        7: 'cage',  # Quote for CAGE Code
        32: 'deliver_fob',  # FOB Point (auto: destination -> "D", origin -> "O")
        36: 'inspection_point',  # Inspection Point Code (auto: destination -> "D", origin -> "O")
        44: '',  # Solicitation Line Number (to be filled per line)
        46: 'pr',  # Purchase Request Number
        47: 'NSN',  # National Stock Number / Part Number
        48: 'unit',  # Unit of Issue
        49: 'quantity',  # Quantity
        103: 'cage',  # Actual Manufacturing/Production Source CAGE code (OEM CAGE from solicitation)
    }
    
    # Default field mappings for RfqReply (position -> source_field)
    # These will be used when exporting RFQ replies
    rfq_reply_mappings = {
        1: 'solicitation_number',  # Solicitation Number
        3: 'rfq.solicitation.is_set_aside',  # Small Business Set Aside Indicator (auto: True -> "A", False -> "N")
        5: 'received_date',  # Return By Date (use received_date)
        6: 'user.cage',  # Quoter CAGE Code (from user)
        7: 'user.cage',  # Quote for CAGE Code (from user)
        32: 'rfq.solicitation.deliver_fob',  # FOB Point (auto: destination -> "D", origin -> "O")
        36: 'rfq.solicitation.inspection_point',  # Inspection Point Code (auto: destination -> "D", origin -> "O")
        44: 'rfq.solicitation.solicitation_line_number',  # Solicitation Line Number
        46: 'rfq.solicitation.purchase_request_number',  # Purchase Request Number
        47: 'nsn',  # National Stock Number / Part Number
        48: 'unit',  # Unit of Issue
        49: 'quantity',  # Quantity
        50: 'unit_price',  # Unit Price
        51: '',  # Delivery Days
        103: 'rfq.solicitation.cage',  # Actual Manufacturing/Production Source CAGE code (from solicitation's OEM CAGE)
    }

    # Create configurations only for missing fields
    configurations = []
    for field_def in field_definitions:
        # Skip if configuration already exists
        if field_def.id in existing_field_ids:
            continue
            
        # Use RfqReply mapping if available, otherwise Solicitation mapping
        source_field = rfq_reply_mappings.get(
            field_def.position, 
            solicitation_mappings.get(field_def.position, '')
        )

        config = UserExportConfiguration(
            user=user,
            field_definition=field_def,
            is_enabled=True,
            source_field=source_field,
            custom_value=''
        )
        configurations.append(config)

    # Bulk create missing configurations
    if configurations:
        UserExportConfiguration.objects.bulk_create(
            configurations, ignore_conflicts=True)
    
    # Verify we now have exactly 121 configurations
    final_count = UserExportConfiguration.objects.filter(user=user).count()
    if final_count != 121:
        import logging
        logger = logging.getLogger(__name__)
        logger.error(
            f"Failed to create 121 UserExportConfiguration records for user {user.username}. "
            f"Found {final_count} instead. Missing configurations for {121 - final_count} fields."
        )
        return False
    
    return True


def export_solicitations_to_file(user, solicitations, file_path=None, filename=None):
    """
    Export solicitations to a text file.

    Args:
        user: User object for configuration lookup
        solicitations: QuerySet or list of Solicitation objects
        file_path: Full path where to save the export file (optional)
        filename: Just the filename (will be saved in exports directory) (optional)

    Returns:
        dict: {
            'count': Number of solicitations exported,
            'file_path': Full path to the exported file,
            'filename': Name of the exported file
        }
    """
    content = generate_export_file(user, solicitations)

    # Determine the file path
    if file_path:
        # Use provided full path
        full_path = file_path
    elif filename:
        # Use provided filename in exports directory
        export_dir = get_export_directory()
        full_path = os.path.join(export_dir, filename)
    else:
        # Generate automatic filename in exports directory
        export_dir = get_export_directory()
        filename = generate_export_filename(user)
        full_path = os.path.join(export_dir, filename)

    # Ensure directory exists
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the file
    with open(full_path, 'w', encoding='utf-8', newline='') as f:
        f.write(content)

    return {
        'count': len(solicitations),
        'file_path': full_path,
        'filename': os.path.basename(full_path)
    }


def build_rfq_reply_values(user, rfq_reply):
    """
    Build the 121-position value list for a single RFQ reply,
    applying all DLA business rules but not converting to CSV.
    """
    import sys
    sys.stderr.write(f"\n[BUILD_RFQ_REPLY_VALUES] FUNCTION CALLED for RFQ reply {rfq_reply.id}, user {user.username}\n")
    sys.stderr.flush()
    
    # CRITICAL: Ensure ExportFieldDefinition records exist and are up-to-date FIRST
    # This ensures field definitions have correct field types before creating configurations
    from .models import ExportFieldDefinition
    if ExportFieldDefinition.objects.count() != 121:
        ExportFieldDefinition.ensure_all_fields_exist()
    else:
        # Even if count is 121, ensure records are up-to-date with correct field types
        ExportFieldDefinition.ensure_all_fields_exist()
    
    # Get user's export configurations for all 121 fields
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    # If user has no configurations OR doesn't have exactly 121 configurations, create/update default ones
    config_count = configurations.count()
    if config_count == 0 or config_count != 121:
        import logging
        logger = logging.getLogger(__name__)
        if config_count == 0:
            logger.info(f"[BUILD_RFQ_REPLY_VALUES] No configurations found for user {user.username}, creating defaults")
        else:
            logger.warning(f"[BUILD_RFQ_REPLY_VALUES] User {user.username} has {config_count} configurations instead of 121, recreating defaults")
        create_default_configurations(user)
        configurations = UserExportConfiguration.objects.filter(
            user=user
        ).select_related('field_definition').order_by('field_definition__position')
        
        # Verify we now have 121 configurations
        if configurations.count() != 121:
            logger.error(f"[BUILD_RFQ_REPLY_VALUES] Failed to create 121 configurations for user {user.username}. Found {configurations.count()} instead.")
            raise ValueError(f"Export configuration incomplete: Expected 121 fields, found {configurations.count()}")

    # Generate raw values for all 121 positions using the user's configuration
    import logging
    import sys
    logger = logging.getLogger(__name__)
    values = []
    empty_count = 0
    empty_fields = []
    
    # Print to console (will show in terminal)
    sys.stderr.write(f"\n[BUILD_RFQ_REPLY_VALUES] Building values for RFQ reply {rfq_reply.id}, user {user.username}\n")
    sys.stderr.write(f"[BUILD_RFQ_REPLY_VALUES] Total configurations: {configurations.count()}\n")
    sys.stderr.flush()
    logger.info(f"[BUILD_RFQ_REPLY_VALUES] Building values for RFQ reply {rfq_reply.id}, user {user.username}")
    logger.info(f"[BUILD_RFQ_REPLY_VALUES] Total configurations: {configurations.count()}")
    
    for config in configurations:
        value = config.get_value(rfq_reply)
        values.append(value)
        if not value or (isinstance(value, str) and not value.strip()):
            empty_count += 1
            empty_fields.append({
                'position': config.field_definition.position,
                'column_name': config.field_definition.column_name,
                'custom_value': config.custom_value,
                'source_field': config.source_field,
                'is_enabled': config.is_enabled
            })

    # ------------------------------------------------------------------
    # Fix for Solicitation Number (Position 1) for RFQ replies
    # ------------------------------------------------------------------
    # Even if the user's export configuration for position 1 is misconfigured
    # or the mapped source field is empty, we want the solicitation number in
    # the preview/export to ALWAYS come from the database using the same
    # priority as the RFQ reply detail page:
    #   1) rfq_reply.solicitation_number
    #   2) rfq_reply.rfq.solicitation.solicitation (linked solicitation)
    #   3) rfq_reply.find_matching_solicitation().solicitation (best match)
    #
    # DLA position indexes are 1-based, list indexes are 0-based.
    try:
        if len(values) >= 1:
            best_solicitation_number = None

            # Priority 1: value stored directly on RfqReply
            if rfq_reply.solicitation_number:
                best_solicitation_number = str(rfq_reply.solicitation_number).strip()

            # Priority 2: linked solicitation through RFQ
            if (not best_solicitation_number and
                getattr(rfq_reply, "rfq", None) and
                getattr(rfq_reply.rfq, "solicitation", None) and
                getattr(rfq_reply.rfq.solicitation, "solicitation", None)):
                best_solicitation_number = str(rfq_reply.rfq.solicitation.solicitation).strip()

            # Priority 3: try to find a matching solicitation using model helper
            if not best_solicitation_number:
                try:
                    matching = rfq_reply.find_matching_solicitation()
                    if matching and getattr(matching, "solicitation", None):
                        best_solicitation_number = str(matching.solicitation).strip()
                except Exception:
                    # Never break export because of matching failures
                    pass

            if best_solicitation_number:
                # Preserve previous behavior: remove dashes from solicitation number
                # so formats like "SPE7L1-26-T-6061" become "SPE7L126T6061".
                cleaned = best_solicitation_number.replace('-', '').strip()
                values[0] = cleaned
    except Exception:
        # Fail-safe: if anything goes wrong here, just keep the original values
        pass
    
    # Print to console (will show in terminal)
    sys.stderr.write(f"[BUILD_RFQ_REPLY_VALUES] Empty values: {empty_count}/121 fields\n")
    sys.stderr.flush()
    logger.info(f"[BUILD_RFQ_REPLY_VALUES] Empty values: {empty_count}/121 fields")
    
    if empty_count > 0:
        # Print first 10 empty fields with details
        sys.stderr.write(f"[BUILD_RFQ_REPLY_VALUES] First 10 empty fields:\n")
        logger.info(f"[BUILD_RFQ_REPLY_VALUES] First 10 empty fields:")
        for field in empty_fields[:10]:
            msg = (
                f"  Position {field['position']} ({field['column_name']}): "
                f"custom_value={repr(field['custom_value'])}, "
                f"source_field={repr(field['source_field'])}, "
                f"is_enabled={field['is_enabled']}"
            )
            sys.stderr.write(msg + "\n")
            logger.info(msg)
        sys.stderr.flush()
    
    if empty_count > 50:
        warning_msg = (
            f"[BUILD_RFQ_REPLY_VALUES] WARNING: Many empty values ({empty_count}/121) for RFQ reply {rfq_reply.id}. "
            f"This may indicate missing source_field mappings or missing data."
        )
        sys.stderr.write(warning_msg + "\n")
        sys.stderr.flush()
        logger.warning(warning_msg)

    # ------------------------------------------------------------------
    # DLA business rules / conditional field logic
    # ------------------------------------------------------------------
    # Item 18 - Joint Venture (conditional):
    # - If Set Aside (3) == "N", must be blank.
    # - If Set Aside (3) != "N" and Small Business Code (13) is not B or M, must be blank.
    # - If Set Aside (3) != "N" and Small Business Code (13) is B or M, only JV or JN is allowed.
    try:
        if len(values) >= 18:
            set_aside = str(values[2]).strip().upper()      # position 3 (0-based index 2)
            small_biz  = str(values[12]).strip().upper()    # position 13 (0-based index 12)
            joint_venture = str(values[17]).strip().upper()
            if set_aside == "N" or small_biz not in ("B", "M"):
                values[17] = ""                             # position 18 (0-based index 17)
            else:
                values[17] = joint_venture if joint_venture in ("JV", "JN") else ""
    except Exception:
        pass

    # Item 19 - Joint Venture Remarks depends on Item 18 - Joint Venture.
    # - If position 18 != "JV", position 19 must be blank.
    # - If position 18 == "JV", position 19 may be populated by the user/config.
    # Positions are 1-based in the DLA spec, convert to 0-based indexes here.
    try:
        if len(values) >= 19:
            joint_venture_val = str(values[17]).strip().upper()  # position 18
            if joint_venture_val != "JV":
                # Force Joint Venture Remarks (position 19) to blank
                values[18] = ""
    except Exception:
        # Fail-safe: never break export because of conditional logic
        pass

    # Item 27 - Days Quote Valid depends on Item 2 - Solicitation Type Indicator
    # and Item 24 - Bid Type Code:
    # - If Solicitation Type Indicator (2) == "I" and Days Quote Valid (27) < 90,
    #   then Bid Type Code (24) must be "BW" (Bid With Exception) or "AB" (Alternate Bid).
    try:
        if len(values) >= 27:
            solicitation_type = str(values[1]).strip().upper()  # position 2
            if solicitation_type == "I":
                days_raw = str(values[26]).strip()  # position 27
                if days_raw:
                    try:
                        days_val = int(days_raw)
                    except ValueError:
                        days_val = None

                    if days_val is not None and days_val < 90 and len(values) >= 24:
                        bid_type = str(values[23]).strip().upper()  # position 24
                        if bid_type not in ("BW", "AB"):
                            # Default to "BW" to satisfy DLA rule when days < 90
                            values[23] = "BW"
    except Exception:
        # Fail-safe: never break export because of conditional logic
        pass

    # Item 28 - Meets Packaging Requirement (Accept Packaging)
    # If Item 28 == "N", then Bid Type Code (24) must be "BW" or "AB".
    try:
        if len(values) >= 28:
            packaging_resp = str(values[27]).strip().upper()  # position 28
            if packaging_resp == "N" and len(values) >= 24:
                bid_type = str(values[23]).strip().upper()  # position 24
                if bid_type not in ("BW", "AB"):
                    values[23] = "BW"
    except Exception:
        # Fail-safe: never break export because of conditional logic
        pass

    # Row 23: normalize legacy Y/N Alternate Disputes Resolution values to DIBBS A/B codes.
    try:
        apply_row_23_alternate_disputes_resolution_rule(values)
    except Exception:
        pass

    # Row 49: Quantity effects on Bid Type Code (24).
    try:
        requirement_quantity = get_rfq_requirement_quantity(rfq_reply)
        apply_row_49_quantity_rule(values, requirement_quantity)
    except Exception:
        pass
    try:
        apply_row_51_delivery_days_rule(values)
    except Exception:
        pass
    try:
        apply_row_56_no_do_minimum_rule(values)
    except Exception:
        pass
    try:
        apply_row_58_hubzone_waiver_rule(values)
    except Exception:
        pass
    try:
        apply_row_100_immediate_shipment_available_rule(values)
    except Exception:
        pass
    try:
        apply_rows_101_116_conditional_rules(values)
    except Exception:
        pass
    try:
        apply_rows_118_121_quality_labor_remarks_rules(values)
    except Exception:
        pass
    try:
        apply_row_59_immediate_shipment_price_rule(values)
    except Exception:
        pass
    try:
        apply_row_60_immediate_shipment_delivery_rule(values)
    except Exception:
        pass
    try:
        apply_row_63_source_supply_cage_rule(values)
    except Exception:
        pass
    try:
        apply_row_64_first_article_waiver_rule(values)
    except Exception:
        pass
    try:
        apply_row_67_material_requirements_rule(values)
    except Exception:
        pass
    try:
        apply_row_71_country_origin_rule(values)
    except Exception:
        pass
    try:
        apply_row_72_country_code_rule(values)
    except Exception:
        pass
    try:
        apply_row_73_duty_free_entry_rule(values)
    except Exception:
        pass
    try:
        apply_row_74_foreign_supplies_rule(values)
    except Exception:
        pass
    try:
        apply_row_75_duty_paid_rule(values)
    except Exception:
        pass
    try:
        apply_row_76_duty_paid_amount_rule(values)
    except Exception:
        pass
    try:
        apply_rows_78_95_price_breaks_rule(values)
    except Exception:
        pass

    # Items 29-31 - BOA/FSS/BPA logic
    # Item 29 - BOA/FSS/BPA code (NAP, FSS, BOA, BPA)
    # Item 30 - BOA/FSS/BPA Contract Number
    # Item 31 - BOA/FSS/BPA Contract Expiration Date
    #
    # If BOA/FSS/BPA (29) is "BOA", "FSS" or "BPA",
    #   Contract # (30) and Expiration date (31) must be completed (we do NOT auto-fill here).
    # If BOA/FSS/BPA (29) is "NAP",
    #   Contract # (30) and Expiration date (31) must be blank.
    try:
        if len(values) >= 31:
            boa_code = str(values[28]).strip().upper()  # position 29
            if boa_code == "NAP":
                # When not applicable, ensure related fields are blank
                values[29] = ""  # position 30
                values[30] = ""  # position 31
            # For BOA/FSS/BPA we rely on upstream data/config to provide 30 and 31;
            # exporter does not invent contract numbers or dates.
    except Exception:
        # Fail-safe: never break export because of conditional logic
        pass

    # Row 33: FOB City must be blank when FOB Point (32) is Destination.
    try:
        if len(values) >= 33:
            fob_point = str(values[31]).strip().upper()
            if fob_point == "D":
                values[32] = ""
    except Exception:
        pass

    # Row 34: FOB State/Province must be blank when FOB Point (32) is Destination
    # or when FOB Country (35) is not US or CA.
    try:
        if len(values) >= 35:
            fob_point = str(values[31]).strip().upper()
            fob_country = str(values[34]).strip().upper()
            if fob_point == "D" or fob_country not in {"US", "CA"}:
                values[33] = ""
    except Exception:
        pass

    # Row 35: FOB Country must be blank when FOB Point (32) is Destination.
    try:
        if len(values) >= 35:
            fob_point = str(values[31]).strip().upper()
            if fob_point == "D":
                values[34] = ""
    except Exception:
        pass

    # Row 36: Inspection Point Code comes from the solicitation inspection_point
    # mapping so Origin/Destination follows the solicitation table.

    # Item 66 - Hazardous Warning Labels must be one of the DLA-defined codes.
    try:
        if len(values) >= 66:
            hazardous_warning_label = str(values[65]).strip()
            values[65] = hazardous_warning_label if hazardous_warning_label in {"1", "2", "3", "4", "5", "6", "7"} else ""
    except Exception:
        pass

    # Item 104 - Actual Manufacturing/Production Source Name and Address
    # must be blank for manufacturers, and is required for dealers when
    # the actual manufacturing source CAGE code is not provided.
    try:
        if len(values) >= 104:
            manufacturer_dealer = str(values[101]).strip().upper() if len(values) >= 102 else ""
            if manufacturer_dealer in {"MM", "QM"}:
                values[103] = ""
    except Exception:
        pass

    # Ensure we have exactly 121 fields
    while len(values) < 121:
        values.append("")

    # Truncate to exactly 121 fields if somehow we have more
    if len(values) > 121:
        values = values[:121]

    return values


def validate_mandatory_fields(user, rfq_reply):
    """
    Validate that all mandatory fields have values for an RFQ reply.
    
    Args:
        user: User object for configuration lookup
        rfq_reply: RfqReply object to validate
        
    Returns:
        tuple: (is_valid: bool, missing_fields: list)
            - is_valid: True if all mandatory fields have values
            - missing_fields: List of dicts with 'position', 'column_name', 'field_name' for missing fields
    """
    # CRITICAL: Ensure ExportFieldDefinition records exist and are up-to-date FIRST
    # This ensures mandatory fields are correctly identified
    if ExportFieldDefinition.objects.count() != 121:
        ExportFieldDefinition.ensure_all_fields_exist()
    else:
        # Even if count is 121, ensure records are up-to-date with correct field types
        ExportFieldDefinition.ensure_all_fields_exist()
    
    # Get all mandatory field definitions
    mandatory_fields = ExportFieldDefinition.objects.filter(
        field_type='mandatory'
    ).order_by('position')
    
    # Debug: Check if mandatory fields exist
    import logging
    logger = logging.getLogger(__name__)
    mandatory_count = mandatory_fields.count()
    logger.info(f"[VALIDATE_MANDATORY] Found {mandatory_count} mandatory fields")
    
    if mandatory_count == 0:
        # No mandatory fields defined - skip validation
        logger.warning("[VALIDATE_MANDATORY] No mandatory fields found in database. Validation skipped.")
        return True, []
    
    # Get user's export configurations
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')
    
    # If user has no configurations, create default ones
    if not configurations.exists():
        create_default_configurations(user)
        configurations = UserExportConfiguration.objects.filter(
            user=user
        ).select_related('field_definition').order_by('field_definition__position')
    
    # Create a dict for quick lookup: position -> config
    config_dict = {config.field_definition.position: config for config in configurations}
    
    # Get the values for this RFQ reply
    values = get_effective_rfq_reply_values(user, rfq_reply)
    
    missing_fields = []

    # Row 23: Alternate Disputes Resolution must use DIBBS A/B codes.
    try:
        row_23_error = validate_row_23_alternate_disputes_resolution(
            values[22] if len(values) >= 23 else ""
        )
        if row_23_error:
            field_def = ExportFieldDefinition.objects.filter(position=23).first()
            missing_fields.append({
                'position': 23,
                'column_name': f"{field_def.column_name if field_def else 'Alternate Disputes Resolution'}: {row_23_error}",
                'field_name': f"{field_def.column_name if field_def else 'Alternate Disputes Resolution'}: {row_23_error}"
            })
    except Exception:
        pass
    
    # Check each mandatory field
    for field_def in mandatory_fields:
        position = field_def.position
        # Position is 1-based, values list is 0-based
        value_index = position - 1
        
        if value_index < len(values):
            value = values[value_index]
            if position == 72:
                end_product_code = str(values[69]).strip().upper() if len(values) >= 70 else ''
                if end_product_code in {'D', 'NQ', 'O', 'ND', 'US'}:
                    continue
            if position in (30, 31):
                boa_code = str(values[28]).strip().upper() if len(values) >= 29 else ''
                if boa_code == 'NAP':
                    continue
            # Check if value is empty or just whitespace
            if not value or (isinstance(value, str) and not value.strip()):
                # Get the configuration for this field to get the field name
                config = config_dict.get(position)
                field_name = field_def.column_name
                if config and config.source_field:
                    field_name = f"{field_def.column_name} ({config.source_field})"
                
                missing_fields.append({
                    'position': position,
                    'column_name': field_def.column_name,
                    'field_name': field_name
                })

    # Conditional DLA rule for position 104:
    # If Manufacturer/Dealer (102) is DD or QD and Source CAGE (103) is blank,
    # Actual Manufacturing/Production Source Name and Address (104) is required.
    try:
        joint_venture = str(values[17]).strip().upper() if len(values) >= 18 else ""
        joint_venture_remarks = str(values[18]).strip() if len(values) >= 19 else ""
        if joint_venture == "JV" and not joint_venture_remarks:
            field_def = ExportFieldDefinition.objects.filter(position=19).first()
            missing_fields.append({
                'position': 19,
                'column_name': field_def.column_name if field_def else 'Joint Venture Remarks',
                'field_name': field_def.column_name if field_def else 'Joint Venture Remarks'
            })
    except Exception:
        pass

    # Conditional DLA rule for positions 29-31:
    # If BOA/FSS/BPA code (29) is BOA, FSS, or BPA,
    # Contract Number (30) and Contract Expiration Date (31) are required.
    # If BOA/FSS/BPA code (29) is NAP, 30 and 31 are blank and not required.
    try:
        boa_code = str(values[28]).strip().upper() if len(values) >= 29 else ""
        if boa_code in {"BOA", "FSS", "BPA"}:
            for required_position, fallback_name in (
                (30, "BOA/FSS/BPA Contract Number"),
                (31, "BOA/FSS/BPA Contract Expiration Date"),
            ):
                value = str(values[required_position - 1]).strip() if len(values) >= required_position else ""
                already_missing = any(item.get('position') == required_position for item in missing_fields)
                if not value and not already_missing:
                    field_def = ExportFieldDefinition.objects.filter(position=required_position).first()
                    missing_fields.append({
                        'position': required_position,
                        'column_name': field_def.column_name if field_def else fallback_name,
                        'field_name': field_def.column_name if field_def else fallback_name
                    })
    except Exception:
        pass

    # Row 30: BOA/FSS/BPA Contract Number max length is 17.
    try:
        contract_number = str(values[29]).strip() if len(values) >= 30 else ""
        if contract_number and len(contract_number) > 17:
            field_def = ExportFieldDefinition.objects.filter(position=30).first()
            missing_fields.append({
                'position': 30,
                'column_name': f"{field_def.column_name if field_def else 'BOA/FSS/BPA Contract Number'} exceeds 17 characters",
                'field_name': f"{field_def.column_name if field_def else 'BOA/FSS/BPA Contract Number'} exceeds 17 characters"
            })
    except Exception:
        pass

    # Row 31: BOA/FSS/BPA Contract Expiration Date must be MM/DD/YYYY when present.
    try:
        expiration_date = str(values[30]).strip() if len(values) >= 31 else ""
        if expiration_date:
            format_ok = (
                len(expiration_date) == 10 and
                expiration_date[2] == "/" and
                expiration_date[5] == "/" and
                expiration_date[:2].isdigit() and
                expiration_date[3:5].isdigit() and
                expiration_date[6:].isdigit()
            )
            if format_ok:
                try:
                    datetime.strptime(expiration_date, "%m/%d/%Y")
                except ValueError:
                    format_ok = False
            if not format_ok:
                field_def = ExportFieldDefinition.objects.filter(position=31).first()
                missing_fields.append({
                    'position': 31,
                    'column_name': f"{field_def.column_name if field_def else 'BOA/FSS/BPA Contract Expiration Date'} must be MM/DD/YYYY",
                    'field_name': f"{field_def.column_name if field_def else 'BOA/FSS/BPA Contract Expiration Date'} must be MM/DD/YYYY"
                })
    except Exception:
        pass

    # Conditional DLA rule for position 33:
    # If FOB Point (32) is Origin, FOB City (33) is required.
    # If FOB Point (32) is Destination, FOB City (33) is blank and not required.
    try:
        fob_point = str(values[31]).strip().upper() if len(values) >= 32 else ""
        fob_city = str(values[32]).strip() if len(values) >= 33 else ""
        if fob_point == "O" and not fob_city:
            field_def = ExportFieldDefinition.objects.filter(position=33).first()
            missing_fields.append({
                'position': 33,
                'column_name': field_def.column_name if field_def else 'FOB City',
                'field_name': field_def.column_name if field_def else 'FOB City'
            })
    except Exception:
        pass

    # Row 33: FOB City max length is 30.
    try:
        fob_city = str(values[32]).strip() if len(values) >= 33 else ""
        if fob_city and len(fob_city) > 30:
            field_def = ExportFieldDefinition.objects.filter(position=33).first()
            missing_fields.append({
                'position': 33,
                'column_name': f"{field_def.column_name if field_def else 'FOB City'} exceeds 30 characters",
                'field_name': f"{field_def.column_name if field_def else 'FOB City'} exceeds 30 characters"
            })
    except Exception:
        pass

    # Conditional DLA rule for position 34:
    # If FOB Point (32) is Origin and FOB Country (35) is US or CA,
    # FOB State/Province (34) is required and must be a valid code.
    try:
        fob_point = str(values[31]).strip().upper() if len(values) >= 32 else ""
        fob_state = str(values[33]).strip().upper() if len(values) >= 34 else ""
        fob_country = str(values[34]).strip().upper() if len(values) >= 35 else ""
        us_codes = {
            "AK", "AL", "AR", "AS", "AZ", "CA", "CO", "CT", "DC", "DE", "FL", "FM",
            "GA", "GU", "HI", "IA", "ID", "IL", "IN", "KS", "KY", "LA", "MA", "MD",
            "ME", "MH", "MI", "MN", "MO", "MS", "MT", "NC", "ND", "NE", "NH", "NJ",
            "NM", "NV", "NY", "OH", "OK", "OR", "PA", "PR", "PW", "RI", "SC", "SD",
            "TN", "TX", "UT", "VA", "VI", "VT", "WA", "WV", "WI", "WY"
        }
        ca_codes = {"AB", "BC", "MB", "NB", "NF", "NS", "NT", "ON", "PE", "QC", "SK", "YT"}
        if fob_point == "O" and fob_country in {"US", "CA"}:
            field_def = ExportFieldDefinition.objects.filter(position=34).first()
            if not fob_state:
                missing_fields.append({
                    'position': 34,
                    'column_name': field_def.column_name if field_def else 'FOB State/Province',
                    'field_name': field_def.column_name if field_def else 'FOB State/Province'
                })
            elif len(fob_state) > 2:
                missing_fields.append({
                    'position': 34,
                    'column_name': f"{field_def.column_name if field_def else 'FOB State/Province'} exceeds 2 characters",
                    'field_name': f"{field_def.column_name if field_def else 'FOB State/Province'} exceeds 2 characters"
                })
            elif fob_country == "US" and fob_state not in us_codes:
                missing_fields.append({
                    'position': 34,
                    'column_name': f"{field_def.column_name if field_def else 'FOB State/Province'} must be a valid US state or territory code",
                    'field_name': f"{field_def.column_name if field_def else 'FOB State/Province'} must be a valid US state or territory code"
                })
            elif fob_country == "CA" and fob_state not in ca_codes:
                missing_fields.append({
                    'position': 34,
                    'column_name': f"{field_def.column_name if field_def else 'FOB State/Province'} must be a valid Canadian province code",
                    'field_name': f"{field_def.column_name if field_def else 'FOB State/Province'} must be a valid Canadian province code"
                })
    except Exception:
        pass

    # Conditional DLA rule for position 35:
    # If FOB Point (32) is Origin, FOB Country (35) is required and must be
    # one of the DLA country codes.
    try:
        fob_point = str(values[31]).strip().upper() if len(values) >= 32 else ""
        fob_country = str(values[34]).strip().upper() if len(values) >= 35 else ""
        country_codes = {
            "AF", "AL", "DZ", "AS", "AD", "AO", "AI", "AQ", "AG", "AR", "AM", "AW", "AU", "AT", "AZ",
            "BS", "BH", "BD", "BB", "BY", "BE", "BZ", "BJ", "BM", "BT", "BO", "BQ", "BA", "BW", "BV",
            "BR", "IO", "BN", "BG", "BF", "CV", "KH", "CM", "BI", "CA", "KY", "CF", "TD", "CL", "CN",
            "CX", "CC", "CO", "KM", "CG", "CD", "CK", "CR", "CI", "HR", "CU", "CW", "CY", "CZ", "DK",
            "DJ", "DM", "DO", "EC", "EG", "SV", "GQ", "ER", "EE", "SZ", "ET", "FK", "FO", "FJ", "FI",
            "FR", "GF", "PF", "TF", "GA", "GM", "GE", "DE", "GH", "GI", "GR", "GL", "GD", "GP", "GU",
            "GT", "GN", "GW", "GY", "HT", "HM", "VA", "HN", "HK", "HU", "IS", "IN", "ID", "IR", "IQ",
            "IE", "IM", "IL", "IT", "JM", "JP", "JO", "KZ", "KE", "KI", "KP", "KR", "XK", "KW", "KG",
            "LA", "LV", "LB", "LS", "LR", "LY", "LI", "LT", "LU", "NF", "MO", "MG", "MW", "MY", "MV",
            "ML", "MT", "MH", "MQ", "MR", "MU", "YT", "MX", "FM", "MD", "MC", "MN", "ME", "MS", "MA",
            "MZ", "MM", "NA", "NR", "NP", "NL", "NC", "NZ", "NI", "NE", "NG", "NU", "MK", "MP", "NO",
            "OM", "PK", "PW", "PS", "PA", "PG", "PY", "PE", "PH", "PN", "PL", "PT", "PR", "QA", "RE",
            "RO", "RU", "RW", "SH", "LC", "KN", "MF", "PM", "VC", "WS", "SM", "ST", "SA", "SN", "RS",
            "SC", "SL", "SG", "SX", "SK", "SI", "SB", "SO", "ZA", "GS", "SS", "ES", "LK", "SD", "SR",
            "SJ", "SE", "CH", "SY", "TW", "TJ", "TZ", "TH", "TL", "TG", "TK", "TT", "TN", "TO", "TR",
            "TM", "TC", "TV", "UG", "UA", "AE", "GB", "US", "UM", "UY", "UZ", "VU", "VE", "VN", "VI",
            "VG", "WF", "EH", "YE", "ZM", "ZW"
        }
        if fob_point == "O":
            field_def = ExportFieldDefinition.objects.filter(position=35).first()
            if not fob_country:
                missing_fields.append({
                    'position': 35,
                    'column_name': field_def.column_name if field_def else 'FOB Country',
                    'field_name': field_def.column_name if field_def else 'FOB Country'
                })
            elif len(fob_country) > 2:
                missing_fields.append({
                    'position': 35,
                    'column_name': f"{field_def.column_name if field_def else 'FOB Country'} exceeds 2 characters",
                    'field_name': f"{field_def.column_name if field_def else 'FOB Country'} exceeds 2 characters"
                })
            elif fob_country not in country_codes:
                missing_fields.append({
                    'position': 35,
                    'column_name': f"{field_def.column_name if field_def else 'FOB Country'} must be a valid country code",
                    'field_name': f"{field_def.column_name if field_def else 'FOB Country'} must be a valid country code"
                })
    except Exception:
        pass

    # Row 36: Inspection Point Code is mandatory and must be D or O.
    try:
        inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
        if inspection_point and inspection_point not in {"D", "O"}:
            field_def = ExportFieldDefinition.objects.filter(position=36).first()
            missing_fields.append({
                'position': 36,
                'column_name': f"{field_def.column_name if field_def else 'Inspection Point Code'} must be D or O",
                'field_name': f"{field_def.column_name if field_def else 'Inspection Point Code'} must be D or O"
            })
    except Exception:
        pass

    # Conditional DLA rule for position 37:
    # If Inspection Point Code (36) is Origin, Packaging CAGE code (37) is required.
    # If Inspection Point Code (36) is Destination, Packaging CAGE code (37) must be blank.
    try:
        inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
        packaging_cage = str(values[36]).strip() if len(values) >= 37 else ""
        if inspection_point == "O":
            field_def = ExportFieldDefinition.objects.filter(position=37).first()
            if not packaging_cage:
                missing_fields.append({
                    'position': 37,
                    'column_name': field_def.column_name if field_def else 'Place of Government Inspection - Packaging CAGE code',
                    'field_name': field_def.column_name if field_def else 'Place of Government Inspection - Packaging CAGE code'
                })
            elif len(packaging_cage) > 5:
                missing_fields.append({
                    'position': 37,
                    'column_name': f"{field_def.column_name if field_def else 'Place of Government Inspection - Packaging CAGE code'} exceeds 5 characters",
                    'field_name': f"{field_def.column_name if field_def else 'Place of Government Inspection - Packaging CAGE code'} exceeds 5 characters"
                })
    except Exception:
        pass

    # Conditional DLA rule for position 38:
    # If Inspection Point Code (36) is Origin, Supplies CAGE code (38) is required.
    # If Inspection Point Code (36) is Destination, Supplies CAGE code (38) must be blank.
    try:
        inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
        supplies_cage = str(values[37]).strip() if len(values) >= 38 else ""
        if inspection_point == "O":
            field_def = ExportFieldDefinition.objects.filter(position=38).first()
            if not supplies_cage:
                missing_fields.append({
                    'position': 38,
                    'column_name': field_def.column_name if field_def else 'Place of Government Inspection - Supplies CAGE code',
                    'field_name': field_def.column_name if field_def else 'Place of Government Inspection - Supplies CAGE code'
                })
            elif len(supplies_cage) > 5:
                missing_fields.append({
                    'position': 38,
                    'column_name': f"{field_def.column_name if field_def else 'Place of Government Inspection - Supplies CAGE code'} exceeds 5 characters",
                    'field_name': f"{field_def.column_name if field_def else 'Place of Government Inspection - Supplies CAGE code'} exceeds 5 characters"
                })
    except Exception:
        pass

    # Row 49: Quantity must follow RFQ requirement rules.
    try:
        quoted_quantity = str(values[48]).strip() if len(values) >= 49 else ""
        requirement_quantity = get_rfq_requirement_quantity(rfq_reply)
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        bid_type = str(values[23]).strip().upper() if len(values) >= 24 else ""
        nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
        prohibited_parts = {"0001S00000052", "0001S00000053"}
        field_def = ExportFieldDefinition.objects.filter(position=49).first()
        if quoted_quantity and len(quoted_quantity) > 10:
            missing_fields.append({
                'position': 49,
                'column_name': f"{field_def.column_name if field_def else 'Quantity'} exceeds 10 characters",
                'field_name': f"{field_def.column_name if field_def else 'Quantity'} exceeds 10 characters"
            })
        quoted_quantity_num = _to_quantity_decimal(quoted_quantity)
        if quoted_quantity and quoted_quantity_num == 0 and bid_type != "DQ":
            missing_fields.append({
                'position': 24,
                'column_name': 'Bid Type Code must be DQ when Quantity is zero',
                'field_name': 'Bid Type Code must be DQ when Quantity is zero'
            })
        elif quoted_quantity and requirement_quantity and not _quantities_match(quoted_quantity, requirement_quantity):
            if solicitation_type == "I":
                missing_fields.append({
                    'position': 49,
                    'column_name': 'Quantity must match the estimated RFQ quantity when Solicitation Type Indicator is I',
                    'field_name': 'Quantity must match the estimated RFQ quantity when Solicitation Type Indicator is I'
                })
            elif nsn_part in prohibited_parts:
                missing_fields.append({
                    'position': 49,
                    'column_name': 'Quantity cannot differ from the RFQ requirement for this NSN/Part Number',
                    'field_name': 'Quantity cannot differ from the RFQ requirement for this NSN/Part Number'
                })
            elif bid_type not in {"BW", "AB"}:
                missing_fields.append({
                    'position': 24,
                    'column_name': 'Bid Type Code must be BW or AB when Quantity differs from the RFQ requirement',
                    'field_name': 'Bid Type Code must be BW or AB when Quantity differs from the RFQ requirement'
                })
    except Exception:
        pass

    # Row 50: Unit Price cannot be blank and must be 0 to 9999999.99999
    # with no more than 5 decimal places.
    try:
        unit_price = str(values[49]).strip() if len(values) >= 50 else ""
        unit_price_error = validate_row_50_unit_price(unit_price)
        if unit_price_error:
            field_def = ExportFieldDefinition.objects.filter(position=50).first()
            missing_fields.append({
                'position': 50,
                'column_name': f"{field_def.column_name if field_def else 'Unit Price'}: {unit_price_error}",
                'field_name': f"{field_def.column_name if field_def else 'Unit Price'}: {unit_price_error}"
            })
    except Exception:
        pass

    # Row 51: Delivery Days cannot be blank and must be a whole number.
    try:
        delivery_days = str(values[50]).strip() if len(values) >= 51 else ""
        solicitation_number = str(values[0]).strip() if len(values) >= 1 else ""
        delivery_days_error = validate_row_51_delivery_days(delivery_days, solicitation_number)
        if delivery_days_error:
            field_def = ExportFieldDefinition.objects.filter(position=51).first()
            missing_fields.append({
                'position': 51,
                'column_name': f"{field_def.column_name if field_def else 'Delivery Days'}: {delivery_days_error}",
                'field_name': f"{field_def.column_name if field_def else 'Delivery Days'}: {delivery_days_error}"
            })

        unit_price_num = _to_quantity_decimal(values[49] if len(values) >= 50 else "")
        delivery_days_num = int(delivery_days) if delivery_days.isdigit() else None
        nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
        bid_type = str(values[23]).strip().upper() if len(values) >= 24 else ""
        waiver_code = str(values[63]).strip().upper() if len(values) >= 64 else ""
        special_parts = {"0001S00000052", "0001S00000053"}
        if unit_price_num == Decimal("0") and delivery_days_num == 0 and nsn_part in special_parts and bid_type not in {"BW", "AB"}:
            missing_fields.append({
                'position': 24,
                'column_name': 'Bid Type Code must be BW or AB when Unit Price and Delivery Days are zero for this NSN/Part Number',
                'field_name': 'Bid Type Code must be BW or AB when Unit Price and Delivery Days are zero for this NSN/Part Number'
            })
        if waiver_code == "N" and delivery_days_num == 0:
            field_def = ExportFieldDefinition.objects.filter(position=51).first()
            missing_fields.append({
                'position': 51,
                'column_name': f"{field_def.column_name if field_def else 'Delivery Days'} cannot be zero when First Article Waiver Code is N",
                'field_name': f"{field_def.column_name if field_def else 'Delivery Days'} cannot be zero when First Article Waiver Code is N"
            })
    except Exception:
        pass

    # Row 56: No DO Minimum Quantity is driven by row 2.
    try:
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        no_do_minimum = str(values[55]).strip().upper() if len(values) >= 56 else ""
        no_do_minimum_error = validate_row_56_no_do_minimum(no_do_minimum, solicitation_type)
        if no_do_minimum_error:
            field_def = ExportFieldDefinition.objects.filter(position=56).first()
            missing_fields.append({
                'position': 56,
                'column_name': f"{field_def.column_name if field_def else 'No DO Minimum Quantity'}: {no_do_minimum_error}",
                'field_name': f"{field_def.column_name if field_def else 'No DO Minimum Quantity'}: {no_do_minimum_error}"
            })
    except Exception:
        pass

    # Row 58: Waiver of HUBZone Preference is driven by rows 57 and 13.
    try:
        hubzone = str(values[56]).strip().upper() if len(values) >= 57 else ""
        hubzone_waiver = str(values[57]).strip().upper() if len(values) >= 58 else ""
        small_business_code = str(values[12]).strip().upper() if len(values) >= 13 else ""
        hubzone_waiver_error = validate_row_58_hubzone_waiver(
            hubzone_waiver,
            hubzone,
            small_business_code
        )
        if hubzone_waiver_error:
            field_def = ExportFieldDefinition.objects.filter(position=58).first()
            missing_fields.append({
                'position': 58,
                'column_name': f"{field_def.column_name if field_def else 'Waiver of HUBZone Preference'}: {hubzone_waiver_error}",
                'field_name': f"{field_def.column_name if field_def else 'Waiver of HUBZone Preference'}: {hubzone_waiver_error}"
            })
    except Exception:
        pass

    # Row 59: Immediate Shipment Price is driven by row 100.
    try:
        immediate_price = str(values[58]).strip() if len(values) >= 59 else ""
        immediate_available = str(values[99]).strip().upper() if len(values) >= 100 else ""
        immediate_price_error = validate_row_59_immediate_shipment_price(
            immediate_price,
            immediate_available
        )
        if immediate_price_error:
            field_def = ExportFieldDefinition.objects.filter(position=59).first()
            missing_fields.append({
                'position': 59,
                'column_name': f"{field_def.column_name if field_def else 'Immediate Shipment Price'}: {immediate_price_error}",
                'field_name': f"{field_def.column_name if field_def else 'Immediate Shipment Price'}: {immediate_price_error}"
            })
    except Exception:
        pass

    # Row 60: Immediate Shipment Delivery Days is driven by row 100.
    try:
        immediate_delivery = str(values[59]).strip() if len(values) >= 60 else ""
        immediate_available = str(values[99]).strip().upper() if len(values) >= 100 else ""
        immediate_delivery_error = validate_row_60_immediate_shipment_delivery(
            immediate_delivery,
            immediate_available
        )
        if immediate_delivery_error:
            field_def = ExportFieldDefinition.objects.filter(position=60).first()
            missing_fields.append({
                'position': 60,
                'column_name': f"{field_def.column_name if field_def else 'Immediate Shipment Delivery Days'}: {immediate_delivery_error}",
                'field_name': f"{field_def.column_name if field_def else 'Immediate Shipment Delivery Days'}: {immediate_delivery_error}"
            })
    except Exception:
        pass

    # Row 63: Source of Supply CAGE Code is driven by row 102.
    try:
        source_supply_cage = str(values[62]).strip() if len(values) >= 63 else ""
        manufacturer_dealer = str(values[101]).strip().upper() if len(values) >= 102 else ""
        source_supply_cage_error = validate_row_63_source_supply_cage(
            source_supply_cage,
            manufacturer_dealer
        )
        if source_supply_cage_error:
            field_def = ExportFieldDefinition.objects.filter(position=63).first()
            missing_fields.append({
                'position': 63,
                'column_name': f"{field_def.column_name if field_def else 'Source of Supply CAGE Code'}: {source_supply_cage_error}",
                'field_name': f"{field_def.column_name if field_def else 'Source of Supply CAGE Code'}: {source_supply_cage_error}"
            })
    except Exception:
        pass

    # Row 64: First Article Waiver Code is driven by row 47.
    try:
        first_article_waiver = str(values[63]).strip().upper() if len(values) >= 64 else ""
        nsn_part = str(values[46]).strip().upper() if len(values) >= 47 else ""
        first_article_waiver_error = validate_row_64_first_article_waiver(
            first_article_waiver,
            nsn_part
        )
        if first_article_waiver_error:
            field_def = ExportFieldDefinition.objects.filter(position=64).first()
            missing_fields.append({
                'position': 64,
                'column_name': f"{field_def.column_name if field_def else 'First Article Waiver Code'}: {first_article_waiver_error}",
                'field_name': f"{field_def.column_name if field_def else 'First Article Waiver Code'}: {first_article_waiver_error}"
            })
    except Exception:
        pass

    # Row 67: Material Requirements is mandatory and may force Bid Type Code.
    try:
        material_requirement = str(values[66]).strip() if len(values) >= 67 else ""
        solicitation_type = str(values[1]).strip().upper() if len(values) >= 2 else ""
        bid_type = str(values[23]).strip().upper() if len(values) >= 24 else ""
        material_requirement_error = validate_row_67_material_requirements(
            material_requirement,
            solicitation_type,
            bid_type
        )
        if material_requirement_error:
            field_def = ExportFieldDefinition.objects.filter(position=67).first()
            missing_fields.append({
                'position': 67,
                'column_name': f"{field_def.column_name if field_def else 'Material Requirements'}: {material_requirement_error}",
                'field_name': f"{field_def.column_name if field_def else 'Material Requirements'}: {material_requirement_error}"
            })
    except Exception:
        pass

    # Row 70: End Product valid codes depend on rows 62, 68, and 69.
    try:
        end_product = str(values[69]).strip().upper() if len(values) >= 70 else ""
        trade_agreement = str(values[61]).strip().upper() if len(values) >= 62 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        free_trade = str(values[68]).strip().upper() if len(values) >= 69 else ""
        end_product_error = validate_row_70_end_product(
            end_product,
            trade_agreement,
            buy_american,
            free_trade
        )
        if end_product_error:
            field_def = ExportFieldDefinition.objects.filter(position=70).first()
            missing_fields.append({
                'position': 70,
                'column_name': f"{field_def.column_name if field_def else 'Buy American/Free Trade/Trade Agreements End Product'}: {end_product_error}",
                'field_name': f"{field_def.column_name if field_def else 'Buy American/Free Trade/Trade Agreements End Product'}: {end_product_error}"
            })
    except Exception:
        pass

    # Row 71: Country of Origin Code is driven by rows 62, 68, 69, and 70.
    try:
        country_origin = str(values[70]).strip().upper() if len(values) >= 71 else ""
        trade_agreement = str(values[61]).strip().upper() if len(values) >= 62 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        free_trade = str(values[68]).strip().upper() if len(values) >= 69 else ""
        end_product = str(values[69]).strip().upper() if len(values) >= 70 else ""
        country_origin_error = validate_row_71_country_origin(
            country_origin,
            trade_agreement,
            buy_american,
            free_trade,
            end_product
        )
        if country_origin_error:
            field_def = ExportFieldDefinition.objects.filter(position=71).first()
            missing_fields.append({
                'position': 71,
                'column_name': f"{field_def.column_name if field_def else 'Country of Origin Code'}: {country_origin_error}",
                'field_name': f"{field_def.column_name if field_def else 'Country of Origin Code'}: {country_origin_error}"
            })
    except Exception:
        pass

    # Row 72: Country Code is driven by row 70.
    try:
        country_code = str(values[71]).strip().upper() if len(values) >= 72 else ""
        end_product = str(values[69]).strip().upper() if len(values) >= 70 else ""
        country_code_error = validate_row_72_country_code(country_code, end_product)
        if country_code_error:
            field_def = ExportFieldDefinition.objects.filter(position=72).first()
            missing_fields.append({
                'position': 72,
                'column_name': f"{field_def.column_name if field_def else 'Country Code'}: {country_code_error}",
                'field_name': f"{field_def.column_name if field_def else 'Country Code'}: {country_code_error}"
            })
    except Exception:
        pass

    # Row 73: Duty Free Entry Requested is driven by row 68.
    try:
        duty_free_entry = str(values[72]).strip().upper() if len(values) >= 73 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        duty_free_entry_error = validate_row_73_duty_free_entry(
            duty_free_entry,
            buy_american
        )
        if duty_free_entry_error:
            field_def = ExportFieldDefinition.objects.filter(position=73).first()
            missing_fields.append({
                'position': 73,
                'column_name': f"{field_def.column_name if field_def else 'Duty Free Entry Requested'}: {duty_free_entry_error}",
                'field_name': f"{field_def.column_name if field_def else 'Duty Free Entry Requested'}: {duty_free_entry_error}"
            })
    except Exception:
        pass

    # Row 74: Foreign Supplies in US Code is driven by rows 68 and 73.
    try:
        foreign_supplies = str(values[73]).strip().upper() if len(values) >= 74 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        duty_free_entry = str(values[72]).strip().upper() if len(values) >= 73 else ""
        foreign_supplies_error = validate_row_74_foreign_supplies(
            foreign_supplies,
            buy_american,
            duty_free_entry
        )
        if foreign_supplies_error:
            field_def = ExportFieldDefinition.objects.filter(position=74).first()
            missing_fields.append({
                'position': 74,
                'column_name': f"{field_def.column_name if field_def else 'Foreign Supplies in US Code'}: {foreign_supplies_error}",
                'field_name': f"{field_def.column_name if field_def else 'Foreign Supplies in US Code'}: {foreign_supplies_error}"
            })
    except Exception:
        pass

    # Row 75: Duty Paid Code is driven by rows 68 and 74.
    try:
        duty_paid = str(values[74]).strip().upper() if len(values) >= 75 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        foreign_supplies = str(values[73]).strip().upper() if len(values) >= 74 else ""
        duty_paid_error = validate_row_75_duty_paid(
            duty_paid,
            buy_american,
            foreign_supplies
        )
        if duty_paid_error:
            field_def = ExportFieldDefinition.objects.filter(position=75).first()
            missing_fields.append({
                'position': 75,
                'column_name': f"{field_def.column_name if field_def else 'Duty Paid Code'}: {duty_paid_error}",
                'field_name': f"{field_def.column_name if field_def else 'Duty Paid Code'}: {duty_paid_error}"
            })
    except Exception:
        pass

    # Row 76: Duty Paid Amount is driven by rows 68 and 75.
    try:
        duty_paid_amount = str(values[75]).strip() if len(values) >= 76 else ""
        buy_american = str(values[67]).strip().upper() if len(values) >= 68 else ""
        duty_paid = str(values[74]).strip().upper() if len(values) >= 75 else ""
        duty_paid_amount_error = validate_row_76_duty_paid_amount(
            duty_paid_amount,
            buy_american,
            duty_paid
        )
        if duty_paid_amount_error:
            field_def = ExportFieldDefinition.objects.filter(position=76).first()
            missing_fields.append({
                'position': 76,
                'column_name': f"{field_def.column_name if field_def else 'Duty Paid Amount'}: {duty_paid_amount_error}",
                'field_name': f"{field_def.column_name if field_def else 'Duty Paid Amount'}: {duty_paid_amount_error}"
            })
    except Exception:
        pass

    # Rows 78-95: Quantity Price Breaks are driven by row 2.
    try:
        for position, message in validate_rows_78_95_price_breaks(values):
            field_def = ExportFieldDefinition.objects.filter(position=position).first()
            fallback_name = f"Quantity Price Breaks Field {position}"
            missing_fields.append({
                'position': position,
                'column_name': f"{field_def.column_name if field_def else fallback_name}: {message}",
                'field_name': f"{field_def.column_name if field_def else fallback_name}: {message}"
            })
    except Exception:
        pass

    # Row 96: Quantity Variance Plus must be a percent from 0 to 10.
    try:
        quantity_variance_plus_error = validate_row_96_quantity_variance_plus(
            values[95] if len(values) >= 96 else ""
        )
        if quantity_variance_plus_error:
            field_def = ExportFieldDefinition.objects.filter(position=96).first()
            missing_fields.append({
                'position': 96,
                'column_name': f"{field_def.column_name if field_def else 'Quantity Variance Plus'}: {quantity_variance_plus_error}",
                'field_name': f"{field_def.column_name if field_def else 'Quantity Variance Plus'}: {quantity_variance_plus_error}"
            })
    except Exception:
        pass

    # Row 97: Quantity Variance Minus must be a percent from 0 to 10.
    try:
        quantity_variance_minus_error = validate_row_97_quantity_variance_minus(
            values[96] if len(values) >= 97 else ""
        )
        if quantity_variance_minus_error:
            field_def = ExportFieldDefinition.objects.filter(position=97).first()
            missing_fields.append({
                'position': 97,
                'column_name': f"{field_def.column_name if field_def else 'Quantity Variance Minus'}: {quantity_variance_minus_error}",
                'field_name': f"{field_def.column_name if field_def else 'Quantity Variance Minus'}: {quantity_variance_minus_error}"
            })
    except Exception:
        pass

    # Row 98: Minimum Order Quantity Code is required for F, P, or blank solicitation type.
    try:
        minimum_order_quantity_code_error = validate_row_98_minimum_order_quantity_code(
            values[97] if len(values) >= 98 else "",
            values[1] if len(values) >= 2 else "",
        )
        if minimum_order_quantity_code_error:
            field_def = ExportFieldDefinition.objects.filter(position=98).first()
            missing_fields.append({
                'position': 98,
                'column_name': f"{field_def.column_name if field_def else 'Minimum Order Quantity Code'}: {minimum_order_quantity_code_error}",
                'field_name': f"{field_def.column_name if field_def else 'Minimum Order Quantity Code'}: {minimum_order_quantity_code_error}"
            })
    except Exception:
        pass

    # Row 99: Minimum Order Maximum Quantity is required when row 98 is Y.
    try:
        minimum_order_maximum_quantity_error = validate_row_99_minimum_order_maximum_quantity(
            values[98] if len(values) >= 99 else "",
            values[97] if len(values) >= 98 else "",
        )
        if minimum_order_maximum_quantity_error:
            field_def = ExportFieldDefinition.objects.filter(position=99).first()
            missing_fields.append({
                'position': 99,
                'column_name': f"{field_def.column_name if field_def else 'Minimum Order Maximum Quantity'}: {minimum_order_maximum_quantity_error}",
                'field_name': f"{field_def.column_name if field_def else 'Minimum Order Maximum Quantity'}: {minimum_order_maximum_quantity_error}"
            })
    except Exception:
        pass

    # Row 100: Immediate Shipment Available is required for F, P, or blank solicitation type.
    try:
        immediate_shipment_available_error = validate_row_100_immediate_shipment_available(
            values[99] if len(values) >= 100 else "",
            values[1] if len(values) >= 2 else "",
        )
        if immediate_shipment_available_error:
            field_def = ExportFieldDefinition.objects.filter(position=100).first()
            missing_fields.append({
                'position': 100,
                'column_name': f"{field_def.column_name if field_def else 'Immediate Shipment Available'}: {immediate_shipment_available_error}",
                'field_name': f"{field_def.column_name if field_def else 'Immediate Shipment Available'}: {immediate_shipment_available_error}"
            })
    except Exception:
        pass

    # Rows 101 and 103-116: product offer details driven by rows 100, 102, 105, 106, and 110.
    try:
        for position, message in validate_rows_101_116_conditional(values):
            already_missing = any(item.get('position') == position for item in missing_fields)
            if already_missing:
                continue
            field_def = ExportFieldDefinition.objects.filter(position=position).first()
            fallback_name = f"Export Field {position}"
            missing_fields.append({
                'position': position,
                'column_name': f"{field_def.column_name if field_def else fallback_name}: {message}",
                'field_name': f"{field_def.column_name if field_def else fallback_name}: {message}"
            })
    except Exception:
        pass

    # Rows 118-121: quality code, quality remarks, child labor code, and quote remarks.
    try:
        for position, message in validate_rows_118_121_quality_labor_remarks(values):
            already_missing = any(item.get('position') == position for item in missing_fields)
            if already_missing:
                continue
            field_def = ExportFieldDefinition.objects.filter(position=position).first()
            fallback_name = f"Export Field {position}"
            missing_fields.append({
                'position': position,
                'column_name': f"{field_def.column_name if field_def else fallback_name}: {message}",
                'field_name': f"{field_def.column_name if field_def else fallback_name}: {message}"
            })
    except Exception:
        pass

    try:
        manufacturer_dealer = str(values[101]).strip().upper() if len(values) >= 102 else ""
        source_cage = str(values[102]).strip() if len(values) >= 103 else ""
        source_name_address = str(values[103]).strip() if len(values) >= 104 else ""
        already_has_source_error = any(item.get('position') in {103, 104} for item in missing_fields)
        if manufacturer_dealer in {"DD", "QD"} and not source_cage and not source_name_address and not already_has_source_error:
            field_def = ExportFieldDefinition.objects.filter(position=104).first()
            missing_fields.append({
                'position': 104,
                'column_name': field_def.column_name if field_def else 'Actual Manufacturing/Production Source Name and Address',
                'field_name': field_def.column_name if field_def else 'Actual Manufacturing/Production Source Name and Address'
            })
    except Exception:
        pass
    
    is_valid = len(missing_fields) == 0
    return is_valid, missing_fields


def get_effective_rfq_reply_values(user, rfq_reply):
    """
    Get the 121 export values for an RFQ reply.
    
    Logic:
    1. First, build base values from global user configurations (applies to all RFQs)
    2. Then, apply per-RFQ overrides ONLY for fields that have non-empty values
       (allows users to customize specific RFQs without affecting others)
    
    This ensures that:
    - Global config provides defaults for all fields
    - Per-RFQ overrides can customize specific fields without needing to fill all 121
    - Empty override values don't override the global config
    """
    # First, build base values from global configurations
    values = build_rfq_reply_values(user, rfq_reply)
    requirement_inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
    
    # Then, apply per-RFQ overrides (if any exist)
    try:
        override = getattr(rfq_reply, 'export_override', None)
        if override and override.data and len(override.data) == 121:
            # Apply overrides: use override value if it's not empty, otherwise keep global config value
            for i in range(121):
                if i == 49:
                    continue
                override_value = override.data[i]
                # Only use override if it has a non-empty value
                if override_value and (not isinstance(override_value, str) or override_value.strip()):
                    values[i] = override_value
    except Exception:
        # If there's any issue with override, just use the global config values
        pass

    # Re-enforce DLA business rules after overrides; overrides must not violate mandatory rules.
    # Row 18 (Joint Venture): must be blank when Set Aside (3) == "N" or Small Biz Code (13) not B/M.
    try:
        if len(values) >= 18:
            set_aside = str(values[2]).strip().upper()
            small_biz = str(values[12]).strip().upper()
            joint_venture = str(values[17]).strip().upper()
            if set_aside == "N" or small_biz not in ("B", "M"):
                values[17] = ""
            else:
                values[17] = joint_venture if joint_venture in ("JV", "JN") else ""
    except Exception:
        pass

    # Row 19 (Joint Venture Remarks): must be blank when row 18 != "JV".
    try:
        if len(values) >= 19:
            if str(values[17]).strip().upper() != "JV":
                values[18] = ""
    except Exception:
        pass

    # Row 27: when Solicitation Type (2) is I and Days Quote Valid (27) is less than 90,
    # Bid Type Code (24) must be BW or AB. Default to BW if needed.
    try:
        if len(values) >= 27:
            solicitation_type = str(values[1]).strip().upper()
            if solicitation_type == "I":
                days_raw = str(values[26]).strip()
                if days_raw:
                    try:
                        days_val = int(days_raw)
                    except ValueError:
                        days_val = None
                    if days_val is not None and days_val < 90 and len(values) >= 24:
                        bid_type = str(values[23]).strip().upper()
                        if bid_type not in ("BW", "AB"):
                            values[23] = "BW"
    except Exception:
        pass

    # Row 28: when Meets Packaging Requirement (28) is N,
    # Bid Type Code (24) must be BW or AB. Default to BW if needed.
    try:
        if len(values) >= 28:
            packaging_requirement = str(values[27]).strip().upper()
            if packaging_requirement == "N" and len(values) >= 24:
                bid_type = str(values[23]).strip().upper()
                if bid_type not in ("BW", "AB"):
                    values[23] = "BW"
    except Exception:
        pass

    # Row 23: normalize legacy Y/N Alternate Disputes Resolution values to DIBBS A/B codes.
    try:
        apply_row_23_alternate_disputes_resolution_rule(values)
    except Exception:
        pass

    # Row 49: Quantity effects on Bid Type Code (24).
    try:
        requirement_quantity = get_rfq_requirement_quantity(rfq_reply)
        apply_row_49_quantity_rule(values, requirement_quantity)
    except Exception:
        pass
    try:
        apply_row_51_delivery_days_rule(values)
    except Exception:
        pass
    try:
        apply_row_56_no_do_minimum_rule(values)
    except Exception:
        pass
    try:
        apply_row_58_hubzone_waiver_rule(values)
    except Exception:
        pass
    try:
        apply_row_100_immediate_shipment_available_rule(values)
    except Exception:
        pass
    try:
        apply_rows_101_116_conditional_rules(values)
    except Exception:
        pass
    try:
        apply_rows_118_121_quality_labor_remarks_rules(values)
    except Exception:
        pass
    try:
        apply_row_59_immediate_shipment_price_rule(values)
    except Exception:
        pass
    try:
        apply_row_60_immediate_shipment_delivery_rule(values)
    except Exception:
        pass
    try:
        apply_row_63_source_supply_cage_rule(values)
    except Exception:
        pass
    try:
        apply_row_64_first_article_waiver_rule(values)
    except Exception:
        pass
    try:
        apply_row_67_material_requirements_rule(values)
    except Exception:
        pass
    try:
        apply_row_71_country_origin_rule(values)
    except Exception:
        pass
    try:
        apply_row_72_country_code_rule(values)
    except Exception:
        pass
    try:
        apply_row_73_duty_free_entry_rule(values)
    except Exception:
        pass
    try:
        apply_row_74_foreign_supplies_rule(values)
    except Exception:
        pass
    try:
        apply_row_75_duty_paid_rule(values)
    except Exception:
        pass
    try:
        apply_row_76_duty_paid_amount_rule(values)
    except Exception:
        pass
    try:
        apply_rows_78_95_price_breaks_rule(values)
    except Exception:
        pass

    # Row 29: when BOA/FSS/BPA code (29) is NAP,
    # Contract Number (30) and Contract Expiration Date (31) must be blank.
    try:
        if len(values) >= 31:
            boa_code = str(values[28]).strip().upper()
            if boa_code == "NAP":
                values[29] = ""
                values[30] = ""
    except Exception:
        pass

    # Row 33: FOB City must be blank when FOB Point (32) is Destination.
    try:
        if len(values) >= 33:
            fob_point = str(values[31]).strip().upper()
            if fob_point == "D":
                values[32] = ""
    except Exception:
        pass

    # Row 34: FOB State/Province must be blank when FOB Point (32) is Destination
    # or when FOB Country (35) is not US or CA.
    try:
        if len(values) >= 35:
            fob_point = str(values[31]).strip().upper()
            fob_country = str(values[34]).strip().upper()
            if fob_point == "D" or fob_country not in {"US", "CA"}:
                values[33] = ""
    except Exception:
        pass

    # Row 35: FOB Country must be blank when FOB Point (32) is Destination.
    try:
        if len(values) >= 35:
            fob_point = str(values[31]).strip().upper()
            if fob_point == "D":
                values[34] = ""
    except Exception:
        pass

    # Row 36: Inspection Point Code must be D or O. If changed from the
    # solicitation requirement, Bid Type Code (24) must be BW or AB.
    try:
        if len(values) >= 36:
            inspection_point = str(values[35]).strip().upper()
            if inspection_point not in {"D", "O"}:
                values[35] = ""
            elif requirement_inspection_point and inspection_point != requirement_inspection_point and len(values) >= 24:
                bid_type = str(values[23]).strip().upper()
                if bid_type not in {"BW", "AB"}:
                    values[23] = "BW"
    except Exception:
        pass

    # Row 37: Packaging CAGE code must be blank when Inspection Point Code (36)
    # is Destination.
    try:
        if len(values) >= 37:
            inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
            if inspection_point == "D":
                values[36] = ""
    except Exception:
        pass

    # Row 38: Supplies CAGE code must be blank when Inspection Point Code (36)
    # is Destination.
    try:
        if len(values) >= 38:
            inspection_point = str(values[35]).strip().upper() if len(values) >= 36 else ""
            if inspection_point == "D":
                values[37] = ""
    except Exception:
        pass

    try:
        if len(values) >= 66:
            hazardous_warning_label = str(values[65]).strip()
            values[65] = hazardous_warning_label if hazardous_warning_label in {"1", "2", "3", "4", "5", "6", "7"} else ""
    except Exception:
        pass

    try:
        if len(values) >= 104:
            manufacturer_dealer = str(values[101]).strip().upper() if len(values) >= 102 else ""
            if manufacturer_dealer in {"MM", "QM"}:
                values[103] = ""
    except Exception:
        pass

    return values


def generate_export_line_for_rfq_reply(user, rfq_reply):
    """
    Generate a single export line for an RFQ reply with 121 fields.

    Args:
        user: User object for configuration lookup
        rfq_reply: RfqReply object to export

    Returns:
        String with comma-separated values (121 fields), all quoted
    """
    values = get_effective_rfq_reply_values(user, rfq_reply)
    return serialize_export_values(values)


def generate_export_file_for_rfq_replies(user, rfq_replies, validate_mandatory=True):
    """
    Generate complete export file for multiple RFQ replies.
    If validate_mandatory is True, validates ALL RFQs first. If ANY fail, returns empty content and all errors.

    Args:
        user: User object for configuration lookup
        rfq_replies: QuerySet or list of RfqReply objects
        validate_mandatory: If True, validate all RFQs first - if any fail, export nothing

    Returns:
        tuple: (content: str, errors: list)
            - content: String containing the complete export file content (empty if validation fails)
            - errors: List of dicts with 'rfq_reply_id', 'rfq_reply_ref', 'missing_fields' for failed RFQs
    """
    errors = []
    
    # First, validate ALL RFQs if validation is enabled
    if validate_mandatory:
        import logging
        logger = logging.getLogger(__name__)
        logger.info(f"[GENERATE_EXPORT_FILE] Validating {rfq_replies.count() if hasattr(rfq_replies, 'count') else len(rfq_replies)} RFQ replies")
        
        for rfq_reply in rfq_replies:
            is_valid, missing_fields = validate_mandatory_fields(user, rfq_reply)
            if not is_valid:
                # Record the error
                rfq_ref = rfq_reply.rfq_unique_id or rfq_reply.solicitation_number or f"ID {rfq_reply.id}"
                errors.append({
                    'rfq_reply_id': rfq_reply.id,
                    'rfq_reply_ref': rfq_ref,
                    'missing_fields': missing_fields
                })
                logger.warning(f"[GENERATE_EXPORT_FILE] RFQ {rfq_ref} (ID: {rfq_reply.id}) failed validation: {len(missing_fields)} missing fields")
        
        # If ANY RFQ has errors, don't export any of them
        if errors:
            logger.error(f"[GENERATE_EXPORT_FILE] Validation failed: {len(errors)} RFQ(s) have errors. Export cancelled.")
            return "", errors
        
        logger.info(f"[GENERATE_EXPORT_FILE] All RFQs passed validation. Proceeding with export.")
    
    # All RFQs passed validation (or validation disabled) - proceed with export
    lines = []
    for rfq_reply in rfq_replies:
        # Use per-RFQ overrides when present, otherwise global config
        values = get_effective_rfq_reply_values(user, rfq_reply)
        line = serialize_export_values(values)
        lines.append(line)

    # Join quote records with Windows CRLF and do not emit blank quote rows.
    content = '\r\n'.join(line for line in lines if line.strip())
    if content:
        content += '\r\n'

    structure_errors = validate_export_file_structure(content)
    if structure_errors:
        errors.append({
            'rfq_reply_id': None,
            'rfq_reply_ref': 'Batch export structure',
            'missing_fields': [
                {
                    'position': 0,
                    'column_name': error,
                    'field_name': error,
                }
                for error in structure_errors
            ]
        })
        return "", errors

    return content, errors


def export_rfq_replies_to_file(user, rfq_replies, file_path=None, filename=None, validate_mandatory=True):
    """
    Export RFQ replies to a text file.

    Args:
        user: User object for configuration lookup
        rfq_replies: QuerySet or list of RfqReply objects
        file_path: Full path where to save the export file (optional)
        filename: Just the filename (will be saved in exports directory) (optional)
        validate_mandatory: If True, skip RFQs with missing mandatory fields (default: True)

    Returns:
        dict: {
            'count': Number of RFQ replies exported,
            'file_path': Full path to the exported file,
            'filename': Name of the exported file,
            'errors': List of dicts with validation errors for skipped RFQs,
            'skipped_count': Number of RFQs skipped due to validation errors
        }
    """
    content, errors = generate_export_file_for_rfq_replies(user, rfq_replies, validate_mandatory=validate_mandatory)

    # Determine the file path
    if file_path:
        # Use provided full path
        full_path = file_path
    elif filename:
        # Use provided filename in exports directory
        export_dir = get_export_directory()
        full_path = os.path.join(export_dir, filename)
    else:
        # Generate automatic filename in exports directory
        export_dir = get_export_directory()
        filename = generate_export_filename(user, prefix='rfq_replies_export')
        full_path = os.path.join(export_dir, filename)

    # Ensure directory exists
    os.makedirs(os.path.dirname(full_path), exist_ok=True)

    # Write the file (only if there's content to write and no errors)
    if errors:
        # Validation failed - don't create file
        full_path = None
        exported_count = 0
    elif content.strip():  # Only write if there's actual content (not just newlines)
        with open(full_path, 'w', encoding='utf-8', newline='') as f:
            f.write(content)
        # Count exported RFQs (lines in content)
        exported_count = len([line for line in content.splitlines() if line.strip()])
    else:
        # If no content, don't create file
        full_path = None
        exported_count = 0

    return {
        'count': exported_count,
        'file_path': full_path,
        'filename': os.path.basename(full_path) if full_path else None,
        'errors': errors,
        'skipped_count': len(errors)
    }


def get_user_field_mapping(user):
    """
    Get user's current field mapping configuration.

    Args:
        user: User object

    Returns:
        Dictionary with position as key and configuration details as value
    """
    configurations = UserExportConfiguration.objects.filter(
        user=user
    ).select_related('field_definition').order_by('field_definition__position')

    mapping = {}
    for config in configurations:
        mapping[config.field_definition.position] = {
            'column_name': config.field_definition.column_name,
            'field_type': config.field_definition.field_type,
            'is_enabled': config.is_enabled,
            'source_field': config.source_field,
            'custom_value': config.custom_value,
            'default_value': config.field_definition.default_value,
        }

    return mapping

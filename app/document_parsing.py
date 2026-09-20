"""Bill of lading identifiers; booking and container numbers are not bills."""
import re


def document_metadata(text, agent_name=""):
    upper = str(text or "").upper()
    normalized = re.sub(r"[ \t]+", " ", upper)
    reference_patterns = [
        r"(?:BILL\s+OF\s+LAD[I1!]NG|BILL\s+NO|B[\s./-]*L)\s*(?:NO\.?|N[O0]\.?|NUMBER|NUM8ER|REF(?:ERENCE)?|#)?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{5,29})",
        r"(?:MASTER|HOUSE)\s+B/?L\s*(?:NO\.?|NUMBER|#)?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{5,29})",
        r"(?:SEA\s+WAYBILL|WAYBILL)\s*(?:NO\.?|N[O0]\.?|NUMBER|#)?\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{5,29})",
        r"(?:رقم البوليصة|رقم بوليصة الشحن)\s*[:#.-]?\s*([A-Z0-9][A-Z0-9/-]{5,29})",
    ]
    references = []
    for pattern in reference_patterns:
        references.extend(re.findall(pattern, normalized))
    containers = sorted(set(re.findall(r"\b[A-Z]{4}\s?\d{7}\b", upper)))
    container_set = {x.replace(" ", "") for x in containers}
    references = [x.strip("-./") for x in references if not re.fullmatch(r"(?:NUMBER|ORIGINAL|COPY|DATE|SHIPPER|CONSIGNEE)", x)]
    references = [x for x in references if x.replace(" ", "") not in container_set and re.search(r"\d", x)]
    if not references:
        carrier_prefixes = {"MSC": ("MEDU", "MSC"), "Maersk Line": ("MAEU",), "CMA CGM": ("CMDU",), "COSCO Line": ("COSU",), "Hapag-Lloyd": ("HLCU",), "Evergreen": ("EGLV",), "OOCL Line": ("OOLU",), "ONE Line": ("ONEY",), "PIL": ("PIL",)}
        prefixes = carrier_prefixes.get(agent_name, ())
        candidates = re.findall(r"\b[A-Z]{3,5}[A-Z0-9/-]{4,25}\b", normalized)
        references = [x for x in candidates if x not in container_set and re.search(r"\d", x) and any(x.startswith(prefix) for prefix in prefixes)]
    doc_type = "بوليصة شحن" if "BILL OF LADING" in upper or re.search(r"\bB/?L\b", upper) else "مستند شحن"
    return doc_type, (references[0] if references else ""), ", ".join(x.replace(" ", "") for x in containers[:20])


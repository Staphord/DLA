"""
GPT-4 Email Data Extractor for RFQ Replies

This module uses Azure OpenAI's GPT-4o model to extract structured data from OEM email replies.
It replaces the regex-based extraction with AI-powered extraction for better accuracy.

Features:
- Handles various email formats and layouts
- Extracts data even with typos and variations
- Understands context and intent
- Can process multiple line items
- Supports both Azure OpenAI and standard OpenAI API
"""

import json
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from django.conf import settings

from azure_openai_client import build_chat_completion_kwargs, create_chat_client


@dataclass
class RFQExtraction:
    """Structured data extracted from RFQ reply email"""
    # RFQ Identification
    rfq_unique_id: Optional[str] = None
    solicitation_number: Optional[str] = None

    # Item Details
    nsn: Optional[str] = None
    part_number: Optional[str] = None
    nomenclature: Optional[str] = None
    quantity: Optional[str] = None
    unit: Optional[str] = None

    # Pricing
    unit_price: Optional[float] = None
    total_price: Optional[float] = None
    minimum_order_qty: Optional[float] = None
    total_shipping_weight: Optional[float] = None
    shipping_cost_to_company: Optional[float] = None
    payment_term: Optional[str] = None
    oem_delivery_days: Optional[int] = None
    tax: Optional[float] = None
    packaging_cost: Optional[float] = None
    handling_fee: Optional[float] = None
    insurance_cost: Optional[float] = None
    customs_duty: Optional[float] = None
    setup_cost: Optional[float] = None
    minimum_order_charge: Optional[float] = None
    rush_delivery_fee: Optional[float] = None
    environmental_fee: Optional[float] = None
    certification_cost: Optional[float] = None
    documentation_fee: Optional[float] = None

    # OEM Information
    oem_name: Optional[str] = None
    replied_email: Optional[str] = None

    # Metadata
    confidence_score: Optional[float] = None
    extraction_notes: Optional[str] = None

    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


class GPT4EmailExtractor:
    """Extract RFQ data from emails using GPT-4 (Azure OpenAI or OpenAI)"""

    def __init__(self):
        """Initialize GPT extractor (Azure OpenAI, Foundry v1, or OpenAI)."""
        self.use_azure = settings.USE_AZURE_OPENAI
        self.max_retries = settings.OPENAI_MAX_RETRIES
        self.timeout = settings.OPENAI_TIMEOUT
        self.client, self.model, self.client_mode = create_chat_client()

    def extract_rfq_data(self, email_data: Dict) -> Optional[Dict]:
        """
        Extract RFQ reply data from email using GPT-4

        Args:
            email_data: Dict with 'subject', 'body', 'from_email',
                       and optionally 'attachment_contents'

        Returns:
            Dict with extracted data or None if extraction failed
        """
        subject = email_data.get('subject', '')
        body = email_data.get('body', '')
        from_email = email_data.get('from_email', '')
        attachment_contents = email_data.get('attachment_contents', [])

        # Build extraction prompt (including attachment content if available)
        prompt = self._build_extraction_prompt(
            subject, body, from_email, attachment_contents)

        # Call GPT-4 with retry logic
        for attempt in range(self.max_retries):
            try:
                response = self._call_gpt4(prompt)

                if response:
                    # Parse and validate response
                    extracted_data = self._parse_response(response, from_email)
                    return extracted_data

            except Exception as e:
                error_type = type(e).__name__

                # Handle rate limit errors
                if 'RateLimitError' in error_type or 'rate_limit' in str(e).lower():
                    wait_time = (attempt + 1) * 2  # Exponential backoff
                    print(f"  [WARN] Rate limit hit, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue

                # Handle API errors
                elif 'APIError' in error_type or 'api' in str(e).lower():
                    print(f"  [ERROR] API error: {e}")
                    if attempt < self.max_retries - 1:
                        time.sleep(1)
                        continue
                    return None

                # Other errors
                else:
                    print(
                        f"  [ERROR] Unexpected error in GPT-4 extraction: {e}")
                    return None

        return None

    def _build_extraction_prompt(self, subject: str, body: str, from_email: str, attachment_contents: List[str] = None) -> str:
        """Build the extraction prompt for GPT-4"""

        # Build attachment section if attachments exist
        attachment_section = ""
        if attachment_contents and len(attachment_contents) > 0:
            attachment_section = "\n\nATTACHMENT CONTENTS:\n"
            for i, content in enumerate(attachment_contents, 1):
                # Limit attachment content to avoid token limits (first 2000 chars per attachment)
                truncated_content = content[:2000] + \
                    "..." if len(content) > 2000 else content
                attachment_section += f"\n--- Attachment {i} ---\n{truncated_content}\n"

        prompt = f"""You are a data extraction assistant for military procurement RFQ (Request for Quotation) replies.
Extract structured data from this email reply from an OEM (Original Equipment Manufacturer).
EMAIL DETAILS:
Subject: {subject}
From: {from_email}

EMAIL BODY:
{body}
{attachment_section}

EXTRACT THE FOLLOWING FIELDS:

1. rfq_unique_id: RFQ/Reference ID - can be in multiple formats:
   - Format 1: ABC-DLA-MMDDYY-CAGE-XXXXXX (e.g., "GTS-DLA-090125-1T615-018637")
   - Format 2: ABC/MMDDYYYY/CAGE/000001 (e.g., "VPG/11142025/H6077/000001")
   - Look for keywords: "RFQ", "Reference", "Ref", "Quote ID", "Request ID"

2. solicitation_number: Solicitation number in formats like:
   - SPEFA5-26-T-0169
   - SPE7M5-24-R-0001
   - Look for keywords: "Solicitation", "Sol", "Contract", "Award"

3. nsn: National Stock Number in format 1234-12-345-6789 (13 digits with dashes)
   - Look for keywords: "NSN", "Stock Number", "National Stock"

4. part_number: Part number or part identifier
   - Look for keywords: "Part Number", "Part No", "Part #", "PN", "P/N", "Part"
   - Can be alphanumeric (e.g., "ABC123", "12345-67", "PN-456")

5. nomenclature: Item description or part name
   - Look for keywords: "Description", "Item", "Part Name", "Nomenclature"

6. quantity: Quantity being quoted (just the number)
   - Look for keywords: "Qty", "Quantity", "QTY"

7. unit: Unit of measure (EA, BOX, EACH, PCS, etc.)
   - Look for keywords: "Unit", "UOM", "U/M"

8. unit_price: Price per unit (decimal number only, no currency symbols or commas)
   - Extract numeric value only (e.g., from "$1,250.00" extract 1250.00)
   - Look for keywords: "Unit Price", "Price Each", "Price/EA"

9. total_price: Total price (decimal number only, no currency symbols or commas)
   - Extract numeric value only (e.g., from "$12,500.00" extract 12500.00)
   - Look for keywords: "Total", "Total Price", "Extended Price"

10. minimum_order_qty: Minimum order quantity / MOQ (decimal number only)
    - Look for keywords: "MOQ", "Minimum Order", "Minimum Qty", "Minimum Quantity", "Min Order Qty"
    - If not found, use null.

11. total_shipping_weight: Total shipping weight in pounds/lbs (decimal number only)
    - Look for keywords: "Shipping Weight", "Weight", "Total Weight", "lbs", "lb"
    - If a different weight unit is provided, extract the numeric value and note the unit in extraction_notes.
    - If not found, use null.

12. shipping_cost_to_company: Shipping/freight cost charged by the OEM to ship to the buyer/company (decimal number only)
    - Look for keywords: "Shipping", "Freight", "Delivery Charge", "Transport", "Carrier Cost"
    - Do not include product price or tax in this value.
    - If not found, use null.

13. payment_term: Payment term code, using ONLY these codes:
    - "1" for Net 30, NET30, 30 Days, Due in 30 Days
    - "10" for 2% 10 Days
    - "3" for 1/2% 20 Days
    - "6" for 1/2% 10 Days
    - "8" for 1/4% 20 Days
    - If the payment term is not explicitly found or does not match one of these, use null.

14. oem_delivery_days: OEM lead time/delivery days (integer days only)
    - Look for keywords: "Lead Time", "Delivery", "ARO", "Ships in", "Available in", "Weeks"
    - Convert weeks to days using 7 days per week.
    - If a range is given, use the larger number.
    - If not found, use null.

15. Additional OEM costs/fees (decimal numbers only, no currency symbols or commas):
    - tax: Sales tax, VAT, GST, use tax, or tax amount
    - packaging_cost: Packaging, packing, package, boxing, crating, or preservation cost
    - handling_fee: Handling, processing, service, or administrative handling fee
    - insurance_cost: Insurance cost for shipment/order
    - customs_duty: Customs, duty, import duty, tariff, or international duty fee
    - setup_cost: Setup, tooling, molding, programming, engineering, or one-time setup cost
    - minimum_order_charge: Minimum order charge, minimum buy charge, MOQ charge, below-minimum fee
    - rush_delivery_fee: Rush, expedite, expedited delivery, urgent processing, or priority fee
    - environmental_fee: Environmental, hazmat, disposal, recycling, or hazardous material fee
    - certification_cost: Certification, testing, quality cert, C of C, inspection cert, or compliance cost
    - documentation_fee: Documentation, paperwork, document, processing, or admin document fee
    - If a fee is not explicitly found, use null.
    - Do not include unit_price or total_price in these additional costs.

16. oem_name: Company/vendor name
    - Extract from email signature or header

17. replied_email: Email address of the sender
    - Use the "From" email address

18. confidence_score: Your confidence in the extraction (0.0 to 1.0)
    - 0.9-1.0: All key fields found with high certainty
    - 0.7-0.9: Most fields found, some assumptions made
    - 0.5-0.7: Several fields missing or uncertain
    - Below 0.5: Very limited data extracted

19. extraction_notes: Any notes about the extraction
    - Note missing fields, assumptions, or if this is a "no quote" / declined response

IMPORTANT RULES:
- If a field is not found, use null
- For prices, extract ONLY the numeric value (remove $, commas, currency codes)
- For NSN, ensure it matches the 13-digit format with dashes (e.g., 5305-01-234-5678)
- For RFQ ID, accept both dash and slash formats
- If the email says "no quote", "declined", or "unable to quote", set prices to null and note in extraction_notes
- If multiple line items exist, extract the FIRST one
- Be flexible with variations and typos
- Look in both email body AND attachments for data

Return ONLY valid JSON in this exact format:
{{
    "rfq_unique_id": "GTS-DLA-090125-1T615-018637",
    "solicitation_number": "SPEFA5-26-T-0169",
    "nsn": "5305-01-234-5678",
    "part_number": "PN-12345",
    "nomenclature": "SCREW, MACHINE",
    "quantity": "100",
    "unit": "EA",
    "unit_price": 12.50,
    "total_price": 1250.00,
    "minimum_order_qty": null,
    "total_shipping_weight": 12.5,
    "shipping_cost_to_company": 85.00,
    "payment_term": "1",
    "oem_delivery_days": 45,
    "tax": null,
    "packaging_cost": 25.00,
    "handling_fee": null,
    "insurance_cost": null,
    "customs_duty": null,
    "setup_cost": null,
    "minimum_order_charge": null,
    "rush_delivery_fee": null,
    "environmental_fee": null,
    "certification_cost": null,
    "documentation_fee": null,
    "oem_name": "Acme Corporation",
    "replied_email": "sales@acme.com",
    "confidence_score": 0.95,
    "extraction_notes": "All fields extracted successfully"
}}"""

        return prompt

    def _call_gpt4(self, prompt: str) -> Optional[str]:
        """Call chat completions API with the extraction prompt."""
        try:
            kwargs = build_chat_completion_kwargs(
                self.model,
                [
                    {
                        "role": "system",
                        "content": "You are a precise data extraction assistant. Always return valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=1500,
                timeout=self.timeout,
            )
            response = self.client.chat.completions.create(**kwargs)
            return response.choices[0].message.content

        except Exception as e:
            raise e

    def _parse_response(self, response: str, from_email: str) -> Dict:
        """Parse and validate GPT-4 response"""
        try:
            data = json.loads(response)

            # Ensure all expected fields exist
            extracted = {
                'rfq_unique_id': data.get('rfq_unique_id') or '',
                'solicitation_number': data.get('solicitation_number') or '',
                'nsn': data.get('nsn') or '',
                'nomenclature': data.get('nomenclature') or '',
                'quantity': data.get('quantity') or '',
                'unit': data.get('unit') or '',
                'unit_price': self._parse_price(data.get('unit_price')),
                'total_price': self._parse_price(data.get('total_price')),
                'minimum_order_qty': self._parse_price(data.get('minimum_order_qty')),
                'total_shipping_weight': self._parse_price(data.get('total_shipping_weight')),
                'shipping_cost_to_company': self._parse_price(data.get('shipping_cost_to_company')),
                'payment_term': self._normalize_payment_term(data.get('payment_term')),
                'oem_delivery_days': self._parse_int(data.get('oem_delivery_days')),
                'tax': self._parse_price(data.get('tax')),
                'packaging_cost': self._parse_price(data.get('packaging_cost')),
                'handling_fee': self._parse_price(data.get('handling_fee')),
                'insurance_cost': self._parse_price(data.get('insurance_cost')),
                'customs_duty': self._parse_price(data.get('customs_duty')),
                'setup_cost': self._parse_price(data.get('setup_cost')),
                'minimum_order_charge': self._parse_price(data.get('minimum_order_charge')),
                'rush_delivery_fee': self._parse_price(data.get('rush_delivery_fee')),
                'environmental_fee': self._parse_price(data.get('environmental_fee')),
                'certification_cost': self._parse_price(data.get('certification_cost')),
                'documentation_fee': self._parse_price(data.get('documentation_fee')),
                'oem_name': data.get('oem_name') or '',
                'replied_email': data.get('replied_email') or '',
                'confidence_score': data.get('confidence_score'),
                'extraction_notes': data.get('extraction_notes') or ''
            }

            # If replied_email is missing, try to extract from from_email
            if not extracted['replied_email'] and from_email:
                extracted['replied_email'] = self._extract_email_address(
                    from_email)

            # If oem_name is missing, try to extract from from_email
            if not extracted['oem_name'] and from_email:
                extracted['oem_name'] = self._extract_company_name(from_email)

            return extracted

        except json.JSONDecodeError as e:
            print(f"  [ERROR] Failed to parse GPT-4 response as JSON: {e}")
            return None
        except Exception as e:
            print(f"  [ERROR] Error parsing GPT-4 response: {e}")
            return None

    def _parse_price(self, price_value) -> Optional[float]:
        """Parse price value to float"""
        if price_value is None:
            return None

        try:
            if isinstance(price_value, (int, float)):
                return float(price_value)

            if isinstance(price_value, str):
                # Remove currency symbols and commas
                cleaned = price_value.replace('$', '').replace(
                    ',', '').replace('USD', '').strip()
                return float(cleaned) if cleaned else None

            return None
        except:
            return None

    def _parse_int(self, value) -> Optional[int]:
        """Parse integer values from model output."""
        if value is None:
            return None
        try:
            if isinstance(value, int):
                return value
            if isinstance(value, float):
                return int(round(value))
            if isinstance(value, str):
                import re
                match = re.search(r'\d+', value.replace(',', ''))
                return int(match.group(0)) if match else None
            return None
        except:
            return None

    def _normalize_payment_term(self, value) -> str:
        """Normalize extracted payment terms to existing DLA field 025 codes."""
        if value is None:
            return ''
        text = str(value).strip().lower()
        if not text:
            return ''

        direct_codes = {'1', '10', '3', '6', '8'}
        if text in direct_codes:
            return text

        compact = text.replace(' ', '').replace('-', '').replace('_', '')
        if 'net30' in compact or compact in {'30days', 'duein30days'}:
            return '1'
        if '2%10' in compact or '2percent10' in compact:
            return '10'
        if ('1/2%20' in compact or '.5%20' in compact or '0.5%20' in compact or
                'half%20' in compact or 'halfpercent20' in compact):
            return '3'
        if ('1/2%10' in compact or '.5%10' in compact or '0.5%10' in compact or
                'half%10' in compact or 'halfpercent10' in compact):
            return '6'
        if ('1/4%20' in compact or '.25%20' in compact or '0.25%20' in compact or
                'quarter%20' in compact or 'quarterpercent20' in compact):
            return '8'
        return ''

    def _extract_email_address(self, from_email: str) -> str:
        """Extract email address from 'Name <email@example.com>' format"""
        import re

        # Try to find email in angle brackets
        match = re.search(r'<([^>]+)>', from_email)
        if match:
            return match.group(1).strip()

        # Try to find email pattern
        match = re.search(r'[\w\.-]+@[\w\.-]+\.\w+', from_email)
        if match:
            return match.group(0)

        return from_email.strip()

    def _extract_company_name(self, from_email: str) -> str:
        """Extract company name from 'Company Name <email@example.com>' format"""
        import re

        # Try to find name before angle bracket
        match = re.search(r'([^<]+)<', from_email)
        if match:
            return match.group(1).strip()

        # Try to extract from email domain
        email_match = re.search(r'@([\w\.-]+)', from_email)
        if email_match:
            domain = email_match.group(1)
            company = domain.split('.')[0]
            return company.upper()

        return ''


def extract_rfq_data_with_gpt4(email_data: Dict) -> Optional[Dict]:
    """
    Convenience function to extract RFQ data using GPT-4

    Args:
        email_data: Dict with 'subject', 'body', 'from_email'

    Returns:
        Dict with extracted data or None if extraction failed
    """
    try:
        extractor = GPT4EmailExtractor()
        return extractor.extract_rfq_data(email_data)
    except Exception as e:
        print(f"  [ERROR] GPT-4 extraction failed: {e}")
        return None

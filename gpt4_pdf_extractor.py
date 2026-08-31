"""
GPT-4 PDF Data Extractor for Solicitation Documents

This module uses Azure OpenAI's GPT-4o model to extract structured data from DLA solicitation PDFs.
Specifically targets fields that are difficult to extract with regex/table parsing:
- Solicitation Line Number (PRLI)
- Procurement History (CAGE, Contract Number, Quantity, Unit Cost, AWD Date, Surplus Material)

Features:
- Handles various PDF formats and layouts
- Understands context and table structures
- Extracts data even with formatting variations
- Supports both Azure OpenAI and standard OpenAI API
"""

import json
import time
from typing import Dict, Optional, List
from dataclasses import dataclass, asdict
from django.conf import settings

from azure_openai_client import build_chat_completion_kwargs, create_chat_client


@dataclass
class PDFExtraction:
    """Structured data extracted from solicitation PDF"""
    # Unit of Issue
    unit_of_issue: Optional[str] = None
    
    # Line Number
    solicitation_line_number: Optional[str] = None
    
    # Procurement History (list of records)
    procurement_history: List[Dict] = None
    
    # Metadata
    confidence_score: Optional[float] = None
    extraction_notes: Optional[str] = None
    
    def __post_init__(self):
        if self.procurement_history is None:
            self.procurement_history = []
    
    def to_dict(self) -> Dict:
        """Convert to dictionary"""
        return asdict(self)


class GPT4PDFExtractor:
    """Extract specific fields from PDFs using GPT-4 (Azure OpenAI or OpenAI)"""

    def __init__(self):
        """Initialize GPT extractor (Azure OpenAI, Foundry v1, or OpenAI)."""
        self.use_azure = settings.USE_AZURE_OPENAI
        self.max_retries = settings.OPENAI_MAX_RETRIES
        self.timeout = settings.OPENAI_TIMEOUT
        self.client, self.model, self.client_mode = create_chat_client()

    def extract_pdf_fields(self, pdf_text: str, max_pages: int = 15, extract_unit: bool = False) -> Optional[Dict]:
        """
        Extract unit of issue, solicitation line number, and procurement history from PDF text using GPT-4

        Args:
            pdf_text: Extracted text from PDF (can be full text or first N pages)
            max_pages: Maximum number of pages to process (for context)
            extract_unit: Whether to extract unit of issue (default: False for backward compatibility)

        Returns:
            Dict with extracted data or None if extraction failed
        """
        # Truncate text if too long (to save tokens and stay within context limits)
        # Keep first ~50,000 characters which should cover first 15 pages
        if len(pdf_text) > 50000:
            pdf_text = pdf_text[:50000]
            print(f"  [GPT-4] Truncated PDF text to 50,000 characters for processing")

        # Build extraction prompt
        prompt = self._build_extraction_prompt(pdf_text, extract_unit=extract_unit)

        # Call GPT-4 with retry logic
        print(f"  [GPT-4] Starting extraction (attempt 1/{self.max_retries})...")
        print(f"  [GPT-4] PDF text length: {len(pdf_text)} characters")
        print(f"  [GPT-4] Extract unit: {extract_unit}")
        
        for attempt in range(self.max_retries):
            try:
                response = self._call_gpt4(prompt)

                if response:
                    print(f"  [GPT-4] Received response from API (length: {len(response)} chars)")
                    # Parse and validate response
                    extracted_data = self._parse_response(response)
                    if extracted_data:
                        print(f"  [GPT-4] Parsed successfully:")
                        print(f"    - solicitation_line_number: {extracted_data.get('solicitation_line_number')}")
                        print(f"    - procurement_history: {len(extracted_data.get('procurement_history', []))} records")
                        print(f"    - confidence_score: {extracted_data.get('confidence_score')}")
                    return extracted_data
                else:
                    print(f"  [GPT-4] No response from API on attempt {attempt + 1}")

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
                    print(f"  [ERROR] Unexpected error in GPT-4 extraction: {e}")
                    return None

        return None

    def _build_extraction_prompt(self, pdf_text: str, extract_unit: bool = False) -> str:
        """Build the extraction prompt for GPT-4"""
        
        # Define newline variable outside f-string to avoid backslash in expression
        newline = "\n"
        indent_newline = "\n    "
        
        unit_extraction_section = ""
        if extract_unit:
            unit_extraction_section = """1. unit_of_issue: The unit of issue (also called Unit, U/I, or Unit of Measure)
   - Look for patterns like: "UNIT:", "U/I:", "UNIT OF ISSUE:", "UI:", "UNIT OF MEASURE:"
   - Common values are 2-letter codes like: EA, BOX, PK, PR, DZ, FT, IN, LB, OZ, etc.
   - May appear in tables with headers like "UNIT", "UI", "U/I", "UNIT OF ISSUE"
   - Usually found near quantity information
   - Must be a valid 2-letter unit code (check against standard DLA unit codes)
   - Return null if not found

"""
        
        # Build conditional strings outside f-string
        unit_rule_text = "- For unit_of_issue: Extract only the 2-letter unit code (e.g., EA, BOX, PK). Must be uppercase. Return null if not found or invalid." + newline if extract_unit else ""
        # JSON format line - includes proper indentation
        if extract_unit:
            json_unit_line = '    "unit_of_issue": "EA",' + newline
        else:
            json_unit_line = ""
        
        prompt = f"""You are extracting specific data from a DLA (Defense Logistics Agency) solicitation PDF document.

PDF TEXT CONTENT:
{pdf_text}

EXTRACT THE FOLLOWING FIELDS:

{unit_extraction_section}{"2" if extract_unit else "1"}. solicitation_line_number: The solicitation line number (also called PRLI - Purchase Request Line Item)
   - Look for patterns like: "LINE NO:", "LINE NUMBER:", "PRLI:", "PR LI:", "LINE ITEM:", "CLIN"
   - Usually a numeric value (e.g., "001", "1", "0001")
   - May appear in tables with headers like "CLIN", "PR", "PRLI", "LINE"
   - If multiple line numbers exist, extract the FIRST/PRIMARY one
   - Return null if not found

{"3" if extract_unit else "2"}. procurement_history: A list of procurement history records (maximum 4 records)
   - Look for a table with headers containing: "CAGE", "Contract Number", "Quantity", "Unit Cost", "AWD Date", "Surplus Material"
   - Extract the FIRST 4 records from this table
   - Each record should have:
     * cage: CAGE code (5 characters, alphanumeric)
     * contract_number: Contract number or award number
     * quantity: Quantity value
     * unit_cost: Unit cost (numeric value, remove currency symbols)
     * awd_date: Award date (if available)
     * surplus_material: Surplus material indicator (if available)
   - Return empty list [] if no procurement history table found
   - Only include records that have at least CAGE and Contract Number

{"4" if extract_unit else "3"}. confidence_score: Your confidence in the extraction (0.0 to 1.0)
   - 0.9-1.0: Both fields found with high certainty
   - 0.7-0.9: One or both fields found with some uncertainty
   - 0.5-0.7: Fields partially found or uncertain
   - Below 0.5: Very limited data extracted

{"5" if extract_unit else "4"}. extraction_notes: Any notes about the extraction
   - Note which fields were found/missing
   - Note any assumptions or variations in format
   - Note if procurement history table was found but empty

IMPORTANT RULES:
{unit_rule_text}- For solicitation_line_number: Extract only the numeric value, not labels
- For procurement_history: Extract maximum 4 records (the first 4 if more exist)
- For unit_cost: Extract numeric value only (remove $, commas, currency codes)
- If a field is not found, use null for line_number or unit_of_issue, or empty list [] for procurement_history
- Be flexible with table formats and variations
- Look for tables even if headers are slightly different (e.g., "CONTRACT" vs "CONTRACT NUMBER")
- Handle cases where data spans multiple pages

Return ONLY valid JSON in this exact format:
{{
{json_unit_line}    "solicitation_line_number": "001",
    "procurement_history": [
        {{
            "cage": "1T615",
            "contract_number": "SPE7M5-24-C-0001",
            "quantity": "1000",
            "unit_cost": "12.50",
            "awd_date": "01/15/2024",
            "surplus_material": "N"
        }},
        {{
            "cage": "2A345",
            "contract_number": "SPE7M5-23-C-0050",
            "quantity": "500",
            "unit_cost": "15.00",
            "awd_date": "12/10/2023",
            "surplus_material": "Y"
        }}
    ],
    "confidence_score": 0.95,
    "extraction_notes": "Both fields extracted successfully. Found 2 procurement history records."
}}"""

        return prompt

    def _call_gpt4(self, prompt: str) -> Optional[str]:
        """Call chat completions API with the extraction prompt."""
        try:
            print(
                f"  [GPT-4] Calling API (model: {self.model}, mode: {self.client_mode})..."
            )
            kwargs = build_chat_completion_kwargs(
                self.model,
                [
                    {
                        "role": "system",
                        "content": "You are a precise data extraction assistant specialized in parsing government procurement documents. Always return valid JSON."
                    },
                    {
                        "role": "user",
                        "content": prompt
                    }
                ],
                max_tokens=2000,
                timeout=self.timeout,
            )
            response = self.client.chat.completions.create(**kwargs)

            content = response.choices[0].message.content
            print(f"  [GPT-4] API call successful")
            return content

        except Exception as e:
            print(f"  [ERROR] GPT-4 API call failed: {type(e).__name__}: {e}")
            import traceback
            print(f"  [ERROR] Traceback: {traceback.format_exc()}")
            return None

    def _parse_response(self, response: str) -> Optional[Dict]:
        """Parse GPT-4 response and validate extracted data"""
        try:
            # Parse JSON response
            data = json.loads(response)

            # Validate and clean data
            result = {
                'unit_of_issue': data.get('unit_of_issue'),
                'solicitation_line_number': data.get('solicitation_line_number'),
                'procurement_history': data.get('procurement_history', []),
                'confidence_score': data.get('confidence_score'),
                'extraction_notes': data.get('extraction_notes', '')
            }
            
            # Clean and validate unit of issue
            if result['unit_of_issue']:
                result['unit_of_issue'] = str(result['unit_of_issue']).strip().upper()
                # Validate it's a 2-letter code
                if len(result['unit_of_issue']) != 2 or not result['unit_of_issue'].isalpha():
                    print(f"  [WARN] Invalid unit code format: {result['unit_of_issue']}, setting to null")
                    result['unit_of_issue'] = None

            # Validate procurement_history structure
            if result['procurement_history']:
                print(f"  [GPT-4] Found {len(result['procurement_history'])} procurement_history records in response")
                validated_history = []
                for idx, record in enumerate(result['procurement_history'][:4]):  # Limit to 4 records
                    if isinstance(record, dict):
                        validated_record = {
                            'cage': str(record.get('cage', '')).strip(),
                            'contract_number': str(record.get('contract_number', '')).strip(),
                            'quantity': str(record.get('quantity', '')).strip(),
                            'unit_cost': str(record.get('unit_cost', '')).strip(),
                            'awd_date': str(record.get('awd_date', '')).strip(),
                            'surplus_material': str(record.get('surplus_material', '')).strip()
                        }
                        # Only include if has at least CAGE and Contract Number
                        if validated_record['cage'] and validated_record['contract_number']:
                            validated_history.append(validated_record)
                            print(f"  [GPT-4] Validated record {idx+1}: CAGE={validated_record['cage']}, Contract={validated_record['contract_number'][:20]}")
                        else:
                            print(f"  [GPT-4] Record {idx+1} filtered out (missing CAGE or Contract Number): CAGE={validated_record['cage']}, Contract={validated_record['contract_number']}")
                    else:
                        print(f"  [GPT-4] Record {idx+1} is not a dict, skipping")
                
                result['procurement_history'] = validated_history
                print(f"  [GPT-4] Final validated procurement_history: {len(validated_history)} records")

            # Clean line number
            if result['solicitation_line_number']:
                result['solicitation_line_number'] = str(result['solicitation_line_number']).strip()
            else:
                print(f"  [GPT-4] solicitation_line_number is null/empty in response")

            # Check if procurement_history is empty
            if not result['procurement_history']:
                print(f"  [GPT-4] procurement_history is empty in response")

            return result

        except json.JSONDecodeError as e:
            print(f"  [ERROR] Failed to parse GPT-4 JSON response: {e}")
            print(f"  [DEBUG] Response was: {response[:500]}")
            return None
        except Exception as e:
            print(f"  [ERROR] Error parsing GPT-4 response: {type(e).__name__}: {e}")
            import traceback
            print(f"  [ERROR] Traceback: {traceback.format_exc()}")
            return None


def extract_pdf_fields_with_gpt4(pdf_text: str, extract_unit: bool = False) -> Optional[Dict]:
    """
    Convenience function to extract PDF fields using GPT-4

    Args:
        pdf_text: Extracted text from PDF
        extract_unit: Whether to extract unit of issue (default: False)

    Returns:
        Dict with extracted data or None if extraction failed
    """
    try:
        extractor = GPT4PDFExtractor()
        return extractor.extract_pdf_fields(pdf_text, extract_unit=extract_unit)
    except Exception as e:
        print(f"  [ERROR] GPT-4 PDF extractor initialization failed: {e}")
        return None


"""
Helpers for RFQ ID preview/sample strings without incrementing sequence or saving.
"""
from datetime import datetime

from .models import RFQIDTemplate


def build_sample_rfq_id_for_user(user, oem_cage_code='ABC12', solicitation_id=1):
    """
    Build a sample RFQ ID using the user's saved RFQIDTemplate (or defaults).
    Mirrors preview_rfq_id / generate_rfq_id logic but uses sequence 1 in-memory only.
    """
    template, _ = RFQIDTemplate.objects.get_or_create(user=user)
    if not template.components:
        default = RFQIDTemplate.get_default_template()
        components = default['components']
        separator = default['separator']
        date_format = default['date_format']
        custom_text = default['custom_text']
        sequence_padding = default['sequence_padding']
    else:
        components = template.components
        separator = template.separator
        date_format = template.date_format
        custom_text = template.custom_text
        sequence_padding = template.sequence_padding

    parts = []
    for comp_obj in components:
        component = comp_obj.get('component')
        if component == 'company_initial':
            if user.company_initial:
                parts.append(user.company_initial.upper())
        elif component == 'dla':
            parts.append('DLA')
        elif component == 'date':
            parts.append(RFQIDTemplate._format_date(datetime.now(), date_format))
        elif component == 'cage_code':
            if oem_cage_code:
                parts.append(oem_cage_code.upper())
            else:
                parts.append(f'SOL{solicitation_id}')
        elif component == 'sequence':
            parts.append(str(1).zfill(int(sequence_padding)))
        elif component == 'custom_text':
            if custom_text:
                parts.append(custom_text)

    return separator.join(parts)

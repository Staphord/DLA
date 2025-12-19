"""
Utility functions for exporting solicitation data to DLA format text files.
Generates comma-separated text files with 121 fields in exact positions.
"""
import csv
import os
from datetime import datetime
from io import StringIO
from django.conf import settings
from django.db.models import Prefetch
from .models import ExportFieldDefinition, UserExportConfiguration, Solicitation, RfqReplyExportOverride


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

    # Ensure we have exactly 121 fields
    while len(values) < 121:
        values.append("")

    # Convert to CSV format with proper quoting
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL)
    writer.writerow(values)

    # Return the line without the trailing newline
    return output.getvalue().strip()


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

    return '\n'.join(lines)


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
        3: 'is_set_aside',  # Small Business Set Aside Indicator (auto: True→"A", False→"N")
        5: 'return_by_date',  # Return By Date
        6: 'cage',  # Quoter CAGE Code
        7: 'cage',  # Quote for CAGE Code
        32: 'deliver_fob',  # FOB Point (auto: destination→"D", origin→"O")
        36: 'inspection_point',  # Inspection Point Code (auto: destination→"D", origin→"O")
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
        3: 'rfq.solicitation.is_set_aside',  # Small Business Set Aside Indicator (auto: True→"A", False→"N")
        5: 'received_date',  # Return By Date (use received_date)
        6: 'user.cage',  # Quoter CAGE Code (from user)
        7: 'user.cage',  # Quote for CAGE Code (from user)
        32: 'rfq.solicitation.deliver_fob',  # FOB Point (auto: destination→"D", origin→"O")
        36: 'rfq.solicitation.inspection_point',  # Inspection Point Code (auto: destination→"D", origin→"O")
        44: '',  # Solicitation Line Number
        46: '',  # Purchase Request Number
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
    with open(full_path, 'w', encoding='utf-8') as f:
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

    # Generate raw values for all 121 positions
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
    # Item 19 – Joint Venture Remarks (position 19) depends on Item 18 – Joint Venture (position 18):
    # - If position 18 != "JV"  → position 19 must be blank.
    # - If position 18 == "JV"  → position 19 may be populated by the user/config.
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

    # Item 27 – Days Quote Valid depends on Item 2 – Solicitation Type Indicator
    # and Item 24 – Bid Type Code:
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

    # Item 28 – Meets Packaging Requirement (Accept Packaging)
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

    # Items 29–31 – BOA/FSS/BPA logic
    # Item 29 – BOA/FSS/BPA code (NAP, FSS, BOA, BPA)
    # Item 30 – BOA/FSS/BPA Contract Number
    # Item 31 – BOA/FSS/BPA Contract Expiration Date
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

    # For RFQ replies, business decision: always export FOB Point (32) and
    # Inspection Point Code (36) as "D" (Destination), regardless of what's
    # stored on the Solicitation or in user mappings.
    try:
        # Positions are 1-based; 32 -> index 31, 36 -> index 35
        if len(values) >= 32:
            values[31] = "D"  # FOB Point
        if len(values) >= 36:
            values[35] = "D"  # Inspection Point Code
    except Exception:
        # Fail-safe: never break export because of conditional logic
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
    
    # Check each mandatory field
    for field_def in mandatory_fields:
        position = field_def.position
        # Position is 1-based, values list is 0-based
        value_index = position - 1
        
        if value_index < len(values):
            value = values[value_index]
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
    
    # Then, apply per-RFQ overrides (if any exist)
    try:
        override = getattr(rfq_reply, 'export_override', None)
        if override and override.data and len(override.data) == 121:
            # Apply overrides: use override value if it's not empty, otherwise keep global config value
            for i in range(121):
                override_value = override.data[i]
                # Only use override if it has a non-empty value
                if override_value and (not isinstance(override_value, str) or override_value.strip()):
                    values[i] = override_value
    except Exception:
        # If there's any issue with override, just use the global config values
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

    # Convert to CSV format with proper quoting (all fields quoted like sample.txt)
    output = StringIO()
    writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator='')
    writer.writerow(values)

    # Get the line and ensure it's complete
    line = output.getvalue()

    # Verify we have exactly 120 commas (for 121 fields)
    comma_count = line.count(',')
    if comma_count != 120:
        # If we don't have the right number of commas, something went wrong
        # Rebuild the line manually to ensure completeness
        quoted_values = [f'"{str(v)}"' for v in values]
        line = ','.join(quoted_values)

    return line


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

        output = StringIO()
        writer = csv.writer(output, quoting=csv.QUOTE_ALL, lineterminator='')
        writer.writerow(values)
        line = output.getvalue()

        # Verify line has exactly 121 fields (120 commas)
        comma_count = line.count(',')
        if comma_count != 120:
            # If line is incomplete, pad with empty fields
            current_fields = line.split(',')
            while len(current_fields) < 121:
                current_fields.append('""')
            line = ','.join(current_fields)
        lines.append(line)

    # Join with newlines and ensure file ends with newline
    content = '\n'.join(lines)
    if content and not content.endswith('\n'):
        content += '\n'
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
        with open(full_path, 'w', encoding='utf-8') as f:
            f.write(content)
        # Count exported RFQs (lines in content)
        exported_count = len([line for line in content.split('\n') if line.strip()])
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

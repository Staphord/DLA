from django.contrib import admin
from .models import (
    ExportFieldDefinition,
    UserExportConfiguration,
    RfqReply
)


admin.site.site_header = "Gilgal Tech Administration"
admin.site.site_title = "Gilgal Tech Administration"
admin.site.index_title = "Gilgal Tech Administrationd"


@admin.register(ExportFieldDefinition)
class ExportFieldDefinitionAdmin(admin.ModelAdmin):
    list_display = [
        'position',
        'column_name',
        'quote_level',
        'field_type',
        'max_length',
        'may_affect_bid_type'
    ]
    list_filter = ['field_type', 'quote_level', 'may_affect_bid_type']
    search_fields = ['column_name', 'definition', 'validation_rules']
    ordering = ['position']
    readonly_fields = ['position']

    fieldsets = (
        ('Basic Information', {
            'fields': ('position', 'column_name', 'quote_level', 'field_type')
        }),
        ('Field Properties', {
            'fields': ('max_length', 'default_value', 'may_affect_bid_type', 'predefined_choices')
        }),
        ('Documentation', {
            'fields': ('definition', 'validation_rules'),
            'classes': ('collapse',)
        }),
    )


@admin.register(UserExportConfiguration)
class UserExportConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        'user',
        'field_position',
        'field_name',
        'is_enabled',
        'source_field',
        'custom_value',
        'updated_at'
    ]
    list_filter = ['is_enabled', 'user', 'field_definition__field_type']
    search_fields = [
        'user__username',
        'field_definition__column_name',
        'source_field',
        'custom_value'
    ]
    ordering = ['user', 'field_definition__position']

    fieldsets = (
        ('User & Field', {
            'fields': ('user', 'field_definition', 'is_enabled')
        }),
        ('Mapping Configuration', {
            'fields': ('source_field', 'custom_value')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    readonly_fields = ['created_at', 'updated_at']

    def field_position(self, obj):
        return obj.field_definition.position
    field_position.short_description = 'Position'
    field_position.admin_order_field = 'field_definition__position'

    def field_name(self, obj):
        return obj.field_definition.column_name
    field_name.short_description = 'Field Name'
    field_name.admin_order_field = 'field_definition__column_name'


@admin.register(RfqReply)
class RfqReplyAdmin(admin.ModelAdmin):
    list_display = [
        'id',
        'user',
        'oem_name',
        'rfq_unique_id',
        'solicitation_number',
        'received_date',
        'final_price',
        'has_pricing'
    ]
    list_filter = ['user', 'received_date']
    search_fields = [
        'rfq_unique_id',
        'solicitation_number',
        'oem_name',
        'replied_email',
        'nsn',
        'part_number'
    ]
    ordering = ['-received_date', '-created_at']
    readonly_fields = ['created_at', 'updated_at', 'email_message_id']

    fieldsets = (
        ('Basic Information', {
            'fields': ('user', 'rfq', 'rfq_unique_id', 'solicitation_number')
        }),
        ('Product Details', {
            'fields': ('nsn', 'part_number', 'nomenclature', 'quantity', 'unit')
        }),
        ('Pricing', {
            'fields': ('unit_price', 'total_price', 'final_price')
        }),
        ('Vendor Information', {
            'fields': ('oem_name', 'replied_email')
        }),
        ('Email Details', {
            'fields': ('email_subject', 'email_body', 'received_date', 'email_message_id'),
            'classes': ('collapse',)
        }),
        ('Attachments', {
            'fields': ('has_attachments', 'attachment_files'),
            'classes': ('collapse',)
        }),
        ('Notes & Metadata', {
            'fields': ('notes', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

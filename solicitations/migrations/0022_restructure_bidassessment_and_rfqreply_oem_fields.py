# Generated manually on 2026-04-23

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0021_bidassessment_calculated_fields'),
    ]

    operations = [
        # ── RfqReply: add OEM Pricing fields ──────────────────────────────────
        migrations.AddField(
            model_name='rfqreply',
            name='minimum_order_qty',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='other_oem_charges',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='total_shipping_weight',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='shipping_cost_to_company',
            field=models.DecimalField(blank=True, decimal_places=2, help_text='Shipping cost from OEM to company', max_digits=12, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='payment_term',
            field=models.CharField(blank=True, default='1', max_length=20),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='package_and_pres_mtd',
            field=models.DecimalField(blank=True, decimal_places=4, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='oem_validity_days',
            field=models.IntegerField(blank=True, default=30, null=True),
        ),
        migrations.AddField(
            model_name='rfqreply',
            name='oem_delivery_days',
            field=models.IntegerField(blank=True, null=True),
        ),

        # ── BidAssessment: rename vertex_* → company_* ────────────────────────
        migrations.RenameField(
            model_name='bidassessment',
            old_name='vertex_adjusted_rate',
            new_name='company_adjusted_rate',
        ),
        migrations.RenameField(
            model_name='bidassessment',
            old_name='vertex_delivery_days',
            new_name='company_delivery_days',
        ),
        migrations.RenameField(
            model_name='bidassessment',
            old_name='vertex_origin_inspection',
            new_name='company_origin_inspection',
        ),
        migrations.RenameField(
            model_name='bidassessment',
            old_name='vertex_validity_days',
            new_name='company_validity_days',
        ),
        migrations.RenameField(
            model_name='bidassessment',
            old_name='vertex_calculated_rate',
            new_name='company_calculated_rate',
        ),

        # ── BidAssessment: remove fields that moved to RfqReply ───────────────
        migrations.RemoveField(model_name='bidassessment', name='minimum_order_qty'),
        migrations.RemoveField(model_name='bidassessment', name='other_oem_charges'),
        migrations.RemoveField(model_name='bidassessment', name='total_shipping_weight'),
        migrations.RemoveField(model_name='bidassessment', name='shipping_cost_to_vtx'),
        migrations.RemoveField(model_name='bidassessment', name='term'),
        migrations.RemoveField(model_name='bidassessment', name='package_and_pres_mtd'),
        migrations.RemoveField(model_name='bidassessment', name='oem_validity_days'),
        migrations.RemoveField(model_name='bidassessment', name='oem_delivery_days'),
        migrations.RemoveField(model_name='bidassessment', name='oem_origin_inspection'),
        migrations.RemoveField(model_name='bidassessment', name='oem_unit_rate'),
        migrations.RemoveField(model_name='bidassessment', name='shipping_cost_to_destination'),
        migrations.RemoveField(model_name='bidassessment', name='shipping_cost_to_manufacturer'),
        migrations.RemoveField(model_name='bidassessment', name='oem_origin_plus5'),
        migrations.RemoveField(model_name='bidassessment', name='total_material_cost'),

        # ── BidAssessment: add new calculated/pricing fields ──────────────────
        migrations.AddField(
            model_name='bidassessment',
            name='oem_credit_card_charge_pct',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=6, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='oem_subtotal',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='oem_total',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='interest_cod_cc',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='interest_50_50',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='interest_cia_prepay',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),
        migrations.AddField(
            model_name='bidassessment',
            name='admin_10pct_oem_origin',
            field=models.DecimalField(blank=True, decimal_places=2, max_digits=14, null=True),
        ),

        # ── BidAssessment: fix company_delivery_days default ──────────────────
        migrations.AlterField(
            model_name='bidassessment',
            name='company_delivery_days',
            field=models.IntegerField(blank=True, default=30, null=True),
        ),
    ]

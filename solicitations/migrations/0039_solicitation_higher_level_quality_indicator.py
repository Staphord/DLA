# Generated for Solicitation.higher_level_quality_indicator (DLA export field 117).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("solicitations", "0038_alter_rfqreply_payment_term_default"),
    ]

    operations = [
        migrations.AddField(
            model_name="solicitation",
            name="higher_level_quality_indicator",
            field=models.CharField(
                blank=True,
                choices=[
                    ("", "-- Not Set --"),
                    ("N", "N - Not Applicable"),
                    ("8", "8 - SAE AS9100"),
                    ("7", "7 - ISO 9001:2015"),
                    ("6", "6 - SAE AS9003 or ISO 9001 tailored to meet SAE AS9003"),
                ],
                default="",
                help_text="Higher-Level Quality Indicator (DLA export field 117)",
                max_length=1,
            ),
        ),
    ]

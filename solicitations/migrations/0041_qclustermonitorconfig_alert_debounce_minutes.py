from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0040_qclustermonitorconfig'),
    ]

    operations = [
        migrations.AddField(
            model_name='qclustermonitorconfig',
            name='alert_debounce_minutes',
            field=models.PositiveSmallIntegerField(
                default=0,
                help_text='Minimum minutes between failure alert emails. Use 0 while testing to email on every failure.',
            ),
        ),
    ]

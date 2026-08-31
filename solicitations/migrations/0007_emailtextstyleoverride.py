from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        ('solicitations', '0006_emailtemplateconfig_header_text_color'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailTextStyleOverride',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('selected_text', models.CharField(help_text='Exact text to match (as plain text as shown in preview).', max_length=500)),
                ('font_family', models.CharField(default='Arial, sans-serif', max_length=100)),
                ('font_size', models.CharField(default='13px', max_length=10)),
                ('color', models.CharField(default='#000000', help_text='Hex color (e.g. #000000)', max_length=7)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('template_config', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='text_style_overrides', to='solicitations.emailtemplateconfig')),
            ],
            options={
                'verbose_name': 'Email Text Style Override',
                'verbose_name_plural': 'Email Text Style Overrides',
                'constraints': [
                    models.UniqueConstraint(fields=('template_config', 'selected_text'), name='unique_text_style_override_per_config'),
                ],
            },
        ),
    ]

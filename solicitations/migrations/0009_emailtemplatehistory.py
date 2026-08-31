from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('solicitations', '0008_alter_emailtemplateconfig_layout_style'),
    ]

    operations = [
        migrations.CreateModel(
            name='EmailTemplateHistory',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('snapshot', models.JSONField(blank=True, default=dict)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='email_template_histories', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'verbose_name': 'Email Template History',
                'verbose_name_plural': 'Email Template Histories',
                'indexes': [
                    models.Index(fields=['user'], name='solicitatio_user_id_31fd40_idx'),
                ],
            },
        ),
    ]


from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_alter_user_options'),
    ]

    operations = [
        migrations.AddField(
            model_name='user',
            name='is_premium',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='user',
            name='tier',
            field=models.CharField(
                choices=[
                    ('free', 'Free'),
                    ('pro', 'Pro'),
                    ('enterprise', 'Enterprise'),
                ],
                default='free',
                max_length=20,
            ),
        ),
    ]

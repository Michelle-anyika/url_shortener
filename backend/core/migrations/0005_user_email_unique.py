from django.db import migrations, models


class Migration(migrations.Migration):
    """Make email unique and align tier choices with module-7 constants."""

    dependencies = [
        ('core', '0004_user_premium_tier'),
    ]

    operations = [
        migrations.AlterField(
            model_name='user',
            name='email',
            field=models.EmailField(blank=False, max_length=254, null=False, unique=True,
                                    verbose_name='email address'),
        ),
        migrations.AlterField(
            model_name='user',
            name='tier',
            field=models.CharField(
                choices=[
                    ('Free', 'Free'),
                    ('Premium', 'Premium'),
                    ('Admin', 'Admin'),
                ],
                default='Free',
                max_length=20,
            ),
        ),
    ]

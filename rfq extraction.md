# RFQ Reply Extraction - Integration Steps

## Quick Start Guide

Follow these steps to integrate the RFQ reply extraction feature into your Django application.

---

## Step 1: Run Migrations

First, create and apply the database migration for the `RfqReply` model:

```bash
# Create migration
python manage.py makemigrations

# Apply migration
python manage.py migrate
```

Expected output:
```
Migrations for 'solicitations':
  solicitations/migrations/0026_rfqreply.py
    - Create model RfqReply
```

---

## Step 2: Register Model in Django Admin

Add the `RfqReply` model to Django admin for easy viewing and management.

**Edit `solicitations/admin.py`:**

```python
from django.contrib import admin
from .models import RfqReply

@admin.register(RfqReply)
class RfqReplyAdmin(admin.ModelAdmin):
    list_display = [
        'rfq_id', 
        'oem_name', 
        'unit_price', 
        'total_price', 
        'received_date', 
        'status',
        'matched_rfq'
    ]
    list_filter = ['status', 'received_date', 'user']
    search_fields = ['rfq_id', 'solicitation_number', 'oem_name', 'replied_email', 'nsn']
    readonly_fields = ['email_message_id', 'created_at', 'updated_at']
    date_hierarchy = 'received_date'
    
    fieldsets = (
        ('RFQ Information', {
            'fields': ('user', 'rfq', 'rfq_id', 'solicitation_number', 'status')
        }),
        ('Item Details', {
            'fields': ('nsn', 'nomenclature', 'quantity', 'unit')
        }),
        ('Pricing', {
            'fields': ('unit_price', 'total_price')
        }),
        ('OEM Information', {
            'fields': ('oem_name', 'replied_email')
        }),
        ('Email Metadata', {
            'fields': ('email_subject', 'email_body', 'received_date', 'email_message_id'),
            'classes': ('collapse',)
        }),
        ('Attachments & Notes', {
            'fields': ('has_attachments', 'attachment_files', 'notes'),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def matched_rfq(self, obj):
        """Show if reply is matched to an RFQ"""
        if obj.rfq:
            return f"✓ {obj.rfq.unique_id}"
        return "✗ Not matched"
    matched_rfq.short_description = 'Matched RFQ'
    
    actions = ['mark_as_quoted', 'mark_as_declined']
    
    def mark_as_quoted(self, request, queryset):
        updated = queryset.update(status='quoted')
        self.message_user(request, f'{updated} replies marked as quoted')
    mark_as_quoted.short_description = 'Mark selected as quoted'
    
    def mark_as_declined(self, request, queryset):
        updated = queryset.update(status='declined')
        self.message_user(request, f'{updated} replies marked as declined')
    mark_as_declined.short_description = 'Mark selected as declined'
```

---

## Step 3: Configure User Email Settings

Each user needs email configuration before extraction can work.

### Option A: Via Django Admin

1. Go to: `http://localhost:8000/admin/solicitations/useremailconfig/`
2. Add new email config for user
3. Fill in SMTP and IMAP settings

### Option B: Via Custom View (Already exists)

1. Go to: `http://localhost:8000/solicitations/email-config/<user_id>/`
2. Fill in the form
3. Test connection

### Example Configuration (Gmail):

```
SMTP Host: smtp.gmail.com
SMTP Port: 587
Email User: user@gmail.com
Email Password: [App Password - NOT regular password]
From Email: user@gmail.com

IMAP Host: imap.gmail.com (or leave blank for auto-detect)
IMAP Port: 993
Save to Sent Folder: ✓ Enabled
```

**Important for Gmail users:**
- Must use App Password: https://support.google.com/accounts/answer/185833
- Enable IMAP in Gmail settings

---

## Step 4: Test the Extraction

Run the test script to verify everything works:

```bash
# Test for specific user
python test_email_extraction.py --user-id 1

# Run specific test
python test_email_extraction.py --user-id 1 --test connection
```

Expected output:
```
======================================================================
# RFQ REPLY EMAIL EXTRACTION - TEST SUITE
======================================================================

======================================================================
TESTING EMAIL CONFIGURATION
======================================================================
✓ User found: john (john@example.com)
✓ Email config found
  SMTP Host: smtp.gmail.com
  ...

======================================================================
TESTING IMAP CONNECTION
======================================================================
✓ IMAP connection successful!
✓ Inbox accessible: 1234 total messages

...

======================================================================
# TEST SUMMARY
======================================================================
✓ PASS - CONFIG
✓ PASS - CONNECTION
✓ PASS - SEARCH
✓ PASS - EXTRACTION
✓ PASS - EXISTING

✓ All tests passed! Ready to run extraction.
```

---

## Step 5: Run Extraction

### Method 1: Django Management Command

```bash
# Extract for specific user (last 30 days)
python manage.py extract_rfq_replies --user-id 1 --days 30

# Extract for all users (last 7 days)
python manage.py extract_rfq_replies --all-users --days 7
```

### Method 2: Standalone Script

```bash
# Extract for specific user
python extractRfqReplies.py --user-id 1 --days 30

# Extract for all users
python extractRfqReplies.py --all-users
```

### Method 3: Background Task (Django Q)

```python
from django_q.tasks import async_task

# Queue extraction task
task_id = async_task(
    'solicitations.tasks.extract_user_rfq_replies',
    user_id=1,
    days_back=30
)

print(f"Task queued: {task_id}")
```

---

## Step 6: View Extracted Replies

### Via Django Admin

1. Go to: `http://localhost:8000/admin/solicitations/rfqreply/`
2. View all extracted replies
3. Filter by user, status, date
4. Search by RFQ ID, OEM name, NSN

### Via Database Query

```python
from solicitations.models import RfqReply

# Get all replies for a user
replies = RfqReply.objects.filter(user_id=1).order_by('-received_date')

# Get matched replies
matched = RfqReply.objects.filter(rfq__isnull=False)

# Get replies with pricing
quoted = RfqReply.objects.filter(unit_price__isnull=False)

# Get recent replies
from django.utils import timezone
from datetime import timedelta

recent = RfqReply.objects.filter(
    received_date__gte=timezone.now() - timedelta(days=7)
)
```

---

## Step 7: Create Custom Views (Optional)

Add views to display RFQ replies in your UI.

**Add to `solicitations/views.py`:**

```python
from django.shortcuts import render
from django.contrib.auth.decorators import login_required
from .models import RfqReply

@login_required
def rfq_replies_list(request):
    """Display RFQ replies for current user"""
    replies = RfqReply.objects.filter(
        user=request.user
    ).select_related('rfq').order_by('-received_date')
    
    context = {
        'replies': replies,
        'total_count': replies.count(),
        'quoted_count': replies.filter(status='quoted').count(),
        'matched_count': replies.filter(rfq__isnull=False).count(),
    }
    
    return render(request, 'solicitations/rfq_replies_list.html', context)


@login_required
def rfq_reply_detail(request, reply_id):
    """Display single RFQ reply details"""
    reply = get_object_or_404(RfqReply, id=reply_id, user=request.user)
    
    context = {
        'reply': reply,
    }
    
    return render(request, 'solicitations/rfq_reply_detail.html', context)
```

**Add to `solicitations/urls.py`:**

```python
urlpatterns = [
    # ... existing patterns ...
    
    # RFQ Replies
    path('rfq-replies/', views.rfq_replies_list, name='rfq-replies-list'),
    path('rfq-reply/<int:reply_id>/', views.rfq_reply_detail, name='rfq-reply-detail'),
]
```

---

## Step 8: Setup Automated Extraction (Optional)

Schedule automatic daily extraction for all users.

**Add to `solicitations/tasks.py`:**

```python
from django_q.models import Schedule

def setup_daily_rfq_reply_extraction():
    """Setup daily RFQ reply extraction schedule"""
    Schedule.objects.update_or_create(
        name='daily_rfq_reply_extraction',
        defaults={
            'func': 'solicitations.tasks.extract_all_users_rfq_replies',
            'args': '30',  # days_back
            'schedule_type': Schedule.DAILY,
            'repeats': -1,  # Infinite
            'next_run': timezone.now().replace(hour=2, minute=0),  # 2 AM daily
        }
    )
```

**Call in `solicitations/apps.py`:**

```python
class SolicitationsConfig(AppConfig):
    # ... existing code ...
    
    def ready(self):
        # ... existing code ...
        
        # Setup RFQ reply extraction schedule
        try:
            from .tasks import setup_daily_rfq_reply_extraction
            setup_daily_rfq_reply_extraction()
        except Exception as e:
            print(f"Error setting up RFQ reply extraction schedule: {e}")
```

---

## Troubleshooting

### Issue: Migration fails

**Solution:**
```bash
# Check for conflicts
python manage.py makemigrations --dry-run

# If conflicts, merge migrations
python manage.py makemigrations --merge
```

### Issue: IMAP connection fails

**Solutions:**
1. Check email credentials
2. For Gmail: Use App Password
3. Enable IMAP in email provider settings
4. Check firewall/network

### Issue: No emails extracted

**Solutions:**
1. Increase `--days` parameter
2. Check email format matches patterns
3. Review email body in admin
4. Add custom extraction patterns

---

## Next Steps

1. ✅ Run migrations
2. ✅ Register in admin
3. ✅ Configure user email settings
4. ✅ Test extraction
5. ✅ Run extraction
6. ✅ View results
7. ⏭️ Create custom views (optional)
8. ⏭️ Setup automation (optional)

---

## Files Created

| File | Purpose |
|------|---------|
| `extractRfqReplies.py` | Main extraction script |
| `solicitations/management/commands/extract_rfq_replies.py` | Django management command |
| `test_email_extraction.py` | Test script |
| `RFQ_REPLY_EXTRACTION_GUIDE.md` | Complete documentation |
| `INTEGRATION_STEPS.md` | This file |

---

## Support

For issues:
1. Check logs in Django admin
2. Run test script
3. Review documentation
4. Check email configuration

---

**Ready to extract RFQ replies!** 🚀


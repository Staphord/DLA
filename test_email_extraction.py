"""
Test script for RFQ Reply Email Extraction

This script helps you test the email extraction functionality
before running it on production data.

Usage:
    python test_email_extraction.py
"""

import os
import sys
import django

# Setup Django
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'RFQ.settings')
django.setup()

from accounts.models import CustomUser
from solicitations.models import UserEmailConfig, RfqReply
from extractRfqReplies import RfqReplyExtractor


def test_email_config(user_id):
    """Test if user has valid email configuration"""
    print("\n" + "="*70)
    print("TESTING EMAIL CONFIGURATION")
    print("="*70)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        print(f"✓ User found: {user.username} ({user.email})")
        
        try:
            config = UserEmailConfig.objects.get(user=user, is_active=True)
            print(f"✓ Email config found")
            print(f"  SMTP Host: {config.email_host}")
            print(f"  SMTP Port: {config.email_port}")
            print(f"  Email User: {config.email_host_user}")
            print(f"  From Email: {config.default_from_email}")
            
            # IMAP settings
            if config.custom_imap_host:
                print(f"  IMAP Host: {config.custom_imap_host}")
            else:
                print(f"  IMAP Host: (auto-detected from SMTP)")
            print(f"  IMAP Port: {config.custom_imap_port}")
            
            return True
            
        except UserEmailConfig.DoesNotExist:
            print("✗ No email configuration found for this user")
            print("  Please configure email settings first:")
            print(f"  http://localhost:8000/solicitations/email-config/{user_id}/")
            return False
            
    except CustomUser.DoesNotExist:
        print(f"✗ User with ID {user_id} not found")
        return False


def test_imap_connection(user_id):
    """Test IMAP connection"""
    print("\n" + "="*70)
    print("TESTING IMAP CONNECTION")
    print("="*70)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        extractor = RfqReplyExtractor(user, days_back=7)
        
        if extractor.connect_to_inbox():
            print("✓ IMAP connection successful!")
            
            # Try to get inbox info
            try:
                status, messages = extractor.imap_connection.select('INBOX')
                if status == 'OK':
                    num_messages = int(messages[0])
                    print(f"✓ Inbox accessible: {num_messages} total messages")
                
                # Close connection
                extractor.imap_connection.close()
                extractor.imap_connection.logout()
                
            except Exception as e:
                print(f"⚠ Warning: Could not read inbox info: {e}")
            
            return True
        else:
            print("✗ IMAP connection failed")
            return False
            
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_email_search(user_id, days_back=7):
    """Test email search"""
    print("\n" + "="*70)
    print(f"TESTING EMAIL SEARCH (last {days_back} days)")
    print("="*70)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        extractor = RfqReplyExtractor(user, days_back=days_back)
        
        if not extractor.connect_to_inbox():
            print("✗ Could not connect to inbox")
            return False
        
        email_ids = extractor.search_rfq_reply_emails()
        
        print(f"✓ Found {len(email_ids)} emails in the last {days_back} days")
        
        if len(email_ids) > 0:
            print(f"\nSample email IDs (first 5):")
            for i, email_id in enumerate(email_ids[:5], 1):
                print(f"  {i}. {email_id.decode()}")
        
        # Close connection
        extractor.imap_connection.close()
        extractor.imap_connection.logout()
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def test_single_email_extraction(user_id, days_back=7):
    """Test extraction on a single email"""
    print("\n" + "="*70)
    print("TESTING SINGLE EMAIL EXTRACTION")
    print("="*70)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        extractor = RfqReplyExtractor(user, days_back=days_back)
        
        if not extractor.connect_to_inbox():
            print("✗ Could not connect to inbox")
            return False
        
        email_ids = extractor.search_rfq_reply_emails()
        
        if len(email_ids) == 0:
            print("⚠ No emails found to test")
            return False
        
        # Test first email
        print(f"\nTesting first email (ID: {email_ids[0].decode()})...")
        
        email_data = extractor.fetch_email_content(email_ids[0])
        
        if email_data:
            print(f"\n✓ Email fetched successfully:")
            print(f"  Subject: {email_data['subject'][:80]}...")
            print(f"  From: {email_data['from_email']}")
            print(f"  Date: {email_data['received_date']}")
            print(f"  Body length: {len(email_data['body'])} characters")
            
            # Try extraction
            print(f"\nAttempting data extraction...")
            extracted = extractor.extract_rfq_data(email_data)
            
            if extracted:
                print(f"✓ Data extracted:")
                for key, value in extracted.items():
                    print(f"  {key}: {value}")
            else:
                print(f"⚠ No RFQ data found in email")
                print(f"\nEmail body preview (first 500 chars):")
                print("-" * 70)
                print(email_data['body'][:500])
                print("-" * 70)
        else:
            print("✗ Could not fetch email")
        
        # Close connection
        extractor.imap_connection.close()
        extractor.imap_connection.logout()
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        import traceback
        traceback.print_exc()
        return False


def show_existing_replies(user_id):
    """Show existing RFQ replies in database"""
    print("\n" + "="*70)
    print("EXISTING RFQ REPLIES IN DATABASE")
    print("="*70)
    
    try:
        user = CustomUser.objects.get(id=user_id)
        replies = RfqReply.objects.filter(user=user).order_by('-received_date')[:10]
        
        if replies.count() == 0:
            print("No RFQ replies found in database")
        else:
            print(f"Found {replies.count()} recent replies:\n")
            for i, reply in enumerate(replies, 1):
                print(f"{i}. RFQ ID: {reply.rfq_id or 'N/A'}")
                print(f"   OEM: {reply.oem_name or 'N/A'}")
                print(f"   Price: ${reply.unit_price or 'N/A'}")
                print(f"   Date: {reply.received_date}")
                print(f"   Status: {reply.status}")
                if reply.rfq:
                    print(f"   ✓ Matched to RFQ: {reply.rfq.unique_id}")
                print()
        
        return True
        
    except Exception as e:
        print(f"✗ Error: {e}")
        return False


def run_all_tests(user_id):
    """Run all tests"""
    print("\n" + "#"*70)
    print("# RFQ REPLY EMAIL EXTRACTION - TEST SUITE")
    print("#"*70)
    
    results = {}
    
    # Test 1: Email config
    results['config'] = test_email_config(user_id)
    
    if not results['config']:
        print("\n⚠ Cannot proceed without valid email configuration")
        return results
    
    # Test 2: IMAP connection
    results['connection'] = test_imap_connection(user_id)
    
    if not results['connection']:
        print("\n⚠ Cannot proceed without IMAP connection")
        return results
    
    # Test 3: Email search
    results['search'] = test_email_search(user_id, days_back=7)
    
    # Test 4: Single email extraction
    results['extraction'] = test_single_email_extraction(user_id, days_back=7)
    
    # Test 5: Show existing replies
    results['existing'] = show_existing_replies(user_id)
    
    # Summary
    print("\n" + "#"*70)
    print("# TEST SUMMARY")
    print("#"*70)
    
    for test_name, passed in results.items():
        status = "✓ PASS" if passed else "✗ FAIL"
        print(f"{status} - {test_name.upper()}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n✓ All tests passed! Ready to run extraction.")
        print("\nNext steps:")
        print("  1. Run extraction: python manage.py extract_rfq_replies --user-id", user_id)
        print("  2. Or use: python extractRfqReplies.py --user-id", user_id)
    else:
        print("\n⚠ Some tests failed. Please fix issues before running extraction.")
    
    return results


if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='Test RFQ reply email extraction')
    parser.add_argument('--user-id', type=int, required=True, help='User ID to test')
    parser.add_argument('--test', choices=['config', 'connection', 'search', 'extraction', 'existing', 'all'],
                       default='all', help='Which test to run')
    
    args = parser.parse_args()
    
    if args.test == 'all':
        run_all_tests(args.user_id)
    elif args.test == 'config':
        test_email_config(args.user_id)
    elif args.test == 'connection':
        test_imap_connection(args.user_id)
    elif args.test == 'search':
        test_email_search(args.user_id)
    elif args.test == 'extraction':
        test_single_email_extraction(args.user_id)
    elif args.test == 'existing':
        show_existing_replies(args.user_id)


import os
import json
import subprocess
from django.db.models import Q, Exists, OuterRef
from django.utils import timezone
from datetime import timedelta
from .models import UserSelectionState, SolicitationEmailStatus


def client_context(request):
    if request.user.is_authenticated:
        return {'client': request.user}
    return {}

def rfq_processing_context(request):
    """
    Context processor to provide RFQ processing status globally
    Works for both manual sending and autosend
    """
    context = {
        'rfq_processing_count': 0,
        'rfq_total_selected': 0,
        'rfq_is_processing': False,
        'rfq_processing_percentage': 0,
        'rfq_processing_status': None,
        'show_stop_button': False,  
    }
    
    # Only process for authenticated users
    if not request.user.is_authenticated:
        return context
    
    try:
        # Get user's selection state (for manual sending)
        selection_state = UserSelectionState.get_for_user(request.user)
        
        # Get processing count from SolicitationEmailStatus (works for both manual and autosend)
        processing_count = SolicitationEmailStatus.objects.filter(
            user=request.user,
            email_status='processing'
        ).count()
        
        # Calculate total selected items
        # For manual sending: use UserSelectionState
        # For autosend: use SolicitationEmailStatus records from current batch
        if selection_state.select_all_mode:
            # If in select all mode, you might need to calculate based on current filter criteria
            # This depends on your business logic - for now, we'll use the processing_ids count
            total_selected = len(selection_state.processing_ids) if selection_state.processing_ids else 0
        else:
            total_selected = len(selection_state.selected_ids)
        
        # If no manual selection but there are processing records, it's likely autosend
        # Calculate total from current batch status records
        if total_selected == 0 and processing_count > 0:
            # This is autosend - calculate total from current batch
            # Count records that are: processing, pending, or recently sent/failed (within last 2 hours)
            recent_cutoff = timezone.now() - timedelta(hours=2)
            
            # Count all records in current batch: processing + pending + recently completed
            current_batch_total = SolicitationEmailStatus.objects.filter(
                user=request.user
            ).filter(
                Q(email_status__in=['processing', 'pending']) |
                Q(email_status__in=['sent', 'failed'], email_sent_at__gte=recent_cutoff)
            ).count()
            
            total_selected = current_batch_total if current_batch_total > 0 else processing_count
        
        # Check if user is currently submitting
        is_processing = selection_state.is_submitting or processing_count > 0
        
        # Calculate processing percentage
        processing_percentage = 0
        if total_selected > 0:
            # Count completed emails (sent or failed)
            # For autosend, only count from current batch
            if total_selected > 0 and processing_count > 0 and len(selection_state.selected_ids) == 0:
                # Autosend: count only recently completed (within last 2 hours)
                recent_cutoff = timezone.now() - timedelta(hours=2)
                completed_count = SolicitationEmailStatus.objects.filter(
                    user=request.user,
                    email_status__in=['sent', 'failed'],
                    email_sent_at__gte=recent_cutoff
                ).count()
            else:
                # Manual send: count all completed
                completed_count = SolicitationEmailStatus.objects.filter(
                    user=request.user,
                    email_status__in=['sent', 'failed']
                ).count()
            
            if completed_count > 0:
                processing_percentage = min(100, (completed_count / total_selected) * 100)
        
        # Determine processing status message
        processing_status = None
        if is_processing:
            if processing_count > 0:
                if total_selected > 0:
                    processing_status = f"Processing {processing_count} of {total_selected} RFQs..."
                else:
                    processing_status = f"Processing {processing_count} RFQs..."
            elif selection_state.is_submitting:
                processing_status = "Preparing RFQs for processing..."
        
        context.update({
            'rfq_processing_count': processing_count,
            'rfq_total_selected': total_selected,
            'rfq_is_processing': is_processing,
            'rfq_processing_percentage': round(processing_percentage, 1),
            'rfq_processing_status': processing_status,
            'show_stop_button': is_processing,  # Show stop button when processing
        })
        
    except Exception as e:
        # Log the error if needed, but don't break the page
        # logger.error(f"Error in rfq_processing_context: {e}")
        pass
    
    return context

def scraping_progress_context(request):
    """
    Context processor to provide scraping progress status globally
    Reads from scrape_progress.json file
    """
    context = {
        'scrape_is_running': False,
        'scrape_percentage': 0,
        'scrape_current': 0,
        'scrape_total': 0,
        'scrape_status_message': None,
        'scrape_stage': None,
        'scrape_status': None,  # 'running', 'completed', 'failed'
    }
    
    # Use dynamic path based on BASE_DIR
    from django.conf import settings
    logs_dir = os.path.join(settings.BASE_DIR, 'logs')
    os.makedirs(logs_dir, exist_ok=True)
    progress_file = os.path.join(logs_dir, 'scrape_progress.json')
    
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                progress_data = json.load(f)
            
            status = progress_data.get('status', '')
            
            # Only show if status is 'running'
            if status == 'running':
                # Verify process is actually running
                try:
                    check_process = subprocess.run(
                        ["pgrep", "-f", "extractSolicitations.py"],
                        stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE,
                        text=True,
                        timeout=5
                    )
                    
                    if check_process.returncode == 0:
                        # Process is running - verify it's alive
                        pids = check_process.stdout.strip().split('\n')
                        pids = [pid for pid in pids if pid]
                        alive_pids = []
                        for pid in pids:
                            try:
                                result = subprocess.run(
                                    ["kill", "-0", pid],
                                    stdout=subprocess.PIPE,
                                    stderr=subprocess.PIPE,
                                    timeout=2
                                )
                                if result.returncode == 0:
                                    alive_pids.append(pid)
                            except:
                                pass
                        
                        if alive_pids:
                            # Process is actually running
                            context.update({
                                'scrape_is_running': True,
                                'scrape_percentage': progress_data.get('percentage', 0),
                                'scrape_current': progress_data.get('current', 0),
                                'scrape_total': progress_data.get('total', 0),
                                'scrape_status_message': progress_data.get('message', 'Scraping in progress...'),
                                'scrape_stage': progress_data.get('stage', 'extracting'),
                                'scrape_status': 'running',
                            })
                except:
                    # If process check fails, still show status if file says running
                    # (might be a permission issue, but file indicates running)
                    context.update({
                        'scrape_is_running': True,
                        'scrape_percentage': progress_data.get('percentage', 0),
                        'scrape_current': progress_data.get('current', 0),
                        'scrape_total': progress_data.get('total', 0),
                        'scrape_status_message': progress_data.get('message', 'Scraping in progress...'),
                        'scrape_stage': progress_data.get('stage', 'extracting'),
                        'scrape_status': 'running',
                    })
            
    except Exception as e:
        # Log the error if needed, but don't break the page
        # logger.error(f"Error in scraping_progress_context: {e}")
        pass
    
    return context
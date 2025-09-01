from django.db.models import Q, Exists, OuterRef
from .models import UserSelectionState, SolicitationEmailStatus


def client_context(request):
    if request.user.is_authenticated:
        return {'client': request.user}
    return {}

def rfq_processing_context(request):
    """
    Context processor to provide RFQ processing status globally
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
        # Get user's selection state
        selection_state = UserSelectionState.get_for_user(request.user)
        
        # Calculate total selected items
        if selection_state.select_all_mode:
            # If in select all mode, you might need to calculate based on current filter criteria
            # This depends on your business logic - for now, we'll use the processing_ids count
            total_selected = len(selection_state.processing_ids) if selection_state.processing_ids else 0
        else:
            total_selected = len(selection_state.selected_ids)
        
        # Get processing count from SolicitationEmailStatus
        processing_count = SolicitationEmailStatus.objects.filter(
            user=request.user,
            email_status='processing'
        ).count()
        
        # Check if user is currently submitting
        is_processing = selection_state.is_submitting or processing_count > 0
        
        # Calculate processing percentage
        processing_percentage = 0
        if total_selected > 0:
            # Count completed emails (sent or failed)
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
                processing_status = f"Processing {processing_count} of {total_selected} RFQs..."
            elif selection_state.is_submitting:
                processing_status = "Preparing RFQs for processing..."
        
        context.update({
            'rfq_processing_count': processing_count,
            'rfq_total_selected': total_selected,
            'rfq_is_processing': is_processing,
            'rfq_processing_percentage': round(processing_percentage, 1),
            'rfq_processing_status': processing_status,
            'show_stop_button': is_processing,  # ADD THIS LINE - Show stop button when processing
        })
        
    except Exception as e:
        # Log the error if needed, but don't break the page
        # logger.error(f"Error in rfq_processing_context: {e}")
        pass
    
    return context
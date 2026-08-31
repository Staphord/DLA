from django.http import HttpResponsePermanentRedirect
from django.conf import settings


class ForceScriptNameRedirectMiddleware:
    """
    Middleware to redirect URLs that are missing the FORCE_SCRIPT_NAME prefix.
    
    If FORCE_SCRIPT_NAME is set (e.g., '/dla'), this middleware will redirect
    requests that don't include this prefix to the correct URL with the prefix.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        # Get the script name prefix from settings
        self.script_prefix = getattr(settings, 'FORCE_SCRIPT_NAME', None)
    
    def __call__(self, request):
        # Only redirect if FORCE_SCRIPT_NAME is set and the path doesn't start with it
        if self.script_prefix and self.script_prefix != '/':
            # Remove trailing slash from prefix for comparison
            prefix = self.script_prefix.rstrip('/')
            path = request.path
            
            # Skip redirect for:
            # 1. URLs that already have the prefix
            if path.startswith(prefix):
                response = self.get_response(request)
                return response
            
            # 2. Static/media files (handled by nginx or Django staticfiles)
            if (path.startswith('/static/') or 
                path.startswith('/media/') or
                path.startswith('/dla/static/') or
                path.startswith('/dla/media/')):
                response = self.get_response(request)
                return response
            
            # 3. Health check or monitoring endpoints (if any)
            if path in ['/health', '/healthcheck', '/ping']:
                response = self.get_response(request)
                return response
            
            # Redirect all Django app URLs
            # This includes:
            # - /solicitations/... (all solicitation URLs)
            # - /admin/... (admin URLs)  
            # - /accounts/... (account URLs)
            # - /logout-user/, /register-user/, etc. (account URLs at root)
            # - / (root path - login page)
            # - Any other path that's not static/media
            
            # Check if it's a Django URL pattern
            is_django_url = (
                path.startswith('/solicitations/') or
                path.startswith('/admin/') or
                path.startswith('/accounts/') or
                path.startswith('/logout-user') or
                path.startswith('/register-user') or
                path.startswith('/register/') or
                path.startswith('/verify-email/') or
                path.startswith('/password-reset/') or
                path.startswith('/reset/') or
                path == '/'  # Root path (login page)
            )
            
            if is_django_url:
                # Build the redirect URL with the prefix
                new_path = prefix + path
                # Preserve query string if present
                if request.GET:
                    query_string = request.GET.urlencode()
                    new_path += '?' + query_string
                
                # Return permanent redirect (301)
                return HttpResponsePermanentRedirect(new_path)
        
        # Continue with normal request processing
        response = self.get_response(request)
        return response


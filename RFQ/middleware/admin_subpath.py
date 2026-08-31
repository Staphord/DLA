"""
Middleware to fix Django admin redirects and form actions for subpath deployment.
Ensures all admin redirects and form action URLs include the FORCE_SCRIPT_NAME prefix.
"""
from django.conf import settings
from django.http import HttpResponseRedirect, HttpResponsePermanentRedirect, HttpResponse
from urllib.parse import urlparse, urlunparse
import re


class AdminSubpathMiddleware:
    """
    Middleware to fix admin redirects and form action URLs that don't include the subpath prefix.
    """
    
    def __init__(self, get_response):
        self.get_response = get_response
        self.script_prefix = getattr(settings, 'FORCE_SCRIPT_NAME', '') or ''
    
    def __call__(self, request):
        response = self.get_response(request)
        
        # Process all redirect types
        if isinstance(response, (HttpResponseRedirect, HttpResponsePermanentRedirect)):
            redirect_url = response.url
            
            # Parse the redirect URL
            parsed = urlparse(redirect_url)
            
            # Check if path starts with /admin/ but doesn't have the prefix
            if parsed.path.startswith('/admin/') and not parsed.path.startswith(self.script_prefix + '/admin/'):
                # Add the prefix to the path
                new_path = self.script_prefix + parsed.path
                
                # Fix the 'next' parameter in query string if present
                from urllib.parse import parse_qs, urlencode
                query_parts = parse_qs(parsed.query, keep_blank_values=True)
                new_query = parsed.query
                
                if 'next' in query_parts:
                    next_url = query_parts['next'][0]
                    # If next URL starts with /admin/ or /, add prefix if missing
                    if next_url.startswith('/admin/') and not next_url.startswith(self.script_prefix + '/admin/'):
                        query_parts['next'][0] = self.script_prefix + next_url
                        new_query = urlencode(query_parts, doseq=True)
                    elif next_url.startswith('/') and next_url != '/' and not next_url.startswith(self.script_prefix):
                        query_parts['next'][0] = self.script_prefix + next_url
                        new_query = urlencode(query_parts, doseq=True)
                
                # Reconstruct URL preserving scheme, netloc, query, etc.
                new_url = urlunparse((
                    parsed.scheme or '',
                    parsed.netloc or '',
                    new_path,
                    parsed.params,
                    new_query,
                    parsed.fragment
                ))
                
                # Use same redirect type
                if isinstance(response, HttpResponsePermanentRedirect):
                    return HttpResponsePermanentRedirect(new_url)
                else:
                    return HttpResponseRedirect(new_url)
        
        # Also fix HTML responses (for form action URLs)
        if isinstance(response, HttpResponse) and 'text/html' in response.get('Content-Type', ''):
            try:
                content = response.content.decode('utf-8')
                
                # Fix form action URLs in admin login forms
                # Pattern: action="/admin/login/" or action='/admin/login/' or action="/admin/login/?next=/admin/"
                # This regex captures the entire action value including query string
                pattern = r'(action=["\'])([^"\']*?)(["\'])'
                def replace_action(match):
                    quote = match.group(1)  # Opening quote
                    url = match.group(2)    # Full URL (may include query string)
                    end_quote = match.group(3)  # Closing quote
                    
                    # Parse URL to separate path and query
                    parsed = urlparse(url if url.startswith('http') else f'http://dummy{url}')
                    path = parsed.path if url.startswith('http') else url.split('?')[0]
                    query = url.split('?', 1)[1] if '?' in url else ''
                    
                    # Only fix paths that start with /admin/ but don't have the prefix
                    if path.startswith('/admin/') and not path.startswith(self.script_prefix + '/admin/'):
                        new_path = self.script_prefix + path
                        
                        # Fix 'next' parameter in query string if present
                        if query:
                            from urllib.parse import parse_qs, urlencode
                            query_parts = parse_qs(query, keep_blank_values=True)
                            if 'next' in query_parts:
                                next_url = query_parts['next'][0]
                                if next_url.startswith('/admin/') and not next_url.startswith(self.script_prefix + '/admin/'):
                                    query_parts['next'][0] = self.script_prefix + next_url
                                    query = urlencode(query_parts, doseq=True)
                        
                        new_url = new_path + ('?' + query if query else '')
                        return f'{quote}{new_url}{end_quote}'
                    return match.group(0)
                
                content = re.sub(pattern, replace_action, content)
                
                # Fix input[name="next"] values
                # Pattern: <input type="hidden" name="next" value="/admin/">
                next_pattern = r'(<input[^>]*name=["\']next["\'][^>]*value=["\'])(/admin/[^"\']*?)(["\'])'
                def replace_next(match):
                    prefix = match.group(1)  # Everything before the value
                    path = match.group(2)    # Path value
                    suffix = match.group(3)  # Closing quote
                    
                    # Only fix paths that start with /admin/ but don't have the prefix
                    if path.startswith('/admin/') and not path.startswith(self.script_prefix + '/admin/'):
                        new_path = self.script_prefix + path
                        return f'{prefix}{new_path}{suffix}'
                    return match.group(0)
                
                content = re.sub(next_pattern, replace_next, content, flags=re.IGNORECASE)
                
                # Only recreate response if content changed
                if content != response.content.decode('utf-8'):
                    # Preserve original headers
                    headers = {}
                    for header, value in response.items():
                        headers[header] = value
                    
                    # Create new response with fixed content
                    new_response = HttpResponse(content, status=response.status_code)
                    
                    # Copy headers (excluding Content-Length which will be recalculated)
                    for header, value in headers.items():
                        if header.lower() != 'content-length':
                            new_response[header] = value
                    
                    new_response['Content-Length'] = str(len(content.encode('utf-8')))
                    response = new_response
            
            except (UnicodeDecodeError, AttributeError):
                # If content can't be decoded or is binary, just pass through
                pass
        
        return response


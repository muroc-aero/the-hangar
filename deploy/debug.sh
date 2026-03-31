#!/bin/bash
# Temporary debug commands — delete after use

echo "=== Check app routes ==="
docker compose -f docker-compose.prod.yml exec oas-mcp python3 -c "
from hangar.oas.server import mcp
app = mcp.streamable_http_app()
for route in getattr(app, 'routes', []):
    print(getattr(route, 'path', ''), getattr(route, 'methods', ''))
"

echo ""
echo "=== Check 401 headers ==="
docker compose -f docker-compose.prod.yml exec oas-mcp python3 -c "
import urllib.request
try:
    urllib.request.urlopen('http://127.0.0.1:8000/mcp', b'{}')
except urllib.error.HTTPError as e:
    print('Status:', e.code)
    print('Headers:')
    for k,v in e.headers.items():
        print(f'  {k}: {v}')
"

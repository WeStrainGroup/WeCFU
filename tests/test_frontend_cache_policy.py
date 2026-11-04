"""Cache policy survives conditional frontend requests without changing photo caching."""
import pytest
from fastapi.testclient import TestClient

import wecfu.server.app as server
from test_public_fusion_contract import BASE, upload


@pytest.mark.parametrize('web_mode', [False, True])
def test_entry_documents_are_never_stored_and_versioned_assets_revalidate(tmp_path, web_mode):
    root = tmp_path/'unused-workspace'
    application = server.build_app(lambda:root, web_mode=web_mode)
    with TestClient(application) as client:
        for endpoint in ('/', '/?launch=synthetic-fresh-launch', '/static/index.html'):
            response = client.get(endpoint)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-store'
            assert response.content == (server._STATIC/'index.html').read_bytes()
        for method,endpoint in [('GET','/static/app.js?v=synthetic-version'),
                                ('HEAD','/static/styles.css?v=synthetic-version')]:
            response = client.request(method, endpoint)
            assert response.status_code == 200
            assert response.headers['cache-control'] == 'no-cache, must-revalidate'
            conditional = client.request(method, endpoint, headers={'If-None-Match':response.headers['etag']})
            assert conditional.status_code == 304
            assert conditional.headers['cache-control'] == 'no-cache, must-revalidate'
            assert conditional.content == b''
        stale = client.get('/static/app.js?v=old-version', headers={'If-None-Match':'"different-old-ui"'})
        assert stale.status_code == 200
        assert stale.headers['cache-control'] == 'no-cache, must-revalidate'
        assert stale.content == (server._STATIC/'app.js').read_bytes()
    assert not root.exists()  # No photo/session workspace was touched by frontend requests.


def test_cache_middleware_leaves_photo_bytes_and_photo_header_contract_unchanged(tmp_path):
    root = tmp_path/'synthetic-workspace'
    application = server.build_app(lambda:root)
    with TestClient(application) as client:
        raw = upload(client)
        source = client.get(BASE+'/raw')
        assert source.status_code == 200 and source.content == raw
        assert 'cache-control' not in source.headers
        context = client.get(BASE+'/raw?display_context=true')
        assert context.status_code == 200 and context.content == raw
        assert context.headers['cache-control'] == 'no-store'
        assert not (root/'runs').exists()

"""Exercise the public demo boundary and real deterministic reporting pipeline."""
import json
import time
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from workmate.api import create_app
from workmate.demo import COOKIE, SAMPLE, SAMPLE_NAME, DemoManager, create_demo_app

SECRET = 'verification-only-secret-not-for-production'


def manager(tmp_path, **kwargs):
    return DemoManager(tmp_path / 'demo', SECRET, secure=False, **kwargs)


def checked(client):
    response = client.post('/api/v1/inspect', json={'file': SAMPLE_NAME})
    assert response.status_code == 200, response.text
    return response.json()


def task_body(receipt):
    return {'file': SAMPLE_NAME, 'instruction': '生成合成销售周报', 'amount_mode': 'A',
            'unit': 'USD', 'report_week': '2026-09-28', 'compare_week': '2026-09-21',
            'complete': {'report': True, 'compare': True},
            'field_mapping': receipt['mapping'], 'confirmation_id': receipt['confirmation_id']}


def finished(client, tid):
    for _ in range(200):
        data = client.get(f'/api/v1/tasks/{tid}').json()
        if data.get('status') in {'done', 'failed'}:
            return data
        time.sleep(.02)
    pytest.fail('demo report did not terminate')


def test_complete_report_isolated_downloadable_and_restored_after_restart(tmp_path):
    m = manager(tmp_path)
    app = create_app(demo=m)
    with TestClient(app) as a, TestClient(app) as b:
        assert 'data-online-demo="true"' in a.get('/').text
        files = a.get('/api/v1/data-files').json()['files']
        assert [f['name'] for f in files] == [SAMPLE_NAME]
        receipt = checked(a)
        response = a.post('/api/v1/tasks', json=task_body(receipt))
        assert response.status_code == 200, response.text
        tid = response.json()['task_id']
        task = finished(a, tid)
        assert task['status'] == 'done', task.get('error')
        basis = a.get(f'/api/v1/tasks/{tid}/basis').json()
        assert basis['verify']['passed'] is True
        assert basis['summary_validation']['provider'] == 'mock'
        report = a.get(f'/api/v1/tasks/{tid}/report').json()['report']
        assert '600.00' in report and '100.00%' in report
        facts = a.get(f'/api/v1/tasks/{tid}/facts').json()
        assert any(f['id'] == 'total_sales' and f['value'] == 600 for f in facts['facts'])
        assert facts['change_facts'] and all(f['total_change'] == 300 for f in facts['change_facts'])
        assert a.get(f'/api/v1/tasks/{tid}/facts').status_code == 200
        artifacts = ['report.md', 'data_summary.xlsx', 'analysis_basis.json', 'charts/trend.png',
                     'charts/top5.png', 'charts/channel.png']
        content = {}
        for name in artifacts:
            response = a.get(f'/api/v1/tasks/{tid}/files/{name}')
            assert response.status_code == 200, (name, response.text[:100])
            assert response.headers['cache-control'] == 'no-store'
            content[name] = response.content
        assert content['charts/trend.png'].startswith(b'\x89PNG')
        assert content['data_summary.xlsx'].startswith(b'PK')
        assert b.get('/api/v1/tasks').json()['tasks'] == []
        for suffix in ['', '/report', '/basis', '/facts', '/files/report.md', '/files/charts/trend.png']:
            assert b.get(f'/api/v1/tasks/{tid}{suffix}').status_code == 404
        assert b.post('/api/v1/tasks', json=task_body(receipt)).json()['error']['code'] == 'CONFIRMATION_INVALID'
        token = a.cookies.get(COOKIE)
    # New application/manager, same on-disk state: no memory from the first server.
    with TestClient(create_app(demo=manager(tmp_path))) as restored:
        restored.cookies.set(COOKIE, token, domain='testserver.local', path='/')
        assert restored.get(f'/api/v1/tasks/{tid}').json()['status'] == 'done'
        for name in artifacts:
            assert restored.get(f'/api/v1/tasks/{tid}/files/{name}').content == content[name]
        assert restored.post('/api/v1/tasks', json=task_body(receipt)).status_code == 200


def test_public_upload_accepts_only_unmodified_sample_and_does_not_store_rejected_data(tmp_path):
    m = manager(tmp_path)
    with TestClient(create_app(demo=m)) as client:
        sample = client.get('/api/v1/demo-sample')
        assert sample.content == SAMPLE and 'attachment' in sample.headers['content-disposition']
        for data, filename in [(SAMPLE, 'renamed.csv'), (SAMPLE, '../../sample.csv')]:
            response = client.post('/api/v1/upload', files={'file': (filename, data)})
            assert response.status_code == 200
            assert response.json()['name'] == SAMPLE_NAME
        response = client.post('/api/v1/upload', files={'file': ('private.csv', b'Customer,Phone\nPrivate,123\n')})
        assert response.status_code == 403
        assert response.json()['error']['code'] == 'DEMO_SAMPLE_ONLY'
        assert len(client.get('/api/v1/data-files').json()['files']) == 1
        assert not any(b'Private' in p.read_bytes() for p in m.root.rglob('*') if p.is_file())
        assert client.post('/api/v1/inspect', json={'file': '/etc/passwd'}).status_code == 403
        assert client.post('/api/v1/inspect', json={'file': '../other.csv'}).status_code == 403


def test_body_limit_cookies_csrf_and_health_probe(tmp_path):
    m = DemoManager(tmp_path / 'demo', SECRET, secure=True)
    with TestClient(create_app(demo=m), base_url='https://testserver') as client:
        assert client.get('/healthz').status_code == 200
        assert list(m.root.iterdir()) == []
        response = client.get('/')
        cookie = response.headers['set-cookie']
        assert all(flag in cookie for flag in ['HttpOnly', 'Secure', 'SameSite=Lax'])
        response = client.post('/api/v1/upload', files={'file': ('big.csv', b'x' * 65536)})
        assert response.status_code == 413
        response = client.post('/api/v1/inspect', json={'file': SAMPLE_NAME}, headers={'Origin': 'https://evil.example'})
        assert response.status_code == 403
        assert client.post('/api/v1/inspect', json={'file': SAMPLE_NAME}, headers={'Origin': 'https://testserver'}).status_code == 200
        assert client.get('/api/openapi.json').status_code == 404


def test_signed_sessions_cannot_be_forged_and_capacity_is_bounded(tmp_path):
    m = manager(tmp_path, max_sessions=2)
    with TestClient(create_app(demo=m)) as client:
        client.get('/')
        first = client.cookies.get(COOKIE)
        sid = first.split('.')[0]
        client.cookies.clear()
        client.cookies.set(COOKIE, first[:-1] + ('0' if first[-1] != '0' else '1'), domain='testserver.local', path='/')
        client.get('/')
        assert client.cookies.get(COOKIE).split('.')[0] != sid
        client.cookies.clear()
        client.cookies.set(COOKIE, '../traversal', domain='testserver.local', path='/')
        assert client.get('/').status_code == 429
        assert len(list(m.root.iterdir())) == 2
        assert client.get('/healthz').status_code == 200


def test_task_limit_and_overlarge_chart_labels_are_rejected(tmp_path):
    with TestClient(create_app(demo=manager(tmp_path, max_tasks=1))) as client:
        receipt = checked(client)
        body = task_body(receipt)
        response = client.post('/api/v1/tasks', json={**body, 'unit': '元' * 10000})
        assert response.status_code == 400
        response = client.post('/api/v1/tasks', json=body)
        assert response.status_code == 200
        assert finished(client, response.json()['task_id'])['status'] == 'done'
        assert client.post('/api/v1/tasks', json=body).status_code == 429
        assert len(client.get('/api/v1/tasks').json()['tasks']) == 1


def test_expired_workspaces_are_cleaned_and_boot_without_secret_fails(tmp_path, monkeypatch):
    m = manager(tmp_path)
    sid, token, expires = m.session(None)
    m.context(sid)
    monkeypatch.setattr('workmate.demo.time.time', lambda: expires + 1)
    new_sid, _, _ = m.session(token)
    assert new_sid != sid and not (m.root / sid).exists()
    monkeypatch.setenv('WORKMATE_DEMO_DIR', str(tmp_path / 'empty'))
    monkeypatch.delenv('WORKMATE_DEMO_SECRET', raising=False)
    with pytest.raises(ValueError, match='WORKMATE_DEMO_SECRET'):
        create_demo_app()

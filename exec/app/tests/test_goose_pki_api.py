"""GOOSE PKI HTTP isolation and existing session/admin enforcement."""
import importlib.util
import io
from pathlib import Path
import sys
import types

import pytest
from flask import Blueprint
from test_auth_session import auth_app, login


@pytest.fixture
def goose_app(auth_app,monkeypatch,tmp_path):
    app,_,_=auth_app
    config=sys.modules['config']
    config.STATE_DONE=0; config.STATE_ERROR=1
    config.INI_PATH=tmp_path/'unused.ini'
    module=types.ModuleType('routes.route_g3')
    module.g3_bp=Blueprint('goose_cert_test',__name__)
    monkeypatch.setitem(sys.modules,'routes.route_g3',module)
    spec=importlib.util.spec_from_file_location('routes.goose_cert_test',
        Path(__file__).resolve().parents[1]/'routes/route_cert.py')
    route=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(route)
    app.register_blueprint(module.g3_bp)
    app.config['GOOSE_PKI_DIR']=str(tmp_path/'goose-pki')
    return app,route


@pytest.mark.parametrize('method,path',[
    ('GET','/api/cert/goose/status'),('POST','/api/cert/goose/key/import'),('POST','/api/cert/goose/apply')])
def test_goose_requires_session_and_admin(goose_app,method,path):
    client=goose_app[0].test_client()
    assert client.open(path,method=method).status_code==401
    credentials=login(client).json
    assert client.open(path,method=method,headers={'X-CSRF-Token': credentials['csrf_token']}).status_code==403


def test_new_routes_do_not_change_tls_modes(goose_app):
    app,route=goose_app
    client=app.test_client(); credentials=login(client,'admin').json
    headers={'X-CSRF-Token': credentials['csrf_token']}
    assert client.get('/api/cert/goose/status').json['data']==dict(installed=False)
    assert client.post('/api/cert/goose/peer/import',headers=headers).status_code==400
    assert client.post('/api/cert/goose/key/import', headers=headers, data={'file':(io.BytesIO(b'bad-key'),'key.pem')}).status_code==422
    # Existing endpoints still enforce their original mode contract.
    assert client.get('/api/cert/ca?pki_mode=trina').status_code==400
    assert client.get('/api/cert/custom/status?pki_mode=general').status_code==400


def test_goose_apply_targets_only_its_service(goose_app,monkeypatch):
    app,route=goose_app
    calls=[]
    monkeypatch.setattr(route.subprocess,'run',lambda args,**kw: calls.append(args) or types.SimpleNamespace(returncode=0))
    with app.test_request_context('/api/cert/goose/apply',method='POST'):
        route._goose_service_apply('goose')
    assert calls==[['systemctl','--no-ask-password','restart','goose_middle.service'],
                   ['systemctl','--no-ask-password','is-active','--quiet','goose_middle.service']]


@pytest.mark.parametrize('failed_action,code', [('restart', 1), ('is-active', 3)])
def test_goose_service_failure_logs_stage_and_bounded_stderr(goose_app,monkeypatch,failed_action,code):
    app,route=goose_app
    logs=[]
    monkeypatch.setattr(route,'_cert_log',lambda event,**details: logs.append((event,details)))
    def run(args,**kwargs):
        return types.SimpleNamespace(returncode=code if args[2]==failed_action else 0,
                                     stderr=b'Unit goose_middle.service failed\n'+b'x'*2000)
    monkeypatch.setattr(route.subprocess,'run',run)
    with app.test_request_context('/api/cert/goose/apply',method='POST'):
        with pytest.raises(OSError):
            route._goose_service_apply('goose')
    details=logs[-1][1]
    assert details['action']==failed_action and details['returncode']==code
    assert details['service']=='goose_middle.service'
    assert len(details['stderr'])==1024


def test_goose_service_timeout_is_logged_and_propagated(goose_app,monkeypatch):
    app,route=goose_app
    logs=[]
    monkeypatch.setattr(route,'_cert_log',lambda event,**details: logs.append((event,details)))
    def run(args,**kwargs):
        raise route.subprocess.TimeoutExpired(args,120)
    monkeypatch.setattr(route.subprocess,'run',run)
    with app.test_request_context('/api/cert/goose/apply',method='POST'):
        with pytest.raises(route.subprocess.TimeoutExpired):
            route._goose_service_apply('goose')
    assert logs[-1][1]['action']=='restart'
    assert logs[-1][1]['error_type']=='TimeoutExpired'


def test_four_file_upload_and_apply_via_existing_authentication(goose_app,monkeypatch,tmp_path):
    # Reuse the independent test-only EC CA generator, not a production identity.
    source=Path(__file__).resolve().parents[3]/'goose/goose_test/tests'
    monkeypatch.syspath_prepend(str(source))
    from test_goose_security import identity,crl,key_bytes,ENC
    root_key,root=identity('api-root',ca=True)
    key,cert=identity('api-subscriber',root,root_key)
    files={'identity':cert.public_bytes(ENC),'key':key_bytes(key),
           'ca':root.public_bytes(ENC),'crl':crl(root,root_key)}
    app,route=goose_app
    calls=[]
    monkeypatch.setattr(route,'_goose_service_apply',calls.append)
    client=app.test_client(); credentials=login(client,'admin').json
    headers={'X-CSRF-Token':credentials['csrf_token']}
    batch=None
    for part,data in files.items():
        fields={'file':(io.BytesIO(data),part+'.pem')}
        if batch:
            fields['batch_id']=batch
        response=client.post('/api/cert/goose/'+part+'/import',data=fields,headers=headers)
        assert response.status_code==200,response.json
        batch=response.json['data']['batch_id']
    assert calls==[]
    assert client.get('/api/cert/goose/status').json['data']=={'installed':False}
    # Missing CSRF must reject even an authenticated administrator.
    assert client.post('/api/cert/goose/apply',json={'batch_id':batch}).status_code==403
    response=client.post('/api/cert/goose/apply',json={'batch_id':batch},headers=headers)
    assert response.status_code==200,response.json
    assert response.json['data']['status']=='applied' and calls==['goose']
    assert client.get('/api/cert/goose/status').json['data']['installed']
    encoded=str(response.json)
    assert 'PRIVATE KEY' not in encoded

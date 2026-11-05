import pytest
from utils.input_validation import validate_ini_payload, public_configuration


def test_valid_payload_is_normalized_without_changing_input():
    value=dict(mainSystem='2',pcsCount=4,bmsCount=10,pointToPointEnabled=True,
               pcsList=[dict(id='1',ip='192.0.2.10',port='502')])
    result=validate_ini_payload(value)
    assert result['mainSystem']==2 and result['pcsList'][0]['port']==502
    assert value['mainSystem']=='2'


@pytest.mark.parametrize('value',[
    [],dict(pcsCount=5),dict(bmsCount=11),dict(mainSystem=0),dict(mainSystem=3),dict(subSystem=5),dict(pcsCount=True),
    dict(pointToPointEnabled='true'),dict(unknown=1),
    dict(pcsList=[dict(id=1,ip='not-an-ip',port=502)]),
    dict(pcsList=[dict(id=1,ip='192.0.2.10',port=65536)]),
    dict(pcsList=[dict(id=1,ip='127.0.0.1',port=502)]),
    dict(pcsList=[dict(id=1,ip=True,port=502)]),
    dict(pcsList=[dict(id=1,ip='192.0.2.10',port=502)]*2),
])
def test_invalid_payload_is_rejected(value):
    with pytest.raises(ValueError):
        validate_ini_payload(value)


def test_ini_response_removes_secrets_and_retains_operational_fields():
    value=dict(DB=dict(password='secret',host='192.0.2.1'),
               TEE=dict(private_key='secret',keyId='public-id'),
               SYSTEM=dict(pcsNum='4',api_token='secret'))
    public=public_configuration(value)
    assert public==dict(DB=dict(host='192.0.2.1'),TEE=dict(keyId='public-id'),SYSTEM=dict(pcsNum='4'))
    assert value['DB']['password']=='secret'


def test_ini_write_and_readback_cover_all_ten_bms_slots(tmp_path):
    # Extract only these pure helpers; importing method would initialize device/MySQL services.
    import ast
    import configparser
    from pathlib import Path
    from typing import Optional
    source=Path(__file__).parents[1]/'utils'/'method.py'
    tree=ast.parse(source.read_text())
    selected=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in
              ('update_ini_from_payload','verify_ini_matches_payload')]
    namespace=dict(Path=Path,Optional=Optional,configparser=configparser)
    exec(compile(ast.Module(body=selected,type_ignores=[]),str(source),'exec'),namespace)
    path=tmp_path/'device.ini'
    path.write_text('[SYSTEM]\n')
    data=validate_ini_payload(dict(bmsCount=10,bmsBrand=1,
                                   bmsList=[dict(id=10,ip='192.0.2.10',port=502)]))
    namespace['update_ini_from_payload'](data,path)
    assert namespace['verify_ini_matches_payload'](data,path)['ok']
    config=configparser.ConfigParser()
    config.read(path)
    assert config.get('BMS_NETWORK','bms10_brand')=='1'
    assert config.get('BMS_NETWORK','bms10_ip')=='192.0.2.10'

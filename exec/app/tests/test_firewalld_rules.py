"""Read-only firewalld collection with isolated auth and command fixtures."""
import pytest
from test_auth_session import auth_app, login
from test_security_center import security_app


ZONES = '''public (active)
  target: default
  interfaces: eth0
  sources: 192.168.2.0/24
  services: ssh https
  ports: 8000/tcp 502/tcp 1502/tcp 6000-6010/udp
  protocols:
  forward: yes
  masquerade: no
  forward-ports:
  source-ports:
  icmp-blocks:
  rich rules:
    rule family="ipv6" source address="2001:db8::/32" port port="443" protocol="tcp" accept
    rule family="ipv4" source address="192.0.2.0/24" drop
trusted
  target: ACCEPT
  interfaces:
  sources:
  services:
  ports:
  rich rules:
'''


def test_runtime_rules_include_ports_and_preserve_conditions(security_app, monkeypatch):
    from routes import route_security as module
    calls = []
    outputs = {
        ('ip', '-j', 'address', 'show'): '[{"ifname":"eth0"}]',
        ('ip', '-j', 'route', 'show'): '[]',
        ('firewall-cmd', '--list-all-zones'): ZONES,
    }
    def command(arguments, **kwargs):
        if arguments[0] == 'firewall-cmd':
            assert kwargs['env']['LC_ALL'] == 'C'
        calls.append(tuple(arguments))
        return outputs[tuple(arguments)]
    monkeypatch.setattr(module, '_command', command)
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/network-rules')
    assert response.status_code == 200
    assert client.get('/api/security/network-rules').json == response.json
    assert len(calls) == 3  # Repeated refresh does not spawn another command set.
    data = response.json
    assert data['rulesAvailable'] is True and data['rulesUnavailableReason'] is None
    assert data['writable'] is False and data['source'] == 'iproute2-firewalld'
    assert data['interfaces'] == [{'ifname': 'eth0'}]
    public, trusted = data['rules']['zones']
    assert data['rules']['scope'] == 'runtime-zones'
    assert public['name'] == 'public' and public['active'] is True
    assert public['interfaces'] == ['eth0']
    assert public['sources'] == ['192.168.2.0/24']
    assert public['services'] == ['ssh', 'https']
    assert public['ports'] == [dict(port=port, protocol=proto) for port, proto in
                               [('8000','tcp'), ('502','tcp'), ('1502','tcp'), ('6000-6010','udp')]]
    assert public['target'] == 'default'
    assert len(public['richRules']) == 2 and '2001:db8::/32' in public['richRules'][0]
    assert public['details']['masquerade'] == 'no'
    assert trusted['ports'] == [] and trusted['active'] is False
    assert trusted['target'] == 'ACCEPT'
    assert calls == list(outputs)


@pytest.mark.parametrize('output,reason', [
    (None, 'FIREWALLD_QUERY_FAILED'),
    ('', 'FIREWALLD_RESPONSE_INVALID'),
    ('not zone output', 'FIREWALLD_RESPONSE_INVALID'),
    ('public\n  ports: invalid', 'FIREWALLD_RESPONSE_INVALID'),
])
def test_firewalld_failure_is_not_an_empty_ruleset(security_app, monkeypatch, output, reason):
    from routes import route_security as module
    monkeypatch.setattr(module, '_command', lambda args, **kwargs: output if args[0] == 'firewall-cmd' else '[]')
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/network-rules')
    assert response.status_code == 200
    assert response.json['rulesAvailable'] is False
    assert response.json['rules'] is None
    assert response.json['rulesUnavailableReason'] == reason


def test_empty_zone_is_a_successful_collection(security_app, monkeypatch):
    from routes import route_security as module
    monkeypatch.setattr(module, '_command', lambda args, **kwargs: 'public\n  ports:\n  services:\n  rich rules:'
                        if args[0] == 'firewall-cmd' else '[]')
    client = security_app[0].test_client()
    login(client, 'admin')
    data = client.get('/api/security/network-rules').json
    assert data['rulesAvailable'] is True
    assert data['rules']['zones'][0]['ports'] == []


def test_low_role_cannot_query_firewalld(security_app, monkeypatch):
    from routes import route_security as module
    def forbidden(arguments, **kwargs):
        pytest.fail('unauthorized request executed a command')
    monkeypatch.setattr(module, '_command', forbidden)
    client = security_app[0].test_client()
    login(client, 'alice')
    assert client.get('/api/security/network-rules').status_code == 403


@pytest.mark.parametrize('header,active', [
    ('public', False),
    ('public (default)', False),
    ('public (active)', True),
    ('public (default, active)', True),
    ('public (active, default)', True),
    ('public (default) (active)', True),
])
def test_zone_header_flags_do_not_break_collection(security_app, monkeypatch, header, active):
    from routes import route_security as module
    output = ZONES.replace('public (active)', header, 1)
    monkeypatch.setattr(module, '_command', lambda args, **kwargs: output if args[0] == 'firewall-cmd' else '[]')
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/network-rules')
    assert response.status_code == 200
    assert response.json['rulesAvailable'] is True
    zone = response.json['rules']['zones'][0]
    assert zone['name'] == 'public' and zone['active'] is active
    assert zone['ports'][0] == dict(port='8000', protocol='tcp')


def test_em1000_actual_output(security_app, monkeypatch):
    from pathlib import Path
    from routes import route_security as module
    output = (Path(__file__).parent / 'fixtures/firewalld-em1000-zones.txt').read_text()
    monkeypatch.setattr(module, '_command', lambda args, **kwargs: output if args[0] == 'firewall-cmd' else '[]')
    client = security_app[0].test_client()
    login(client, 'admin')
    response = client.get('/api/security/network-rules')
    assert response.status_code == 200 and response.json['rulesAvailable'] is True
    zones = {zone['name']: zone for zone in response.json['rules']['zones']}
    assert len(zones) == 10
    public = zones['public']
    assert public['active'] is True and public['interfaces'] == ['net2']
    assert public['ports'] == [dict(port=port, protocol='tcp') for port in
                               ['8000', '502', '9000', '3306', '443']]
    assert public['services'] == ['dhcpv6-client', 'ssh']
    assert public['details']['icmp-blocks'] == 'timestamp-reply timestamp-request'
    assert zones['nm-shared']['richRules'] == ['rule priority="32767" reject']


@pytest.mark.parametrize('indent', ['  ', '    ', '\t', '\t\t'])
def test_rich_rule_indentation_is_not_fixed(security_app, indent):
    from routes.route_security import _firewalld_zones
    output = 'public (default, active)\n  rich rules:\n' + indent + 'rule priority="32767" reject'
    assert _firewalld_zones(output)[0]['richRules'] == ['rule priority="32767" reject']


def test_parse_error_identifies_line_and_zone(security_app):
    from routes.route_security import _firewalld_zones
    with pytest.raises(ValueError, match='line 3, zone=public') as error:
        _firewalld_zones('public\n  rich rules:\n    unexpected continuation')
    assert 'unexpected continuation' in str(error.value)


def test_command_applies_locale_without_changing_global_environment(security_app, monkeypatch):
    import os
    from types import SimpleNamespace
    from routes import route_security as module
    monkeypatch.setenv('LC_ALL', 'zh_CN.UTF-8')
    def run(arguments, **kwargs):
        assert kwargs['env']['LC_ALL'] == 'C'
        return SimpleNamespace(returncode=0, stdout='public\n  ports:\n')
    monkeypatch.setattr(module.subprocess, 'run', run)
    assert module._command(['firewall-cmd', '--list-all-zones'], env=dict(os.environ, LC_ALL='C'))
    assert os.environ['LC_ALL'] == 'zh_CN.UTF-8'

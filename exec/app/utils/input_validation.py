"""Device-independent validation for the existing INI update contract."""
import ipaddress
import re


def _integer(value, minimum, maximum):
    if type(value) is bool or not isinstance(value,(str,int)) or len(str(value))>5 or not re.fullmatch(r'[0-9]+',str(value)):
        raise ValueError('INVALID_INTEGER')
    result=int(value)
    if not minimum <= result <= maximum:
        raise ValueError('VALUE_OUT_OF_RANGE')
    return result


def validate_ini_payload(payload):
    # Capacities match logger/lib/app_config.h: SYS=2, SUB=4, PCS=4, BMS=10, MEASURE=10.
    if not isinstance(payload,dict):
        raise ValueError('INVALID_JSON')
    fields={'mainSystem','subSystem','pcsCount','bmsCount','pointToPointEnabled',
            'pcsList','bmsList','testCtlList','bmsBrand','pcsBrand','operatorName'}
    if set(payload)-fields:
        raise ValueError('UNKNOWN_CONFIGURATION_FIELD')
    result=dict(payload)
    for key,minimum,maximum in (('mainSystem',1,2),('subSystem',1,4),
                               ('pcsCount',0,4),('bmsCount',0,10),
                               ('bmsBrand',0,65535),('pcsBrand',0,65535)):
        if key in result:
            result[key]=_integer(result[key],minimum,maximum)
    if 'pointToPointEnabled' in result and type(result['pointToPointEnabled']) is not bool:
        raise ValueError('INVALID_BOOLEAN')
    for key,maximum in (('pcsList',4),('bmsList',10),('testCtlList',10)):
        if key not in result:
            continue
        values=result[key]
        if not isinstance(values,list) or len(values)>maximum:
            raise ValueError('INVALID_DEVICE_LIST')
        normalized=[]
        identifiers=set()
        for value in values:
            if not isinstance(value,dict) or set(value)-{'id','ip','port'}:
                raise ValueError('INVALID_DEVICE_ENTRY')
            identifier=_integer(value.get('id'),1,maximum)
            if identifier in identifiers:
                raise ValueError('DUPLICATE_DEVICE_ID')
            identifiers.add(identifier)
            if not isinstance(value.get('ip'),str):
                raise ValueError('INVALID_IP_ADDRESS')
            try:
                address=ipaddress.IPv4Address(value.get('ip'))
            except (ValueError,TypeError):
                raise ValueError('INVALID_IP_ADDRESS') from None
            if address.is_multicast or address.is_unspecified or address.is_loopback or str(address)=='255.255.255.255':
                raise ValueError('INVALID_IP_ADDRESS')
            normalized.append(dict(id=identifier,ip=str(address),port=_integer(value.get('port'),1,65535)))
        result[key]=normalized
    return result


def public_configuration(value):
    if isinstance(value,dict):
        return {key:public_configuration(item) for key,item in value.items() if not re.search(
            r'password|passwd|(?:^|_)pwd(?:$|_)|secret|private[_-]?key|token|api[_-]?key|salt',key,re.I)}
    if isinstance(value,list):
        return [public_configuration(item) for item in value]
    return value

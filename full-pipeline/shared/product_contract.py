"""Small, explicit JSON contract dialect shared by planning and trusted acceptance."""
import math
import re

SCHEMA_KEYS = {'type', 'properties', 'required', 'additionalProperties', 'items', 'enum',
               'minimum', 'maximum', 'minLength', 'maxLength', 'minItems', 'maxItems', 'description'}
TYPES = {'object', 'array', 'string', 'integer', 'number', 'boolean', 'null'}
REFERENCE = re.compile(r'\{\{([A-Za-z][A-Za-z0-9_]{0,47})\}\}')


def schema_types(schema):
    kind=schema.get('type')
    if isinstance(kind,str) and kind in TYPES: return [kind]
    if isinstance(kind,list) and len(kind)==2 and all(isinstance(x,str) and x in TYPES for x in kind) and 'null' in kind and len(set(kind))==2:
        return kind
    raise ValueError('Schema type must be explicit, optionally [type, null]')


def validate_schema(schema, depth=0):
    if depth > 8 or not isinstance(schema, dict):
        raise ValueError('JSON Schema requires an explicit supported type; maximum depth is 8')
    kinds=schema_types(schema)
    if set(schema) - SCHEMA_KEYS: raise ValueError('Unsupported JSON Schema keywords: '+str(set(schema)-SCHEMA_KEYS))
    properties = schema.get('properties', {})
    if not isinstance(properties, dict) or len(properties)>50: raise ValueError('Invalid schema properties')
    for child in properties.values(): validate_schema(child, depth+1)
    required = schema.get('required', [])
    if not isinstance(required,list) or any(not isinstance(key,str) or key not in properties for key in required):
        raise ValueError('Schema required must refer to properties')
    if 'additionalProperties' in schema and not isinstance(schema['additionalProperties'],bool):
        raise ValueError('additionalProperties must be boolean')
    if 'array' in kinds: validate_schema(schema.get('items'), depth+1)
    if 'enum' in schema and (not isinstance(schema['enum'],list) or not schema['enum']): raise ValueError('Invalid enum')
    for key in ('minimum','maximum','minLength','maxLength','minItems','maxItems'):
        if key in schema and (type(schema[key]) not in (int,float) or not math.isfinite(schema[key])):
            raise ValueError('Invalid schema bound: '+key)


def validate_value(value, schema, label='value', partial=False, references=False):
    if references and isinstance(value,str) and REFERENCE.fullmatch(value): return
    kinds=schema_types(schema)
    if value is None and 'null' in kinds:
        if 'enum' in schema and None not in schema['enum']: raise ValueError(label+': null is excluded by enum')
        return
    kind=next((kind for kind in kinds if kind!='null'),'null')
    valid={'object':isinstance(value,dict),'array':isinstance(value,list),'string':isinstance(value,str),
           'integer':type(value) is int,'number':type(value) in (int,float),
           'boolean':type(value) is bool,'null':value is None}[kind]
    if not valid: raise ValueError(label+': expected '+kind)
    if kind=='number' and not math.isfinite(value): raise ValueError(label+': number must be finite')
    if 'enum' in schema and value not in schema['enum']: raise ValueError(label+': invalid enum value')
    if kind=='object':
        properties=schema.get('properties',{})
        if not partial and set(schema.get('required',[]))-set(value): raise ValueError(label+': missing required fields')
        if schema.get('additionalProperties') is False and set(value)-set(properties): raise ValueError(label+': unknown fields')
        for key,item in value.items():
            if key in properties: validate_value(item,properties[key],label+'.'+key,partial,references)
    if kind=='array':
        for index,item in enumerate(value): validate_value(item,schema['items'],f'{label}[{index}]',partial,references)
    for minimum,maximum,size in [('minLength','maxLength',len(value) if kind=='string' else None),
                                 ('minItems','maxItems',len(value) if kind=='array' else None),
                                 ('minimum','maximum',value if kind in ('number','integer') else None)]:
        if partial and kind=='array': continue
        if size is not None and (minimum in schema and size<schema[minimum] or maximum in schema and size>schema[maximum]):
            raise ValueError(label+': outside contract bounds')


def endpoint_for(plan,method,path):
    path=path.split('?',1)[0]
    for endpoint in sorted(plan['endpoints'],key=lambda item:item['path'].count('{')):
        pattern=re.escape(endpoint['path'])
        pattern=re.sub(r'\\\{[A-Za-z][A-Za-z0-9_]*\\\}',r'[^/?]+',pattern)
        if endpoint['method']==method and re.fullmatch(pattern,path): return endpoint
    raise ValueError('Endpoint absent from frozen product contract: '+method+' '+path)


def resolve_references(value,variables):
    if isinstance(value,dict): return {key:resolve_references(item,variables) for key,item in value.items()}
    if isinstance(value,list): return [resolve_references(item,variables) for item in value]
    if not isinstance(value,str): return value
    def found(match):
        key=match.group(1)
        if key not in variables: raise ValueError('Unknown acceptance variable: '+key)
        return variables[key]
    match=REFERENCE.fullmatch(value)
    if match: return found(match)
    return REFERENCE.sub(lambda match:str(found(match)),value)


def validate_reference_types(value,schema,variables):
    if isinstance(value,str):
        reference=REFERENCE.fullmatch(value)
        if reference:
            source=variables.get(reference.group(1))
            if source is None: raise ValueError('Unknown acceptance capture')
            destinations=schema_types(schema)
            if source['type'] not in destinations and not (source['type']=='integer' and 'number' in destinations):
                raise ValueError('Captured value type contradicts its destination in the API contract')
    if isinstance(value,dict):
        for key,item in value.items():
            if key in schema.get('properties',{}): validate_reference_types(item,schema['properties'][key],variables)
    if isinstance(value,list):
        for item in value: validate_reference_types(item,schema['items'],variables)


def capture_schema(response_schema,path):
    current=response_schema
    for key in path.split('.'):
        if current['type']!='object' or key not in current.get('properties',{}) or key not in current.get('required',[]):
            raise ValueError('Capture must traverse required response properties: '+path)
        current=current['properties'][key]
    if not isinstance(current['type'],str) or current['type'] not in {'string','integer','number','boolean'}: raise ValueError('Capture must end in a non-null scalar value')
    return current

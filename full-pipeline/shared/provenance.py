"""Restore evidence quotes from original input without accepting invented quotations."""
import unicodedata


def normalized_source(text):
    characters=[]
    positions=[]
    index=0
    while index<len(text):
        end=index+1
        if text[index].isspace():
            while end<len(text) and text[end].isspace(): end+=1
            if characters and characters[-1]!=' ':
                characters.append(' ');positions.append((index,end))
        else:
            while end<len(text) and unicodedata.combining(text[end]): end+=1
            for character in unicodedata.normalize('NFC',text[index:end]):
                characters.append(character);positions.append((index,end))
        index=end
    if characters and characters[-1]==' ':
        characters.pop();positions.pop()
    return ''.join(characters),positions


def restore_source_quotes(spec,source):
    normalized,positions=normalized_source(source)
    audit=[]
    for requirement in spec.requirements:
        quote=requirement.sourceQuote
        if not quote:
            audit.append({'requirementId':requirement.id,'status':'not_provided'})
            continue
        if quote in source:
            audit.append({'requirementId':requirement.id,'status':'exact'})
            continue
        expected,_=normalized_source(quote)
        offset=normalized.find(expected) if expected else -1
        if offset>=0:
            start=positions[offset][0]
            end=positions[offset+len(expected)-1][1]
            requirement.sourceQuote=source[start:end]
            audit.append({'requirementId':requirement.id,'status':'restored_from_original',
                          'sourceStart':start,'sourceEnd':end})
        else:
            # sourceQuote is optional provenance, not a business acceptance condition.
            # Never retain a paraphrase as if it were a verified direct quotation.
            requirement.sourceQuote=''
            audit.append({'requirementId':requirement.id,'status':'unverified',
                          'reason':'Цитата модели не найдена в исходном тексте; точная ссылка не подтверждена'})
    return {'entries':audit,'unverifiedCount':sum(item['status']=='unverified' for item in audit),
            'restoredCount':sum(item['status']=='restored_from_original' for item in audit),
            'policy':'Original text preserved; whitespace/NFC equivalents restored to original substrings; unmatched quotes omitted and disclosed.'}

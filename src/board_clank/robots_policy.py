"""Conservative RFC9309 matching, independent of Python's robotparser version."""
import math
import re
from urllib.parse import urlsplit, quote, unquote_to_bytes


def normalized(value):
    # Decode only ASCII unreserved octets. Keep encoded reserved delimiters.
    value = re.sub(r'%([0-9a-fA-F]{2})', lambda m: chr(int(m[1],16))
        if chr(int(m[1],16)) in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-._~'
        else '%'+m[1].upper(), value)
    return quote(value, safe="/%?=&:+;,@!$'()*-._~")


class Robots:
    def __init__(self, text, agent='BoardClank'):
        text=text.removeprefix('\ufeff')
        groups=[]; agents=[]; rules=[]; delays=[]; rates=[]
        def flush():
            if agents:groups.append((list(agents),list(rules),list(delays),list(rates)))
        saw_record=False
        for line in text.splitlines()+['user-agent: __end__']:
            line=line.split('#',1)[0].strip()
            if ':' not in line:continue
            key,value=(v.strip() for v in line.split(':',1));key=key.lower()
            if key=='user-agent':
                if saw_record:
                    flush();agents=[];rules=[];delays=[];rates=[];saw_record=False
                agents.append(value.lower())
            elif agents and key in {'allow','disallow','crawl-delay','request-rate'}:
                saw_record=True
                if key in {'allow','disallow'} and value:
                    # Common leading-* extension is interpreted conservatively,
                    # e.g. Wix's *?lightbox= rule, rather than silently ignored.
                    if not value.startswith(('/','*')):raise ValueError('unqualified robots path')
                    rules.append((key=='allow',normalized(value)))
                elif key=='crawl-delay':
                    delay=float(value)
                    if not math.isfinite(delay) or delay<0:raise ValueError('invalid crawl delay')
                    delays.append(delay)
                elif key=='request-rate':
                    match=re.fullmatch(r'([1-9]\d*)/([1-9]\d*)',value)
                    if not match:raise ValueError('unqualified robots request rate')
                    rates.append(int(match[2])/int(match[1]))
        # Empty groups also apply; explicit matching agents take precedence over *.
        flush()
        specific=[g for g in groups if any(a!='*' and a in agent.lower() for a in g[0])]
        if specific:
            length=max(len(a) for g in specific for a in g[0] if a!='*' and a in agent.lower())
            selected=[g for g in specific if any(len(a)==length and a in agent.lower() for a in g[0])]
        else:selected=[g for g in groups if '*' in g[0]]
        self.rules=[r for g in selected for r in g[1]]
        self.min_interval=max([0]+[d for g in selected for d in g[2]+g[3]])

    def allows(self,url):
        p=urlsplit(url);path=normalized((p.path or '/')+('?' + p.query if p.query else ''))
        matches=[]
        for allow,pattern in self.rules:
            end=pattern.endswith('$');body=pattern[:-1] if end else pattern
            expression='^'+re.escape(body).replace(r'\*','.*')+('$' if end else '')
            if re.search(expression,path):matches.append((len(unquote_to_bytes(body.replace('*',''))),allow))
        return max(matches,default=(0,True))[1]

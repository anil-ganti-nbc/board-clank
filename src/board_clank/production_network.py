"""Process-scoped urllib guard, including redirects and collector worker threads."""
from contextlib import contextmanager
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import hashlib
import io
import threading
import time
from urllib import request as http
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.response import addinfourl

from board_clank.collectors.base import CollectorError
from board_clank.production_ledger import assert_running
from board_clank.robots_policy import Robots


class LimitedResponse:
    def __init__(self,response,limit,guard,record):
        self.response=response;self.limit=limit;self.used=0;self.guard=guard;self.record=record
        self.hash=hashlib.sha256();self.capture=None;self.on_close=None;self.closed=False
        if guard.capture_dir:
            guard.capture_dir.mkdir(parents=True,exist_ok=True)
            path=guard.capture_dir/(str(record['attempt'])+'.body')
            self.capture=path.open('xb');record['body_file']=str(path)
        record.update(body_complete=False,body_bytes=0)
    def __getattr__(self,key):return getattr(self.response,key)
    def __enter__(self):return self
    def __exit__(self,*args):self.close()
    def __del__(self):
        try:self.close()
        except Exception:pass
    def close(self):
        if self.closed:return
        self.closed=True
        try:
            self.response.close()
            if self.capture and not self.capture.closed:
                self.capture.flush();self.capture.close()
        finally:
            release=self.on_close;self.on_close=None
            if release:release()
    def read(self,size=-1):
        with self.guard.lock:
            remaining=min(self.limit-self.used,self.guard.budget.max_total_response_bytes-self.guard.bytes)
            wanted=min(size,remaining+1) if size>=0 else remaining+1
            data=self.response.read(wanted)
            self.used+=len(data);self.guard.bytes+=len(data)
            if len(data)>remaining:
                self.close();raise CollectorError('production response byte budget exhausted')
            if self.capture:self.capture.write(data)
            self.hash.update(data)
            self.record.update(body_sha256=self.hash.hexdigest(),body_bytes=self.used,
                               body_complete=len(data)<wanted or not data)
            if self.record['body_complete']:self.close()
            return data


class Guard:
    def __init__(self,source,budget,ledger,root,*,clock=time.monotonic,sleep=time.sleep,capture_dir=None):
        self.source=source;self.budget=budget;self.ledger=ledger;self.root=root
        self.clock=clock;self.sleep=sleep;self.deadline=clock()+budget.cycle_timeout_seconds
        self.count=0;self.last=None;self.lock=threading.RLock();self.robots={};self.requests=[];self.url_attempts={}
        self.bytes=0;self.capture_dir=capture_dir;self.robots_records={}
        self.semaphore=threading.BoundedSemaphore(budget.max_concurrency);self.local=threading.local()

    def remaining(self):
        assert_running(self.root)
        left=self.deadline-self.clock()
        if left<=0:raise CollectorError('production source deadline exhausted')
        return left

    def reserve(self,url,interval):
        with self.lock:
            left=self.remaining()
            wait=max(0,interval-(self.clock()-self.last)) if self.last is not None else 0
            if wait>=left:raise CollectorError('source spacing exceeds remaining deadline')
            if wait:self.sleep(wait)
            self.remaining()
            if self.count>=self.budget.max_requests_per_cycle:
                raise CollectorError('source cycle request budget exhausted')
            if self.bytes>=self.budget.max_total_response_bytes:
                raise CollectorError('source total byte budget exhausted')
            if self.url_attempts.get(url,0)>=self.budget.retries+1:
                raise CollectorError('source URL attempt budget exhausted')
            self.ledger.reserve(self.source,self.budget,hashlib.sha256(url.encode()).hexdigest())
            self.url_attempts[url]=self.url_attempts.get(url,0)+1
            self.count+=1;self.last=self.clock()
            record={'url':url,'attempt':self.count,'requested_utc':datetime.now(timezone.utc).isoformat()}
            self.requests.append(record)
            return record

    def open(self,original,opener,fullurl,data=None,timeout=http.socket._GLOBAL_DEFAULT_TIMEOUT):
        depth=getattr(self.local,'depth',0)
        outer=depth==0
        if outer and not self.semaphore.acquire(timeout=self.remaining()):
            raise CollectorError('source concurrency deadline exhausted')
        self.local.depth=depth+1
        try:
            response=self._open(original,opener,fullurl,data,timeout)
            if outer:
                if response.closed:self.semaphore.release()
                else:response.on_close=self.semaphore.release
            return response
        except BaseException:
            if outer:self.semaphore.release()
            raise
        finally:self.local.depth=depth

    def _open(self,original,opener,fullurl,data=None,timeout=http.socket._GLOBAL_DEFAULT_TIMEOUT):
        req=fullurl if isinstance(fullurl,http.Request) else http.Request(fullurl)
        url=req.full_url;p=urlsplit(url);origin=p.scheme+'://'+p.netloc
        if (origin not in self.budget.origins or p.username or p.password or p.fragment
                or req.get_method()!='GET' or data is not None or req.data is not None):
            raise CollectorError('production HTTP boundary refused')
        req.add_header('User-Agent','BoardClank/1.0 (production first-party PRODUCT)')
        robots_request=p.path=='/robots.txt' and not p.query
        policy=self.robots.get(origin)
        if not robots_request and (policy is None or not policy.allows(url)):
            raise CollectorError('robots policy absent or disallows selected URL')
        interval=max(self.budget.min_interval_seconds,policy.min_interval if policy else 0)
        attempts=self.budget.retries+1
        for attempt in range(attempts):
            record=self.reserve(url,interval)
            try:
                deadline=min(self.budget.timeout_seconds,self.remaining())
                if isinstance(timeout,(int,float)):deadline=min(deadline,timeout)
                response=original(opener,req,data,timeout=deadline)
                if isinstance(response,LimitedResponse):
                    # urllib's redirect recursion already wrapped the final body.
                    # Reuse it so bytes/captures are not counted twice.
                    record.update(status='REDIRECT_FOLLOWED',final_status=response.status,
                        final_url=response.geturl(),response_attempt=response.record['attempt'])
                    return response
                record.update(status=response.status,final_url=response.geturl())
                if response.status>=400:
                    status=response.status;headers=response.headers
                    response.close()
                    raise HTTPError(url,status,'source HTTP failure',headers,None)
                # Redirects are guarded by this same process hook before being followed.
                if response.geturl()!=url and robots_request:
                    response.close();raise CollectorError('robots redirect requires manual review')
                return LimitedResponse(response,min(self.budget.max_response_bytes,512000) if robots_request else self.budget.max_response_bytes,self,record)
            except HTTPError as exc:
                status=exc.code
                record['status']=status
                # Do not include a third-party response body in error logs.
                retry=exc.headers.get('Retry-After')
                exc.close()
                if status in {401,403}:
                    self.ledger.block_source(self.source,self.budget.access_evidence.sha256,status)
                if robots_request and status in {404,410} and self.budget.allow_missing_robots:
                    return LimitedResponse(addinfourl(io.BytesIO(b''),{},url,code=status),0,self,record)
                if status not in {429,502,503,504} or attempt+1==attempts:
                    raise CollectorError('source HTTP failure '+str(status)) from None
                delay=2**attempt
                if retry:
                    try:delay=max(delay,float(retry))
                    except ValueError:
                        try:delay=max(delay,parsedate_to_datetime(retry).timestamp()-time.time())
                        except (ValueError,TypeError):raise CollectorError('invalid source retry delay') from None
                if not 0<=delay<min(60,self.remaining()):
                    raise CollectorError('source retry delay exceeds bounded budget') from None
                self.sleep(delay)
            except OSError:
                # A GET can retry safely; every attempt consumes the same persistent budget.
                if attempt+1==attempts:raise CollectorError('source transport unavailable') from None
                delay=2**attempt
                if delay>=self.remaining():raise CollectorError('source retry deadline exhausted') from None
                self.sleep(delay)


@contextmanager
def guarded_http(guard):
    """Only use inside the dedicated source child process, never in a shared server."""
    # do_open returns each raw HTTP response before redirect/error processors
    # read its body. OpenerDirector.open is too high: it hides intermediate
    # response reads and can double-count a final redirected body.
    original=http.AbstractHTTPHandler.do_open
    def bounded(handler,http_class,req,**kwargs):
        def transport(_handler,request,data=None,timeout=http.socket._GLOBAL_DEFAULT_TIMEOUT):
            request.timeout=timeout
            return original(_handler,http_class,request,**kwargs)
        return guard.open(transport,handler,req,timeout=getattr(req,'timeout',http.socket._GLOBAL_DEFAULT_TIMEOUT))
    http.AbstractHTTPHandler.do_open=bounded
    try:
        class NoRobotsRedirect(http.HTTPRedirectHandler):
            def redirect_request(self,*args,**kwargs):
                raise CollectorError('robots redirect requires manual review')
        class MissingRobotsProcessor(http.HTTPErrorProcessor):
            def http_response(self,req,response):
                p=urlsplit(req.full_url)
                if (guard.budget.allow_missing_robots and response.status in {404,410}
                        and p.path=='/robots.txt' and not p.query):
                    return response  # Preserve404/410; do not manufacture an HTTP200.
                return super().http_response(req,response)
            https_response=http_response
        for origin in guard.budget.origins:
            with http.build_opener(NoRobotsRedirect(),MissingRobotsProcessor()).open(http.Request(origin+'/robots.txt',headers={'User-Agent':'BoardClank/1.0 (production PRODUCT; robots compliance)'})) as response:
                if response.status!=200 and not (response.status in {404,410} and guard.budget.allow_missing_robots):
                    raise CollectorError('robots requires successful policy response or explicit missing-policy approval')
                if response.status==200 and response.headers.get('Content-Type','').split(';')[0].lower() not in {'text/plain','text/x-robots'}:
                    raise CollectorError('robots policy response is not plain text')
                text=response.read().decode('utf-8')
                if '<html' in text.lower() or text.lstrip().startswith('<'):
                    raise CollectorError('robots challenge/document refused')
                guard.robots[origin]=Robots(text)
                guard.robots_records[origin]={'status':response.status,'body_sha256':hashlib.sha256(text.encode()).hexdigest(),
                    'missing_policy_explicitly_allowed':response.status!=200}
        yield guard
    finally:
        http.AbstractHTTPHandler.do_open=original

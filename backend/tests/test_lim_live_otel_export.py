"""OTLP wire-level proof without a third-party collector dependency."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from uuid import uuid4

from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

from app import lim_live_observability as obs


class Receiver(BaseHTTPRequestHandler):
    def do_POST(self):
        self.server.payloads.append((self.path, self.rfile.read(int(self.headers['Content-Length']))))
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *_):
        pass


def test_configured_otel_sends_parent_and_domain_over_otlp_http(monkeypatch):
    server = ThreadingHTTPServer(('127.0.0.1', 0), Receiver)
    server.payloads = []
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setenv('LIM_OTEL_TRACES_ENDPOINT',
                       f'http://127.0.0.1:{server.server_port}/v1/traces')
    monkeypatch.setattr(obs, '_tracer_override', None)
    monkeypatch.setattr(obs, '_otel_provider', None)
    monkeypatch.setattr(obs, '_otel_endpoint', None)
    try:
        run_id = str(uuid4())
        with obs.run_span(run_id, str(uuid4())):
            with obs.domain_span(run_id, 'inventory'):
                pass
        assert obs._otel_provider.force_flush(timeout_millis=5000)
        assert server.payloads
        assert all(path == '/v1/traces' for path, _ in server.payloads)
        spans = []
        for _, body in server.payloads:
            request = ExportTraceServiceRequest.FromString(body)
            spans.extend(span for resource in request.resource_spans
                         for scope in resource.scope_spans for span in scope.spans)
        root = next(span for span in spans if span.name == 'lim.live.run')
        child = next(span for span in spans if span.name == 'lim.live.domain.inventory')
        assert child.trace_id == root.trace_id
        assert child.parent_span_id == root.span_id
        assert next(attr.value.string_value for attr in root.attributes if attr.key == 'lim.run_id') == run_id
    finally:
        if obs._otel_provider is not None:
            obs._otel_provider.shutdown()
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

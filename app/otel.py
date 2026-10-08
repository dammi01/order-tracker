import logging
import os

from opentelemetry import trace, metrics
from opentelemetry._logs import set_logger_provider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.grpc._log_exporter import OTLPLogExporter
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

_RESOURCE = Resource.create({"service.name": "order-tracker"})


def setup_observability() -> None:
    # All three signals go to the OpenTelemetry Collector.
    # The endpoint comes from OTEL_EXPORTER_OTLP_ENDPOINT (set in compose.yaml).

    # Traces
    tracer_provider = TracerProvider(resource=_RESOURCE)
    tracer_provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # Metrics: export every 5s so Prometheus/Grafana react quickly
    reader = PeriodicExportingMetricReader(OTLPMetricExporter(), export_interval_millis=5000)
    metrics.set_meter_provider(MeterProvider(resource=_RESOURCE, metric_readers=[reader]))

    # Logs: inject trace_id/span_id into each record, then ship records via OTLP
    LoggingInstrumentor().instrument(set_logging_format=True)
    logging.basicConfig(level=logging.INFO)
    logger_provider = LoggerProvider(resource=_RESOURCE)
    logger_provider.add_log_record_processor(BatchLogRecordProcessor(OTLPLogExporter()))
    set_logger_provider(logger_provider)
    logging.getLogger().addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))

    # Automatic spans for each sqlite3 query
    SQLite3Instrumentor().instrument()

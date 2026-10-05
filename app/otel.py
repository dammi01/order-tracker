import logging

from opentelemetry import trace, metrics
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, ConsoleSpanExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import ConsoleMetricExporter, PeriodicExportingMetricReader
from opentelemetry.instrumentation.logging import LoggingInstrumentor
from opentelemetry.instrumentation.sqlite3 import SQLite3Instrumentor

_RESOURCE = Resource.create({"service.name": "order-tracker"})


def setup_observability() -> None:
    # Traces: SimpleSpanProcessor exporta na hora (bom pra ver no console em tempo real;
    # trocaremos por BatchSpanProcessor quando o Q3 mandar isso pro Collector).
    tracer_provider = TracerProvider(resource=_RESOURCE)
    tracer_provider.add_span_processor(SimpleSpanProcessor(ConsoleSpanExporter()))
    trace.set_tracer_provider(tracer_provider)

    # Metrics: ciclo de export a cada 5s
    reader = PeriodicExportingMetricReader(ConsoleMetricExporter(), export_interval_millis=5000)
    metrics.set_meter_provider(MeterProvider(resource=_RESOURCE, metric_readers=[reader]))

    # Logs: injeta trace_id/span_id em cada linha de log automaticamente
    LoggingInstrumentor().instrument(set_logging_format=True)
    logging.basicConfig(level=logging.INFO)

    # Spans automáticos para cada query sqlite3
    SQLite3Instrumentor().instrument()

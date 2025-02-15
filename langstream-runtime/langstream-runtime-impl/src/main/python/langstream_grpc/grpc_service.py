#
# Copyright DataStax, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#

import asyncio
import importlib
import json
import os
import logging
import threading
from concurrent.futures import Future
from io import BytesIO
from typing import Union, List, Tuple, Any, Optional, Dict, AsyncIterable

import fastavro
import grpc
import inspect

from langstream_grpc.proto import agent_pb2_grpc
from langstream_grpc.proto.agent_pb2 import (
    ProcessorRequest,
    Record as GrpcRecord,
    Value,
    Header,
    ProcessorResponse,
    ProcessorResult,
    Schema,
    InfoResponse,
    SourceRequest,
    SourceResponse,
    SinkRequest,
    SinkResponse,
)
from langstream_grpc.proto.agent_pb2_grpc import AgentServiceServicer
from .api import Source, Sink, Processor, Record, Agent, AgentContext
from .util import SimpleRecord, AvroValue


class RecordWithId(SimpleRecord):
    def __init__(
        self,
        record_id,
        value,
        key=None,
        headers: List[Tuple[str, Any]] = None,
        origin: str = None,
        timestamp: int = None,
    ):
        super().__init__(value, key, headers, origin, timestamp)
        self.record_id = record_id


def wrap_in_record(record):
    if isinstance(record, tuple) or isinstance(record, list):
        return SimpleRecord(*record)
    if isinstance(record, dict):
        return SimpleRecord(**record)
    return record


class AgentService(AgentServiceServicer):
    def __init__(self, agent: Union[Agent, Source, Sink, Processor]):
        self.agent = agent
        self.schema_id = 0
        self.schemas = {}
        self.client_schemas = {}

    async def agent_info(self, _, __):
        info = await acall_method_if_exists(self.agent, "agent_info") or {}
        return InfoResponse(json_info=json.dumps(info))

    async def get_topic_producer_records(self, request_iterator, context):
        # TODO: to be implemented
        async for _ in request_iterator:
            yield

    async def read(self, requests: AsyncIterable[SourceRequest], _):
        read_records = {}
        op_result = []
        last_record_id = 0
        read_requests_task = asyncio.create_task(
            self.handle_read_requests(requests, read_records, op_result)
        )
        while True:
            if len(op_result) > 0:
                if op_result[0] is True:
                    break
                raise op_result[0]
            records = await asyncio.to_thread(self.agent.read)
            if len(records) > 0:
                records = [wrap_in_record(record) for record in records]
                grpc_records = []
                for record in records:
                    schemas, grpc_record = self.to_grpc_record(record)
                    for schema in schemas:
                        yield SourceResponse(schema=schema)
                    grpc_records.append(grpc_record)
                for i, record in enumerate(records):
                    last_record_id += 1
                    grpc_records[i].record_id = last_record_id
                    read_records[last_record_id] = record
                yield SourceResponse(records=grpc_records)
        read_requests_task.cancel()

    async def handle_read_requests(
        self,
        requests: AsyncIterable[SourceRequest],
        read_records: Dict[int, Record],
        read_result,
    ):
        try:
            async for request in requests:
                if len(request.committed_records) > 0:
                    for record_id in request.committed_records:
                        record = read_records.pop(record_id, None)
                        if record is not None:
                            await acall_method_if_exists(self.agent, "commit", record)
                if request.HasField("permanent_failure"):
                    failure = request.permanent_failure
                    record = read_records.pop(failure.record_id, None)
                    await acall_method_if_exists(
                        self.agent,
                        "permanent_failure",
                        record,
                        RuntimeError(failure.error_message),
                    )
            read_result.append(True)
        except Exception as e:
            read_result.append(e)

    async def process(self, requests: AsyncIterable[ProcessorRequest], _):
        async for request in requests:
            if request.HasField("schema"):
                schema = fastavro.parse_schema(json.loads(request.schema.value))
                self.client_schemas[request.schema.schema_id] = schema
            if len(request.records) > 0:
                for source_record in request.records:
                    grpc_result = ProcessorResult(record_id=source_record.record_id)
                    try:
                        processed_records = await asyncio.to_thread(
                            self.agent.process, self.from_grpc_record(source_record)
                        )
                        if isinstance(processed_records, Future):
                            processed_records = await asyncio.wrap_future(
                                processed_records
                            )
                        for record in processed_records:
                            schemas, grpc_record = self.to_grpc_record(
                                wrap_in_record(record)
                            )
                            for schema in schemas:
                                yield ProcessorResponse(schema=schema)
                            grpc_result.records.append(grpc_record)
                        yield ProcessorResponse(results=[grpc_result])
                    except Exception as e:
                        grpc_result.error = str(e)
                        yield ProcessorResponse(results=[grpc_result])

    async def write(self, requests: AsyncIterable[SinkRequest], context):
        async for request in requests:
            if request.HasField("schema"):
                schema = fastavro.parse_schema(json.loads(request.schema.value))
                self.client_schemas[request.schema.schema_id] = schema
            if request.HasField("record"):
                try:
                    result = await asyncio.to_thread(
                        self.agent.write, self.from_grpc_record(request.record)
                    )
                    if isinstance(result, Future):
                        await asyncio.wrap_future(result)
                    yield SinkResponse(record_id=request.record.record_id)
                except Exception as e:
                    yield SinkResponse(record_id=request.record.record_id, error=str(e))

    def from_grpc_record(self, record: GrpcRecord) -> SimpleRecord:
        return RecordWithId(
            record_id=record.record_id,
            value=self.from_grpc_value(record.value),
            key=self.from_grpc_value(record.key),
            headers=[(h.name, self.from_grpc_value(h.value)) for h in record.headers],
            origin=record.origin if record.origin != "" else None,
            timestamp=record.timestamp if record.HasField("timestamp") else None,
        )

    def from_grpc_value(self, value: Value):
        if value is None or value.WhichOneof("type_oneof") is None:
            return None
        if value.HasField("avro_value"):
            schema = self.client_schemas[value.schema_id]
            avro_value = BytesIO(value.avro_value)
            try:
                return AvroValue(
                    schema=schema, value=fastavro.schemaless_reader(avro_value, schema)
                )
            finally:
                avro_value.close()
        if value.HasField("json_value"):
            return json.loads(value.json_value)
        return getattr(value, value.WhichOneof("type_oneof"))

    def to_grpc_record(self, record: Record) -> Tuple[List[Schema], GrpcRecord]:
        schemas = []
        schema, value = self.to_grpc_value(record.value())
        if schema is not None:
            schemas.append(schema)
        schema, key = self.to_grpc_value(record.key())
        if schema is not None:
            schemas.append(schema)
        headers = []
        for name, header_value in record.headers():
            schema, grpc_header_value = self.to_grpc_value(header_value)
            if schema is not None:
                schemas.append(schema)
            headers.append(Header(name=name, value=grpc_header_value))
        return schemas, GrpcRecord(
            value=value,
            key=key,
            headers=headers,
            origin=record.origin(),
            timestamp=record.timestamp(),
        )

    def to_grpc_value(self, value) -> Tuple[Optional[Schema], Optional[Value]]:
        if value is None:
            return None, None
        grpc_value = Value()
        grpc_schema = None
        if isinstance(value, bytes):
            grpc_value.bytes_value = value
        elif isinstance(value, str):
            grpc_value.string_value = value
        elif isinstance(value, bool):
            grpc_value.boolean_value = value
        elif isinstance(value, int):
            grpc_value.long_value = value
        elif isinstance(value, float):
            grpc_value.double_value = value
        elif type(value).__name__ == "AvroValue":
            schema_str = fastavro.schema.to_parsing_canonical_form(value.schema)
            if schema_str not in self.schemas:
                self.schema_id += 1
                self.schemas[schema_str] = self.schema_id
                grpc_schema = Schema(
                    schema_id=self.schema_id, value=schema_str.encode("utf-8")
                )
            fp = BytesIO()
            try:
                fastavro.schemaless_writer(fp, value.schema, value.value)
                grpc_value.avro_value = fp.getvalue()
                grpc_value.schema_id = self.schema_id
            finally:
                fp.close()
        elif isinstance(value, dict) or isinstance(value, list):
            grpc_value.json_value = json.dumps(value)
        else:
            raise TypeError(f"Got unsupported type {type(value)}")
        return grpc_schema, grpc_value


def call_method_if_exists(klass, method, *args, **kwargs):
    method = getattr(klass, method, None)
    if callable(method):
        defined_positional_parameters_count = len(inspect.signature(method).parameters)
        if defined_positional_parameters_count >= len(args):
            return method(*args, **kwargs)
        else:
            return method(*args[:defined_positional_parameters_count], **kwargs)
    return None


async def acall_method_if_exists(klass, method, *args, **kwargs):
    return await asyncio.to_thread(
        call_method_if_exists, klass, method, *args, **kwargs
    )


class MainExecutor(threading.Thread):
    def __init__(self, onError, klass, method, *args, **kwargs):
        threading.Thread.__init__(self)
        self.onError = onError
        self.method = method
        self.klass = klass
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            logging.info("Starting main method from thread")
            call_method_if_exists(self.klass, self.method, *self.args, **self.kwargs)
        except Exception as e:
            logging.error(e)
            self.onError()


def call_method_new_thread_if_exists(klass, method_name, *args, **kwargs):
    method = getattr(klass, method_name, None)
    if callable(method):
        executor = MainExecutor(crash_process, klass, method_name, *args, **kwargs)
        executor.start()
        return True

    return False


def crash_process():
    logging.error("Main method with an error. Exiting process.")
    os.exit(1)


async def init_agent(configuration, context) -> Agent:
    full_class_name = configuration["className"]
    class_name = full_class_name.split(".")[-1]
    module_name = full_class_name[: -len(class_name) - 1]
    module = importlib.import_module(module_name)
    agent = getattr(module, class_name)()
    context_impl = DefaultAgentContext(configuration, context)
    await acall_method_if_exists(agent, "init", configuration, context_impl)
    return agent


class DefaultAgentContext(AgentContext):
    def __init__(self, configuration: dict, context: dict):
        self.configuration = configuration
        self.context = context

    def get_persistent_state_directory(self) -> Optional[str]:
        return self.context.get("persistentStateDirectory")


class AgentServer(object):
    def __init__(self, target: str):
        self.target = target
        self.grpc_server = grpc.aio.server()
        self.port = self.grpc_server.add_insecure_port(target)
        self.agent = None

    async def init(self, config, context):
        configuration = json.loads(config)
        logging.debug("Configuration: " + json.dumps(configuration))
        environment = configuration.get("environment", [])
        logging.debug("Environment: " + json.dumps(environment))
        for env in environment:
            key = env["key"]
            value = env["value"]
            logging.debug(f"Setting environment variable {key}={value}")
            os.environ[key] = value
        self.agent = await init_agent(configuration, json.loads(context))

    async def start(self):
        await acall_method_if_exists(self.agent, "start")
        call_method_new_thread_if_exists(self.agent, "main", crash_process)

        agent_pb2_grpc.add_AgentServiceServicer_to_server(
            AgentService(self.agent), self.grpc_server
        )

        await self.grpc_server.start()
        logging.info("GRPC Server started, listening on " + self.target)

    async def stop(self):
        await self.grpc_server.stop(None)
        await acall_method_if_exists(self.agent, "close")

#!/usr/bin/env python3
#
# Source-only drift check for streaming transfer compatibility research.

import argparse
import glob
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

TARGET_DOCS = (
    "research/module-streaming-transfer-compatibility-matrix.md",
    "research/module-streaming-transfer-compatibility-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "streaming_handshake_framing_contract",
    "streaming_ssl_optional_fallback_contract",
    "streaming_inbound_tls_policy_contract",
    "streaming_control_file_channel_contract",
    "streaming_file_semaphore_keepalive_contract",
    "streaming_tls_zero_copy_fallback_contract",
    "streaming_internode_compression_boundary",
    "streaming_stream_compression_format_contract",
    "streaming_outgoing_file_header_contract",
    "streaming_partial_uncompressed_contract",
    "streaming_partial_compressed_contract",
    "streaming_entire_sstable_contract",
    "streaming_state_netstats_observability_contract",
    "streaming_receive_failure_contract",
    "streaming_existing_tests_baseline",
    "streaming_mixed_tls_compression_gap",
)

SOURCE_TOKEN_CHECKS = {
    "src/java/org/apache/cassandra/streaming/async/NettyStreamingConnectionFactory.java": (
        "public class NettyStreamingConnectionFactory implements StreamingChannel.Factory",
        "public static int MAX_CONNECT_ATTEMPTS = 3;",
        "template.withDefaults(ConnectionCategory.STREAMING)",
        "settings.withEncryption() && settings.encryption.getOptional()",
        "Arrays.asList(SslFallbackConnectionType.values())",
        "initiateStreaming(eventLoop, settings, sslFallbackConnectionType)",
        "new NettyStreamingChannel(channel, kind)",
        "if (!isSSLError(cause))",
        "throw new IOException(\"failed to connect to \" + template.to + \" for streaming data\", cause);",
    ),
    "src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java": (
        "public enum SslFallbackConnectionType",
        "SERVER_CONFIG",
        "MTLS",
        "SSL",
        "NO_SSL",
        "settings.withEncryption()",
        "SslContext sslContext = getSslContext(sslConnectionType);",
        "pipeline.addFirst(SSL_HANDLER_NAME, sslHandler);",
        "pipeline.addLast(\"server-authentication\", new ServerAuthenticationHandler(settings));",
    ),
    "src/java/org/apache/cassandra/net/InboundConnectionInitiator.java": (
        "switch(settings.encryption.tlsEncryptionPolicy())",
        "case UNENCRYPTED:",
        "new RejectSslHandler()",
        "case OPTIONAL:",
        "new OptionalSslHandler(settings.encryption)",
        "case ENCRYPTED:",
        "getSslHandler(\"creating\", channel, settings.encryption)",
        "private void setupStreamingPipeline",
        "assert initiate.framing == Framing.UNPROTECTED;",
        "new NettyStreamingChannel(channel, StreamingChannel.Kind.CONTROL)",
        "pipeline.replace(this, \"streamInbound\", streamingChannel);",
        "new StreamDeserializingTask(null, streamingChannel, current_version)",
        "streaming connection established, version = {}, framing = {}, encryption = {}",
        "FrameDecoderLZ4.fast(allocator)",
        "FrameDecoderCrc.create(allocator)",
        "new FrameDecoderUnprotected(allocator)",
    ),
    "src/java/org/apache/cassandra/net/HandshakeProtocol.java": (
        "The initial message sent when a node creates a new connection to a remote peer.",
        "whether it is for streaming or for messaging",
        "CMP - compression enabled bit",
        "MOD - connection mode",
        "final ConnectionType type;",
        "final Framing framing;",
        "private int encodeFlags()",
        "if (type.isStreaming())",
        "flags |= 1 << 3;",
        "flags |= ((framing.id & 1) << 2) | ((framing.id & 2) << 3);",
        "flags |= (acceptVersions.min << 16);",
        "flags |= (acceptVersions.max << 24);",
    ),
    "src/java/org/apache/cassandra/streaming/async/NettyStreamingChannel.java": (
        "static final AttributeKey<Boolean> TRANSFERRING_FILE_ATTR",
        "new AsyncStreamingInputPlus(channel)",
        "compareAndSet(false, true)",
        "throw new IllegalStateException(\"channel's transferring state is currently set to true. refusing to start new stream\");",
        "new AsyncStreamingOutputPlus(channel)",
        "channel.attr(TRANSFERRING_FILE_ATTR).set(FALSE)",
    ),
    "src/java/org/apache/cassandra/streaming/async/StreamingMultiplexedChannel.java": (
        "public class StreamingMultiplexedChannel",
        "DEFAULT_MAX_PARALLEL_TRANSFERS",
        "sendControlMessage(StreamMessage message)",
        "public Future<?> sendMessage(StreamingChannel channel, StreamMessage message)",
        "if (message instanceof OutgoingStreamMessage)",
        "Cannot send stream data messages for preview streaming sessions",
        "new FileStreamTask((OutgoingStreamMessage) message, connectTo)",
        "public void run()",
        "if (!acquirePermit(",
        "channel = getOrCreateFileChannel(connectTo);",
        "try (StreamingDataOutputPlus out = channel.acquireOut())",
        "serialize(msg, out, messagingVersion, session);",
        "session.onError(e);",
        "fileTransferSemaphore.release(1);",
    ),
    "src/java/org/apache/cassandra/net/AsyncStreamingOutputPlus.java": (
        "For zero-copy-streaming, 1MiB at a time",
        "For streaming with SSL, 64KiB at a time",
        "channel.pipeline().get(SslHandler.class) != null",
        "return writeFileToChannel(file, limiter, 1 << 16);",
        "return writeFileToChannelZeroCopy(file, limiter, 1 << 20, 1 << 20, 2 << 20);",
    ),
    "src/java/org/apache/cassandra/db/streaming/package-info.java": (
        "uncompressed sstable",
        "compressed sstable, transferred with SSL/TLS",
        "compressed sstable, transferred without SSL/TLS",
        "StreamCompressionSerializer",
        "send them both over the same socket",
    ),
    "src/java/org/apache/cassandra/streaming/async/StreamCompressionSerializer.java": (
        "int - compressed payload length",
        "int - uncompressed payload length",
        "private static final int HEADER_LENGTH = 8;",
        "public static StreamingDataOutputPlus.Write serialize",
        "out.putInt(0, compressedLength);",
        "out.putInt(4, uncompressedLength);",
        "public ByteBuf deserialize",
        "final int compressedLength = in.readInt();",
        "final int uncompressedLength = in.readInt();",
        "if (in instanceof ReadableByteChannel)",
        "decompressor.decompress(compressedNioBuffer, uncompressedNioBuffer);",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraOutgoingFile.java": (
        "private static CassandraStreamHeader makeHeader",
        "CompressionInfo.newLazyInstance",
        "withSSTableVersion",
        "withCompressionInfo",
        "isEntireSSTable(shouldStreamEntireSSTable)",
        "withComponentManifest",
        "public void write(StreamSession session, StreamingDataOutputPlus out, int version)",
        "if (shouldStreamEntireSSTable)",
        "new CassandraEntireSSTableStreamWriter",
        "header.isCompressed() ?",
        "new CassandraCompressedStreamWriter",
        "new CassandraStreamWriter",
        "public boolean computeShouldStreamEntireSSTables()",
        "!DatabaseDescriptor.streamEntireSSTables()",
        "hasLegacyCounterShards",
        "descriptor.version.hasOldBfFormat()",
        "return contained(sections, ref.get());",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraStreamHeader.java": (
        "public long calculateSize()",
        "if (isEntireSSTable)",
        "if (compressionInfo != null)",
        "public static final IVersionedSerializer<CassandraStreamHeader> serializer",
        "out.writeUTF(header.version.toString());",
        "out.writeUTF(header.version.format.name());",
        "CompressionInfo.serializer.serialize",
        "out.writeBoolean(header.isEntireSSTable);",
        "ComponentManifest.serializers.get(header.version.format.name()).serialize",
        "DatabaseDescriptor.getSSTableFormats().get(formatName)",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraIncomingFile.java": (
        "CassandraStreamHeader.serializer.deserialize",
        "session.countStreamedIn(streamHeader.isEntireSSTable);",
        "if (streamHeader.isEntireSSTable)",
        "new CassandraEntireSSTableStreamReader",
        "else if (streamHeader.isCompressed())",
        "new CassandraCompressedStreamReader",
        "new CassandraStreamReader",
        "size = streamHeader.size();",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraStreamWriter.java": (
        "private static final int DEFAULT_CHUNK_SIZE = 64 * 1024;",
        "private final LZ4Compressor compressor",
        "public void write(StreamingDataOutputPlus out)",
        "ChecksumValidator validator",
        "session.progress(filename, ProgressInfo.Direction.OUT",
        "StreamCompressionSerializer.serialize(compressor, buffer, current_version)",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraStreamReader.java": (
        "try (StreamCompressionInputStream streamCompressionInputStream",
        "new TrackedDataInputPlus(streamCompressionInputStream)",
        "writer = createWriter",
        "deserializer = getDeserializer",
        "session.progress(sequenceName, ProgressInfo.Direction.IN",
        "new RangeAwareSSTableWriter",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamWriter.java": (
        "public class CassandraCompressedStreamWriter extends CassandraStreamWriter",
        "private final CompressionInfo compressionInfo;",
        "List<Section> sections = fuseAdjacentChunks(compressionInfo.chunks());",
        "out.writeToChannel(bufferSupplier ->",
        "session.progress(filename, ProgressInfo.Direction.OUT",
        "private List<Section> fuseAdjacentChunks",
        "CRC_LENGTH",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraCompressedStreamReader.java": (
        "public class CassandraCompressedStreamReader extends CassandraStreamReader",
        "new CompressedInputStream(inputPlus, compressionInfo, ChecksumType.CRC32",
        "cis.position(section.lowerPosition);",
        "session.progress(sectionName, ProgressInfo.Direction.IN",
        "return compressionInfo.getTotalSize();",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamWriter.java": (
        "public class CassandraEntireSSTableStreamWriter",
        "StreamManager.getEntireSSTableRateLimiter(session.peer)",
        "for (Component component : manifest.components())",
        "FileChannel channel = context.channel(sstable.descriptor, component, length);",
        "out.writeFileToChannel(channel, limiter);",
        "session.progress(sstable.descriptor.fileFor(component).toString(), ProgressInfo.Direction.OUT",
    ),
    "src/java/org/apache/cassandra/db/streaming/CassandraEntireSSTableStreamReader.java": (
        "public class CassandraEntireSSTableStreamReader implements IStreamReader",
        "ComponentManifest manifest = header.componentManifest;",
        "SSTableZeroCopyWriter writer",
        "for (Component component : manifest.components())",
        "writer.writeComponent(component, in, length);",
        "session.progress(writer.descriptor.fileFor(component).toString(), ProgressInfo.Direction.IN",
        "createZeroCopyWriter",
    ),
    "src/java/org/apache/cassandra/streaming/messages/IncomingStreamMessage.java": (
        "StreamManager.instance.findSession",
        "ColumnFamilyStore.getIfExists(header.tableId)",
        "throw new StreamReceiveException(session",
        "prepareIncomingStream(session, header)",
        "incomingData.read(input, version);",
        "stream.session().attachInbound(channel);",
    ),
    "src/java/org/apache/cassandra/streaming/messages/OutgoingStreamMessage.java": (
        "public class OutgoingStreamMessage extends StreamMessage",
        "message.startTransfer();",
        "message.serialize(out, version, session);",
        "session.streamSent(message);",
        "message.finishTransfer();",
        "StreamMessageHeader.serializer.serialize(header, out, version);",
        "stream.write(session, out, version);",
    ),
    "src/java/org/apache/cassandra/streaming/StreamDeserializingTask.java": (
        "public class StreamDeserializingTask implements Runnable",
        "while (null != (message = StreamMessage.deserialize(input, messagingVersion)))",
        "if (message instanceof KeepAliveMessage)",
        "session = deriveSession(message);",
        "session.messageReceived(message);",
        "session.onError(t);",
        "channel.close();",
    ),
    "src/java/org/apache/cassandra/streaming/StreamingState.java": (
        "public float progress()",
        "public String failureCause()",
        "public String successMessage()",
        "table.add(\"failure_cause\", failureCause());",
        "table.add(\"success_message\", successMessage());",
        "case FILE_PROGRESS:",
        "streamProgress((StreamEvent.ProgressEvent) event);",
    ),
    "src/java/org/apache/cassandra/db/virtual/StreamingVirtualTable.java": (
        "StreamManager.instance.getStreamingStates()",
        "StreamingState state = StreamManager.instance.getStreamingState(id);",
        "ds.column(\"failure_cause\", state.failureCause());",
        "ds.column(\"success_message\", state.successMessage());",
        "state.sessions().update(ds);",
    ),
    "src/java/org/apache/cassandra/tools/nodetool/NetStats.java": (
        "@Command(name = \"netstats\"",
        "Set<StreamState> statuses = probe.getStreamStatus();",
        "Not sending any streams.",
        "printReceivingSummaries",
        "printSendingSummaries",
        "Receiving %d files",
        "Sending %d files",
    ),
    "src/java/org/apache/cassandra/metrics/StreamingMetrics.java": (
        "public class StreamingMetrics",
        "TotalIncomingBytes",
        "TotalOutgoingBytes",
        "TotalOutgoingRepairBytes",
        "TotalOutgoingRepairSSTables",
        "EntireSSTablesStreamedIn",
        "PartialSSTablesStreamedIn",
        "public void countStreamedIn(boolean isEntireSSTable)",
    ),
    "src/java/org/apache/cassandra/config/Config.java": (
        "public volatile DataRateSpec.LongBytesPerSecondBound stream_throughput_outbound",
        "public volatile DataRateSpec.LongBytesPerSecondBound inter_dc_stream_throughput_outbound",
        "public volatile DataRateSpec.LongBytesPerSecondBound entire_sstable_stream_throughput_outbound",
        "public boolean stream_entire_sstables = true;",
        "public volatile boolean streaming_stats_enabled = true;",
        "public InternodeCompression internode_compression = InternodeCompression.none;",
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "public static boolean streamEntireSSTables()",
        "public static boolean setStreamEntireSSTables(boolean value)",
        "public static Config.InternodeCompression internodeCompression()",
        "public static void setInternodeCompression(Config.InternodeCompression compression)",
        "public static boolean getStreamingStatsEnabled()",
        "public static void setStreamingStatsEnabled(boolean streamingStatsEnabled)",
    ),
    "conf/cassandra.yaml": (
        "server_encryption_options:",
        "internode_encryption: none",
        "stream_entire_sstables: true",
        "stream_throughput_outbound: 24MiB/s",
        "streaming_stats_enabled: true",
        "internode_compression: dc",
    ),
}

TEST_TOKEN_CHECKS = {
    "test/unit/org/apache/cassandra/streaming/async/StreamCompressionSerializerTest.java": (
        "public class StreamCompressionSerializerTest",
        "roundTrip_HappyPath_NotReadabaleByteBuffer",
        "StreamCompressionSerializer.serialize(compressor, input, VERSION)",
        "serializer.deserialize(decompressor",
        "roundTrip_HappyPath_ReadabaleByteBuffer",
        "extends DataInputBuffer implements ReadableByteChannel",
    ),
    "test/unit/org/apache/cassandra/streaming/async/StreamingMultiplexedChannelTest.java": (
        "FileStreamTask_acquirePermit_closed",
        "FileStreamTask_acquirePermit_HapppyPath",
        "FileStreamTask_BadChannelAttr",
        "Assert.assertEquals(StreamSession.State.FAILED, session.state())",
        "FileStreamTask_HappyPath",
        "onControlMessageComplete_Exception",
    ),
    "test/unit/org/apache/cassandra/streaming/EntireSSTableStreamingCorrectFilesCountTest.java": (
        "public class EntireSSTableStreamingCorrectFilesCountTest",
        "streaming of entire SSTables works currently only with this strategy",
        "outgoingStream.write(session, out, MessagingService.VERSION_40);",
        "getTotalNumberOfFiles()",
        "ComponentManifest.create(sstable).components().size()",
    ),
    "test/unit/org/apache/cassandra/net/AsyncStreamingOutputPlusTest.java": (
        "public class AsyncStreamingOutputPlusTest",
        "public void testSuccess()",
        "out.writeToChannel(alloc ->",
        "assertEquals(40, out.position())",
    ),
    "test/unit/org/apache/cassandra/net/HandshakeTest.java": (
        "testOutboundConnectionDoesntFallbackWhenErrorIsNotSSLRelated",
        "testOutboundFallbackOnSSLHandshakeFailure",
        "SslFallbackConnectionType",
        "withInternodeEncryption(ServerEncryptionOptions.InternodeEncryption.all)",
        "OutboundConnectionSettings(endpoint)",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/AbstractNetstatsStreaming.java": (
        "public abstract class AbstractNetstatsStreaming",
        "NetstatsOutputParser",
        "filter(output -> output.contains(\"Receiving\") || output.contains(\"Sending\"))",
        "public static void validate",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithEntireSSTablesCompressionStreamingTest.java": (
        "testWithStreamingEntireSSTablesWithCompression",
        "testWithStreamingEntireSSTablesWithoutCompression",
        "testWithStreamingEntireSSTablesWithoutCompressionWithoutThrottling",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/NetstatsBootstrapWithoutEntireSSTablesCompressionStreamingTest.java": (
        "testWithoutStreamingEntireSSTablesWithCompression",
        "testWithoutStreamingEntireSSTablesWithoutCompression",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/NetstatsRepairStreamingTest.java": (
        "testWithCompressionEnabled",
        "testWithCompressionDisabled",
        "stream_entire_sstables",
        "nodetoolResult(\"repair\", \"netstats_test\")",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/streaming/StreamingStatsDisabledTest.java": (
        "streaming_stats_enabled",
        "SELECT * FROM system_views.streaming",
        "StreamManager.instance.setStreamingStatsEnabled(true)",
        "nodetoolResult(\"repair\", KEYSPACE)",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/sai/IndexStreamingTest.java": (
        "public class IndexStreamingTest",
        "stream_entire_sstables",
        "streaming_slow_events_log_timeout",
        "SELECT * FROM system_views.streaming",
        "progress_percentage",
        "files_sent",
        "files_received",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java": (
        "public class InternodeEncryptionOptionsTest",
        "optionalTlsConnectionAllowedWithKeystoreTest",
        "tlsConnectionRejectedWhenUnencrypted",
        "allInternodeEncryptionEstablishedTest",
        "server_encryption_options",
        "SELECT successful_connection_attempts, address, port FROM system_views.internode_outbound",
    ),
    "test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java": (
        "internode_compression",
        "Config.InternodeCompression.dc",
    ),
}

DOC_REQUIRED_TOKENS = (
    "NettyStreamingConnectionFactory",
    "HandshakeProtocol",
    "InboundConnectionInitiator",
    "OutboundConnectionInitiator",
    "StreamingMultiplexedChannel",
    "NettyStreamingChannel",
    "AsyncStreamingOutputPlus",
    "StreamCompressionSerializer",
    "CassandraOutgoingFile",
    "CassandraStreamHeader",
    "CassandraIncomingFile",
    "CassandraStreamWriter",
    "CassandraCompressedStreamWriter",
    "CassandraEntireSSTableStreamWriter",
    "CassandraStreamReader",
    "CassandraCompressedStreamReader",
    "CassandraEntireSSTableStreamReader",
    "IncomingStreamMessage",
    "OutgoingStreamMessage",
    "StreamDeserializingTask",
    "StreamingState",
    "StreamingVirtualTable",
    "NetStats",
    "StreamingMetrics",
    "stream_entire_sstables",
    "server_encryption_options",
    "internode_compression",
    "StreamingMultiplexedChannelTest",
    "StreamCompressionSerializerTest",
    "EntireSSTableStreamingCorrectFilesCountTest",
    "NetstatsRepairStreamingTest",
    "IndexStreamingTest",
    "InternodeEncryptionOptionsTest",
    "HandshakeTest",
    "JVMDTestTest",
)

STREAMING_TEST_MARKERS = re.compile(
    r"StreamPlan|StreamSession|Streaming|stream_entire_sstables|system_views\.streaming|"
    r"Netstats|nodetoolResult\(\"repair\"|nodetoolResult\(\"rebuild\"|bootstrap",
    re.IGNORECASE,
)
TLS_TEST_MARKERS = re.compile(
    r"server_encryption_options|InternodeEncryption|withInternodeEncryption|SslFallbackConnectionType|"
    r"optionalTls|TLS|SslHandler",
    re.IGNORECASE,
)
INTERNODE_COMPRESSION_MARKERS = re.compile(
    r"internode_compression|Config\.InternodeCompression|InternodeCompression",
    re.IGNORECASE,
)
MIXED_VERSION_MARKERS = re.compile(
    r"UpgradeableCluster|MixedMode|upgradesToCurrentFrom|upgrades\(|Versions\.|upgrade",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CheckResult:
    name: str
    source: str
    ok: bool
    detail: str = ""


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def token_checks(groups: dict[str, tuple[str, ...]], category: str) -> list[CheckResult]:
    results: list[CheckResult] = []
    for path, tokens in groups.items():
        text = read(path)
        for token in tokens:
            results.append(CheckResult(f"{category}: {token}", path, token in text))
    return results


def doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[CheckResult]:
    text = doc_text()
    results = [
        CheckResult(f"doc scenario: {scenario}", "research docs", scenario in text)
        for scenario in SCENARIO_IDS
    ]
    results.extend(
        CheckResult(f"doc token: {token}", "research docs", token in text)
        for token in DOC_REQUIRED_TOKENS
    )
    return results


def mixed_tls_compression_streaming_candidates() -> list[str]:
    candidates: list[str] = []
    for path in glob.glob(str(REPO_ROOT / "test/distributed/**/*.java"), recursive=True):
        rel = str(Path(path).relative_to(REPO_ROOT))
        text = Path(path).read_text(encoding="utf-8")
        if (
            STREAMING_TEST_MARKERS.search(text)
            and TLS_TEST_MARKERS.search(text)
            and INTERNODE_COMPRESSION_MARKERS.search(text)
            and MIXED_VERSION_MARKERS.search(text)
        ):
            candidates.append(rel)
    return sorted(candidates)


def gap_checks() -> list[CheckResult]:
    candidates = mixed_tls_compression_streaming_candidates()
    return [
        CheckResult(
            "distributed mixed-version TLS internode_compression streaming gap unchanged",
            "test/distributed/**/*.java",
            not candidates,
            ", ".join(candidates),
        )
    ]


def run_checks() -> dict[str, list[CheckResult]]:
    return {
        "source": token_checks(SOURCE_TOKEN_CHECKS, "source"),
        "test": token_checks(TEST_TOKEN_CHECKS, "test"),
        "gap": gap_checks(),
        "doc": doc_checks(),
    }


def print_failures(results: dict[str, list[CheckResult]]) -> None:
    for category, checks in results.items():
        failures = [check for check in checks if not check.ok]
        if not failures:
            continue
        print(f"{category} failures:", file=sys.stderr)
        for failure in failures:
            suffix = f" ({failure.detail})" if failure.detail else ""
            print(f"  - {failure.source}: {failure.name}{suffix}", file=sys.stderr)


def main() -> int:
    parser = argparse.ArgumentParser(description="Check streaming transfer compatibility research drift.")
    parser.add_argument("--json", action="store_true", help="print machine-readable result details")
    args = parser.parse_args()

    results = run_checks()
    ok = all(check.ok for checks in results.values() for check in checks)

    if args.json:
        payload = {
            category: [check.__dict__ for check in checks]
            for category, checks in results.items()
        }
        payload["ok"] = ok
        payload["scenario_count"] = len(SCENARIO_IDS)
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif ok:
        print(
            "OK Streaming transfer compatibility drift checks passed "
            f"({len(results['source'])} source checks, "
            f"{len(results['test'])} test checks, "
            f"{len(results['gap'])} explicit gap checks, "
            f"{len(results['doc'])} doc checks, "
            f"{len(SCENARIO_IDS)} scenarios)"
        )
    else:
        print_failures(results)

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

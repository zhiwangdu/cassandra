#!/usr/bin/env python3
#
# Source-only drift check for messaging TLS/compression compatibility research.

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

ENCRYPTION_OPTIONS = "src/java/org/apache/cassandra/config/EncryptionOptions.java"
CONFIG = "src/java/org/apache/cassandra/config/Config.java"
DATABASE_DESCRIPTOR = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
CASSANDRA_YAML = "conf/cassandra.yaml"
INBOUND_CONNECTION_INITIATOR = "src/java/org/apache/cassandra/net/InboundConnectionInitiator.java"
OUTBOUND_CONNECTION_INITIATOR = "src/java/org/apache/cassandra/net/OutboundConnectionInitiator.java"
OUTBOUND_CONNECTION_SETTINGS = "src/java/org/apache/cassandra/net/OutboundConnectionSettings.java"
HANDSHAKE_PROTOCOL = "src/java/org/apache/cassandra/net/HandshakeProtocol.java"

INTERNODE_ENCRYPTION_OPTIONS_TEST = "test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java"
INTERNODE_ENCRYPTION_ENFORCEMENT_TEST = "test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionEnforcementTest.java"
INTERNODE_ERROR_EXCLUSION_TEST = "test/distributed/org/apache/cassandra/distributed/test/InternodeErrorExclusionTest.java"
OUTBOUND_CONNECTION_SETTINGS_TEST = "test/unit/org/apache/cassandra/net/OutboundConnectionSettingsTest.java"
FRAMING_TEST = "test/unit/org/apache/cassandra/net/FramingTest.java"
JVMD_TEST_TEST = "test/distributed/org/apache/cassandra/distributed/test/JVMDTestTest.java"

GAP_UPGRADE_DIR = "test/distributed/org/apache/cassandra/distributed/upgrade"
GAP_UPGRADE_TOKENS = ("internode_compression", "server_encryption_options")

TARGET_DOCS = (
    "research/module-messaging-tls-compression-compatibility.md",
    "research/module-messaging-tls-compression-drift-checker.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "messaging_tls_policy_config_baseline",
    "messaging_tls_optional_inbound_baseline",
    "messaging_tls_reject_unencrypted_baseline",
    "messaging_tls_strict_inbound_baseline",
    "messaging_tls_protocol_cipher_baseline",
    "messaging_tls_cross_dc_enforcement_baseline",
    "messaging_tls_mtls_auth_baseline",
    "messaging_internode_compression_policy_baseline",
    "messaging_internode_compression_config_baseline",
    "messaging_frame_codec_baseline",
    "messaging_error_reporting_exclusion_baseline",
    "messaging_tls_compression_mixed_version_gap",
)

SOURCE_TOKEN_CHECKS = {
    ENCRYPTION_OPTIONS: (
        "public enum TlsEncryptionPolicy",
        "UNENCRYPTED(\"unencrypted\")",
        "OPTIONAL(\"optionally encrypted\")",
        "ENCRYPTED(\"encrypted\")",
        "initializeSslContextFactory();",
        "isEnabled = this.enabled != null && enabled;",
        "isOptional = !isEnabled;",
        "public TlsEncryptionPolicy tlsEncryptionPolicy()",
        "return TlsEncryptionPolicy.OPTIONAL;",
        "return TlsEncryptionPolicy.ENCRYPTED;",
        "return TlsEncryptionPolicy.UNENCRYPTED;",
        "public enum InternodeEncryption",
        "all, none, dc, rack",
        "isEnabled = this.internode_encryption != InternodeEncryption.none;",
        "logger.warn(\"Setting server_encryption_options.enabled has no effect, use internode_encryption\");",
        "logger.warn(\"Setting require_client_auth is incompatible with 'rack' and 'dc' internode_encryption values.\"",
        "isOptional = super.isOptional || internode_encryption == InternodeEncryption.rack || internode_encryption == InternodeEncryption.dc;",
        "public boolean shouldEncrypt(InetAddressAndPort endpoint)",
        "case none:",
        "case all:",
        "case dc:",
        "case rack:",
        "public boolean isExplicitlyOptional()",
        "return optional != null && optional;",
    ),
    CONFIG: (
        "public EncryptionOptions.ServerEncryptionOptions server_encryption_options = new EncryptionOptions.ServerEncryptionOptions();",
        "public InternodeCompression internode_compression = InternodeCompression.none;",
        "public enum InternodeCompression",
        "all, none, dc",
    ),
    DATABASE_DESCRIPTOR: (
        "conf.server_encryption_options.applyConfig();",
        "conf.server_encryption_options.legacy_ssl_storage_port_enabled",
        "conf.server_encryption_options.tlsEncryptionPolicy() == EncryptionOptions.TlsEncryptionPolicy.UNENCRYPTED",
        "throw new ConfigurationException(\"legacy_ssl_storage_port_enabled is true (enabled) with internode encryption disabled (none). Enable encryption or disable the legacy ssl storage port.\");",
        "public static EncryptionOptions.ServerEncryptionOptions getInternodeMessagingEncyptionOptions()",
        "public static void setInternodeMessagingEncyptionOptions(EncryptionOptions.ServerEncryptionOptions encryptionOptions)",
        "public static Config.InternodeCompression internodeCompression()",
        "return conf.internode_compression;",
        "public static void setInternodeCompression(Config.InternodeCompression compression)",
    ),
    CASSANDRA_YAML: (
        "server_encryption_options:",
        "internode_encryption: none",
        "optional defaults to true if internode_encryption is none",
        "legacy_ssl_storage_port_enabled: false",
        "require_client_auth: false",
        "internode_compression: dc",
    ),
    INBOUND_CONNECTION_INITIATOR: (
        "switch(settings.encryption.tlsEncryptionPolicy())",
        "case UNENCRYPTED:",
        "pipeline.addAfter(PIPELINE_INTERNODE_ERROR_EXCLUSIONS, \"rejectssl\", new RejectSslHandler());",
        "case OPTIONAL:",
        "pipeline.addAfter(PIPELINE_INTERNODE_ERROR_EXCLUSIONS, SSL_HANDLER_NAME, new OptionalSslHandler(settings.encryption));",
        "case ENCRYPTED:",
        "SslHandler sslHandler = getSslHandler(\"creating\", channel, settings.encryption);",
        "HandshakeProtocol.Initiate.maybeDecode(in);",
        "if (isEncryptionRequired(initiate.from) && !isChannelEncrypted(ctx))",
        "peer {} attempted to establish an unencrypted connection",
        "return !settings.encryption.isExplicitlyOptional() && settings.encryption.shouldEncrypt(peer);",
        "return ctx.pipeline().get(SslHandler.class) != null;",
        "FrameDecoderLZ4.fast(allocator)",
        "FrameDecoderCrc.create(allocator)",
        "new FrameDecoderUnprotected(allocator)",
        "if (SslHandler.isEncrypted(in))",
        "ctx.pipeline().replace(this, SSL_HANDLER_NAME, sslHandler);",
        "logger.info(\"Rejected incoming TLS connection before negotiating from {} to {}. TLS is explicitly disabled by configuration.\"",
        "address contained in internode_error_reporting_exclusions",
        "Invalid legacy protocol magic.",
    ),
    OUTBOUND_CONNECTION_INITIATOR: (
        "OUTBOUND_PRECONNECT",
        "MessagingService.instance().interruptOutbound(settings.to);",
        "if ((sslConnectionType == SslFallbackConnectionType.SERVER_CONFIG && settings.withEncryption())",
        "SslContext sslContext = getSslContext(sslConnectionType);",
        "SslHandler sslHandler = newSslHandler(channel, sslContext, peer);",
        "pipeline.addFirst(SSL_HANDLER_NAME, sslHandler);",
        "pipeline.addLast(\"server-authentication\", new ServerAuthenticationHandler(settings));",
        "requireClientAuth = settings.withEncryption();",
        "return SSLFactory.getOrCreateSslContext(settings.encryption, requireClientAuth, ISslContextFactory.SocketType.CLIENT, SSL_FACTORY_CONTEXT_DESCRIPTION);",
        "Initiate msg = new Initiate(settings.acceptVersions, type, settings.framing, settings.from);",
        "Accept msg = Accept.maybeDecode(in);",
        "FrameEncoderLZ4.fastInstance",
        "FrameEncoderCrc.instance",
        "FrameEncoderUnprotected.instance",
        "messagingSuccess(ctx.channel(), useMessagingVersion, frameEncoder.allocator())",
    ),
    OUTBOUND_CONNECTION_SETTINGS: (
        "public enum Framing",
        "UNPROTECTED(0)",
        "LZ4(1)",
        "CRC(2)",
        "public boolean withEncryption()",
        "public ServerEncryptionOptions encryption()",
        "return encryption != null ? encryption : defaultEncryptionOptions(to);",
        "public Framing framing(ConnectionCategory category)",
        "return Framing.UNPROTECTED;",
        "? Framing.LZ4 : Framing.CRC;",
        "static ServerEncryptionOptions defaultEncryptionOptions(InetAddressAndPort endpoint)",
        "ServerEncryptionOptions options = DatabaseDescriptor.getInternodeMessagingEncyptionOptions();",
        "return options.shouldEncrypt(endpoint) ? options : null;",
        "static boolean shouldCompressConnection(IEndpointSnitch snitch, InetAddressAndPort localHost, InetAddressAndPort remoteHost)",
        "DatabaseDescriptor.internodeCompression() == Config.InternodeCompression.all",
        "DatabaseDescriptor.internodeCompression() == Config.InternodeCompression.dc",
        "!isInLocalDC(snitch, localHost, remoteHost)",
    ),
    HANDSHAKE_PROTOCOL: (
        "class HandshakeProtocol",
        "static class Initiate",
        "final AcceptVersions acceptVersions;",
        "final ConnectionType type;",
        "final Framing framing;",
        "private int encodeFlags()",
        "flags |= ((framing.id & 1) << 2) | ((framing.id & 2) << 3);",
        "flags |= (acceptVersions.min << 16);",
        "flags |= (acceptVersions.max << 24);",
        "static Initiate maybeDecode(ByteBuf buf) throws IOException",
        "validateLegacyProtocolMagic(in.readInt());",
        "if (maxMessagingVersion < MessagingService.VERSION_40)",
        "Framing framing = Framing.forId(framingBits);",
        "throw new InvalidCrc(read, computed);",
        "static class Accept",
        "final int useMessagingVersion;",
        "final int maxMessagingVersion;",
        "buffer.writeInt(computeCrc32(buffer, 0, 8));",
        "static Accept maybeDecode(ByteBuf in) throws InvalidCrc",
        "return new Accept(useMessagingVersion, maxMessagingVersion);",
    ),
}

TEST_TOKEN_CHECKS = {
    INTERNODE_ENCRYPTION_OPTIONS_TEST: (
        "public void nodeWillNotStartWithBadKeystoreTest()",
        "public void legacySslPortProvidedWithEncryptionNoneWillNotStartTest()",
        "public void optionalTlsConnectionDisabledWithoutKeystoreTest()",
        "public void optionalTlsConnectionAllowedWithKeystoreTest()",
        "public void optionalTlsConnectionAllowedToStoragePortTest()",
        "public void legacySslStoragePortEnabledWithSameRegularAndSslPortTest()",
        "public void tlsConnectionRejectedWhenUnencrypted()",
        "public void allInternodeEncryptionEstablishedTest()",
        "SELECT successful_connection_attempts, address, port FROM system_views.internode_outbound",
        "public void negotiatedProtocolMustBeAcceptedProtocolTest()",
        "public void connectionCannotAgreeOnClientAndServer()",
        "public void nodeMustNotStartWithNonExistantProtocol()",
        "public void nodeMustNotStartWithNonExistantCipher()",
        "ConnectResult.FAILED_TO_NEGOTIATE",
        "ConnectResult.NEGOTIATED",
    ),
    INTERNODE_ENCRYPTION_ENFORCEMENT_TEST: (
        "public void testInboundConnectionsAreRejectedWhenAuthFails()",
        "public void testOutboundConnectionsAreRejectedWhenAuthFails()",
        "public void testOutboundConnectionsAreInterruptedWhenAuthFails()",
        "public void testConnectionsAreAcceptedWhenAuthSucceds()",
        "public void testAuthenticationWithCertificateAuthenticator()",
        "public void testConnectionsAreRejectedWithInvalidConfig()",
        "public void testConnectionsAreAcceptedWithValidConfig()",
        "encryption.put(\"internode_encryption\", \"all\");",
        "encryption.put(\"internode_encryption\", \"dc\");",
        "encryption.put(\"require_client_auth\", \"true\");",
        "MessagingService.instance().messageHandlers.isEmpty()",
        "outbound.small.isConnected() || outbound.large.isConnected() || outbound.urgent.isConnected()",
    ),
    OUTBOUND_CONNECTION_SETTINGS_TEST: (
        "public void shouldCompressConnection_None()",
        "DatabaseDescriptor.setInternodeCompression(Config.InternodeCompression.none);",
        "public void shouldCompressConnection_DifferentDc()",
        "DatabaseDescriptor.setInternodeCompression(Config.InternodeCompression.dc);",
        "public void shouldCompressConnection_All()",
        "DatabaseDescriptor.setInternodeCompression(Config.InternodeCompression.all);",
        "public void shouldCompressConnection_SameDc()",
        "Assert.assertFalse(OutboundConnectionSettings.shouldCompressConnection(getEndpointSnitch(), LOCAL_ADDR, REMOTE_ADDR));",
        "Assert.assertTrue(OutboundConnectionSettings.shouldCompressConnection(getEndpointSnitch(), LOCAL_ADDR, REMOTE_ADDR));",
    ),
    FRAMING_TEST: (
        "public void testRandomLZ4()",
        "testSomeFrames(FrameEncoderLZ4.fastInstance, FrameDecoderLZ4.fast(GlobalBufferPoolAllocator.instance));",
        "public void testRandomCrc()",
        "testSomeFrames(FrameEncoderCrc.instance, FrameDecoderCrc.create(GlobalBufferPoolAllocator.instance));",
    ),
    JVMD_TEST_TEST: (
        "public void nonSharedConfigClassTest()",
        "c.set(\"internode_compression\", Config.InternodeCompression.dc);",
        "assertEquals(Config.InternodeCompression.dc, DatabaseDescriptor.internodeCompression());",
    ),
    INTERNODE_ERROR_EXCLUSION_TEST: (
        "public void ignoreExcludedInternodeErrors()",
        "address contained in internode_error_reporting_exclusions",
        "public void testNoSpammingInvalidLegacyProtocolMagicException()",
        "Failed to properly handshake with peer localhost. Closing the channel. Invalid legacy protocol magic.",
    ),
}

DOC_TOKEN_CHECKS = {
    "research/module-messaging-tls-compression-compatibility.md": (
        *SCENARIO_IDS,
        ENCRYPTION_OPTIONS,
        INBOUND_CONNECTION_INITIATOR,
        OUTBOUND_CONNECTION_INITIATOR,
        OUTBOUND_CONNECTION_SETTINGS,
        HANDSHAKE_PROTOCOL,
        INTERNODE_ENCRYPTION_OPTIONS_TEST,
        INTERNODE_ENCRYPTION_ENFORCEMENT_TEST,
        OUTBOUND_CONNECTION_SETTINGS_TEST,
        FRAMING_TEST,
        GAP_UPGRADE_DIR,
        "gap still open",
    ),
    "research/module-messaging-tls-compression-drift-checker.md": (
        *SCENARIO_IDS[-1:],
        "python3 research/tools/check-messaging-tls-compression-drift.py",
        "GAP_UPGRADE_TOKENS",
        "gap still open",
        GAP_UPGRADE_DIR,
    ),
    "research/README.md": (
        "module-messaging-tls-compression-compatibility.md",
        "module-messaging-tls-compression-drift-checker.md",
        "research/tools/check-messaging-tls-compression-drift.py",
        "Messaging | 第五轮源码侧完成",
        "TLS/compression mixed-version dtest",
    ),
    "research/notes/source-map.md": (
        "Messaging TLS/compression compatibility",
        "research/tools/check-messaging-tls-compression-drift.py",
        "messaging_tls_compression_mixed_version_gap",
        "test/unit/org/apache/cassandra/net/OutboundConnectionSettingsTest.java",
        "test/distributed/org/apache/cassandra/distributed/test/InternodeEncryptionOptionsTest.java",
    ),
}


@dataclass(frozen=True)
class TokenCheck:
    kind: str
    path: str
    token: str


def read_text(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def check_required_tokens(checks, kind):
    missing = []
    count = 0
    for path, tokens in checks.items():
        text = read_text(path)
        for token in tokens:
            count += 1
            if token not in text:
                missing.append(TokenCheck(kind, path, token))
    return missing, count


def scan_upgrade_gap():
    unexpected = []
    count = 0
    root = REPO_ROOT / GAP_UPGRADE_DIR
    if not root.exists():
        raise FileNotFoundError(GAP_UPGRADE_DIR)

    for path in sorted(root.rglob("*.java")):
        rel = str(path.relative_to(REPO_ROOT))
        text = path.read_text(encoding="utf-8")
        for token in GAP_UPGRADE_TOKENS:
            count += 1
            if token in text:
                unexpected.append(TokenCheck("upgrade-gap", rel, token))
    return unexpected, count


def check():
    missing = []
    check_count = 0

    for checks, kind in (
        (SOURCE_TOKEN_CHECKS, "source"),
        (TEST_TOKEN_CHECKS, "test"),
        (DOC_TOKEN_CHECKS, "doc"),
    ):
        missing_part, count = check_required_tokens(checks, kind)
        missing.extend(missing_part)
        check_count += count

    unexpected_upgrade_tokens, gap_count = scan_upgrade_gap()
    check_count += gap_count

    return {
        "ok": not missing and not unexpected_upgrade_tokens,
        "check_count": check_count,
        "target_docs": TARGET_DOCS,
        "missing": [entry.__dict__ for entry in missing],
        "unexpected_upgrade_tokens": [entry.__dict__ for entry in unexpected_upgrade_tokens],
        "upgrade_gap_dir": GAP_UPGRADE_DIR,
        "upgrade_gap_tokens": GAP_UPGRADE_TOKENS,
    }


def main():
    parser = argparse.ArgumentParser(description="Check messaging TLS/compression compatibility research drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args()

    try:
        result = check()
    except Exception as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        if result["ok"]:
            print(f"OK messaging TLS/compression drift checks passed: {result['check_count']} checks")
        else:
            if result["missing"]:
                print("Missing required tokens:")
                for entry in result["missing"]:
                    print(f"  [{entry['kind']}] {entry['path']}: {entry['token']}")
            if result["unexpected_upgrade_tokens"]:
                print("Unexpected upgrade mixed-version anchors found:")
                for entry in result["unexpected_upgrade_tokens"]:
                    print(f"  {entry['path']}: {entry['token']}")
            print("Update messaging TLS/compression research docs and checker gap predicates.")

    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

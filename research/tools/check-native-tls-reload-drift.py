#!/usr/bin/env python3
#
# Source-only drift check for native TLS reload coverage research.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

SSL_FACTORY_SOURCE = "src/java/org/apache/cassandra/security/SSLFactory.java"
FILE_BASED_FACTORY_SOURCE = "src/java/org/apache/cassandra/security/FileBasedSslContextFactory.java"
PEM_FACTORY_SOURCE = "src/java/org/apache/cassandra/security/PEMBasedSslContextFactory.java"
PIPELINE_CONFIGURATOR_SOURCE = "src/java/org/apache/cassandra/transport/PipelineConfigurator.java"
NATIVE_TRANSPORT_SERVICE_SOURCE = "src/java/org/apache/cassandra/service/NativeTransportService.java"
DATABASE_DESCRIPTOR_SOURCE = "src/java/org/apache/cassandra/config/DatabaseDescriptor.java"
ENCRYPTION_OPTIONS_SOURCE = "src/java/org/apache/cassandra/config/EncryptionOptions.java"
SIMPLE_CLIENT_SOURCE = "src/java/org/apache/cassandra/transport/SimpleClient.java"
MTLS_AUTHENTICATOR_SOURCE = "src/java/org/apache/cassandra/auth/MutualTlsAuthenticator.java"
MESSAGING_MBEAN_SOURCE = "src/java/org/apache/cassandra/net/MessagingServiceMBeanImpl.java"

SSL_FACTORY_TEST = "test/unit/org/apache/cassandra/security/SSLFactoryTest.java"
NATIVE_TLS_TEST = "test/distributed/org/apache/cassandra/distributed/test/NativeTransportEncryptionOptionsTest.java"
ABSTRACT_ENCRYPTION_TEST = "test/distributed/org/apache/cassandra/distributed/test/AbstractEncryptionOptionsImpl.java"
PEM_FACTORY_TEST = "test/unit/org/apache/cassandra/security/PEMBasedSslContextFactoryTest.java"
FILE_BASED_FACTORY_TEST = "test/unit/org/apache/cassandra/security/FileBasedSslContextFactoryTest.java"

TARGET_DOCS = (
    "research/module-native-tls-reload-coverage-matrix.md",
    "research/module-native-tls-reload-drift-checker.md",
    "research/module-native-protocol.md",
    "research/module-schema-cql-auth.md",
    "research/module-schema-cql-auth-native-deep-dive.md",
    "research/module-schema-cql-auth-native-third-round.md",
    "research/README.md",
    "research/notes/source-map.md",
)

SCENARIO_IDS = (
    "native_tls_reload_context_cache_contract",
    "native_tls_reload_file_watch_contract",
    "native_tls_reload_pem_file_contract",
    "native_tls_reload_startup_validation_contract",
    "native_tls_reload_native_pipeline_contract",
    "native_tls_reload_dual_port_policy",
    "native_tls_reload_mtls_gate",
    "native_tls_reload_jmx_force_gate",
    "native_tls_reload_test_coverage_matrix",
    "native_tls_reload_e2e_gap",
)

SOURCE_TOKEN_CHECKS = {
    SSL_FACTORY_SOURCE: (
        "private static final ConcurrentHashMap<CacheKey, SslContext> cachedSslContexts",
        "public static final int DEFAULT_HOT_RELOAD_INITIAL_DELAY_SEC = 600",
        "public static final int DEFAULT_HOT_RELOAD_PERIOD_SEC = 600",
        "public static void checkCertFilesForHotReloading()",
        "public static void forceCheckCertFiles()",
        "private static void checkCachedContextsForReload(boolean forceReload)",
        "validateSslContext(key.contextDescription, opts",
        "clearSslContextCache(key.encryptionOptions, keysToCheck)",
        "public static synchronized void initHotReloading",
        "scheduleWithFixedDelay(SSLFactory::checkCertFilesForHotReloading",
        "static class CacheKey",
    ),
    FILE_BASED_FACTORY_SOURCE: (
        "protected volatile List<HotReloadableFile> hotReloadableFiles",
        "public boolean shouldReload()",
        "public synchronized void initHotReloading()",
        "fileList.add(new HotReloadableFile(keystoreContext.filePath))",
        "fileList.add(new HotReloadableFile(outboundKeystoreContext.filePath))",
        "fileList.add(new HotReloadableFile(trustStoreContext.filePath))",
        "boolean shouldReload()",
        "lastModTime = curModTime",
    ),
    PEM_FACTORY_SOURCE: (
        "public final class PEMBasedSslContextFactory extends FileBasedSslContextFactory",
        "public synchronized void initHotReloading()",
        "pemEncodedKeyContext.maybeFilebasedKey",
        "pemEncodedOutboundKeyContext.maybeFilebasedKey",
        "pemEncodedTrustCertificates.maybeFilebasedKey",
        "pemBasedKeyStoreContext.key = readPEMFile(keyStoreContext.filePath)",
        "pemEncodedTrustCertificates.key = readPEMFile(trustStoreContext.filePath)",
    ),
    DATABASE_DESCRIPTOR_SOURCE: (
        "conf.client_encryption_options.applyConfig()",
        "native_transport_port_ssl",
        "Encryption must be enabled in client_encryption_options for native_transport_port_ssl",
        "public static void applySslContext()",
        'SSLFactory.validateSslContext("Native transport"',
        "SSLFactory.initHotReloading(conf.server_encryption_options, conf.client_encryption_options, false)",
        "getNativeProtocolEncryptionOptions()",
    ),
    ENCRYPTION_OPTIONS_SOURCE: (
        "public EncryptionOptions applyConfig()",
        "initializeSslContextFactory()",
        "sslContextFactoryInstance.hasKeystore()",
        "protected void fillSslContextParams",
        "ConfigKey.KEYSTORE",
        "ConfigKey.TRUSTSTORE",
        "ConfigKey.REQUIRE_CLIENT_AUTH",
        "public boolean equals(Object o)",
        "public int hashCode()",
    ),
    PIPELINE_CONFIGURATOR_SOURCE: (
        "protected EncryptionConfig encryptionConfig()",
        "case OPTIONAL:",
        "SslHandler.isEncrypted(byteBuf)",
        "SSLFactory.getOrCreateSslContext(encryptionOptions",
        "ISslContextFactory.SocketType.SERVER",
        "channel.pipeline().addFirst(SSL_HANDLER, newSslHandler(channel, sslContext, peer))",
    ),
    NATIVE_TRANSPORT_SERVICE_SOURCE: (
        "if (nativePort != nativePortSSL)",
        "withTlsEncryptionPolicy(EncryptionOptions.TlsEncryptionPolicy.UNENCRYPTED)",
        "tlsPortServer = builder.withTlsEncryptionPolicy(encryptionPolicy).withPort(nativePortSSL).build()",
        "Encryption must be enabled in client_encryption_options for native_transport_port_ssl",
    ),
    SIMPLE_CLIENT_SOURCE: (
        "public Builder encryption(EncryptionOptions options)",
        "private class SecureInitializer extends Initializer",
        "SSLFactory.getOrCreateSslContext(encryptionOptions, encryptionOptions.require_client_auth",
        'channel.pipeline().addFirst("ssl", newSslHandler(channel, sslContext, peer))',
    ),
    MTLS_AUTHENTICATOR_SOURCE: (
        "checkMtlsConfigurationIsValid",
        "!config.client_encryption_options.getEnabled() || !config.client_encryption_options.require_client_auth",
        "MutualTlsAuthenticator requires client_encryption_options.enabled to be true",
    ),
    MESSAGING_MBEAN_SOURCE: (
        "public void reloadSslCertificates()",
        "SSLFactory.forceCheckCertFiles();",
    ),
}

DOC_REQUIRED_TOKENS = (
    "module-native-tls-reload-coverage-matrix.md",
    "module-native-tls-reload-drift-checker.md",
    "check-native-tls-reload-drift.py",
    SSL_FACTORY_SOURCE,
    FILE_BASED_FACTORY_SOURCE,
    PEM_FACTORY_SOURCE,
    PIPELINE_CONFIGURATOR_SOURCE,
    NATIVE_TRANSPORT_SERVICE_SOURCE,
    DATABASE_DESCRIPTOR_SOURCE,
    ENCRYPTION_OPTIONS_SOURCE,
    SIMPLE_CLIENT_SOURCE,
    MTLS_AUTHENTICATOR_SOURCE,
    MESSAGING_MBEAN_SOURCE,
    SSL_FACTORY_TEST,
    NATIVE_TLS_TEST,
    ABSTRACT_ENCRYPTION_TEST,
    PEM_FACTORY_TEST,
    FILE_BASED_FACTORY_TEST,
    "client_encryption_options",
    "native_transport_port_ssl",
    "require_client_auth",
    "reloadSslCertificates",
    "DEFAULT_HOT_RELOAD_INITIAL_DELAY_SEC",
    "DEFAULT_HOT_RELOAD_PERIOD_SEC",
) + SCENARIO_IDS


@dataclass(frozen=True)
class Check:
    name: str
    source: str
    ok: bool


def read(path: str) -> str:
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def documented(symbol: str, text: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", text) is not None


def source_checks() -> tuple[list[Check], dict[str, object]]:
    checks: list[Check] = []

    for path, tokens in SOURCE_TOKEN_CHECKS.items():
        text = read(path)
        checks.append(Check(f"source token contract {path}", path, all(token in text for token in tokens)))

    ssl_test = read(SSL_FACTORY_TEST)
    native_tls_test = read(NATIVE_TLS_TEST)
    abstract_test = read(ABSTRACT_ENCRYPTION_TEST)
    pem_test = read(PEM_FACTORY_TEST)
    file_test = read(FILE_BASED_FACTORY_TEST)

    checks.extend(
        (
            Check(
                "SSLFactoryTest covers JKS/PEM reload and bad rotation retention",
                SSL_FACTORY_TEST,
                all(
                    token in ssl_test
                    for token in (
                        "testSslContextReload_HappyPath",
                        "testPEMSslContextReload_HappyPath",
                        "testSslFactoryHotReload_BadPassword_DoesNotClearExistingSslContext",
                        "testSslFactoryHotReload_CorruptOrNonExistentFile_DoesNotClearExistingSslContext",
                        "Assert.assertNotSame(oldCtx, newCtx)",
                        "Assert.assertSame(oldCtx, newCtx)",
                    )
                ),
            ),
            Check(
                "NativeTransportEncryptionOptionsTest covers TLS negotiation but not reload",
                NATIVE_TLS_TEST,
                all(
                    token in native_tls_test
                    for token in (
                        "optionalTlsConnectionAllowedWithKeystoreTest",
                        "optionalTlsConnectionAllowedToRegularPortTest",
                        "negotiatedProtocolMustBeAcceptedProtocolTest",
                        "connectionCannotAgreeOnClientAndServerTest",
                        "testEndpointVerification",
                    )
                )
                and not any(token in native_tls_test for token in ("HotReload", "checkCertFilesForHotReloading", "forceCheckCertFiles", "reloadSslCertificates")),
            ),
            Check(
                "AbstractEncryptionOptionsImpl exposes TlsConnection handshake helper",
                ABSTRACT_ENCRYPTION_TEST,
                all(token in abstract_test for token in ("public class TlsConnection", "ConnectResult connect()", "handshakeFuture()", "setProtocolAndCipher")),
            ),
            Check(
                "PEM and file based factory tests exist",
                f"{PEM_FACTORY_TEST} / {FILE_BASED_FACTORY_TEST}",
                "public class PEMBasedSslContextFactoryTest" in pem_test and "public class FileBasedSslContextFactoryTest" in file_test,
            ),
        )
    )

    metadata = {
        "source_files": len(SOURCE_TOKEN_CHECKS),
        "scenario_count": len(SCENARIO_IDS),
        "scheduled_reload_seconds": {
            "initial_delay": 600,
            "period": 600,
        },
        "e2e_gap_expected": True,
    }
    return checks, metadata


def read_doc_text() -> str:
    return "\n".join(read(path) for path in TARGET_DOCS)


def doc_checks() -> list[Check]:
    text = read_doc_text()
    checks = [Check(f"doc scenario {scenario}", " / ".join(TARGET_DOCS), documented(scenario, text)) for scenario in SCENARIO_IDS]
    checks.extend(Check(f"doc token {token}", " / ".join(TARGET_DOCS), token in text) for token in DOC_REQUIRED_TOKENS)
    return checks


def check() -> tuple[dict[str, object], bool]:
    sources, metadata = source_checks()
    docs = doc_checks()
    result = {
        "sources": list(SOURCE_TOKEN_CHECKS),
        "tests": [
            SSL_FACTORY_TEST,
            NATIVE_TLS_TEST,
            ABSTRACT_ENCRYPTION_TEST,
            PEM_FACTORY_TEST,
            FILE_BASED_FACTORY_TEST,
        ],
        "docs": list(TARGET_DOCS),
        "scenario_ids": list(SCENARIO_IDS),
        "metadata": metadata,
        "source_checks": [entry.__dict__ for entry in sources],
        "doc_checks": [entry.__dict__ for entry in docs],
    }
    ok = all(entry.ok for entry in sources) and all(entry.ok for entry in docs)
    return result, ok


def main() -> int:
    parser = argparse.ArgumentParser(description="Check native TLS reload source/doc drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()

    try:
        result, ok = check()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        failed_sources = [entry for entry in result["source_checks"] if not entry["ok"]]
        failed_docs = [entry for entry in result["doc_checks"] if not entry["ok"]]
        if failed_sources or failed_docs:
            print("Native TLS reload drift check failed.")
            for entry in failed_sources + failed_docs:
                print(f"- {entry['name']} ({entry['source']})")
        else:
            metadata = result["metadata"]
            print(
                "Native TLS reload drift check passed: "
                f"{metadata['source_files']} source files, "
                f"{metadata['scenario_count']} scenarios, "
                f"{metadata['scheduled_reload_seconds']['initial_delay']}s/{metadata['scheduled_reload_seconds']['period']}s reload schedule, "
                "native reload E2E gap remains explicit."
            )

    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

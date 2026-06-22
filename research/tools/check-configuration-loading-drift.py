#!/usr/bin/env python3
#
# Source-only drift check for configuration loading/runtime research coverage.

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]

MATRIX_DOC = "research/module-configuration-loading-runtime-matrix.md"
CHECKER_DOC = "research/module-configuration-loading-drift-checker.md"
README_DOC = "research/README.md"
SOURCE_MAP_DOC = "research/notes/source-map.md"

EXPECTED_COUNTS = {
    "config_public_fields": 414,
    "config_replaces": 96,
    "converters": 22,
    "system_properties": 328,
    "settings_aliases": 27,
    "runtime_setters": 439,
}

SCENARIOS = (
    "config_model_field_contract",
    "config_database_descriptor_modes_contract",
    "config_loader_selection_contract",
    "config_yaml_url_and_empty_file_contract",
    "config_yaml_property_checker_contract",
    "config_duplicate_and_replacement_guard_contract",
    "config_compat_replacement_converter_contract",
    "config_system_property_overlay_contract",
    "config_parameterized_nested_contract",
    "config_unit_spec_contract",
    "config_apply_simple_validation_contract",
    "config_settings_virtual_table_contract",
    "config_runtime_jmx_setter_contract",
    "config_guardrails_startup_checks_contract",
    "config_existing_unit_tests_baseline",
    "config_ci_drift_checker_gap",
)

SOURCE_EXPECTATIONS = {
    "src/java/org/apache/cassandra/config/Config.java": (
        "Properties declared as volatile can be mutated via JMX.",
        'public static final String PROPERTY_PREFIX = "cassandra.";',
        "public String cluster_name = \"Test Cluster\";",
        '@Replaces(oldName = "permissions_validity_in_ms", converter = Converters.MILLIS_DURATION_INT, deprecated = true)',
        '@Replaces(oldName = "stream_throughput_outbound_megabits_per_sec", converter = Converters.MEGABITS_TO_BYTES_PER_SECOND_DATA_RATE, deprecated = true)',
        "public volatile DataRateSpec.LongBytesPerSecondBound stream_throughput_outbound = new DataRateSpec.LongBytesPerSecondBound(\"24MiB/s\");",
        "public static class MemtableOptions",
        "private static boolean isClientMode = false;",
        "public static void setClientMode(boolean clientMode)",
        "public volatile Map<StartupCheckType, Map<String, Object>> startup_checks = new HashMap<>();",
        "public volatile AutoRepairConfig auto_repair = new AutoRepairConfig();",
        '@Replaces(oldName = "keyspace_count_warn_threshold", converter = Converters.KEYSPACE_COUNT_THRESHOLD_TO_GUARDRAIL, deprecated = true)',
        '@Replaces(oldName = "compaction_large_partition_warning_threshold", converter = Converters.LONG_BYTES_DATASTORAGE_MEBIBYTES_DATASTORAGE, deprecated = true)',
    ),
    "src/java/org/apache/cassandra/config/ConfigurationLoader.java": (
        "public interface ConfigurationLoader",
        "Config loadConfig() throws ConfigurationException;",
    ),
    "src/java/org/apache/cassandra/config/DatabaseDescriptor.java": (
        "public static void daemonInitialization() throws ConfigurationException",
        "public static void toolInitialization(boolean failIfDaemonOrClient)",
        "public static void clientInitialization(boolean failIfDaemonOrTool, Supplier<Config> configSupplier)",
        "if (Config.getOverrideLoadConfig() != null)",
        "String loaderClass = CONFIG_LOADER.getString();",
        "loaderClass == null",
        "? new YamlConfigurationLoader()",
        ': FBUtilities.construct(loaderClass, "configuration loading")',
        "Config.log(config);",
        "private static void applyAll() throws ConfigurationException",
        "applyCompatibilityMode();",
        "applySimpleConfig();",
        "applyGuardrails();",
        "applyStartupChecks();",
        "private static void applySimpleConfig()",
        "validateUpperBoundStreamingConfig();",
        "checkForLowestAcceptedTimeouts(conf);",
        "static void validateUpperBoundStreamingConfig() throws ConfigurationException",
        "guardrails = new GuardrailsOptions(conf);",
        "startupChecksOptions = new StartupChecksOptions(conf.startup_checks);",
    ),
    "src/java/org/apache/cassandra/config/YamlConfigurationLoader.java": (
        'static final String SYSTEM_PROPERTY_PREFIX = "cassandra.settings.";',
        "private static URL getStorageConfigURL() throws ConfigurationException",
        "String configUrl = CASSANDRA_CONFIG.getString();",
        "url = loader.getResource(configUrl);",
        "Please prefix the file with",
        "public Config loadConfig(URL url) throws ConfigurationException",
        "SafeConstructor constructor = new CustomConstructor(Config.class, Yaml.class.getClassLoader());",
        "Map<Class<?>, Map<String, Replacement>> replacements = getNameReplacements(Config.class);",
        "verifyReplacements(replacements, configBytes);",
        "PropertiesChecker propertiesChecker = new PropertiesChecker(replacements);",
        "propertiesChecker.check();",
        "maybeAddSystemProperties(result);",
        "if (name.startsWith(SYSTEM_PROPERTY_PREFIX))",
        "updateFromMap(map, false, obj);",
        "Config contains both old and new keys for the same configuration parameters",
        "loaderOptions.setAllowDuplicateKeys(ALLOW_DUPLICATE_CONFIG_KEYS.getBoolean());",
        "public static <T> T fromMap(Map<String,Object> map, boolean shouldCheck, Class<T> klass)",
        "public static <T> T updateFromMap(Map<String, ?> map, boolean shouldCheck, T obj)",
        "static class CustomConstructor extends CustomClassLoaderConstructor",
        'seedDesc.putMapPropertyType("parameters", String.class, String.class);',
        'memtableDesc.addPropertyParameters("configurations", String.class, InheritingClass.class);',
        "return Lists.newCopyOnWriteArrayList();",
        "return Maps.newConcurrentMap();",
        "return Sets.newConcurrentHashSet();",
        "return config == null ? new Config() : config;",
        "private static class PropertiesChecker extends PropertyUtils",
        "missingProperties.add(result.getName());",
        "nullProperties.add(getName());",
        "return getNestedProperty(type, name);",
        "throw new ConfigurationException(\"Invalid yaml. Those properties \" + nullProperties + \" are not valid\", false);",
        "throw new ConfigurationException(\"Invalid yaml. Please remove properties \" + missingProperties + \" from your cassandra.yaml\", false);",
        "loaderOptions.setCodePointLimit(64 * 1024 * 1024);",
    ),
    "src/java/org/apache/cassandra/config/DefaultLoader.java": (
        "public class DefaultLoader implements Loader",
        "int modifiers = f.getModifiers();",
        "Modifier.isStatic(modifiers)",
        "Modifier.isTransient(modifiers)",
        "f.isAnnotationPresent(JsonIgnore.class)",
        "new FieldProperty(f)",
        "new MethodPropertyPlus(d)",
    ),
    "src/java/org/apache/cassandra/config/Properties.java": (
        'public static final String DELIMITER = ".";',
        "public static Property andThen(Property root, Property leaf, String delimiter)",
        "public static Map<String, Property> flatten(Loader loader, Map<String, Property> input, String delimiter)",
        "Constructor<?> c = root.getType().getDeclaredConstructor();",
        "return Collection.class.isAssignableFrom(prop.getType()) || Map.class.isAssignableFrom(prop.getType());",
        "return new DefaultLoader();",
        "return new ForwardingProperty(newName, prop);",
    ),
    "src/java/org/apache/cassandra/config/Replacement.java": (
        "public final String oldName;",
        "public final Class<?> oldType;",
        "public final String newName;",
        "public final Converters converter;",
        "newProperty.set(o, converter.convert(o1));",
        "return converter.unconvert(newProperty.get(o));",
        "return oldName.equals(newName);",
    ),
    "src/java/org/apache/cassandra/config/Replacements.java": (
        "public static Map<Class<? extends Object>, Map<String, Replacement>> getNameReplacements(Class<? extends Object> klass)",
        "getReplacementsRecursive(seen, accum, field.getType());",
        "field.getAnnotationsByType(ReplacesList.class)",
        "throw new ConfigurationException(\"Invalid annotations, you have more than one @Replaces annotation",
        "Class<?> oldType = r.converter().getOldType();",
        "Class<?> expectedNewType = r.converter().getNewType();",
    ),
    "src/java/org/apache/cassandra/config/Converters.java": (
        "IDENTITY(null, null, o -> o, o -> o),",
        "MILLIS_DURATION_LONG(Long.class, DurationSpec.LongMillisecondsBound.class,",
        "MILLIS_CUSTOM_DURATION(Integer.class, DurationSpec.IntMillisecondsBound.class,",
        "NEGATIVE_SECONDS_DURATION(Integer.class, DurationSpec.IntSecondsBound.class,",
        "MINUTES_CUSTOM_DURATION(Integer.class, DurationSpec.IntMinutesBound.class,",
        "NEGATIVE_MEBIBYTES_DATA_STORAGE_INT(Integer.class, DataStorageSpec.IntMebibytesBound.class,",
        "BYTES_CUSTOM_DATASTORAGE(Long.class, DataStorageSpec.LongBytesBound.class,",
        "MEBIBYTES_PER_SECOND_DATA_RATE(Integer.class, DataRateSpec.LongBytesPerSecondBound.class,",
        "MEGABITS_TO_BYTES_PER_SECOND_DATA_RATE(Integer.class, DataRateSpec.LongBytesPerSecondBound.class,",
        "KEYSPACE_COUNT_THRESHOLD_TO_GUARDRAIL(int.class, int.class,",
        "TABLE_COUNT_THRESHOLD_TO_GUARDRAIL(int.class, int.class,",
        "public Object convert(Object value)",
        "public Object unconvert(Object value)",
    ),
    "src/java/org/apache/cassandra/config/CassandraRelevantProperties.java": (
        'ALLOW_DUPLICATE_CONFIG_KEYS("cassandra.allow_duplicate_config_keys", "true")',
        'ALLOW_NEW_OLD_CONFIG_KEYS("cassandra.allow_new_old_config_keys")',
        'CASSANDRA_CONFIG("cassandra.config", "cassandra.yaml")',
        'CONFIG_ALLOW_SYSTEM_PROPERTIES("cassandra.config.allow_system_properties")',
        'CONFIG_LOADER("cassandra.config.loader")',
        'VIRTUAL_TABLE_COMPLEX_SETTINGS_FORMAT_JSON("cassandra.virtual_table_complex_settings_format_json", "false")',
        "System properties have duplicate key",
        "Enum constants are not in alphabetical order",
        "public String getString()",
        "public boolean getBoolean()",
        "public Integer setInt(int value)",
        "public <T extends Enum<T>> T getEnum(boolean toUppercase, Class<T> enumClass)",
    ),
    "src/java/org/apache/cassandra/config/CassandraRelevantEnv.java": (
        'JAVA_HOME ("JAVA_HOME")',
        'CIRCLECI("CIRCLECI")',
        'CASSANDRA_SKIP_SYNC("CASSANDRA_SKIP_SYNC")',
        "public boolean getBoolean()",
    ),
    "src/java/org/apache/cassandra/config/ParameterizedClass.java": (
        'public static final String CLASS_NAME = "class_name";',
        'public static final String PARAMETERS = "parameters";',
        "static public <K> K newInstance(ParameterizedClass parameterizedClass, List<String> searchPackages)",
        "Class.forName(name);",
        "c.getParameterTypes().length == 1 && c.getParameterTypes()[0].equals(Map.class)",
        "parameterizedClass.parameters == null ? Collections.emptyMap() : parameterizedClass.parameters",
        "c.getParameterTypes().length == 0",
    ),
    "src/java/org/apache/cassandra/config/InheritingClass.java": (
        "public String inherits = null;",
        "public ParameterizedClass resolve(Map<String, ParameterizedClass> map)",
        "throw new ConfigurationException(\"Configuration definition inherits unknown \" + inherits",
        "resolvedParameters.putAll(this.parameters);",
        "String resolvedClass = this.class_name == null ? parent.class_name : this.class_name;",
    ),
    "src/java/org/apache/cassandra/config/Redacted.java": (
        'String REDACTED_STRING = "<REDACTED>";',
        "String redactedValue() default REDACTED_STRING;",
    ),
    "src/java/org/apache/cassandra/config/DurationSpec.java": (
        "public abstract class DurationSpec",
        "private static final Pattern UNITS_PATTERN",
        "public final static class LongMillisecondsBound extends DurationSpec",
        "public final static class IntSecondsBound extends DurationSpec",
    ),
    "src/java/org/apache/cassandra/config/DataStorageSpec.java": (
        "public abstract class DataStorageSpec",
        "public final static class LongBytesBound extends DataStorageSpec",
        "public enum DataStorageUnit",
        "MEBIBYTES",
        "GIBIBYTES",
    ),
    "src/java/org/apache/cassandra/config/DataRateSpec.java": (
        "public abstract class DataRateSpec",
        "public final static class LongBytesPerSecondBound extends DataRateSpec",
        "public enum DataRateUnit",
        "MEBIBYTES_PER_SECOND",
    ),
    "src/java/org/apache/cassandra/db/virtual/SettingsTable.java": (
        "public final class SettingsTable extends AbstractVirtualTable",
        "public static final Map<String, String> BACKWARDS_COMPATIBLE_NAMES = ImmutableMap.copyOf(getBackwardsCompatibleNames());",
        "protected static final Map<String, Property> PROPERTIES = ImmutableMap.copyOf(getProperties());",
        "this.useJsonFormat = CassandraRelevantProperties.VIRTUAL_TABLE_COMPLEX_SETTINGS_FORMAT_JSON.getBoolean();",
        'ClientWarn.instance.warn("key \'" + name + "\' is deprecated; should switch to \'" + BACKWARDS_COMPATIBLE_NAMES.get(name) + "\'");',
        "Redacted maybeCredential = prop.getAnnotation(Redacted.class);",
        'if (key.endsWith("_password") || key.equals("password"))',
        "return JsonUtils.JSON_OBJECT_MAPPER.writeValueAsString(o);",
        "Map<String, Property> properties = loader.flatten(Config.class);",
        "Map<String, Replacement> replacements = Replacements.getNameReplacements(Config.class).get(Config.class);",
        'names.put("authenticator", "authenticator.class_name");',
        'names.put("server_encryption_options_protocol", "server_encryption_options.accepted_protocols");',
    ),
    "src/java/org/apache/cassandra/service/StorageServiceMBean.java": (
        "public void updateSnitch(String epSnitchClassName, Boolean dynamic, Integer dynamicUpdateInterval, Integer dynamicResetInterval, Double dynamicBadnessThreshold) throws ClassNotFoundException;",
        "public void setRpcTimeout(long value);",
        "public void setStreamThroughputMbitPerSec(int value);",
        "public void setStreamThroughputMebibytesPerSec(int value);",
        "public void setCompactionThroughputMbPerSec(int value);",
        "public void setMigrateKeycacheOnCompaction(boolean invalidateKeyCacheOnCompaction);",
        "public void setTombstoneWarnThreshold(int tombstoneDebugThreshold);",
        "public void setBatchSizeWarnThresholdInKiB(int batchSizeDebugThreshold);",
        "public void setReadThresholdsEnabled(boolean value);",
    ),
    "src/java/org/apache/cassandra/service/StorageService.java": (
        "public void setRpcTimeout(long value)",
        "DatabaseDescriptor.setRpcTimeout(value);",
        "public void setStreamThroughputMbitPerSec(int value)",
        "DatabaseDescriptor.setStreamThroughputOutboundMegabitsPerSec(value);",
        "StreamManager.StreamRateLimiter.updateThroughput();",
        "public void setStreamThroughputMebibytesPerSec(int value)",
        "public void setEntireSSTableStreamThroughputMebibytesPerSec(int value)",
        "StreamManager.StreamRateLimiter.updateEntireSSTableThroughput();",
        "public void setInterDCStreamThroughputMebibytesPerSec(int value)",
        "public void setCompactionThroughputMbPerSec(int value)",
        "CompactionManager.instance.setRateInBytes(valueInBytes);",
        "public void updateSnitch(String epSnitchClassName, Boolean dynamic, Integer dynamicUpdateInterval, Integer dynamicResetInterval, Double dynamicBadnessThreshold) throws ClassNotFoundException",
        "DatabaseDescriptor.setDynamicUpdateInterval(dynamicUpdateInterval);",
        "DatabaseDescriptor.createEndpointSnitch(dynamic != null && dynamic, epSnitchClassName);",
        "snitch.applyConfigChanges();",
        "public void setMigrateKeycacheOnCompaction(boolean invalidateKeyCacheOnCompaction)",
        "public void setReadThresholdsEnabled(boolean value)",
    ),
}

TEST_EXPECTATIONS = {
    "test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java": (
        "public void testConfigurationLoader() throws Exception",
        "CONFIG_LOADER.setString(testLoader.getClass().getName());",
        "public void testExceptionsForInvalidConfigValues()",
        "public void testLowestAcceptableTimeouts() throws ConfigurationException",
        "public void testConcurrentValidations()",
        "public void testRepairCommandPoolSize()",
        "Invalid value of entire_sstable_stream_throughput_outbound:",
        "Invalid value of stream_throughput_outbound:",
    ),
    "test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java": (
        "public void validateTypes()",
        "public void updateInPlace()",
        "public void withSystemProperties()",
        "CONFIG_ALLOW_SYSTEM_PROPERTIES",
        "SYSTEM_PROPERTY_PREFIX + \"storage_port\"",
        "public void readConvertersSpecialCasesFromConfig()",
        "public void readConvertersSpecialCasesFromMap()",
        "public void fromMapTest()",
        "public void typeChange()",
        "public void converters()",
        "public void testBackwardCompatibilityOfInternodeAuthenticatorPropertyAsMap()",
    ),
    "test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java": (
        "ALLOW_DUPLICATE_CONFIG_KEYS.setBoolean(false);",
        "public void testDuplicateParamThrows() throws IOException",
        "public void testReplacementDupesOldFirst() throws IOException",
        "public void testReplacementDupesNewFirst() throws IOException",
        "public void testReplacementDupesMultiReplace() throws IOException",
        "found duplicate key endpoint_snitch",
        "[enable_user_defined_functions -> user_defined_functions_enabled]",
    ),
    "test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java": (
        'CASSANDRA_CONFIG.setString("cassandra-old.yaml");',
        "public void testConfigurationLoaderBackwardCompatibility()",
        "config.stream_throughput_outbound",
        "config.inter_dc_stream_throughput_outbound",
        "config.permissions_validity",
    ),
    "test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java": (
        "public void testConfigurationLoaderParser()",
        "config.request_timeout",
        "config.native_transport_max_frame_size",
        "config.compaction_throughput",
        "config.stream_throughput_outbound",
    ),
    "test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java": (
        "public void diff_3_0() throws IOException",
        "public void diff_3_11() throws IOException",
        "public void diff_4_0() throws IOException",
        "public void diff_4_1() throws IOException",
        "public void diff_5_0() throws IOException",
        "BACKWARDS_COMPATIBLE_NAMES",
        "Replacements.getNameReplacements(type)",
        "Property %s changed to nested type but is missing from SettingsTable.BACKWARDS_COMPATIBLE_NAMES",
    ),
    "test/unit/org/apache/cassandra/config/DefaultLoaderTest.java": (
        "public void fieldPresentWithoutGetterOrSetter()",
        "public void fieldPresentWithGetter()",
        "public void noFieldWithGetterAndSetter()",
        "public void noFieldWithoutGetterAndWithSetter()",
    ),
    "test/unit/org/apache/cassandra/config/PropertiesTest.java": (
        "public void backAndForth() throws Exception",
        "public void configMutate() throws Exception",
        "public void nestedMutate() throws Exception",
        "loader.flatten(Config.class)",
        'containsKey("seed_provider.class_name")',
    ),
    "test/unit/org/apache/cassandra/config/CassandraRelevantPropertiesTest.java": (
        "public void testString()",
        "public void testBoolean()",
        "public void testDecimal()",
        "public void testHexadecimal()",
        "public void testOctal()",
        "public void testClearProperty()",
    ),
    "test/unit/org/apache/cassandra/config/ParameterizedClassTest.java": (
        "ParameterizedClass",
        "testNewInstanceWithSingleEmptyConstructorUsesEmptyConstructor",
        "testNewInstanceWithValidConstructorsFavorsMapConstructor",
        "ParameterizedClassExample",
        "newInstance",
    ),
    "test/unit/org/apache/cassandra/config/DataStorageSpecTest.java": (
        "DataStorageSpec",
        "MEBIBYTES",
    ),
    "test/unit/org/apache/cassandra/config/DataRateSpecTest.java": (
        "DataRateSpec",
        "MEBIBYTES_PER_SECOND",
    ),
    "test/unit/org/apache/cassandra/config/DurationSpecTest.java": (
        "DurationSpec",
        "IntSecondsBound",
    ),
}

DOC_EXPECTATIONS = {
    MATRIX_DOC: SCENARIOS + (
        "414 个非 static public field-style 配置声明",
        "96 个 `Config` 级 `@Replaces`",
        "22 个 converter",
        "328 个 system property enum",
        "27 个 4.0 旧名映射",
        "Configuration Loading And Runtime Matrix",
        "Daemon Config Initialization",
        "YAML Load And Overlay",
        "Runtime JMX Update",
    ),
    CHECKER_DOC: SCENARIOS + (
        "Configuration Loading Drift Checker",
        "414 non-static public field-style config declarations",
        "96 `Config` `@Replaces`",
        "22 converter enum entries",
        "328 relevant system properties",
        "27 `system_views.settings` compatibility names",
        "439 runtime setter declarations",
    ),
    README_DOC: (
        "module-configuration-loading-runtime-matrix.md",
        "module-configuration-loading-drift-checker.md",
        "research/tools/check-configuration-loading-drift.py",
        "| Configuration |",
    ),
    SOURCE_MAP_DOC: (
        "Configuration loading/runtime",
        "module-configuration-loading-runtime-matrix.md",
        "module-configuration-loading-drift-checker.md",
        "research/tools/check-configuration-loading-drift.py",
        "src/java/org/apache/cassandra/config/Config.java:58",
        "src/java/org/apache/cassandra/config/DatabaseDescriptor.java:391",
        "src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:71",
        "src/java/org/apache/cassandra/db/virtual/SettingsTable.java:46",
    ),
}

CI_FILES = (
    ".circleci/config.yml",
    "build.xml",
)


@dataclass
class Failure:
    category: str
    path: str
    detail: str


def read(path):
    return (REPO_ROOT / path).read_text(encoding="utf-8")


def count_config_fields(text):
    return len(re.findall(r"^\s+public (?!static)(?:volatile )?[\w<>, ?.\[\]]+\s+\w+(?:\s=|;)", text, re.MULTILINE))


def count_enum_constants(text):
    return len(re.findall(r"^\s+[A-Z0-9_]+\(", text, re.MULTILINE))


def count_runtime_setters(paths):
    pattern = re.compile(r"^\s+(?:public static void set|public void set|void set)", re.MULTILINE)
    return sum(len(pattern.findall(read(path))) for path in paths)


def collect_counts():
    config = read("src/java/org/apache/cassandra/config/Config.java")
    converters = read("src/java/org/apache/cassandra/config/Converters.java")
    relevant_properties = read("src/java/org/apache/cassandra/config/CassandraRelevantProperties.java")
    settings_table = read("src/java/org/apache/cassandra/db/virtual/SettingsTable.java")
    return {
        "config_public_fields": count_config_fields(config),
        "config_replaces": config.count("@Replaces("),
        "converters": count_enum_constants(converters),
        "system_properties": count_enum_constants(relevant_properties),
        "settings_aliases": settings_table.count("names.put("),
        "runtime_setters": count_runtime_setters((
            "src/java/org/apache/cassandra/config/DatabaseDescriptor.java",
            "src/java/org/apache/cassandra/service/StorageService.java",
            "src/java/org/apache/cassandra/service/StorageServiceMBean.java",
        )),
    }


def check_tokens(expectations, category):
    failures = []
    for path, tokens in expectations.items():
        full = REPO_ROOT / path
        if not full.exists():
            failures.append(Failure(category, path, "missing file"))
            continue
        text = full.read_text(encoding="utf-8")
        for token in tokens:
            if token not in text:
                failures.append(Failure(category, path, f"missing token: {token}"))
    return failures


def check_counts():
    failures = []
    actual = collect_counts()
    for name, expected in EXPECTED_COUNTS.items():
        observed = actual[name]
        if observed != expected:
            failures.append(Failure("count", name, f"expected {expected}, observed {observed}"))
    return failures, actual


def check_ci_gap():
    failures = []
    token = "check-configuration-loading-drift.py"
    for path in CI_FILES:
        full = REPO_ROOT / path
        if not full.exists():
            failures.append(Failure("ci", path, "missing CI/build file"))
            continue
        if token in full.read_text(encoding="utf-8"):
            failures.append(Failure("ci", path, f"{token} is now wired; update config_ci_drift_checker_gap"))
    return failures


def main(argv):
    parser = argparse.ArgumentParser(description="Check configuration loading research coverage for drift.")
    parser.add_argument("--json", action="store_true", help="emit machine-readable result")
    args = parser.parse_args(argv)

    failures = []
    failures.extend(check_tokens(SOURCE_EXPECTATIONS, "source"))
    failures.extend(check_tokens(TEST_EXPECTATIONS, "test"))
    failures.extend(check_tokens(DOC_EXPECTATIONS, "doc"))
    count_failures, counts = check_counts()
    failures.extend(count_failures)
    failures.extend(check_ci_gap())

    if args.json:
        print(json.dumps({
            "ok": not failures,
            "counts": counts,
            "failures": [failure.__dict__ for failure in failures],
        }, indent=2, sort_keys=True))
    elif failures:
        for failure in failures:
            print(f"{failure.category}: {failure.path}: {failure.detail}", file=sys.stderr)
    else:
        print(
            "OK configuration loading drift checks passed "
            f"({counts['config_public_fields']} config fields, "
            f"{counts['config_replaces']} replacements, "
            f"{counts['converters']} converters, "
            f"{counts['system_properties']} system properties, "
            f"{counts['settings_aliases']} settings aliases, "
            f"{counts['runtime_setters']} runtime setters, "
            f"{len(SCENARIOS)} scenarios)"
        )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

# Configuration Loading And Runtime Matrix

本矩阵补齐 Cassandra 配置子系统：配置字段定义在 `Config`，加载由 `DatabaseDescriptor` 选择 `ConfigurationLoader` 并应用 daemon/tool/client 三种初始化模式；YAML、system properties、兼容 key 转换、`system_views.settings` 和 JMX runtime setter 构成同一配置面，但生命周期和可变性不同。

## Source Contract

| Scenario | Contract | Source anchors | Test anchors |
| --- | --- | --- | --- |
| `config_model_field_contract` | `Config` 是配置字段总表，`public` 字段映射 YAML 名，`volatile` 字段声明可经 JMX 修改；`PROPERTY_PREFIX` 仅服务内部 Java property，不等同于 YAML overlay 前缀。当前源码有 414 个非 static public field-style 配置声明、96 个 `Config` 级 `@Replaces`、22 个 converter 和 328 个 system property enum。 | `src/java/org/apache/cassandra/config/Config.java:53`, `src/java/org/apache/cassandra/config/Config.java:58`, `src/java/org/apache/cassandra/config/Config.java:79`, `src/java/org/apache/cassandra/config/Config.java:89`, `src/java/org/apache/cassandra/config/Converters.java:44`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:31` | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:100`, `test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:37` |
| `config_database_descriptor_modes_contract` | daemon 初始化加载配置并执行完整 `applyAll()`；tool 初始化只应用兼容、SSTable、simple config、partitioner、snitch、encryption；client 初始化使用空/传入 config，设置 client mode，只应用兼容、disk optimization 和 SSTable format。三种模式互斥。 | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:245`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:283`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:340`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:391`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:447` | `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:71`, `test/unit/org/apache/cassandra/config/DatabaseDescriptorRefTest.java:48` |
| `config_loader_selection_contract` | `DatabaseDescriptor.loadConfig()` 优先使用 `Config.getOverrideLoadConfig()`，否则读取 `cassandra.config.loader` 构造自定义 `ConfigurationLoader`，默认使用 `YamlConfigurationLoader`，并只 log 一次配置。 | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:391`, `src/java/org/apache/cassandra/config/ConfigurationLoader.java:23`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:110`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:174` | `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:71` |
| `config_yaml_url_and_empty_file_contract` | `cassandra.config` 可是 URL 或 classpath resource；本地文件必须带 `file://` 前缀；空 YAML 返回 `new Config()` 而不是 null，避免后续初始化 NPE。 | `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:76`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:119`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:307`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:85` | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:484` |
| `config_yaml_property_checker_contract` | YAML loader 通过 `DefaultLoader` + `PropertiesChecker` 查字段、支持嵌套 `a.b` 路径、拒绝未知属性、拒绝非 nullable 的 null 值，并收集 deprecated warnings。 | `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:321`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:339`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:400`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:417`, `src/java/org/apache/cassandra/config/DefaultLoader.java:44`, `src/java/org/apache/cassandra/config/Properties.java:70` | `test/unit/org/apache/cassandra/config/PropertiesTest.java:36`, `test/unit/org/apache/cassandra/config/DefaultLoaderTest.java:31` |
| `config_duplicate_and_replacement_guard_contract` | raw YAML 先按 `ALLOW_DUPLICATE_CONFIG_KEYS` 处理重复 key，再由 `verifyReplacements()` 检测 old/new 同时出现；`ALLOW_NEW_OLD_CONFIG_KEYS` 只把冲突从失败降级为 warning。 | `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:172`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:198`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:34`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:36` | `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java:67`, `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java:75`, `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java:96` |
| `config_compat_replacement_converter_contract` | `@Replaces` 扫描递归配置类型，old name 通过 `Replacement.toProperty()` 转发到新字段；`Converters` 处理 duration/storage/rate 单位、负值 sentinel、guardrail keyspace/table threshold 兼容反算。 | `src/java/org/apache/cassandra/config/Replacements.java:34`, `src/java/org/apache/cassandra/config/Replacement.java:57`, `src/java/org/apache/cassandra/config/Converters.java:31`, `src/java/org/apache/cassandra/config/Converters.java:170`, `src/java/org/apache/cassandra/config/Config.java:361`, `src/java/org/apache/cassandra/config/Config.java:861` | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:330`, `test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java:43`, `test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java:124` |
| `config_system_property_overlay_contract` | `cassandra.config.allow_system_properties` 打开后，只有 `cassandra.settings.` 前缀的 Java property 会 overlay 到配置对象；该前缀刻意匹配 `system_views.settings`，支持 scalar/nested 路径，不支持任意复杂集合字符串。 | `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:71`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:152`, `src/java/org/apache/cassandra/config/CassandraRelevantProperties.java:173` | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:135`, `test/unit/org/apache/cassandra/config/CassandraRelevantPropertiesTest.java:32` |
| `config_template_defaults_contract` | operator-facing 模板有 compatible/latest 两份：`conf/cassandra.yaml` 保持升级兼容默认值，`conf/cassandra_latest.yaml` 打开最新功能；`test/conf/latest_diff.yaml` 是两者差异的测试 overlay，dtest latest mode 在 `InstanceConfig` 手写同一组 overrides，单 JVM debug 可用 `UnitConfigOverride` 拼接 test configs。 | `conf/cassandra.yaml:11`, `conf/cassandra_latest.yaml:17`, `test/conf/latest_diff.yaml:19`, `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:119`, `test/unit/org/apache/cassandra/config/UnitConfigOverride.java:32` | `test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:37`, `test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java:43`, `test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java:124` |
| `config_parameterized_nested_contract` | `ParameterizedClass` 支持 map 构造器优先、无参构造器兜底和 search package；`InheritingClass` 用于 memtable factory 继承配置；`CustomConstructor` 为 `parameters` 和 `memtable.configurations` 声明泛型并返回 copy-on-write/concurrent 容器。 | `src/java/org/apache/cassandra/config/ParameterizedClass.java:67`, `src/java/org/apache/cassandra/config/ParameterizedClass.java:96`, `src/java/org/apache/cassandra/config/InheritingClass.java:48`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:274`, `src/java/org/apache/cassandra/config/Config.java:192` | `test/unit/org/apache/cassandra/config/ParameterizedClassTest.java`, `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:267` |
| `config_unit_spec_contract` | 配置单位类型分三族：`DurationSpec`、`DataStorageSpec`、`DataRateSpec`；`YamlConfigurationLoaderTest.validateTypes()` 禁止直接把抽象基类放入 `Config` 字段，必须使用有边界的具体类型。 | `src/java/org/apache/cassandra/config/DurationSpec.java:42`, `src/java/org/apache/cassandra/config/DataRateSpec.java:274`, `src/java/org/apache/cassandra/config/DataStorageSpec.java:478`, `src/java/org/apache/cassandra/config/YamlConfigurationLoader.java:274` | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:100`, `test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:37`, `test/unit/org/apache/cassandra/config/DataStorageSpecTest.java`, `test/unit/org/apache/cassandra/config/DataRateSpecTest.java`, `test/unit/org/apache/cassandra/config/DurationSpecTest.java` |
| `config_apply_simple_validation_contract` | `applySimpleConfig()` 是配置归一化/校验中心：初始化 storage port、限制 streaming throughput 上界、校验 commitlog sync、disk access mode、timeout 下限、缓存/目录/commitlog/memtable/native transport/default size。 | `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:478`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1041`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1112`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1129` | `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:282`, `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:354`, `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:491`, `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:594` |
| `config_settings_virtual_table_contract` | `system_views.settings` 用 flatten 后的 `Config` property 暴露当前值，支持 27 个 4.0 旧名映射，`@Redacted` 字段和 map 中 password key 会脱敏，集合/map 可用 JSON 格式输出。 | `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:46`, `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:51`, `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:72`, `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:97`, `src/java/org/apache/cassandra/db/virtual/SettingsTable.java:151`, `src/java/org/apache/cassandra/config/Redacted.java:36` | `test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java:46`, `test/unit/org/apache/cassandra/config/PropertiesTest.java:36` |
| `config_runtime_jmx_setter_contract` | Runtime 可变配置主要经 `StorageServiceMBean`/`StorageService` 到 `DatabaseDescriptor` setter，再联动 rate limiter、compaction manager、snitch、cache 或 guardrails；不是所有 `volatile` YAML 字段都有 JMX setter。 | `src/java/org/apache/cassandra/service/StorageServiceMBean.java:713`, `src/java/org/apache/cassandra/service/StorageService.java:1664`, `src/java/org/apache/cassandra/service/StorageService.java:1782`, `src/java/org/apache/cassandra/service/StorageService.java:1924`, `src/java/org/apache/cassandra/service/StorageService.java:6294`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:2188` | `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:354`, `test/unit/org/apache/cassandra/tools/nodetool/GuardrailsConfigCommandsTest.java:164` |
| `config_guardrails_startup_checks_contract` | Guardrails 和 startup checks 是 `applyAll()` 尾部构造的配置对象，配置字段在 `Config`，运行对象在 `DatabaseDescriptor`；异常要包装成配置错误，避免 daemon 半初始化。 | `src/java/org/apache/cassandra/config/Config.java:955`, `src/java/org/apache/cassandra/config/Config.java:966`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:473`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1112`, `src/java/org/apache/cassandra/config/DatabaseDescriptor.java:1129` | `test/unit/org/apache/cassandra/config/StartupCheckOptionsTest.java`, `test/unit/org/apache/cassandra/db/guardrails/GuardrailsConfigProviderTest.java` |
| `config_existing_unit_tests_baseline` | 现有 unit tests 覆盖 loader selection、YAML map/update、system property overlay、converter special cases、旧 YAML、跨版本 diff、duplicate old/new key、property flatten/mutate、system property parser、unit spec parser 和 DatabaseDescriptor 校验。 | `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java`, `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java`, `test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java`, `test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java`, `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java` | same |
| `config_ci_drift_checker_gap` | 当前 checker 是 research 层 source/test/doc gate，尚未接入 Ant/CircleCI；若未来 CI 调用 `check-configuration-loading-drift.py`，需要更新本矩阵并关闭 gap。 | `.circleci/`, `build.xml`, `research/tools/check-configuration-loading-drift.py` | none |

## Design Goals

- 给开发者一个可追踪的配置真相源：任意配置项必须能从 YAML 名称追到 `Config` 字段、兼容旧名、单位类型、`DatabaseDescriptor` 应用点、runtime setter 和测试用例。
- 把启动期配置错误尽早变成 `ConfigurationException`，而不是让 daemon 带着半应用配置继续运行。
- 维持旧版本 YAML 和 `system_views.settings` 旧列名兼容，降低升级成本。
- 区分 compatible 模板、latest 模板、test overlay 和 dtest latest overrides，避免默认值演进只改一处。
- 将 daemon/tool/client 三种初始化面分开，使离线工具和 client-mode 测试不会意外初始化完整 server。

## Problems Solved

- 旧配置名与新单位类型迁移：`@Replaces` + `Converters` 让 `*_in_ms`、`*_in_mb`、megabits/sec 等旧格式仍能进入新 `DurationSpec`/`DataStorageSpec`/`DataRateSpec` 字段。
- 配置来源分裂：`YamlConfigurationLoader` 统一 URL/classpath/file 配置，`DatabaseDescriptor` 统一加载器选择，system property overlay 只开放 `cassandra.settings.` 前缀。
- Runtime 变更可见性：`StorageServiceMBean` setter 明确哪些配置可在线改，并把变更同步给 rate limiter、compaction、snitch、cache 或 guardrails。
- 运维观测：`system_views.settings` 让当前生效配置可查询，同时处理旧名、脱敏和复杂类型格式。

## Design Tradeoffs

- `Config` 保持 public field 模型，方便 SnakeYAML 与 reflection flatten；代价是字段过多且编译器无法强约束所有 YAML 名称变化，必须靠 drift checker 和 compatibility tests 补强。
- 旧名兼容通过 annotation 和 converter 局部声明，升级成本低；代价是 duplicate old/new 检测必须先解析 raw YAML。
- `cassandra.settings.` overlay 只处理 Java system properties 的字符串值，适合自动化覆盖 scalar/nested scalar；复杂集合仍应留在 YAML 或 map-based tests。
- `system_views.settings` flatten 嵌套 property 可读性好，但旧版 4.0 使用 underscore 名称，需显式 `BACKWARDS_COMPATIBLE_NAMES` 映射。
- `volatile` 表示可被 JMX 变更的意图，不等于自动生成 setter；runtime 变更仍依赖手写 `StorageService`/`DatabaseDescriptor` 方法。

## Core Classes

| Class | Responsibility |
| --- | --- |
| `Config` | 配置字段总表、默认值、client mode flag、`@Replaces` 标注和嵌套 option 类型。 |
| `DatabaseDescriptor` | 加载配置、三种初始化模式、`applyAll()`/`applySimpleConfig()`、配置归一化和 runtime getter/setter。 |
| `YamlConfigurationLoader` | YAML/URL 读取、replacement duplicate 检测、SnakeYAML constructor、system property overlay、`fromMap()`/`updateFromMap()` 测试入口。 |
| `DefaultLoader` / `Properties` | 反射发现字段/JavaBean property，flatten 嵌套配置路径，支持 `Properties.andThen()` 写入嵌套对象。 |
| `Replacement` / `Replacements` / `Replaces` / `Converters` | 旧名/旧类型兼容系统。 |
| `CassandraRelevantProperties` / `CassandraRelevantEnv` | 受支持 system properties/env 的类型化访问入口。 |
| `ParameterizedClass` / `InheritingClass` | pluggable provider class name + parameters，以及 memtable configuration 继承。 |
| `SettingsTable` | `system_views.settings` 当前配置投影、旧名映射、脱敏和复杂值格式化。 |
| `StorageServiceMBean` / `StorageService` | JMX runtime config facade。 |

## Core Interfaces

- `ConfigurationLoader.loadConfig()`：自定义 loader SPI，`DatabaseDescriptor.loadConfig()` 根据 `cassandra.config.loader` 构造。
- `Loader.getProperties()` / `Loader.flatten()`：配置 property 枚举与嵌套展开接口。
- `StorageServiceMBean`：runtime setter/getter 运维接口。

## Core Data Structures

- `Config` public fields：YAML schema 的源码表示。
- `Map<Class<?>, Map<String, Replacement>>`：按配置类型索引 old-name replacement。
- `PropertiesChecker.missingProperties/nullProperties/deprecationWarnings`：loader 阶段错误与告警集合。
- `SettingsTable.PROPERTIES`：flatten 后的 `system_views.settings` property map。
- `SettingsTable.BACKWARDS_COMPATIBLE_NAMES`：旧 settings 表列名到新 dotted path 的映射。
- `DurationSpec`/`DataStorageSpec`/`DataRateSpec`：带单位和边界的配置值对象。

## Lifecycle

### Daemon Config Initialization

```text
CassandraDaemon.applyConfig()
  -> DatabaseDescriptor.daemonInitialization()
     -> loadConfig()
        -> overrideLoadConfig? custom loader? YamlConfigurationLoader
        -> Config.log(config)
     -> setConfig(config)
     -> applyAll()
        -> applyCompatibilityMode()
        -> applySSTableFormats()
        -> applyCryptoProvider()
        -> applySimpleConfig()
        -> applyPartitioner()
        -> applyAddressConfig()
        -> applySnitch()
        -> applyTokensConfig()
        -> applySeedProvider()
        -> applyEncryptionContext()
        -> applySslContext()
        -> createAllDirectories()
        -> applyGuardrails()
        -> applyStartupChecks()
     -> AuthConfig.applyAuth()
```

### YAML Load And Overlay

```text
YamlConfigurationLoader.loadConfig()
  -> getStorageConfigURL()
  -> read bytes
  -> getNameReplacements(Config.class)
  -> verifyReplacements(raw yaml)
  -> PropertiesChecker
  -> CustomConstructor(Config.class)
  -> yaml.loadAs(..., Config.class)
  -> propertiesChecker.check()
  -> maybeAddSystemProperties()
     -> read -Dcassandra.settings.*
     -> updateFromMap(map, false, config)
```

### Runtime JMX Update

```text
operator / nodetool / JMX client
  -> StorageServiceMBean setter
  -> StorageService setter
  -> DatabaseDescriptor setter mutates Config/static derived state
  -> optional side effect
     -> StreamManager.StreamRateLimiter.update*
     -> CompactionManager.instance.setRateInBytes
     -> DynamicEndpointSnitch.applyConfigChanges
     -> cache / guardrail state update
```

## Configuration Items

| Config/property | Definition | Impact |
| --- | --- | --- |
| `cassandra.config` | `CassandraRelevantProperties.CASSANDRA_CONFIG` | YAML URL/classpath/file location. |
| `cassandra.config.loader` | `CassandraRelevantProperties.CONFIG_LOADER` | Custom `ConfigurationLoader` implementation. |
| `conf/cassandra.yaml` | distribution template | Compatible default template used for upgrade-safe deployments; keeps latest-only feature flips commented or legacy-compatible. |
| `conf/cassandra_latest.yaml` | distribution template | Latest default template for new-feature defaults such as BTI/Trie/UCS-related settings and `stream_entire_sstables`. |
| `test/conf/latest_diff.yaml` | test overlay | Derived diff from compatible to latest template; must stay aligned with `InstanceConfig` latest-mode overrides. |
| `cassandra.config.allow_system_properties` | `CassandraRelevantProperties.CONFIG_ALLOW_SYSTEM_PROPERTIES` | Enables `cassandra.settings.` overlay. |
| `cassandra.allow_duplicate_config_keys` | `CassandraRelevantProperties.ALLOW_DUPLICATE_CONFIG_KEYS` | Controls SnakeYAML duplicate key handling. |
| `cassandra.allow_new_old_config_keys` | `CassandraRelevantProperties.ALLOW_NEW_OLD_CONFIG_KEYS` | Controls old/new replacement duplicate failure vs warning. |
| `cassandra.settings.*` | `YamlConfigurationLoader.SYSTEM_PROPERTY_PREFIX` | Runtime process system property overlay into config object at load time. |
| `cassandra.virtual_table_complex_settings_format_json` | `CassandraRelevantProperties.VIRTUAL_TABLE_COMPLEX_SETTINGS_FORMAT_JSON` | Controls collection/map formatting in `system_views.settings`. |
| `stream_throughput_outbound` and old `*_megabits_per_sec` | `Config.stream_throughput_outbound` + `Converters.MEGABITS_TO_BYTES_PER_SECOND_DATA_RATE` | Streaming rate config and JMX runtime conversion. |
| `startup_checks` | `Config.startup_checks` | Input for `StartupChecksOptions`. |
| guardrails YAML fields | `Config` guardrail block | Input for `GuardrailsOptions` and runtime guardrail config. |

## Metrics

- 配置加载本身没有独立 metric；证据主要来自 startup log、异常、JMX getter、`system_views.settings` 查询和相关组件 metrics。
- Runtime throughput setter 会影响 streaming/compaction 的实际 rate limiter 和相关 metrics，但 metric 定义仍在 streaming/compaction 模块。
- `system_views.settings` 是配置观测面，不是 metric；查询成本来自 virtual table reflection/value formatting。

## Logs

- `YamlConfigurationLoader.getStorageConfigURL()` 记录 `Configuration location: ...`。
- `YamlConfigurationLoader.loadConfig(URL)` debug 记录 `Loading settings from ...`。
- `PropertiesChecker.check()` 对 deprecated 配置名记录 warning。
- `DatabaseDescriptor.applySimpleConfig()` 记录 disk access mode、commitlog sync mode、memtable thresholds、native transport rate limit 和 CDC enabled 等派生配置。
- `StorageService` runtime setter 记录配置变更，例如 stream throughput、compaction throughput、tombstone threshold 和 snitch config。

## Operational Notes

- 变更 YAML 字段时必须同步 `Config` 字段、`@Replaces`、`conf/cassandra.yaml`/`cassandra_latest.yaml`、`system_views.settings` 旧名映射、unit tests 和本文档。
- 不要把 `Config.PROPERTY_PREFIX` 与 `YamlConfigurationLoader.SYSTEM_PROPERTY_PREFIX` 混淆；前者是内部 Java property 命名风格，后者才是 YAML overlay gate。
- 自定义 loader 必须返回完整可应用的 `Config`，否则 `applySimpleConfig()` 会在 daemon 初始化中失败。
- 旧名和新名同时出现在 YAML 默认是失败；临时升级窗口可用 `cassandra.allow_new_old_config_keys=true` 降级为 warning，但应清理旧名。
- `system_views.settings` 会 redaction credential，但 map 参数 key 只按 `password`/`*_password` best effort 脱敏。
- 修改 `conf/cassandra_latest.yaml` 的 latest-only 默认值时，同步检查 `test/conf/latest_diff.yaml` 和 `InstanceConfig` 的 `DTEST_JVM_DTESTS_USE_LATEST` 分支。

## Performance Bottlenecks

- YAML 加载需要读取完整文件并做 raw duplicate/replacement 检查，默认 code point limit 是 64 MiB。
- `Properties.flatten(Config.class)` 和 `SettingsTable.PROPERTIES` 依赖 reflection；启动时构造成本可接受，但查询 `system_views.settings` 全表会格式化所有配置值。
- `applySimpleConfig()` 会访问文件系统容量、目录配置和运行时内存大小，慢盘或异常文件系统会放大启动延迟。
- Runtime setter 本身很轻，但联动的 rate limiter、snitch 更新、cache 策略变化可能影响正在运行的请求。

## Common Failures

- `Invalid yaml. Please remove properties ...`：YAML 中存在未知 key 或 nested path 拼错。
- `Invalid yaml. Those properties ... are not valid`：给非 nullable 默认字段赋 null。
- `Config contains both old and new keys...`：旧名和新名同时存在；移除旧名或临时设置 `ALLOW_NEW_OLD_CONFIG_KEYS`。
- 本地 `cassandra.config` 缺少 `file://` 前缀：`getStorageConfigURL()` 会拒绝。
- 自定义 class 参数实例化失败：检查 `ParameterizedClass.class_name`、search package、map/no-arg constructor 和 parameters 类型。
- JMX setter 修改无效：确认该配置确实有 `StorageServiceMBean` setter，并检查是否需要额外 side effect 更新 rate limiter/manager。

## Test Cases

| Test | Coverage |
| --- | --- |
| `test/unit/org/apache/cassandra/config/DatabaseDescriptorTest.java:71` | 默认 YAML loader 与 custom `ConfigurationLoader` selection。 |
| `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:100` | `Config` 字段不能使用抽象 spec 类型。 |
| `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:135` | `cassandra.settings.` system property overlay。 |
| `test/unit/org/apache/cassandra/config/YamlConfigurationLoaderTest.java:330` | converter special cases and old names。 |
| `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java:67` | duplicate YAML key failure。 |
| `test/unit/org/apache/cassandra/config/FailStartupDuplicateParamsTest.java:75` | old/new replacement duplicate failure。 |
| `test/unit/org/apache/cassandra/config/ConfigCompatibilityTest.java:124` | 3.0/3.11/4.0/4.1/5.0 config tree compatibility diff。 |
| `test/unit/org/apache/cassandra/config/LoadOldYAMLBackwardCompatibilityTest.java:43` | old YAML duration/storage/rate compatibility parse。 |
| `test/unit/org/apache/cassandra/config/ParseAndConvertUnitsTest.java:37` | default YAML unit parse baseline。 |
| `test/distributed/org/apache/cassandra/distributed/impl/InstanceConfig.java:119` | dtest `DTEST_JVM_DTESTS_USE_LATEST` latest defaults mirror `latest_diff.yaml`。 |
| `test/distributed/org/apache/cassandra/distributed/upgrade/ConfigCompatibilityTestGenerate.java:43` | manual generator for versioned config compatibility dumps。 |
| `test/unit/org/apache/cassandra/config/PropertiesTest.java:36` | flatten property get/set round trip。 |
| `test/unit/org/apache/cassandra/config/DefaultLoaderTest.java:31` | field vs getter/setter property precedence。 |
| `test/unit/org/apache/cassandra/config/CassandraRelevantPropertiesTest.java:32` | typed system property access and reset behavior。 |

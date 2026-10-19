---
name: java-spring-boot
description: "Spring Boot 3.x/4.x service essentials. Covers constructor injection and configuration-properties records, transaction proxy rules, JPA/Hibernate N+1 and fetch strategy, RestClient and HTTP interfaces, virtual threads, observability, Spring Security basics, test slices with Testcontainers, and the Boot 4 migration. Load when building, debugging or upgrading a Spring Boot service."
when_to_use: "Editing application.yml or @Configuration classes; LazyInitializationException, N+1 query logs or slow list endpoints; @Transactional that does not roll back or does not apply; RestClient or WebClient timeouts; spring.threads.virtual.enabled; Actuator probes, Micrometer or tracing setup; SecurityFilterChain, JWT resource server or CSRF errors; slow @SpringBootTest suites; upgrading Boot 3.x to 3.5 or 4.0 (Jackson 3, Jakarta EE 11)."
---

# Spring Boot services (3.x and 4.x)

Boot 3.x = Spring Framework 6, Jakarta EE 10, Java 17+. Boot 4.0 (November 2025) = Framework 7,
Jakarta EE 11, Jackson 3, JSpecify nullness, modular auto-configuration, still Java 17+.
Everything below applies to both unless marked. Build wiring: `java-build-maven-gradle`; test
tooling: `java-testing-junit`; full upgrade procedure: [Boot 4 migration](references/boot4-migration.md).

## 1. Orientation

```bash
grep -nE 'spring-boot' pom.xml build.gradle.kts gradle/libs.versions.toml 2>/dev/null | head
./mvnw -q dependency:tree -Dincludes=org.springframework.boot | head -20
java -jar target/app.jar --debug 2>&1 | sed -n '/CONDITIONS EVALUATION REPORT/,/Unconditional classes/p' | less
curl -s localhost:8080/actuator/conditions | jq '.contexts[].negativeMatches | keys'   # needs exposure
curl -s localhost:8080/actuator/env/spring.datasource.url | jq '.propertySources'      # which source won
```

The conditions report answers "why is (or isn't) this bean here". `/actuator/env` masks values by
default but still shows which property source supplied a key. Starters: Boot 4 renames
`spring-boot-starter-web` to `spring-boot-starter-webmvc` and adds per-technology test starters.

Precedence, highest first: test properties > command-line args > `SPRING_APPLICATION_JSON` >
Java system properties > OS env vars > config files (outside the jar beats inside, profile-specific
beats plain) > `@PropertySource` > defaults. Env var binding: `PAYMENTS_GATEWAY_BASEURL` ->
`payments.gateway.base-url` (dots to `_`, drop `-`, upper-case). Profiles: activate with
`SPRING_PROFILES_ACTIVE=prod`, group with `spring.profiles.group.prod=db,otel`, scope a YAML
document with `spring.config.activate.on-profile`. Profiles select behaviour; secrets come from
env vars or a secret store.

## 2. DI and configuration

```java
@ConfigurationProperties(prefix = "payments.gateway")
@Validated                                           // needs spring-boot-starter-validation
public record GatewayProperties(
        @NotNull URI baseUrl,
        @DefaultValue("2s") Duration connectTimeout,
        @DefaultValue("5s") Duration readTimeout,
        @Min(1) @DefaultValue("3") int maxAttempts) {}

@SpringBootApplication @ConfigurationPropertiesScan
public class PaymentsApplication { public static void main(String[] a) { SpringApplication.run(PaymentsApplication.class, a); } }

@Service
class RefundService {                                // single constructor: no @Autowired
    private final PaymentRepository payments;
    private final GatewayClient gateway;
    RefundService(PaymentRepository payments, GatewayClient gateway) { this.payments = payments; this.gateway = gateway; }
}
```

- Constructor injection with `final` fields; no field or setter injection (untestable, hides cycles).
- Circular references fail at startup (since 2.6). Fix the design (extract the shared part into a
  third bean, or publish an event); `spring.main.allow-circular-references` and `@Lazy` hide it.
- `@Value` for one-off values only; groups of settings get a record. Add
  `spring-boot-configuration-processor` for IDE metadata.

## 3. Transactions

`@Transactional` is applied by a proxy around the bean: only calls entering through the proxy
are transactional.

| Trap | Effect | Fix |
|---|---|---|
| self-invocation (`this.markClosed()`) | no transaction; each repository call commits alone | annotate the public entry method, move the method to another bean, or `TransactionTemplate` |
| `private` or `final` method | never intercepted | public (or package-visible with class proxies, Framework 6+) |
| checked exception thrown | **commits**; default rollback is `RuntimeException` and `Error` only | `rollbackFor = Exception.class`; Framework 6.2+ `@EnableTransactionManagement(rollbackOn = RollbackOn.ALL_EXCEPTIONS)` |
| inner call fails, caller catches it | `UnexpectedRollbackException` (rollback-only) at commit | do not swallow inside the transaction |
| `REQUIRES_NEW` | second connection while the first is held; inner commit survives outer rollback | pool size > concurrent callers x 2, or redesign (outbox) |
| work on `@Async` or another thread | transactions are thread-bound | start one inside the async method |
| `@TransactionalEventListener` (default `AFTER_COMMIT`) | runs after commit; its writes need `REQUIRES_NEW` | outbox table for reliable side effects |

`@Transactional(readOnly = true)` at class level for query services (Hibernate skips dirty
checking and flush), `@Transactional` on write methods. Programmatic:
`transactionTemplate.executeWithoutResult(status -> ...)`. Trace boundaries with
`logging.level.org.springframework.orm.jpa.JpaTransactionManager=debug` ("Creating new transaction").

## 4. JPA and Hibernate

```properties
spring.jpa.open-in-view=false
spring.jpa.properties.hibernate.default_batch_fetch_size=50
# dev and tests only
logging.level.org.hibernate.SQL=debug
logging.level.org.hibernate.orm.jdbc.bind=trace
spring.jpa.properties.hibernate.generate_statistics=true
```

Open-in-view (Boot's default, with a startup warning) keeps the session open through view
rendering and hides N+1 queries; turn it off and fetch what each use case needs. With statistics
on, every session logs "Session Metrics" (statements prepared, time spent).

| Use case | Fetch with | Caveat |
|---|---|---|
| list/read endpoint | DTO projection (`select new ...View(...)`, record or interface projection) | no entities, no lazy loading, one statement |
| write use case needing a graph | `join fetch` or `@EntityGraph(attributePaths = {"customer", "lines"})` | collection fetch + paging = in-memory paging (HHH90003004): page ids first, then fetch |
| to-one across a page | `default_batch_fetch_size` or `@BatchSize` | N queries become N/batch |
| all associations | `fetch = FetchType.LAZY`, including `@ManyToOne`/`@OneToOne` | to-one defaults to EAGER: the classic hidden N+1 |

```java
@Entity
public class PurchaseOrder {
    @Id @GeneratedValue private Long id;
    @Version private long version;                                    // optimistic locking
    @ManyToOne(fetch = FetchType.LAZY) private Customer customer;
    @OneToMany(mappedBy = "order", cascade = CascadeType.ALL, orphanRemoval = true) private List<OrderLine> lines = new ArrayList<>();
    public Long getId() { return id; }
    @Override public boolean equals(Object o) {                       // getter: works on Hibernate proxies
        return this == o || (o instanceof PurchaseOrder other && id != null && id.equals(other.getId()));
    }
    @Override public int hashCode() { return PurchaseOrder.class.hashCode(); }   // stable across persist
}
```

`@Version` conflicts surface as `ObjectOptimisticLockingFailureException`: return 409 or retry the
whole idempotent use case. Never return entities from controllers; map to records.

## 5. HTTP

```java
@HttpExchange("/v1")
public interface GatewayClient {
    @PostExchange("/charges")
    ChargeResponse charge(@RequestHeader("Idempotency-Key") String key, @RequestBody ChargeRequest body);
}

@Bean
GatewayClient gatewayClient(RestClient.Builder builder, GatewayProperties props) {
    var http = HttpClient.newBuilder().connectTimeout(props.connectTimeout()).build();
    var factory = new JdkClientHttpRequestFactory(http);
    factory.setReadTimeout(props.readTimeout());                 // no timeout = threads stuck forever
    RestClient rest = builder.baseUrl(props.baseUrl().toString()).requestFactory(factory).build();
    return HttpServiceProxyFactory.builderFor(RestClientAdapter.create(rest)).build().createClient(GatewayClient.class);
}
@RestControllerAdvice
class ApiErrors extends ResponseEntityExceptionHandler {          // framework exceptions become ProblemDetail too
    @ExceptionHandler(PaymentNotFoundException.class)
    ProblemDetail notFound(PaymentNotFoundException e) {
        var pd = ProblemDetail.forStatusAndDetail(HttpStatus.NOT_FOUND, e.getMessage());
        pd.setType(URI.create("https://errors.acme.example/payment-not-found"));
        pd.setProperty("paymentId", e.id());
        return pd;
    }
}
```

`RestClient` (Framework 6.1+, Boot 3.2+) for blocking code, including on virtual threads;
`WebClient` only in a WebFlux application (never `.block()` inside MVC). Framework 7 can register
interface clients in groups with `@ImportHttpServices` instead of the factory code. Errors use
RFC 9457 problem details; without a custom advice, `spring.mvc.problemdetails.enabled=true`
renders Spring MVC's own exceptions as `application/problem+json`.

## 6. Concurrency

```properties
spring.threads.virtual.enabled=true            # 3.2+ on Java 21+: web requests, @Async, @Scheduled, listeners
spring.main.keep-alive=true                    # virtual threads are daemons: keeps scheduler-only apps alive
spring.task.execution.simple.concurrency-limit=200
spring.datasource.hikari.maximum-pool-size=20
spring.datasource.hikari.connection-timeout=2000
```

Virtual threads remove the request-thread cap, so the database pool becomes the limit: size it
from measured concurrency, keep `connection-timeout` short, and bound fan-out
(`concurrency-limit`, semaphores). On JDK 21-23, `synchronized` around I/O pins carriers (fixed
in 24). `@Scheduled` fixed-rate jobs can overlap when a run outlasts the period; use fixed delay
or a lock (ShedLock across instances). Details: `java-virtual-threads`.

## 7. Observability

```properties
management.endpoints.web.exposure.include=health,info,prometheus
management.endpoint.health.probes.enabled=true
management.endpoint.health.group.readiness.include=readinessState,db
management.endpoint.health.show-details=when-authorized
management.tracing.sampling.probability=0.1
management.otlp.tracing.endpoint=http://otel-collector:4318/v1/traces
logging.structured.format.console=ecs
```

- Probes: `/actuator/health/liveness` checks application state only (a DB in liveness restarts
  every pod on a DB blip); `/actuator/health/readiness` may include the database. Auto-enabled on Kubernetes.
- Metrics: `micrometer-registry-prometheus` -> `/actuator/prometheus`. `@Observed`/`@Timed` need
  the annotation aspects (`management.observations.annotations.enabled=true`, 3.2+, AspectJ on
  the classpath). Never tag with ids or raw URIs (cardinality).
- Tracing on 3.x: `micrometer-tracing-bridge-otel` + `opentelemetry-exporter-otlp` (ids reach the
  logging MDC). Boot 4 adds an OpenTelemetry starter; confirm 4.x property names before reuse.
- Structured logging (3.4+): `logging.structured.format.console=ecs` or `logstash`.

## 8. Security

```java
@Configuration @EnableMethodSecurity
class SecurityConfig {
    @Bean
    SecurityFilterChain api(HttpSecurity http) throws Exception {
        return http
            .authorizeHttpRequests(auth -> auth
                .requestMatchers("/actuator/health/**").permitAll()
                .requestMatchers(HttpMethod.GET, "/api/payments/**").hasAuthority("SCOPE_payments:read")
                .requestMatchers("/api/**").hasAuthority("SCOPE_payments:write")
                .anyRequest().denyAll())
            .oauth2ResourceServer(rs -> rs.jwt(Customizer.withDefaults()))
            .sessionManagement(s -> s.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
            .csrf(csrf -> csrf.disable())     // bearer-token API only; cookie sessions keep CSRF on
            .build();
    }
}
```

`spring.security.oauth2.resourceserver.jwt.issuer-uri` (or `jwk-set-uri` to avoid an IdP call at
startup) plus audience validation. Method rules: `@PreAuthorize("hasAuthority('SCOPE_payments:refund')")`.
Browser apps with session cookies keep CSRF enabled. Spring Security 7 (Boot 4) accepts only the
lambda DSL: no `and()` chains, no `authorizeRequests`. Deeper review: `security-review`.

## 9. Tests

| Slice | Loads | Test here |
|---|---|---|
| `@WebMvcTest(PaymentController.class)` | MVC, advice, filters, Jackson, security | mapping, validation, problem details, access rules |
| `@DataJpaTest` | repositories, `EntityManager`, Flyway; each test rolls back | queries, mappings, SQL counts |
| `@JsonTest` | Jackson + `JacksonTester` | wire-format contracts |
| `@RestClientTest(GatewayClient.class)` | client builder + `MockRestServiceServer` | client mapping |
| `@SpringBootTest` | the whole app | a handful of end-to-end wiring tests |

```java
@TestConfiguration(proxyBeanMethods = false)
public class PostgresTestConfig {
    @Bean @ServiceConnection
    PostgreSQLContainer<?> postgres() { return new PostgreSQLContainer<>("postgres:17-alpine"); }
}
```

Use it with `@Import(PostgresTestConfig.class)` (plus `@AutoConfigureTestDatabase(replace = NONE)`
on `@DataJpaTest`), and for local runs via
`SpringApplication.from(PaymentsApplication::main).with(PostgresTestConfig.class).run(args)`.
Mocks: `@MockitoBean` (Framework 6.2, Boot 3.4+); `@MockBean` is deprecated in 3.4, removed in 4.0.
Context cache: each distinct set of configuration, profiles, properties and mock beans builds a
new context (max 32 cached). Keep one shared IT configuration, put `@MockitoBean`s in a common
base class, avoid `@DirtiesContext`, check hits with `logging.level.org.springframework.test.context.cache=debug`.

## 10. Boot 4 migration checklist

1. Latest 3.5.x with zero deprecation warnings; `spring-boot-properties-migrator` reports renamed keys.
2. OpenRewrite `org.openrewrite.java.spring.boot4.UpgradeSpringBoot_4_0` (rewrite-spring), reviewed as a normal diff.
3. Modular auto-configuration: `webmvc` starter rename, per-technology test starters, classic starters only as a bridge, moved imports.
4. Spring Framework 7 + Jakarta EE 11: Tomcat 11 or Jetty 12.1 (no Undertow), JPA 3.2 with Hibernate 7, Validation 3.1.
5. Jackson 3: group `tools.jackson.core`, packages `tools.jackson.*` (annotations unchanged), `JsonMapperBuilderCustomizer`; diff payloads with `@JsonTest`.
6. JSpecify nullness in Spring APIs: new NullAway/Kotlin errors where nullable returns were ignored.
7. Tests: `@MockitoBean`, JUnit 6, Testcontainers 2, `RestTestClient`; Security 7 lambda DSL; canary deploy.

## 11. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| `LazyInitializationException` after turning open-in-view off | graph not fetched inside the transaction | DTO projection or fetch join for that use case |
| list endpoint slows linearly with page size | N+1 on to-one or collections | section 4, then assert statement counts |
| data half-written after an exception | self-invoked or private `@Transactional`, checked exception | section 3 |
| `UnexpectedRollbackException` | inner failure swallowed | rethrow, or separate the transaction deliberately |
| request threads blocked for minutes on a slow API | no read timeout | timeouts on every client |
| pods restart when the DB blips | DB in the liveness group | DB only in readiness |
| slow suite, many "Spring Boot" banners | context cache misses | section 9 |
| `@ConfigurationProperties` values silently null | missing scan or wrong prefix | `@ConfigurationPropertiesScan`, `@Validated` with `@NotNull` |

## 12. Worked example: an N+1 listing and a self-invoked `@Transactional`

Before: `GET /api/orders?status=OPEN` returns 20 orders in 41 statements (1 for orders, up to 20
for customers, 20 for lines) with open-in-view on, and `LazyInitializationException` with it off.
`POST /api/orders/{id}/close` sometimes writes the outbox event while the order stays OPEN.

```java
public List<OrderView> list(OrderStatus status, Pageable page) {
    return orders.findByStatus(status, page).stream()                          // 1 query
        .map(o -> new OrderView(o.getId(), o.getCustomer().getName(),          // +1 per order
                                (long) o.getLines().size(), o.total()))         // +1 per order
        .toList();
}
public void close(long id) { markClosed(id); }   // self-invocation: proxy bypassed
@Transactional void markClosed(long id) {
    orders.findById(id).orElseThrow().close();    // detached entity: the change is never flushed
    outbox.save(OutboxEvent.orderClosed(id));     // commits on its own
}
```

After: one projection query, one transaction at the entry point.

```java
@Query("""
    select new com.acme.orders.OrderView(o.id, c.name, count(l), sum(l.amount))
    from PurchaseOrder o join o.customer c left join o.lines l
    where o.status = :status
    group by o.id, c.name
    order by o.id""")
List<OrderView> findViews(@Param("status") OrderStatus status, Pageable page);   // in PurchaseOrderRepository
public record OrderView(Long id, String customerName, Long lineCount, BigDecimal total) {
    public OrderView { total = total == null ? BigDecimal.ZERO : total; }
}

@Service @Transactional(readOnly = true)
public class OrderService {
    public List<OrderView> list(OrderStatus status, Pageable page) { return orders.findViews(status, page); }
    @Transactional
    public void close(long id) {
        orders.findById(id).orElseThrow(() -> new OrderNotFoundException(id)).close();
        outbox.save(OutboxEvent.orderClosed(id));
    }
}
```

Verification with SQL-count assertions (Hibernate statistics; rows seeded with `JdbcTemplate`
so seeding is not counted):

```java
@DataJpaTest
@AutoConfigureTestDatabase(replace = AutoConfigureTestDatabase.Replace.NONE)
@Import({PostgresTestConfig.class, OrderService.class})
@TestPropertySource(properties = "spring.jpa.properties.hibernate.generate_statistics=true")
@Transactional(propagation = Propagation.NOT_SUPPORTED)     // let OrderService own its transactions
class OrderServiceSqlTest {
    @Autowired OrderService service;
    @Autowired EntityManagerFactory emf;
    @Autowired JdbcTemplate jdbc;
    Statistics stats;
    @BeforeEach void seed() {
        TestOrders.insert(jdbc, 25, 3);                        // 25 OPEN orders x 3 lines
        stats = emf.unwrap(SessionFactory.class).getStatistics();
        stats.clear();
    }
    @AfterEach void clean() { TestOrders.truncate(jdbc); }
    @Test void listingIsOneStatement() {
        assertThat(service.list(OrderStatus.OPEN, PageRequest.of(0, 20))).hasSize(20);
        assertThat(stats.getPrepareStatementCount()).isEqualTo(1);
    }

    @Test void closeIsOneTransaction() {
        long id = TestOrders.anyOpenId(jdbc);
        service.close(id);
        assertThat(stats.getTransactionCount()).isEqualTo(1);
        assertThat(jdbc.queryForObject("select status from purchase_order where id = ?", String.class, id)).isEqualTo("CLOSED");
    }
}
```

Run the test against the old code first: 41 statements (or `LazyInitializationException`) and 2
transactions with the order still OPEN; after the fix, 1 statement and 1 transaction. Done when
both assertions are green, `org.hibernate.SQL` shows a single select for the listing, and the
endpoint's latency no longer grows with page size.

Related: `java-testing-junit`, `java-build-maven-gradle`, `java-virtual-threads`, `java-quarkus`, `sql-query-tuning`, `observability-instrumentation`, `security-review`, hub `java-craft`

---
name: java-quarkus
description: "Quarkus 3 services. Covers extensions, CDI with ArC, Quarkus REST (formerly RESTEasy Reactive), Hibernate ORM with Panache, config profiles and @ConfigMapping, Dev Services and continuous testing, native executables with GraalVM or Mandrel, and build-time vs run-time initialisation. Load when building, testing or natively compiling a Quarkus application."
when_to_use: "Editing a Quarkus application.properties (%dev, %test, %prod keys) or @ConfigMapping; quarkus dev, Dev UI or continuous testing; BlockingOperationNotAllowedException or vert.x-eventloop-thread blocked warnings; @Blocking, @NonBlocking or @RunOnVirtualThread; Panache entities or repositories; Dev Services containers; @QuarkusTest or @QuarkusIntegrationTest failures; native build errors (reflection, resources, class initialization) or measuring native startup and RSS."
---

# Quarkus 3 services

Quarkus moves framework work to build time: it indexes classes, wires CDI, and generates
bytecode during the build, so start-up does little and native compilation works. Anything that
discovers code reflectively at run time fights that model. Quarkus 3.x runs on Java 17+ (21 for
virtual threads). Property names below are 3.x; one recent rename is called out. Generic Java
test tooling: `java-testing-junit`; build wiring: `java-build-maven-gradle`.

## 1. Project setup

```bash
quarkus create app com.acme:fruits --java=21 \
  --extension='rest-jackson,hibernate-orm-panache,jdbc-postgresql,flyway,hibernate-validator,smallrye-health'
cd fruits
quarkus ext list --installable | grep -i kafka         # discover extensions
quarkus ext add micrometer-registry-prometheus opentelemetry
./mvnw quarkus:add-extension -Dextensions="rest-client-jackson"   # same without the CLI
quarkus dev                                             # or ./mvnw quarkus:dev
```

Dev mode: live reload on the next request, Dev Services containers, Dev UI at
`http://localhost:8080/q/dev-ui` (config editor, beans, endpoints), `r` runs tests, `h` lists keys.
The build imports `io.quarkus.platform:quarkus-bom` and uses `quarkus-maven-plugin` with
`<extensions>true</extensions>` (Gradle: `id("io.quarkus")` plus `enforcedPlatform(...)` of the BOM).

| Need | Extension | Note |
|---|---|---|
| JSON REST server | `quarkus-rest-jackson` | Quarkus REST; never mix with classic `quarkus-resteasy*` |
| REST client | `quarkus-rest-client-jackson` | `@RegisterRestClient` interfaces |
| blocking ORM | `quarkus-hibernate-orm-panache` + `quarkus-jdbc-postgresql` | JDBC on worker or virtual threads |
| reactive ORM | `quarkus-hibernate-reactive-panache` + `quarkus-reactive-pg-client` | Mutiny `Uni`, `@WithTransaction` |
| migrations | `quarkus-flyway` or `quarkus-liquibase` | run at start or as a job |
| resilience | `quarkus-smallrye-fault-tolerance` | `@Timeout`, `@Retry`, `@CircuitBreaker` |
| health, metrics, traces | `quarkus-smallrye-health`, `quarkus-micrometer-registry-prometheus`, `quarkus-opentelemetry` | section 8 |

Prefer a core or Quarkiverse extension over the plain library: the extension does build-time
wiring and native registration that the bare jar does not.

## 2. CDI with ArC

| Scope | Instances | Client proxy | Use |
|---|---|---|---|
| `@ApplicationScoped` | one, created on first method call | yes | default for services; mockable with `@InjectMock` |
| `@Singleton` | one, created on first injection | no | slightly cheaper; cannot be `@InjectMock`ed |
| `@RequestScoped` | per request | yes | request state |
| `@Dependent` | per injection point | no | small helpers, producer default |

```java
@ApplicationScoped
class FruitService {
    private final FruitRepository fruits;
    private final Clock clock;
    FruitService(FruitRepository fruits, Clock clock) { this.fruits = fruits; this.clock = clock; }  // constructor injection
}

class Producers {
    @Produces @Singleton Clock clock() { return Clock.systemUTC(); }
}
```

What breaks under build-time discovery:

- Beans need a bean-defining annotation, and classes from dependency jars are only beans if the
  jar has a Jandex index or is listed via `quarkus.index-dependency.<name>.group-id`/`.artifact-id`.
- Beans reached only programmatically (`CDI.current().select(...)`, `Instance<T>` lookups by
  type name) are removed as unused: add `@Unremovable` or `quarkus.arc.unremovable-types`.
- Private injection points and private observer or producer members force reflection: use
  package-private.
- Run-time classpath scanning (component scan, Reflections) and run-time bytecode generation
  (cglib, ByteBuddy proxies) do not work, and fail outright in native.
- `@ApplicationScoped` beans are lazy: to run code at boot, observe `StartupEvent` or use `@Startup`.
- Interceptors (`@Transactional`, fault tolerance) are bound through generated subclasses; ArC
  documents intercepted self-invocation as a non-standard feature, but private methods are never
  intercepted.

## 3. Quarkus REST endpoints

```java
@Path("/fruits")
public class FruitResource {
    @Inject FruitsConfig config;

    @GET                                                   // blocking signature: worker thread
    public List<Fruit> list(@RestQuery @DefaultValue("0") int page) {
        return Fruit.findAll(Sort.by("name")).page(Page.of(page, config.pageSize())).list();
    }
    @GET @Path("/{id}")
    public Fruit get(@RestPath long id) {
        return Fruit.<Fruit>findByIdOptional(id).orElseThrow(() -> new FruitNotFoundException(id));
    }
    @POST @Transactional
    public RestResponse<Fruit> create(@Valid Fruit fruit) {
        fruit.persist();
        return RestResponse.status(RestResponse.Status.CREATED, fruit);
    }
    @DELETE @Path("/{id}") @Transactional
    public void delete(@RestPath long id) {
        if (!Fruit.deleteById(id)) throw new FruitNotFoundException(id);
    }
}

public class ExceptionMappers {
    @ServerExceptionMapper
    public RestResponse<Problem> notFound(FruitNotFoundException e) {
        return RestResponse.status(RestResponse.Status.NOT_FOUND, new Problem("fruit-not-found", e.getMessage()));
    }
}
```

| Method returns / annotation | Runs on | Rule |
|---|---|---|
| plain object, `void`, `RestResponse<T>` | worker thread | blocking I/O allowed |
| `Uni`, `Multi`, `CompletionStage` | Vert.x event loop | never block; `@Blocking` moves it to a worker |
| blocking signature + `@NonBlocking` | event loop | only for pure CPU-light code |
| blocking signature + `@RunOnVirtualThread` | new virtual thread per request (Java 21+) | bound the DB pool (`quarkus.datasource.jdbc.max-size`); JDK 21-23 pins on `synchronized` I/O |

A blocking call on the event loop throws `BlockingOperationNotAllowedException` (for known
blocking APIs) or logs "Thread vert.x-eventloop-thread-N has been blocked"; move the work, do not
raise the warning threshold. Annotations come from `io.smallrye.common.annotation`.

## 4. Persistence with Hibernate ORM and Panache

```java
@Entity
public class Fruit extends PanacheEntity {                 // active record; Long id generated
    @NotBlank @Column(nullable = false, unique = true) public String name;
    @PositiveOrZero public int calories;
    public static Optional<Fruit> findByName(String name) { return find("name", name).firstResultOptional(); }
}

@ApplicationScoped                                          // repository alternative
public class FruitRepository implements PanacheRepository<Fruit> {
    public List<Fruit> lowCalorie(int max) { return list("calories <= ?1", Sort.by("name"), max); }
}
```

| Choose | When |
|---|---|
| active record (`PanacheEntity`) | small CRUD services; tests mock statics with `PanacheMock` (`quarkus-panache-mock`) |
| repository (`PanacheRepository<T>`, `PanacheRepositoryBase<T, ID>` for non-Long ids) | domain logic kept off entities; `@InjectMock` the repository |

Public fields on Panache entities are rewritten to accessors at build time. Transactions:
`@Transactional` (jakarta) on the resource or service method, or programmatic
`QuarkusTransaction.requiringNew().run(() -> ...)`; `@TestTransaction` rolls back in tests.

```properties
quarkus.datasource.db-kind=postgresql                    # build-time property
quarkus.flyway.migrate-at-start=true
quarkus.hibernate-orm.schema-management.strategy=validate    # 3.23+; older: quarkus.hibernate-orm.database.generation
quarkus.datasource.devservices.image-name=postgres:17-alpine
%prod.quarkus.datasource.jdbc.url=${DB_URL}
%prod.quarkus.datasource.username=${DB_USER}
%prod.quarkus.datasource.password=${DB_PASSWORD}
```

Dev Services: in dev and test, a datasource with no JDBC URL gets a container started
automatically (Docker or Podman required); `quarkus.devservices.enabled=false` turns them off.
Flyway scripts live in `src/main/resources/db/migration` (`V1__init.sql`). Use
`drop-and-create` only for throwaway prototypes; `validate` plus migrations everywhere else.

## 5. Config

```java
@ConfigMapping(prefix = "fruits")
public interface FruitsConfig {
    @WithDefault("20") int pageSize();
    Optional<String> banner();
    Duration cacheTtl();                                    // required: start-up fails if missing
}
```

```properties
fruits.cache-ttl=10m
%dev.fruits.page-size=5
%test.fruits.cache-ttl=1s
```

- Profiles: `dev` (dev mode), `test` (tests), `prod` (packaged default); custom via
  `-Dquarkus.profile=staging` or `QUARKUS_PROFILE`, keys `%staging.` or `application-staging.properties`.
- Precedence: system properties > env vars (`FRUITS_PAGE_SIZE`) > `.env` in the working directory
  > `application.properties`.
- Build-time properties (`quarkus.datasource.db-kind`, extension switches) are frozen into the
  build; changing them at run time has no effect beyond a warning. Dev UI marks them.
- Secrets: never in `application.properties`. Env vars, a git-ignored `.env` for dev only,
  Kubernetes Secrets via `quarkus-kubernetes-config`, or a Vault credentials provider (Quarkiverse).

## 6. Testing

```java
@QuarkusTest                                     // app started once and shared by test classes
class FruitResourceTest {
    @Test
    void createsAndLists() {
        given().contentType(ContentType.JSON).body("""
                {"name":"kiwi","calories":42}
                """)
            .when().post("/fruits")
            .then().statusCode(201).body("id", notNullValue());
        given().when().get("/fruits?page=0")
            .then().statusCode(200).body("name", hasItem("kiwi"));
    }
}

@QuarkusIntegrationTest                           // black box: the built jar, native binary or container
class FruitResourceIT extends FruitResourceTest {}
```

- Artifacts (3.x): `quarkus-junit5`, `quarkus-junit5-mockito` (`@InjectMock` for normal-scoped
  beans), `rest-assured`. Dev Services also serve `@QuarkusTest` and `@QuarkusIntegrationTest`.
- Each distinct `@TestProfile` restarts the application: group tests per profile.
- `@QuarkusIntegrationTest` cannot inject beans; it talks HTTP only. `./mvnw verify` runs it
  against the jar, `./mvnw verify -Dnative` against the native binary.
- Continuous testing: `r` in dev mode, or `quarkus test` for a test-only watch loop; it reruns
  only tests affected by the change.
- Shared database across tests: unique names per test or cleanup in `@AfterEach`.

## 7. Native image

```bash
./mvnw package -Dnative -Dquarkus.native.container-build=true    # no local GraalVM required
./mvnw package -Dnative -Dquarkus.native.container-build=true -Dquarkus.native.builder-image=mandrel
quarkus build --native -Dquarkus.native.container-build=true
./mvnw verify -Dnative                                            # build + ITs against the binary
```

`-Dnative` activates the generated `native` profile (`quarkus.native.enabled=true`; before 3.9
`quarkus.package.type=native`). Mandrel (a GraalVM distribution for Java-only native builds) is
the usual container builder; `graalvm` is the alternative. Budget minutes and several GB of RAM
per build (`quarkus.native.native-image-xmx`); build natively in CI, not on every local change.

| Problem | Symptom | Fix |
|---|---|---|
| reflection on a class Quarkus cannot see | `ClassNotFoundException`, empty JSON, missing fields only in native | `@RegisterForReflection` on own types; `@RegisterForReflection(targets = {Vendor.class})` on a holder class for third-party types |
| resource not embedded | `getResource` returns null in native | `quarkus.native.resources.includes=templates/**,certs/*.pem` |
| state captured at build time | build fails "Detected an instance of Random/SplittableRandom class in the image heap", or a frozen timestamp/env value | initialise lazily or at run time: `quarkus.native.additional-build-args=--initialize-at-run-time=com.acme.Tokens` |
| dynamic proxies, runtime bytecode generation | `UnsupportedFeatureError` | replace the library or find its extension |
| type only behind `Response`/`Object` | serialised as `{}` | return a typed `RestResponse<T>` or register it |

Quarkus initialises most classes at build time, so static initialisers run during the build:
keep them free of clocks, randomness, environment reads, threads and connections.

| Measure | How | Expect (order of magnitude) |
|---|---|---|
| start-up | "started in N s" log line; time until `/q/health/ready` is 200 | JVM ~1 s; native tens of ms |
| RSS after first request | `ps -o rss= -p $PID` (KB) | JVM ~150-250 MB; native ~30-80 MB |
| artifact size | `ls -lh target/*-runner` | native binary ~50-100 MB |
| peak throughput | load test both modes | JVM (JIT) usually wins long-running peaks |

Choose native for scale-to-zero, serverless, CLIs and dense deployments; JVM mode for long-running
throughput-bound services (JDK 24+ AOT cache, JEP 483, narrows the start-up gap).

## 8. Observability

```properties
quarkus.otel.exporter.otlp.endpoint=http://otel-collector:4317
quarkus.otel.traces.sampler=parentbased_traceidratio
quarkus.otel.traces.sampler.arg=0.1
```

```java
@Readiness @ApplicationScoped
class GatewayHealth implements HealthCheck {
    @Inject GatewayClient gateway;
    @Override public HealthCheckResponse call() {
        return HealthCheckResponse.named("gateway").status(gateway.ping()).build();
    }
}
```

- SmallRye Health: `/q/health/live`, `/q/health/ready`, `/q/health/started`; the datasource
  readiness check is automatic. Liveness never checks dependencies.
- Micrometer: `/q/metrics` with the Prometheus registry; HTTP server metrics are automatic;
  custom meters through an injected `MeterRegistry` or `@Counted`/`@Timed`. No ids in tags.
- OpenTelemetry: REST server and client spans automatic; trace ids in logs via the log format
  (`%X{traceId}`); JSON logs with `quarkus-logging-json`.

## 9. Pitfalls

| Symptom | Cause | Fix |
|---|---|---|
| bean "not found" only after build | unused-bean removal or unindexed dependency | `@Unremovable`, Jandex index, `quarkus.index-dependency` |
| `@InjectMock` fails on a bean | `@Singleton` or `@Dependent` (no client proxy) | make it `@ApplicationScoped` |
| requests stall under load | blocking code on the event loop | section 3 table |
| `ContextNotActiveException` | request-scoped bean used off the request thread | pass data explicitly; activate context deliberately |
| config change ignored in prod | build-time property set at run time | rebuild, or use a run-time property |
| tests slow, app restarts | many `@TestProfile` variants | group by profile |
| native works locally, fails in CI | builder image or memory differs | pin `quarkus.native.builder-image`, raise `native-image-xmx` |
| Dev Services fail to start | no Docker/Podman socket | start the runtime, or set the JDBC URL for that profile |

## 10. Worked example: REST + Panache CRUD built to native and measured

1. Create the app with the command in section 1 (`rest-jackson`, `hibernate-orm-panache`,
   `jdbc-postgresql`, `flyway`, `hibernate-validator`, `smallrye-health`).
2. Schema in `src/main/resources/db/migration/V1__fruit.sql` (Hibernate 6+ default sequence:
   `<entity>_seq`, increment 50):

```sql
create sequence fruit_seq start with 1 increment by 50;
create table fruit (id bigint primary key, name varchar(100) not null unique, calories int not null);
```

3. Entity, resource, mapper and `FruitsConfig` from sections 3-5; the properties block from
   section 4 with `schema-management.strategy=validate`, so a mapping that disagrees with the
   migration fails at start.
4. Dev loop: `quarkus dev`, Dev Services start Postgres;
   `curl -s -XPOST localhost:8080/fruits -H 'content-type: application/json' -d '{"name":"kiwi","calories":42}'`
   returns 201; `r` runs `FruitResourceTest`.
5. JVM verification: `./mvnw verify` runs `FruitResourceTest` and `FruitResourceIT` against the jar.
6. Native: `./mvnw verify -Dnative -Dquarkus.native.container-build=true` builds
   `target/fruits-1.0.0-SNAPSHOT-runner` and reruns `FruitResourceIT` against it. A failure here
   but not in step 5 is a native problem (section 7 table), not a logic bug.
7. Measure both modes against the same local database:

```bash
docker run -d --name pg -e POSTGRES_PASSWORD=dev-only -p 5432:5432 postgres:17-alpine
export DB_URL=jdbc:postgresql://localhost:5432/postgres DB_USER=postgres DB_PASSWORD=dev-only
ls -lh target/fruits-1.0.0-SNAPSHOT-runner
./target/fruits-1.0.0-SNAPSHOT-runner & PID=$!          # log: "... native ... started in 0.0XXs"
until curl -sf localhost:8080/q/health/ready >/dev/null; do sleep 0.05; done
curl -s localhost:8080/fruits >/dev/null; ps -o rss= -p $PID; kill $PID
java -jar target/quarkus-app/quarkus-run.jar & PID=$!   # JVM mode, same steps (build it with ./mvnw package)
```

8. Record a table (mode, start-up, RSS after the first request, artifact size, p99 under the same
   load) in the PR. Done when both test runs are green, native start-up and RSS are measured
   rather than assumed, and the decision to ship native or JVM mode cites those numbers.

Related: `java-testing-junit`, `java-build-maven-gradle`, `java-spring-boot`, `java-virtual-threads`, `container-images`, `observability-instrumentation`, hub `java-craft`

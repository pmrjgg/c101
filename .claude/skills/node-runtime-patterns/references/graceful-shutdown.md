# Graceful shutdown for Node HTTP services

Checked on Node 24.22 (run directly with type stripping): readiness flips to 503 during the drain delay,
a 600 ms in-flight request completes, a 5 s request is cut at the 1 s deadline, closers run, process exits.

## Module

```ts
// src/shutdown.ts
import type { Server } from "node:http";
import { once } from "node:events";
import { setTimeout as sleep } from "node:timers/promises";

export interface ShutdownOptions {
  server: Server;
  drainDelayMs: number;      // time for the load balancer to observe readiness failure
  deadlineMs: number;        // in-flight requests get this long after server.close()
  onReadinessChange: (ready: boolean) => void;
  closers: ReadonlyArray<() => Promise<void>>;   // DB pools, worker pools, consumers, log flush
  log?: (msg: string, extra?: Record<string, unknown>) => void;
}

export function installGracefulShutdown(o: ShutdownOptions): void {
  const log = o.log ?? ((m, e) => console.log(JSON.stringify({ msg: m, ...e })));
  let started = false;
  const run = async (signal: NodeJS.Signals) => {
    if (started) return;                       // handlers are `once`: a second signal kills the process
    started = true;
    const t0 = performance.now();
    log("shutdown.start", { signal });
    o.onReadinessChange(false);
    await sleep(o.drainDelayMs);
    o.server.close();                          // stop accepting; idle keep-alive sockets close (Node 19+)
    const hard = setTimeout(() => {
      log("shutdown.deadline", { open: "closing remaining connections" });
      o.server.closeAllConnections();
    }, o.deadlineMs);
    hard.unref();
    await once(o.server, "close");
    clearTimeout(hard);
    const results = await Promise.allSettled(o.closers.map(c => c()));
    const failed = results.filter(r => r.status === "rejected").length;
    log("shutdown.done", { ms: Math.round(performance.now() - t0), failedClosers: failed });
    process.exitCode = failed ? 1 : 0;
    setTimeout(() => process.exit(), 1_000).unref();   // flush stdout, then exit even if a handle leaks
  };
  process.once("SIGTERM", run);
  process.once("SIGINT", run);
}
```

Usage:

```ts
let ready = true;
const server = createServer((req, res) => {
  if (req.url === "/readyz") { res.writeHead(ready ? 200 : 503).end(); return; }
  // ...
});
server.keepAliveTimeout = 65_000;
server.headersTimeout = 66_000;
installGracefulShutdown({
  server,
  drainDelayMs: config.SHUTDOWN_DRAIN_MS,     // 5_000
  deadlineMs: 20_000,
  onReadinessChange: r => { ready = r; },
  closers: [() => pool.destroy(), () => db.end(), () => consumer.close()],
});
```

## Budget

```
drainDelay + deadline + closers + flush  <  terminationGracePeriodSeconds (Kubernetes default 30 s)
5 s        + 20 s     + ~2 s    + 1 s     =  28 s
```

If requests can legitimately run longer than the deadline (uploads, reports), raise
`terminationGracePeriodSeconds` or make the work resumable; do not silently cut it.

## Platform checklist

| Item | Setting |
|---|---|
| signal delivery | exec-form `CMD ["node", "dist/main.js"]`, or `tini`/`--init` as PID 1; avoid `npm start` as PID 1 |
| readiness vs liveness | readiness turns 503 on shutdown; liveness stays 200 until exit (a failing liveness probe restarts the pod mid-drain) |
| preStop hook | optional `sleep 5` preStop instead of `drainDelayMs` when the app cannot delay itself |
| load balancer | idle timeout below `keepAliveTimeout`; deregistration delay at least `drainDelayMs` |
| queue consumers | stop fetching first, finish in-flight messages, then ack/nack and close |
| WebSockets / SSE | send a close frame or final event, then end; clients reconnect to other instances |
| background timers | `.unref()` so they never block exit |

## Testing it

```bash
node src/main.ts &                                   # or the built JS
PID=$!
curl -s "localhost:8080/slow?ms=600" & curl -s "localhost:8080/slow?ms=60000" -w '%{http_code}\n' &
sleep 0.2; kill -TERM "$PID"
curl -s -o /dev/null -w '%{http_code}\n' localhost:8080/readyz     # expect 503 during the drain
wait                                                               # slow finishes, the 60 s request is cut
```

In an automated test, spawn the service with `child_process.spawn`, send `child.kill("SIGTERM")`, and
assert on exit code, logs and the responses received.

## Frameworks

- Fastify: `await app.close()` runs `onClose` hooks; its server timeouts are constructor options.
- Express 5: `const server = app.listen(port)`; use the module above unchanged.
- Hono on `@hono/node-server`: `serve()` returns the Node `Server`; same module.

# Disposable desktop for the desktop-sandbox MCP server (sandboxed computer use).
# Build once with `bin/desktop-sandbox --build` (the only step that needs network).
#
#   BASE            pin by digest for reproducible, reviewed builds, e.g.
#                   --build-arg BASE=debian:bookworm-slim@sha256:<digest>
#   EXTRA_PACKAGES  Debian packages for the apps you want to drive, e.g.
#                   --build-arg EXTRA_PACKAGES="libreoffice-calc firefox-esr"
#
# Runtime hardening comes from the server's `run` flags (no network, read-only root, cap-drop ALL,
# no-new-privileges, unprivileged user, limits); this image adds: no setuid/setgid binaries, no sudo, no
# package manager use at runtime (root filesystem is read-only), X only on a local socket.
ARG BASE=debian:bookworm-slim
FROM ${BASE}

ARG EXTRA_PACKAGES=""
RUN apt-get update \
 && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      xvfb xdotool x11-utils imagemagick openbox tini fonts-dejavu-core x11-apps \
      ${EXTRA_PACKAGES} \
 && rm -rf /var/lib/apt/lists/* /var/cache/apt/* \
 && find / -xdev -type f -perm /6000 -exec chmod a-s {} + \
 && useradd --uid 10001 --create-home --home-dir /home/sandbox --shell /usr/sbin/nologin sandbox \
 && mkdir -p /exchange && chown 10001:10001 /exchange

COPY --chmod=0755 entrypoint.sh /usr/local/bin/sandbox-entrypoint

ENV DISPLAY=:99 HOME=/home/sandbox
USER 10001:10001
WORKDIR /exchange
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/sandbox-entrypoint"]
